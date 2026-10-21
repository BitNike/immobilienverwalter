"""Einstellungen (Vermieter, Administration) und Profil."""
import os
import secrets

from flask import abort, flash, g, redirect, render_template, request, send_file, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import dateien
import mail
from auth import link_senden, passwort_pruefen
from calc import SCHLUESSEL, parse_num
from core import (OHNE_ZUGANG, ROLLEN, ZAEHLERARTEN, admin_noetig, app, eigentuemer_anlegen, einstellung,
                  einstellung_setzen, exe, ist_admin, one,
                  row, rows, sichtbare_immobilien, wohnungen_der_immobilie, zurueck)
from immobilien import wohnung_werte, zaehler_aus_formular

PROFIL_FELDER = ("vorname", "name", "strasse", "hausnummer", "plz", "ort", "email")


def profil_werte(mit_notizen=False):
    f = request.form
    vals = {k: f.get(k, "").strip() for k in PROFIL_FELDER}
    if mit_notizen:
        vals["notizen"] = f.get("notizen", "")
    return vals


def zugeordnete_wohnungen(uid):
    return rows("SELECT w.*, i.name AS immobilie FROM wohnung w LEFT JOIN immobilie i ON i.id = w.immobilie_id "
                "WHERE w.eigentuemer_id = ? ORDER BY i.name, w.bezeichnung", (uid,))


# ---------- Einstellungen: Vermieter (für alle sichtbar) ----------

@app.get("/einstellungen")
def einstellungen():
    return redirect(url_for("vermieter_liste"))


@app.get("/einstellungen/vermieter")
def vermieter_liste():
    return render_template("einstellungen/vermieter_liste.html", bereich="vermieter",
                           benutzer=rows("SELECT * FROM benutzer ORDER BY name, vorname, benutzername"))


# ---------- Administration: Vermieter ----------

def _zugangsdaten(f, uid=None):
    """Benutzername und Passwort-Hash für einen Zugang prüfen; None als Hash = Passwort unverändert lassen."""
    name = f.get("benutzername", "").strip()
    if not name or name.startswith("~"):
        raise ValueError("Bitte einen Benutzernamen angeben (darf nicht mit ~ beginnen).")
    if one("SELECT 1 FROM benutzer WHERE benutzername = ? AND id IS NOT ?", (name, uid)):
        raise ValueError("Dieser Benutzername ist bereits vergeben.")
    if f.get("passwort"):
        return name, passwort_pruefen(f["passwort"], f.get("passwort2", ""))
    if f.get("einladen"):
        return name, generate_password_hash(secrets.token_urlsafe(24))
    return name, None


@app.route("/einstellungen/admin/vermieter/neu", methods=["GET", "POST"])
@admin_noetig
def vermieter_neu():
    if request.method == "POST":
        f = request.form
        rolle = f.get("rolle", OHNE_ZUGANG)
        if rolle not in ROLLEN:
            abort(400)
        vals = profil_werte()
        if rolle == OHNE_ZUGANG:
            uid = eigentuemer_anlegen(vals)
        else:
            name, pw_hash = _zugangsdaten(f)
            if not pw_hash:
                raise ValueError("Bitte ein Startpasswort vergeben oder eine Einladung per E-Mail senden.")
            uid = exe(f"INSERT INTO benutzer (benutzername, passwort_hash, rolle, {', '.join(vals)}) "
                      f"VALUES (?, ?, ?, {', '.join('?' * len(vals))})", [name, pw_hash, rolle, *vals.values()])
        if request.files.get("foto") and request.files["foto"].filename:
            dateien.foto_speichern(request.files["foto"], uid)
            exe("UPDATE benutzer SET foto = foto + 1 WHERE id = ?", (uid,))
        if rolle != OHNE_ZUGANG and f.get("einladen"):
            _einladung(uid)
        flash("Vermieter angelegt.")
        return redirect(url_for("vermieter_bearbeiten", uid=uid))
    return render_template("einstellungen/vermieter_form.html", bereich="admin_vermieter", b={}, neu=True,
                           smtp=mail.konfiguriert())


def _einladung(uid):
    b = row("SELECT * FROM benutzer WHERE id = ?", (uid,))
    if not b["email"]:
        flash("Für die Einladung fehlt die E-Mail-Adresse.", "fehler")
        return
    try:
        link_senden(b, einladung=True)
        flash(f"Einladung an {b['email']} gesendet.")
    except Exception as e:  # noqa: BLE001
        flash(f"Einladung konnte nicht gesendet werden: {e}", "fehler")


