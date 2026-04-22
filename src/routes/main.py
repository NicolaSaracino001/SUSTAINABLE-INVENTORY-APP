from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, send_from_directory, current_app, session, jsonify
from flask_login import login_required, current_user
from src.models.models import MenuItem, RecipeItem, Product, ConsumptionLog, User, Supplier, WasteLog, SaleLog, db
from datetime import datetime, timedelta
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


def _upload_dir(subdir: str) -> str:
    """
    Restituisce la directory scrivibile per i file caricati dagli utenti.
    - Vercel / produzione: il filesystem è read-only, quindi usiamo /tmp/foodloop/<subdir>.
    - Locale (development): src/static/<subdir>, così i file sono servibili come static assets.
    La directory viene creata se non esiste.
    """
    if os.environ.get('VERCEL') or os.environ.get('FLASK_ENV') == 'production':
        base = '/tmp/foodloop'
    else:
        base = os.path.join(current_app.root_path, 'static')
    path = os.path.join(base, subdir)
    os.makedirs(path, exist_ok=True)
    return path


@main.route('/uploads/<path:filename>')
@login_required
def serve_upload(filename):
    """
    Serve i file caricati dagli utenti (avatar, immagini ricette, ecc.).
    In produzione (Vercel) i file risiedono in /tmp/foodloop/; in locale in static/.
    """
    if os.environ.get('VERCEL') or os.environ.get('FLASK_ENV') == 'production':
        base = '/tmp/foodloop'
    else:
        base = os.path.join(current_app.root_path, 'static')
    return send_from_directory(base, filename)


def _convert_heic_to_jpeg(heic_path: str) -> str:
    """
    Converte un file HEIC/HEIF in JPEG usando pillow-heif.
    Elimina il file originale e restituisce il percorso del JPEG risultante.
    Solleva ImportError se pillow-heif non è installato.
    """
    import pillow_heif          # noqa: F401 — registra il codec HEIF in Pillow
    from PIL import Image
    pillow_heif.register_heif_opener()

    jpeg_path = heic_path.rsplit('.', 1)[0] + '.jpg'
    with Image.open(heic_path) as img:
        img.convert('RGB').save(jpeg_path, 'JPEG', quality=92)
    os.remove(heic_path)
    return jpeg_path


# Unità che richiedono la conversione g/ml → kg/L al salvataggio della ricetta
_KG_L_UNITS = {
    'kg', 'kilo', 'kilogrammi', 'chilogrammi', 'chilogrammo',
    'l', 'lt', 'litri', 'liter', 'litre', 'litro',
}


def _to_stock_unit(quantity_in_g_or_ml: float, product) -> tuple:
    """
    Converte una quantità inserita in g/ml nell'unità di misura del prodotto a magazzino.

    Se il prodotto è in kg o L → divide per 1000 (es. 250g → 0.250 kg).
    Altrimenti restituisce il valore invariato (pz, g, ml, etc.).

    Returns:
        (quantity_converted, unit_string)
    """
    if product is None:
        return quantity_in_g_or_ml, ''
    unit = (product.unit or '').lower().strip()
    if unit in _KG_L_UNITS:
        return quantity_in_g_or_ml / 1000.0, product.unit
    return quantity_in_g_or_ml, product.unit

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

    # Grafico: mostra al massimo i 25 prodotti con valore di magazzino più alto.
    # Con 200+ prodotti un grafico a 200 barre sarebbe illeggibile e lento.
    chart_products = sorted(all_products, key=lambda p: p.quantity * p.unit_cost, reverse=True)[:25]
    chart_labels = [p.name for p in chart_products]
    chart_values = [round(p.quantity, 4) for p in chart_products]

    # Consumi ultimi 30 giorni per gli stessi prodotti (diverging bar chart)
    from collections import defaultdict
    cutoff_30d = datetime.utcnow() - timedelta(days=30)
    product_ids = [p.id for p in chart_products]
    recent_logs = ConsumptionLog.query.filter(
        ConsumptionLog.user_id == rest_id,
        ConsumptionLog.product_id.in_(product_ids),
        ConsumptionLog.timestamp >= cutoff_30d
    ).all()
    consumption_map = defaultdict(float)
    for log in recent_logs:
        consumption_map[log.product_id] += log.quantity_used
    # Valori negativi: fanno puntare le barre verso il basso nel diverging chart
    chart_consumption = [-round(consumption_map.get(p.id, 0), 4) for p in chart_products]
    
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
                           chart_consumption=chart_consumption,
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
            upload_folder = _upload_dir('recipes_img')
            pic.save(os.path.join(upload_folder, unique_name))
            item.image_file = unique_name

    db.session.commit()
    flash("Dettagli del Piatto aggiornati con successo! 👨‍🍳")
    return redirect(url_for('main.recipe', item_id=item.id))

