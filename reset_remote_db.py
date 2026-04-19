"""
reset_remote_db.py — Ricrea il database remoto da zero.

USO:
    FLASK_ENV=production DATABASE_URL=postgresql://... python reset_remote_db.py

ATTENZIONE: esegue DROP ALL + CREATE ALL — cancella tutti i dati esistenti.
Usare solo durante il setup iniziale o dopo modifiche ai modelli in produzione.
"""
import sys
import os

sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from src.app import create_app
from src.models.models import db

app = create_app()

with app.app_context():
    print("Dropping all tables...")
    db.drop_all()
    print("Creating all tables with updated schema...")
    db.create_all()
    print("Done. Database reset successfully.")
