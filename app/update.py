"""Hinweis auf neue Versionen: einmal am Tag die neueste Veröffentlichung auf GitHub abfragen (nur Version und Link,
es werden keine Daten aus der App übertragen). NK_UPDATE_CHECK=aus oder der Haken auf „Über“ schaltet das ab."""
import json
import logging
import os
import re
import threading
import time
import urllib.request

from flask import flash, redirect, request, url_for

from core import VERSION, admin_noetig, app, einstellung, einstellung_setzen

API = "https://api.github.com/repos/BitNike/immobilienverwalter/releases/latest"
ABSTAND = 24 * 60 * 60  # Sekunden zwischen zwei Abfragen
log = logging.getLogger(__name__)
_laeuft = threading.Lock()


def versionsteile(text):
    """„v0.28.1“ → (0, 28, 1); unlesbar → None."""
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (text or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def aktiv():
    return os.environ.get("NK_UPDATE_CHECK", "an") != "aus" and einstellung("update_pruefen", "1") == "1"


def abfragen():
    """Neueste Veröffentlichung holen und merken. Fehler (offline, GitHub nicht erreichbar) werden nur protokolliert."""
    try:
        anfrage = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json",
                                                       "User-Agent": f"Immobilienverwalter/{VERSION}"})
        with urllib.request.urlopen(anfrage, timeout=10) as antwort:
            daten = json.load(antwort)
        if versionsteile(daten.get("tag_name")):
            einstellung_setzen("update_neueste", daten["tag_name"].lstrip("v"))
            einstellung_setzen("update_url", daten.get("html_url") or "")
    except Exception as e:  # noqa: BLE001 – ein fehlgeschlagener Blick auf GitHub darf nie stören
        log.info("Update-Prüfung fehlgeschlagen: %s", e)
    einstellung_setzen("update_geprueft", str(int(time.time())))


def _im_hintergrund():
    if not _laeuft.acquire(blocking=False):
        return

    def lauf():
        try:
            with app.app_context():
                abfragen()
        finally:
            _laeuft.release()
    threading.Thread(target=lauf, name="update", daemon=True).start()


def neue_version():
    """{version, url}, wenn eine neuere Version als die laufende bekannt ist; stößt bei Bedarf die Tagesabfrage an."""
    if not aktiv():
        return None
    if time.time() - int(einstellung("update_geprueft", "0") or 0) > ABSTAND:
        _im_hintergrund()
    neueste = einstellung("update_neueste")
    if versionsteile(neueste) and versionsteile(VERSION) and versionsteile(neueste) > versionsteile(VERSION):
        return {"version": neueste, "url": einstellung("update_url")}
    return None


@app.post("/einstellungen/update")
@admin_noetig
def update_einstellen():
    if request.form.get("aktion") == "jetzt":
        abfragen()
        neu = neue_version()
        flash(f"Neue Version {neu['version']} verfügbar." if neu else
              f"Du nutzt die neueste Version ({VERSION})." if einstellung("update_neueste") else
              "GitHub war nicht erreichbar, bitte später noch einmal versuchen.")
    else:
        einstellung_setzen("update_pruefen", "1" if request.form.get("pruefen") else "0")
        flash("Gespeichert.")
    return redirect(url_for("info"))