@app.route("/einstellungen/admin/vermieter/<int:uid>", methods=["GET", "POST"])
@admin_noetig
def vermieter_bearbeiten(uid):
    b = row("SELECT * FROM benutzer WHERE id = ?", (uid,))
    if request.method == "POST":
        f = request.form
        rolle = f.get("rolle", b["rolle"])
        if rolle not in ROLLEN:
            abort(400)
        if b["rolle"] == "admin" and rolle != "admin" and \
                one("SELECT COUNT(*) AS n FROM benutzer WHERE rolle = 'admin'")["n"] <= 1:
            raise ValueError("Es muss mindestens ein Administrator bleiben.")
        if uid == g.user["id"] and rolle == OHNE_ZUGANG:
            raise ValueError("Du kannst dir nicht selbst den Zugang entziehen.")
        vals = profil_werte()
        neuer_zugang = not b["passwort_hash"]
        if rolle == OHNE_ZUGANG:
            if not (vals["vorname"] or vals["name"]):
                raise ValueError("Bitte mindestens den Namen angeben.")
            name = b["benutzername"] if b["benutzername"].startswith("~") else "~" + secrets.token_hex(8)
            exe("UPDATE benutzer SET passwort_hash = '' WHERE id = ?", (uid,))
        else:
            name, pw_hash = _zugangsdaten(f, uid)
            if pw_hash and (f.get("passwort") or neuer_zugang):  # Einladung überschreibt kein bestehendes Passwort
                exe("UPDATE benutzer SET passwort_hash = ? WHERE id = ?", (pw_hash, uid))
            elif neuer_zugang:
                raise ValueError("Für den neuen Zugang bitte ein Passwort vergeben oder eine Einladung senden.")
        exe(f"UPDATE benutzer SET benutzername = ?, rolle = ?, {', '.join(k + ' = ?' for k in vals)} WHERE id = ?",
            [name, rolle, *vals.values(), uid])
        if rolle != OHNE_ZUGANG and f.get("einladen") and neuer_zugang:
            _einladung(uid)
        if request.files.get("foto") and request.files["foto"].filename:
            dateien.foto_speichern(request.files["foto"], uid)
            exe("UPDATE benutzer SET foto = foto + 1 WHERE id = ?", (uid,))
        flash("Gespeichert.")
        return redirect(url_for("vermieter_bearbeiten", uid=uid))
    andere = rows("SELECT w.*, i.name AS immobilie FROM wohnung w LEFT JOIN immobilie i ON i.id = w.immobilie_id "
                  "WHERE w.eigentuemer_id IS NOT ? ORDER BY i.name IS NULL, i.name, w.bezeichnung", (uid,))
    return render_template("einstellungen/vermieter_form.html", bereich="admin_vermieter", b=b, neu=False,
                           smtp=mail.konfiguriert(), wohnungen=zugeordnete_wohnungen(uid), andere=andere)


@app.post("/einstellungen/admin/vermieter/<int:uid>/mietobjekte")
@admin_noetig
def vermieter_mietobjekt(uid):
    """Mietobjekt diesem Eigentümer zuordnen (wid) oder die Zuordnung lösen (loesen)."""
    row("SELECT id FROM benutzer WHERE id = ?", (uid,))
    f = request.form
    if f.get("loesen"):
        exe("UPDATE wohnung SET eigentuemer_id = NULL WHERE id = ? AND eigentuemer_id = ?", (int(f["loesen"]), uid))
    elif f.get("wid"):
        exe("UPDATE wohnung SET eigentuemer_id = ? WHERE id = ?", (uid, int(f["wid"])))
    return redirect(url_for("vermieter_bearbeiten", uid=uid) + "#mietobjekte")


@app.post("/einstellungen/admin/vermieter/<int:uid>/einladung")
@admin_noetig
def vermieter_einladen(uid):
    if row("SELECT rolle FROM benutzer WHERE id = ?", (uid,))["rolle"] == OHNE_ZUGANG:
        raise ValueError("Dieser Eigentümer hat keinen Zugang. Bitte zuerst eine Gruppe mit Zugang wählen.")
    _einladung(uid)
    return redirect(url_for("vermieter_bearbeiten", uid=uid))


@app.post("/einstellungen/admin/vermieter/<int:uid>/loeschen")
@admin_noetig
def vermieter_loeschen(uid):
    if uid == g.user["id"]:
        raise ValueError("Du kannst dich nicht selbst löschen.")
    exe("DELETE FROM benutzer WHERE id = ?", (uid,))
    flash("Vermieter gelöscht. Zugeordnete Mietobjekte sind jetzt ohne Eigentümer.")
    return redirect(url_for("vermieter_liste"))


# ---------- Administration: Mietobjekte (vorgefertigte Wohnungen) ----------

