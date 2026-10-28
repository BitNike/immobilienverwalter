"""Immobilien, Mietobjekte (Wohnungen), Mietverhältnisse, Zähler, Kosten, Vorauszahlungen, Dokumente."""
import os
import re
from datetime import date

from flask import abort, flash, g, redirect, render_template, request, send_file, session, url_for

import dateien
import db
from vertraege import MIETARTEN, kennzahlen as vertrag_kennzahlen, mietvertraege, vertraege
from calc import berechne, cent_genau, de_num, messbeginn, parse_date, parse_mea, parse_num, rund, verbrauch_zeitraum
from core import (BEREICHE, SCHLUESSEL, ablage_kategorie_anlegen, ablage_kategorien, ZAEHLERARTEN, admin_noetig, app, eigentuemer_anlegen, exe, immobilie_laden, ist_admin, jahr, one,
                  person_name, row, rows, sichtbare_immobilien, wohnung_bearbeitbar, wohnung_laden,
                  wohnung_sichtbar, wohnungen_der_immobilie, zurueck)

IMMOBILIE_FELDER = ("name", "strasse", "hausnummer", "plz", "ort", "absender", "kontoinhaber", "iban", "bank", "notiz",
                    "schluessel")
WOHNUNG_FELDER = ("bezeichnung", "haus", "umlageschluessel", "kontoinhaber", "iban", "bank", "notiz")


# ---------- Hilfen ----------

def mv_personen(mv_id):
    return rows("SELECT * FROM mieter_person WHERE mv_id = ? ORDER BY id", (mv_id,))


def mv_name(mv):
    return ", ".join(person_name(p) for p in mv.get("personen") or []) or "(ohne Namen)"


app.jinja_env.globals.update(mv_name=mv_name)


def kostenarten_aktiv():
    return rows("SELECT * FROM kostenart WHERE aktiv = 1 ORDER BY sortierung, name")


def haeuser(iid):
    """Häuser bzw. Hauseingänge der Immobilie (Feld „Haus“ der Mietobjekte), natürlich sortiert."""
    return [r["haus"] for r in rows("SELECT DISTINCT haus FROM wohnung WHERE immobilie_id = ? AND haus <> '' "
                                    "ORDER BY haus COLLATE NATUERLICH", (iid,))]


def hausgeld_wohnungen(iid, b):
    """Wohnungen, auf die eine Hausgeld-Buchung entfällt: die gewählte oder alle des Eigentümers in der Immobilie."""
    if b["hausgeld_wohnung_id"]:
        return [b["hausgeld_wohnung_id"]]
    return [w["id"] for w in rows("SELECT id FROM wohnung WHERE immobilie_id = ? AND eigentuemer_id = ? "
                                   "ORDER BY bezeichnung COLLATE NATUERLICH", (iid, b["hausgeld_eigentuemer_id"]))]


def hausgeld_aus_buchungen(iid, j):
    """Hausgeld je Wohnung aus den Buchungen des Jahres. Zahlt ein Eigentümer für alle seine Wohnungen, wird der Betrag
    gleichmäßig und cent-genau aufgeteilt. Ergebnis: ({wohnung_id: {betrag, anzahl}}, [nicht zuordenbare Buchungen])."""
    erg, offen = {}, []
    for b in rows("SELECT * FROM buchung WHERE immobilie_id = ? AND jahr = ? AND hausgeld_eigentuemer_id IS NOT NULL "
                  "ORDER BY datum, id", (iid, j)):
        wids = hausgeld_wohnungen(iid, b)
        if not wids:
            offen.append(b)
            continue
        wert = b["betrag"] if b["art"] == "einnahme" else -b["betrag"]
        for wid, x in cent_genau({wid: wert / len(wids) for wid in wids}).items():
            h = erg.setdefault(wid, {"betrag": 0.0, "anzahl": 0})
            h["betrag"] = rund(h["betrag"] + x)
            h["anzahl"] += 1
    return erg, offen


def hausgeld_optionen(iid):
    """Eigentümer der Immobilie mit ihren Wohnungen – für die Auswahl „Hausgeld von …“ und den Filter."""
    erg = {}
    for w in rows("SELECT * FROM wohnung WHERE immobilie_id = ? AND eigentuemer_id IS NOT NULL "
                  "ORDER BY bezeichnung COLLATE NATUERLICH", (iid,)):
        e = erg.get(w["eigentuemer_id"])
        if not e:
            b = one("SELECT * FROM benutzer WHERE id = ?", (w["eigentuemer_id"],))
            e = erg[w["eigentuemer_id"]] = {"id": w["eigentuemer_id"], "name": person_name(b) if b else "?", "wohnungen": []}
        e["wohnungen"].append(w)
    return sorted(erg.values(), key=lambda e: e["name"].casefold())


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
    hausgeld, hausgeld_offen = hausgeld_aus_buchungen(iid, j)
    for wid, h in hausgeld.items():  # Hausgeld aus Buchungen hat Vorrang vor dem von Hand eingetragenen
        vz[(wid, None)] = h["betrag"]
    erg = berechne(date(j, 1, 1), date(j, 12, 31), immo, wohnungen, kosten, kostenarten, mvs, zaehler, vz)
    erg["vz_gespeichert"] = set(vz)
    erg["hausgeld_buchungen"] = {wid: h["anzahl"] for wid, h in hausgeld.items()}
    erg["hausgeld_offen"] = hausgeld_offen
    return erg


def buchungen_filtern(buchungen, f):
    """Filter und Suche im Reiter Buchungen. f: q (Text oder Betrag), ziel (Kostenart-ID, ruecklage, hausgeld),
    art, monat (1–12), wohnung, eigentuemer, ohne (nur ohne Beleg)."""
    q = f["q"].casefold()
    try:
        q_betrag = parse_num(f["q"], None) if f["q"] else None
    except ValueError:
        q_betrag = None
    erg = []
    for b in buchungen:
        if q and q not in f"{b['text']} {b['notiz']} {b['ziel_text']} {b['ziel_zusatz']}".casefold() \
                and not (q_betrag is not None and abs(b["betrag"] - q_betrag) < 0.005):
            continue
        if f["ziel"] == "hausgeld" and not b["hausgeld_eigentuemer_id"]:
            continue
        if f["ziel"] == "ruecklage" and (b["kostenart_id"] or b["hausgeld_eigentuemer_id"]):
            continue
        if f["ziel"].isdigit() and b["kostenart_id"] != int(f["ziel"]):
            continue
        if f["art"] and b["art"] != f["art"]:
            continue
        if f["monat"].isdigit() and not (b["datum"] and int(b["datum"][5:7]) == int(f["monat"])):
            continue
        if f["wohnung"].isdigit() and int(f["wohnung"]) not in b["wohnungen"]:
            continue
        if f["eigentuemer"].isdigit() and b["hausgeld_eigentuemer_id"] != int(f["eigentuemer"]):
            continue
        if f["ohne"] and (b["dokument_id"] or b["hausgeld_eigentuemer_id"]):  # Hausgeld: Kontoauszug genügt
            continue
        erg.append(b)
    return erg


def reiter_waehlen(reiter):
    """Gewählter Reiter aus ?reiter=, sonst der erste. reiter: [(schluessel, titel)]."""
    gewaehlt = request.args.get("reiter")
    return gewaehlt if gewaehlt in dict(reiter) else reiter[0][0]


def standard_schluessel(immo, anzahl_wohnungen):
    """Vorauswahl für neue Gebäudekosten; None = Standard der Kostenart."""
    return immo["schluessel"] or ("flaeche" if anzahl_wohnungen == 1 else None)


def kostenart_regeln(iid):
    """{kostenart_id: {schluessel, grundlage, ungenutzt}} – Regeln der Immobilie (Reiter „Umlageschlüssel“)."""
    return {r["kostenart_id"]: r for r in rows("SELECT * FROM immobilie_kostenart WHERE immobilie_id = ?", (iid,))}


def schluessel_vorgabe(immo, ka, anzahl_wohnungen):
    """Schlüssel ohne eigene Regel der Immobilie: Wasser bleibt Wasser, sonst Standard der Immobilie bzw. der Kostenart."""
    if ka["schluessel"] == "wasser":
        return "wasser"
    return standard_schluessel(immo, anzahl_wohnungen) or ka["schluessel"]