@main.route('/add_recipe_item/<int:item_id>', methods=['POST'])
@login_required
def add_recipe_item(item_id):
    product_id = request.form.get('product_id')
    quantity   = float(request.form.get('quantity'))

    # L'utente inserisce in g o ml; convertiamo in kg/L se necessario
    # così il DB salva sempre nell'unità del magazzino (es. 30g → 0.030 kg).
    product = Product.query.get(product_id)
    quantity, display_unit = _to_stock_unit(quantity, product)

    new_recipe_item = RecipeItem(menu_item_id=item_id, product_id=product_id, quantity_needed=quantity)
    db.session.add(new_recipe_item)
    db.session.commit()
    flash(f"Ingrediente collegato alla ricetta ({round(quantity, 5)} {display_unit}).")
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

    inventory_list = "\n".join(
        [f"ID: {p.id} | Nome: {p.name} | Unità magazzino: {p.unit}" for p in products]
    )

    prompt = f"""
    Sei l'Executive Chef di un ristorante e devi creare la distinta base per il piatto: "{item.name}".
    Hai a disposizione SOLO questi ingredienti nel tuo magazzino:

    {inventory_list}

    REGOLE OBBLIGATORIE sulle quantità (per 1 singola porzione):
    - Esprimi SEMPRE le dosi in GRAMMI (g) per ingredienti solidi/secchi (es. farina 250, riso 180, sale 5).
    - Esprimi SEMPRE le dosi in MILLILITRI (ml) per i liquidi (es. olio 30, acqua 100, vino 50).
    - Per ingredienti venduti a "pezzi" (pz, unità) usa il numero intero di pezzi (es. uova 2, limoni 1).
    - NON usare kg o L — usa sempre la forma base (g, ml, pz).
    - Stima quantità realistiche per una porzione da ristorante.

    Devi rispondere ESATTAMENTE E SOLO con un array JSON, senza markdown, senza spiegazioni:
    [
        {{"product_id": numero_id, "quantity": quantita_in_g_o_ml_o_pz}}
    ]
    """

    MODELS_TO_TRY = ['gemini-2.0-flash', 'gemini-2.5-flash-lite']
    response  = None
    last_exc  = None
    model_used = None

    try:
        client = genai_sdk.Client(api_key=api_key)

        for candidate in MODELS_TO_TRY:
            try:
                response = client.models.generate_content(
                    model=candidate,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        response_mime_type='application/json',
                    ),
                )
                model_used = candidate
                break
            except Exception as exc:
                last_exc = exc
                exc_str  = str(exc)
                if any(k in exc_str for k in ('404', 'MODEL_NOT_FOUND', 'not found', 'PERMISSION_DENIED')):
                    continue
                if 'RESOURCE_EXHAUSTED' in exc_str or '429' in exc_str:
                    continue
                raise   # errori inattesi propagano subito

        if response is None:
            raise last_exc

        raw_text = response.text.replace('```json', '').replace('```', '').strip()
        suggested_items = json.loads(raw_text)

        RecipeItem.query.filter_by(menu_item_id=item.id).delete()
        for ing in suggested_items:
            pid     = int(ing['product_id'])
            qty_raw = float(ing['quantity'])

            # L'AI restituisce in g/ml → converti in unità del magazzino prima di salvare
            prod = Product.query.get(pid)
            qty_stored, _ = _to_stock_unit(qty_raw, prod)

            new_r_item = RecipeItem(
                menu_item_id=item.id,
                product_id=pid,
                quantity_needed=qty_stored
            )
            db.session.add(new_r_item)

        db.session.commit()
        flash(f"✨ Ricetta AI generata con successo! (modello: {model_used.split('/')[-1]})")

    except Exception as e:
        err_str = str(e)
        if 'RESOURCE_EXHAUSTED' in err_str or '429' in err_str:
            flash("⏳ Quota API esaurita su tutti i modelli disponibili. Riprova tra 30–60 secondi.")
        else:
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
    # Query con lazy='joined' definito nel modello → niente N+1 su log.product
    logs     = ConsumptionLog.query.filter_by(user_id=current_user.id).all()
    products = Product.query.filter_by(user_id=current_user.id).all()
    wastes   = WasteLog.query.filter_by(user_id=current_user.id).all()

    # 1. Metriche Base
    total_cost_consumed = sum(l.quantity_used * l.product.unit_cost for l in logs)
    total_waste_cost    = sum(w.cost_lost for w in wastes)

    # 2. Grafico 1: Top 5 Consumi (Barre) — per costo totale consumato
    product_stats = {}
    for log in logs:
        name = log.product.name
        product_stats[name] = product_stats.get(name, 0) + (log.quantity_used * log.product.unit_cost)
    sorted_stats = sorted(product_stats.items(), key=lambda x: x[1], reverse=True)[:5]
    top_labels = [x[0] for x in sorted_stats]
    top_values = [round(x[1], 2) for x in sorted_stats]

    # 3. Grafico 2: Valore per Fornitore (Torta) — top 6 per leggibilità
    supplier_value = {}
    for p in products:
        val      = p.quantity * p.unit_cost
        sup_name = p.supplier.name if p.supplier else "Senza Fornitore"
        supplier_value[sup_name] = supplier_value.get(sup_name, 0) + val
    sorted_sup = sorted(supplier_value.items(), key=lambda x: x[1], reverse=True)[:6]
    sup_labels = [x[0] for x in sorted_sup]
    sup_values = [round(x[1], 2) for x in sorted_sup]

    # 4. Grafico 3: Trend Consumi mensile negli ultimi 6 mesi (Linea)
    #    Aggrega il costo consumato per mese → grafici con un andamento leggibile
    from collections import defaultdict
    monthly = defaultdict(float)
    for log in logs:
        month_key = log.timestamp.strftime('%b %Y')
        monthly[month_key] += log.quantity_used * log.product.unit_cost

    # Ordina per data e prendi gli ultimi 6 mesi
    def _month_sort_key(s):
        return datetime.strptime(s, '%b %Y')

    sorted_months = sorted(monthly.keys(), key=_month_sort_key)[-6:]
    trend_labels  = sorted_months
    trend_values  = [round(monthly[m], 2) for m in sorted_months]

    # 5. Grafico 4: Salute del Magazzino (Ciambella)
    good_stock = len([p for p in products if p.quantity > p.min_threshold])
    low_stock  = len([p for p in products if 0 < p.quantity <= p.min_threshold])
    out_stock  = len([p for p in products if p.quantity == 0])
    health_labels = ["In Salute", "Sotto Scorta", "Esauriti"]
    health_values = [good_stock, low_stock, out_stock]

    return render_template('analytics.html',
                           total_cost=round(total_cost_consumed, 2),
                           total_orders=len(logs),
                           total_waste=round(total_waste_cost, 2),
                           top_labels=top_labels, top_values=top_values,
                           sup_labels=sup_labels, sup_values=sup_values,
                           trend_labels=trend_labels, trend_values=trend_values,
                           health_labels=health_labels, health_values=health_values)

