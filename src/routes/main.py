from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from src.models.models import MenuItem, RecipeItem, Product, db
import os
import requests

main = Blueprint('main', __name__)

def get_weather_info():
    """Funzione di supporto per recuperare il meteo tramite API"""
    api_key = os.getenv('WEATHER_API_KEY')
    city = os.getenv('CITY', 'Milano')
    
    # Se non c'è una chiave valida, restituiamo un messaggio neutro
    if not api_key or api_key == "inserisci_la_tua_chiave_qui":
        return None
    
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric&lang=it"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
        return None
    except:
        return None

@main.route('/dashboard')
@login_required
def dashboard():
    # Prodotti sotto soglia
    low_stock_products = Product.query.filter(
        Product.user_id == current_user.id,
        Product.quantity <= Product.min_threshold
    ).all()
    
    # Logica Meteo
    weather = get_weather_info()
    suggestion = "Meteo non disponibile. Basati sui consumi medi settimanali per l'approvvigionamento."
    
    if weather:
        temp = weather['main']['temp']
        desc = weather['weather'][0]['description']
        if temp > 25:
            suggestion = f"Previsti {temp}°C ({desc}). Suggerimento: Aumenta le scorte di bevande, insalate e prodotti freschi. Previsto aumento affluenza all'aperto."
        elif temp < 12:
            suggestion = f"Previsti {temp}°C ({desc}). Suggerimento: Clima freddo. Sposta l'approvvigionamento su prodotti per zuppe, stufati e carni rosse."
        else:
            suggestion = f"Meteo mite ({temp}°C, {desc}). L'affluenza dovrebbe essere costante. Mantieni le scorte standard."

    return render_template('dashboard.html', 
                           name=current_user.restaurant_name, 
                           low_stock=low_stock_products,
                           weather_suggestion=suggestion)

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

@main.route('/sell_item/<int:item_id>', methods=['POST'])
@login_required
def sell_item(item_id):
    recipe_items = RecipeItem.query.filter_by(menu_item_id=item_id).all()
    if not recipe_items:
        flash("Errore: Definisci la ricetta prima di scaricare!")
        return redirect(url_for('main.menu'))
    
    for r_item in recipe_items:
        product = Product.query.get(r_item.product_id)
        if product:
            product.quantity -= r_item.quantity_needed
    
    db.session.commit()
    flash("Scontrino registrato e magazzino aggiornato!")
    return redirect(url_for('main.menu'))