def schluessel_fuer(immo, ka, regeln=None, anzahl_wohnungen=None):
    """Umlageschlüssel einer Kostenart in dieser Immobilie: eigene Regel, sonst die Vorgabe."""
    r = (kostenart_regeln(immo["id"]) if regeln is None else regeln).get(ka["id"])
    if r and r["schluessel"]:
        return r["schluessel"]
    if anzahl_wohnungen is None:
        anzahl_wohnungen = one("SELECT COUNT(*) AS n FROM wohnung WHERE immobilie_id = ?", (immo["id"],))["n"]
    return schluessel_vorgabe(immo, ka, anzahl_wohnungen)


def kostenarten_immobilie(immo):
    """Aktive Kostenarten ohne die, die diese Immobilie für ihre Gebäudekosten ausgeblendet hat; „schluessel“ ist der der
    Immobilie. Beim Mietobjekt bleiben alle Kostenarten wählbar (z. B. Müllgebühr, die der Eigentümer direkt bezahlt)."""
    regeln = kostenart_regeln(immo["id"])
    anzahl = one("SELECT COUNT(*) AS n FROM wohnung WHERE immobilie_id = ?", (immo["id"],))["n"]
    return [dict(k, schluessel=schluessel_fuer(immo, k, regeln, anzahl)) for k in kostenarten_aktiv()
            if not (regeln.get(k["id"]) and regeln[k["id"]]["ungenutzt"])]


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
    regeln = kostenart_regeln(immo["id"]) if ganze_immobilie else {}
    for gk in erg["gebaeude"]:
        r = regeln.get(gk["kosten"]["kostenart_id"])
        if r and r["schluessel"] and gk["kosten"]["schluessel"] != r["schluessel"]:
            punkt(f"{gk['kostenart']}: verteilt nach {SCHLUESSEL[gk['kosten']['schluessel']]}, die Regel der Immobilie sagt "
                  f"{SCHLUESSEL[r['schluessel']]}{' (' + r['grundlage'] + ')' if r['grundlage'] else ''}.",
                  url_for("immobilie", iid=immo["id"], reiter="schluessel"), "hinweis")
    for b in erg.get("hausgeld_offen", []) if ganze_immobilie else []:
        punkt(f"Hausgeld „{b['text']}“ ({de_num(b['betrag'])} €): Der Eigentümer hat hier keine Wohnung mehr, der Betrag "
              "wird keiner Wohnung zugerechnet.", url_for("immobilie", iid=immo["id"], reiter="buchungen", buchung=b["id"]))
    if ganze_immobilie:
        rl = ruecklage(immo["id"], jahr())
        if rl["vorhanden"] and rl["anfang"] is None:
            punkt("Erhaltungsrücklage: Der Anfangsbestand fehlt, der Endbestand stimmt deshalb nicht.",
                  url_for("immobilie", iid=immo["id"], reiter="ruecklage"), "hinweis")
    schluessel = {gk["kosten"]["schluessel"] for gk in erg["gebaeude"] if not gk["warnung"]}
    if not immo["iban"] and any(not erg["wohnungen"][i]["wohnung"]["iban"] for i in wids if i in erg["wohnungen"]):
        punkt("Bei der Immobilie ist keine IBAN hinterlegt; im Brief fehlt dann die Bankverbindung.",
              url_for("immobilie", iid=immo["id"], reiter="stammdaten"), "hinweis")

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
                  url_for("wohnung", wid=wid, reiter="zaehler"), "hinweis")
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


def zaehler_mit_staenden(sql, args, j=None):
    """Zähler mit Ablesungen (neueste zuerst). Mit Jahr j zusätzlich wie bei den Konten: Stand zu Jahresbeginn
    (letzte Ablesung bis 31.12. des Vorjahres), Stand zum Jahresende (letzte Ablesung im Jahr), Verbrauch im Jahr."""
    zs = rows(sql, args)
    for z in zs:
        z["staende"] = rows("SELECT * FROM zaehlerstand WHERE zaehler_id = ? ORDER BY datum DESC, id DESC", (z["id"],))
        if j is None:
            continue
        z["anfang"] = next((s for s in z["staende"] if s["datum"] <= f"{j - 1}-12-31"), None)
        z["staende_jahr"] = [s for s in z["staende"] if s["datum"][:4] == str(j)]
        z["ende"] = z["staende_jahr"][0] if z["staende_jahr"] else None
        z["verbrauch"] = verbrauch_zeitraum([{**z, "staende": [(s["datum"], s["stand"]) for s in z["staende"]]}],
                                            date(j, 1, 1), date(j, 12, 31))
        z["im_jahr"] = not (z["ausgebaut"] and z["ausgebaut"] < f"{j}-01-01") and \
            not (z["eingebaut"] and z["eingebaut"] > f"{j}-12-31")
        # Zwischenstand, solange der Stand zum Jahresende fehlt (z. B. mitten im Jahr)
        z["bisher"] = rund(z["ende"]["stand"] - z["anfang"]["stand"]) \
            if z["verbrauch"] is None and z["anfang"] and z["ende"] else None
    return zs


def ablesungen_im_jahr(zs):
    """Alle Ablesungen der Zähler im Jahr, nach Datum – für die eingeklappte Liste."""
    return sorted(({**s, "zaehler": z} for z in zs for s in z.get("staende_jahr", [])),
                  key=lambda s: (s["datum"], s["id"]))


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


def kurzname(bezeichnung):
    """Kurzform für die eingeklappte Spalte: die Nummer („Wohnung 12“ → „12“, „3a“), sonst die ersten drei Zeichen."""
    m = re.search(r"\d+\s*[a-zA-Z]?\b", bezeichnung or "")
    return m.group(0).replace(" ", "") if m else (bezeichnung or "?")[:3]


