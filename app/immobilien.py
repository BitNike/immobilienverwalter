"""Immobilien, Mietobjekte (Wohnungen), Mietverhältnisse, Zähler, Kosten, Vorauszahlungen, Dokumente."""
import os
from datetime import date

from flask import abort, flash, g, redirect, render_template, request, send_file, session, url_for

import dateien
import db
from calc import berechne, de_num, messbeginn, parse_date, parse_mea, parse_num, rund, verbrauch_zeitraum
from core import (BEREICHE, ablage_kategorie_anlegen, ablage_kategorien, ZAEHLERARTEN, admin_noetig, app, eigentuemer_anlegen, exe, immobilie_laden, ist_admin, jahr, one,
                  person_name, row, rows, sichtbare_immobilien, wohnung_bearbeitbar, wohnung_laden,
                  wohnung_sichtbar, wohnungen_der_immobilie, zurueck)

IMMOBILIE_FELDER = ("name", "strasse", "hausnummer", "plz", "ort", "absender", "kontoinhaber", "iban", "bank", "notiz",
                    "schluessel")
WOHNUNG_FELDER = ("bezeichnung", "umlageschluessel", "kontoinhaber", "iban", "bank", "notiz")


# ---------- Hilfen ----------

def mv_personen(mv_id):
    return rows("SELECT * FROM mieter_person WHERE mv_id = ? ORDER BY id", (mv_id,))


def mv_name(mv):
    return ", ".join(person_name(p) for p in mv.get("personen") or []) or "(ohne Namen)"


app.jinja_env.globals.update(mv_name=mv_name)


def kostenarten_aktiv():
    return rows("SELECT * FROM kostenart WHERE aktiv = 1 ORDER BY sortierung, name")


def berechnung(immo, j):
    """Lädt alle Daten einer Immobilie für ein Jahr und berechnet die Verteilung."""
    iid = immo["id"]
    wohnungen = rows("SELECT * FROM wohnung WHERE immobilie_id = ? ORDER BY bezeichnung COLLATE NATUERLICH", (iid,))
    kosten = rows("SELECT k.* FROM kosten k JOIN kostenart ka ON ka.id = k.kostenart_id "
                  "WHERE k.immobilie_id = ? AND k.jahr = ? ORDER BY ka.sortierung, ka.name, k.id", (iid, j))
    kostenarten = {k["id"]: k for k in rows("SELECT * FROM kostenart")}
    mvs = rows("SELECT m.* FROM mietverhaeltnis m JOIN wohnung w ON w.id = m.wohnung_id "
               "WHERE w.immobilie_id = ? ORDER BY m.von", (iid,))
    for mv in mvs:
        mv["personen"] = mv_personen(mv["id"])
    zaehler = rows("SELECT z.* FROM zaehler z JOIN wohnung w ON w.id = z.wohnung_id WHERE w.immobilie_id = ?", (iid,))
    for z in zaehler:
        z["staende"] = [(s["datum"], s["stand"]) for s in
                        rows("SELECT datum, stand FROM zaehlerstand WHERE zaehler_id = ?", (z["id"],))]
    vz = {(r["wohnung_id"], r["mv_id"]): r["betrag"] for r in rows(
        "SELECT v.* FROM vorauszahlung v JOIN wohnung w ON w.id = v.wohnung_id "
        "WHERE w.immobilie_id = ? AND v.jahr = ?", (iid, j))}
    erg = berechne(date(j, 1, 1), date(j, 12, 31), immo, wohnungen, kosten, kostenarten, mvs, zaehler, vz)
    erg["vz_gespeichert"] = set(vz)
    return erg


def standard_schluessel(immo, anzahl_wohnungen):
    """Vorauswahl für neue Gebäudekosten; None = Standard der Kostenart."""
    return immo["schluessel"] or ("flaeche" if anzahl_wohnungen == 1 else None)


def vorhandene_kostenarten(iid, j, wid=None):
    """{kostenart_id: Ort} der Kosten eines Jahres – für die Rückfrage bei doppelter Erfassung."""
    orte = {}
    for k in rows("SELECT k.kostenart_id, k.wohnung_id, w.bezeichnung FROM kosten k "
                  "LEFT JOIN wohnung w ON w.id = k.wohnung_id WHERE k.immobilie_id = ? AND k.jahr = ?", (iid, j)):
        if wid is None or k["wohnung_id"] in (None, wid):
            orte.setdefault(k["kostenart_id"], "als Gebäudekosten" if k["wohnung_id"] is None
                            else f"bei {k['bezeichnung']}")
    return orte


def pruefungen(immo, erg, wids, ganze_immobilie=False):
    """Offene Punkte vor dem Export: 'fehler' verfälschen die Abrechnung, 'hinweis' sollte man ansehen."""
    punkte = []

    def punkt(text, link, art="fehler"):
        punkte.append({"text": text, "link": link, "art": art})

    for gk in erg["gebaeude"]:
        k = gk["kosten"]
        name = f"{gk['kostenart']} ({de_num(k['betrag'])} €)"
        link = url_for("immobilie", iid=immo["id"], bearbeiten=k["id"]) + "#kosten"
        if gk["warnung"]:
            punkt(f"{name}: {gk['warnung']} Der Betrag wird niemandem zugeordnet.", link)
        elif ganze_immobilie and gk["rest"] < 0:
            punkt(f"{name}: Es werden {de_num(-gk['rest'])} € mehr verteilt als vorhanden. "
                  "Bitte MEA bzw. Wohnflächen der Mietobjekte prüfen.", link)
        elif ganze_immobilie and gk["rest"] > 0:
            punkt(f"{name}: {de_num(gk['rest'])} € sind keinem Mietobjekt zugeordnet. "
                  "Fehlen Mietobjekte oder deren MEA bzw. Wohnfläche?", link, "hinweis")
    if ganze_immobilie and immo["weg"]:
        rl = ruecklage(immo["id"], jahr())
        if rl["vorhanden"] and rl["anfang"] is None:
            punkt("Erhaltungsrücklage: Der Anfangsbestand fehlt, der Endbestand stimmt deshalb nicht.",
                  url_for("immobilie", iid=immo["id"]) + "#ruecklage", "hinweis")
    schluessel = {gk["kosten"]["schluessel"] for gk in erg["gebaeude"] if not gk["warnung"]}
    if not immo["iban"] and any(not erg["wohnungen"][i]["wohnung"]["iban"] for i in wids if i in erg["wohnungen"]):
        punkt("Bei der Immobilie ist keine IBAN hinterlegt; im Brief fehlt dann die Bankverbindung.",
              url_for("immobilie", iid=immo["id"], stammdaten=1) + "#stammdaten", "hinweis")

    for wid, r in erg["wohnungen"].items():
        if wid not in wids:
            continue
        w = r["wohnung"]
        stamm = url_for("wohnung_stamm", wid=wid)
        abrechnung = url_for("wohnung", wid=wid) + "#abrechnung"
        if "mea" in schluessel and not w["mea"]:
            punkt(f"{w['bezeichnung']}: Keine MEA hinterlegt. Kosten nach MEA entfallen auf dieses Mietobjekt mit 0 €.",
                  stamm)
        if "wasser" in schluessel and r["wasser"] is not None and r["wasser_ab"]:
            punkt(f"{w['bezeichnung']}: Wasserverbrauch erst ab {r['wasser_ab']:%d.%m.%Y} gemessen, der Zählerstand "
                  "zum Jahresanfang fehlt (z. B. aus der Ablesung zum 31.12. des Vorjahres nachtragen).",
                  url_for("wohnung", wid=wid) + "#zaehler", "hinweis")
        if "flaeche" in schluessel and not w["wohnflaeche"]:
            punkt(f"{w['bezeichnung']}: Keine Wohnfläche hinterlegt. Kosten nach Wohnfläche entfallen auf dieses "
                  "Mietobjekt mit 0 €.", stamm)
        if (immo["weg"] or w["mieter_extern"]) and (wid, None) not in erg["vz_gespeichert"]:
            punkt(f"{w['bezeichnung']}: Das Hausgeld des Eigentümers ist noch nicht eingetragen.",
                  url_for("immobilie", iid=immo["id"]) + "#hausgeld" if immo["weg"] else abrechnung, "hinweis")
        for p in ([] if w["mieter_extern"] else r["parteien"]):
            if (wid, p["mv"]["id"]) not in erg["vz_gespeichert"]:
                punkt(f"{w['bezeichnung']}: Die Vorauszahlung von {mv_name(p['mv'])} ist nur vorgeschlagen "
                      f"({de_num(p['vorauszahlung_soll'])} €) und noch nicht gespeichert.", abrechnung)
        gezaehlt = {}
        for po in r["posten"]:
            gezaehlt[po["kostenart"]] = gezaehlt.get(po["kostenart"], 0) + 1
        for name, n in gezaehlt.items():
            if n > 1:
                punkt(f"{w['bezeichnung']}: „{name}“ ist {n}-mal enthalten. Sind das wirklich verschiedene Rechnungen?",
                      abrechnung, "hinweis")
    return punkte


