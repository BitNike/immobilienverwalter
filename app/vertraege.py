"""Verträge je Immobilie oder Mietobjekt (Laufzeit, Kündigungsfrist, Preisgarantie, Tarif), Erinnerung per Mail.
Die Berechnung des Kündigungstermins stammt aus der Vertragsübersicht (rechnung.termin)."""
import calendar
import logging
import os
import threading
import time
from datetime import date

from flask import abort, flash, g, redirect, render_template, request, url_for

import mail
from calc import de_num, parse_date, parse_num, rund
from core import (admin_noetig, app, einstellung, einstellung_setzen, exe, ist_admin, jahr, one, person_name, row, rows,
                  wohnung_laden)

ZAHLWEISEN = {"monatlich": ("monatlich", 12, "monat"), "vierteljaehrlich": ("vierteljährlich", 4, "quartal"),
              "halbjaehrlich": ("halbjährlich", 2, "halbjahr"), "jaehrlich": ("jährlich", 1, "jahr"),
              "einmalig": ("einmalig", 0, None)}
VERLAENGERUNG = {12: "um 1 Jahr", 1: "monatlich", 24: "um 2 Jahre", 36: "um 3 Jahre", 60: "um 5 Jahre",
                 0: "keine (endet automatisch)"}
FRIST = {0: "jederzeit zum Ablauf", 1: "1 Monat", 2: "2 Monate", 3: "3 Monate", 6: "6 Monate"}
ARTEN = ["Strom (Allgemeinstrom)", "Gas", "Wasser / Abwasser", "Gebäudeversicherung", "Haftpflichtversicherung",
         "Hausmeister", "Gartenpflege", "Wartung Heizung", "Schornsteinfeger", "Müllentsorgung", "Internet / TV",
         "Aufzug", "Rauchmelder", "Sonstiges"]
STATUS = {"laeuft": "läuft", "bald": "bald kündigen", "endet": "endet", "gekuendigt": "gekündigt", "beendet": "beendet",
          "unbekannt": "Daten fehlen"}
MIETARTEN = {"": "ohne Anpassung", "staffel": "Staffelmiete", "index": "Indexmiete"}
log = logging.getLogger(__name__)


# ---------- Berechnung (wie in der Vertragsübersicht) ----------

def plus_monate(d, n):
    m = d.month - 1 + n
    j, m = d.year + m // 12, m % 12 + 1
    return date(j, m, min(d.day, calendar.monthrange(j, m)[1]))


def termin(beginn, ablauf, verlaengerung, frist, gekuendigt_zum, heute, vorlauf):
    """Nächstes Vertragsende, zu dem noch gekündigt werden kann. Ohne Ablauf gilt der erste Jahrestag des Beginns.
    Ist die Frist für das aktuelle Ende verstrichen, wird um die Verlängerung weitergezählt (immer von der Basis aus).
    Nach der Mindestlaufzeit mit monatlicher Verlängerung ist der Vertrag laufend kündbar („flexibel“, nie „bald“)."""
    beginn, ablauf, gekuendigt_zum = parse_date(beginn), parse_date(ablauf), parse_date(gekuendigt_zum)
    leer = {"ende": None, "kuendigen_bis": None, "tage": None, "flexibel": False}
    if gekuendigt_zum:
        return {**leer, "status": "beendet" if gekuendigt_zum < heute else "gekuendigt", "ende": gekuendigt_zum}
    basis = ablauf or (plus_monate(beginn, 12) if beginn else None)
    if basis is None:
        return {**leer, "status": "unbekannt"}
    if not verlaengerung:
        return {**leer, "status": "beendet" if basis < heute else "endet", "ende": basis}
    ende, k = basis, 0
    while plus_monate(ende, -frist) < heute:
        k += 1
        ende = plus_monate(basis, k * verlaengerung)
    bis = plus_monate(ende, -frist)
    tage = (bis - heute).days
    flexibel = k > 0 and verlaengerung < 12
    return {"status": "bald" if tage <= vorlauf and not flexibel else "laeuft", "ende": ende, "kuendigen_bis": bis,
            "tage": tage, "flexibel": flexibel}


def stichtag(datum, heute, vorlauf):
    """Einzelnes Datum (Preisgarantie, Befristung, Mietanpassung): Tage bis dahin und ob es im Vorlauf liegt."""
    d = parse_date(datum)
    if d is None:
        return None
    tage = (d - heute).days
    return {"datum": d, "tage": tage, "bald": 0 <= tage <= vorlauf, "vorbei": tage < 0}