# ---> FASE 41: AI FORECASTING & BUSINESS INTELLIGENCE <---

@main.route('/api/generate_insights', methods=['POST'])
@login_required
@owner_required
def generate_insights():
    """Chiama Gemini per analizzare i dati del ristorante e restituire insights in JSON."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "config", "message": "Chiave API Gemini non configurata."}), 500

    rest_id = current_user.id
    cutoff = datetime.utcnow() - timedelta(days=30)

    # 1. Prodotti con giacenza sotto soglia
    low_stock = Product.query.filter(
        Product.user_id == rest_id,
        Product.quantity <= Product.min_threshold
    ).order_by(Product.quantity.asc()).limit(10).all()

    # 2. Log consumi ultimi 30 giorni
    recent_logs = ConsumptionLog.query.filter(
        ConsumptionLog.user_id == rest_id,
        ConsumptionLog.timestamp >= cutoff
    ).all()

    # 3. Log sprechi ultimi 30 giorni
    waste_logs = WasteLog.query.filter(
        WasteLog.user_id == rest_id,
        WasteLog.timestamp >= cutoff
    ).order_by(WasteLog.cost_lost.desc()).limit(15).all()

    # Aggregazioni per il prompt
    consumption_by_product = {}
    for log in recent_logs:
        name = log.product.name
        cost = log.quantity_used * log.product.unit_cost
        consumption_by_product[name] = consumption_by_product.get(name, 0) + cost
    top_consumption = sorted(consumption_by_product.items(), key=lambda x: x[1], reverse=True)[:8]

    # Costruzione del riassunto testuale
    low_stock_txt = ", ".join(
        [f"{p.name} (giacenza: {p.quantity} {p.unit}, soglia: {p.min_threshold})" for p in low_stock]
    ) or "Nessun prodotto sotto scorta."

    consumption_txt = ", ".join(
        [f"{name}: €{round(cost, 2)}" for name, cost in top_consumption]
    ) or "Nessun consumo registrato negli ultimi 30 giorni."

    waste_txt = ", ".join(
        [f"{w.product.name}: {w.quantity_wasted} {w.product.unit} (€{round(w.cost_lost, 2)} persi)"
         for w in waste_logs]
    ) or "Nessuno spreco registrato negli ultimi 30 giorni."

    prompt = f"""Sei un consulente esperto di gestione ristoranti. Analizza questi dati reali e fornisci consigli pratici e specifici in italiano.

DATI DEL RISTORANTE "{current_user.get_restaurant_name}" (ultimi 30 giorni):

PRODOTTI SOTTO SCORTA MINIMA:
{low_stock_txt}

TOP CONSUMI PER COSTO (€):
{consumption_txt}

SPRECHI REGISTRATI (allineamenti magazzino):
{waste_txt}

Rispondi SOLO con un oggetto JSON valido, senza markdown, senza spiegazioni. Usa esattamente queste 3 chiavi:
{{
  "low_stock_warnings": ["avviso 1", "avviso 2", "avviso 3"],
  "cost_anomalies": ["anomalia 1", "anomalia 2", "anomalia 3"],
  "waste_reduction_tips": ["consiglio 1", "consiglio 2", "consiglio 3"]
}}

