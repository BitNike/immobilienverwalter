"""Flask-App, Datenbank-Helfer, Anmeldung, Rechte und Template-Filter."""
import os
import secrets
from datetime import date
from functools import wraps

from flask import Flask, abort, flash, g, redirect, request, session, url_for

import db
from calc import SCHLUESSEL, de_monate, de_num, parse_date
from icons import ICONS

VERSION = "0.10.1"
NAME = "Immobilienverwalter"
URL = "https://github.com/BitNike/immobilienverwalter"  # Projektseite (Fußzeile des Briefs, Seite „Über“)
ENTWICKLER = "Sascha Benecke"
LIZENZ = "AGPL-3.0"
SPENDEN_URL = "https://www.paypal.com/paypalme/saschabenecke"

app = Flask(__name__)


def _secret_key():
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    pfad = os.path.join(db.DATA_DIR, "secret_key")
    os.makedirs(db.DATA_DIR, exist_ok=True)
    if not os.path.exists(pfad):
        with open(pfad, "w") as f:
            f.write(secrets.token_hex(32))
    with open(pfad) as f:
        return f.read().strip()


app.config.update(
    SECRET_KEY=_secret_key(),
    MAX_CONTENT_LENGTH=30 * 1024 * 1024,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
)
app.teardown_appcontext(db.close_db)
db.init_db()

OHNE_ZUGANG = "ohne_zugang"
ROLLEN = {
    OHNE_ZUGANG: "Ohne Zugang",
    "admin": "Administrator",
    "vermieter_plus": "Vermieter + (darf Zahlen eintragen)",
    "vermieter": "Vermieter (nur lesen)",
}
ZAEHLERARTEN = {"wasser": "Wasser", "strom": "Strom", "gas": "Gas", "waerme": "Wärme"}
EINHEITEN = {"wasser": "m³", "strom": "kWh", "gas": "m³", "waerme": "kWh"}
BEREICHE = {"mieter": "Mieter (Nebenkosten)", "vermieter": "Vermieter (z. B. Steuer)", "mieterordner": "Mieterordner"}


# ---------- Datenbank ----------

def rows(sql, args=()):
    return [dict(r) for r in db.get_db().execute(sql, args).fetchall()]


def one(sql, args=()):
    r = db.get_db().execute(sql, args).fetchone()
    return dict(r) if r else None


def row(sql, args=()):
    r = one(sql, args)
    if r is None:
        abort(404)
    return r


def exe(sql, args=()):
    con = db.get_db()
    cur = con.execute(sql, args)
    con.commit()
    return cur.lastrowid


def einstellung(schluessel, standard=""):
    r = one("SELECT wert FROM einstellung WHERE schluessel = ?", (schluessel,))
    return r["wert"] if r and r["wert"] is not None else standard


def einstellung_setzen(schluessel, wert):
    exe("INSERT INTO einstellung (schluessel, wert) VALUES (?, ?) "
        "ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert", (schluessel, wert))


# ---------- Anmeldung & Rechte ----------

OFFEN = {"login", "login_zweifaktor", "einrichtung", "passwort_vergessen", "passwort_setzen", "static", "logo_datei"}


@app.get("/health")
def gesundheit():
    """Für den Docker-Healthcheck: antwortet ohne Anmeldung, wenn App und Datenbank erreichbar sind."""
    one("SELECT 1 AS ok")
    return {"status": "ok", "version": VERSION}


@app.before_request
def anmeldung_pruefen():
    g.user = None
    if request.endpoint in ("static", "gesundheit"):
        return None
    if not one("SELECT id FROM benutzer LIMIT 1"):
        return None if request.endpoint in ("einrichtung", "logo_datei") else redirect(url_for("einrichtung"))
    if session.get("uid"):
        g.user = one("SELECT * FROM benutzer WHERE id = ?", (session["uid"],))
        if g.user and g.user["rolle"] == OHNE_ZUGANG:  # Zugang wurde entzogen
            g.user = None
            session.clear()
    if g.user is None and request.endpoint not in OFFEN:
        return redirect(url_for("login", next=request.full_path if request.method == "GET" else None))
    return None


def ist_admin():
    return bool(g.user) and g.user["rolle"] == "admin"


