from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from src.models.models import MenuItem, RecipeItem, Product
from src.app import db

main = Blueprint('main', __name__)

@main.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', name=current_user.restaurant_name)

@main.route('/inventory')
@login_required
def inventory():
    # Recuperiamo i prodotti dell'utente loggato
    products = Product.query.filter_by(user_id=current_user.id).all()
    return render_template('inventory.html', products=products)

@main.route('/add_inventory_item', methods=['POST'])
@login_required
def add_inventory_item():
    name = request.form.get('name')
    quantity = request.form.get('quantity')
    unit = request.form.get('unit')
    threshold = request.form.get('threshold')
    
    new_product = Product(
        name=name,
        quantity=float(quantity),
        unit=unit,
        min_threshold=float(threshold),
        user_id=current_user.id
    )
    db.session.add(new_product)
    db.session.commit()
    
    flash('Prodotto caricato in magazzino!')
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
    price = request.form.get('price')
    
    new_item = MenuItem(name=name, price=float(price), user_id=current_user.id)
    db.session.add(new_item)
    db.session.commit()
    
    return redirect(url_for('main.menu'))