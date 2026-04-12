import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from src.models.models import User, db

auth = Blueprint('auth', __name__)
logger = logging.getLogger('foodloop.auth')


@auth.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user     = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            login_user(user)
            logger.info(f'LOGIN OK — utente: {email} | ruolo: {user.role}')
            return redirect(url_for('main.dashboard'))
        else:
            # Log il tentativo fallito senza esporre la password
            logger.warning(f'LOGIN FALLITO — email: {email} | ip: {request.remote_addr}')
            flash("Email o password errati. Riprova.")

    return render_template('login.html')


@auth.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email           = request.form.get('email', '').strip().lower()
        full_name       = request.form.get('full_name', '').strip()
        restaurant_name = request.form.get('restaurant_name', '').strip()
        password        = request.form.get('password', '')

        if not email or not full_name or not restaurant_name or not password:
            flash("Tutti i campi sono obbligatori.")
            return redirect(url_for('auth.register'))

        if len(password) < 6:
            flash("La password deve contenere almeno 6 caratteri.")
            return redirect(url_for('auth.register'))

        if User.query.filter_by(email=email).first():
            logger.warning(f'REGISTER DUPLICATA — email già in uso: {email}')
            flash("Questa email è già registrata.")
            return redirect(url_for('auth.register'))

        new_user = User(
            email=email,
            full_name=full_name,
            restaurant_name=restaurant_name,
            role='owner'
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        logger.info(f'REGISTER OK — nuovo utente: {email} | locale: {restaurant_name}')
        login_user(new_user)
        return redirect(url_for('main.dashboard'))

    return render_template('register.html')


@auth.route('/logout')
@login_required
def logout():
    logger.info(f'LOGOUT — utente: {current_user.email}')
    logout_user()
    return redirect(url_for('auth.login'))


# ---> FASE 32: CAMBIO PASSWORD OBBLIGATORIO <---
@auth.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if not current_user.must_change_password:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        new_password     = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if len(new_password) < 6:
            flash("La password deve contenere almeno 6 caratteri.")
        elif new_password != confirm_password:
            flash("Le password non coincidono. Riprova.")
        else:
            current_user.set_password(new_password)
            current_user.must_change_password = False
            db.session.commit()
            logger.info(f'PASSWORD CAMBIATA — utente: {current_user.email}')
            flash("✅ Password personale impostata! Benvenuto in FoodLoop.")
            return redirect(url_for('main.dashboard'))

    return render_template('change_password.html')
