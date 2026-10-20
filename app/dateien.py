"""Ablage von Dokumenten, Profilfotos und Logo."""
import io
import os
import re
import unicodedata

from PIL import Image, ImageOps

import db

DOK_DIR = os.path.abspath(os.environ.get("NK_DOKUMENTE", os.path.join(os.path.dirname(__file__), "..", "dokumente")))
BILD_DIR = os.path.join(db.DATA_DIR, "bilder")

DOKUMENT_TYPEN = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
FOTO_MAX_BYTES = 3 * 1024 * 1024
FOTO_PIXEL = 400
LOGO_MAX_BYTES = 2 * 1024 * 1024
LOGO_MAX_HOEHE = 160


def ordnername(text):
    """Dateisystem-tauglicher Name, Umlaute bleiben lesbar."""
    text = unicodedata.normalize("NFC", text or "").strip()
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", text)
    return re.sub(r"\s+", " ", text)[:80].strip(" .") or "Unbenannt"


def eindeutig(verzeichnis, dateiname):
    stamm, endung = os.path.splitext(dateiname)
    kandidat, n = dateiname, 2
    while os.path.exists(os.path.join(verzeichnis, kandidat)):
        kandidat = f"{stamm} ({n}){endung}"
        n += 1
    return kandidat


def dokument_speichern(datei, relativer_ordner):
    """Speichert ein hochgeladenes Dokument und gibt (relativer Pfad, MIME, Größe) zurück."""
    endung = os.path.splitext(datei.filename or "")[1].lower()
    if endung not in DOKUMENT_TYPEN:
        raise ValueError("Erlaubt sind PDF, JPG und PNG.")
    ziel = os.path.join(DOK_DIR, relativer_ordner)
    os.makedirs(ziel, exist_ok=True)
    name = eindeutig(ziel, ordnername(os.path.splitext(datei.filename)[0]) + endung)
    pfad = os.path.join(ziel, name)
    datei.save(pfad)
    return os.path.relpath(pfad, DOK_DIR), DOKUMENT_TYPEN[endung], os.path.getsize(pfad)


def dokument_pfad(relativ):
    pfad = os.path.abspath(os.path.join(DOK_DIR, relativ))
    if not pfad.startswith(DOK_DIR + os.sep):
        raise ValueError("Ungültiger Pfad")
    return pfad


def _bild_lesen(datei, max_bytes):
    daten = datei.read(max_bytes + 1)
    if len(daten) > max_bytes:
        raise ValueError(f"Bild ist größer als {max_bytes // 1024 // 1024} MB.")
    try:
        img = Image.open(io.BytesIO(daten))
        img.load()
    except Exception as e:
        raise ValueError("Bild konnte nicht gelesen werden.") from e
    format_ = img.format  # exif_transpose liefert eine Kopie ohne Formatangabe
    return ImageOps.exif_transpose(img), format_


def foto_pfad(uid):
    return os.path.join(BILD_DIR, f"profil_{uid}.jpg")


def foto_speichern(datei, uid):
    """Quadratisch zuschneiden, auf FOTO_PIXEL verkleinern, als JPEG speichern."""
    img = _bild_lesen(datei, FOTO_MAX_BYTES)[0].convert("RGB")
    w, h = img.size
    s = min(w, h)
    img = img.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
    img = img.resize((FOTO_PIXEL, FOTO_PIXEL), Image.LANCZOS)
    os.makedirs(BILD_DIR, exist_ok=True)
    img.save(foto_pfad(uid), "JPEG", quality=85, optimize=True)


def logo_speichern(datei):
    """PNG (mit Transparenz) oder JPG; wird auf LOGO_MAX_HOEHE Pixel Höhe begrenzt. Gibt Dateinamen zurück."""
    img, format_ = _bild_lesen(datei, LOGO_MAX_BYTES)
    if format_ not in ("PNG", "JPEG"):
        raise ValueError("Logo bitte als PNG oder JPG hochladen.")
    if img.height > LOGO_MAX_HOEHE:
        if img.mode == "P":
            img = img.convert("RGBA")
        img = img.resize((round(img.width * LOGO_MAX_HOEHE / img.height), LOGO_MAX_HOEHE), Image.LANCZOS)
    os.makedirs(BILD_DIR, exist_ok=True)
    for alt in ("logo.png", "logo.jpg"):
        if os.path.exists(os.path.join(BILD_DIR, alt)):
            os.remove(os.path.join(BILD_DIR, alt))
    if format_ == "PNG":
        name = "logo.png"
        img.save(os.path.join(BILD_DIR, name), "PNG", optimize=True)
    else:
        name = "logo.jpg"
        img.convert("RGB").save(os.path.join(BILD_DIR, name), "JPEG", quality=90)
    return name
