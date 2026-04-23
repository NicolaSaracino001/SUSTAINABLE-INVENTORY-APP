import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from src.models.models import User, PasswordResetToken, db
from src.utils.mailer import send_reset_email

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


# ─── FASE 45: RECUPERO PASSWORD ───────────────────────────────────────────────

@auth.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Mostra il form per richiedere il reset della password e genera il token."""
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user  = User.query.filter_by(email=email).first()

        if user:
            # Invalida token precedenti ancora attivi per questo utente
            PasswordResetToken.query.filter_by(user_id=user.id, used=False).update({'used': True})
            db.session.flush()

            reset_token = PasswordResetToken.generate(user.id)
            db.session.add(reset_token)
            db.session.commit()

            reset_url = url_for('auth.reset_password', token=reset_token.token, _external=True)

            logger.info(f'RESET PASSWORD — token generato per: {email} | scade: {reset_token.expires_at.strftime("%Y-%m-%d %H:%M:%S")} UTC')

            # ── Invio email reale via SMTP ────────────────────────────────────
            sent = send_reset_email(
                to_email  = user.email,
                reset_url = reset_url,
                user_name = user.full_name,
            )
            if not sent:
                # SMTP non configurato o errore: logga il link per sviluppo locale
                logger.warning(f'RESET PASSWORD — email non inviata. Link di fallback: {reset_url}')

        else:
            # Email non trovata — nessun log che rivela l'esistenza dell'account
            logger.info('RESET PASSWORD — email non trovata nel sistema (risposta generica)')

        # Risposta identica in ogni caso (anti-enumeration)
        flash("Se l'email è registrata, riceverai a breve il link per reimpostare la password.")
        return redirect(url_for('auth.forgot_password'))

    return render_template('forgot_password.html')


@auth.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token: str):
    """Verifica il token e permette di impostare una nuova password."""
    record = PasswordResetToken.query.filter_by(token=token).first()

    if not record or not record.is_valid:
        logger.warning(f'RESET PASSWORD — token non valido o scaduto: {token[:16]}...')
        flash("Il link di reset non è valido o è scaduto. Richiedine uno nuovo.")
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        new_password     = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if len(new_password) < 6:
            flash("La password deve contenere almeno 6 caratteri.")
        elif new_password != confirm_password:
            flash("Le password non coincidono. Riprova.")
        elif check_password_hash(record.user.password_hash, new_password):
            # Policy anti-riciclo: blocca se la nuova è uguale all'attuale
            flash("La nuova password non può essere uguale a quella precedente.")
        else:
            record.user.set_password(new_password)
            record.used = True          # invalida il token dopo l'uso
            db.session.commit()
            logger.info(f'RESET PASSWORD OK — utente: {record.user.email}')
            flash("Password aggiornata con successo! Puoi accedere con la nuova password.")
            return redirect(url_for('auth.login'))

    return render_template('reset_password.html', token=token)


# ─── FASE 45.3: CAMBIO PASSWORD IN-APP ───────────────────────────────────────

@auth.route('/update-password', methods=['POST'])
@login_required
def update_password():
    """Permette all'utente loggato di cambiare la propria password dall'area Account."""
    current_pw  = request.form.get('current_password', '')
    new_pw      = request.form.get('new_password', '')
    confirm_pw  = request.form.get('confirm_password', '')

    # Rileggo l'utente fresco dal DB — evita qualsiasi cache del proxy Flask-Login
    user = db.session.get(User, current_user.id)

    # 1. La password attuale deve essere corretta
    if not check_password_hash(user.password_hash, current_pw):
        flash("La password attuale non è corretta.", 'pw_error')
        return redirect(url_for('main.profile') + '#sicurezza')

    # 2. Policy anti-riciclo — confronto esplicito hash vs input
    if check_password_hash(user.password_hash, new_pw):
        flash("Errore: La nuova password non può essere uguale a quella attuale.", 'pw_error')
        return redirect(url_for('main.profile') + '#sicurezza')

    # 3. La nuova e la conferma devono coincidere
    if new_pw != confirm_pw:
        flash("La nuova password e la conferma non coincidono.", 'pw_error')
        return redirect(url_for('main.profile') + '#sicurezza')

    # 4. Lunghezza minima
    if len(new_pw) < 6:
        flash("La nuova password deve contenere almeno 6 caratteri.", 'pw_error')
        return redirect(url_for('main.profile') + '#sicurezza')

    user.set_password(new_pw)
    db.session.commit()
    logger.info(f'PASSWORD AGGIORNATA IN-APP — utente: {user.email}')
    flash("✅ Password aggiornata con successo!", 'pw_success')
    return redirect(url_for('main.profile') + '#sicurezza')
