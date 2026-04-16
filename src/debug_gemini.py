"""
debug_gemini.py — Test isolato della connessione Gemini.
Carica GEMINI_API_KEY da .env e invia un semplice messaggio di testo.
Esegui con: python src/debug_gemini.py
"""
import os
import sys

# Carica .env dalla root del progetto
from pathlib import Path
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)
    print(f"[OK] .env caricato da: {env_path}")
else:
    print(f"[WARN] .env non trovato in: {env_path}")

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("[ERRORE] GEMINI_API_KEY non trovata nel file .env o nelle variabili di ambiente.")
    sys.exit(1)

masked = api_key[:6] + "..." + api_key[-4:]
print(f"[OK] GEMINI_API_KEY trovata: {masked}")

# Importa il nuovo SDK google-genai
try:
    from google import genai as genai_sdk
    from google.genai import types as genai_types
    import google.genai as _g
    print(f"[OK] google-genai SDK importato. Versione: {_g.__version__}")
except ImportError as e:
    print(f"[ERRORE] Impossibile importare google-genai: {e}")
    print("  → Installa con: pip install google-genai")
    sys.exit(1)

# Test connessione
MODEL = "gemini-2.5-flash-lite"  # fallback attivo oggi — 2.0-flash quota giornaliera esaurita
TEST_PROMPT = "Ciao, come stai? Rispondi in una frase brevissima."

print(f"\n--- Invio messaggio di test al modello [{MODEL}] ---")
print(f"  Prompt: {TEST_PROMPT!r}")

try:
    client = genai_sdk.Client(api_key=api_key)
    response = client.models.generate_content(
        model=MODEL,
        contents=TEST_PROMPT,
    )
    print(f"\n[SUCCESSO] Risposta ricevuta:")
    print(f"  {response.text}")
    print(f"\n[INFO] Tokens usati: {response.usage_metadata}")
except Exception as e:
    print(f"\n[ERRORE] Chiamata API fallita: {type(e).__name__}")
    print(f"  Messaggio: {e}")
    print("\n  Diagnosi:")
    err = str(e)
    if "API_KEY_INVALID" in err or "INVALID_ARGUMENT" in err and "key" in err.lower():
        print("  → La chiave API non è valida. Verifica GEMINI_API_KEY nel .env.")
    elif "PERMISSION_DENIED" in err:
        print("  → Accesso negato. La chiave potrebbe non avere i permessi per Gemini.")
    elif "RESOURCE_EXHAUSTED" in err or "quota" in err.lower():
        print("  → Quota esaurita (free tier: 15 req/min). Attendi e riprova.")
    elif "404" in err or "MODEL_NOT_FOUND" in err:
        print(f"  → Modello [{MODEL}] non trovato. La chiave potrebbe non supportarlo.")
    elif "name resolution" in err.lower() or "connection" in err.lower():
        print("  → Problema di rete/DNS. Verifica la connessione internet.")
    else:
        print("  → Errore sconosciuto. Vedi il messaggio sopra per dettagli.")
    sys.exit(1)

print("\n[OK] Tutto funziona correttamente. Gemini è raggiungibile.")
