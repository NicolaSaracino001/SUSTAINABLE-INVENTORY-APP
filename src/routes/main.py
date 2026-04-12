from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, current_app, session
from flask_login import login_required, current_user
from src.models.models import MenuItem, RecipeItem, Product, ConsumptionLog, User, Supplier, WasteLog, db
from datetime import datetime
from functools import wraps
from werkzeug.utils import secure_filename
import pandas as pd
import io
import os
import uuid
import json
import time
from google import genai as genai_sdk
from google.genai import types as genai_types
import urllib.parse
import requests

main = Blueprint('main', __name__)

@main.before_request
def check_password_change():
    if current_user.is_authenticated:
        if current_user.must_change_password and request.endpoint not in ['auth.change_password', 'auth.logout', 'static']:
            return redirect(url_for('auth.change_password'))

def owner_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.role != 'owner':
            flash("❌ Accesso negato: Area riservata al Proprietario del locale.")
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@main.route('/dashboard')
@login_required
def dashboard():
    rest_id = current_user.get_restaurant_id
    all_products = Product.query.filter_by(user_id=rest_id).all()
    low_stock_products = [p for p in all_products if p.quantity <= p.min_threshold]
    
    chart_labels = [p.name for p in all_products]
    chart_values = [p.quantity for p in all_products]
    chart_thresholds = [p.min_threshold for p in all_products]
    
    total_inventory_value = sum([p.quantity * p.unit_cost for p in all_products])
    
    if current_user.role == 'owner':
        budget = current_user.monthly_budget
    else:
        boss = User.query.get(current_user.parent_id)
        budget = boss.monthly_budget

    if budget > 0:
        budget_percent = min((total_inventory_value / budget) * 100, 100)
    else:
        budget_percent = 0

    total_logs = ConsumptionLog.query.filter_by(user_id=rest_id).count()
    if total_logs == 0:
        insight = "Fase di Apprendimento: il sistema sta analizzando i dati."
    elif total_logs < 10:
        insight = f"Apprendimento in corso ({total_logs} dati). Servono più vendite per le previsioni."
    else:
        insight = f"Modello Attivo ({total_logs} data points). I trend si stanno stabilizzando."

    return render_template('dashboard.html', 
                           name=current_user.get_restaurant_name, 
                           low_stock=low_stock_products,
                           weather_suggestion=insight,
                           chart_labels=chart_labels,
                           chart_values=chart_values,
                           chart_thresholds=chart_thresholds,
                           total_value=round(total_inventory_value, 2),
                           budget=budget,
                           budget_percent=round(budget_percent, 1))

@main.route('/inventory')
@login_required
def inventory():
    rest_id = current_user.get_restaurant_id
    products = Product.query.filter_by(user_id=rest_id).all()
    suppliers = Supplier.query.filter_by(user_id=rest_id).all()
    return render_template('inventory.html', products=products, suppliers=suppliers)

@main.route('/add_inventory_item', methods=['POST'])
@login_required
def add_inventory_item():
    name = request.form.get('name')
    quantity = float(request.form.get('quantity'))
    unit = request.form.get('unit')
    threshold = float(request.form.get('threshold'))
    cost_str = request.form.get('unit_cost')
    unit_cost = float(cost_str) if cost_str else 0.0
    supplier_id = request.form.get('supplier_id')
    
    new_product = Product(
        name=name, quantity=quantity, unit=unit, 
        min_threshold=threshold, unit_cost=unit_cost, 
        user_id=current_user.get_restaurant_id,
        supplier_id=supplier_id if supplier_id else None
    )
    db.session.add(new_product)
    db.session.commit()
    flash("Prodotto aggiunto al magazzino.")
    return redirect(url_for('main.inventory'))

