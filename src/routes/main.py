from flask import Blueprint, render_template
from flask_login import login_required, current_user

main = Blueprint('main', __name__)

@main.route('/dashboard')
@login_required
def dashboard():
    # Qui passeremo in futuro i dati dei prodotti in scadenza e ordini
    return render_template('dashboard.html', name=current_user.restaurant_name)

@main.route('/inventory')
@login_required
def inventory():
    return render_template('inventory.html')

@main.route('/menu')
@login_required
def menu():
    return render_template('menu.html')