def vorlauf():
    try:
        return max(1, int(einstellung("erinnerung_vorlauf", "30")))
    except ValueError:
        return 30


def jahresbetrag(v):
    return rund((v["betrag"] or 0) * ZAHLWEISEN.get(v["zahlweise"], ZAHLWEISEN["monatlich"])[1])


def vertraege(iid, wid=None, heute=None, nur_sichtbare=True):
    """Verträge einer Immobilie (wid=None: alle, auch die der Mietobjekte) bzw. eines Mietobjekts, mit Termin."""
    heute = heute or date.today()
    sql = ("SELECT v.*, w.bezeichnung AS wohnung, w.eigentuemer_id, ka.name AS kostenart FROM vertrag v "
           "LEFT JOIN wohnung w ON w.id = v.wohnung_id LEFT JOIN kostenart ka ON ka.id = v.kostenart_id "
           "WHERE v.immobilie_id = ?")
    args = [iid]
    if wid is not None:
        sql += " AND v.wohnung_id = ?"
        args.append(wid)
    erg = rows(sql + " ORDER BY v.gekuendigt_zum IS NOT NULL, v.art COLLATE NATUERLICH, v.anbieter", args)
    if nur_sichtbare and not ist_admin():
        erg = [v for v in erg if not v["wohnung_id"] or v["eigentuemer_id"] == g.user["id"]]
    tage = vorlauf()
    for v in erg:
        v["termin"] = termin(v["beginn"], v["ablauf"], v["verlaengerung"], v["frist"], v["gekuendigt_zum"], heute, tage)
        v["preis"] = stichtag(v["preisgarantie_bis"], heute, tage)
        v["jahr"] = jahresbetrag(v)
        v["aktiv"] = v["termin"]["status"] not in ("beendet",)
        v["tarif"] = rund(v["verbrauch"] * v["arbeitspreis"] / 100 + (v["grundpreis"] or 0) * 12) \
            if v["verbrauch"] is not None and v["arbeitspreis"] is not None else None
    return erg


def kennzahlen(liste):
    aktiv = [v for v in liste if v["aktiv"]]
    naechste = sorted((v for v in aktiv if v["termin"]["kuendigen_bis"] and not v["termin"]["flexibel"]),
                      key=lambda v: v["termin"]["kuendigen_bis"])
    return {"anzahl": len(aktiv), "jahr": rund(sum(v["jahr"] for v in aktiv)),
            "naechste": naechste[0] if naechste else None,
            "bald": sum(1 for v in aktiv if v["termin"]["status"] == "bald" or (v["preis"] and v["preis"]["bald"]))}


def mietvertraege(wid, heute=None):
    """Mietverhältnisse eines Mietobjekts mit Vertragsangaben (Kaltmiete, Befristung, nächste Mietanpassung)."""
    heute = heute or date.today()
    erg = rows("SELECT * FROM mietverhaeltnis WHERE wohnung_id = ? ORDER BY von DESC", (wid,))
    for mv in erg:
        mv["personen"] = rows("SELECT * FROM mieter_person WHERE mv_id = ? ORDER BY id", (mv["id"],))
        mv["laufend"] = not mv["bis"] or mv["bis"] >= heute.isoformat()
        mv["befristung"] = stichtag(mv["befristet_bis"], heute, vorlauf()) if mv["laufend"] else None
        mv["anpassung"] = stichtag(mv["anpassung_am"], heute, vorlauf()) if mv["laufend"] else None
    return erg


# ---------- Pflege ----------

def _recht(immobilie_id, wohnung_id):
    if wohnung_id:
        w = wohnung_laden(wohnung_id, bearbeiten=True)
        if w["immobilie_id"] != immobilie_id:
            abort(400)
    elif not ist_admin():
        abort(403)


