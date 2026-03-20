from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, current_app
from flask_login import login_required, current_user
from src.models.models import MenuItem, RecipeItem, Product, ConsumptionLog, User, Supplier, db
from datetime import datetime
from functools import wraps
from werkzeug.utils import secure_filename
import pandas as pd
import io
import os
import uuid

main = Blueprint('main', __name__)

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

# ---> FASE 29: ROTTE PER I FORNITORI <---
@main.route('/suppliers')
@login_required
def suppliers():
    suppliers = Supplier.query.filter_by(user_id=current_user.get_restaurant_id).all()
    return render_template('suppliers.html', suppliers=suppliers)

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

@main.route('/analytics')
@login_required
@owner_required
def analytics():
    logs = ConsumptionLog.query.filter_by(user_id=current_user.id).all()
    total_cost_consumed = 0
    product_stats = {}
    
    for log in logs:
        cost = log.quantity_used * log.product.unit_cost
        total_cost_consumed += cost
        if log.product.name in product_stats:
            product_stats[log.product.name] += log.quantity_used
        else:
            product_stats[log.product.name] = log.quantity_used

    return render_template('analytics.html', total_cost=round(total_cost_consumed, 2), total_orders=len(logs), labels=list(product_stats.keys()), values=list(product_stats.values()))

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
    db.session.add(new_staff)
    db.session.commit()
    flash(f"✅ Account dipendente per {full_name} creato!")
    return redirect(url_for('main.settings'))