def zaehler_mit_staenden(sql, args):
    zs = rows(sql, args)
    for z in zs:
        z["staende"] = rows("SELECT * FROM zaehlerstand WHERE zaehler_id = ? ORDER BY datum DESC", (z["id"],))
    return zs


def dokumente_sichtbar(immo_id, j, wohnung_id=None):
    """Dokumente eines Jahres; Nicht-Admins sehen gemeinsame Mieterbelege und die ihrer Wohnungen."""
    docs = rows("""SELECT d.*, ka.name AS kostenart, m.ordner AS mv_ordner, m.wohnung_id AS mv_wohnung
                   FROM dokument d LEFT JOIN kostenart ka ON ka.id = d.kostenart_id
                   LEFT JOIN mietverhaeltnis m ON m.id = d.mv_id
                   WHERE d.immobilie_id = ? AND d.jahr = ? ORDER BY d.bereich, m.ordner, d.titel""", (immo_id, j))
    eigene = None if ist_admin() else {w["id"] for w in wohnungen_der_immobilie(immo_id)}
    erg = []
    for d in docs:
        wid = d["wohnung_id"] or d["mv_wohnung"]
        if wohnung_id is not None and wid not in (None, wohnung_id):
            continue
        if wohnung_id is not None and wid is None and d["bereich"] != "mieter":
            continue
        if eigene is not None and not (wid in eigene or (wid is None and d["bereich"] == "mieter")):
            continue
        erg.append(d)
    return erg


def spalte(immo, aktiv_wohnung=None):
    """Daten für die zweite Spalte (Mietobjekte der Immobilie)."""
    return {"immo": immo, "spalte_wohnungen": wohnungen_der_immobilie(immo["id"]), "aktiv_wohnung": aktiv_wohnung}


def adresse(o):
    zeile1 = " ".join(x for x in (o.get("strasse"), o.get("hausnummer")) if x)
    zeile2 = " ".join(x for x in (o.get("plz"), o.get("ort")) if x)
    return zeile1, zeile2


app.jinja_env.globals.update(adresse=adresse)


# ---------- Start ----------

@app.get("/")
def start():
    immobilien = sichtbare_immobilien()
    for i in immobilien:
        i["wohnungen"] = wohnungen_der_immobilie(i["id"])
    return render_template("start.html", immobilien=immobilien)


@app.get("/archiv")
def archiv():
    immobilien = sichtbare_immobilien(archiv=True)
    for i in immobilien:
        i["wohnungen"] = wohnungen_der_immobilie(i["id"])
    return render_template("start.html", immobilien=immobilien, archiv=True)


# ---------- Immobilie ----------

def immobilie_werte():
    f = request.form
    vals = {k: f.get(k, "").strip() for k in IMMOBILIE_FELDER}
    if not vals["name"]:
        raise ValueError("Bitte einen Namen für die Immobilie angeben.")
    vals["iban"] = vals["iban"].upper()
    if vals["schluessel"] not in ("", "mea", "flaeche", "einheiten"):
        raise ValueError("Unbekannter Umlageschlüssel.")
    vals["weg"] = 1 if f.get("weg") else 0
    vals["gesamtflaeche"] = parse_num(f.get("gesamtflaeche"), None)
    einheiten = parse_num(f.get("einheiten_gesamt"), None)
    vals["einheiten_gesamt"] = int(einheiten) if einheiten else None
    return vals


@app.route("/immobilien/neu", methods=["GET", "POST"])
@admin_noetig
def immobilie_neu():
    if request.method == "POST":
        vals = immobilie_werte()
        basis, n = dateien.ordnername(vals["name"]), 2
        vals["ordner"] = basis
        while one("SELECT 1 FROM immobilie WHERE ordner = ?", (vals["ordner"],)):
            vals["ordner"] = f"{basis} ({n})"
            n += 1
        iid = exe(f"INSERT INTO immobilie ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})",
                  list(vals.values()))
        _dokumente_hochladen(iid)
        flash("Immobilie angelegt. Füge jetzt über + in der mittleren Spalte die Mietobjekte hinzu.")
        return redirect(url_for("immobilie", iid=iid))
    return render_template("immobilie_neu.html", kostenarten=kostenarten_aktiv())