@app.get("/einstellungen/admin/wohnungen")
@admin_noetig
def wohnungen_liste():
    ws = rows("""SELECT w.*, i.name AS immobilie, b.vorname, b.name AS eig_name, b.benutzername
                 FROM wohnung w LEFT JOIN immobilie i ON i.id = w.immobilie_id
                 LEFT JOIN benutzer b ON b.id = w.eigentuemer_id ORDER BY i.name IS NULL, i.name, w.bezeichnung""")
    return render_template("einstellungen/wohnungen_liste.html", bereich="admin_wohnungen", wohnungen=ws)


@app.route("/einstellungen/admin/wohnungen/neu", methods=["GET", "POST"])
@app.route("/einstellungen/admin/wohnungen/<int:wid>", methods=["GET", "POST"])
@admin_noetig
def wohnung_stamm(wid=None):
    w = row("SELECT * FROM wohnung WHERE id = ?", (wid,)) if wid else {"mea_basis": 1000}
    if request.method == "POST":
        vals = wohnung_werte()
        if wid:
            exe(f"UPDATE wohnung SET {', '.join(k + ' = ?' for k in vals)} WHERE id = ?", [*vals.values(), wid])
        else:
            wid = exe(f"INSERT INTO wohnung ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})",
                      list(vals.values()))
        zaehler_aus_formular(wid)
        flash("Mietobjekt gespeichert.")
        return redirect(url_for("wohnung_stamm", wid=wid))
    zaehler = rows("SELECT * FROM zaehler WHERE wohnung_id = ? ORDER BY art, ausgebaut IS NULL, id", (wid,)) if wid else []
    return render_template("einstellungen/wohnung_form.html", bereich="admin_wohnungen", w=w, zaehler=zaehler,
                           immobilien=rows("SELECT * FROM immobilie ORDER BY name"),
                           benutzer=rows("SELECT * FROM benutzer ORDER BY name, vorname"))


@app.post("/einstellungen/admin/wohnungen/<int:wid>/loeschen")
@admin_noetig
def wohnung_stamm_loeschen(wid):
    w = row("SELECT * FROM wohnung WHERE id = ?", (wid,))
    exe("DELETE FROM wohnung WHERE id = ?", (wid,))
    flash(f"Mietobjekt „{w['bezeichnung']}“ gelöscht.")
    ziel = request.form.get("next", "")
    return redirect(ziel if ziel.startswith("/") and not ziel.startswith("//") else url_for("wohnungen_liste"))


# ---------- Administration: Kostenarten ----------

def kostenart_werte():
    f = request.form
    name = f.get("name", "").strip()
    if not name:
        raise ValueError("Bitte einen Namen angeben.")
    schl = f.get("schluessel", "mea")
    if schl not in SCHLUESSEL:
        abort(400)
    return (name, f.get("betrkv_nr", "").strip(), 1 if f.get("umlagefaehig") else 0, schl,
            int(parse_num(f.get("sortierung"), 0)))


@app.route("/einstellungen/admin/kostenarten", methods=["GET", "POST"])
@admin_noetig
def kostenarten_admin():
    if request.method == "POST":
        exe("INSERT INTO kostenart (name, betrkv_nr, umlagefaehig, schluessel, sortierung) VALUES (?, ?, ?, ?, ?)",
            kostenart_werte())
        return redirect(url_for("kostenarten_admin"))
    from betrkv import KOSTENARTEN
    return render_template("einstellungen/kostenarten.html", bereich="admin_kostenarten",
                           kostenarten=rows("SELECT * FROM kostenart ORDER BY aktiv DESC, sortierung, name"),
                           betrkv=KOSTENARTEN)


@app.post("/einstellungen/admin/kostenarten/<int:kid>")
@admin_noetig
def kostenart_speichern(kid):
    exe("UPDATE kostenart SET name = ?, betrkv_nr = ?, umlagefaehig = ?, schluessel = ?, sortierung = ?, aktiv = ? "
        "WHERE id = ?", (*kostenart_werte(), 1 if request.form.get("aktiv") else 0, kid))
    flash("Kostenart gespeichert.")
    return redirect(url_for("kostenarten_admin"))


@app.post("/einstellungen/admin/kostenarten/<int:kid>/loeschen")
@admin_noetig
def kostenart_loeschen(kid):
    if one("SELECT 1 FROM kosten WHERE kostenart_id = ?", (kid,)):
        exe("UPDATE kostenart SET aktiv = 0 WHERE id = ?", (kid,))
        flash("Die Kostenart wird bereits verwendet und wurde deshalb nur deaktiviert.")
    else:
        exe("DELETE FROM kostenart WHERE id = ?", (kid,))
    return redirect(url_for("kostenarten_admin"))


# ---------- Administration: Logo & SMTP ----------

