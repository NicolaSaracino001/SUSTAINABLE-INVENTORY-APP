"""
FoodLoop — Mailer
Invia email transazionali tramite SMTP configurabile via variabili d'ambiente.

Variabili richieste su Vercel / .env:
  SMTP_SERVER          es. smtp.gmail.com  | smtp.sendgrid.net
  SMTP_PORT            es. 587 (STARTTLS)  | 465 (SSL)
  SMTP_USERNAME        account mittente
  SMTP_PASSWORD        password / API key
  MAIL_DEFAULT_SENDER  es. noreply@foodloop.app
"""

import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger('foodloop.mailer')


def _smtp_config() -> dict:
    try:
        port = int(os.environ.get('SMTP_PORT', 587))
    except (ValueError, TypeError):
        logger.warning('MAILER — SMTP_PORT non valido, uso 587 come default')
        port = 587
    return {
        'server':   os.environ.get('SMTP_SERVER', ''),
        'port':     port,
        'username': os.environ.get('SMTP_USERNAME', ''),
        'password': os.environ.get('SMTP_PASSWORD', ''),
        'sender':   os.environ.get('MAIL_DEFAULT_SENDER', ''),
    }


def _smtp_send(cfg: dict, to_email: str, subject: str,
               html_body: str, plain_body: str) -> bool:
    """
    Core SMTP transport.
    Ritorna True se l'invio ha successo, False altrimenti (errore già loggato).
    """
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From']    = cfg['sender']
    msg['To']      = to_email
    msg.attach(MIMEText(plain_body, 'plain', 'utf-8'))
    msg.attach(MIMEText(html_body,  'html',  'utf-8'))

    try:
        port = cfg['port']
        if port == 465:
            with smtplib.SMTP_SSL(cfg['server'], port, timeout=10) as smtp:
                smtp.login(cfg['username'], cfg['password'])
                smtp.sendmail(cfg['sender'], to_email, msg.as_string())
        else:
            with smtplib.SMTP(cfg['server'], port, timeout=10) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(cfg['username'], cfg['password'])
                smtp.sendmail(cfg['sender'], to_email, msg.as_string())
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error('MAILER — autenticazione SMTP fallita: controlla SMTP_USERNAME e SMTP_PASSWORD')
    except smtplib.SMTPException as e:
        logger.error(f'MAILER — errore SMTP: {e}')
    except OSError as e:
        logger.error(f'MAILER — connessione fallita ({cfg["server"]}:{port}): {e}')

    return False


def send_reset_email(to_email: str, reset_url: str, user_name: str = '') -> bool:
    """
    Invia l'email HTML di reset password usando il template emails/reset_password.html.
    Ritorna True se l'invio ha successo, False altrimenti (errore già loggato).
    """
    cfg = _smtp_config()

    if not all([cfg['server'], cfg['username'], cfg['password'], cfg['sender']]):
        logger.warning(
            'MAILER — variabili SMTP non configurate. '
            'Imposta SMTP_SERVER, SMTP_USERNAME, SMTP_PASSWORD, MAIL_DEFAULT_SENDER.'
        )
        return False

    from flask import render_template
    html_body = render_template(
        'emails/reset_password.html',
        user_name=user_name,
        to_email=to_email,
        reset_url=reset_url,
    )

    plain_body = (
        f"{'Ciao ' + user_name + ',' if user_name else 'Ciao,'}\n\n"
        "Hai richiesto il reset della password per il tuo account FoodLoop.\n\n"
        f"Clicca qui per reimpostare la password (valido 1 ora):\n{reset_url}\n\n"
        "Se non hai richiesto il reset, ignora questa email.\n\n"
        "— Il team FoodLoop"
    )

    ok = _smtp_send(cfg, to_email, '🔑 Reimposta la tua password FoodLoop', html_body, plain_body)
    if ok:
        logger.info(f'EMAIL INVIATA — reset password a: {to_email}')
    return ok


def send_welcome_premium_email(to_email: str, user_name: str = '') -> bool:
    """
    Invia l'email HTML di benvenuto Premium usando il template emails/welcome_premium.html.
    Ritorna True se l'invio ha successo, False altrimenti (errore già loggato).
    """
    cfg = _smtp_config()

    if not all([cfg['server'], cfg['username'], cfg['password'], cfg['sender']]):
        logger.warning(
            'MAILER — variabili SMTP non configurate. '
            'Email di benvenuto Premium non inviata.'
        )
        return False

    from flask import render_template
    html_body = render_template(
        'emails/welcome_premium.html',
        user_name=user_name,
        to_email=to_email,
    )

    plain_body = (
        f"{'Ciao ' + user_name + '!' if user_name else 'Ciao!'}\n\n"
        "Benvenuto su FoodLoop Premium! Il tuo account è ora attivo.\n\n"
        "Hai accesso a tutte le funzionalità:\n"
        "  ✓ Prodotti e utenti illimitati\n"
        "  ✓ AI Insights con Gemini\n"
        "  ✓ Invoice Scanner AI\n"
        "  ✓ Gestione Team completa\n"
        "  ✓ Supporto prioritario\n\n"
        "Grazie per aver scelto FoodLoop Premium.\n\n"
        "— Il team FoodLoop"
    )

    ok = _smtp_send(cfg, to_email, '🎉 Benvenuto su FoodLoop Premium!', html_body, plain_body)
    if ok:
        logger.info(f'EMAIL INVIATA — benvenuto Premium a: {to_email}')
    return ok