@app.get("/immobilien/<int:iid>")
def immobilie(iid):
    immo = immobilie_laden(iid)
    j = jahr()
    erg = berechnung(immo, j)
    eigene = {w["id"] for w in wohnungen_der_immobilie(iid)}
    verteilung = [r for wid, r in erg["wohnungen"].items() if wid in eigene]
    for r in verteilung:
        r["eigentuemer"] = one("SELECT * FROM benutzer WHERE id = ?", (r["wohnung"]["eigentuemer_id"],))
    vorjahr_vorhanden = not erg["gebaeude"] and one(
        "SELECT 1 FROM kosten WHERE immobilie_id = ? AND jahr = ?", (iid, j - 1))
    hauptzaehler = zaehler_mit_staenden("SELECT * FROM zaehler WHERE immobilie_id = ? "
                                        "ORDER BY art, ausgebaut IS NULL, bezeichnung COLLATE NATUERLICH, id", (iid,))
    hauptverbrauch = []
    for art in ZAEHLERARTEN:
        uhren = [{**z, "staende": [(s["datum"], s["stand"]) for s in z["staende"]]}
                 for z in hauptzaehler if z["art"] == art]
        if uhren:
            hauptverbrauch.append({"art": art, "anzahl": sum(1 for z in uhren if not z["ausgebaut"]),
                                   "verbrauch": verbrauch_zeitraum(uhren, date(j, 1, 1), date(j, 12, 31)),
                                   "ab": messbeginn(uhren, date(j, 1, 1), date(j, 12, 31))})
    mit_uhr = [r["wasser"] for r in erg["wohnungen"].values() if r["wasser"] is not None]
    wohnungen_wasser = sum(mit_uhr) if mit_uhr else None
    mvs = rows("SELECT m.*, w.bezeichnung AS wohnung FROM mietverhaeltnis m JOIN wohnung w ON w.id = m.wohnung_id "
               "WHERE w.immobilie_id = ? ORDER BY m.nummer", (iid,))
    for mv in mvs:
        mv["personen"] = mv_personen(mv["id"])
    mea = [r["wohnung"] for r in verteilung if r["wohnung"]["mea"]]
    mea_summe = {"anteil": sum(w["mea"] / w["mea_basis"] for w in mea if w["mea_basis"]),
                 "basen": {w["mea_basis"] for w in mea}} if mea else None
    buchungen = rows("SELECT b.*, ka.name AS kostenart, ka.ruecklage AS zufuehrung FROM buchung b "
                     "LEFT JOIN kostenart ka ON ka.id = b.kostenart_id WHERE b.immobilie_id = ? AND b.jahr = ? "
                     "ORDER BY b.datum IS NULL, b.datum DESC, b.id DESC", (iid, j))
    belege = {}
    for b in buchungen:
        if b["kosten_id"]:
            belege[b["kosten_id"]] = belege.get(b["kosten_id"], 0) + 1
    vorlage = dict(session.get("buchung_vorlage") or {})
    if not (vorlage.get("datum") or "").startswith(str(j)):
        vorlage["datum"] = date.today().isoformat() if date.today().year == j else ""
    umfang = one("SELECT (SELECT COUNT(*) FROM wohnung WHERE immobilie_id = :i) AS wohnungen, "
                 "(SELECT COUNT(*) FROM mietverhaeltnis m JOIN wohnung w ON w.id = m.wohnung_id WHERE w.immobilie_id = :i) AS mieter, "
                 "(SELECT COUNT(*) FROM kosten WHERE immobilie_id = :i) AS kosten, "
                 "(SELECT COUNT(*) FROM dokument WHERE immobilie_id = :i) + "
                 "(SELECT COUNT(*) FROM ablage WHERE immobilie_id = :i) AS dokumente", {"i": iid})
    return render_template("immobilie.html", **spalte(immo), erg=erg, verteilung=verteilung, mea_summe=mea_summe,
                           umfang=umfang, hauptverbrauch=hauptverbrauch, wohnungen_wasser=wohnungen_wasser,
                           pruefung=pruefungen(immo, erg, eigene, ganze_immobilie=ist_admin()),
                           buchungen=buchungen, belege=belege, vorlage=vorlage, BEZAHLT=BEZAHLT,
                           offen_bar=[b for b in buchungen if b["art"] == "ausgabe" and b["bezahlt"] == "bar"
                                      and not b["erstattet"]],
                           rl=ruecklage(iid, j),
                           vorjahr_vorhanden=vorjahr_vorhanden, kostenarten=kostenarten_aktiv(),
                           dokumente=dokumente_sichtbar(iid, j), hauptzaehler=hauptzaehler, mvs=mvs,
                           ablage=ablage_sichtbar(iid),
                           wohnungen=rows("SELECT * FROM wohnung WHERE immobilie_id = ? ORDER BY bezeichnung COLLATE NATUERLICH", (iid,)))


@app.post("/immobilien/<int:iid>/stammdaten")
@admin_noetig
def immobilie_speichern(iid):
    vals = immobilie_werte()
    exe(f"UPDATE immobilie SET {', '.join(k + ' = ?' for k in vals)} WHERE id = ?", [*vals.values(), iid])
    flash("Immobilie gespeichert.")
    return redirect(url_for("immobilie", iid=iid))


@app.post("/immobilien/<int:iid>/loeschen")
@admin_noetig
def immobilie_loeschen(iid):
    immo = row("SELECT * FROM immobilie WHERE id = ?", (iid,))
    con = db.get_db()
    con.execute("DELETE FROM wohnung WHERE immobilie_id = ?", (iid,))  # mit Mietern, Zählern, Kosten (CASCADE)
    con.execute("DELETE FROM immobilie WHERE id = ?", (iid,))
    con.commit()
    flash(f"Immobilie „{immo['name']}“ mit allen Mietobjekten gelöscht. Hochgeladene Dateien liegen weiterhin im "
          f"Dokumentenordner „{immo['ordner']}“ und können dort von Hand entfernt werden.")
    return redirect(url_for("start"))


@app.post("/immobilien/<int:iid>/archiv")
@admin_noetig
def immobilie_archivieren(iid):
    archiviert = 1 if request.form.get("archiviert") == "1" else 0
    exe("UPDATE immobilie SET archiviert = ? WHERE id = ?", (archiviert, iid))
    flash("Immobilie archiviert. Du findest sie links unter „Archiv“." if archiviert else "Immobilie wiederhergestellt.")
    return redirect(url_for("immobilie", iid=iid))


# ---------- Kosten ----------

def _kostenart_id(f):
    kid = int(f.get("kostenart_id") or 0)
    row("SELECT id FROM kostenart WHERE id = ?", (kid,))
    return kid


@app.post("/wohnungen/<int:wid>/kosten")
def wohnung_kosten_neu(wid):
    w = wohnung_laden(wid, bearbeiten=True)
    if not w["immobilie_id"]:
        abort(400)
    f = request.form
    mv_id = int(f["mv_id"]) if f.get("mv_id") else None
    if mv_id:
        row("SELECT id FROM mietverhaeltnis WHERE id = ? AND wohnung_id = ?", (mv_id, wid))
    exe("INSERT INTO kosten (immobilie_id, jahr, wohnung_id, mv_id, kostenart_id, betrag, notiz) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (w["immobilie_id"], jahr(), wid, mv_id, _kostenart_id(f), parse_num(f.get("betrag")),
         f.get("notiz", "").strip()))
    return redirect(url_for("wohnung", wid=wid) + "#abrechnung")


def _kosten_recht(k):
    if k["wohnung_id"]:
        wohnung_laden(k["wohnung_id"], bearbeiten=True)
    elif not ist_admin():
        abort(403)


@app.post("/kosten/<int:kid>")
def kosten_speichern(kid):
    k = row("SELECT * FROM kosten WHERE id = ?", (kid,))
    _kosten_recht(k)
    f = request.form
    schl = f.get("schluessel", k["schluessel"])
    if schl not in ("mea", "flaeche", "einheiten", "wasser"):
        raise ValueError("Unbekannter Umlageschlüssel.")
    kostenart_id = _kostenart_id(f) if f.get("kostenart_id") else k["kostenart_id"]
    mv_id = k["mv_id"]
    if k["wohnung_id"] and "mv_id" in f:
        mv_id = int(f["mv_id"]) if f["mv_id"] else None
        if mv_id:
            row("SELECT id FROM mietverhaeltnis WHERE id = ? AND wohnung_id = ?", (mv_id, k["wohnung_id"]))
    # Gebäudekosten haben keinen eigenen Betrag mehr, er ist die Summe ihrer Buchungen.
    betrag = parse_num(f.get("betrag")) if k["wohnung_id"] else k["betrag"]
    exe("UPDATE kosten SET kostenart_id = ?, betrag = ?, schluessel = ?, mv_id = ?, notiz = ? WHERE id = ?",
        (kostenart_id, betrag, schl, mv_id, f.get("notiz", k["notiz"] or "").strip(), kid))
    exe("UPDATE buchung SET kostenart_id = ? WHERE kosten_id = ?", (kostenart_id, kid))
    return zurueck()


