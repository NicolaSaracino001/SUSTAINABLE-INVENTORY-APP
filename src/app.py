import os
from flask import Flask, redirect, url_for
from flask_login import LoginManager
from dotenv import load_dotenv
from src.models.models import db, User

load_dotenv()

# ── Configurazioni per ambiente ────────────────────────────────────────────────

class Config:
    """Base comune a tutti gli ambienti."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-fallback-change-in-production')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20 MB upload limit


class DevelopmentConfig(Config):
    """SQLite locale — per sviluppo."""
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'sqlite:///' + os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'database.db')
    )


class ProductionConfig(Config):
    """PostgreSQL — per deployment su Render / Railway / Heroku."""
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')  # Es: postgresql://...

    @classmethod
    def validate(cls):
        if not cls.SQLALCHEMY_DATABASE_URI:
            raise RuntimeError("DATABASE_URL non impostata in produzione!")
        # Heroku fornisce ancora "postgres://" — SQLAlchemy 2.x richiede "postgresql://"
        if cls.SQLALCHEMY_DATABASE_URI.startswith('postgres://'):
            cls.SQLALCHEMY_DATABASE_URI = cls.SQLALCHEMY_DATABASE_URI.replace(
                'postgres://', 'postgresql://', 1
            )


_config_map = {
    'development': DevelopmentConfig,
    'production':  ProductionConfig,
}

# ── Factory ────────────────────────────────────────────────────────────────────

def create_app(config_name: str = None) -> Flask:
    app = Flask(__name__)

    env = config_name or os.environ.get('FLASK_ENV', 'development')
    cfg = _config_map.get(env, DevelopmentConfig)

    if env == 'production':
        ProductionConfig.validate()

    app.config.from_object(cfg)

    # Stampa ambiente attivo all'avvio
    print(f"[FoodLoop] Ambiente: {env.upper()} | DB: {app.config['SQLALCHEMY_DATABASE_URI'][:40]}...")

    # Inizializza estensioni
    db.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Registra Blueprint
    from src.routes.auth import auth as auth_blueprint
    from src.routes.main import main as main_blueprint

    app.register_blueprint(auth_blueprint)
    app.register_blueprint(main_blueprint)

    # Crea tabelle se non esistono
    with app.app_context():
        db.create_all()

    @app.route('/')
    def index():
        return redirect(url_for('auth.login'))

    return app