@main.route('/align_inventory/<int:product_id>', methods=['POST'])
@login_required
def align_inventory(product_id):
    product = Product.query.get_or_404(product_id)
    if product.user_id != current_user.get_restaurant_id:
        flash("❌ Accesso negato.")
        return redirect(url_for('main.inventory'))

    actual_quantity = float(request.form.get('actual_quantity'))

    if actual_quantity < 0:
        flash("❌ Errore: La giacenza non può essere negativa.")
        return redirect(url_for('main.inventory'))

    if actual_quantity < product.quantity:
        wasted_qty = product.quantity - actual_quantity
        cost_lost = wasted_qty * product.unit_cost
        
        waste_entry = WasteLog(
            user_id=current_user.get_restaurant_id,
            product_id=product.id,
            quantity_wasted=wasted_qty,
            cost_lost=cost_lost
        )
        db.session.add(waste_entry)
        flash(f"⚖️ Magazzino allineato! Rilevati {round(wasted_qty, 2)} {product.unit} di scarto per '{product.name}'. (Costo perso: {round(cost_lost, 2)} €)")
    
    elif actual_quantity > product.quantity:
        added_qty = actual_quantity - product.quantity
        flash(f"⚖️ Magazzino allineato! Aggiunti {round(added_qty, 2)} {product.unit} extra di '{product.name}' trovati in giacenza.")
    else:
        flash(f"✅ Nessuna differenza rilevata. I conti di '{product.name}' tornano perfettamente!")

    product.quantity = actual_quantity
    db.session.commit()

    return redirect(url_for('main.inventory'))

# ---> FASE 35: GENERATORE ORDINI AUTOMATICI <---
@main.route('/suppliers')
@login_required
def suppliers():
    rest_id = current_user.get_restaurant_id
    suppliers_list = Supplier.query.filter_by(user_id=rest_id).all()
    
    # 1. Troviamo i prodotti in esaurimento
    low_stock_products = Product.query.filter(
        Product.user_id == rest_id,
        Product.quantity <= Product.min_threshold
    ).all()

    # 2. Raggruppiamo i prodotti per fornitore
    orders_by_supplier = {}
    for p in low_stock_products:
        sup_name = p.supplier.name if p.supplier else "🛒 Fornitore Non Assegnato (Supermercato)"
        sup_contact = p.supplier.contact_info if p.supplier else ""
        
        if sup_name not in orders_by_supplier:
            orders_by_supplier[sup_name] = {'contact': sup_contact, 'items': []}
        
        # Consigliamo di riordinare il doppio della soglia minima
        suggested = (p.min_threshold * 2) - p.quantity
        if suggested <= 0: suggested = 1.0

        orders_by_supplier[sup_name]['items'].append({
            'name': p.name,
            'current': p.quantity,
            'unit': p.unit,
            'suggested': round(suggested, 2)
        })

    # 3. Generiamo il testo formattato per WhatsApp
    for sup_name, data in orders_by_supplier.items():
        testo_wa = f"📦 ORDINE MERCE\nDa: {current_user.get_restaurant_name}\n\nCiao! Ecco la lista dei prodotti da rifornire:\n\n"
        for item in data['items']:
            testo_wa += f"• {item['suggested']} {item['unit']} di {item['name']}\n"
        testo_wa += "\nGrazie per la disponibilità!"
        data['wa_text'] = testo_wa

    return render_template('suppliers.html', suppliers=suppliers_list, auto_orders=orders_by_supplier)

@main.route('/add_supplier', methods=['POST'])
@login_required
def add_supplier():
    name = request.form.get('name')
    contact = request.form.get('contact')
    new_sup = Supplier(name=name, contact_info=contact, user_id=current_user.get_restaurant_id)
    db.session.add(new_sup)
    db.session.commit()
    flash("Fornitore salvato in rubrica con successo! 🚚")
    return redirect(url_for('main.suppliers'))

@main.route('/menu')
@login_required
def menu():
    menu_items = MenuItem.query.filter_by(user_id=current_user.get_restaurant_id).all()
    return render_template('menu.html', menu_items=menu_items)

@main.route('/add_menu_item', methods=['POST'])
@login_required
def add_menu_item():
    name = request.form.get('name')
    price = float(request.form.get('price'))
    new_item = MenuItem(name=name, price=price, user_id=current_user.get_restaurant_id)
    db.session.add(new_item)
    db.session.commit()
    flash("Nuovo piatto creato con successo.")
    return redirect(url_for('main.menu'))