@app.post("/kosten/<int:kid>/loeschen")
def kosten_loeschen(kid):
    k = row("SELECT * FROM kosten WHERE id = ?", (kid,))
    _kosten_recht(k)
    exe("DELETE FROM kosten WHERE id = ?", (kid,))
    return zurueck()


@app.post("/immobilien/<int:iid>/vorjahr")
@admin_noetig
def vorjahr_uebernehmen(iid):
    j = jahr()
    con = db.get_db()
    con.execute("""INSERT INTO kosten (immobilie_id, jahr, wohnung_id, mv_id, kostenart_id, betrag, schluessel, notiz)
                   SELECT immobilie_id, ?, wohnung_id, NULL, kostenart_id, 0, schluessel, notiz
                   FROM kosten WHERE immobilie_id = ? AND jahr = ? AND mv_id IS NULL ORDER BY id""",
                (j, iid, j - 1))
    con.commit()
    flash(f"Kostenarten aus {j - 1} übernommen (Beträge auf 0). Die Beträge ergeben sich aus den Buchungen.")
    return redirect(url_for("immobilie", iid=iid) + "#kosten")


# ---------- Buchungen (Belege) ----------

BEZAHLT = {"konto": "Konto", "bar": "Bar ausgelegt"}


def kostenposition(immo, j, kostenart_id):
    """Gebäudekosten-Position der Kostenart im Jahr; fehlt sie, wird sie mit dem passenden Schlüssel angelegt."""
    k = one("SELECT id FROM kosten WHERE immobilie_id = ? AND jahr = ? AND kostenart_id = ? AND wohnung_id IS NULL "
            "ORDER BY id", (immo["id"], j, kostenart_id))
    if k:
        return k["id"]
    ka = row("SELECT * FROM kostenart WHERE id = ?", (kostenart_id,))
    anzahl = one("SELECT COUNT(*) AS n FROM wohnung WHERE immobilie_id = ?", (immo["id"],))["n"]
    schl = ka["schluessel"] if ka["schluessel"] == "wasser" else standard_schluessel(immo, anzahl) or ka["schluessel"]
    return exe("INSERT INTO kosten (immobilie_id, jahr, kostenart_id, betrag, schluessel) VALUES (?, ?, ?, 0, ?)",
               (immo["id"], j, kostenart_id, schl))


def kosten_aus_buchungen(kid):
    """Betrag der Kostenposition = Summe ihrer Buchungen (Einnahmen mindern); ohne Buchungen fällt sie weg."""
    s = one("SELECT COUNT(*) AS n, SUM(CASE art WHEN 'einnahme' THEN -betrag ELSE betrag END) AS summe "
            "FROM buchung WHERE kosten_id = ?", (kid,))
    if s["n"]:
        exe("UPDATE kosten SET betrag = ? WHERE id = ?", (rund(s["summe"]), kid))
    else:
        exe("DELETE FROM kosten WHERE id = ?", (kid,))


def buchung_werte():
    f = request.form
    vals = {"datum": f.get("datum") or None, "text": f.get("text", "").strip(), "art": f.get("art"),
            "betrag": parse_num(f.get("betrag")), "bezahlt": f.get("bezahlt", "konto")}
    if not vals["text"]:
        raise ValueError("Bitte eine Beschreibung angeben, z. B. „Lampe Flur Haus 2“.")
    if vals["art"] not in ("ausgabe", "einnahme"):
        raise ValueError("Bitte Ausgabe oder Einnahme wählen.")
    if not vals["betrag"]:
        raise ValueError("Bitte einen Betrag angeben.")
    if vals["bezahlt"] not in BEZAHLT:
        raise ValueError("Bitte angeben, wie bezahlt wurde.")
    ziel = f.get("ziel", "")
    if not ziel:
        raise ValueError("Bitte eine Kostenart oder die Erhaltungsrücklage wählen.")
    vals["kostenart_id"] = None if ziel == "ruecklage" else _kostenart_id({"kostenart_id": ziel})
    vals["erstattet"] = (f.get("erstattet") or None) if vals["bezahlt"] == "bar" and vals["art"] == "ausgabe" else None
    return vals


def _beleg_speichern(immo, j, vals):
    """Optionaler Beleg (Foto oder PDF) landet als Vermieter-Dokument des Jahres."""
    d = request.files.get("beleg")
    if not d or not d.filename:
        return None
    pfad, mime, groesse = dateien.dokument_speichern(d, os.path.join(immo["ordner"], str(j), "Vermieter"))
    return exe("INSERT INTO dokument (immobilie_id, jahr, bereich, kostenart_id, titel, pfad, mime, groesse, "
               "hochgeladen_von) VALUES (?, ?, 'vermieter', ?, ?, ?, ?, ?, ?)",
               (immo["id"], j, vals["kostenart_id"], vals["text"], pfad, mime, groesse, g.user["id"]))


@app.post("/immobilien/<int:iid>/buchungen")
@admin_noetig
def buchung_neu(iid):
    immo = row("SELECT * FROM immobilie WHERE id = ?", (iid,))
    j = jahr()
    vals = buchung_werte()
    if not vals["datum"]:
        raise ValueError("Bitte das Datum des Belegs angeben.")
    vals["kosten_id"] = kostenposition(immo, j, vals["kostenart_id"]) if vals["kostenart_id"] else None
    vals["dokument_id"] = _beleg_speichern(immo, j, vals)
    exe(f"INSERT INTO buchung (immobilie_id, jahr, {', '.join(vals)}) VALUES (?, ?, {', '.join('?' * len(vals))})",
        [iid, j, *vals.values()])
    if vals["kosten_id"]:
        kosten_aus_buchungen(vals["kosten_id"])
    # Für die nächste Zeile vorbelegen, damit mehrere Belege schnell hintereinander gehen
    session["buchung_vorlage"] = {"datum": vals["datum"], "art": vals["art"], "bezahlt": vals["bezahlt"],
                                  "ziel": str(vals["kostenart_id"] or "ruecklage")}
    return redirect(url_for("immobilie", iid=iid, neu=1) + "#buchungen")


@app.post("/buchungen/<int:bid>")
@admin_noetig
def buchung_speichern(bid):
    b = row("SELECT * FROM buchung WHERE id = ?", (bid,))
    immo = row("SELECT * FROM immobilie WHERE id = ?", (b["immobilie_id"],))
    vals = buchung_werte()
    vals["kosten_id"] = kostenposition(immo, b["jahr"], vals["kostenart_id"]) if vals["kostenart_id"] else None
    dok = _beleg_speichern(immo, b["jahr"], vals)
    if dok:
        vals["dokument_id"] = dok
    exe(f"UPDATE buchung SET {', '.join(k + ' = ?' for k in vals)} WHERE id = ?", [*vals.values(), bid])
    if vals["kosten_id"]:
        kosten_aus_buchungen(vals["kosten_id"])
    if b["kosten_id"] and b["kosten_id"] != vals["kosten_id"]:
        kosten_aus_buchungen(b["kosten_id"])
    return redirect(url_for("immobilie", iid=immo["id"]) + "#buchungen")