def spalte(immo, aktiv_wohnung=None):
    """Daten für die zweite Spalte (Mietobjekte der Immobilie)."""
    wohnungen = wohnungen_der_immobilie(immo["id"])
    for w in wohnungen:
        w["kurz"] = kurzname(w["bezeichnung"])
    return {"immo": immo, "spalte_wohnungen": wohnungen, "aktiv_wohnung": aktiv_wohnung}


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
    vals = {k: f.get(k, "").strip() for k in IMMOBILIE_FELDER if k != "schluessel" or k in f}
    if not vals["name"]:
        raise ValueError("Bitte einen Namen für die Immobilie angeben.")
    vals["iban"] = vals["iban"].upper()
    if vals.get("schluessel", "") not in ("", "mea", "flaeche", "einheiten"):
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
                                        "ORDER BY art, ausgebaut IS NOT NULL, bezeichnung COLLATE NATUERLICH, id", (iid,), j)
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
    # Buchungen mit Belegdatum in diesem Jahr, die (meist versehentlich) in einem anderen Jahr stehen
    fremde = rows("SELECT b.*, ka.name AS kostenart, (b.hausgeld_eigentuemer_id IS NULL AND (b.kostenart_id IS NULL OR ka.ruecklage = 1)) AS rl_eintrag "
                  "FROM buchung b LEFT JOIN kostenart ka ON ka.id = b.kostenart_id "
                  "WHERE b.immobilie_id = ? AND b.jahr <> ? AND substr(b.datum, 1, 4) = ? ORDER BY b.datum, b.id",
                  (iid, j, str(j)))
    belege = {}
    for b in buchungen:
        if b["kosten_id"]:
            belege[b["kosten_id"]] = belege.get(b["kosten_id"], 0) + 1
    hg_opt = hausgeld_optionen(iid)
    eig_namen = {e["id"]: e["name"] for e in hg_opt}
    wohnung_bez = {w["id"]: w["bezeichnung"] for w in rows("SELECT id, bezeichnung FROM wohnung WHERE immobilie_id = ?", (iid,))}
    for b in buchungen:
        b["ziel"] = ziel_wert(b)
        if b["hausgeld_eigentuemer_id"]:
            b["wohnungen"] = hausgeld_wohnungen(iid, b)
            name = eig_namen.get(b["hausgeld_eigentuemer_id"]) or person_name(
                one("SELECT * FROM benutzer WHERE id = ?", (b["hausgeld_eigentuemer_id"],)) or {})
            b["ziel_text"] = f"Hausgeld {name}"
            b["ziel_zusatz"] = ", ".join(wohnung_bez.get(w, "?") for w in b["wohnungen"]) or "keine Wohnung"
        else:
            b["wohnungen"], b["ziel_zusatz"] = [], f"nur {b['haus']}" if b["haus"] else ""
            b["ziel_text"] = b["kostenart"] if b["kostenart_id"] else "Erhaltungsrücklage"
    if not ist_admin():  # Eigentümer sehen nur das Hausgeld ihrer eigenen Wohnungen
        buchungen = [b for b in buchungen if not b["hausgeld_eigentuemer_id"] or set(b["wohnungen"]) & eigene]
        hg_opt = [e for e in hg_opt if e["id"] == g.user["id"]]
    filter_ = {k: request.args.get(k, "").strip() for k in ("q", "ziel", "art", "monat", "wohnung", "eigentuemer", "ohne")}
    alle_buchungen, buchungen = buchungen, buchungen_filtern(buchungen, filter_)
    vorlage = dict(session.get("buchung_vorlage") or {})
    rl_vorlage = dict(session.get("ruecklage_vorlage") or {})
    for v in (vorlage, rl_vorlage):
        if not (v.get("datum") or "").startswith(str(j)):
            v["datum"] = date.today().isoformat() if date.today().year == j else ""
    umfang = one("SELECT (SELECT COUNT(*) FROM wohnung WHERE immobilie_id = :i) AS wohnungen, "
                 "(SELECT COUNT(*) FROM mietverhaeltnis m JOIN wohnung w ON w.id = m.wohnung_id WHERE w.immobilie_id = :i) AS mieter, "
                 "(SELECT COUNT(*) FROM kosten WHERE immobilie_id = :i) AS kosten, "
                 "(SELECT COUNT(*) FROM dokument WHERE immobilie_id = :i) + "
                 "(SELECT COUNT(*) FROM ablage WHERE immobilie_id = :i) AS dokumente", {"i": iid})
    reiter = [("uebersicht", "Übersicht"), ("buchungen", "Buchungen"), ("ruecklage", "Rücklage")]
    if ist_admin() or hauptzaehler:
        reiter.append(("zaehler", "Zähler"))
    reiter += [("vertraege", "Verträge"), ("dokumente", "Dokumente")]
    if ist_admin():
        reiter += [("stammdaten", "Stammdaten"), ("schluessel", "Umlageschlüssel")]
    vliste = vertraege(iid, j=j)
    pruefung = pruefungen(immo, erg, eigene, ganze_immobilie=ist_admin())
    return render_template("immobilie.html", **spalte(immo), erg=erg, verteilung=verteilung, mea_summe=mea_summe,
                           reiter=reiter, aktiv=reiter_waehlen(reiter), vliste=vliste, vk=vertrag_kennzahlen(vliste),
                           umfang=umfang, hauptverbrauch=hauptverbrauch, wohnungen_wasser=wohnungen_wasser,
                           pruefung=pruefung, buchungen=buchungen, alle_buchungen=alle_buchungen, filter_=filter_,
                           hg_opt=hg_opt if immo["weg"] else [], haeuser=haeuser(iid), belege=belege, vorlage=vorlage,
                           rl_vorlage=rl_vorlage, BEZAHLT=BEZAHLT, RL_ARTEN=RL_ARTEN, fremde=fremde,
                           kt=konten(iid, j), kontostand_vorlage=session.get("kontostand_vorlage") or {},
                           dauer=dauerauftraege(iid, j), RHYTHMEN=RHYTHMEN,
                           dauer_vorjahr=one("SELECT COUNT(*) AS n FROM dauerauftrag WHERE immobilie_id = ? AND jahr = ?",
                                             (iid, j - 1))["n"],
                           offen_bar=[b for b in alle_buchungen if b["art"] == "ausgabe" and b["bezahlt"] == "bar"
                                      and not b["erstattet"]],
                           rl=ruecklage(iid, j),
                           vorjahr_vorhanden=vorjahr_vorhanden, kostenarten=kostenarten_immobilie(immo),
                           regeln=kostenart_regeln(iid), alle_kostenarten=kostenarten_aktiv(),
                           vorgaben={k["id"]: schluessel_vorgabe(immo, k, umfang["wohnungen"]) for k in kostenarten_aktiv()},
                           dokumente=dokumente_sichtbar(iid, j), hauptzaehler=hauptzaehler, mvs=mvs,
                           ablage=ablage_sichtbar(iid),
                           wohnungen=rows("SELECT * FROM wohnung WHERE immobilie_id = ? ORDER BY bezeichnung COLLATE NATUERLICH", (iid,)))


@app.post("/immobilien/<int:iid>/stammdaten")
@admin_noetig
def immobilie_speichern(iid):
    vals = immobilie_werte()
    exe(f"UPDATE immobilie SET {', '.join(k + ' = ?' for k in vals)} WHERE id = ?", [*vals.values(), iid])
    flash("Immobilie gespeichert.")
    return redirect(url_for("immobilie", iid=iid, reiter="stammdaten"))


@app.post("/immobilien/<int:iid>/umlageschluessel")
@admin_noetig
def umlageschluessel_speichern(iid):
    """Regeln je Kostenart (Felder s_<id>, g_<id>, u_<id>) und Standard der Immobilie; auf Wunsch auf das Jahr anwenden."""
    row("SELECT id FROM immobilie WHERE id = ?", (iid,))
    f = request.form
    standard = f.get("schluessel", "")
    if standard not in ("", "mea", "flaeche", "einheiten"):
        raise ValueError("Unbekannter Umlageschlüssel.")
    exe("UPDATE immobilie SET schluessel = ? WHERE id = ?", (standard, iid))
    for ka in kostenarten_aktiv():
        s, grundlage, ungenutzt = f.get(f"s_{ka['id']}", ""), f.get(f"g_{ka['id']}", "").strip(), 1 if f.get(f"u_{ka['id']}") else 0
        if s and s not in SCHLUESSEL:
            raise ValueError("Unbekannter Umlageschlüssel.")
        if s or grundlage or ungenutzt:
            exe("INSERT INTO immobilie_kostenart (immobilie_id, kostenart_id, schluessel, grundlage, ungenutzt) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT (immobilie_id, kostenart_id) DO UPDATE SET schluessel = excluded.schluessel, "
                "grundlage = excluded.grundlage, ungenutzt = excluded.ungenutzt", (iid, ka["id"], s, grundlage, ungenutzt))
        else:
            exe("DELETE FROM immobilie_kostenart WHERE immobilie_id = ? AND kostenart_id = ?", (iid, ka["id"]))
    if f.get("anwenden"):
        immo, regeln, n = row("SELECT * FROM immobilie WHERE id = ?", (iid,)), kostenart_regeln(iid), 0
        kostenarten = {k["id"]: k for k in rows("SELECT * FROM kostenart")}
        for k in rows("SELECT * FROM kosten WHERE immobilie_id = ? AND jahr = ? AND wohnung_id IS NULL", (iid, jahr())):
            neu = schluessel_fuer(immo, kostenarten[k["kostenart_id"]], regeln)
            if neu != k["schluessel"]:
                exe("UPDATE kosten SET schluessel = ? WHERE id = ?", (neu, k["id"]))
                n += 1
        flash(f"Umlageschlüssel gespeichert und auf {jahr()} angewendet ({n} Kostenposition{'en' if n != 1 else ''} geändert).")
    else:
        flash("Umlageschlüssel gespeichert. Sie gelten für neue Kostenpositionen.")
    return redirect(url_for("immobilie", iid=iid, reiter="schluessel"))


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
    return redirect(url_for("immobilie", iid=iid, reiter="stammdaten"))


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
    con.execute("""INSERT INTO kosten (immobilie_id, jahr, wohnung_id, mv_id, kostenart_id, betrag, schluessel, notiz, haus)
                   SELECT immobilie_id, ?, wohnung_id, NULL, kostenart_id, 0, schluessel, notiz, haus
                   FROM kosten WHERE immobilie_id = ? AND jahr = ? AND mv_id IS NULL ORDER BY id""",
                (j, iid, j - 1))
    con.commit()
    flash(f"Kostenarten aus {j - 1} übernommen (Beträge auf 0). Die Beträge ergeben sich aus den Buchungen.")
    return redirect(url_for("immobilie", iid=iid) + "#kosten")


# ---------- Buchungen (Belege) ----------