@main.route('/recipe/<int:item_id>')
@login_required
def recipe(item_id):
    item = MenuItem.query.get_or_404(item_id)
    products = Product.query.filter_by(user_id=current_user.get_restaurant_id).all()
    recipe_items = RecipeItem.query.filter_by(menu_item_id=item_id).all()
    return render_template('recipe.html', item=item, products=products, recipe_items=recipe_items)

@main.route('/update_recipe_details/<int:item_id>', methods=['POST'])
@login_required
def update_recipe_details(item_id):
    item = MenuItem.query.get_or_404(item_id)
    if item.user_id != current_user.get_restaurant_id:
        flash("Accesso negato.")
        return redirect(url_for('main.menu'))

    prep_time = request.form.get('prep_time')
    item.prep_time = int(prep_time) if prep_time else None
    item.allergens = request.form.get('allergens')
    item.instructions = request.form.get('instructions')

    if 'image' in request.files:
        pic = request.files['image']
        if pic.filename != '':
            filename = secure_filename(pic.filename)
            unique_name = str(uuid.uuid4().hex) + "_" + filename
            upload_folder = os.path.join(current_app.root_path, 'static', 'recipes_img')
            os.makedirs(upload_folder, exist_ok=True)
            pic.save(os.path.join(upload_folder, unique_name))
            item.image_file = unique_name

    db.session.commit()
    flash("Dettagli del Piatto aggiornati con successo! 👨‍🍳")
    return redirect(url_for('main.recipe', item_id=item.id))

@main.route('/add_recipe_item/<int:item_id>', methods=['POST'])
@login_required
def add_recipe_item(item_id):
    product_id = request.form.get('product_id')
    quantity = float(request.form.get('quantity'))
    new_recipe_item = RecipeItem(menu_item_id=item_id, product_id=product_id, quantity_needed=quantity)
    db.session.add(new_recipe_item)
    db.session.commit()
    flash("Ingrediente collegato alla ricetta.")
    return redirect(url_for('main.recipe', item_id=item_id))

@main.route('/generate_recipe_ai/<int:item_id>', methods=['POST'])
@login_required
def generate_recipe_ai(item_id):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        flash("❌ Errore: Manca la chiave API di Gemini nel file .env!")
        return redirect(url_for('main.recipe', item_id=item_id))

    item = MenuItem.query.get_or_404(item_id)
    products = Product.query.filter_by(user_id=current_user.get_restaurant_id).all()
    
    if not products:
        flash("❌ Il tuo magazzino è vuoto. Aggiungi materie prime prima di usare l'AI.")
        return redirect(url_for('main.recipe', item_id=item_id))

    inventory_list = "\n".join([f"ID: {p.id} | Nome: {p.name} | Unità: {p.unit}" for p in products])
    
    prompt = f"""
    Sei l'Executive Chef di un ristorante e devi creare la distinta base per il piatto: "{item.name}".
    Hai a disposizione SOLO questi ingredienti nel tuo magazzino:
    
    {inventory_list}
    
    Scegli SOLO gli ingredienti strettamente necessari per questo piatto presenti nella lista. 
    Stima una quantità logica per 1 singola porzione, rispettando l'unità di misura indicata (es. se è in 'kg', scrivi 0.1 per 100 grammi).
    
    Devi rispondere ESATTAMENTE E SOLO con un array JSON in questo formato, senza markdown, senza spiegazioni, senza virgolette extra:
    [
        {{"product_id": numero_id, "quantity": quantita_decimale}}
    ]
    """

    try:
        client = genai_sdk.Client(api_key=api_key)
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_mime_type='application/json',
            ),
        )
        raw_text = response.text.replace('```json', '').replace('```', '').strip()
        suggested_items = json.loads(raw_text)

        RecipeItem.query.filter_by(menu_item_id=item.id).delete()
        for ing in suggested_items:
            new_r_item = RecipeItem(
                menu_item_id=item.id,
                product_id=int(ing['product_id']),
                quantity_needed=float(ing['quantity'])
            )
            db.session.add(new_r_item)

        db.session.commit()
        flash("✨ Ricetta AI generata con successo!")

    except Exception as e:
        flash(f"❌ Errore durante la generazione AI: Riprova. Dettaglio: {str(e)}")

    return redirect(url_for('main.recipe', item_id=item_id))