def admin_noetig(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not ist_admin():
            abort(403)
        return f(*a, **kw)
    return wrapper


def sichtbare_immobilien(archiv=False):
    if ist_admin():
        return rows("SELECT * FROM immobilie WHERE archiviert = ? ORDER BY name COLLATE NATUERLICH", (int(archiv),))
    return rows("SELECT DISTINCT i.* FROM immobilie i JOIN wohnung w ON w.immobilie_id = i.id "
                "WHERE w.eigentuemer_id = ? AND i.archiviert = ? ORDER BY i.name COLLATE NATUERLICH", (g.user["id"], int(archiv)))


def immobilie_laden(iid):
    i = row("SELECT * FROM immobilie WHERE id = ?", (iid,))
    if not ist_admin() and not one("SELECT 1 FROM wohnung WHERE immobilie_id = ? AND eigentuemer_id = ?",
                                   (iid, g.user["id"])):
        abort(403)
    return i


def wohnungen_der_immobilie(iid):
    sql = "SELECT * FROM wohnung WHERE immobilie_id = ?"
    args = [iid]
    if not ist_admin():
        sql += " AND eigentuemer_id = ?"
        args.append(g.user["id"])
    return rows(sql + " ORDER BY bezeichnung COLLATE NATUERLICH", args)


def wohnung_sichtbar(w):
    return ist_admin() or w["eigentuemer_id"] == g.user["id"]


def wohnung_bearbeitbar(w):
    return ist_admin() or (w["eigentuemer_id"] == g.user["id"] and g.user["rolle"] == "vermieter_plus")


def wohnung_laden(wid, bearbeiten=False):
    w = row("SELECT * FROM wohnung WHERE id = ?", (wid,))
    if not wohnung_sichtbar(w) or (bearbeiten and not wohnung_bearbeitbar(w)):
        abort(403)
    return w


def jahr():
    """Ausgewähltes Abrechnungsjahr (über ?jahr= umschaltbar, in der Sitzung gemerkt)."""
    j = request.args.get("jahr", type=int)
    if j and 1990 <= j <= 2200:
        session["jahr"] = j
    return session.get("jahr") or date.today().year - 1


def zurueck(standard="/"):
    return redirect(request.form.get("next") or request.referrer or standard)


@app.errorhandler(ValueError)
def eingabefehler(e):
    flash(f"Bitte Eingabe prüfen: {e}", "fehler")
    return zurueck()


@app.errorhandler(413)
def zu_gross(_e):
    flash("Die Datei ist zu groß.", "fehler")
    return zurueck()


# ---------- Templates ----------

@app.template_filter("eur")
def f_eur(v):
    return f"{de_num(v or 0)} €"


@app.template_filter("num")
def f_num(v, stellen=2):
    return de_num(v or 0, stellen)


@app.template_filter("monate")
def f_monate(v):
    return de_monate(v or 0)


@app.template_filter("datum")
def f_datum(v, kurz=False):
    d = parse_date(v) if v else None
    return d.strftime("%d.%m.%y" if kurz else "%d.%m.%Y") if d else ""


def person_name(b):
    benutzername = b.get("benutzername", "")
    return " ".join(x for x in (b.get("vorname"), b.get("name")) if x) or \
        ("" if benutzername.startswith("~") else benutzername)


def ablage_kategorien():
    """{schluessel: name} der Ablage-Kategorien in der gepflegten Reihenfolge."""
    return {r["schluessel"]: r["name"] for r in
            rows("SELECT * FROM ablage_kategorie ORDER BY sortierung, name COLLATE NATUERLICH")}


def ablage_kategorie_anlegen(name):
    """Neue Kategorie anlegen bzw. eine gleichnamige wiederverwenden; gibt den Schlüssel zurück."""
    name = " ".join(name.split())
    if not name:
        raise ValueError("Bitte einen Namen für die neue Kategorie angeben.")
    vorhanden = one("SELECT schluessel FROM ablage_kategorie WHERE name = ? COLLATE NOCASE", (name,))
    if vorhanden:
        return vorhanden["schluessel"]
    schluessel = "k" + secrets.token_hex(4)
    sortierung = (one("SELECT MAX(sortierung) AS m FROM ablage_kategorie WHERE schluessel <> 'sonstiges'")["m"] or 0) + 5
    exe("INSERT INTO ablage_kategorie (schluessel, name, sortierung) VALUES (?, ?, ?)", (schluessel, name, sortierung))
    return schluessel


def eigentuemer_anlegen(vals):
    """Eigentümer ohne Zugang: nur Kontaktdaten. Platzhalter-Benutzername (~…) und leeres Passwort,
    Anmeldung und „Passwort vergessen“ sind für diese Gruppe gesperrt."""
    if not (vals.get("vorname") or vals.get("name")):
        raise ValueError("Bitte mindestens den Namen des Eigentümers angeben.")
    return exe(f"INSERT INTO benutzer (benutzername, passwort_hash, rolle, {', '.join(vals)}) "
               f"VALUES (?, '', ?, {', '.join('?' * len(vals))})",
               ["~" + secrets.token_hex(8), OHNE_ZUGANG, *vals.values()])


app.jinja_env.globals.update(
    ICONS=ICONS, ROLLEN=ROLLEN, SCHLUESSEL=SCHLUESSEL, ZAEHLERARTEN=ZAEHLERARTEN, EINHEITEN=EINHEITEN, BEREICHE=BEREICHE,
    ablage_kategorien=lambda: ablage_kategorien(),
    person_name=person_name, NAME=NAME, LIZENZ=LIZENZ, PROJEKT_URL=URL,
)


@app.context_processor
def kontext():
    if not g.get("user"):
        return {"user": None, "ist_admin": False, "logo": logo_info(), "version": VERSION}
    return {
        "user": g.user, "ist_admin": ist_admin(), "logo": logo_info(), "version": VERSION,
        "sidebar_immobilien": sichtbare_immobilien(), "archiv_anzahl": len(sichtbare_immobilien(archiv=True)),
        "jahr": jahr(),
    }


def logo_info():
    return {"typ": einstellung("logo_typ", "standard"), "text": einstellung("logo_text", "Immobilienverwalter"),
            "version": einstellung("logo_version", "0")}
