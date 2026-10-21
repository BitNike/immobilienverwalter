<p align="center"><img src="design/logo-readme.png" alt="Immobilienverwalter" width="480"></p>

# Immobilienverwalter

Web-App im Docker-Container für Vermieter: Immobilien, Mietobjekte, Mieter, Zähler, Belege und die jährliche Betriebskostenabrechnung (§ 556 BGB, § 2 BetrKV).

## Starten

```bash
cp .env.example .env      # SMTP und APP_URL eintragen (optional)
docker compose up -d --build
```

Danach im Browser: `http://<IP-des-Rechners>:8080`. Der erste Zugang, der angelegt wird, ist Administrator.

## Aufbau

- **Immobilie** (links): nur der Admin legt sie an, mit Anschrift, Absender, IBAN und Dokumenten.
- **Mietobjekt** (mittlere Spalte): Wohnung mit Wohnfläche, MEA, Zählern und Eigentümer. Vorgefertigte Wohnungen pflegst du unter Einstellungen → Administration → Mietobjekte.
- **Mietverhältnis**: eine oder mehrere Personen, Ein- und Auszug, Vorauszahlung. Jedes Mietverhältnis erhält eine fortlaufende Nummer und einen eigenen Ordner, z. B. `001 - Gerber`.
- **Jahr-Umschalter** (‹ 2025 ›) oben rechts, um rückwirkend zu arbeiten. Mit „Kostenarten aus Vorjahr übernehmen“ legst du ein neues Jahr schnell an.

### Kosten

| Wo erfasst | Verteilung |
|---|---|
| Immobilie (Gebäudekosten) | auf die Mietobjekte nach MEA, Wohnfläche, Einheiten oder Wasserverbrauch |
| Mietobjekt | zeitanteilig nach Monaten auf die Mieter |
| Mietobjekt, „für Mieter …“ | zu 100 % für diesen Mieter (z. B. Heizkostenabrechnung des Messdienstes) |

Auf Leerstand entfallende und nicht umlagefähige Kosten trägt der Eigentümer. Der Wasserverbrauch ergibt sich aus den Zählerständen. Bei einem Zählertausch bleibt der alte Zähler mit seinen Ständen erhalten.

### Export

Pro Mietobjekt gibt es eine **Mieter-Abrechnung** und eine **Eigentümer-Abrechnung** (z. B. für eine WEG). Der Export erzeugt ein PDF mit Deckblatt und den ausgewählten Belegen; vorher siehst du eine Vorschau.

### Benutzergruppen

| Gruppe | Rechte |
|---|---|
| Administrator | alles |
| Vermieter + | sieht die eigenen Mietobjekte und darf dort Mieter, Zählerstände, Kosten und Vorauszahlungen eintragen |
| Vermieter | sieht die eigenen Mietobjekte, nur lesend |

## Daten & Backup

| Volume | Inhalt |
|---|---|
| `nk-daten` → `/data` | SQLite-Datenbank, Profilfotos, Logo |
| `nk-dokumente` → `/dokumente` | Belege: `<Immobilie>/<Jahr>/Vermieter`, `<Immobilie>/<Jahr>/Mieter`, `<Immobilie>/<Jahr>/Mieter/<Nr - Name>` |

```bash
docker run --rm -v nebenkostenabrechnung_nk-daten:/data -v nebenkostenabrechnung_nk-dokumente:/dokumente \
  -v "$PWD":/backup debian:bookworm-slim tar czf /backup/backup-$(date +%F).tgz /data /dokumente
```

## Sicherheit

Gedacht für das Heimnetz. Bevor die App ins Internet geht, sind HTTPS (Reverse Proxy) und ein CSRF-Schutz für die Formulare nötig.

## Entwicklung

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python app/main.py     # http://localhost:8080, Daten unter ./data und ./dokumente
.venv/bin/pytest tests
```

> Arbeitshilfe, keine Rechtsberatung.