Ogni lista deve contenere da 2 a 4 elementi. Ogni elemento è una stringa concisa e azionabile (max 120 caratteri). Sii specifico con i nomi dei prodotti dai dati forniti."""

    MODELS_TO_TRY = ['gemini-2.0-flash', 'gemini-2.5-flash-lite']
    response = None
    last_exc = None
    quota_exhausted = False

    try:
        client = genai_sdk.Client(api_key=api_key)

        for candidate in MODELS_TO_TRY:
            try:
                response = client.models.generate_content(
                    model=candidate,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        response_mime_type='application/json',
                        http_options=genai_types.HttpOptions(timeout=45000),
                    ),
                )
                break
            except Exception as exc:
                last_exc = exc
                exc_str = str(exc)
                if 'RESOURCE_EXHAUSTED' in exc_str or '429' in exc_str:
                    quota_exhausted = True
                    continue
                if any(k in exc_str for k in ('404', 'MODEL_NOT_FOUND', 'not found', 'PERMISSION_DENIED')):
                    continue
                raise

        if response is None:
            if quota_exhausted:
                return jsonify({"error": "quota", "message": "L'AI sta elaborando troppi dati, riprova tra qualche istante."}), 429
            raise last_exc

        raw_text = response.text.replace('```json', '').replace('```', '').strip()
        insights = json.loads(raw_text)

        # Validazione minima delle chiavi attese
        for key in ('low_stock_warnings', 'cost_anomalies', 'waste_reduction_tips'):
            if key not in insights or not isinstance(insights[key], list):
                insights[key] = ["Dati insufficienti per questa categoria."]

        return jsonify(insights)

    except json.JSONDecodeError:
        return jsonify({"error": "parse", "message": "Risposta AI non valida. Riprova."}), 500
    except Exception as e:
        err_str = str(e)
        if 'RESOURCE_EXHAUSTED' in err_str or '429' in err_str:
            return jsonify({"error": "quota", "message": "L'AI sta elaborando troppi dati, riprova tra qualche istante."}), 429
        return jsonify({"error": "generic", "message": f"Errore AI: {type(e).__name__}"}), 500


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
    import cloudinary.uploader

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
            try:
                result = cloudinary.uploader.upload(
                    pic,
                    folder='foodloop/avatars',
                    public_id=f"user_{current_user.id}_{uuid.uuid4().hex[:8]}",
                    overwrite=True,
                    resource_type='image',
                )
                current_user.profile_image = result['secure_url']
                db.session.commit()
                flash("Foto profilo personalizzata caricata!")
            except Exception as e:
                flash(f"❌ Errore durante l'upload dell'immagine: {type(e).__name__}")
        else:
            flash("Nessuna foto selezionata.")

    elif avatar_type in ['robot', 'human']:
        # Salva direttamente l'URL pubblico DiceBear — nessun file locale
        safe_name = urllib.parse.quote(current_user.full_name)
        style = "bottts" if avatar_type == 'robot' else "avataaars"
        avatar_url = f"https://api.dicebear.com/7.x/{style}/svg?seed={safe_name}&backgroundColor=e2e8f0"
        current_user.profile_image = avatar_url
        db.session.commit()
        flash("Avatar generato e salvato con successo!")

    return redirect(url_for('main.profile'))


# ---> FASE 37: AI INVOICE SCANNER <---

@main.route('/invoice_scanner')
@login_required
def invoice_scanner():
    """Pagina principale: upload form + visualizzazione risultati scan."""
    result_id = session.get('invoice_scan_result_id')
    scan_result = None
    if result_id:
        result_path = os.path.join(_upload_dir('invoice_tmp'), f'result_{result_id}.json')
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

    # --- Logging terminale (verbose) ---
    logger = logging.getLogger('foodloop.invoice')
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('[FoodLoop] %(levelname)s: %(message)s'))
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY non trovata nelle variabili di ambiente!")
        flash("❌ Errore: Manca la chiave API di Gemini nel file .env!")
        return redirect(url_for('main.invoice_scanner'))
    masked_key = api_key[:6] + "..." + api_key[-4:]
    logger.debug(f"GEMINI_API_KEY trovata: {masked_key}")

    if 'invoice_file' not in request.files or request.files['invoice_file'].filename == '':
        flash("❌ Nessun file selezionato. Carica un'immagine o un PDF della fattura.")
        return redirect(url_for('main.invoice_scanner'))

    file = request.files['invoice_file']
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    mime_map = {
        'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
        'png': 'image/png', 'webp': 'image/webp',
        'pdf': 'application/pdf',
        'heic': 'image/heic', 'heif': 'image/heic',   # convertiti subito dopo il salvataggio
    }
    if ext not in mime_map:
        flash("❌ Formato non supportato. Carica un file JPG, PNG, WEBP, HEIC o PDF.")
        return redirect(url_for('main.invoice_scanner'))

    mime_type = mime_map[ext]
    is_pdf = ext == 'pdf'

    # Salva file temporaneo
    upload_folder = _upload_dir('invoice_tmp')
    filename = f"inv_{current_user.id}_{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(upload_folder, filename)
    file.save(filepath)
    logger.info(f"File salvato temporaneamente: {filepath} ({mime_type})")

    # ── Conversione HEIC → JPEG (foto iPhone) ─────────────────────────────────
    if ext in ('heic', 'heif'):
        try:
            filepath  = _convert_heic_to_jpeg(filepath)
            mime_type = 'image/jpeg'
            ext       = 'jpg'
            logger.info(f"File HEIC convertito in JPEG: {filepath}")
        except Exception as heic_err:
            try:
                os.remove(filepath)
            except Exception:
                pass
            logger.error(f"Conversione HEIC fallita: {heic_err}")
            flash("❌ Impossibile convertire il file HEIC. Assicurati che pillow-heif sia installato.")
            return redirect(url_for('main.invoice_scanner'))

    gemini_file_ref = None   # traccia l'eventuale file caricato su Files API

    try:
        client = genai_sdk.Client(api_key=api_key)

        # Cascata: gemini-2.0-flash è il target principale (multimodale, veloce, free tier).
        # gemini-2.5-flash-lite come failover su pool di quota separata.
        MODELS_TO_TRY = ['gemini-2.0-flash', 'gemini-2.5-flash-lite']

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
                logger.error(f"[{candidate}] Errore Google API — {type(exc).__name__}: {exc_str}")
                if any(k in exc_str for k in ('404', 'MODEL_NOT_FOUND', 'not found', 'PERMISSION_DENIED')):
                    logger.warning(f"Modello {candidate} non disponibile, provo il prossimo.")
                    continue
                if 'RESOURCE_EXHAUSTED' in exc_str or '429' in exc_str:
                    logger.warning(f"Quota esaurita per {candidate}, provo il prossimo nella cascata.")
                    continue
                raise  # timeout, errori di rete, argomenti invalidi → propagano subito

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

        # Salva risultato JSON temporaneo nella stessa directory del file caricato
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
        import traceback
        err_str = str(e)
        logger.error("=" * 60)
        logger.error(f"ERRORE SCAN_INVOICE — {type(e).__name__}")
        logger.error(f"Messaggio completo Google: {err_str}")
        logger.error("Traceback completo:")
        logger.error(traceback.format_exc())
        logger.error("=" * 60)
        if 'RESOURCE_EXHAUSTED' in err_str or 'quota' in err_str.lower():
            flash("⏳ Quota API esaurita (free tier: 15 req/min). Attendi 30–60 secondi e riprova.")
        elif 'API_KEY_INVALID' in err_str:
            flash("❌ Chiave API Gemini non valida. Verifica GEMINI_API_KEY nel file .env.")
        elif any(k in err_str for k in ('404', 'MODEL_NOT_FOUND', 'PERMISSION_DENIED')):
            flash("❌ Nessun modello Gemini disponibile per questa API key. Verifica GEMINI_API_KEY nel file .env.")
        elif 'INVALID_ARGUMENT' in err_str:
            flash(f"❌ Argomento non valido inviato a Gemini: {err_str[:150]}")
        elif 'timeout' in err_str.lower() or 'deadline' in err_str.lower():
            flash("⏳ Timeout: Gemini ha impiegato troppo. Riprova con un file più piccolo o immagine JPG.")
        else:
            flash(f"❌ Errore durante l'analisi AI: {type(e).__name__}: {str(e)[:150]}")
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
        result_path = os.path.join(_upload_dir('invoice_tmp'), f'result_{result_id}.json')
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

    upload_folder = _upload_dir('invoice_tmp')
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


# ══════════════════════════════════════════════════════════════════════════════
# FASE 42: SALES & INVENTORY OFFLOADING — Scarico Automatizzato
# ══════════════════════════════════════════════════════════════════════════════

import logging as _logging

_sale_logger = _logging.getLogger('foodloop.sales')


def process_sale(user_id, sold_items_list, source='manual'):
    """
    Scarica il magazzino in base ai piatti venduti usando la Distinta Base (RecipeItem).

    Args:
        user_id          : ID del ristorante (owner)
        sold_items_list  : lista di dict [{"menu_item_id": int, "portions": float}, ...]
        source           : causale — 'receipt_scan' | 'manual'

    Returns:
        SaleLog appena creato e committato

    Raises:
        ValueError  : se scorte insufficienti per un prodotto
    """
    _sale_logger.info(
        f"[process_sale] START — user={user_id} source={source} items={sold_items_list}"
    )

    total_portions = sum(float(i.get('portions', 1)) for i in sold_items_list)

    # ── Pre-check: verifica disponibilità prima di toccare qualsiasi riga ─────
    for item_data in sold_items_list:
        menu_item = MenuItem.query.get(item_data['menu_item_id'])
        if not menu_item:
            _sale_logger.warning(f"  MenuItem ID {item_data['menu_item_id']} non trovato — saltato")
            continue

        portions     = float(item_data.get('portions', 1))
        recipe_items = RecipeItem.query.filter_by(menu_item_id=menu_item.id).all()
        if not recipe_items:
            _sale_logger.warning(f"  '{menu_item.name}' senza ricetta — saltato nel pre-check")
            continue

        for r_item in recipe_items:
            product = Product.query.get(r_item.product_id)
            if not product or product.user_id != user_id:
                continue
            # quantity_needed è già in unità del magazzino (conversione avviene al salvataggio)
            needed = r_item.quantity_needed * portions
            if product.quantity < needed:
                raise ValueError(
                    f"Scorte insufficienti per '{product.name}': "
                    f"disponibile {round(product.quantity, 4)} {product.unit}, "
                    f"richiesto {round(needed, 4)} {product.unit} "
                    f"per '{menu_item.name}' x{portions}"
                )

    # ── Crea SaleLog ──────────────────────────────────────────────────────────
    sale_log = SaleLog(
        user_id=user_id,
        total_items=int(total_portions),
        source=source
    )
    db.session.add(sale_log)
    db.session.flush()   # ottieni sale_log.id prima del commit
    _sale_logger.info(f"  SaleLog creato (id={sale_log.id})")

    # ── Scarico effettivo ─────────────────────────────────────────────────────
    deducted_count = 0
    for item_data in sold_items_list:
        menu_item = MenuItem.query.get(item_data['menu_item_id'])
        if not menu_item:
            continue

        portions     = float(item_data.get('portions', 1))
        recipe_items = RecipeItem.query.filter_by(menu_item_id=menu_item.id).all()

        if not recipe_items:
            _sale_logger.warning(f"  '{menu_item.name}' senza ricetta — nessuno scarico")
            continue

        for r_item in recipe_items:
            product = Product.query.get(r_item.product_id)
            if not product or product.user_id != user_id:
                continue

            # quantity_needed è già in unità del magazzino — moltiplicazione diretta
            qty_used = r_item.quantity_needed * portions
            product.quantity = max(0.0, product.quantity - qty_used)

            log_entry = ConsumptionLog(
                user_id=user_id,
                product_id=product.id,
                quantity_used=qty_used,
                notes=f"Vendita: {menu_item.name} x{int(portions)} [Sale #{sale_log.id}]"
            )
            db.session.add(log_entry)
            deducted_count += 1
            _sale_logger.info(
                f"  Scaricato: '{product.name}' -{round(qty_used, 6)} {product.unit} "
                f"← '{menu_item.name}' x{portions}  (giacenza ora: {round(product.quantity, 6)})"
            )

    db.session.commit()
    _sale_logger.info(
        f"[process_sale] DONE — SaleLog#{sale_log.id}  "
        f"{deducted_count} ConsumptionLog scritti"
    )
    return sale_log


# ── Pagina principale Chiusura Cassa ─────────────────────────────────────────

@main.route('/sales_offload')
@login_required
def sales_offload():
    """Pagina Chiusura Cassa: gestione menu + scanner scontrini."""
    rest_id    = current_user.get_restaurant_id
    menu_items = MenuItem.query.filter_by(user_id=rest_id).all()
    products   = Product.query.filter_by(user_id=rest_id).all()

    pending_sale = None
    result_id    = session.get('sale_scan_result_id')
    if result_id:
        result_path = os.path.join(_upload_dir('sale_tmp'), f'result_{result_id}.json')
        if os.path.exists(result_path):
            with open(result_path, 'r', encoding='utf-8') as f:
                pending_sale = json.load(f)

    return render_template(
        'sales_offload.html',
        menu_items=menu_items,
        products=products,
        pending_sale=pending_sale
    )


# ── AI Receipt Scanner ────────────────────────────────────────────────────────

@main.route('/api/scan_receipt', methods=['POST'])
@login_required
def scan_receipt():
    """
    Riceve l'immagine dello scontrino, usa la cascata Gemini
    (gemini-2.0-flash → failover gemini-2.5-flash-lite su quota 429),
    estrae la lista piatti e salva in sessione per la conferma a due step.
    """
    logger = _logging.getLogger('foodloop.receipt')
    if not logger.handlers:
        handler = _logging.StreamHandler()
        handler.setFormatter(_logging.Formatter('[FoodLoop] %(levelname)s: %(message)s'))
        logger.addHandler(handler)
    logger.setLevel(_logging.DEBUG)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY non trovata!")
        flash("❌ Manca la chiave API Gemini nel file .env!")
        return redirect(url_for('main.sales_offload'))

    masked = api_key[:6] + "..." + api_key[-4:]
    logger.debug(f"GEMINI_API_KEY trovata: {masked}")

    if 'receipt_file' not in request.files or request.files['receipt_file'].filename == '':
        flash("❌ Nessun file selezionato. Carica un'immagine dello scontrino.")
        return redirect(url_for('main.sales_offload'))

    file     = request.files['receipt_file']
    ext      = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    mime_map = {
        'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
        'png': 'image/png', 'webp': 'image/webp',
        'pdf': 'application/pdf',
        'heic': 'image/heic', 'heif': 'image/heic',   # convertiti subito dopo il salvataggio
    }
    if ext not in mime_map:
        flash("❌ Formato non supportato. Carica JPG, PNG, WEBP, HEIC o PDF.")
        return redirect(url_for('main.sales_offload'))

    mime_type = mime_map[ext]
    is_pdf    = ext == 'pdf'

    tmp_folder = _upload_dir('sale_tmp')
    filename = f"rec_{current_user.id}_{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(tmp_folder, filename)
    file.save(filepath)
    logger.info(f"File scontrino salvato: {filepath} ({mime_type})")

    # ── Conversione HEIC → JPEG (foto iPhone) ─────────────────────────────────
    if ext in ('heic', 'heif'):
        try:
            filepath  = _convert_heic_to_jpeg(filepath)
            mime_type = 'image/jpeg'
            ext       = 'jpg'
            logger.info(f"File HEIC convertito in JPEG: {filepath}")
        except Exception as heic_err:
            try:
                os.remove(filepath)
            except Exception:
                pass
            logger.error(f"Conversione HEIC fallita: {heic_err}")
            flash("❌ Impossibile convertire il file HEIC. Assicurati che pillow-heif sia installato.")
            return redirect(url_for('main.sales_offload'))

    gemini_file_ref = None
    response        = None

    try:
        client        = genai_sdk.Client(api_key=api_key)
        MODELS_TO_TRY = ['gemini-2.0-flash', 'gemini-2.5-flash-lite']

        prompt = (
            "You are a restaurant POS system. Extract all dishes/items and their quantities "
            "from this end-of-day receipt or sales summary. "
            "Return ONLY a pure JSON array. No markdown, no extra text. "
            'Format: [{"name": "dish name", "quantity": number}] '
            "If quantity is not readable, use 1. Return ONLY the JSON array."
        )

        if is_pdf:
            logger.info("Modalità PDF: upload via Files API...")
            gemini_file_ref = client.files.upload(
                path=filepath,
                config=genai_types.UploadFileConfig(mime_type=mime_type)
            )
            max_wait, waited = 30, 0
            while str(gemini_file_ref.state) in ('FileState.PROCESSING', 'PROCESSING') and waited < max_wait:
                time.sleep(2)
                waited += 2
                gemini_file_ref = client.files.get(name=gemini_file_ref.name)
                logger.info(f"Attesa PDF... {waited}s | stato: {gemini_file_ref.state}")
            if str(gemini_file_ref.state) in ('FileState.FAILED', 'FAILED'):
                flash("❌ Gemini non è riuscito a elaborare il PDF.")
                return redirect(url_for('main.sales_offload'))
            content_parts = [prompt, gemini_file_ref]
        else:
            with open(filepath, 'rb') as f_img:
                raw_bytes = f_img.read()
            logger.info(f"Immagine: {len(raw_bytes)} bytes — invio inline")
            content_parts = [
                prompt,
                genai_types.Part.from_bytes(data=raw_bytes, mime_type=mime_type)
            ]

        # ── Cascata modelli ────────────────────────────────────────────────────
        model_name = None
        last_exc   = None
        for candidate in MODELS_TO_TRY:
            try:
                logger.info(f"Tentativo con modello: {candidate}")
                response = client.models.generate_content(
                    model=candidate,
                    contents=content_parts,
                    config=genai_types.GenerateContentConfig(
                        http_options=genai_types.HttpOptions(timeout=90000),
                    ),
                )
                model_name = candidate
                logger.info(f"Risposta da [{candidate}]. Lunghezza: {len(response.text)} chars")
                logger.debug(f"Raw (primi 300): {response.text[:300]}")
                break
            except Exception as exc:
                last_exc = exc
                exc_str  = str(exc)
                logger.error(f"[{candidate}] Errore: {type(exc).__name__}: {exc_str}")
                if any(k in exc_str for k in ('404', 'MODEL_NOT_FOUND', 'not found', 'PERMISSION_DENIED')):
                    logger.warning(f"Modello {candidate} non disponibile, provo il prossimo.")
                    continue
                if 'RESOURCE_EXHAUSTED' in exc_str or '429' in exc_str:
                    logger.warning(f"Quota esaurita per {candidate}, failover.")
                    continue
                raise

        if response is None:
            raise last_exc

        # Cleanup file Gemini
        if gemini_file_ref:
            try:
                client.files.delete(name=gemini_file_ref.name)
                logger.info(f"File Gemini eliminato: {gemini_file_ref.name}")
            except Exception as ce:
                logger.warning(f"Impossibile eliminare file Gemini: {ce}")
            gemini_file_ref = None

        raw_text = response.text.replace('```json', '').replace('```', '').strip()
        ai_items = json.loads(raw_text)
        logger.info(f"JSON parsato. Voci dallo scontrino: {len(ai_items)}")

        # ── Matching AI names → MenuItem ──────────────────────────────────────
        rest_id    = current_user.get_restaurant_id
        menu_items = MenuItem.query.filter_by(user_id=rest_id).all()

        matched_items   = []
        unmatched_names = []

        for ai_item in ai_items:
            ai_name  = (ai_item.get('name') or '').lower().strip()
            portions = float(ai_item.get('quantity', 1))
            if not ai_name:
                continue

            found = next(
                (m for m in menu_items if m.name.lower().strip() == ai_name), None
            )
            if not found:
                found = next(
                    (m for m in menu_items
                     if ai_name in m.name.lower() or m.name.lower() in ai_name),
                    None
                )

            if found:
                recipe_items = RecipeItem.query.filter_by(menu_item_id=found.id).all()
                deductions   = []
                for r in recipe_items:
                    prod = Product.query.get(r.product_id)
                    if prod and prod.user_id == rest_id:
                        deductions.append({
                            'product_id':      prod.id,
                            'product_name':    prod.name,
                            'unit':            prod.unit,
                            'qty_per_portion': r.quantity_needed,
                            'total_qty':       round(r.quantity_needed * portions, 4),
                            'current_stock':   round(prod.quantity, 4),
                        })

                matched_items.append({
                    'menu_item_id':   found.id,
                    'menu_item_name': found.name,
                    'portions':       portions,
                    'has_recipe':     len(recipe_items) > 0,
                    'deductions':     deductions,
                })
                logger.info(f"  Match: '{ai_item.get('name')}' → '{found.name}' x{portions}")
            else:
                unmatched_names.append(ai_item.get('name', '?'))
                logger.warning(f"  No match: '{ai_item.get('name')}'")

        # ── Salva pending sale ────────────────────────────────────────────────
        pending = {
            'source':          'receipt_scan',
            'scan_model':      model_name,
            'raw_items':       ai_items,
            'matched_items':   matched_items,
            'unmatched_names': unmatched_names,
        }
        result_id   = uuid.uuid4().hex
        result_path = os.path.join(tmp_folder, f'result_{result_id}.json')
        with open(result_path, 'w', encoding='utf-8') as f:
            json.dump(pending, f, ensure_ascii=False)

        old_id = session.get('sale_scan_result_id')
        if old_id:
            old_path = os.path.join(tmp_folder, f'result_{old_id}.json')
            try:
                os.remove(old_path)
            except Exception:
                pass

        session['sale_scan_result_id'] = result_id

        n_matched   = len(matched_items)
        n_unmatched = len(unmatched_names)
        flash(
            f"✅ Scontrino analizzato con {model_name.split('/')[-1]}! "
            f"{n_matched} piatti riconosciuti"
            + (f", {n_unmatched} non trovati nel menu." if n_unmatched else ".")
        )

    except json.JSONDecodeError as je:
        raw = response.text if response else 'N/A'
        logger.error(f"JSON decode error: {je}. Raw: {raw[:200]}")
        flash("❌ Gemini non ha restituito JSON valido. Riprova con un'immagine più nitida.")
    except Exception as e:
        import traceback as _tb
        err_str = str(e)
        logger.error("=" * 60)
        logger.error(f"ERRORE SCAN_RECEIPT — {type(e).__name__}: {err_str}")
        logger.error(_tb.format_exc())
        logger.error("=" * 60)
        if 'RESOURCE_EXHAUSTED' in err_str or '429' in err_str:
            flash("⏳ Quota API esaurita. Attendi 30–60 secondi e riprova.")
        elif 'API_KEY_INVALID' in err_str:
            flash("❌ Chiave API Gemini non valida.")
        elif any(k in err_str for k in ('404', 'MODEL_NOT_FOUND', 'PERMISSION_DENIED')):
            flash("❌ Nessun modello Gemini disponibile per questa API key.")
        elif 'timeout' in err_str.lower():
            flash("⏳ Timeout Gemini. Riprova con un'immagine JPG più piccola.")
        else:
            flash(f"❌ Errore analisi AI: {type(e).__name__}: {str(e)[:150]}")
    finally:
        try:
            os.remove(filepath)
            logger.info(f"File temporaneo eliminato: {filepath}")
        except Exception:
            pass
        if gemini_file_ref:
            try:
                client.files.delete(name=gemini_file_ref.name)
            except Exception:
                pass

    return redirect(url_for('main.sales_offload'))


# ── Conferma Scarico ──────────────────────────────────────────────────────────

@main.route('/confirm_sale', methods=['POST'])
@login_required
def confirm_sale():
    """
    Legge la vendita in attesa (receipt_scan) dalla sessione
    oppure riceve la lista manuale dal form, poi chiama process_sale().
    """
    logger  = _logging.getLogger('foodloop.sales')
    rest_id = current_user.get_restaurant_id
    source  = request.form.get('source', 'manual')

    if source == 'receipt_scan':
        result_id = session.pop('sale_scan_result_id', None)
        if not result_id:
            flash("❌ Nessuna vendita in attesa trovata.")
            return redirect(url_for('main.sales_offload'))

        result_path = os.path.join(_upload_dir('sale_tmp'), f'result_{result_id}.json')
        try:
            with open(result_path, 'r', encoding='utf-8') as f:
                pending = json.load(f)
        except Exception:
            flash("❌ Dati di vendita scaduti. Ricarica lo scontrino.")
            return redirect(url_for('main.sales_offload'))
        finally:
            try:
                os.remove(result_path)
            except Exception:
                pass

        sold_items_list = [
            {'menu_item_id': item['menu_item_id'], 'portions': item['portions']}
            for item in pending.get('matched_items', [])
            if item.get('has_recipe')
        ]
    else:
        item_ids        = request.form.getlist('menu_item_id')
        portions_list   = request.form.getlist('portions')
        sold_items_list = []
        for mid, qty in zip(item_ids, portions_list):
            try:
                q = float(qty)
                if q > 0:
                    sold_items_list.append({'menu_item_id': int(mid), 'portions': q})
            except (ValueError, TypeError):
                pass

    if not sold_items_list:
        flash("⚠️ Nessun piatto con ricetta definita — nessuno scarico eseguito.")
        return redirect(url_for('main.sales_offload'))

    try:
        sale_log = process_sale(rest_id, sold_items_list, source=source)
        total    = sum(i['portions'] for i in sold_items_list)
        flash(
            f"✅ Scarico completato! {int(total)} porzioni registrate. "
            f"(SaleLog #{sale_log.id})"
        )
    except ValueError as ve:
        flash(f"❌ Impossibile completare lo scarico: {ve}")
    except Exception as e:
        logger.error(f"Errore confirm_sale: {e}", exc_info=True)
        flash(f"❌ Errore interno durante lo scarico: {type(e).__name__}")

    return redirect(url_for('main.sales_offload'))


@main.route('/clear_sale_scan')
@login_required
def clear_sale_scan():
    """Elimina la vendita in attesa dalla sessione."""
    result_id = session.pop('sale_scan_result_id', None)
    if result_id:
        result_path = os.path.join(_upload_dir('sale_tmp'), f'result_{result_id}.json')
        try:
            os.remove(result_path)
        except Exception:
            pass
    flash("Analisi scontrino annullata.")
    return redirect(url_for('main.sales_offload'))