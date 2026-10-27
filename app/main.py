"""Einstiegspunkt (gunicorn main:app). Die Module registrieren ihre Routen beim Import."""
import auth  # noqa: F401
import dokumente  # noqa: F401
import einstellungen  # noqa: F401
import export  # noqa: F401
import immobilien  # noqa: F401
import vertraege
import zweifaktor  # noqa: F401
from core import app

vertraege.starten()  # Erinnerungen per Mail im Hintergrund

if __name__ == "__main__":
    app.run(debug=True, port=8080)
