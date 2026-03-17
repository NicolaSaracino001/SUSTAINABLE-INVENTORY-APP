from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from src.models.models import MenuItem, RecipeItem, Product
from src.app import db

main = Blueprint('main', __name__)

@main.route('/dashboard')
@login_required
def dashboard():
    # Recuperiamo i prodotti sottosoglia per avvisare il ristoratore
    low_stock_products = Product.query.filter(
        Product.user_id == current_user.id,
        Product.quantity <= Product.min_threshold
    ).all()
    return render_template('dashboard.html', name=current_user.restaurant_name, low_stock=low_stock_products)

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
    new_product = Product(name=name, quantity=quantity, unit=unit, min_threshold=threshold, user_id=current_user.id)
    db.session.add(new_product)
    db.session.commit()
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
    return redirect(url_for('main.recipe', item_id=item_id))

# LOGICA DI SCARICO AUTOMATICO
@main.route('/sell_item/<int:item_id>', methods=['POST'])
@login_required
def sell_item(item_id):
    # 1. Trova il piatto e la sua ricetta
    recipe_items = RecipeItem.query.filter_by(menu_item_id=item_id).all()
    
    if not recipe_items:
        flash("Errore: Questo piatto non ha ingredienti associati!")
        return redirect(url_for('main.menu'))

    # 2. Sottrai le quantità dal magazzino
    for r_item in recipe_items:
        product = Product.query.get(r_item.product_id)
        if product:
            product.quantity -= r_item.quantity_needed
    
    db.session.commit()
    flash(f"Ordine registrato! Inventario aggiornato automaticamente.")
    return redirect(url_for('main.menu'))