def _werte():
    f = request.form

    def zahl(name):
        return parse_num(f.get(name), None) if f.get(name, "").strip() else None

    vals = {"art": f.get("art", "").strip(), "anbieter": f.get("anbieter", "").strip(),
            "vertragsnummer": f.get("vertragsnummer", "").strip(), "beginn": f.get("beginn") or None,
            "ablauf": f.get("ablauf") or None, "verlaengerung": int(f.get("verlaengerung") or 12),
            "frist": int(f.get("frist") or 0), "gekuendigt_zum": f.get("gekuendigt_zum") or None,
            "preisgarantie_bis": f.get("preisgarantie_bis") or None, "betrag": parse_num(f.get("betrag")),
            "zahlweise": f.get("zahlweise", "monatlich"), "arbeitspreis": zahl("arbeitspreis"),
            "grundpreis": zahl("grundpreis"), "verbrauch": zahl("verbrauch"), "kontakt": f.get("kontakt", "").strip(),
            "notiz": f.get("notiz", "").strip(), "erinnern": 1 if f.get("erinnern") else 0,
            "kostenart_id": int(f["kostenart_id"]) if f.get("kostenart_id") else None}
    if not vals["art"]:
        raise ValueError("Bitte angeben, was für ein Vertrag es ist (z. B. „Strom (Allgemeinstrom)“).")
    if vals["zahlweise"] not in ZAHLWEISEN or vals["verlaengerung"] not in VERLAENGERUNG or vals["frist"] not in FRIST:
        raise ValueError("Bitte Zahlweise, Verlängerung und Kündigungsfrist wählen.")
    if vals["kostenart_id"]:
        row("SELECT id FROM kostenart WHERE id = ?", (vals["kostenart_id"],))
    return vals


def _zurueck(v):
    if request.form.get("seite") == "wohnung" and v["wohnung_id"]:
        return redirect(url_for("wohnung", wid=v["wohnung_id"], reiter="vertraege"))
    return redirect(url_for("immobilie", iid=v["immobilie_id"], reiter="vertraege"))


@app.post("/immobilien/<int:iid>/vertraege")
def vertrag_neu(iid):
    row("SELECT id FROM immobilie WHERE id = ?", (iid,))
    wid = int(request.form["wohnung_id"]) if request.form.get("wohnung_id") else None
    _recht(iid, wid)
    vals = _werte()
    exe(f"INSERT INTO vertrag (immobilie_id, wohnung_id, {', '.join(vals)}) VALUES (?, ?, {', '.join('?' * len(vals))})",
        [iid, wid, *vals.values()])
    flash(f"Vertrag „{vals['art']}“ angelegt.")
    return _zurueck({"immobilie_id": iid, "wohnung_id": wid})


@app.post("/vertraege/<int:vid>")
def vertrag_speichern(vid):
    v = row("SELECT * FROM vertrag WHERE id = ?", (vid,))
    _recht(v["immobilie_id"], v["wohnung_id"])
    vals = _werte()
    exe(f"UPDATE vertrag SET {', '.join(k + ' = ?' for k in vals)} WHERE id = ?", [*vals.values(), vid])
    return _zurueck(v)


@app.post("/vertraege/<int:vid>/loeschen")
def vertrag_loeschen(vid):
    v = row("SELECT * FROM vertrag WHERE id = ?", (vid,))
    _recht(v["immobilie_id"], v["wohnung_id"])
    exe("DELETE FROM vertrag WHERE id = ?", (vid,))
    flash(f"Vertrag „{v['art']}“ gelöscht.")
    return _zurueck(v)


@app.post("/vertraege/<int:vid>/dauerauftrag")
@admin_noetig
def vertrag_dauerauftrag(vid):
    """Dauerauftrag fürs angezeigte Jahr aus dem Vertrag anlegen – nur ein Vorschlag, gebucht wird bei den Buchungen."""
    v = row("SELECT * FROM vertrag WHERE id = ?", (vid,))
    j = jahr()
    rhythmus = ZAHLWEISEN.get(v["zahlweise"], ZAHLWEISEN["monatlich"])[2]
    if v["wohnung_id"] or not v["kostenart_id"] or not rhythmus or not v["betrag"]:
        raise ValueError("Ein Dauerauftrag geht nur für Verträge der Immobilie mit Kostenart, Betrag und "
                         "regelmäßiger Zahlweise.")
    von = max(parse_date(v["beginn"]) or date(j, 1, 1), date(j, 1, 1))
    ende = parse_date(v["gekuendigt_zum"]) or (parse_date(v["ablauf"]) if not v["verlaengerung"] else None)
    bis = min(ende, date(j, 12, 31)) if ende else date(j, 12, 31)
    if von.year != j or bis < von:
        raise ValueError(f"Der Vertrag läuft {j} nicht.")
    text = " · ".join(x for x in (v["art"], v["anbieter"]) if x)
    exe("INSERT INTO dauerauftrag (immobilie_id, jahr, text, art, kostenart_id, betrag, rhythmus, von, bis, notiz) "
        "VALUES (?, ?, ?, 'ausgabe', ?, ?, ?, ?, ?, ?)",
        (v["immobilie_id"], j, text, v["kostenart_id"], v["betrag"], rhythmus, von.isoformat(), bis.isoformat(),
         f"aus Vertrag {v['vertragsnummer']}".strip()))
    flash(f"Dauerauftrag „{text}“ für {j} angelegt – bitte bei den Buchungen prüfen und buchen.")
    return redirect(url_for("immobilie", iid=v["immobilie_id"], reiter="buchungen") + "#dauerauftraege")


