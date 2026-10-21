import os
import sqlite3

from flask import g

DATA_DIR = os.path.abspath(os.environ.get("NK_DATA", os.path.join(os.path.dirname(__file__), "..", "data")))
DB_PATH = os.path.join(DATA_DIR, "nebenkosten.sqlite")

# Jede Migration wird genau einmal ausgeführt (PRAGMA user_version).
MIGRATIONEN = [
    """
    CREATE TABLE benutzer (
        id INTEGER PRIMARY KEY,
        benutzername TEXT NOT NULL UNIQUE COLLATE NOCASE,
        passwort_hash TEXT NOT NULL,
        rolle TEXT NOT NULL DEFAULT 'vermieter',
        vorname TEXT NOT NULL DEFAULT '',
        name TEXT NOT NULL DEFAULT '',
        strasse TEXT NOT NULL DEFAULT '',
        hausnummer TEXT NOT NULL DEFAULT '',
        plz TEXT NOT NULL DEFAULT '',
        ort TEXT NOT NULL DEFAULT '',
        email TEXT NOT NULL DEFAULT '',
        notizen TEXT NOT NULL DEFAULT '',
        foto INTEGER NOT NULL DEFAULT 0,
        erstellt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE einstellung (schluessel TEXT PRIMARY KEY, wert TEXT);
    CREATE TABLE kostenart (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        betrkv_nr TEXT NOT NULL DEFAULT '',
        umlagefaehig INTEGER NOT NULL DEFAULT 1,
        schluessel TEXT NOT NULL DEFAULT 'mea',
        sortierung INTEGER NOT NULL DEFAULT 0,
        aktiv INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE immobilie (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        strasse TEXT NOT NULL DEFAULT '',
        hausnummer TEXT NOT NULL DEFAULT '',
        plz TEXT NOT NULL DEFAULT '',
        ort TEXT NOT NULL DEFAULT '',
        ordner TEXT NOT NULL UNIQUE,
        absender TEXT NOT NULL DEFAULT '',
        kontoinhaber TEXT NOT NULL DEFAULT '',
        iban TEXT NOT NULL DEFAULT '',
        bank TEXT NOT NULL DEFAULT '',
        gesamtflaeche REAL,
        einheiten_gesamt INTEGER,
        notiz TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE wohnung (
        id INTEGER PRIMARY KEY,
        immobilie_id INTEGER REFERENCES immobilie(id) ON DELETE SET NULL,
        eigentuemer_id INTEGER REFERENCES benutzer(id) ON DELETE SET NULL,
        bezeichnung TEXT NOT NULL,
        wohnflaeche REAL NOT NULL DEFAULT 0,
        mea REAL NOT NULL DEFAULT 0,
        mea_basis REAL NOT NULL DEFAULT 1000,
        umlageschluessel TEXT NOT NULL DEFAULT '',
        iban TEXT NOT NULL DEFAULT '',
        notiz TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE zaehler (
        id INTEGER PRIMARY KEY,
        wohnung_id INTEGER REFERENCES wohnung(id) ON DELETE CASCADE,
        immobilie_id INTEGER REFERENCES immobilie(id) ON DELETE CASCADE,
        art TEXT NOT NULL,
        nummer TEXT NOT NULL DEFAULT '',
        eingebaut TEXT,
        ausgebaut TEXT
    );
    CREATE TABLE zaehlerstand (
        id INTEGER PRIMARY KEY,
        zaehler_id INTEGER NOT NULL REFERENCES zaehler(id) ON DELETE CASCADE,
        datum TEXT NOT NULL,
        stand REAL NOT NULL,
        notiz TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE mietverhaeltnis (
        id INTEGER PRIMARY KEY,
        wohnung_id INTEGER NOT NULL REFERENCES wohnung(id) ON DELETE CASCADE,
        nummer INTEGER NOT NULL,
        ordner TEXT NOT NULL,
        von TEXT NOT NULL,
        bis TEXT,
        vorauszahlung_monat REAL NOT NULL DEFAULT 0,
        neue_anschrift TEXT NOT NULL DEFAULT '',
        notiz TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE mieter_person (
        id INTEGER PRIMARY KEY,
        mv_id INTEGER NOT NULL REFERENCES mietverhaeltnis(id) ON DELETE CASCADE,
        vorname TEXT NOT NULL DEFAULT '',
        name TEXT NOT NULL
    );
    CREATE TABLE kosten (
        id INTEGER PRIMARY KEY,
        immobilie_id INTEGER NOT NULL REFERENCES immobilie(id) ON DELETE CASCADE,
        jahr INTEGER NOT NULL,
        wohnung_id INTEGER REFERENCES wohnung(id) ON DELETE CASCADE,
        mv_id INTEGER REFERENCES mietverhaeltnis(id) ON DELETE SET NULL,
        kostenart_id INTEGER NOT NULL REFERENCES kostenart(id),
        betrag REAL NOT NULL DEFAULT 0,
        schluessel TEXT NOT NULL DEFAULT 'mea',
        notiz TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE vorauszahlung (
        id INTEGER PRIMARY KEY,
        jahr INTEGER NOT NULL,
        wohnung_id INTEGER NOT NULL REFERENCES wohnung(id) ON DELETE CASCADE,
        mv_id INTEGER REFERENCES mietverhaeltnis(id) ON DELETE CASCADE,
        betrag REAL NOT NULL
    );
    CREATE TABLE dokument (
        id INTEGER PRIMARY KEY,
        immobilie_id INTEGER NOT NULL REFERENCES immobilie(id) ON DELETE CASCADE,
        jahr INTEGER NOT NULL,
        bereich TEXT NOT NULL,
        mv_id INTEGER REFERENCES mietverhaeltnis(id) ON DELETE SET NULL,
        wohnung_id INTEGER REFERENCES wohnung(id) ON DELETE SET NULL,
        kostenart_id INTEGER REFERENCES kostenart(id) ON DELETE SET NULL,
        titel TEXT NOT NULL,
        pfad TEXT NOT NULL,
        mime TEXT NOT NULL,
        groesse INTEGER NOT NULL DEFAULT 0,
        hochgeladen_von INTEGER REFERENCES benutzer(id) ON DELETE SET NULL,
        hochgeladen_am TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    # 2: Standard-Umlageschlüssel je Immobilie ('' = automatisch)
    """
    ALTER TABLE immobilie ADD COLUMN schluessel TEXT NOT NULL DEFAULT '';
    """,
    # 3: Eigentümer-Abrechnung nur bei WEG; Bestand: WEG, wenn mehr als ein Mietobjekt
    """
    ALTER TABLE immobilie ADD COLUMN weg INTEGER NOT NULL DEFAULT 0;
    UPDATE immobilie SET weg = 1 WHERE (SELECT COUNT(*) FROM wohnung w WHERE w.immobilie_id = immobilie.id) > 1;
    """,
    # 4: Immobilien archivieren (ausgeblendet, Daten bleiben erhalten)
    """
    ALTER TABLE immobilie ADD COLUMN archiviert INTEGER NOT NULL DEFAULT 0;
    """,
]

# Vorbelegte Kostenarten (Name, Nr. § 2 BetrKV, umlagefähig, Standardschlüssel)
STANDARD_KOSTENARTEN = [
    ("Heizkosten", "4", 1, "mea"),
    ("Warmwasser", "5", 1, "mea"),
    ("Allgemeinstrom", "11", 1, "mea"),
    ("Gebäudeversicherung", "13", 1, "mea"),
    ("Haftpflichtversicherung", "13", 1, "mea"),
    ("Hausmeister", "14", 1, "mea"),
    ("Grundsteuer", "1", 1, "mea"),
    ("Schneeräumung / Straßenreinigung", "8", 1, "mea"),
    ("Kanalgebühren / Niederschlagswasser", "3", 1, "mea"),
    ("Wasser / Abwasser", "2", 1, "wasser"),
    ("Müllentsorgung", "8", 1, "mea"),
    ("Gebäudereinigung", "9", 1, "mea"),
    ("Gartenpflege", "10", 1, "mea"),
    ("Schornsteinfeger", "12", 1, "mea"),
    ("Aufzug", "7", 1, "mea"),
    ("Antenne / Breitband", "15", 1, "einheiten"),
    ("Wartung / Betriebskosten", "17", 1, "mea"),
    ("Verwaltung", "", 0, "mea"),
    ("Instandhaltung / Reparaturen", "", 0, "mea"),
]


def verbinden(pfad=None):
    con = sqlite3.connect(pfad or DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def get_db():
    if "db" not in g:
        g.db = verbinden()
    return g.db


def close_db(_exc=None):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = verbinden()
    version = con.execute("PRAGMA user_version").fetchone()[0]
    for i, sql in enumerate(MIGRATIONEN[version:], start=version + 1):
        con.executescript(sql)
        if i == 1:
            con.executemany("INSERT INTO kostenart (name, betrkv_nr, umlagefaehig, schluessel, sortierung) "
                            "VALUES (?, ?, ?, ?, ?)",
                            [(*k, n * 10) for n, k in enumerate(STANDARD_KOSTENARTEN)])
        con.execute(f"PRAGMA user_version = {i}")
        con.commit()
    con.close()