@main.route('/delete_recipe_item/<int:recipe_item_id>', methods=['POST'])
@login_required
def delete_recipe_item(recipe_item_id):
    r_item = RecipeItem.query.get_or_404(recipe_item_id)
    item_id = r_item.menu_item_id
    db.session.delete(r_item)
    db.session.commit()
    flash("Ingrediente rimosso dalla ricetta.")
    return redirect(url_for('main.recipe', item_id=item_id))

@main.route('/sell_item/<int:item_id>', methods=['POST'])
@login_required
def sell_item(item_id):
    recipe_items = RecipeItem.query.filter_by(menu_item_id=item_id).all()
    if not recipe_items:
        flash("Errore: Definisci la ricetta prima di scaricare!")
        return redirect(url_for('main.menu'))
    
    for r_item in recipe_items:
        product = Product.query.get(r_item.product_id)
        if not product or product.quantity < r_item.quantity_needed:
            flash(f"Impossibile registrare l'ordine! Quantità insufficiente.")
            return redirect(url_for('main.menu'))
            
    for r_item in recipe_items:
        product = Product.query.get(r_item.product_id)
        product.quantity -= r_item.quantity_needed
        log_entry = ConsumptionLog(user_id=current_user.get_restaurant_id, product_id=product.id, quantity_used=r_item.quantity_needed)
        db.session.add(log_entry)
        
    db.session.commit()
    flash("Scontrino registrato! Magazzino e log aggiornati.")
    return redirect(url_for('main.menu'))

@main.route('/analytics')
@login_required
@owner_required
def analytics():
    logs = ConsumptionLog.query.filter_by(user_id=current_user.id).all()
    products = Product.query.filter_by(user_id=current_user.id).all()
    wastes = WasteLog.query.filter_by(user_id=current_user.id).all()
    
    # 1. Metriche Base
    total_cost_consumed = sum([log.quantity_used * log.product.unit_cost for log in logs])
    total_waste_cost = sum([w.cost_lost for w in wastes])

    # 2. Dati Grafico 1: Top 5 Consumi (Barre)
    product_stats = {}
    for log in logs:
        product_stats[log.product.name] = product_stats.get(log.product.name, 0) + log.quantity_used
    sorted_stats = sorted(product_stats.items(), key=lambda x: x[1], reverse=True)[:5]
    top_labels = [x[0] for x in sorted_stats]
    top_values = [x[1] for x in sorted_stats]

    # 3. Dati Grafico 2: Valore per Fornitore (Torta)
    supplier_value = {}
    for p in products:
        val = p.quantity * p.unit_cost
        sup_name = p.supplier.name if p.supplier else "Senza Fornitore"
        supplier_value[sup_name] = supplier_value.get(sup_name, 0) + val
    sup_labels = list(supplier_value.keys())
    sup_values = [round(v, 2) for v in supplier_value.values()]

    # 4. Dati Grafico 3: Trend Consumi nel tempo (Linea)
    # Raggruppiamo le ultime 10 operazioni per ID (simulando il tempo)
    recent_logs = ConsumptionLog.query.filter_by(user_id=current_user.id).order_by(ConsumptionLog.id.desc()).limit(15).all()
    trend_labels = [f"Op #{l.id}" for l in reversed(recent_logs)]
    trend_values = [l.quantity_used for l in reversed(recent_logs)]

    # 5. Dati Grafico 4: Salute del Magazzino (Ciambella)
    good_stock = len([p for p in products if p.quantity > p.min_threshold])
    low_stock = len([p for p in products if p.quantity > 0 and p.quantity <= p.min_threshold])
    out_stock = len([p for p in products if p.quantity == 0])
    health_labels = ["In Salute", "Sotto Scorta", "Esauriti"]
    health_values = [good_stock, low_stock, out_stock]

    return render_template('analytics.html', 
                           total_cost=round(total_cost_consumed, 2), total_orders=len(logs), total_waste=round(total_waste_cost, 2),
                           top_labels=top_labels, top_values=top_values,
                           sup_labels=sup_labels, sup_values=sup_values,
                           trend_labels=trend_labels, trend_values=trend_values,
                           health_labels=health_labels, health_values=health_values)

