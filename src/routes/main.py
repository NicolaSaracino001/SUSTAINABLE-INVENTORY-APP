from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
from src.models.models import MenuItem, RecipeItem, Product, ConsumptionLog, db
from datetime import datetime
import pandas as pd
import io

main = Blueprint('main', __name__)

@main.route('/dashboard')
@login_required
def dashboard():
    all_products = Product.query.filter_by(user_id=current_user.id).all()
    low_stock_products = [p for p in all_products if p.quantity <= p.min_threshold]
    
    chart_labels = [p.name for p in all_products]
    chart_values = [p.quantity for p in all_products]
    chart_thresholds = [p.min_threshold for p in all_products]
    
    total_inventory_value = sum([p.quantity * p.unit_cost for p in all_products])
    
    # ---> FASE 25: CALCOLI ARCADE / BUDGET <---
    budget = current_user.monthly_budget
    if budget > 0:
        budget_percent = min((total_inventory_value / budget) * 100, 100) # Max 100% visivo
    else:
        budget_percent = 0

    total_logs = ConsumptionLog.query.filter_by(user_id=current_user.id).count()
    if total_logs == 0:
        insight = "Fase di Apprendimento: il sistema neurale sta analizzando i dati."
    elif total_logs < 10:
        insight = f"Apprendimento in corso ({total_logs} dati registrati). Servono più vendite per le previsioni."
    else:
        insight = f"Modello Attivo ({total_logs} data points). I tuoi trend di consumo si stanno stabilizzando."

    return render_template('dashboard.html', 
                           name=current_user.restaurant_name, 
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
    products = Product.query.filter_by(user_id=current_user.id).all()
    return render_template('inventory.html', products=products)

@main.route('/add_inventory_item', methods=['POST'])
@login_required
def add_inventory_item():
    name = request.form.get('name')
    quantity = float(request.form.get('quantity'))
    unit = request.form.get('unit')
    threshold = float(request.form.get('threshold'))
    cost_str = request.form.get('unit_cost')
    unit_cost = float(cost_str) if cost_str else 0.0
    
    new_product = Product(
        name=name, quantity=quantity, unit=unit, 
        min_threshold=threshold, unit_cost=unit_cost, user_id=current_user.id
    )
    db.session.add(new_product)
    db.session.commit()
    flash("Prodotto aggiunto al magazzino con costo di acquisto registrato.")
    return redirect(url_for('main.inventory'))

@main.route('/menu')
@login_required
def menu():
    menu_items = MenuItem.query.filter_by(user_id=current_user.id).all()
    return render_template('menu.html', menu_items=menu_items)

@main.route('/add_menu_item', methods=['POST'])
@login_required
def add_menu_item():
    name = request.form.get('name')
    price = float(request.form.get('price'))
    new_item = MenuItem(name=name, price=price, user_id=current_user.id)
    db.session.add(new_item)
    db.session.commit()
    flash("Nuovo piatto creato con successo.")
    return redirect(url_for('main.menu'))

@main.route('/recipe/<int:item_id>')
@login_required
def recipe(item_id):
    item = MenuItem.query.get_or_404(item_id)
    products = Product.query.filter_by(user_id=current_user.id).all()
    recipe_items = RecipeItem.query.filter_by(menu_item_id=item_id).all()
    return render_template('recipe.html', item=item, products=products, recipe_items=recipe_items)

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
        log_entry = ConsumptionLog(user_id=current_user.id, product_id=product.id, quantity_used=r_item.quantity_needed)
        db.session.add(log_entry)
        
    db.session.commit()
    flash("Scontrino registrato! Consumi salvati nel dataset storico.")
    return redirect(url_for('main.menu'))

@main.route('/profile')
@login_required
def profile():
    return render_template('profile.html', user=current_user)

# ---> FASE 25: ROTTA PER AGGIORNARE IL BUDGET <---
@main.route('/update_budget', methods=['POST'])
@login_required
def update_budget():
    new_budget = request.form.get('budget')
    if new_budget:
        current_user.monthly_budget = float(new_budget)
        db.session.commit()
        flash("Budget Operativo aggiornato con successo! 🎮")
    return redirect(url_for('main.profile'))

@main.route('/export_excel')
@login_required
def export_excel():
    products = Product.query.filter_by(user_id=current_user.id).all()
    if not products:
        flash("Il magazzino è vuoto, nessun dato da esportare.")
        return redirect(url_for('main.profile'))
        
    data = {
        "Prodotto": [p.name for p in products],
        "Giacenza Attuale": [p.quantity for p in products],
        "Unità di Misura": [p.unit for p in products],
        "Soglia di Allarme": [p.min_threshold for p in products],
        "Costo Unitario (€)": [p.unit_cost for p in products],
        "Valore Totale in Magazzino (€)": [round(p.quantity * p.unit_cost, 2) for p in products]
    }
    
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Report_FoodLoop')
    output.seek(0)
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"Report_Magazzino_{date_str}.xlsx"
    return send_file(output, download_name=filename, as_attachment=True)