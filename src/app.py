from flask import Flask
from flask_login import LoginManager
import os
from dotenv import load_dotenv
from src.models.models import db, User 

load_dotenv()

def create_app():
    app = Flask(__name__)

    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Inizializza il db con l'app
    db.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Registrazione Blueprints
    from src.routes.auth import auth as auth_blueprint
    from src.routes.main import main as main_blueprint
    
    app.register_blueprint(auth_blueprint)
    app.register_blueprint(main_blueprint)

    # ---> LA MAGIA È QUI <---
    # Crea automaticamente tutte le tabelle nel database se non esistono
    with app.app_context():
        db.create_all()

    @app.route('/')
    def index():
        return "<h1>S.I.M. Acceso!</h1><a href='/login'>Vai al Login</a>"

    return app