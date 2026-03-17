from ..app import db
from flask_login import UserMixin
from datetime import datetime

# Modello Utente (Ristoratore)
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    restaurant_name = db.Column(db.String(100), nullable=False)
    # Collegamento con i prodotti in magazzino
    inventory = db.relationship('Product', backref='owner', lazy=True)

# Modello Prodotto (Magazzino/Deposito)
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Float, default=0.0)  # Quantità attuale
    unit = db.Column(db.String(20), nullable=False) # kg, litri, pezzi
    min_threshold = db.Column(db.Float, default=5.0) # Soglia per avviso mail
    expiry_date = db.Column(db.Date, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# Modello Piatto del Menù (es. Pizza Margherita)
class MenuItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # Relazione con gli ingredienti necessari
    recipe = db.relationship('RecipeItem', backref='menu_item', lazy=True)

# Modello Ricetta (Il ponte tra Piatto e Ingredienti)
class RecipeItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    menu_item_id = db.Column(db.Integer, db.ForeignKey('menu_item.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity_needed = db.Column(db.Float, nullable=False) # Quanto serve per 1 porzione