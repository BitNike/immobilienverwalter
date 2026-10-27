<p align="center"><img src="design/logo-readme.png" alt="Immobilienverwalter" width="480"></p>

<p align="center">
  <a href="https://github.com/BitNike/immobilienverwalter/actions/workflows/tests.yml"><img src="https://github.com/BitNike/immobilienverwalter/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/Lizenz-AGPL--3.0-17325c" alt="Lizenz: AGPL-3.0"></a>
  <a href="https://github.com/BitNike/immobilienverwalter/releases/latest"><img src="https://img.shields.io/github/v/release/BitNike/immobilienverwalter?label=Version" alt="Version"></a>
</p>

# Immobilienverwalter

Web-App im Docker-Container für Vermieter: Immobilien, Mietobjekte, Mieter, Zähler, Belege und die jährliche Betriebskostenabrechnung (§ 556 BGB, § 2 BetrKV).

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
Für eine feste Version statt `latest` z. B. `ghcr.io/bitnike/immobilienverwalter:0.10.1` eintragen.

E-Mail-Versand (Passwort vergessen, Einladungen) ist optional: Vorlage [`.env.example`](.env.example) als `.env`
neben die Compose-Datei legen und ausfüllen.

### Aus dem Quellcode (für Entwickler)

```bash
git clone https://github.com/BitNike/immobilienverwalter.git
cd immobilienverwalter
docker compose -f docker-compose.build.yml up -d --build
```

## Aufbau

- **Immobilie** (links): nur der Admin legt sie an, mit Anschrift, Absender, IBAN und Dokumenten.
- **Mietobjekt** (mittlere Spalte): Wohnung mit Wohnfläche, MEA, Zählern und Eigentümer. Vorgefertigte Wohnungen pflegst du unter Einstellungen → Administration → Mietobjekte.
- **Mietverhältnis**: eine oder mehrere Personen, Ein- und Auszug, Vorauszahlung. Jedes Mietverhältnis erhält eine fortlaufende Nummer und einen eigenen Ordner, z. B. `001 - Gerber`.
- **Reiter** unter dem Seitenkopf: Immobilie mit Übersicht, Buchungen, Rücklage, Zähler, Dokumente und Stammdaten; Mietobjekt mit Abrechnung, Mieter, Zähler, Dokumente und Stammdaten.
- **Jahr-Umschalter** (‹ 2025 ›) oben rechts, um rückwirkend zu arbeiten. Mit „Kostenarten aus Vorjahr übernehmen“ legst du ein neues Jahr schnell an.

### Kosten

| Wo erfasst | Verteilung |
|---|---|
| Immobilie, Belege und Buchungen | je Kostenart zusammengezählt, auf die Mietobjekte nach MEA, Wohnfläche, Einheiten oder Wasserverbrauch |
| Mietobjekt | zeitanteilig nach Monaten auf die Mieter |
| Mietobjekt, „für Mieter …“ | zu 100 % für diesen Mieter (z. B. Heizkostenabrechnung des Messdienstes) |

Gebäudekosten erfasst du als Buchungen, eine Zeile je Rechnung oder Kassenbon (Datum, Beschreibung, Kostenart, Betrag, Konto oder bar ausgelegt, optional mit Belegfoto). Einnahmen mindern die Kostenart. Bar Ausgelegtes bleibt als „noch nicht erstattet“ markiert, bis du die Erstattung einträgst.

**Daueraufträge:** wiederkehrende Zahlungen (z. B. Hausmeister, Hausgeld) je Jahr anlegen; die App bucht eine Jahressumme mit Rechenweg oder je Termin einzeln. Im neuen Jahr werden sie aus dem Vorjahr übernommen und geprüft.

**Hausgeld (WEG):** Überweisungen der Eigentümer als Buchungen erfassen – für eine Wohnung oder gleichmäßig für alle Wohnungen eines Eigentümers. Die Summe geht in die Eigentümer-Abrechnung. Buchungen lassen sich filtern und durchsuchen.

**Verträge:** je Immobilie oder Mietobjekt mit Laufzeit, Kündigungsfrist und Preisgarantie; die App berechnet den nächsten Kündigungstermin und erinnert per E-Mail (Einstellungen → Erinnerungen). Mietverträge: Kaltmiete, Befristung und Staffel-/Indexmiete am Mietverhältnis.

**Erhaltungsrücklage (WEG):** Buchungen mit dem Ziel „Erhaltungsrücklage“ werden nicht umgelegt; Einnahmen (z. B. PV-Anlage) fließen hinein, Ausgaben werden entnommen. Die Zuführung kommt aus einer Kostenart mit Haken „Rücklage“. Anfangsbestand, Zuführung, Einnahmen, Entnahmen und Endbestand stehen auf der Immobilie und in der Eigentümer-Abrechnung. Dazu Kontostände je Konto (z. B. Girokonto, Tagesgeld) zum Stichtag laut Kontoauszug, mit Abgleich gegen die Rücklage.

Auf Leerstand entfallende und nicht umlagefähige Kosten trägt der Eigentümer. Der Wasserverbrauch ergibt sich aus den Zählerständen. Bei einem Zählertausch bleibt der alte Zähler mit seinen Ständen erhalten.

### Export

Pro Mietobjekt gibt es eine **Mieter-Abrechnung** und eine **Eigentümer-Abrechnung** (z. B. für eine WEG). Der Export erzeugt ein PDF mit Deckblatt; wählbar sind die Erhaltungsrücklage, eine Belegliste nach Kostenart (Mieter sehen nur umlagefähige Kosten) und die hochgeladenen Belege als Anlagen. Vorher siehst du eine Vorschau.

### Benutzergruppen

| Gruppe | Rechte |
|---|---|
| Administrator | alles |
| Vermieter + | sieht die eigenen Mietobjekte und darf dort Mieter, Zählerstände, Kosten und Vorauszahlungen eintragen |
| Vermieter | sieht die eigenen Mietobjekte, nur lesend |

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

Gedacht für das Heimnetz. Bevor die App ins Internet geht, sind HTTPS (Reverse Proxy) und ein CSRF-Schutz für die Formulare nötig.

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
