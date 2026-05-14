# FoodLoop - Product Requirements Document (PRD)

## 1. Visione del Prodotto
FoodLoop è una piattaforma gestionale SaaS avanzata (Enterprise) progettata per il settore alimentare e della ristorazione. L'obiettivo è digitalizzare e ottimizzare la gestione dei locali, riducendo gli sprechi attraverso l'uso dell'Intelligenza Artificiale.

## 2. Tech Stack e Infrastruttura
- **Backend:** Python con framework Flask.
- **Frontend:** HTML, CSS, JavaScript (Template Jinja2).
- **Database:** SQLAlchemy (ORM).
- **Pagamenti:** Stripe (Checkout Session & Customer Portal).
- **Intelligenza Artificiale:** Google Gemini API.
- **Hosting & Deploy:** Vercel.

## 3. Architettura e Funzionalità Core
- **Gestione Utenti (Auth):** Registrazione, Login, Reset Password con email HTML.
- **Modello SaaS:** Abbonamento Free e Premium (gestito tramite webhook Stripe in Modalità Test, futuro Live).
- **Multi-Sede (Tenant):** Un singolo utente Owner può creare e gestire più negozi/sedi in modo isolato (switch rapido).
- **Inventario e Magazzino:** Tracciamento dei prodotti, lotti e date di scadenza per singola sede.
- **Gestione Team:** Ruoli RBAC (Owner vs Staff). Lo staff ha accesso limitato e non visualizza le sezioni finanziarie e di abbonamento.

## 4. Integrazioni AI (Premium Features)
- **AI Insights:** Gemini analizza i dati del magazzino per prevedere le scadenze e suggerire strategie anti-spreco.
- **Invoice Scanner AI:** OCR intelligente per l'estrazione dei dati dalle fatture (PDF/Immagini) e il popolamento automatico dei prodotti in magazzino.

## 5. Regole di Sviluppo (Strict Guidelines per AI Agents)
- **Nessun FOUC (Flickering):** Evitare assolutamente script JS o regole CSS inline (`display: none`) che nascondono il body o l'UI durante il caricamento. Gestire il rendering condizionale lato server con Jinja.
- **URL Dinamici:** Mai hardcodare URL assoluti nei template (es. `https://foodloop.app`). Usare sempre la funzione Flask `url_for('nome_rotta', _external=True)`.
- **Commit Sicuri e Tracciamento:** Nessuna esecuzione autonoma di comandi git o commit da parte degli agenti. Il controllo di versione e il tracciamento dettagliato delle fasi avvengono esclusivamente tramite l'intervento umano su GitHub Desktop.