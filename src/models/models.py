from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import secrets

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)  # scrypt hash supera 150 char
    full_name = db.Column(db.String(255), nullable=False)
    restaurant_name = db.Column(db.String(255))
    role = db.Column(db.String(50), default='owner')
    parent_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    must_change_password = db.Column(db.Boolean, default=False)
    monthly_budget = db.Column(db.Float, default=0.0)
    profile_image = db.Column(db.String(500), default='default')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def get_restaurant_id(self):
        return self.id if self.role == 'owner' else self.parent_id

    @property
    def get_restaurant_name(self):
        if self.role == 'owner':
            return self.restaurant_name
        boss = User.query.get(self.parent_id)
        return boss.restaurant_name if boss else "Staff"

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(50), nullable=False)
    min_threshold = db.Column(db.Float, nullable=False)
    unit_cost = db.Column(db.Float, default=0.0)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False,
                        index=True)   # ← indice: query filter_by(user_id) veloce
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=True)
    supplier = db.relationship('Supplier', backref='products')

class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    contact_info = db.Column(db.String(250), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False,
                        index=True)

class MenuItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    price = db.Column(db.Float, nullable=False)
    prep_time = db.Column(db.Integer)
    allergens = db.Column(db.String(200))
    instructions = db.Column(db.Text)
    image_file = db.Column(db.String(255), default='default.jpg')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class RecipeItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    menu_item_id = db.Column(db.Integer, db.ForeignKey('menu_item.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity_needed = db.Column(db.Float, nullable=False)
    menu_item = db.relationship('MenuItem', backref=db.backref('recipe_items', lazy=True))
    product = db.relationship('Product')

class ConsumptionLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False,
                        index=True)   # ← indice: filtraggio per utente veloce
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity_used = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow,
                          index=True)  # ← indice: ordinamento temporale veloce
    notes = db.Column(db.String(200), nullable=True)      # causale: es. "Vendita: Pizza x2"
    product = db.relationship('Product', lazy='joined')   # eager load: evita N+1

class SaleLog(db.Model):
    """Traccia ogni chiusura di cassa / vendita registrata nel sistema."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False,
                        index=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    total_items = db.Column(db.Integer, nullable=False, default=0)  # numero totale di porzioni
    source = db.Column(db.String(50), nullable=False, default='manual')  # 'receipt_scan' | 'manual'


class PasswordResetToken(db.Model):
    """Token sicuro per il reset della password — scade dopo 1 ora."""
    __tablename__ = 'password_reset_token'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    token      = db.Column(db.String(128), unique=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used       = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('reset_tokens', lazy='dynamic'))

    @staticmethod
    def generate(user_id: int) -> 'PasswordResetToken':
        """Crea un nuovo token sicuro da 64 byte hex, scadenza 1 ora."""
        token = secrets.token_hex(64)
        expires = datetime.utcnow() + timedelta(hours=1)
        return PasswordResetToken(user_id=user_id, token=token, expires_at=expires)

    @property
    def is_valid(self) -> bool:
        """True se il token non è stato usato e non è scaduto."""
        return not self.used and datetime.utcnow() < self.expires_at


class WasteLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False,
                        index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity_wasted = db.Column(db.Float, nullable=False)
    cost_lost = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    product = db.relationship('Product', lazy='joined')   # eager load: evita N+1