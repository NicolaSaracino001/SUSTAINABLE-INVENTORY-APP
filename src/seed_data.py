#!/usr/bin/env python3
"""
FoodLoop — Seed Data Script (Fase 40: The Great Simulation)
============================================================
Popola il database con dati realistici per stress test UI/performance.

Utilizzo:
  python -m src.seed_data                          # Popola DB (primo owner trovato)
  python -m src.seed_data --email me@example.com  # Usa utente specifico
  python -m src.seed_data --reset                  # Cancella tutti i dati di simulazione
"""
import sys
import os
import random
import argparse
from datetime import datetime, timedelta

# Bootstrap: aggiunge la root del progetto al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.app import create_app
from src.models.models import db, User, Product, Supplier, ConsumptionLog, WasteLog

# ─────────────────────────────────────────────────────────────────────────────
#  DATI DI SIMULAZIONE
# ─────────────────────────────────────────────────────────────────────────────

SUPPLIERS_DATA = [
    # (nome, contatto)
    ("Alimentari Rossi & Figli",      "ordini@rossiefifigli.it | Tel: 02-1234567"),
    ("Bevande Milano SpA",             "vendite@bevmilano.it | Tel: 02-9876543"),
    ("Ortofrutticola Verdi",           "fresh@ortoverdi.it | Tel: 02-5551234"),
    ("Caseificio Val Padana",          "formaggi@valpadana.it | Tel: 0376-445566"),
    ("Macelleria De Luca",             "ordini@delucacarni.it | Tel: 02-3334455"),
    ("Pasta & Farina Italica",         "commerciale@pastaitalia.it | Tel: 059-112233"),
    ("Birrificio Artigianale Nord",    "info@biranord.it | Tel: 031-667788"),
    ("Liquori e Spirits Italia",       "trade@spiritsitalia.it | Tel: 02-9998877"),
    ("Detersivi Pro Clean",            "proclean@pulizia.it | Tel: 02-4445566"),
    ("Igiene Ambienti SRL",            "info@igieneamb.it | Tel: 02-7778899"),
    ("Conserve del Sud",               "ordini@conservesud.it | Tel: 080-5566778"),
    ("Pescato Fresco Adriatico",       "pesce@adriatico.it | Tel: 0541-334455"),
    ("Vini DOC Toscana",               "ordini@vinitoscana.it | Tel: 0577-223344"),
    ("Dolciumi Artigianali",           "info@dolciuriartisan.it | Tel: 02-8889900"),
    ("Spezie e Condimenti Orient",     "trade@spezieorient.it | Tel: 02-1112233"),
]