@main.route('/profile')
@login_required
@owner_required
def profile():
    return render_template('profile.html', user=current_user)

@main.route('/update_budget', methods=['POST'])
@login_required
@owner_required
def update_budget():
    new_budget = request.form.get('budget', '').strip()
    if new_budget:
        try:
            budget_value = float(new_budget)
            if budget_value < 0 or budget_value > 10_000_000:
                flash("❌ Valore budget non valido (deve essere tra 0 e 10.000.000).")
                return redirect(url_for('main.profile'))
            current_user.monthly_budget = round(budget_value, 2)
            db.session.commit()
            flash("Budget Operativo aggiornato con successo!")
        except ValueError:
            flash("❌ Inserisci un numero valido per il budget (es. 1500.00).")
    return redirect(url_for('main.profile'))

@main.route('/export_excel')
@login_required
@owner_required
def export_excel():
    products = Product.query.filter_by(user_id=current_user.id).all()
    if not products:
        flash("Il magazzino è vuoto, nessun dato da esportare.")
        return redirect(url_for('main.profile'))
        
    data = {"Prodotto": [p.name for p in products], "Giacenza": [p.quantity for p in products], "Unità": [p.unit for p in products], "Costo": [p.unit_cost for p in products]}
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Report_FoodLoop')
    output.seek(0)
    filename = f"Report_Magazzino_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
    return send_file(output, download_name=filename, as_attachment=True)

@main.route('/settings')
@login_required
@owner_required
def settings():
    staff_members = User.query.filter_by(parent_id=current_user.id).all()
    return render_template('settings.html', staff=staff_members)

@main.route('/add_staff', methods=['POST'])
@login_required
@owner_required
def add_staff():
    full_name = request.form.get('full_name')
    email = request.form.get('email')
    password = request.form.get('password') 
    
    if User.query.filter_by(email=email).first():
        flash("❌ Errore: Questa email è già in uso.")
        return redirect(url_for('main.settings'))
        
    new_staff = User(email=email, full_name=full_name, role='staff', parent_id=current_user.id)
    new_staff.set_password(password)
    new_staff.must_change_password = True 
    
    db.session.add(new_staff)
    db.session.commit()
    flash(f"✅ Account creato! Comunica a {full_name} la password temporanea: dovrà cambiarla al primo accesso.")
    return redirect(url_for('main.settings'))

@main.route('/update_avatar', methods=['POST'])
@login_required
def update_avatar():
    # Whitelist estensioni immagine — blocca upload di file eseguibili
    ALLOWED_AVATAR_EXT = {'jpg', 'jpeg', 'png', 'gif', 'webp'}

    avatar_type = request.form.get('avatar_type')

    if avatar_type == 'file':
        if 'avatar_file' in request.files and request.files['avatar_file'].filename != '':
            pic = request.files['avatar_file']
            filename = secure_filename(pic.filename)
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
            if ext not in ALLOWED_AVATAR_EXT:
                flash("❌ Formato non supportato. Carica un'immagine JPG, PNG, GIF o WEBP.")
                return redirect(url_for('main.profile'))
            unique_name = f"{uuid.uuid4().hex}.{ext}"   # nome completamente anonimo
            upload_folder = os.path.join(current_app.root_path, 'static', 'avatars')
            os.makedirs(upload_folder, exist_ok=True)
            pic.save(os.path.join(upload_folder, unique_name))
            current_user.profile_image = unique_name
            db.session.commit()
            flash("Foto profilo personalizzata caricata!")
        else:
            flash("Nessuna foto selezionata.")
            
    elif avatar_type in ['robot', 'human']:
        # Genera un avatar unico basato sul nome
        safe_name = urllib.parse.quote(current_user.full_name)
        style = "bottts" if avatar_type == 'robot' else "avataaars"
        url = f"https://api.dicebear.com/7.x/{style}/svg?seed={safe_name}&backgroundColor=e2e8f0"
        
        try:
            # Scarica l'immagine e salvala nel magazzino di FoodLoop
            response = requests.get(url)
            if response.status_code == 200:
                unique_name = f"avatar_{current_user.id}_{avatar_type}.svg"
                upload_folder = os.path.join(current_app.root_path, 'static', 'avatars')
                os.makedirs(upload_folder, exist_ok=True)
                with open(os.path.join(upload_folder, unique_name), 'wb') as f:
                    f.write(response.content)
                current_user.profile_image = unique_name
                db.session.commit()
                flash(f"Avatar generato e salvato con successo! 🎨")
        except Exception as e:
            flash("Errore durante la generazione dell'avatar.")

    return redirect(url_for('main.profile'))