BEZAHLT = {"konto": "Konto", "bar": "Bar ausgelegt"}


def kostenposition(immo, j, kostenart_id, haus=""):
    """Gebäudekosten-Position der Kostenart (und ggf. des Hauses) im Jahr; fehlt sie, wird sie mit dem passenden
    Schlüssel angelegt."""
    k = one("SELECT id FROM kosten WHERE immobilie_id = ? AND jahr = ? AND kostenart_id = ? AND wohnung_id IS NULL "
            "AND haus = ? ORDER BY id", (immo["id"], j, kostenart_id, haus or ""))
    if k:
        return k["id"]
    schl = schluessel_fuer(immo, row("SELECT * FROM kostenart WHERE id = ?", (kostenart_id,)))
    return exe("INSERT INTO kosten (immobilie_id, jahr, kostenart_id, betrag, schluessel, haus) VALUES (?, ?, ?, 0, ?, ?)",
               (immo["id"], j, kostenart_id, schl, haus or ""))


def kosten_aus_buchungen(kid):
    """Betrag der Kostenposition = Summe ihrer Buchungen (Einnahmen mindern); ohne Buchungen fällt sie weg."""
    s = one("SELECT COUNT(*) AS n, SUM(CASE art WHEN 'einnahme' THEN -betrag ELSE betrag END) AS summe "
            "FROM buchung WHERE kosten_id = ?", (kid,))
    if s["n"]:
        exe("UPDATE kosten SET betrag = ? WHERE id = ?", (rund(s["summe"]), kid))
    else:
        exe("DELETE FROM kosten WHERE id = ?", (kid,))


RL_ARTEN = {"zufuehrung": "Zuführung", "einnahme": "Einnahme", "entnahme": "Entnahme"}


def ruecklage_kostenart(gewuenscht=None):
    """Kostenart für Zuführungen zur Rücklage: die gewünschte, falls sie eine ist, sonst die erste aktive."""
    if gewuenscht and one("SELECT 1 FROM kostenart WHERE id = ? AND ruecklage = 1", (gewuenscht,)):
        return int(gewuenscht)
    ka = one("SELECT id FROM kostenart WHERE ruecklage = 1 AND aktiv = 1 ORDER BY sortierung, name")
    if not ka:
        raise ValueError("Es gibt keine Kostenart mit Haken „Rücklage“ (Einstellungen → Kostenarten).")
    return ka["id"]


def ziel_aufloesen(ziel, iid):
    """„Kostenart / Ziel“ aus dem Formular: Kostenart-ID, „ruecklage“ oder Hausgeld („e<id>“ = von diesem Eigentümer für
    alle seine Wohnungen der Immobilie, „w<id>“ = für diese Wohnung). Ergebnis: (kostenart_id, eigentümer, wohnung)."""
    if not ziel:
        raise ValueError("Bitte eine Kostenart, die Rücklage oder Hausgeld wählen.")
    if ziel == "ruecklage":
        return None, None, None
    if ziel[0] == "w":
        w = one("SELECT * FROM wohnung WHERE id = ? AND immobilie_id = ?", (int(ziel[1:]), iid))
        if not w or not w["eigentuemer_id"]:
            raise ValueError("Für diese Wohnung ist kein Eigentümer hinterlegt.")
        return None, w["eigentuemer_id"], w["id"]
    if ziel[0] == "e":
        eig = int(ziel[1:])
        if not one("SELECT 1 FROM wohnung WHERE immobilie_id = ? AND eigentuemer_id = ?", (iid, eig)):
            raise ValueError("Dieser Eigentümer hat in dieser Immobilie keine Wohnung.")
        return None, eig, None
    return _kostenart_id({"kostenart_id": ziel}), None, None


def ziel_wert(b):
    """Gegenstück zu ziel_aufloesen(): der Formularwert für eine gespeicherte Buchung bzw. einen Dauerauftrag."""
    if b.get("hausgeld_wohnung_id"):
        return f"w{b['hausgeld_wohnung_id']}"
    if b.get("hausgeld_eigentuemer_id"):
        return f"e{b['hausgeld_eigentuemer_id']}"
    return str(b["kostenart_id"]) if b.get("kostenart_id") else "ruecklage"


def buchung_werte(iid):
    f = request.form
    art, ziel = f.get("art"), f.get("ziel", "")
    rl_art = f.get("rl_art")
    if rl_art:  # Eingabe im Reiter „Rücklage“: Zuführung läuft über die Rücklage-Kostenart und wird umgelegt
        if rl_art not in RL_ARTEN:
            raise ValueError("Bitte Zuführung, Einnahme oder Entnahme wählen.")
        art = "einnahme" if rl_art == "einnahme" else "ausgabe"
        ziel = str(ruecklage_kostenart(ziel)) if rl_art == "zufuehrung" else "ruecklage"
    vals = {"datum": f.get("datum") or None, "text": f.get("text", "").strip(), "art": art,
            "betrag": parse_num(f.get("betrag")), "bezahlt": f.get("bezahlt", "konto"),
            "notiz": f.get("notiz", "").strip()}
    if not vals["text"]:
        raise ValueError("Bitte eine Beschreibung angeben, z. B. „Lampe Flur Haus 2“.")
    if vals["art"] not in ("ausgabe", "einnahme"):
        raise ValueError("Bitte Ausgabe oder Einnahme wählen.")
    if not vals["betrag"]:
        raise ValueError("Bitte einen Betrag angeben.")
    if vals["bezahlt"] not in BEZAHLT:
        raise ValueError("Bitte angeben, wie bezahlt wurde.")
    vals["kostenart_id"], vals["hausgeld_eigentuemer_id"], vals["hausgeld_wohnung_id"] = ziel_aufloesen(ziel, iid)
    vals["haus"] = f.get("haus", "").strip() if vals["kostenart_id"] else ""
    if vals["haus"] and vals["haus"] not in haeuser(iid):
        raise ValueError(f"Kein Mietobjekt gehört zum Haus „{vals['haus']}“.")
    if vals["hausgeld_eigentuemer_id"]:
        vals["art"] = "einnahme"  # Hausgeld ist immer eine Einnahme; Korrekturen mit negativem Betrag
    vals["erstattet"] = (f.get("erstattet") or None) if vals["bezahlt"] == "bar" and vals["art"] == "ausgabe" else None
    return vals


def _buchungsjahr(standard):
    """Abrechnungsjahr der Buchung: vom Formular (Rückfrage, wenn das Belegdatum in einem anderen Jahr liegt), sonst standard."""
    j = request.form.get("buchungsjahr", type=int)
    return j if j and 1990 <= j <= 2200 else standard


def _jahr_hinweis(j):
    if j != jahr():
        flash(f"Die Buchung steht im Jahr {j}; die Ansicht wurde auf {j} umgestellt.")


def _buchung_reiter():
    """Nach dem Speichern zurück auf den Reiter, von dem aus gebucht wurde."""
    return "ruecklage" if request.form.get("reiter") == "ruecklage" else "buchungen"


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
    j = _buchungsjahr(jahr())
    vals = buchung_werte(iid)
    if not vals["datum"]:
        raise ValueError("Bitte das Datum des Belegs angeben.")
    vals["kosten_id"] = kostenposition(immo, j, vals["kostenart_id"], vals["haus"]) if vals["kostenart_id"] else None
    vals["dokument_id"] = _beleg_speichern(immo, j, vals)
    exe(f"INSERT INTO buchung (immobilie_id, jahr, {', '.join(vals)}) VALUES (?, ?, {', '.join('?' * len(vals))})",
        [iid, j, *vals.values()])
    if vals["kosten_id"]:
        kosten_aus_buchungen(vals["kosten_id"])
    # Für die nächste Zeile vorbelegen, damit mehrere Belege schnell hintereinander gehen
    vorlage = {"datum": vals["datum"], "art": vals["art"], "bezahlt": vals["bezahlt"], "ziel": ziel_wert(vals)}
    if _buchung_reiter() == "ruecklage":
        session["ruecklage_vorlage"] = {**vorlage, "rl_art": request.form.get("rl_art")}
    else:
        session["buchung_vorlage"] = vorlage
    _jahr_hinweis(j)
    return redirect(url_for("immobilie", iid=iid, reiter=_buchung_reiter(), neu=1, jahr=j if j != jahr() else None))


