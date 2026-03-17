from src.app import create_app, db
from src.models.models import User, Product, MenuItem, RecipeItem

app = create_app()

with app.app_context():
    # Questo comando crea fisicamente il file .db e le tabelle
    db.create_all()
    print("Database creato con successo!")