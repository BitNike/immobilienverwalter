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
