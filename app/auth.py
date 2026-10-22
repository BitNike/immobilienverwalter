"""Ersteinrichtung, Anmeldung, Passwort vergessen / Einladung."""
import os

from flask import flash, g, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

import mail
from core import OHNE_ZUGANG, app, exe, one

MIN_PASSWORT = 8


def passwort_pruefen(pw, wiederholung):
    if len(pw) < MIN_PASSWORT:
        raise ValueError(f"Das Passwort muss mindestens {MIN_PASSWORT} Zeichen haben.")
    if pw != wiederholung:
        raise ValueError("Die Passwörter stimmen nicht überein.")
    return generate_password_hash(pw)


def _serializer():
    return URLSafeTimedSerializer(app.secret_key, salt="passwort")


def token_erstellen(benutzer):
    # Fingerabdruck des Hashs: Link wird nach einer Passwortänderung ungültig.
    return _serializer().dumps({"uid": benutzer["id"], "h": benutzer["passwort_hash"][-16:]})


def link_basis():
    return (os.environ.get("APP_URL") or request.url_root).rstrip("/")


def link_senden(benutzer, einladung=False):
    link = link_basis() + url_for("passwort_setzen", token=token_erstellen(benutzer))
    if einladung:
        betreff = "Einladung zum Immobilienverwalter"
        text = (f"Hallo {benutzer['vorname'] or benutzer['benutzername']},\n\n"
                f"für dich wurde ein Zugang angelegt. Benutzername: {benutzer['benutzername']}\n"
                f"Bitte lege über diesen Link dein Passwort fest (7 Tage gültig):\n{link}\n")
    else:
        betreff = "Passwort zurücksetzen"
        text = (f"Hallo {benutzer['vorname'] or benutzer['benutzername']},\n\n"
                f"über diesen Link kannst du ein neues Passwort festlegen (7 Tage gültig):\n{link}\n\n"
                "Falls du das nicht angefordert hast, ignoriere diese E-Mail.\n")
    mail.senden(benutzer["email"], betreff, text)


@app.route("/einrichtung", methods=["GET", "POST"])
def einrichtung():
    """Der erste Benutzer wird Administrator."""
    if one("SELECT id FROM benutzer LIMIT 1"):
        return redirect(url_for("login"))
    if request.method == "POST":
        f = request.form
        name = f.get("benutzername", "").strip()
        if not name:
            raise ValueError("Bitte einen Benutzernamen angeben.")
        uid = exe("INSERT INTO benutzer (benutzername, passwort_hash, rolle, vorname, name, email) "
                  "VALUES (?, ?, 'admin', ?, ?, ?)",
                  (name, passwort_pruefen(f.get("passwort", ""), f.get("passwort2", "")),
                   f.get("vorname", "").strip(), f.get("name", "").strip(), f.get("email", "").strip()))
        session.clear()
        session["uid"] = uid
        session.permanent = True
        flash("Willkommen! Du bist Administrator. Lege jetzt deine erste Immobilie an.")
        return redirect(url_for("start"))
    return render_template("auth/einrichtung.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        b = one("SELECT * FROM benutzer WHERE benutzername = ?", (request.form.get("benutzername", "").strip(),))
        if b and b["rolle"] != OHNE_ZUGANG and b["passwort_hash"] and \
                check_password_hash(b["passwort_hash"], request.form.get("passwort", "")):
            ziel = request.args.get("next") or ""
            if b["totp_aktiv"]:
                from zweifaktor import zweiten_schritt_starten
                return zweiten_schritt_starten(b, ziel)
            session.clear()
            session["uid"] = b["id"]
            session.permanent = True
            return redirect(ziel if ziel.startswith("/") and not ziel.startswith("//") else url_for("start"))
        flash("Benutzername oder Passwort ist falsch.", "fehler")
    return render_template("auth/login.html", smtp=mail.konfiguriert())


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/passwort-vergessen", methods=["GET", "POST"])
def passwort_vergessen():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        b = one("SELECT * FROM benutzer WHERE email = ? COLLATE NOCASE AND rolle <> ?", (email, OHNE_ZUGANG)) \
            if email else None
        if b and mail.konfiguriert():
            try:
                link_senden(b)
            except Exception as e:  # noqa: BLE001 – Fehler dem Nutzer anzeigen
                app.logger.warning("Mailversand fehlgeschlagen: %s", e)
        flash("Falls die E-Mail-Adresse bekannt ist, wurde ein Link zum Zurücksetzen verschickt.")
        return redirect(url_for("login"))
    return render_template("auth/passwort_vergessen.html", smtp=mail.konfiguriert())


@app.route("/passwort-setzen/<token>", methods=["GET", "POST"])
def passwort_setzen(token):
    try:
        daten = _serializer().loads(token, max_age=7 * 24 * 3600)
    except SignatureExpired:
        flash("Der Link ist abgelaufen.", "fehler")
        return redirect(url_for("login"))
    except BadSignature:
        flash("Der Link ist ungültig.", "fehler")
        return redirect(url_for("login"))
    b = one("SELECT * FROM benutzer WHERE id = ?", (daten["uid"],))
    if not b or b["rolle"] == OHNE_ZUGANG or b["passwort_hash"][-16:] != daten["h"]:
        flash("Der Link wurde bereits verwendet.", "fehler")
        return redirect(url_for("login"))
    if request.method == "POST":
        exe("UPDATE benutzer SET passwort_hash = ? WHERE id = ?",
            (passwort_pruefen(request.form.get("passwort", ""), request.form.get("passwort2", "")), b["id"]))
        flash("Passwort gespeichert.")
        if b["totp_aktiv"]:  # Passwort-Link ersetzt nicht den zweiten Faktor
            from zweifaktor import zweiten_schritt_starten
            return zweiten_schritt_starten(b)
        session.clear()
        session["uid"] = b["id"]
        return redirect(url_for("start"))
    g.user = None
    return render_template("auth/passwort_setzen.html", b=b)