@app.post("/buchungen/<int:bid>/erstattet")
@admin_noetig
def buchung_erstattet(bid):
    b = row("SELECT * FROM buchung WHERE id = ?", (bid,))
    exe("UPDATE buchung SET erstattet = ? WHERE id = ?", (date.today().isoformat(), bid))
    return redirect(url_for("immobilie", iid=b["immobilie_id"]) + "#buchungen")


@app.post("/buchungen/<int:bid>/loeschen")
@admin_noetig
def buchung_loeschen(bid):
    b = row("SELECT * FROM buchung WHERE id = ?", (bid,))
    exe("DELETE FROM buchung WHERE id = ?", (bid,))
    if b["kosten_id"]:
        kosten_aus_buchungen(b["kosten_id"])
    return redirect(url_for("immobilie", iid=b["immobilie_id"]) + "#buchungen")


# ---------- Erhaltungsrücklage ----------

def ruecklage(iid, j):
    """Entwicklung der Erhaltungsrücklage im Jahr j (Vermögensbericht der WEG). Der Anfangsbestand ist eingetragen
    oder wird ab dem letzten eingetragenen Jahr fortgeschrieben; None, wenn noch nie einer eingetragen wurde."""
    def bewegungen(jj):
        zufuehrung = one("SELECT COALESCE(SUM(k.betrag), 0) AS s FROM kosten k JOIN kostenart ka ON ka.id = k.kostenart_id "
                         "WHERE k.immobilie_id = ? AND k.jahr = ? AND k.wohnung_id IS NULL AND ka.ruecklage = 1",
                         (iid, jj))["s"]
        buchungen = rows("SELECT * FROM buchung WHERE immobilie_id = ? AND jahr = ? AND kostenart_id IS NULL "
                         "ORDER BY datum IS NULL, datum, id", (iid, jj))
        return zufuehrung, buchungen

    def saldo(zufuehrung, buchungen):
        return zufuehrung + sum(b["betrag"] if b["art"] == "einnahme" else -b["betrag"] for b in buchungen)

    basis = one("SELECT * FROM ruecklage_bestand WHERE immobilie_id = ? AND jahr <= ? ORDER BY jahr DESC LIMIT 1",
                (iid, j))
    anfang = None
    if basis:
        anfang = basis["betrag"]
        for jj in range(basis["jahr"], j):
            anfang += saldo(*bewegungen(jj))
    zufuehrung, buchungen = bewegungen(j)
    einnahmen = [b for b in buchungen if b["art"] == "einnahme"]
    entnahmen = [b for b in buchungen if b["art"] == "ausgabe"]
    return {"anfang": None if anfang is None else rund(anfang), "eingetragen": bool(basis) and basis["jahr"] == j,
            "zufuehrung": rund(zufuehrung), "einnahmen": einnahmen, "entnahmen": entnahmen,
            "summe_einnahmen": rund(sum(b["betrag"] for b in einnahmen)),
            "summe_entnahmen": rund(sum(b["betrag"] for b in entnahmen)),
            "ende": rund((anfang or 0) + saldo(zufuehrung, buchungen)),
            "vorhanden": bool(basis or zufuehrung or buchungen)}


@app.post("/immobilien/<int:iid>/ruecklage")
@admin_noetig
def ruecklage_speichern(iid):
    row("SELECT id FROM immobilie WHERE id = ?", (iid,))
    j = jahr()
    wert = request.form.get("anfang", "").strip()
    exe("DELETE FROM ruecklage_bestand WHERE immobilie_id = ? AND jahr = ?", (iid, j))
    if wert:
        exe("INSERT INTO ruecklage_bestand (immobilie_id, jahr, betrag) VALUES (?, ?, ?)", (iid, j, parse_num(wert)))
    flash("Anfangsbestand der Rücklage gespeichert." if wert else "Anfangsbestand wird aus dem Vorjahr fortgeschrieben.")
    return redirect(url_for("immobilie", iid=iid) + "#ruecklage")


# ---------- Mietobjekte ----------

def wohnung_werte():
    f = request.form
    vals = {k: f.get(k, "").strip() for k in WOHNUNG_FELDER}
    if not vals["bezeichnung"]:
        raise ValueError("Bitte eine Bezeichnung angeben, z. B. „1. OG links“.")
    vals["iban"] = vals["iban"].upper()
    vals["wohnflaeche"] = parse_num(f.get("wohnflaeche"))
    vals["mieter_extern"] = 1 if f.get("mieter_extern") else 0
    mea, basis = parse_mea(f.get("mea"))
    vals["mea"] = mea
    vals["mea_basis"] = basis or parse_num(f.get("mea_basis"), 1000.0) or 1000.0
    eig = f.get("eigentuemer_id")
    if eig == "neu":
        eig = eigentuemer_anlegen({k: f.get("neu_" + k, "").strip()
                                   for k in ("vorname", "name", "strasse", "hausnummer", "plz", "ort", "email")})
    vals["eigentuemer_id"] = int(eig) if eig else None
    if "immobilie_id" in f:
        vals["immobilie_id"] = int(f["immobilie_id"]) if f["immobilie_id"] else None
    return vals


def zaehler_aus_formular(wid):
    """Felder wasser_nummer / strom_nummer / gas_nummer aus dem Wohnungsformular anlegen."""
    for art in ZAEHLERARTEN:
        nummer = request.form.get(f"{art}_nummer", "").strip()
        if nummer and not one("SELECT 1 FROM zaehler WHERE wohnung_id = ? AND art = ? AND ausgebaut IS NULL",
                              (wid, art)):
            exe("INSERT INTO zaehler (wohnung_id, art, nummer) VALUES (?, ?, ?)", (wid, art, nummer))


@app.route("/immobilien/<int:iid>/wohnungen/neu", methods=["GET", "POST"])
@admin_noetig
def wohnung_hinzufuegen(iid):
    immo = row("SELECT * FROM immobilie WHERE id = ?", (iid,))
    if request.method == "POST":
        if request.form.get("vorhandene"):
            wid = int(request.form["vorhandene"])
            exe("UPDATE wohnung SET immobilie_id = ? WHERE id = ? AND immobilie_id IS NULL", (iid, wid))
        else:
            vals = wohnung_werte()
            vals["immobilie_id"] = iid
            wid = exe(f"INSERT INTO wohnung ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})",
                      list(vals.values()))
            zaehler_aus_formular(wid)
        return redirect(url_for("wohnung", wid=wid))
    frei = rows("SELECT * FROM wohnung WHERE immobilie_id IS NULL ORDER BY bezeichnung COLLATE NATUERLICH")
    return render_template("wohnung_neu.html", **spalte(immo), frei=frei,
                           benutzer=rows("SELECT * FROM benutzer ORDER BY name, vorname"))


