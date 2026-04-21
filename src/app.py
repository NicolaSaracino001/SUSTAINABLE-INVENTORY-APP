import os
import logging
from datetime import timedelta
from flask import Flask, redirect, url_for, render_template
from flask_login import LoginManager
from dotenv import load_dotenv
import cloudinary
from src.models.models import db, User

load_dotenv()

# ── Cloudinary — lettura automatica di CLOUDINARY_URL dall'ambiente ───────────
cloudinary.config()   # legge CLOUDINARY_URL se presente, non-op altrimenti

# ── Logging centralizzato ──────────────────────────────────────────────────────
def setup_logging():
    """Configura il logger globale di FoodLoop con formato leggibile nel terminale."""
    fmt = logging.Formatter(
        '[%(asctime)s] %(levelname)-8s  %(name)s — %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler = logging.StreamHandler()
    handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Evita duplicati se Flask aggiunge handler di default
    if not root.handlers:
        root.addHandler(handler)
    else:
        root.handlers[0].setFormatter(fmt)

    # Riduci il verboso di librerie terze
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

    return logging.getLogger('foodloop')


logger = setup_logging()


# ── Configurazioni per ambiente ────────────────────────────────────────────────

class Config:
    """Base comune a tutti gli ambienti."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-only-change-in-production')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20 MB upload limit

    # ── Session & Cookie Security ──────────────────────────────────────────
    SESSION_COOKIE_HTTPONLY  = True    # JS non può leggere il cookie di sessione
    SESSION_COOKIE_SAMESITE  = 'Lax'  # Protegge da CSRF cross-site
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_DURATION = timedelta(days=14)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)


class DevelopmentConfig(Config):
    """SQLite locale — per sviluppo."""
    DEBUG = True
    TESTING = False
    SESSION_COOKIE_SECURE = False   # HTTP va bene in locale
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'sqlite:///' + os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'database.db')
    )


class ProductionConfig(Config):
    """PostgreSQL — per deployment su Render / Railway / Heroku."""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True    # Solo su HTTPS in produzione

    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', '')

    @classmethod
    def validate(cls):
        if not cls.SQLALCHEMY_DATABASE_URI:
            raise RuntimeError("DATABASE_URL non impostata in produzione!")
        # Heroku fornisce ancora "postgres://" — SQLAlchemy 2.x richiede "postgresql://"
        if cls.SQLALCHEMY_DATABASE_URI.startswith('postgres://'):
            cls.SQLALCHEMY_DATABASE_URI = cls.SQLALCHEMY_DATABASE_URI.replace(
                'postgres://', 'postgresql://', 1
            )
        if os.environ.get('SECRET_KEY', '').startswith('dev-only'):
            raise RuntimeError("SECRET_KEY non sicura impostata in produzione!")


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

    # ── Log di avvio ──────────────────────────────────────────────────────
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    db_display = db_uri[:60] + '...' if len(db_uri) > 60 else db_uri
    secret_safe = 'CUSTOM ✓' if not app.config['SECRET_KEY'].startswith('dev-only') else 'DEFAULT ⚠ (cambia in produzione)'

    logger.info('━' * 58)
    logger.info('  FoodLoop — avvio applicazione')
    logger.info('━' * 58)
    logger.info(f'  Ambiente  : {env.upper()}')
    logger.info(f'  Database  : {db_display}')
    logger.info(f'  SecretKey : {secret_safe}')
    logger.info(f'  Debug     : {app.config["DEBUG"]}')
    logger.info(f'  Cookie    : httponly=True  samesite=Lax  secure={app.config.get("SESSION_COOKIE_SECURE", False)}')
    logger.info('━' * 58)

    # ── Inizializza estensioni ─────────────────────────────────────────────
    db.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Accedi per continuare.'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # ── Registra Blueprint ─────────────────────────────────────────────────
    from src.routes.auth import auth as auth_blueprint
    from src.routes.main import main as main_blueprint

    app.register_blueprint(auth_blueprint)
    app.register_blueprint(main_blueprint)

    # ── Crea tabelle se non esistono ───────────────────────────────────────
    with app.app_context():
        db.create_all()
        logger.info('  Database  : tabelle verificate / create ✓')

        # ── Migration SQLite: aggiungi colonne mancanti a tabelle esistenti ──
        # db.create_all() non altera tabelle già esistenti — lo facciamo noi.
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        # Colonna notes su consumption_log (Fase 42)
        existing_cols = [c['name'] for c in inspector.get_columns('consumption_log')]
        if 'notes' not in existing_cols:
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE consumption_log ADD COLUMN notes VARCHAR(200)'))
                conn.commit()
            logger.info('  Migration : consumption_log.notes aggiunta ✓')

        # Fase 43.3 — profile_image allargato a VARCHAR(500) per URL Cloudinary
        user_cols = {c['name']: c for c in inspector.get_columns('user')}
        if 'profile_image' in user_cols:
            col_type = str(user_cols['profile_image']['type'])
            if '255' in col_type:
                dialect = db.engine.dialect.name
                try:
                    with db.engine.connect() as conn:
                        if dialect == 'postgresql':
                            conn.execute(text(
                                'ALTER TABLE "user" ALTER COLUMN profile_image TYPE VARCHAR(500)'
                            ))
                        # SQLite non supporta ALTER COLUMN TYPE — la nuova colonna
                        # nasce già a 500 char per i nuovi DB, i vecchi sono in memoria
                        conn.commit()
                    logger.info('  Migration : user.profile_image → VARCHAR(500) ✓')
                except Exception:
                    pass   # già aggiornata o non necessario

        logger.info('━' * 58)

    # ── Gestori errori personalizzati ──────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        logger.warning(f'404 — risorsa non trovata: {e}')
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_error(e):
        db.session.rollback()   # evita sessioni DB corrotte dopo un errore
        logger.error(f'500 — errore interno: {e}', exc_info=True)
        return render_template('errors/500.html'), 500

    @app.route('/')
    def index():
        return redirect(url_for('auth.login'))

    return app