# Struttura: (nome, unità, qty_base, soglia_min, costo_base_€, indice_fornitore)
PRODUCTS_DATA = {
    "Alimentari": [
        ("Farina 00",                "kg",  50,  10, 0.85,  5),
        ("Farina Manitoba",          "kg",  30,   8, 1.20,  5),
        ("Farina Integrale",         "kg",  20,   5, 1.10,  5),
        ("Semola di Grano Duro",     "kg",  25,   8, 0.95,  5),
        ("Riso Carnaroli",           "kg",  40,  10, 2.80,  0),
        ("Riso Basmati",             "kg",  20,   5, 2.20,  0),
        ("Pasta Spaghetti",          "kg",  30,  10, 1.40,  5),
        ("Pasta Rigatoni",           "kg",  25,   8, 1.35,  5),
        ("Pasta Penne",              "kg",  20,   8, 1.35,  5),
        ("Pasta Linguine",           "kg",  15,   5, 1.50,  5),
        ("Pasta Fusilli",            "kg",  15,   5, 1.40,  5),
        ("Olio EVO Toscano",         "l",   30,   5, 8.50, 12),
        ("Olio di Semi Girasole",    "l",   20,   5, 2.20,  0),
        ("Pomodori Pelati",          "kg",  60,  15, 1.80, 10),
        ("Polpa di Pomodoro",        "kg",  40,  10, 1.60, 10),
        ("Concentrato di Pomodoro",  "kg",  10,   3, 2.10, 10),
        ("Passata di Pomodoro",      "l",   50,  12, 1.50, 10),
        ("Sale Marino Grosso",       "kg",  15,   3, 0.60,  0),
        ("Sale Fino",                "kg",  10,   2, 0.55,  0),
        ("Zucchero Semolato",        "kg",  20,   5, 0.90,  0),
        ("Zucchero di Canna",        "kg",  10,   3, 1.40,  0),
        ("Aceto di Vino Bianco",     "l",    8,   2, 1.20,  0),
        ("Aceto Balsamico",          "l",    5,   1, 6.50,  0),
        ("Brodo Vegetale (dadi)",    "pz",  50,  10, 0.30,  0),
        ("Brodo di Carne (dadi)",    "pz",  40,  10, 0.35,  0),
        ("Tonno in scatola",         "pz",  60,  15, 1.80,  0),
        ("Sardine sott'olio",        "pz",  30,   8, 2.10, 11),
        ("Acciughe sott'olio",       "pz",  20,   5, 3.20, 11),
        ("Olive Nere",               "kg",   8,   2, 4.50, 10),
        ("Olive Verdi",              "kg",   8,   2, 4.20, 10),
        ("Capperi",                  "kg",   2, 0.5, 8.00, 10),
        ("Lenticchie",               "kg",  10,   3, 1.80,  0),
        ("Ceci",                     "kg",  10,   3, 1.70,  0),
        ("Fagioli Borlotti",         "kg",   8,   2, 1.90,  0),
        ("Fagioli Cannellini",       "kg",   8,   2, 1.90,  0),
        ("Mais in scatola",          "pz",  20,   5, 1.10,  0),
        ("Pangrattato",              "kg",   5,   1, 1.20,  5),
        ("Biscotti Secchi",          "kg",   5,   1, 3.50, 13),
        # Prodotti freschi
        ("Pomodori Ciliegini",       "kg",  15,   4, 3.20,  2),
        ("Pomodori Ramati",          "kg",  20,   5, 2.80,  2),
        ("Insalata Mista",           "kg",  10,   3, 4.50,  2),
        ("Rucola",                   "kg",   5,   1, 6.50,  2),
        ("Spinaci Freschi",          "kg",   8,   2, 4.80,  2),
        ("Zucchine",                 "kg",  15,   4, 2.20,  2),
        ("Melanzane",                "kg",  12,   3, 2.40,  2),
        ("Peperoni Rossi",           "kg",  10,   3, 3.80,  2),
        ("Cipolle Dorate",           "kg",  15,   4, 1.20,  2),
        ("Aglio",                    "kg",   5,   1, 3.50,  2),
        ("Carote",                   "kg",  10,   3, 1.40,  2),
        ("Sedano",                   "kg",   5,   1, 1.80,  2),
        ("Patate",                   "kg",  25,   8, 0.90,  2),
        ("Patate Dolci",             "kg",   8,   2, 2.20,  2),
        ("Funghi Champignon",        "kg",   8,   2, 5.50,  2),
        ("Funghi Porcini Secchi",    "kg",   1, 0.2,28.00,  2),
        # Carne
        ("Petto di Pollo",           "kg",  20,   5, 6.80,  4),
        ("Cosce di Pollo",           "kg",  15,   4, 4.50,  4),
        ("Manzo Macinato",           "kg",  15,   4, 9.50,  4),
        ("Manzo a Fette",            "kg",  10,   3,14.00,  4),
        ("Pancetta Tesa",            "kg",   5, 1.5,12.00,  4),
        ("Prosciutto Cotto",         "kg",   4,   1,15.00,  4),
        ("Salame Milano",            "kg",   3, 0.5,18.00,  4),
        ("Guanciale",                "kg",   3, 0.5,16.00,  4),
        ("Salsiccia Fresca",         "kg",   5, 1.5, 8.50,  4),
        # Pesce
        ("Salmone Fresco",           "kg",   5, 1.5,18.00, 11),
        ("Gamberi Freschi",          "kg",   4,   1,22.00, 11),
        ("Calamari",                 "kg",   4,   1,14.00, 11),
        ("Orata Fresca",             "kg",   5, 1.5,16.00, 11),
        ("Branzino Fresco",          "kg",   4,   1,17.50, 11),
        ("Merluzzo",                 "kg",   3,   1,12.00, 11),
        # Latticini
        ("Parmigiano Reggiano",      "kg",   8,   2,14.00,  3),
        ("Pecorino Romano",          "kg",   5, 1.5,12.00,  3),
        ("Mozzarella Fior di Latte", "kg",  10,   3, 7.80,  3),
        ("Ricotta di Vacca",         "kg",   8,   2, 4.50,  3),
        ("Burro",                    "kg",   5, 1.5, 8.00,  3),
        ("Panna da Cucina",          "l",    8,   2, 2.80,  3),
        ("Latte Intero",             "l",   20,   5, 1.40,  3),
        ("Uova Fresche",             "pz", 120,  24, 0.30,  3),
        ("Mascarpone",               "kg",   3,   1, 6.50,  3),
        ("Gorgonzola",               "kg",   2, 0.5,18.00,  3),
        # Spezie
        ("Pepe Nero Macinato",       "kg",   1, 0.2,18.00, 14),
        ("Origano Secco",            "kg", 0.5, 0.1,12.00, 14),
        ("Basilico Secco",           "kg", 0.5, 0.1,14.00, 14),
        ("Rosmarino Secco",          "kg", 0.5, 0.1,10.00, 14),
        ("Timo Secco",               "kg", 0.3,0.05,15.00, 14),
        ("Noce Moscata",             "kg", 0.2,0.05,22.00, 14),
        ("Cannella",                 "kg", 0.2,0.05,20.00, 14),
        ("Curcuma",                  "kg", 0.3,0.05,18.00, 14),
        ("Paprika Dolce",            "kg", 0.5, 0.1,12.00, 14),
        ("Peperoncino Secco",        "kg", 0.3,0.05,16.00, 14),
        # Dolci/panificazione
        ("Lievito di Birra Fresco",  "kg",   1, 0.2, 4.50,  5),
        ("Cacao in Polvere",         "kg",   2, 0.5, 8.50, 13),
        ("Cioccolato Fondente",      "kg",   3, 0.5,12.00, 13),
        ("Miele Millefiori",         "kg",   3, 0.5, 9.50,  0),
        ("Marmellata di Albicocche", "kg",   3, 0.5, 5.50,  0),
        ("Mandorle",                 "kg",   2, 0.5,14.00,  0),
        ("Noci",                     "kg",   2, 0.5,16.00,  0),
        ("Pistacchi",                "kg",   1, 0.2,22.00,  0),
    ],
    "Bevande": [
        ("Acqua Naturale 1.5L",              "pz", 100, 24, 0.45,  1),
        ("Acqua Frizzante 1.5L",             "pz",  80, 24, 0.50,  1),
        ("Acqua Naturale 0.5L",              "pz", 150, 48, 0.40,  1),
        ("Acqua Frizzante 0.5L",             "pz", 120, 48, 0.45,  1),
        ("Succo di Arancia",                 "l",   20,  5, 1.80,  1),
        ("Succo di Mela",                    "l",   15,  4, 1.60,  1),
        ("Succo Multivitaminico",            "l",   10,  3, 2.20,  1),
        ("Coca-Cola 0.33L",                  "pz", 100, 24, 0.80,  1),
        ("Fanta 0.33L",                      "pz",  60, 18, 0.80,  1),
        ("Sprite 0.33L",                     "pz",  60, 18, 0.80,  1),
        ("Te Freddo Limone",                 "pz",  48, 12, 0.90,  1),
        ("Te Freddo Pesca",                  "pz",  48, 12, 0.90,  1),
        ("Caffe in Grani",                   "kg",  10,  2,12.00,  0),
        ("Caffe Macinato",                   "kg",   5,  1,14.00,  0),
        ("Caffe Capsule Nespresso",          "pz", 100, 20, 0.50,  0),
        ("Te Nero in Bustine",               "pz", 100, 20, 0.25,  0),
        ("Te Verde in Bustine",              "pz",  50, 10, 0.30,  0),
        ("Camomilla",                        "pz",  50, 10, 0.25,  0),
        ("Latte di Soia",                    "l",   10,  3, 2.50,  1),
        ("Latte di Avena",                   "l",    8,  2, 2.80,  1),
        ("Birra Lager 0.33L (artigianale)",  "pz", 100, 24, 1.80,  6),
        ("Birra Bionda 0.5L (artigianale)",  "pz",  60, 18, 2.50,  6),
        ("Birra Rossa 0.5L (artigianale)",   "pz",  48, 12, 2.80,  6),
        ("Birra Weizen 0.5L",                "pz",  36, 12, 2.60,  6),
        ("Vino Rosso Chianti DOC",           "bt",  48, 12, 6.50, 12),
        ("Vino Bianco Pinot Grigio DOC",     "bt",  36, 12, 5.80, 12),
        ("Vino Rosato",                      "bt",  24,  6, 5.50, 12),
        ("Prosecco DOC",                     "bt",  30,  8, 7.50, 12),
        ("Champagne Brut",                   "bt",  12,  3,28.00, 12),
        ("Vino da Tavola Rosso (sfuso)",     "l",   30,  8, 2.20, 12),
        ("Amaro alle Erbe",                  "bt",   6,  1,12.00,  7),
        ("Limoncello Artigianale",           "bt",   8,  2, 9.50,  7),
        ("Grappa di Barolo",                 "bt",   4,  1,18.00,  7),
        ("Rum Caraibico",                    "bt",   4,  1,22.00,  7),
        ("Vodka Premium",                    "bt",   4,  1,20.00,  7),
        ("Gin Botanico",                     "bt",   4,  1,24.00,  7),
        ("Whisky Blend",                     "bt",   3,  1,28.00,  7),
        ("Aperol",                           "bt",   6,  1,14.00,  7),
    ],
    "Pulizia": [
        ("Detersivo Piatti Professionale",   "l",  10,  2, 4.50,  8),
        ("Detersivo Lavastoviglie",          "kg", 15,  4, 3.80,  8),
        ("Brillantante Lavastoviglie",       "l",   5,  1, 6.50,  8),
        ("Sale Lavastoviglie",               "kg", 10,  3, 1.80,  8),
        ("Sgrassante Cucina",                "l",   8,  2, 5.20,  8),
        ("Sgrassante Forno (spray)",         "pz", 10,  2, 6.80,  8),
        ("Disincrostante Bagni",             "l",   5,  1, 4.90,  9),
        ("Candeggina Classica",              "l",  10,  3, 1.50,  9),
        ("Ammorbidente",                     "l",   5,  1, 3.50,  8),
        ("Detersivo Panni",                  "kg",  5,  1, 8.50,  8),
        ("Carta Assorbente (rotoli)",        "pz", 50, 10, 0.85,  9),
        ("Carta Igienica (rotoli)",          "pz",100, 24, 0.60,  9),
        ("Carta Forno",                      "pz", 20,  5, 1.80,  9),
        ("Pellicola Trasparente",            "pz", 10,  2, 3.20,  9),
        ("Alluminio da Cucina",              "pz", 10,  2, 3.50,  9),
        ("Sacchi Spazzatura 70L",            "pz",100, 20, 0.25,  9),
        ("Sacchi Spazzatura 110L",           "pz", 50, 10, 0.40,  9),
        ("Guanti in Lattice (coppia)",       "pz", 50, 10, 0.80,  9),
        ("Guanti Monouso (sc. 100)",         "pz", 20,  5, 6.00,  9),
        ("Spugne da Cucina",                 "pz", 30,  8, 0.60,  9),
        ("Panni Microfibra",                 "pz", 20,  5, 2.50,  9),
        ("Detergente Pavimenti",             "l",  10,  2, 3.80,  8),
        ("Lucidante Inox Professionale",     "l",   3,0.5, 9.50,  8),
        ("Igienizzante Mani 500ml",          "pz", 15,  4, 3.50,  9),
        ("Sapone Liquido Mani",              "l",   8,  2, 4.20,  9),
        ("Disinfettante Multiuso",           "l",   5,  1, 8.50,  9),
        ("Deodorante Ambienti (spray)",      "pz", 10,  2, 5.80,  9),
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
#  HELPER
# ─────────────────────────────────────────────────────────────────────────────

def _get_user(email=None):
    """Trova l'utente target. Esce con errore se non trovato."""
    if email:
        user = User.query.filter_by(email=email).first()
        if not user:
            print(f"[ERRORE] Nessun utente con email: {email}")
            sys.exit(1)
        return user

    user = User.query.filter_by(role='owner').first() or User.query.first()
    if not user:
        print("[ERRORE] Nessun utente nel database. Registrati prima sull'app.")
        sys.exit(1)
    return user


def _bar(label, n, total=None):
    suffix = f"/{total}" if total else ""
    print(f"    {label}: {n}{suffix}")


# ─────────────────────────────────────────────────────────────────────────────
#  SEED
# ─────────────────────────────────────────────────────────────────────────────

def seed(user_id):
    """Inserisce fornitori, prodotti e storico consumi realistico."""
    random.seed(42)   # riproducibile

    print(f"\n{'='*58}")
    print(f"  FoodLoop — Seed Data (Fase 40)")
    print(f"  Target user_id: {user_id}")
    print(f"{'='*58}\n")

    # ── Fornitori ────────────────────────────────────────────────────────────
    print("[1/3] Creazione fornitori...")
    created_suppliers = []
    new_sup_count = 0
    for name, contact in SUPPLIERS_DATA:
        existing = Supplier.query.filter_by(name=name, user_id=user_id).first()
        if existing:
            created_suppliers.append(existing)
        else:
            s = Supplier(name=name, contact_info=contact, user_id=user_id)
            db.session.add(s)
            created_suppliers.append(s)
            new_sup_count += 1
    db.session.flush()   # ottieni gli ID
    _bar("Fornitori nuovi", new_sup_count, len(SUPPLIERS_DATA))

    # ── Prodotti ─────────────────────────────────────────────────────────────
    print("[2/3] Creazione prodotti (200 target)...")
    created_products = []
    new_prod_count = 0

    for category, items in PRODUCTS_DATA.items():
        for name, unit, qty_base, threshold, cost_base, sup_idx in items:
            existing = Product.query.filter_by(name=name, user_id=user_id).first()
            if existing:
                created_products.append(existing)
                continue

            # Variazione ±15% su costo e ±25% su quantità
            cost = round(cost_base * random.uniform(0.85, 1.15), 2)
            qty  = round(qty_base  * random.uniform(0.75, 1.25), 2)

            sup = created_suppliers[sup_idx] if sup_idx < len(created_suppliers) else None
            p = Product(
                name=name, quantity=qty, unit=unit,
                min_threshold=threshold, unit_cost=cost,
                user_id=user_id,
                supplier_id=sup.id if sup else None,
            )
            db.session.add(p)
            created_products.append(p)
            new_prod_count += 1

    db.session.flush()
    _bar("Prodotti nuovi", new_prod_count, len(created_products))

    # ── Storico (50 cicli-fattura → ConsumptionLog + WasteLog) ───────────────
    print("[3/3] Generazione storico 6 mesi (50 cicli-fattura)...")

    now        = datetime.utcnow()
    start_date = now - timedelta(days=180)

    # Usa i prodotti alimentari/bevande per i log (non pulizia)
    loggable = [p for p in created_products if p.unit in ('kg', 'l', 'pz', 'bt')][:80]
    if not loggable:
        loggable = created_products[:80]

    log_count   = 0
    waste_count = 0

    for cycle in range(50):
        # Data casuale negli ultimi 6 mesi (con leggero peso verso i giorni recenti)
        weight = random.betavariate(1.5, 1.0)          # leggermente più recente
        event_date = start_date + timedelta(days=int(180 * weight))

        # Ogni ciclo simula una consegna: 4-10 righe
        num_items = random.randint(4, 10)
        batch = random.sample(loggable, min(num_items, len(loggable)))

        for p in batch:
            # Volume consumato: 20-80% della soglia min (realistico per un giorno)
            qty = round(p.min_threshold * random.uniform(0.20, 0.80), 3)
            qty = max(qty, 0.01)

            log = ConsumptionLog(
                user_id=user_id,
                product_id=p.id,
                quantity_used=qty,
                timestamp=event_date + timedelta(hours=random.randint(8, 22),
                                                 minutes=random.randint(0, 59)),
            )
            db.session.add(log)
            log_count += 1

            # 12% di probabilità di generare scarto associato
            if random.random() < 0.12:
                waste_qty  = round(qty * random.uniform(0.05, 0.20), 3)
                cost_lost  = round(waste_qty * p.unit_cost, 2)
                waste = WasteLog(
                    user_id=user_id,
                    product_id=p.id,
                    quantity_wasted=waste_qty,
                    cost_lost=cost_lost,
                    timestamp=event_date + timedelta(hours=random.randint(8, 22)),
                )
                db.session.add(waste)
                waste_count += 1

    db.session.commit()

    _bar("Log consumi", log_count)
    _bar("Log scarti",  waste_count)

    print(f"\n{'='*58}")
    print(f"  Seeding completato con successo!")
    print(f"  Prodotti totali : {len(created_products)}")
    print(f"  Fornitori totali: {len(created_suppliers)}")
    print(f"  ConsumptionLog  : {log_count}")
    print(f"  WasteLog        : {waste_count}")
    print(f"{'='*58}\n")
    print("  Avvia l'app e visita /analytics per ammirare la simulazione.")
    print("  Quando hai finito: python -m src.seed_data --reset\n")


# ─────────────────────────────────────────────────────────────────────────────
#  RESET
# ─────────────────────────────────────────────────────────────────────────────

def reset(user_id):
    """Cancella TUTTI i dati associati a user_id (prodotti, fornitori, log)."""
    waste_count = WasteLog.query.filter_by(user_id=user_id).count()
    log_count   = ConsumptionLog.query.filter_by(user_id=user_id).count()
    prod_count  = Product.query.filter_by(user_id=user_id).count()
    sup_count   = Supplier.query.filter_by(user_id=user_id).count()

    print(f"\n{'='*58}")
    print(f"  FoodLoop — Reset Dati Simulazione")
    print(f"  Target user_id: {user_id}")
    print(f"{'='*58}")
    print(f"\n  Saranno cancellati:")
    print(f"    WasteLog      : {waste_count} righe")
    print(f"    ConsumptionLog: {log_count} righe")
    print(f"    Prodotti      : {prod_count} righe")
    print(f"    Fornitori     : {sup_count} righe")

    confirm = input("\n  Confermi il reset? (digita 'SI' per confermare): ").strip()
    if confirm != "SI":
        print("  Reset annullato.\n")
        return

    # Elimina in ordine di dipendenza FK
    WasteLog.query.filter_by(user_id=user_id).delete()
    ConsumptionLog.query.filter_by(user_id=user_id).delete()
    # Scollega supplier_id prima di cancellare i fornitori
    Product.query.filter_by(user_id=user_id).update({"supplier_id": None})
    db.session.flush()
    Product.query.filter_by(user_id=user_id).delete()
    Supplier.query.filter_by(user_id=user_id).delete()
    db.session.commit()

    print(f"\n  Database ripristinato allo stato pulito.\n")


# ─────────────────────────────────────────────────────────────────────────────
#  ENTRYPOINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="FoodLoop — Seed Data / Reset Script (Fase 40)"
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Cancella tutti i dati di simulazione per l'utente target"
    )
    parser.add_argument(
        "--email", type=str, default=None,
        help="Email dell'utente target (default: primo owner nel DB)"
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        user = _get_user(args.email)
        print(f"\n  Utente: {user.full_name} ({user.email})  [ID: {user.id}]")

        if args.reset:
            reset(user.id)
        else:
            seed(user.id)