@app.post("/buchungen/<int:bid>")
@admin_noetig
def buchung_speichern(bid):
    b = row("SELECT * FROM buchung WHERE id = ?", (bid,))
    immo = row("SELECT * FROM immobilie WHERE id = ?", (b["immobilie_id"],))
    vals = buchung_werte(immo["id"])
    vals["jahr"] = j = _buchungsjahr(b["jahr"])
    vals["kosten_id"] = kostenposition(immo, j, vals["kostenart_id"], vals["haus"]) if vals["kostenart_id"] else None
    dok = _beleg_speichern(immo, j, vals)
    if dok:
        vals["dokument_id"] = dok
    exe(f"UPDATE buchung SET {', '.join(k + ' = ?' for k in vals)} WHERE id = ?", [*vals.values(), bid])
    if vals["kosten_id"]:
        kosten_aus_buchungen(vals["kosten_id"])
    if b["kosten_id"] and b["kosten_id"] != vals["kosten_id"]:
        kosten_aus_buchungen(b["kosten_id"])
    _jahr_hinweis(j)
    return redirect(url_for("immobilie", iid=immo["id"], reiter=_buchung_reiter(), jahr=j if j != jahr() else None))


@app.post("/buchungen/<int:bid>/jahr")
@admin_noetig
def buchung_ins_datumsjahr(bid):
    """Buchung in das Jahr ihres Belegdatums verschieben (z. B. versehentlich im falschen Jahr erfasst)."""
    b = row("SELECT * FROM buchung WHERE id = ?", (bid,))
    immo = row("SELECT * FROM immobilie WHERE id = ?", (b["immobilie_id"],))
    if not b["datum"]:
        raise ValueError("Die Buchung hat kein Datum.")
    j = int(b["datum"][:4])
    kid = kostenposition(immo, j, b["kostenart_id"], b["haus"]) if b["kostenart_id"] else None
    exe("UPDATE buchung SET jahr = ?, kosten_id = ? WHERE id = ?", (j, kid, bid))
    if kid:
        kosten_aus_buchungen(kid)
    if b["kosten_id"] and b["kosten_id"] != kid:
        kosten_aus_buchungen(b["kosten_id"])
    flash(f"„{b['text']}“ steht jetzt im Jahr {j}.")
    return zurueck()


@app.post("/buchungen/<int:bid>/erstattet")
@admin_noetig
def buchung_erstattet(bid):
    b = row("SELECT * FROM buchung WHERE id = ?", (bid,))
    exe("UPDATE buchung SET erstattet = ? WHERE id = ?", (date.today().isoformat(), bid))
    return redirect(url_for("immobilie", iid=b["immobilie_id"], reiter=_buchung_reiter()))


@app.post("/buchungen/<int:bid>/loeschen")
@admin_noetig
def buchung_loeschen(bid):
    b = row("SELECT * FROM buchung WHERE id = ?", (bid,))
    exe("DELETE FROM buchung WHERE id = ?", (bid,))
    if b["kosten_id"]:
        kosten_aus_buchungen(b["kosten_id"])
    return redirect(url_for("immobilie", iid=b["immobilie_id"], reiter=_buchung_reiter()))


# ---------- Daueraufträge ----------

RHYTHMEN = {"monat": ("monatlich", 1), "quartal": ("vierteljährlich", 3), "halbjahr": ("halbjährlich", 6),
            "jahr": ("jährlich", 12)}


