from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    restaurant_name = db.Column(db.String(150), nullable=False)
    
    products = db.relationship('Product', backref='owner', lazy=True)
    menu_items = db.relationship('MenuItem', backref='owner', lazy=True)
    # Collegamento al nuovo registro storico
    consumptions = db.relationship('ConsumptionLog', backref='owner', lazy=True)

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Float, nullable=False, default=0.0)
    unit = db.Column(db.String(20), nullable=False)
    min_threshold = db.Column(db.Float, nullable=False, default=5.0)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class MenuItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipes = db.relationship('RecipeItem', backref='menu_item', lazy=True, cascade="all, delete-orphan")

class RecipeItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    menu_item_id = db.Column(db.Integer, db.ForeignKey('menu_item.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity_needed = db.Column(db.Float, nullable=False)
    
    product = db.relationship('Product')

# ---> NUOVA TABELLA PER IL DATASET PREDITTIVO <---
class ConsumptionLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity_used = db.Column(db.Float, nullable=False)
    # Salva in automatico la data e l'ora esatta in cui avviene il consumo
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    product = db.relationship('Product')