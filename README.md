<p align="center"><img src="design/logo-readme.png" alt="Immobilienverwalter" width="480"></p>

<p align="center">
  <a href="https://github.com/BitNike/immobilienverwalter/actions/workflows/tests.yml"><img src="https://github.com/BitNike/immobilienverwalter/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/Lizenz-AGPL--3.0-17325c" alt="Lizenz: AGPL-3.0"></a>
  <a href="https://github.com/BitNike/immobilienverwalter/releases/latest"><img src="https://img.shields.io/github/v/release/BitNike/immobilienverwalter?label=Version" alt="Version"></a>
</p>

# Immobilienverwalter

Web-App im Docker-Container für Vermieter: Immobilien, Mietobjekte, Mieter, Zähler, Belege und die jährliche Betriebskostenabrechnung (§ 556 BGB, § 2 BetrKV).

📖 **[Handbuch](docs/README.md)**: Anleitung zu allen Funktionen, mit einem durchgerechneten WEG-Beispiel.

## Installation

### Mit dem fertigen Image (empfohlen)

Kein Git und kein Bauen nötig – läuft auf PC/Server (amd64) sowie Raspberry Pi und Synology (arm64).
Die Datei [`docker-compose.yml`](docker-compose.yml) in einen eigenen Ordner herunterladen, dann:

```bash
docker compose up -d
```

Oder in **Portainer, Dockge, Unraid oder dem Synology Container Manager** einen neuen Stack anlegen und den Inhalt
der [`docker-compose.yml`](docker-compose.yml) einfügen. Mehr braucht es nicht, der Quellcode ist dafür nicht nötig.

Danach im Browser: `http://<IP-des-Rechners>:8080`. Der erste Zugang, der angelegt wird, ist Administrator.

**Update:** `docker compose pull && docker compose up -d` – die Daten liegen in den Volumes und bleiben erhalten.
Für eine feste Version statt `latest` z. B. `ghcr.io/bitnike/immobilienverwalter:0.26.1` eintragen.

E-Mail-Versand (Passwort vergessen, Einladungen, Erinnerungen) ist optional: Vorlage [`.env.example`](.env.example) als `.env`
neben die Compose-Datei legen und ausfüllen.

### Aus dem Quellcode (für Entwickler)

```bash
git clone https://github.com/BitNike/immobilienverwalter.git
cd immobilienverwalter
docker compose -f docker-compose.build.yml up -d --build
```

## Funktionen

Ausführlich im **[Handbuch](docs/README.md)**.

- **Immobilien und Mietobjekte** mit Wohnfläche, MEA, Eigentümer, mehreren Häusern je Immobilie und Archiv.
- **Umlageschlüssel je Immobilie** (MEA, Wohnfläche, Einheiten, Wasserverbrauch) mit Grundlage, z. B. aus der Teilungserklärung;
  cent-genaue Verteilung. Kostenarten nach § 2 BetrKV pflegt der Administrator.
- **Buchungen** statt Kostensummen: eine Zeile je Rechnung, mit Beleg, Barauslagen, Filter und Suche.
  **Daueraufträge** je Jahr (Jahressumme oder einzeln).
- **Mieter** mit Ein- und Auszug, Vorauszahlungen, Mietvertragsangaben; Kosten zeitanteilig nach Monaten,
  Leerstand und nicht umlagefähige Kosten trägt der Eigentümer.
- **WEG:** Eigentümer-Abrechnung gegen das Hausgeld, Hausgeld als Buchung, Eigentümer ohne Zugang,
  Kosten der Wohnung „über die WEG“ oder „vom Eigentümer direkt“ bezahlt (z. B. Müll, Grundsteuer),
  **Erhaltungsrücklage** als Kontoblatt mit Kontoständen.
- **Zähler** für Wasser, Strom, Gas und Wärme mit Ablesungen und Zählertausch; Wasser nach Verbrauch verteilen.
- **Verträge** mit Kündigungsterminen, Preisgarantie, Zählern und Unterlagen, Abgleich mit den Buchungen;
  **Erinnerungen per E-Mail**.
- **Prüfliste „Bitte prüfen“** vor dem Export: fehlende MEA, ungespeicherte Vorauszahlungen, doppelte Kosten,
  Kosten aus dem Vorjahr, die noch fehlen, und mehr.
- **Export als PDF:** Brief nach DIN 5008 für Fensterumschläge mit GiroCode, Belegliste und Belegen als Anlagen;
  Mieter- und Eigentümer-Abrechnung je Mietobjekt.
- **Dokumente:** Belege je Jahr und eine Ablage (Protokolle, Pläne, Verträge) mit zentraler Suche.
- **Benutzer:** Administrator, Vermieter + (darf Zahlen eintragen), Vermieter (nur lesen), Ohne Zugang;
  Zwei-Faktor-Anmeldung.

## Daten & Backup

| Volume | Inhalt |
|---|---|
| `immobilienverwalter_daten` → `/data` | SQLite-Datenbank, Profilfotos, Logo |
| `immobilienverwalter_dokumente` → `/dokumente` | Belege `<Immobilie>/<Jahr>/…` und Ablage `<Immobilie>/Ablage/…` |

```bash
docker run --rm -v immobilienverwalter_daten:/data -v immobilienverwalter_dokumente:/dokumente \
  -v "$PWD":/backup debian:bookworm-slim tar czf /backup/backup-$(date +%F).tgz /data /dokumente
```

Umzug einer bestehenden Installation mit anderen Volume-Namen: in der `docker-compose.yml` unter `volumes:` den alten
Namen eintragen und `external: true` ergänzen. Dann bindet Docker die vorhandenen Daten ein und legt nie ein leeres
Volume an. Bei einer Neuinstallation ist nichts zu tun, die Volumes entstehen beim ersten Start.

## Sicherheit

Gedacht für das Heimnetz. Bevor die App ins Internet geht, sind HTTPS (Reverse Proxy) und ein CSRF-Schutz für die Formulare nötig. Für Administratoren empfiehlt sich die Zwei-Faktor-Anmeldung (Profil → Sicherheit).

## Entwicklung

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python app/main.py     # http://localhost:8080, Daten unter ./data und ./dokumente
.venv/bin/pytest tests
```

> Arbeitshilfe, keine Rechtsberatung.

## Lizenz

Freie Software unter der [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0): kostenlos nutzen, verändern und
weitergeben. Wer eine veränderte Fassung anderen anbietet – auch übers Internet –, muss deren Quellcode ebenfalls unter
dieser Lizenz offenlegen.

**Keine Rechtsberatung, keine Gewähr.** Die Software ist ein Hilfsmittel zur Erstellung von Betriebskostenabrechnungen und
ersetzt keine Rechts- oder Steuerberatung. Für Richtigkeit und rechtliche Wirksamkeit der Abrechnungen ist allein der Nutzer
verantwortlich; bitte jede Abrechnung vor dem Versand prüfen. Haftung ausgeschlossen, soweit gesetzlich zulässig.

Entwickler: Sascha Benecke · [Unterstützen per PayPal](https://www.paypal.com/paypalme/saschabenecke)