# ---------- Erinnerung ----------

def faellige(heute=None):
    """Alle Termine im Vorlauf, für die noch keine Mail ging: [(art, objekt, text, merker)].
    art: kuendigung | preis | befristung | anpassung; merker = (Tabelle, Spalte, id, Wert) zum Abhaken."""
    heute = heute or date.today()
    erg = []
    for immo in rows("SELECT * FROM immobilie WHERE archiviert = 0"):
        for v in vertraege(immo["id"], heute=heute, nur_sichtbare=False):
            if not v["erinnern"]:
                continue
            name = " · ".join(x for x in (v["art"], v["anbieter"]) if x)
            ort = f"{immo['name']}{', ' + v['wohnung'] if v['wohnung'] else ''}"
            t = v["termin"]
            if t["status"] == "bald" and v["erinnert_fuer"] != t["kuendigen_bis"].isoformat():
                erg.append({"art": "kuendigung", "eigentuemer": v["eigentuemer_id"], "datum": t["kuendigen_bis"],
                            "text": f"{name} ({ort})\n  kündigen bis {t['kuendigen_bis']:%d.%m.%Y} zum {t['ende']:%d.%m.%Y}"
                                    f" (noch {t['tage']} Tage), {de_num(v['jahr'])} € pro Jahr"
                                    + (f", Vertragsnummer {v['vertragsnummer']}" if v["vertragsnummer"] else ""),
                            "merker": ("vertrag", "erinnert_fuer", v["id"], t["kuendigen_bis"].isoformat())})
            p = v["preis"]
            if p and p["bald"] and v["erinnert_preis"] != p["datum"].isoformat():
                erg.append({"art": "preis", "eigentuemer": v["eigentuemer_id"], "datum": p["datum"],
                            "text": f"{name} ({ort})\n  Preisgarantie bis {p['datum']:%d.%m.%Y} (noch {p['tage']} Tage)",
                            "merker": ("vertrag", "erinnert_preis", v["id"], p["datum"].isoformat())})
        for w in rows("SELECT * FROM wohnung WHERE immobilie_id = ?", (immo["id"],)):
            for mv in mietvertraege(w["id"], heute):
                mieter = ", ".join(person_name(p) for p in mv["personen"]) or "Mieter"
                ort = f"{immo['name']}, {w['bezeichnung']}"
                for art, s, spalte, was in (("befristung", mv["befristung"], "erinnert_befristung", "Befristung endet"),
                                            ("anpassung", mv["anpassung"], "erinnert_anpassung", "Mietanpassung möglich ab")):
                    if s and s["bald"] and mv[spalte] != s["datum"].isoformat():
                        erg.append({"art": art, "eigentuemer": w["eigentuemer_id"], "datum": s["datum"],
                                    "text": f"Mietvertrag {mieter} ({ort})\n  {was} {s['datum']:%d.%m.%Y} (noch {s['tage']} Tage)",
                                    "merker": ("mietverhaeltnis", spalte, mv["id"], s["datum"].isoformat())})
    return sorted(erg, key=lambda x: x["datum"])


UEBERSCHRIFTEN = {"kuendigung": "Hier läuft bald die Kündigungsfrist ab. Ohne Kündigung verlängern sich die Verträge:",
                  "preis": "Hier endet bald die Preisgarantie – ein guter Zeitpunkt, neue Konditionen auszuhandeln:",
                  "befristung": "Hier endet bald die Befristung eines Mietvertrags:",
                  "anpassung": "Hier ist bald eine Mietanpassung möglich (Staffel- oder Indexmiete):"}


def empfaenger(posten):
    """{E-Mail: [Posten]}: Benutzer mit Haken „Erinnerungen“ bekommen alles; Eigentümer (falls eingeschaltet) die
    Termine ihrer Mietobjekte."""
    an = {}
    for b in rows("SELECT * FROM benutzer WHERE erinnerung = 1 AND email <> ''"):
        an.setdefault(b["email"], []).extend(posten)
    if einstellung("erinnerung_eigentuemer", "0") == "1":
        for p in posten:
            b = one("SELECT * FROM benutzer WHERE id = ? AND email <> ''", (p["eigentuemer"],)) if p["eigentuemer"] else None
            if b and p not in an.get(b["email"], []):
                an.setdefault(b["email"], []).append(p)
    return an