def plus_monate(d, n):
    m = d.month - 1 + n
    j, m = d.year + m // 12, m % 12 + 1
    tage = [31, 29 if j % 4 == 0 and (j % 100 or j % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(j, m, min(d.day, tage))


def faelligkeiten(da, j):
    """Fälligkeiten eines Dauerauftrags im Jahr j: ab „von“ im Rhythmus, höchstens bis „bis“."""
    von, bis = parse_date(da["von"]), parse_date(da["bis"]) if da["bis"] else None
    schritt, erg, k = RHYTHMEN[da["rhythmus"]][1], [], 0
    while True:
        d = plus_monate(von, k * schritt)
        if d.year > j or (bis and d > bis):
            return erg
        if d.year == j:
            erg.append(d)
        k += 1


def dauerauftraege(iid, j):
    """Daueraufträge des Jahres mit Rechenweg und dem, was davon schon gebucht ist."""
    erg = rows("SELECT d.*, ka.name AS kostenart FROM dauerauftrag d LEFT JOIN kostenart ka ON ka.id = d.kostenart_id "
               "WHERE d.immobilie_id = ? AND d.jahr = ? ORDER BY d.text COLLATE NATUERLICH, d.von", (iid, j))
    for da in erg:
        da["ziel"] = ziel_wert(da)
        if da["hausgeld_eigentuemer_id"]:
            name = person_name(one("SELECT * FROM benutzer WHERE id = ?", (da["hausgeld_eigentuemer_id"],)) or {})
            wids = hausgeld_wohnungen(iid, da)
            fuer = ", ".join(row("SELECT bezeichnung FROM wohnung WHERE id = ?", (w,))["bezeichnung"] for w in wids)
            da["ziel_text"] = f"Hausgeld {name} · {fuer or 'keine Wohnung'}"
        else:
            da["ziel_text"] = da["kostenart"] or "→ Rücklage"
        da["termine"] = faelligkeiten(da, j)
        da["soll"] = rund(len(da["termine"]) * da["betrag"])
        da["rechenweg"] = f"{len(da['termine'])} × {de_num(da['betrag'])} € = {de_num(da['soll'])} €"
        da["gebucht"] = rows("SELECT * FROM buchung WHERE dauerauftrag_id = ? AND jahr = ? ORDER BY datum", (da["id"], j))
        da["gebucht_summe"] = rund(sum(b["betrag"] for b in da["gebucht"]))
        if da["einzeln"]:
            daten = {b["datum"] for b in da["gebucht"]}
            da["offen"] = [d for d in da["termine"] if d.isoformat() not in daten]
            da["buchung"] = None
        else:
            da["offen"] = [] if da["gebucht"] else da["termine"]
            da["buchung"] = da["gebucht"][0] if da["gebucht"] else None
    return erg


def _dauerauftrag_werte(iid, j):
    f = request.form
    vals = {"text": f.get("text", "").strip(), "art": f.get("art"), "betrag": parse_num(f.get("betrag")),
            "rhythmus": f.get("rhythmus"), "einzeln": 1 if f.get("einzeln") else 0,
            "von": f.get("von") or f"{j}-01-01", "bis": f.get("bis") or f"{j}-12-31", "notiz": f.get("notiz", "").strip()}
    if not vals["text"]:
        raise ValueError("Bitte eine Beschreibung angeben, z. B. „Hausmeister“.")
    if vals["art"] not in ("ausgabe", "einnahme") or vals["rhythmus"] not in RHYTHMEN:
        raise ValueError("Bitte Art und Rhythmus wählen.")
    if not vals["betrag"]:
        raise ValueError("Bitte einen Betrag angeben.")
    if not (vals["von"].startswith(str(j)) and vals["bis"].startswith(str(j))):
        raise ValueError(f"Ein Dauerauftrag gilt nur für ein Jahr: „ab“ und „bis“ müssen in {j} liegen. "
                         "Fürs nächste Jahr übernimmst du ihn dort aus dem Vorjahr.")
    if vals["bis"] < vals["von"]:
        raise ValueError("„bis“ liegt vor „ab“.")
    vals["kostenart_id"], vals["hausgeld_eigentuemer_id"], vals["hausgeld_wohnung_id"] = \
        ziel_aufloesen(f.get("ziel", ""), iid)
    if vals["hausgeld_eigentuemer_id"]:
        vals["art"] = "einnahme"
    return vals


def _zu_dauerauftraegen(iid):
    return redirect(url_for("immobilie", iid=iid, reiter="buchungen") + "#dauerauftraege")


@app.post("/immobilien/<int:iid>/dauerauftraege")
@admin_noetig
def dauerauftrag_neu(iid):
    row("SELECT id FROM immobilie WHERE id = ?", (iid,))
    j = jahr()
    vals = _dauerauftrag_werte(iid, j)
    exe(f"INSERT INTO dauerauftrag (immobilie_id, jahr, {', '.join(vals)}) VALUES (?, ?, {', '.join('?' * len(vals))})",
        [iid, j, *vals.values()])
    return _zu_dauerauftraegen(iid)


@app.post("/dauerauftraege/<int:did>")
@admin_noetig
def dauerauftrag_speichern(did):
    da = row("SELECT * FROM dauerauftrag WHERE id = ?", (did,))
    vals = _dauerauftrag_werte(da["immobilie_id"], da["jahr"])
    exe(f"UPDATE dauerauftrag SET {', '.join(k + ' = ?' for k in vals)} WHERE id = ?", [*vals.values(), did])
    return _zu_dauerauftraegen(da["immobilie_id"])


@app.post("/dauerauftraege/<int:did>/loeschen")
@admin_noetig
def dauerauftrag_loeschen(did):
    da = row("SELECT * FROM dauerauftrag WHERE id = ?", (did,))
    exe("DELETE FROM dauerauftrag WHERE id = ?", (did,))
    flash(f"Dauerauftrag „{da['text']}“ gelöscht. Bereits gebuchte Buchungen bleiben erhalten.")
    return _zu_dauerauftraegen(da["immobilie_id"])


def _dauerauftrag_buchung(immo, j, da, datum, text, betrag, notiz, buchung=None):
    """Buchung aus einem Dauerauftrag anlegen bzw. (buchung) überschreiben; Gebäudekosten werden nachgezogen."""
    vals = {"datum": datum.isoformat(), "text": text, "art": da["art"], "betrag": betrag, "bezahlt": "konto",
            "notiz": notiz, "kostenart_id": da["kostenart_id"], "hausgeld_eigentuemer_id": da["hausgeld_eigentuemer_id"],
            "hausgeld_wohnung_id": da["hausgeld_wohnung_id"],
            "kosten_id": kostenposition(immo, j, da["kostenart_id"], buchung["haus"] if buchung else "")
            if da["kostenart_id"] else None}
    if buchung:
        exe(f"UPDATE buchung SET {', '.join(k + ' = ?' for k in vals)} WHERE id = ?", [*vals.values(), buchung["id"]])
        if buchung["kosten_id"] and buchung["kosten_id"] != vals["kosten_id"]:
            kosten_aus_buchungen(buchung["kosten_id"])
    else:
        exe(f"INSERT INTO buchung (immobilie_id, jahr, dauerauftrag_id, {', '.join(vals)}) "
            f"VALUES (?, ?, ?, {', '.join('?' * len(vals))})", [immo["id"], j, da["id"], *vals.values()])
    if vals["kosten_id"]:
        kosten_aus_buchungen(vals["kosten_id"])


def _dauerauftrag_buchen(immo, j, da):
    """Offene Termine buchen: je Termin eine Buchung (einzeln) oder eine Jahresbuchung mit Rechenweg."""
    if da["einzeln"]:
        for d in da["offen"]:
            _dauerauftrag_buchung(immo, j, da, d, f"{da['text']} {d:%m/%Y}", da["betrag"],
                                  f"Dauerauftrag ({RHYTHMEN[da['rhythmus']][0]})")
    else:
        _dauerauftrag_buchung(immo, j, da, da["termine"][-1], f"{da['text']} {j}", da["soll"],
                              f"{da['rechenweg']} ({RHYTHMEN[da['rhythmus']][0]}, Dauerauftrag)", da["buchung"])


@app.post("/immobilien/<int:iid>/dauerauftraege/buchen")
@admin_noetig
def dauerauftraege_buchen(iid):
    """Offene Termine aller Daueraufträge des Jahres buchen; vorhandene (evtl. von Hand geänderte) bleiben unberührt."""
    immo = row("SELECT * FROM immobilie WHERE id = ?", (iid,))
    j = jahr()
    offen = [da for da in dauerauftraege(iid, j) if da["offen"]]
    for da in offen:
        _dauerauftrag_buchen(immo, j, da)
    flash(f"{len(offen)} Dauerauftrag/-aufträge für {j} gebucht." if offen else f"Für {j} ist schon alles gebucht.")
    return _zu_dauerauftraegen(iid)


@app.post("/dauerauftraege/<int:did>/angleichen")
@admin_noetig
def dauerauftrag_angleichen(did):
    """Jahresbuchung wieder auf den Rechenweg setzen (z. B. nach Änderung des Betrags)."""
    da = row("SELECT * FROM dauerauftrag WHERE id = ?", (did,))
    immo = row("SELECT * FROM immobilie WHERE id = ?", (da["immobilie_id"],))
    da = next(x for x in dauerauftraege(immo["id"], da["jahr"]) if x["id"] == did)
    if da["termine"] and not da["einzeln"]:
        _dauerauftrag_buchung(immo, da["jahr"], da, da["termine"][-1], f"{da['text']} {da['jahr']}", da["soll"],
                              f"{da['rechenweg']} ({RHYTHMEN[da['rhythmus']][0]}, Dauerauftrag)", da["buchung"])
    return _zu_dauerauftraegen(immo["id"])


def _ins_jahr(datum, j):
    """Datum ins Jahr j verschieben (29.02. wird in Nicht-Schaltjahren zum 28.02.)."""
    d = parse_date(datum)
    return plus_monate(d, (j - d.year) * 12).isoformat()


@app.post("/immobilien/<int:iid>/dauerauftraege/vorjahr")
@admin_noetig
def dauerauftraege_vorjahr(iid):
    """Daueraufträge des Vorjahres ins angezeigte Jahr kopieren – zum Prüfen und Anpassen an den neuen Wirtschaftsplan."""
    row("SELECT id FROM immobilie WHERE id = ?", (iid,))
    j = jahr()
    if one("SELECT 1 FROM dauerauftrag WHERE immobilie_id = ? AND jahr = ?", (iid, j)):
        raise ValueError(f"Für {j} gibt es schon Daueraufträge.")
    alte = rows("SELECT * FROM dauerauftrag WHERE immobilie_id = ? AND jahr = ?", (iid, j - 1))
    for da in alte:
        exe("INSERT INTO dauerauftrag (immobilie_id, jahr, text, art, kostenart_id, hausgeld_eigentuemer_id, "
            "hausgeld_wohnung_id, betrag, rhythmus, einzeln, von, bis, notiz) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (iid, j, da["text"], da["art"], da["kostenart_id"], da["hausgeld_eigentuemer_id"], da["hausgeld_wohnung_id"],
             da["betrag"], da["rhythmus"], da["einzeln"], _ins_jahr(da["von"], j), _ins_jahr(da["bis"], j), da["notiz"]))
    flash(f"{len(alte)} Dauerauftrag/-aufträge aus {j - 1} übernommen. Bitte Beträge prüfen, dann buchen.")
    return _zu_dauerauftraegen(iid)


# ---------- Erhaltungsrücklage ----------

def ruecklage(iid, j):
    """Entwicklung der Erhaltungsrücklage im Jahr j (Vermögensbericht der WEG). Der Anfangsbestand ist eingetragen
    oder wird ab dem letzten eingetragenen Jahr fortgeschrieben; None, wenn noch nie einer eingetragen wurde."""
    def bewegungen(jj):
        zufuehrung = one("SELECT COALESCE(SUM(k.betrag), 0) AS s FROM kosten k JOIN kostenart ka ON ka.id = k.kostenart_id "
                         "WHERE k.immobilie_id = ? AND k.jahr = ? AND k.wohnung_id IS NULL AND ka.ruecklage = 1",
                         (iid, jj))["s"]
        buchungen = rows("SELECT * FROM buchung WHERE immobilie_id = ? AND jahr = ? AND kostenart_id IS NULL "
                         "AND hausgeld_eigentuemer_id IS NULL "
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
    # Kontoblatt: alle Bewegungen des Jahres (Zuführungen sind Buchungen auf eine Rücklage-Kostenart) mit laufendem Stand
    eintraege = rows("SELECT b.*, ka.name AS kostenart FROM buchung b LEFT JOIN kostenart ka ON ka.id = b.kostenart_id "
                     "WHERE b.immobilie_id = ? AND b.jahr = ? AND b.hausgeld_eigentuemer_id IS NULL "
                     "AND (b.kostenart_id IS NULL OR ka.ruecklage = 1)",
                     (iid, j))
    eintraege.sort(key=lambda b: (b["datum"] or f"{j}-12-31", b["id"]))
    stand = anfang or 0
    for b in eintraege:
        zufluss = b["art"] == "einnahme" if b["kostenart_id"] is None else b["art"] == "ausgabe"
        b["rl_art"] = "zufuehrung" if b["kostenart_id"] else ("einnahme" if zufluss else "entnahme")
        b["wert"] = b["betrag"] if zufluss else -b["betrag"]
        stand += b["wert"]
        b["stand"] = rund(stand)
    eintrag = one("SELECT * FROM ruecklage_bestand WHERE immobilie_id = ? AND jahr = ?", (iid, j))
    return {"anfang": None if anfang is None else rund(anfang), "eingetragen": bool(eintrag),
            "notiz": eintrag["notiz"] if eintrag else "", "eintraege": eintraege,
            "zufluesse": rund(sum(b["wert"] for b in eintraege if b["wert"] > 0)),
            "abfluesse": rund(-sum(b["wert"] for b in eintraege if b["wert"] < 0)),
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
        exe("INSERT INTO ruecklage_bestand (immobilie_id, jahr, betrag, notiz) VALUES (?, ?, ?, ?)",
            (iid, j, parse_num(wert), request.form.get("notiz", "").strip()))
    flash("Anfangsbestand der Rücklage gespeichert." if wert else
          "Eingetragener Anfangsbestand entfernt; er wird, falls möglich, aus dem Vorjahr fortgeschrieben.")
    return redirect(url_for("immobilie", iid=iid, reiter="ruecklage"))


# ---------- Konten (Stände zum Stichtag laut Kontoauszug) ----------

def konten(iid, j):
    """Konten mit Stand zu Jahresbeginn (letzter Stand bis 31.12. des Vorjahres) und Jahresende (letzter Stand bis
    31.12. des Jahres) sowie den Ständen, die im Jahr eingetragen sind."""
    erg = rows("SELECT * FROM konto WHERE immobilie_id = ? ORDER BY ruecklage, name COLLATE NATUERLICH", (iid,))
    for k in erg:
        def letzter(bis):
            return one("SELECT * FROM kontostand WHERE konto_id = ? AND datum <= ? ORDER BY datum DESC, id DESC LIMIT 1",
                       (k["id"], bis))
        k["anfang"], k["ende"] = letzter(f"{j - 1}-12-31"), letzter(f"{j}-12-31")
        k["staende"] = rows("SELECT * FROM kontostand WHERE konto_id = ? AND substr(datum, 1, 4) = ? ORDER BY datum, id",
                            (k["id"], str(j)))
        if k["ende"] and not k["ende"]["datum"].startswith(str(j)):  # kein Stand in diesem Jahr
            k["zuletzt"], k["ende"] = k["ende"], None
    rl = [k for k in erg if k["ruecklage"]]
    return {"liste": erg,
            "anfang": rund(sum(k["anfang"]["betrag"] for k in erg if k["anfang"])),
            "ende": rund(sum(k["ende"]["betrag"] for k in erg if k["ende"])),
            "rl_konten": len(rl), "rl_ende": rund(sum(k["ende"]["betrag"] for k in rl if k["ende"])),
            "rl_anfang": rund(sum(k["anfang"]["betrag"] for k in rl if k["anfang"])),
            "rl_anfang_vorhanden": any(k["anfang"] for k in rl),
            "rl_vollstaendig": all(k["ende"] for k in rl),
            "staende": sorted(({**st, "konto": k["name"]} for k in erg for st in k["staende"]),
                              key=lambda st: (st["datum"], st["id"]))}


def _konto_laden(kid):
    k = row("SELECT * FROM konto WHERE id = ?", (kid,))
    return k, row("SELECT * FROM immobilie WHERE id = ?", (k["immobilie_id"],))


def _konto_werte():
    f = request.form
    name = f.get("name", "").strip()
    if not name:
        raise ValueError("Bitte einen Namen für das Konto angeben, z. B. „Tagesgeld“.")
    return {"name": name, "ruecklage": 1 if f.get("ruecklage") else 0, "iban": f.get("iban", "").strip().upper(),
            "bank": f.get("bank", "").strip()}


@app.post("/immobilien/<int:iid>/konten")
@admin_noetig
def konto_neu(iid):
    row("SELECT id FROM immobilie WHERE id = ?", (iid,))
    vals = _konto_werte()
    exe(f"INSERT INTO konto (immobilie_id, {', '.join(vals)}) VALUES (?, {', '.join('?' * len(vals))})", [iid, *vals.values()])
    return redirect(url_for("immobilie", iid=iid, reiter="ruecklage") + "#konten")


@app.post("/konten/<int:kid>")
@admin_noetig
def konto_speichern(kid):
    k, immo = _konto_laden(kid)
    vals = _konto_werte()
    exe(f"UPDATE konto SET {', '.join(x + ' = ?' for x in vals)} WHERE id = ?", [*vals.values(), kid])
    return redirect(url_for("immobilie", iid=immo["id"], reiter="ruecklage") + "#konten")


@app.post("/konten/<int:kid>/loeschen")
@admin_noetig
def konto_loeschen(kid):
    k, immo = _konto_laden(kid)
    exe("DELETE FROM konto WHERE id = ?", (kid,))
    flash(f"Konto „{k['name']}“ mit allen Kontoständen gelöscht.")
    return redirect(url_for("immobilie", iid=immo["id"], reiter="ruecklage") + "#konten")


def _kontostand_werte():
    f = request.form
    datum = f.get("datum") or ""
    if not datum or not f.get("betrag", "").strip():
        raise ValueError("Bitte Datum und Kontostand angeben.")
    return {"datum": datum, "betrag": parse_num(f.get("betrag")), "notiz": f.get("notiz", "").strip()}


def _zum_stand(iid, datum):
    """Zurück zur Rücklage – im Jahr des Kontostands, damit er gleich zu sehen ist."""
    j = int(datum[:4])
    if j != jahr():
        flash(f"Der Kontostand vom {parse_date(datum):%d.%m.%Y} gehört ins Jahr {j}; die Ansicht wurde umgestellt.")
    return redirect(url_for("immobilie", iid=iid, reiter="ruecklage", jahr=j if j != jahr() else None) + "#konten")


@app.post("/immobilien/<int:iid>/kontostaende")
@admin_noetig
def kontostand_neu(iid):
    k, immo = _konto_laden(int(request.form.get("konto_id") or 0))
    if immo["id"] != iid:
        abort(400)
    vals = _kontostand_werte()
    exe("INSERT INTO kontostand (konto_id, datum, betrag, notiz) VALUES (?, ?, ?, ?)", (k["id"], *vals.values()))
    session["kontostand_vorlage"] = {"konto_id": k["id"], "datum": vals["datum"]}
    return _zum_stand(iid, vals["datum"])


@app.post("/kontostaende/<int:sid>")
@admin_noetig
def kontostand_speichern(sid):
    st = row("SELECT * FROM kontostand WHERE id = ?", (sid,))
    k, immo = _konto_laden(st["konto_id"])
    vals = _kontostand_werte()
    exe("UPDATE kontostand SET datum = ?, betrag = ?, notiz = ? WHERE id = ?", (*vals.values(), sid))
    return _zum_stand(immo["id"], vals["datum"])


@app.post("/kontostaende/<int:sid>/loeschen")
@admin_noetig
def kontostand_loeschen(sid):
    st = row("SELECT * FROM kontostand WHERE id = ?", (sid,))
    k, immo = _konto_laden(st["konto_id"])
    exe("DELETE FROM kontostand WHERE id = ?", (sid,))
    return redirect(url_for("immobilie", iid=immo["id"], reiter="ruecklage") + "#konten")


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
                                   for k in ("vorname", "name", "strasse", "hausnummer", "plz", "ort", "email", "telefon", "mobil")})
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
    reiter = [("abrechnung", "Abrechnung"), ("mieter", "Mieter"), ("zaehler", "Zähler"), ("vertraege", "Verträge"),
              ("dokumente", "Dokumente"), ("stammdaten", "Stammdaten")]
    vliste = vertraege(immo["id"], wid, j=j)
    return render_template(
        "wohnung.html", **spalte(immo, wid), w=w, r=r, erg=erg, mvs=mvs, direkt=direkt,
        reiter=reiter, aktiv=reiter_waehlen(reiter), vliste=vliste, vk=vertrag_kennzahlen(vliste),
        mietvertraege=mietvertraege(wid),
        benutzer=rows("SELECT * FROM benutzer ORDER BY name, vorname") if ist_admin() else [],
        pruefung=pruefungen(immo, erg, {wid}), vorhanden=vorhandene_kostenarten(immo["id"], j, wid),
        darf=wohnung_bearbeitbar(w), kostenarten=kostenarten_aktiv(),  # „nicht genutzt“ gilt nur für die Gebäudekosten
        eigentuemer=one("SELECT * FROM benutzer WHERE id = ?", (w["eigentuemer_id"],)),
        zaehler=zaehler_mit_staenden("SELECT * FROM zaehler WHERE wohnung_id = ? "
                                     "ORDER BY art, ausgebaut IS NOT NULL, bezeichnung COLLATE NATUERLICH, id", (wid,), j),
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
    vals = {"von": von, "bis": bis, "vorauszahlung_monat": parse_num(f.get("vorauszahlung_monat")),
            "neue_anschrift": f.get("neue_anschrift", "").strip(), "notiz": f.get("notiz", "").strip()}
    if "kaltmiete" in f:  # Mietvertragsangaben
        mietart = f.get("mietart", "")
        if mietart not in MIETARTEN:
            raise ValueError("Unbekannte Mietart.")
        vals.update(kaltmiete=parse_num(f.get("kaltmiete")), mietart=mietart,
                    befristet_bis=f.get("befristet_bis") or None, anpassung_am=f.get("anpassung_am") or None)
    return vals


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
    return redirect(url_for("wohnung", wid=wid, reiter="mieter"))


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
    return redirect(url_for("wohnung", wid=mv["wohnung_id"], reiter="mieter"))


@app.post("/mieter/<int:mid>/loeschen")
def mv_loeschen(mid):
    mv = _mv_laden(mid)
    exe("DELETE FROM mietverhaeltnis WHERE id = ?", (mid,))
    return redirect(url_for("wohnung", wid=mv["wohnung_id"], reiter="mieter"))


@app.post("/mieter/<int:mid>/personen")
def person_neu(mid):
    mv = _mv_laden(mid)
    name = request.form.get("name", "").strip()
    if not name:
        raise ValueError("Bitte einen Namen angeben.")
    exe("INSERT INTO mieter_person (mv_id, vorname, name) VALUES (?, ?, ?)",
        (mid, request.form.get("vorname", "").strip(), name))
    return redirect(url_for("wohnung", wid=mv["wohnung_id"], reiter="mieter"))


@app.post("/personen/<int:pid>/loeschen")
def person_loeschen(pid):
    p = row("SELECT * FROM mieter_person WHERE id = ?", (pid,))
    mv = _mv_laden(p["mv_id"])
    exe("DELETE FROM mieter_person WHERE id = ?", (pid,))
    return redirect(url_for("wohnung", wid=mv["wohnung_id"], reiter="mieter"))


# ---------- Vorauszahlungen ----------

@app.post("/wohnungen/<int:wid>/vorauszahlungen")
def vorauszahlungen_speichern(wid):
    wohnung_laden(wid, bearbeiten=True)
    j = jahr()
    mv_ids = {m["id"] for m in rows("SELECT id FROM mietverhaeltnis WHERE wohnung_id = ?", (wid,))}
    w = row("SELECT * FROM wohnung WHERE id = ?", (wid,))
    hausgeld_gebucht = w["immobilie_id"] and wid in hausgeld_aus_buchungen(w["immobilie_id"], j)[0]
    con = db.get_db()
    for k, v in request.form.items():
        if not k.startswith("vz_") or (k == "vz_eigentuemer" and hausgeld_gebucht):
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
    aus_buchungen = hausgeld_aus_buchungen(iid, j)[0]
    wohnungen = {w["id"] for w in rows("SELECT id FROM wohnung WHERE immobilie_id = ?", (iid,))} - set(aus_buchungen)
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


def _zaehler_vertrag(vid, wid, iid):
    """Vertrag für einen Zähler prüfen: Wohnungszähler nur mit Verträgen dieser Wohnung, Hauptzähler mit denen der
    Immobilie. Leer = keiner."""
    if not vid:
        return None
    v = row("SELECT * FROM vertrag WHERE id = ?", (int(vid),))
    if (wid and v["wohnung_id"] != wid) or (not wid and (v["wohnung_id"] or v["immobilie_id"] != iid)):
        raise ValueError("Dieser Vertrag gehört nicht zu diesem Zähler.")
    return v["id"]


@app.post("/zaehler")
def zaehler_neu():
    f = request.form
    art = f.get("art")
    if art not in ZAEHLERARTEN:
        raise ValueError("Unbekannte Zählerart.")
    wid = int(f["wohnung_id"]) if f.get("wohnung_id") else None
    iid = int(f["immobilie_id"]) if f.get("immobilie_id") else None
    _zaehler_recht({"wohnung_id": wid})
    vid = _zaehler_vertrag(f.get("vertrag_id"), wid, iid)
    zid = exe("INSERT INTO zaehler (wohnung_id, immobilie_id, art, nummer, bezeichnung, eingebaut, notiz, vertrag_id) "
              "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
              (wid, None if wid else iid, art, f.get("nummer", "").strip(), f.get("bezeichnung", "").strip(),
               f.get("eingebaut") or None, f.get("notiz", "").strip(), vid))
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
    neu = exe("INSERT INTO zaehler (wohnung_id, immobilie_id, art, nummer, bezeichnung, eingebaut, notiz, vertrag_id) "
              "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (z["wohnung_id"], z["immobilie_id"], z["art"], f.get("nummer", "").strip(),
                                                  z["bezeichnung"], datum, z["notiz"], z["vertrag_id"]))
    exe("INSERT INTO zaehlerstand (zaehler_id, datum, stand, notiz) VALUES (?, ?, ?, 'Einbau')",
        (neu, datum, parse_num(f.get("anfangsstand"))))
    flash("Zähler getauscht. Der alte Zähler bleibt mit seinen Ständen erhalten.")
    return zurueck()


@app.post("/zaehler/<int:zid>/bearbeiten")
def zaehler_bearbeiten(zid):
    z = row("SELECT * FROM zaehler WHERE id = ?", (zid,))
    _zaehler_recht(z)
    f = request.form
    iid = z["immobilie_id"] or one("SELECT immobilie_id FROM wohnung WHERE id = ?", (z["wohnung_id"],))["immobilie_id"]
    exe("UPDATE zaehler SET bezeichnung = ?, nummer = ?, notiz = ?, vertrag_id = ? WHERE id = ?",
        (f.get("bezeichnung", "").strip(), f.get("nummer", "").strip(), f.get("notiz", "").strip(),
         _zaehler_vertrag(f.get("vertrag_id"), z["wohnung_id"], iid), zid))
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


def _zur_ablesung(datum):
    """Zurück zur Seite – im Jahr der Ablesung, damit sie gleich zu sehen ist."""
    ziel = request.form.get("next") or request.referrer or "/"
    j = int(datum[:4])
    if j != jahr():
        flash(f"Die Ablesung vom {parse_date(datum):%d.%m.%Y} gehört ins Jahr {j}; die Ansicht wurde umgestellt.")
        ziel = ziel.split("#")[0] + ("&" if "?" in ziel else "?") + f"jahr={j}"
    return redirect(ziel)


@app.post("/zaehlerstaende")
def zaehlerstand_eintragen():
    """Ablesung über die Auswahl „Zähler“ in der Eingabezeile."""
    zid = int(request.form.get("zaehler_id") or 0)
    zaehlerstand_neu(zid)
    return _zur_ablesung(request.form["datum"])


@app.post("/zaehlerstaende/<int:sid>")
def zaehlerstand_speichern(sid):
    s = row("SELECT * FROM zaehlerstand WHERE id = ?", (sid,))
    _zaehler_recht(row("SELECT * FROM zaehler WHERE id = ?", (s["zaehler_id"],)))
    f = request.form
    if not f.get("datum") or not f.get("stand", "").strip():
        raise ValueError("Datum und Zählerstand sind Pflichtfelder.")
    exe("UPDATE zaehlerstand SET datum = ?, stand = ?, notiz = ? WHERE id = ?",
        (f["datum"], parse_num(f["stand"]), f.get("notiz", "").strip(), sid))
    return _zur_ablesung(f["datum"])


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
