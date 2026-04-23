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
    return {
        'server':   os.environ.get('SMTP_SERVER', ''),
        'port':     int(os.environ.get('SMTP_PORT', 587)),
        'username': os.environ.get('SMTP_USERNAME', ''),
        'password': os.environ.get('SMTP_PASSWORD', ''),
        'sender':   os.environ.get('MAIL_DEFAULT_SENDER', ''),
    }


def send_reset_email(to_email: str, reset_url: str, user_name: str = '') -> bool:
    """
    Invia l'email HTML di reset password.
    Ritorna True se l'invio ha successo, False altrimenti (errore già loggato).
    """
    cfg = _smtp_config()

    if not all([cfg['server'], cfg['username'], cfg['password'], cfg['sender']]):
        logger.warning(
            'MAILER — variabili SMTP non configurate. '
            'Imposta SMTP_SERVER, SMTP_USERNAME, SMTP_PASSWORD, MAIL_DEFAULT_SENDER.'
        )
        return False

    salutation = f'Ciao {user_name},' if user_name else 'Ciao,'

    html_body = f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:40px 16px;">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:16px;overflow:hidden;
                    box-shadow:0 4px 24px rgba(0,0,0,0.08);">

        <!-- Header verde -->
        <tr>
          <td style="background:linear-gradient(135deg,#10b981 0%,#059669 100%);
                     padding:32px 40px;text-align:center;">
            <h1 style="margin:0;color:#ffffff;font-size:26px;font-weight:800;
                       letter-spacing:-0.5px;">
              🍃 FoodLoop
            </h1>
            <p style="margin:6px 0 0;color:rgba(255,255,255,0.85);font-size:13px;">
              Gestione Intelligente del Ristorante
            </p>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:36px 40px;">
            <p style="margin:0 0 8px;font-size:15px;color:#334155;">{salutation}</p>
            <p style="margin:0 0 24px;font-size:15px;color:#475569;line-height:1.6;">
              Abbiamo ricevuto una richiesta di reimpostazione della password
              per il tuo account FoodLoop associato a <strong>{to_email}</strong>.
            </p>

            <!-- CTA Button -->
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td align="center" style="padding:8px 0 28px;">
                  <a href="{reset_url}"
                     style="display:inline-block;background:linear-gradient(135deg,#10b981 0%,#059669 100%);
                            color:#ffffff;font-size:15px;font-weight:700;text-decoration:none;
                            padding:14px 36px;border-radius:10px;letter-spacing:0.2px;">
                    🔑 Reimposta Password
                  </a>
                </td>
              </tr>
            </table>

            <p style="margin:0 0 8px;font-size:13px;color:#94a3b8;">
              Il link è valido per <strong>1 ora</strong>. Se non hai richiesto
              il reset, puoi ignorare questa email in tutta sicurezza.
            </p>
            <p style="margin:0;font-size:12px;color:#cbd5e1;word-break:break-all;">
              Oppure copia questo URL nel browser:<br>
              <a href="{reset_url}" style="color:#10b981;">{reset_url}</a>
            </p>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#f8fafc;padding:20px 40px;border-top:1px solid #e2e8f0;
                     text-align:center;">
            <p style="margin:0;font-size:12px;color:#94a3b8;">
              © 2025 FoodLoop — Inviato automaticamente, non rispondere a questa email.
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

    plain_body = (
        f"{salutation}\n\n"
        f"Hai richiesto il reset della password per il tuo account FoodLoop.\n\n"
        f"Clicca qui per reimpostare la password (valido 1 ora):\n{reset_url}\n\n"
        f"Se non hai richiesto il reset, ignora questa email.\n\n"
        f"— Il team FoodLoop"
    )

    msg = MIMEMultipart('alternative')
    msg['Subject'] = '🔑 Reimposta la tua password FoodLoop'
    msg['From']    = cfg['sender']
    msg['To']      = to_email
    msg.attach(MIMEText(plain_body, 'plain', 'utf-8'))
    msg.attach(MIMEText(html_body,  'html',  'utf-8'))

    try:
        port = cfg['port']
        if port == 465:
            # SSL diretto
            with smtplib.SMTP_SSL(cfg['server'], port, timeout=10) as smtp:
                smtp.login(cfg['username'], cfg['password'])
                smtp.sendmail(cfg['sender'], to_email, msg.as_string())
        else:
            # STARTTLS (porta 587 o 25)
            with smtplib.SMTP(cfg['server'], port, timeout=10) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(cfg['username'], cfg['password'])
                smtp.sendmail(cfg['sender'], to_email, msg.as_string())

        logger.info(f'EMAIL INVIATA — reset password a: {to_email}')
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error('MAILER — autenticazione SMTP fallita: controlla SMTP_USERNAME e SMTP_PASSWORD')
    except smtplib.SMTPException as e:
        logger.error(f'MAILER — errore SMTP: {e}')
    except OSError as e:
        logger.error(f'MAILER — connessione fallita ({cfg["server"]}:{port}): {e}')

    return False
