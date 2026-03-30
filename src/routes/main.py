from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, current_app
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
import google.generativeai as genai
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
        genai.configure(api_key=api_key)
        
        modello_scelto = None
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                modello_scelto = m.name
                break
                
        if not modello_scelto:
            flash("❌ Errore critico: Nessun modello AI disponibile per la tua API Key.")
            return redirect(url_for('main.recipe', item_id=item_id))

        model = genai.GenerativeModel(modello_scelto)
        response = model.generate_content(prompt)
        
        raw_text = response.text.replace('```json', '').replace('```', '').strip()
        suggested_items = json.loads(raw_text)
        
        RecipeItem.query.filter_by(menu_item_id=item.id).delete()
        
        for ing in suggested_items:
            new_r_item = RecipeItem(menu_item_id=item.id, product_id=int(ing['product_id']), quantity_needed=float(ing['quantity']))
            db.session.add(new_r_item)
            
        db.session.commit()
        flash(f"✨ Magia AI completata! (Modello ufficiale usato: {modello_scelto})")
        
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
    new_budget = request.form.get('budget')
    if new_budget:
        current_user.monthly_budget = float(new_budget)
        db.session.commit()
        flash("Budget Operativo aggiornato con successo! 🎮")
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
    avatar_type = request.form.get('avatar_type')
    
    if avatar_type == 'file':
        if 'avatar_file' in request.files and request.files['avatar_file'].filename != '':
            pic = request.files['avatar_file']
            filename = secure_filename(pic.filename)
            unique_name = str(uuid.uuid4().hex) + "_" + filename
            upload_folder = os.path.join(current_app.root_path, 'static', 'avatars')
            os.makedirs(upload_folder, exist_ok=True)
            pic.save(os.path.join(upload_folder, unique_name))
            current_user.profile_image = unique_name
            db.session.commit()
            flash("Foto profilo personalizzata caricata! 📸")
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