# ---> FASE 37: AI INVOICE SCANNER <---

@main.route('/invoice_scanner')
@login_required
def invoice_scanner():
    """Pagina principale: upload form + visualizzazione risultati scan."""
    result_id = session.get('invoice_scan_result_id')
    scan_result = None
    if result_id:
        result_path = os.path.join(current_app.root_path, 'static', 'invoice_tmp', f'result_{result_id}.json')
        if os.path.exists(result_path):
            with open(result_path, 'r') as f:
                scan_result = json.load(f)
    products = Product.query.filter_by(user_id=current_user.get_restaurant_id).all()
    return render_template('invoice_scanner.html', scan_result=scan_result, products=products)


@main.route('/scan_invoice', methods=['POST'])
@login_required
def scan_invoice():
    """Riceve il file, lo manda a Gemini Vision, salva il JSON estratto."""
    import logging

    # --- Logging terminale ---
    logger = logging.getLogger('foodloop.invoice')
    logging.basicConfig(level=logging.INFO, format='[FoodLoop] %(levelname)s: %(message)s')

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        flash("❌ Errore: Manca la chiave API di Gemini nel file .env!")
        return redirect(url_for('main.invoice_scanner'))

    if 'invoice_file' not in request.files or request.files['invoice_file'].filename == '':
        flash("❌ Nessun file selezionato. Carica un'immagine o un PDF della fattura.")
        return redirect(url_for('main.invoice_scanner'))

    file = request.files['invoice_file']
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    mime_map = {
        'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
        'png': 'image/png', 'webp': 'image/webp',
        'pdf': 'application/pdf'
    }
    if ext not in mime_map:
        flash("❌ Formato non supportato. Carica un file JPG, PNG, WEBP o PDF.")
        return redirect(url_for('main.invoice_scanner'))

    mime_type = mime_map[ext]
    is_pdf = ext == 'pdf'

    # Salva file temporaneo
    upload_folder = os.path.join(current_app.root_path, 'static', 'invoice_tmp')
    os.makedirs(upload_folder, exist_ok=True)
    filename = f"inv_{current_user.id}_{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(upload_folder, filename)
    file.save(filepath)
    logger.info(f"File salvato temporaneamente: {filepath} ({mime_type})")

    gemini_file_ref = None   # traccia l'eventuale file caricato su Files API

    try:
        client = genai_sdk.Client(api_key=api_key)

        # Modelli in cascata — prova in ordine senza sprecare quota
        MODELS_TO_TRY = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-2.0-flash-lite']

        # Prompt minimale — meno token = risposta più veloce e stabile
        prompt = (
            "Extract all data from this invoice as pure JSON only. "
            "No markdown fences, no extra text. "
            'Format: {"supplier_name":"...","invoice_date":"YYYY-MM-DD",'
            '"invoice_number":"...","products":['
            '{"name":"...","quantity":0.0,"unit":"...","unit_price":0.0}]} '
            "Use null for unreadable fields. Return ONLY the JSON object."
        )

        # Costruisce le parti del contenuto
        if is_pdf:
            logger.info("Modalità PDF: upload via Files API (nuovo SDK)...")
            gemini_file_ref = client.files.upload(
                path=filepath,
                config=genai_types.UploadFileConfig(mime_type=mime_type)
            )
            logger.info(f"File caricato: {gemini_file_ref.name} | stato: {gemini_file_ref.state}")

            max_wait, waited = 30, 0
            while str(gemini_file_ref.state) in ('FileState.PROCESSING', 'PROCESSING') and waited < max_wait:
                time.sleep(2)
                waited += 2
                gemini_file_ref = client.files.get(name=gemini_file_ref.name)
                logger.info(f"Attesa PDF... {waited}s | stato: {gemini_file_ref.state}")

            if str(gemini_file_ref.state) in ('FileState.FAILED', 'FAILED'):
                flash("❌ Gemini non è riuscito a elaborare il PDF. Prova a convertirlo in immagine JPG.")
                return redirect(url_for('main.invoice_scanner'))

            content_parts = [prompt, gemini_file_ref]

        else:
            logger.info(f"Modalità immagine: invio inline bytes ({mime_type})...")
            with open(filepath, 'rb') as f_img:
                raw_bytes = f_img.read()
            logger.info(f"Dimensione immagine: {len(raw_bytes)} bytes")
            content_parts = [
                prompt,
                genai_types.Part.from_bytes(data=raw_bytes, mime_type=mime_type)
            ]

        # Retry a cascata — prova ogni modello fino al successo
        response = None
        model_name = None
        last_exc = None
        for candidate in MODELS_TO_TRY:
            try:
                logger.info(f"Tentativo con modello: {candidate}")
                response = client.models.generate_content(
                    model=candidate,
                    contents=content_parts,
                    config=genai_types.GenerateContentConfig(
                        http_options=genai_types.HttpOptions(timeout=90000),  # 90s in ms
                    ),
                )
                model_name = candidate
                logger.info(f"Risposta da [{candidate}]. Lunghezza: {len(response.text)} chars")
                logger.info(f"Raw (primi 300): {response.text[:300]}")
                break
            except Exception as exc:
                last_exc = exc
                exc_str = str(exc)
                if any(k in exc_str for k in ('404', 'MODEL_NOT_FOUND', 'not found', 'PERMISSION_DENIED')):
                    logger.warning(f"Modello {candidate} non disponibile, provo il prossimo: {exc_str[:80]}")
                    continue
                raise  # quota, timeout, errori di rete → propagano subito

        if response is None:
            raise last_exc  # tutti i modelli 404

        # Cleanup file PDF su Gemini (best-effort)
        if gemini_file_ref:
            try:
                client.files.delete(name=gemini_file_ref.name)
                logger.info(f"File Gemini eliminato: {gemini_file_ref.name}")
            except Exception as ce:
                logger.warning(f"Impossibile eliminare file Gemini: {ce}")
            gemini_file_ref = None

        raw_text = response.text.replace('```json', '').replace('```', '').strip()
        scan_data = json.loads(raw_text)
        logger.info(f"JSON parsato correttamente. Prodotti trovati: {len(scan_data.get('products', []))}")

        # Salva risultato in file JSON temporaneo
        result_id = uuid.uuid4().hex
        result_path = os.path.join(upload_folder, f'result_{result_id}.json')
        with open(result_path, 'w', encoding='utf-8') as f:
            json.dump(scan_data, f, ensure_ascii=False)

        # Rimuovi eventuale vecchio risultato
        old_result_id = session.get('invoice_scan_result_id')
        if old_result_id:
            old_path = os.path.join(upload_folder, f'result_{old_result_id}.json')
            try:
                os.remove(old_path)
            except Exception:
                pass

        session['invoice_scan_result_id'] = result_id

        n_products = len(scan_data.get('products', []))
        supplier = scan_data.get('supplier_name', 'Fornitore sconosciuto')
        flash(f"✅ Fattura analizzata con {model_name.split('/')[-1]}! Trovati {n_products} prodotti da {supplier}.")

    except json.JSONDecodeError as je:
        raw = response.text if response is not None else 'N/A'
        logger.error(f"JSON decode error: {je}. Raw text: {raw[:200]}")
        flash("❌ Gemini non ha restituito un JSON valido. Riprova con un'immagine più nitida o leggibile.")
    except Exception as e:
        err_str = str(e)
        logger.error(f"Errore scan_invoice: {type(e).__name__}: {err_str}")
        if 'RESOURCE_EXHAUSTED' in err_str or 'quota' in err_str.lower():
            flash("⏳ Quota API esaurita (free tier: 15 req/min). Attendi 30–60 secondi e riprova.")
        elif any(k in err_str for k in ('404', 'MODEL_NOT_FOUND', 'PERMISSION_DENIED')):
            flash("❌ Nessun modello Gemini disponibile per questa API key. Verifica GEMINI_API_KEY nel file .env.")
        elif 'INVALID_ARGUMENT' in err_str:
            flash(f"❌ Argomento non valido inviato a Gemini: {err_str[:120]}")
        elif 'timeout' in err_str.lower() or 'deadline' in err_str.lower():
            flash("⏳ Timeout: Gemini ha impiegato troppo. Riprova con un file più piccolo o immagine JPG.")
        else:
            flash(f"❌ Errore durante l'analisi AI: {type(e).__name__}: {str(e)[:120]}")
    finally:
        # Cleanup file locale
        try:
            os.remove(filepath)
            logger.info(f"File temporaneo locale eliminato: {filepath}")
        except Exception:
            pass
        # Cleanup file Gemini residuo (se l'eccezione è avvenuta prima del delete)
        if gemini_file_ref:
            try:
                client.files.delete(name=gemini_file_ref.name)
            except Exception:
                pass

    return redirect(url_for('main.invoice_scanner'))