@app.get("/wohnungen/<int:wid>")
def wohnung(wid):
    w = wohnung_laden(wid)
    if not w["immobilie_id"]:
        flash("Dieses Mietobjekt ist keiner Immobilie zugeordnet.", "fehler")
        return redirect(url_for("wohnung_stamm", wid=wid))
    immo = row("SELECT * FROM immobilie WHERE id = ?", (w["immobilie_id"],))
    j = jahr()
    erg = berechnung(immo, j)
    r = erg["wohnungen"][wid]
    mvs = rows("SELECT * FROM mietverhaeltnis WHERE wohnung_id = ? ORDER BY von DESC", (wid,))
    for mv in mvs:
        mv["personen"] = mv_personen(mv["id"])
        a, b = parse_date(mv["von"]), parse_date(mv["bis"])
        mv["im_jahr"] = a <= date(j, 12, 31) and (b is None or b >= date(j, 1, 1))
    direkt = {k["id"]: k for k in rows("SELECT * FROM kosten WHERE wohnung_id = ? AND jahr = ?", (wid, j))}
    return render_template(
        "wohnung.html", **spalte(immo, wid), w=w, r=r, erg=erg, mvs=mvs, direkt=direkt,
        pruefung=pruefungen(immo, erg, {wid}), vorhanden=vorhandene_kostenarten(immo["id"], j, wid),
        darf=wohnung_bearbeitbar(w), kostenarten=kostenarten_aktiv(),
        eigentuemer=one("SELECT * FROM benutzer WHERE id = ?", (w["eigentuemer_id"],)),
        zaehler=zaehler_mit_staenden("SELECT * FROM zaehler WHERE wohnung_id = ? ORDER BY art, ausgebaut IS NULL, id",
                                     (wid,)),
        dokumente=dokumente_sichtbar(immo["id"], j, wid), ablage=ablage_sichtbar(immo["id"], wid),
        vz_gespeichert={x["mv_id"]: x["betrag"] for x in
                        rows("SELECT * FROM vorauszahlung WHERE wohnung_id = ? AND jahr = ?", (wid, j))})


@app.post("/wohnungen/<int:wid>/entfernen")
@admin_noetig
def wohnung_entfernen(wid):
    w = row("SELECT * FROM wohnung WHERE id = ?", (wid,))
    exe("UPDATE wohnung SET immobilie_id = NULL WHERE id = ?", (wid,))
    flash("Mietobjekt aus der Immobilie entfernt. Es bleibt unter Einstellungen → Mietobjekte erhalten.")
    return redirect(url_for("immobilie", iid=w["immobilie_id"]))


# ---------- Mietverhältnisse ----------

def mv_werte():
    f = request.form
    von, bis = f.get("von", ""), f.get("bis", "") or None
    if not von:
        raise ValueError("Bitte das Einzugsdatum angeben.")
    if bis and parse_date(bis) < parse_date(von):
        raise ValueError("Der Auszug liegt vor dem Einzug.")
    return {"von": von, "bis": bis, "vorauszahlung_monat": parse_num(f.get("vorauszahlung_monat")),
            "neue_anschrift": f.get("neue_anschrift", "").strip(), "notiz": f.get("notiz", "").strip()}


@app.post("/wohnungen/<int:wid>/mieter")
def mv_neu(wid):
    w = wohnung_laden(wid, bearbeiten=True)
    name = request.form.get("name", "").strip()
    if not name:
        raise ValueError("Bitte den Namen des Mieters angeben.")
    vals = mv_werte()
    nummer = (one("SELECT MAX(m.nummer) AS n FROM mietverhaeltnis m JOIN wohnung x ON x.id = m.wohnung_id "
                  "WHERE x.immobilie_id = ?", (w["immobilie_id"],))["n"] or 0) + 1
    vals.update(wohnung_id=wid, nummer=nummer, ordner=dateien.ordnername(f"{nummer:03d} - {name}"))
    mid = exe(f"INSERT INTO mietverhaeltnis ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})",
              list(vals.values()))
    exe("INSERT INTO mieter_person (mv_id, vorname, name) VALUES (?, ?, ?)",
        (mid, request.form.get("vorname", "").strip(), name))
    return redirect(url_for("wohnung", wid=wid) + "#mieter")


def _mv_laden(mid):
    mv = row("SELECT * FROM mietverhaeltnis WHERE id = ?", (mid,))
    wohnung_laden(mv["wohnung_id"], bearbeiten=True)
    return mv


@app.post("/mieter/<int:mid>")
def mv_speichern(mid):
    mv = _mv_laden(mid)
    vals = mv_werte()
    exe(f"UPDATE mietverhaeltnis SET {', '.join(k + ' = ?' for k in vals)} WHERE id = ?", [*vals.values(), mid])
    flash("Mietverhältnis gespeichert.")
    return redirect(url_for("wohnung", wid=mv["wohnung_id"]) + "#mieter")


@app.post("/mieter/<int:mid>/loeschen")
def mv_loeschen(mid):
    mv = _mv_laden(mid)
    exe("DELETE FROM mietverhaeltnis WHERE id = ?", (mid,))
    return redirect(url_for("wohnung", wid=mv["wohnung_id"]) + "#mieter")


@app.post("/mieter/<int:mid>/personen")
def person_neu(mid):
    mv = _mv_laden(mid)
    name = request.form.get("name", "").strip()
    if not name:
        raise ValueError("Bitte einen Namen angeben.")
    exe("INSERT INTO mieter_person (mv_id, vorname, name) VALUES (?, ?, ?)",
        (mid, request.form.get("vorname", "").strip(), name))
    return redirect(url_for("wohnung", wid=mv["wohnung_id"]) + "#mieter")


@app.post("/personen/<int:pid>/loeschen")
def person_loeschen(pid):
    p = row("SELECT * FROM mieter_person WHERE id = ?", (pid,))
    mv = _mv_laden(p["mv_id"])
    exe("DELETE FROM mieter_person WHERE id = ?", (pid,))
    return redirect(url_for("wohnung", wid=mv["wohnung_id"]) + "#mieter")


# ---------- Vorauszahlungen ----------

@app.post("/wohnungen/<int:wid>/vorauszahlungen")
def vorauszahlungen_speichern(wid):
    wohnung_laden(wid, bearbeiten=True)
    j = jahr()
    mv_ids = {m["id"] for m in rows("SELECT id FROM mietverhaeltnis WHERE wohnung_id = ?", (wid,))}
    con = db.get_db()
    for k, v in request.form.items():
        if not k.startswith("vz_"):
            continue
        mid = None if k == "vz_eigentuemer" else int(k[3:])
        if mid is not None and mid not in mv_ids:
            continue
        con.execute("DELETE FROM vorauszahlung WHERE jahr = ? AND wohnung_id = ? AND mv_id IS ?", (j, wid, mid))
        if v.strip():
            con.execute("INSERT INTO vorauszahlung (jahr, wohnung_id, mv_id, betrag) VALUES (?, ?, ?, ?)",
                        (j, wid, mid, parse_num(v)))
    con.commit()
    flash("Vorauszahlungen gespeichert.")
    return redirect(url_for("wohnung", wid=wid) + "#abrechnung")