def pruefen(heute=None):
    """Schickt je Empfänger eine Sammel-Mail mit allen neu fälligen Terminen; gibt die Anzahl der Termine zurück."""
    if einstellung("erinnerung_aktiv", "1") != "1" or not mail.konfiguriert():
        return 0
    posten = faellige(heute)
    an = empfaenger(posten)
    if not an:
        return 0
    url = os.environ.get("APP_URL", "")
    for adresse, liste in an.items():
        teile = [UEBERSCHRIFTEN[art] + "\n\n" + "\n\n".join("- " + p["text"] for p in liste if p["art"] == art)
                 for art in UEBERSCHRIFTEN if any(p["art"] == art for p in liste)]
        text = "Hallo,\n\n" + "\n\n\n".join(teile) + (f"\n\nImmobilienverwalter: {url}" if url else "") + \
            "\n\nDiese Erinnerung kommt einmal je Termin."
        betreff = f"Erinnerung: {len(liste)} Termin{'e' if len(liste) != 1 else ''} bei Verträgen"
        mail.senden(adresse, betreff, text)
    gemeldet = {id(p) for liste in an.values() for p in liste}
    for p in posten:
        if id(p) in gemeldet:
            tabelle, spalte, pid, wert = p["merker"]
            exe(f"UPDATE {tabelle} SET {spalte} = ? WHERE id = ?", (wert, pid))
    return len(gemeldet)


def _schleife():
    while True:
        try:
            with app.app_context():
                n = pruefen(date.today())
                if n:
                    log.warning("Erinnerung für %d Termine gesendet", n)
        except Exception:  # noqa: BLE001 – der Thread darf nicht sterben
            log.exception("Erinnerung fehlgeschlagen")
        time.sleep(6 * 3600)


def starten():
    """Hintergrund-Prüfung alle 6 Stunden (gunicorn läuft mit genau einem Worker). NK_ERINNERUNG=aus schaltet sie ab."""
    if os.environ.get("NK_ERINNERUNG", "an") != "aus":
        threading.Thread(target=_schleife, name="erinnerung", daemon=True).start()


@app.route("/einstellungen/admin/erinnerungen", methods=["GET", "POST"])
@admin_noetig
def erinnerungen_admin():
    if request.method == "POST":
        if request.form.get("aktion") == "jetzt":
            try:
                n = pruefen(date.today())
                flash(f"{n} Termin(e) gemeldet." if n else "Keine neuen Termine zu melden (oder kein Empfänger).")
            except Exception as e:  # noqa: BLE001
                flash(f"Versand fehlgeschlagen: {e}", "fehler")
            return redirect(url_for("erinnerungen_admin"))
        einstellung_setzen("erinnerung_aktiv", "1" if request.form.get("aktiv") else "0")
        einstellung_setzen("erinnerung_eigentuemer", "1" if request.form.get("eigentuemer") else "0")
        einstellung_setzen("erinnerung_vorlauf", str(max(1, min(365, int(parse_num(request.form.get("vorlauf"), 30))))))
        ids = {int(x) for x in request.form.getlist("empfaenger")}
        for b in rows("SELECT id FROM benutzer"):
            exe("UPDATE benutzer SET erinnerung = ? WHERE id = ?", (1 if b["id"] in ids else 0, b["id"]))
        flash("Einstellungen für Erinnerungen gespeichert.")
        return redirect(url_for("erinnerungen_admin"))
    return render_template("einstellungen/erinnerungen.html", bereich="admin_erinnerungen",
                           aktiv=einstellung("erinnerung_aktiv", "1") == "1",
                           eigentuemer=einstellung("erinnerung_eigentuemer", "0") == "1", vorlauf=vorlauf(),
                           benutzer=rows("SELECT * FROM benutzer WHERE rolle <> 'ohne_zugang' ORDER BY name, vorname"),
                           konfiguriert=mail.konfiguriert(), faellig=faellige())


app.jinja_env.globals.update(VERTRAG_STATUS=STATUS, ZAHLWEISEN=ZAHLWEISEN, VERLAENGERUNG=VERLAENGERUNG, FRIST=FRIST,
                             VERTRAGSARTEN=ARTEN, MIETARTEN=MIETARTEN)