@main.route('/clear_invoice_scan')
@login_required
def clear_invoice_scan():
    """Elimina il risultato di scansione corrente dalla sessione."""
    result_id = session.pop('invoice_scan_result_id', None)
    if result_id:
        upload_folder = os.path.join(current_app.root_path, 'static', 'invoice_tmp')
        result_path = os.path.join(upload_folder, f'result_{result_id}.json')
        try:
            os.remove(result_path)
        except Exception:
            pass
    return redirect(url_for('main.invoice_scanner'))


@main.route('/apply_invoice_update', methods=['POST'])
@login_required
def apply_invoice_update():
    """Applica gli aggiornamenti selezionati dall'utente alla tabella Product."""
    result_id = session.pop('invoice_scan_result_id', None)
    if not result_id:
        flash("❌ Nessun risultato di scansione trovato. Ricarica una fattura.")
        return redirect(url_for('main.invoice_scanner'))

    upload_folder = os.path.join(current_app.root_path, 'static', 'invoice_tmp')
    result_path = os.path.join(upload_folder, f'result_{result_id}.json')

    try:
        with open(result_path, 'r', encoding='utf-8') as f:
            scan_data = json.load(f)
    except Exception:
        flash("❌ Dati di scansione non trovati. Ricarica la fattura.")
        return redirect(url_for('main.invoice_scanner'))
    finally:
        try:
            os.remove(result_path)
        except Exception:
            pass

    scanned_products = scan_data.get('products', [])
    selected_indices = request.form.getlist('selected_products')
    rest_id = current_user.get_restaurant_id
    db_products = Product.query.filter_by(user_id=rest_id).all()

    updated_count = 0
    not_found = []

    for idx_str in selected_indices:
        idx = int(idx_str)
        if idx >= len(scanned_products):
            continue

        scanned = scanned_products[idx]
        scanned_name = (scanned.get('name') or '').lower().strip()

        # Match esatto (case-insensitive)
        matched = next((p for p in db_products if p.name.lower().strip() == scanned_name), None)

        # Match parziale se nessun esatto
        if not matched:
            matched = next(
                (p for p in db_products if scanned_name in p.name.lower() or p.name.lower() in scanned_name),
                None
            )

        if matched:
            update_qty = request.form.get(f'update_qty_{idx}') == 'on'
            update_price = request.form.get(f'update_price_{idx}') == 'on'

            if update_qty and scanned.get('quantity') is not None:
                matched.quantity += float(scanned['quantity'])
            if update_price and scanned.get('unit_price') is not None:
                matched.unit_cost = float(scanned['unit_price'])

            updated_count += 1
        else:
            not_found.append(scanned.get('name', '?'))

    db.session.commit()

    if updated_count > 0:
        flash(f"✅ Magazzino aggiornato! {updated_count} prodotti aggiornati dalla fattura.")
    if not_found:
        flash(f"⚠️ Non trovati in magazzino (aggiungi manualmente): {', '.join(not_found)}")
    if updated_count == 0 and not not_found:
        flash("ℹ️ Nessun prodotto selezionato per l'aggiornamento.")

    return redirect(url_for('main.invoice_scanner'))