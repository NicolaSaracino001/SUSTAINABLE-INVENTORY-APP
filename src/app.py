from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
import os
from dotenv import load_dotenv

# Carica le configurazioni dal file .env
load_dotenv()

# Inizializziamo l'oggetto Database (SQLAlchemy)
db = SQLAlchemy()

def create_app():
    # 1. CREIAMO PRIMA L'OGGETTO APP (Fondamentale!)
    app = Flask(__name__)

    # 2. CONFIGURAZIONE (presa dal file .env)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # 3. COLLEGIAMO IL DATABASE ALL'APP
    db.init_app(app)

    # 4. CONFIGURAZIONE LOGIN
    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    # Registrazione dei Blueprints (Rotte)
    from .routes.auth import auth as auth_blueprint
    app.register_blueprint(auth_blueprint)

    # Rotta di prova
    @app.route('/')
    def index():
        return "<h1>S.I.M. Acceso!</h1><a href='/login'>Vai al Login</a>"

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)