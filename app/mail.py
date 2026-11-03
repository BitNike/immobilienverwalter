"""E-Mail-Versand. Zugangsdaten kommen aus der .env (siehe .env.example)."""
import os
import smtplib
import ssl
from email.message import EmailMessage


def konfiguration():
    return {
        "host": os.environ.get("SMTP_HOST", ""),
        "port": int(os.environ.get("SMTP_PORT") or 587),
        "benutzer": os.environ.get("SMTP_USER", ""),
        "passwort": os.environ.get("SMTP_PASSWORD", ""),
        "absender": os.environ.get("SMTP_FROM", ""),
        "sicherheit": os.environ.get("SMTP_SECURITY", "starttls").lower(),  # starttls | ssl | none
    }


def konfiguriert():
    k = konfiguration()
    return bool(k["host"] and k["absender"])


def logo_fuer_mail():
    """Logo wie oben links in der App (Einstellungen → Logo & Brief): eingebautes Standard-Logo, hochgeladenes Bild
    oder – bei „Text“ – keins. Ergebnis: (bytes, Untertyp, Breite in px) oder None."""
    import dateien
    from core import einstellung
    typ = einstellung("logo_typ", "standard")
    if typ == "standard":
        pfad = os.path.join(os.path.dirname(__file__), "static", "logo.png")
    elif typ == "bild" and einstellung("logo_datei"):
        pfad = os.path.join(dateien.BILD_DIR, einstellung("logo_datei"))
    else:
        return None
    if not os.path.exists(pfad):
        return None
    with open(pfad, "rb") as f:
        daten = f.read()
    untertyp = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".gif": "gif", ".webp": "webp"}.get(
        os.path.splitext(pfad)[1].lower(), "png")
    return daten, untertyp, 260 if typ == "standard" else 200


def nachricht(an, betreff, ueberschrift, absaetze, knopf=None, hinweis="", anrede=""):
    """Einfache Mail im Stil der Erinnerungsmail: Logo, Überschrift, Absätze, optional ein Knopf (Text, Link) und ein
    kleiner Hinweis im Fuß. Textfassung für Mailprogramme ohne HTML wird mitgeschickt."""
    from flask import render_template
    from core import einstellung
    logo = logo_fuer_mail()
    text = "\n\n".join(x for x in ([anrede + ","] if anrede else []) + list(absaetze) +
                        ([f"{knopf[0]}: {knopf[1]}"] if knopf else []) + ([hinweis] if hinweis else []))
    html = render_template("mail/nachricht.html", betreff=betreff, ueberschrift=ueberschrift, anrede=anrede,
                           absaetze=absaetze, knopf=knopf, hinweis=hinweis, logo=bool(logo),
                           logo_breite=logo[2] if logo else 0, logo_text=einstellung("logo_text", "Immobilienverwalter"),
                           url=os.environ.get("APP_URL", ""))
    senden(an, betreff, text + "\n", html=html, bilder={"logo": logo[:2]} if logo else {})


def senden(an, betreff, text, html=None, bilder=None):
    """Mail als reiner Text, auf Wunsch zusätzlich als HTML. bilder: {cid: (bytes, Untertyp)} werden eingebettet und
    im HTML über src="cid:<cid>" angesprochen (kein Nachladen aus dem Internet)."""
    k = konfiguration()
    if not konfiguriert():
        raise RuntimeError("SMTP ist nicht eingerichtet (.env).")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = k["absender"], an, betreff
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
        html_teil = msg.get_payload()[-1]
        for cid, (daten, untertyp) in (bilder or {}).items():
            html_teil.add_related(daten, maintype="image", subtype=untertyp, cid=f"<{cid}>", filename=f"{cid}.{untertyp}")
    ctx = ssl.create_default_context()
    if k["sicherheit"] == "ssl":
        server = smtplib.SMTP_SSL(k["host"], k["port"], context=ctx, timeout=20)
    else:
        server = smtplib.SMTP(k["host"], k["port"], timeout=20)
        if k["sicherheit"] == "starttls":
            server.starttls(context=ctx)
    with server:
        if k["benutzer"]:
            server.login(k["benutzer"], k["passwort"])
        server.send_message(msg)