@app.post("/immobilien/<int:iid>/hausgeld")
@admin_noetig
def hausgeld_speichern(iid):
    """Hausgeld aller Mietobjekte einer WEG auf einmal (gleiche Daten wie „Eigentümer-Abrechnung“ beim Mietobjekt)."""
    j = jahr()
    wohnungen = {w["id"] for w in rows("SELECT id FROM wohnung WHERE immobilie_id = ?", (iid,))}
    con = db.get_db()
    for k, v in request.form.items():
        if not k.startswith("hg_") or int(k[3:]) not in wohnungen:
            continue
        wid = int(k[3:])
        con.execute("DELETE FROM vorauszahlung WHERE jahr = ? AND wohnung_id = ? AND mv_id IS NULL", (j, wid))
        if v.strip():
            con.execute("INSERT INTO vorauszahlung (jahr, wohnung_id, mv_id, betrag) VALUES (?, ?, NULL, ?)",
                        (j, wid, parse_num(v)))
    con.commit()
    flash("Hausgeld gespeichert.")
    return redirect(url_for("immobilie", iid=iid) + "#hausgeld")


# ---------- Zähler ----------

def _zaehler_recht(z):
    if z["wohnung_id"]:
        wohnung_laden(z["wohnung_id"], bearbeiten=True)
    elif not ist_admin():
        abort(403)


@app.post("/zaehler")
def zaehler_neu():
    f = request.form
    art = f.get("art")
    if art not in ZAEHLERARTEN:
        raise ValueError("Unbekannte Zählerart.")
    wid = int(f["wohnung_id"]) if f.get("wohnung_id") else None
    iid = int(f["immobilie_id"]) if f.get("immobilie_id") else None
    _zaehler_recht({"wohnung_id": wid})
    zid = exe("INSERT INTO zaehler (wohnung_id, immobilie_id, art, nummer, bezeichnung, eingebaut) VALUES (?, ?, ?, ?, ?, ?)",
              (wid, None if wid else iid, art, f.get("nummer", "").strip(), f.get("bezeichnung", "").strip(),
               f.get("eingebaut") or None))
    if f.get("stand", "").strip() and f.get("eingebaut"):
        exe("INSERT INTO zaehlerstand (zaehler_id, datum, stand, notiz) VALUES (?, ?, ?, 'Einbau')",
            (zid, f["eingebaut"], parse_num(f["stand"])))
    return zurueck()


@app.post("/zaehler/<int:zid>/tausch")
def zaehler_tausch(zid):
    """Zählerwechsel: alter Zähler bleibt mit Ausbaustand erhalten, neuer Zähler startet mit Einbaustand."""
    z = row("SELECT * FROM zaehler WHERE id = ?", (zid,))
    _zaehler_recht(z)
    f = request.form
    datum = f.get("datum")
    if not datum:
        raise ValueError("Bitte das Datum des Wechsels angeben.")
    exe("INSERT INTO zaehlerstand (zaehler_id, datum, stand, notiz) VALUES (?, ?, ?, 'Ausbau')",
        (zid, datum, parse_num(f.get("endstand"))))
    exe("UPDATE zaehler SET ausgebaut = ? WHERE id = ?", (datum, zid))
    neu = exe("INSERT INTO zaehler (wohnung_id, immobilie_id, art, nummer, bezeichnung, eingebaut) VALUES (?, ?, ?, ?, ?, ?)",
              (z["wohnung_id"], z["immobilie_id"], z["art"], f.get("nummer", "").strip(), z["bezeichnung"], datum))
    exe("INSERT INTO zaehlerstand (zaehler_id, datum, stand, notiz) VALUES (?, ?, ?, 'Einbau')",
        (neu, datum, parse_num(f.get("anfangsstand"))))
    flash("Zähler getauscht. Der alte Zähler bleibt mit seinen Ständen erhalten.")
    return zurueck()


@app.post("/zaehler/<int:zid>/bearbeiten")
def zaehler_bearbeiten(zid):
    z = row("SELECT * FROM zaehler WHERE id = ?", (zid,))
    _zaehler_recht(z)
    f = request.form
    exe("UPDATE zaehler SET bezeichnung = ?, nummer = ? WHERE id = ?",
        (f.get("bezeichnung", "").strip(), f.get("nummer", "").strip(), zid))
    return zurueck()


@app.post("/zaehler/<int:zid>/loeschen")
def zaehler_loeschen(zid):
    z = row("SELECT * FROM zaehler WHERE id = ?", (zid,))
    _zaehler_recht(z)
    exe("DELETE FROM zaehler WHERE id = ?", (zid,))
    return zurueck()


@app.post("/zaehler/<int:zid>/staende")
def zaehlerstand_neu(zid):
    z = row("SELECT * FROM zaehler WHERE id = ?", (zid,))
    _zaehler_recht(z)
    f = request.form
    if not f.get("datum") or not f.get("stand", "").strip():
        raise ValueError("Datum und Zählerstand sind Pflichtfelder.")
    exe("INSERT INTO zaehlerstand (zaehler_id, datum, stand, notiz) VALUES (?, ?, ?, ?)",
        (zid, f["datum"], parse_num(f["stand"]), f.get("notiz", "").strip()))
    return zurueck()


@app.post("/zaehlerstaende/<int:sid>/loeschen")
def zaehlerstand_loeschen(sid):
    s = row("SELECT * FROM zaehlerstand WHERE id = ?", (sid,))
    _zaehler_recht(row("SELECT * FROM zaehler WHERE id = ?", (s["zaehler_id"],)))
    exe("DELETE FROM zaehlerstand WHERE id = ?", (sid,))
    return zurueck()


# ---------- Dokumente ----------

def _dokumente_hochladen(iid, wohnung_id=None):
    """Speichert hochgeladene Dateien unter <Immobilie>/<Jahr>/Vermieter|Mieter[/<Nr - Name>]."""
    f = request.form
    dateiliste = [d for d in request.files.getlist("dateien") if d and d.filename]
    if not dateiliste:
        return 0
    immo = row("SELECT * FROM immobilie WHERE id = ?", (iid,))
    j = int(f.get("dok_jahr") or 0)
    if not 1990 <= j <= 2200:
        raise ValueError("Bitte das Jahr für die Dokumente auswählen.")
    bereich = f.get("bereich", "mieter")
    mv_id = int(f["mv_id"]) if bereich == "mieterordner" and f.get("mv_id") else None
    if bereich not in BEREICHE or (bereich == "mieterordner" and not mv_id):
        raise ValueError("Bitte den Ablageort (Vermieter, Mieter oder Mieterordner) wählen.")
    ordner = [immo["ordner"], str(j)]
    if bereich == "vermieter":
        ordner.append("Vermieter")
    else:
        ordner.append("Mieter")
        if mv_id:
            mv = row("SELECT m.* FROM mietverhaeltnis m JOIN wohnung w ON w.id = m.wohnung_id "
                     "WHERE m.id = ? AND w.immobilie_id = ?", (mv_id, iid))
            if not ist_admin():
                wohnung_laden(mv["wohnung_id"], bearbeiten=True)
            ordner.append(mv["ordner"])
            wohnung_id = None
    kostenart_id = int(f["kostenart_id"]) if f.get("kostenart_id") else None
    if f.get("dok_wohnung_id"):
        wohnung_id = int(f["dok_wohnung_id"])
    for d in dateiliste:
        pfad, mime, groesse = dateien.dokument_speichern(d, os.path.join(*ordner))
        titel = (f.get("titel", "").strip() if len(dateiliste) == 1 else "") or os.path.splitext(d.filename)[0]
        exe("INSERT INTO dokument (immobilie_id, jahr, bereich, mv_id, wohnung_id, kostenart_id, titel, notiz, pfad, "
            "mime, groesse, hochgeladen_von) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (iid, j, bereich, mv_id, wohnung_id, kostenart_id, titel, f.get("notiz", "").strip(), pfad, mime, groesse,
             g.user["id"]))
    return len(dateiliste)