@app.route("/einstellungen/admin/logo", methods=["GET", "POST"])
@admin_noetig
def logo_admin():
    if request.method == "POST":
        f = request.form
        einstellung_setzen("logo_text", f.get("logo_text", "").strip() or "Immobilienverwalter")
        typ = f.get("logo_typ", "standard")
        if typ not in ("standard", "bild", "text"):
            typ = "standard"
        if request.files.get("logo") and request.files["logo"].filename:
            einstellung_setzen("logo_datei", dateien.logo_speichern(request.files["logo"]))
            einstellung_setzen("logo_version", str(int(einstellung("logo_version", "0")) + 1))
            typ = "bild"
        if typ == "bild" and not einstellung("logo_datei"):
            raise ValueError("Bitte zuerst ein Logo hochladen.")
        einstellung_setzen("logo_typ", typ)
        einstellung_setzen("brief_fusszeile", "1" if f.get("brief_fusszeile") else "0")
        hoch = round(parse_num(f.get("brief_anschrift_hoch"), 0.0))
        if not -10 <= hoch <= 30:
            raise ValueError("Die Anschrift lässt sich zwischen -10 und 30 mm verschieben.")
        einstellung_setzen("brief_anschrift_hoch", str(hoch))
        flash("Gespeichert.")
        return redirect(url_for("logo_admin"))
    return render_template("einstellungen/logo.html", bereich="admin_logo", logo_datei=einstellung("logo_datei"),
                           brief_fusszeile=einstellung("brief_fusszeile", "1") == "1",
                           brief_anschrift_hoch=round(parse_num(einstellung("brief_anschrift_hoch", "0"))))


@app.get("/logo")
def logo_datei():
    name = einstellung("logo_datei")
    pfad = os.path.join(dateien.BILD_DIR, name) if name else None
    if not pfad or not os.path.exists(pfad):
        abort(404)
    return send_file(pfad, max_age=0)


@app.route("/einstellungen/admin/smtp", methods=["GET", "POST"])
@admin_noetig
def smtp_admin():
    if request.method == "POST":
        an = request.form.get("an", "").strip() or g.user["email"]
        try:
            mail.senden(an, "Testnachricht Immobilienverwalter", "Der E-Mail-Versand funktioniert.")
            flash(f"Testmail an {an} gesendet.")
        except Exception as e:  # noqa: BLE001
            flash(f"Versand fehlgeschlagen: {e}", "fehler")
        return redirect(url_for("smtp_admin"))
    return render_template("einstellungen/smtp.html", bereich="admin_smtp", k=mail.konfiguration(),
                           konfiguriert=mail.konfiguriert(), app_url=os.environ.get("APP_URL", ""))


# ---------- Profil ----------

@app.route("/profil", methods=["GET", "POST"])
def profil():
    if request.method == "POST":
        vals = profil_werte(mit_notizen=True)
        exe(f"UPDATE benutzer SET {', '.join(k + ' = ?' for k in vals)} WHERE id = ?", [*vals.values(), g.user["id"]])
        if request.files.get("foto") and request.files["foto"].filename:
            dateien.foto_speichern(request.files["foto"], g.user["id"])
            exe("UPDATE benutzer SET foto = foto + 1 WHERE id = ?", (g.user["id"],))
        flash("Profil gespeichert.")
        return redirect(url_for("profil"))
    return render_template("profil/info.html", bereich="profil_info", b=g.user)


@app.get("/profil/immobilien")
def profil_immobilien():
    immobilien = sichtbare_immobilien()
    for i in immobilien:
        i["wohnungen"] = wohnungen_der_immobilie(i["id"])
    return render_template("profil/immobilien.html", bereich="profil_immobilien", immobilien=immobilien)


@app.route("/profil/passwort", methods=["GET", "POST"])
def profil_passwort():
    if request.method == "POST":
        if not check_password_hash(g.user["passwort_hash"], request.form.get("alt", "")):
            raise ValueError("Das aktuelle Passwort ist falsch.")
        exe("UPDATE benutzer SET passwort_hash = ? WHERE id = ?",
            (passwort_pruefen(request.form.get("passwort", ""), request.form.get("passwort2", "")), g.user["id"]))
        flash("Passwort geändert.")
        return redirect(url_for("profil"))
    return render_template("profil/passwort.html", bereich="profil_passwort")


@app.post("/profil/foto/loeschen")
def foto_loeschen():
    uid = int(request.form.get("uid") or g.user["id"])
    if uid != g.user["id"] and not ist_admin():
        abort(403)
    try:
        os.remove(dateien.foto_pfad(uid))
    except FileNotFoundError:
        pass
    exe("UPDATE benutzer SET foto = 0 WHERE id = ?", (uid,))
    return zurueck()


@app.get("/benutzer/<int:uid>/foto")
def foto(uid):
    pfad = dateien.foto_pfad(uid)
    if not os.path.exists(pfad):
        abort(404)
    return send_file(pfad, mimetype="image/jpeg", max_age=0)


app.jinja_env.globals.update(ZAEHLERARTEN=ZAEHLERARTEN)
