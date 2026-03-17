from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
import os
import sys
from dotenv import load_dotenv

# Carica configurazioni
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
load_dotenv()

# Inizializziamo db QUI, fuori dalla funzione
db = SQLAlchemy()

def create_app():
    app = Flask(__name__)

    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Colleghiamo il db all'app
    db.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    from src.models.models import User
    
    @login_manager.user_loader
    def load_user(user_id):
        # Usiamo il contesto per sicurezza
        return User.query.get(int(user_id))

    # Import e registrazione dei Blueprints
    from src.routes.auth import auth as auth_blueprint
    from src.routes.main import main as main_blueprint
    
    app.register_blueprint(auth_blueprint)
    app.register_blueprint(main_blueprint)

    @app.route('/')
    def index():
        return "<h1>S.I.M. Acceso!</h1><a href='/login'>Vai al Login</a>"

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)