@app.post("/immobilien/<int:iid>/dokumente")
def dokument_hochladen(iid):
    wid = int(request.form["wohnung_id"]) if request.form.get("wohnung_id") else None
    if wid:
        w = wohnung_laden(wid, bearbeiten=True)
        if w["immobilie_id"] != iid:
            abort(400)
        if request.form.get("bereich") == "vermieter" and not ist_admin():
            abort(403)
    elif not ist_admin():
        abort(403)
    n = _dokumente_hochladen(iid, wid)
    flash(f"{n} Dokument(e) hochgeladen." if n else "Keine Datei ausgewählt.", None if n else "fehler")
    return zurueck()


def _dokument_laden(did, bearbeiten=False):
    d = row("SELECT d.*, m.wohnung_id AS mv_wohnung FROM dokument d "
            "LEFT JOIN mietverhaeltnis m ON m.id = d.mv_id WHERE d.id = ?", (did,))
    if ist_admin():
        return d
    wid = d["wohnung_id"] or d["mv_wohnung"]
    if wid:
        w = wohnung_laden(wid, bearbeiten=bearbeiten)
        if not w:
            abort(403)
    elif bearbeiten or d["bereich"] != "mieter":
        abort(403)
    else:
        immobilie_laden(d["immobilie_id"])
    return d


@app.get("/dokumente/<int:did>")
def dokument_anzeigen(did):
    d = _dokument_laden(did)
    return send_file(dateien.dokument_pfad(d["pfad"]), mimetype=d["mime"],
                     download_name=os.path.basename(d["pfad"]), as_attachment=bool(request.args.get("download")))


@app.post("/dokumente/<int:did>/loeschen")
def dokument_loeschen(did):
    d = _dokument_laden(did, bearbeiten=True)
    try:
        os.remove(dateien.dokument_pfad(d["pfad"]))
    except FileNotFoundError:
        pass
    exe("DELETE FROM dokument WHERE id = ?", (did,))
    return zurueck()


# ---------- Ablage (unabhängig von der Abrechnung) ----------

def ablage_sichtbar(iid, wohnung_id=None):
    """Einträge einer Immobilie (wohnung_id=None) bzw. eines Mietobjekts. Eigentümer sehen die gemeinsamen
    Unterlagen ihrer Immobilie (außer „nur für Administrator“) und die ihrer eigenen Mietobjekte."""
    sql = ("SELECT a.*, w.bezeichnung AS wohnung FROM ablage a LEFT JOIN wohnung w ON w.id = a.wohnung_id "
           "WHERE a.immobilie_id = ?")
    args = [iid]
    if wohnung_id is not None:
        sql += " AND a.wohnung_id = ?"
        args.append(wohnung_id)
    if not ist_admin():
        sql += " AND a.intern = 0 AND (a.wohnung_id IS NULL OR w.eigentuemer_id = ?)"
        args.append(g.user["id"])
    eintraege = rows(sql + " ORDER BY a.jahr IS NULL, a.jahr DESC, a.titel COLLATE NATUERLICH", args)
    return [(k, t, [e for e in eintraege if e["kategorie"] == k]) for k, t in ablage_kategorien().items()
            if any(e["kategorie"] == k for e in eintraege)]


@app.post("/immobilien/<int:iid>/ablage")
def ablage_hochladen(iid):
    immo = row("SELECT * FROM immobilie WHERE id = ?", (iid,))
    f = request.form
    wid = int(f["wohnung_id"]) if f.get("wohnung_id") else None
    if wid:
        w = wohnung_laden(wid, bearbeiten=True)
        if w["immobilie_id"] != iid:
            abort(400)
    elif not ist_admin():
        abort(403)
    kategorie = f.get("kategorie")
    if kategorie == "neu" and ist_admin():
        kategorie = ablage_kategorie_anlegen(f.get("neue_kategorie", ""))
    kategorien = ablage_kategorien()
    if kategorie not in kategorien:
        raise ValueError("Bitte eine Kategorie wählen.")
    jahr_ = int(f["jahr"]) if f.get("jahr", "").strip() else None
    if jahr_ is not None and not 1900 <= jahr_ <= 2200:
        raise ValueError("Bitte ein gültiges Jahr angeben oder das Feld leer lassen.")
    dateiliste = [d for d in request.files.getlist("dateien") if d and d.filename]
    if not dateiliste:
        raise ValueError("Bitte mindestens eine Datei auswählen.")
    ordner = [immo["ordner"], "Ablage"]
    if wid:
        ordner.append(dateien.ordnername(w["bezeichnung"]))
    ordner.append(dateien.ordnername(kategorien[kategorie]))
    for d in dateiliste:
        pfad, mime, groesse = dateien.dokument_speichern(d, os.path.join(*ordner))
        titel = (f.get("titel", "").strip() if len(dateiliste) == 1 else "") or os.path.splitext(d.filename)[0]
        exe("INSERT INTO ablage (immobilie_id, wohnung_id, kategorie, titel, jahr, notiz, intern, pfad, mime, groesse, "
            "hochgeladen_von) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (iid, wid, kategorie, titel, jahr_, f.get("notiz", "").strip(), 1 if f.get("intern") and ist_admin() else 0,
             pfad, mime, groesse, g.user["id"]))
    flash(f"{len(dateiliste)} Dokument(e) in der Ablage gespeichert.")
    return zurueck()


def _ablage_laden(aid, bearbeiten=False):
    a = row("SELECT * FROM ablage WHERE id = ?", (aid,))
    if ist_admin():
        return a
    if a["intern"]:
        abort(403)
    if a["wohnung_id"]:
        wohnung_laden(a["wohnung_id"], bearbeiten=bearbeiten)
    elif bearbeiten:
        abort(403)
    else:
        immobilie_laden(a["immobilie_id"])
    return a


@app.get("/ablage/<int:aid>")
def ablage_anzeigen(aid):
    a = _ablage_laden(aid)
    return send_file(dateien.dokument_pfad(a["pfad"]), mimetype=a["mime"],
                     download_name=os.path.basename(a["pfad"]), as_attachment=bool(request.args.get("download")))


@app.post("/ablage/<int:aid>/loeschen")
def ablage_loeschen(aid):
    a = _ablage_laden(aid, bearbeiten=True)
    try:
        os.remove(dateien.dokument_pfad(a["pfad"]))
    except FileNotFoundError:
        pass
    exe("DELETE FROM ablage WHERE id = ?", (aid,))
    return zurueck()


@app.context_processor
def _hilfen():
    return {"wohnung_bearbeitbar": wohnung_bearbeitbar if g.get("user") else (lambda w: False),
            "wohnung_sichtbar": wohnung_sichtbar if g.get("user") else (lambda w: False)}
