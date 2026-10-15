# Zu Vorum beitragen

Danke für dein Interesse an Vorum. Fehlerberichte, Verbesserungen der Dokumentation,
Übersetzungen und Code-Beiträge sind willkommen. Issues und Pull Requests können
auf Deutsch oder Englisch verfasst werden.

## Fehler und Ideen

Prüfe vor einem neuen Issue, ob das Thema bereits gemeldet wurde. Beschreibe bei
Fehlern die verwendete Version bzw. den Commit, die Umgebung, die Schritte zur
Reproduktion und das erwartete sowie tatsächliche Ergebnis. Screenshots und
gekürzte Logs helfen, sofern sie keine persönlichen Daten oder Geheimnisse enthalten.

Größere Funktionsänderungen am besten zuerst in einem Issue besprechen. Kleine
Korrekturen können direkt als Pull Request eingereicht werden.
Sicherheitslücken bitte über den vertraulichen Meldeweg in
[SECURITY.md](SECURITY.md) melden.

## Entwicklungsumgebung

Erstelle einen Fork, klone ihn und lege einen Branch für deine Änderung an.
Im Projektverzeichnis mit Python 3.9 oder neuer:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install pytest
python -m flask --app vorum run --port 8000
```

Unter Windows aktivierst du die Umgebung in PowerShell mit
`.venv\Scripts\Activate.ps1`. Für einen lokalen Test mit Docker kannst du
stattdessen `docker compose up --build -d` verwenden. Die Ersteinrichtung und der
separate Mail-Worker sind in der [README](README.md) beschrieben.

Verwende eine eigene Entwicklungsinstallation mit künstlichen Benutzerdaten und
keine Produktionsdatenbank. Ein lokal konfigurierter SMTP-Zugang kann echte
E-Mails versenden; die automatisierten Tests verwenden einen Test-Mailausgang.

## Orientierung im Code

| Pfad | Inhalt |
| --- | --- |
| `vorum/__init__.py` | App-Factory, Forenfunktionen, Anmeldung und Verwaltung |
| `vorum/schema.sql` | SQLite-Schema; ergänzende Migrationen liegen in der App-Factory |
| `vorum/notifications.py` | Abos, Versandwarteschlange und Worker |
| `vorum/mail.py` | Gemeinsamer SMTP-Versand |
| `vorum/api.py` | Externe Benutzer und einmalige Login-Links |
| `vorum/templates/` und `vorum/static/` | Jinja-Templates, CSS und JavaScript |
| `vorum/translations.py` | Deutsche und englische Oberflächentexte |
| `tests/` | Funktionstests und optionaler Browser-Smoke-Test |
| `docs/` | API- und Betriebsdokumentation |

## Änderungen vorbereiten

- Halte Änderungen überschaubar und folge dem Stil des betroffenen Codes.
- Berücksichtige Deutsch und Englisch sowie mobile Ansicht und Hell-/Dunkelmodus
  bei Änderungen an der Oberfläche.
- Prüfe bei Zugriffen auf Daten stets Forenzuordnung, Rollen und globale Konten.
  Änderungen an Schreibzugriffen müssen CSRF-Schutz bzw. API-Authentifizierung
  berücksichtigen.
- Verwende parametrisierte SQL-Abfragen und behalte die serverseitige
  HTML-Bereinigung bei.
- Plane Schemaänderungen auch für bestehende Installationen. Daten dürfen beim
  Update nicht unbeabsichtigt verloren gehen; dokumentiere nötige Betriebsschritte.
- Ergänze bei Fehlerkorrekturen oder neuem Verhalten passende Tests und passe die
  Dokumentation an. Für reine Text- oder Formatänderungen sind keine neuen Tests nötig.
- Lade keine Datenbanken, Uploads, Zugangsdaten, privaten Schlüssel oder lokalen
  Backups hoch. Prüfe vor dem Commit die vorgemerkten Dateien und `git diff --cached`.
  Feste Zugangsdaten in vorhandenen Test-Fixtures sind ausschließlich Testwerte.

## Prüfen

Die Funktionstests laufen mit temporären Datenbanken:

```sh
python -m pytest -q
```

Für Änderungen an Oberfläche oder Browser-Verhalten gibt es zusätzlich einen
optionalen Smoke-Test:

```sh
python -m pip install playwright
python -m playwright install chromium
python tests/browser_smoke.py
```

Er verwendet ebenfalls eine temporäre Datenbank und einen Test-Mailausgang.
Screenshots werden unter `/tmp/vorum-preview/` abgelegt; bitte vor einer
Weitergabe trotzdem auf unbeabsichtigte Inhalte prüfen.

Der CI-Workflow prüft Python 3.9 und 3.12 sowie einen Docker-Start mit Webserver
und Worker. Den Container-Test kannst du bei laufendem Docker lokal ausführen:

```sh
docker build -t vorum:ci .
VORUM_IMAGE=vorum:ci bash tests/container_smoke.sh
```

Er erzeugt ein separates Compose-Projekt samt Testvolume, prüft Erreichbarkeit,
Dateirechte und gemeinsam genutzte persistente Daten und entfernt die Testressourcen
anschließend wieder. Ein echter SMTP-Versand gehört nicht zu diesem Starttest.
Die CI-Startprüfung läuft auf AMD64; beim Release werden zusätzlich ARM64-Images
gebaut. Ein ARM64-Laufzeittest ist damit noch nicht abgedeckt.

Der [Release-Ablauf](docs/releases.md) beschreibt die Image-Veröffentlichung.

## Pull Request einreichen

Beschreibe das Problem, das Verhalten nach deiner Änderung und die tatsächlich
ausgeführten Prüfungen. Verlinke das zugehörige Issue, falls vorhanden. Bei
sichtbaren Änderungen helfen Screenshots mit Beispieldaten. Weise auf
Datenbankänderungen, neue Konfiguration oder Einschränkungen hin.

Mit einem Beitrag erklärst du dich damit einverstanden, dass deine eigenen
Änderungen unter der [MIT-Lizenz](LICENSE) des Projekts veröffentlicht werden.
Übernimm fremden Code und Assets nur, wenn deren Lizenz dies erlaubt, und erhalte
erforderliche Copyright- und Lizenzhinweise. Abhängigkeiten behalten ihre eigenen
Lizenzen.
