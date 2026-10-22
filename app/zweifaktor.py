"""Zwei-Faktor-Anmeldung per Authenticator-App (TOTP, RFC 6238) mit einmaligen Notfall-Codes."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from flask import flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from core import NAME, admin_noetig, app, exe, one, row

SCHRITT = 30          # Sekunden je Code
STELLEN = 6
MAX_VERSUCHE = 5
ANZAHL_NOTFALLCODES = 8


# ---------- TOTP ----------

def neues_geheimnis():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(geheimnis, zaehler):
    key = base64.b32decode(geheimnis + "=" * (-len(geheimnis) % 8))
    mac = hmac.new(key, struct.pack(">Q", zaehler), hashlib.sha1).digest()
    o = mac[-1] & 0x0F
    return f"{(struct.unpack('>I', mac[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** STELLEN:0{STELLEN}d}"


def code_pruefen(geheimnis, code, letzter_schritt=0, jetzt=None):
    """Gibt den Zeitschritt des passenden Codes zurück (±1 Schritt Toleranz für Uhrabweichungen), sonst None.
    Schritte bis einschließlich `letzter_schritt` sind verbraucht – derselbe Code gilt nur einmal."""
    code = "".join((code or "").split())
    if not (code.isdigit() and len(code) == STELLEN):
        return None
    t = int((jetzt if jetzt is not None else time.time()) // SCHRITT)
    for s in (t - 1, t, t + 1):
        if s > letzter_schritt and hmac.compare_digest(_hotp(geheimnis, s), code):
            return s
    return None


def otpauth_uri(geheimnis, benutzername):
    konto = quote(f"{NAME}:{benutzername}")
    return f"otpauth://totp/{konto}?secret={geheimnis}&issuer={quote(NAME)}&digits={STELLEN}&period={SCHRITT}"


def notfallcodes_erzeugen():
    """Gibt (Codes zum einmaligen Anzeigen, gespeicherte Hashes) zurück."""
    codes = ["-".join(secrets.token_hex(2) for _ in range(2)) for _ in range(ANZAHL_NOTFALLCODES)]
    return codes, "\n".join(generate_password_hash(c) for c in codes)


def notfallcode_einloesen(benutzer, code):
    code = "".join((code or "").split()).lower()
    hashes = [h for h in (benutzer["totp_notfall"] or "").split("\n") if h]
    for h in hashes:
        if check_password_hash(h, code):
            hashes.remove(h)
            exe("UPDATE benutzer SET totp_notfall = ? WHERE id = ?", ("\n".join(hashes), benutzer["id"]))
            return True
    return False


# ---------- Anmeldung: zweiter Schritt ----------

def zweiten_schritt_starten(benutzer, ziel=""):
    """Nach korrektem Passwort: noch nicht anmelden, sondern den Code abfragen."""
    session.clear()
    session["2fa_uid"] = benutzer["id"]
    session["2fa_ziel"] = ziel
    session["2fa_versuche"] = 0
    return redirect(url_for("login_zweifaktor"))


@app.route("/login/code", methods=["GET", "POST"])
def login_zweifaktor():
    uid = session.get("2fa_uid")
    b = one("SELECT * FROM benutzer WHERE id = ?", (uid,)) if uid else None
    if not b or not b["totp_aktiv"]:
        session.clear()
        return redirect(url_for("login"))
    if request.method == "POST":
        session["2fa_versuche"] = session.get("2fa_versuche", 0) + 1
        eingabe = request.form.get("code", "")
        schritt = code_pruefen(b["totp_geheimnis"], eingabe, b["totp_schritt"])
        if schritt:
            exe("UPDATE benutzer SET totp_schritt = ? WHERE id = ?", (schritt, b["id"]))
        if schritt or notfallcode_einloesen(b, eingabe):
            ziel = session.get("2fa_ziel") or ""
            session.clear()
            session["uid"] = b["id"]
            session.permanent = True
            if not schritt:
                rest = len([h for h in (one("SELECT totp_notfall FROM benutzer WHERE id = ?", (b["id"],))["totp_notfall"]
                                        or "").split("\n") if h])
                flash(f"Mit Notfall-Code angemeldet. Es sind noch {rest} Notfall-Codes übrig.")
            return redirect(ziel if ziel.startswith("/") and not ziel.startswith("//") else url_for("start"))
        if session["2fa_versuche"] >= MAX_VERSUCHE:
            session.clear()
            flash("Zu viele falsche Codes. Bitte erneut anmelden.", "fehler")
            return redirect(url_for("login"))
        flash("Der Code ist falsch oder abgelaufen.", "fehler")
    g.user = None
    return render_template("auth/zweifaktor.html")


# ---------- Profil → Sicherheit ----------

def _passwort_bestaetigen():
    if not check_password_hash(g.user["passwort_hash"], request.form.get("passwort", "")):
        raise ValueError("Das Passwort ist falsch.")


@app.post("/profil/zweifaktor/start")
def zweifaktor_start():
    session["totp_neu"] = neues_geheimnis()
    return redirect(url_for("profil_passwort") + "#zweifaktor")


@app.post("/profil/zweifaktor/abbrechen")
def zweifaktor_abbrechen():
    session.pop("totp_neu", None)
    return redirect(url_for("profil_passwort"))


@app.post("/profil/zweifaktor/bestaetigen")
def zweifaktor_bestaetigen():
    geheimnis = session.get("totp_neu")
    if not geheimnis:
        return redirect(url_for("profil_passwort"))
    schritt = code_pruefen(geheimnis, request.form.get("code"))
    if not schritt:
        raise ValueError("Der Code passt nicht. Bitte den aktuellen Code aus der App eingeben (Uhrzeit des Handys prüfen).")
    codes, hashes = notfallcodes_erzeugen()
    exe("UPDATE benutzer SET totp_geheimnis = ?, totp_aktiv = 1, totp_schritt = ?, totp_notfall = ? WHERE id = ?",
        (geheimnis, schritt, hashes, g.user["id"]))
    session.pop("totp_neu", None)
    flash("Zwei-Faktor-Anmeldung ist aktiv.")
    return render_template("profil/sicherheit.html", bereich="profil_passwort",
                           b=row("SELECT * FROM benutzer WHERE id = ?", (g.user["id"],)), notfallcodes=codes)


@app.post("/profil/zweifaktor/notfallcodes")
def zweifaktor_notfallcodes():
    _passwort_bestaetigen()
    codes, hashes = notfallcodes_erzeugen()
    exe("UPDATE benutzer SET totp_notfall = ? WHERE id = ?", (hashes, g.user["id"]))
    flash("Neue Notfall-Codes erzeugt. Die alten gelten nicht mehr.")
    return render_template("profil/sicherheit.html", bereich="profil_passwort",
                           b=row("SELECT * FROM benutzer WHERE id = ?", (g.user["id"],)), notfallcodes=codes)


@app.post("/profil/zweifaktor/deaktivieren")
def zweifaktor_deaktivieren():
    _passwort_bestaetigen()
    b = g.user
    if not (code_pruefen(b["totp_geheimnis"], request.form.get("code"), b["totp_schritt"])
            or notfallcode_einloesen(b, request.form.get("code"))):
        raise ValueError("Der Code ist falsch.")
    _zuruecksetzen(b["id"])
    flash("Zwei-Faktor-Anmeldung ausgeschaltet.")
    return redirect(url_for("profil_passwort"))


def _zuruecksetzen(uid):
    exe("UPDATE benutzer SET totp_geheimnis = '', totp_aktiv = 0, totp_schritt = 0, totp_notfall = '' WHERE id = ?", (uid,))


@app.post("/einstellungen/admin/vermieter/<int:uid>/zweifaktor-zuruecksetzen")
@admin_noetig
def zweifaktor_admin_zuruecksetzen(uid):
    row("SELECT id FROM benutzer WHERE id = ?", (uid,))
    _zuruecksetzen(uid)
    flash("Zwei-Faktor-Anmeldung zurückgesetzt. Der Benutzer meldet sich jetzt nur mit Passwort an und kann sie neu einrichten.")
    return redirect(url_for("vermieter_bearbeiten", uid=uid))


def qr_svg(text):
    import segno
    return segno.make(text, error="m").svg_inline(scale=1, border=2, omitsize=True)
