# Vorum

**Deine Community. Deine Foren. Auf deinem Server.**

Vorum ist eine selbst gehostete Open-Source-Forensoftware für Communities,
Vereine und Projekte, die einen eigenen Ort für Austausch schaffen möchten.
Diskussionen bleiben als Themen und Antworten auffindbar, Mitglieder behalten
neue Beiträge im Blick und du bestimmst, wo die Daten liegen.

Mit einer Installation betreibst du mehrere Foren unter eigenen Domains – mit
eigenem Auftritt, eigener Verwaltung und lokalen oder gemeinsamen Konten.
Deutsch und Englisch, eine responsive Oberfläche und Docker-Unterstützung sind
von Anfang an dabei.

**MIT-lizenziert · Flask & SQLite · Deutsch / Englisch · Docker Compose**

## Was Vorum bietet

- **Raum für gute Gespräche:** Themenbereiche, formatierte Beiträge, Anhänge und
  direkte Links zu Beiträgen. Ein Bearbeitungsverlauf macht Änderungen nachvollziehbar.
- **Mehrere Communities, eine Installation:** Foren werden über ihre Hostnamen
  zugeordnet. Jedes Forum hat eigene Einstellungen, Inhalte und Administratoren;
  globale Konten können in allen Foren verwendet werden.
- **Ein Auftritt, der zu dir passt:** Eigenes Logo samt Favicon, sechs Farbschemata
  und Startseitentexte auf Deutsch und Englisch. Hell- und Dunkeldarstellung lassen
  sich automatisch oder manuell wählen.
- **Auf dem Laufenden bleiben:** Persistenter Lesestatus und Abos für einzelne
  Themen oder ganze Foren. E-Mails kommen direkt oder als tägliche bzw.
  wöchentliche Zusammenfassung.
- **Verwaltung im Browser:** Vier Rollen – Super-Admin, Admin, Moderator und User –
  sowie Benutzerverwaltung, E-Mail-Bestätigung und Moderation.
- **Anbindung an deine Anwendung:** Eine JSON-API überträgt Benutzer und erstellt
  kurzlebige, einmalig verwendbare Login-Links. Lokale Registrierung und Anmeldung
  lassen sich deaktivieren oder auf eine externe Anwendung umleiten.
- **Überschaubarer Betrieb:** Python, Flask und SQLite; kein separater
  Datenbankserver nötig. Docker Compose startet Webserver und Mail-Worker gemeinsam.

Vorum wird aktiv weiterentwickelt. Prüfe vor einem öffentlichen Einsatz die
[Betriebshinweise](docs/operations.md), richte Backups ein und teste deinen
Anwendungsfall. Die Auswahl eines Forums über den Hostnamen ersetzt keine
Zugriffssperre: Forenübersicht und Beiträge sind öffentlich lesbar; Downloads von
Anhängen benötigen ein angemeldetes, bestätigtes Konto.

## In wenigen Minuten ausprobieren

Du brauchst Docker mit Docker Compose, eine lokale Kopie dieses Projekts und für
spätere Bestätigungsmails bzw. Benachrichtigungen einen SMTP-Zugang.

Im Projektverzeichnis:

```sh
docker compose up --build -d
```

Öffne [localhost:8000](http://localhost:8000) und richte dein erstes Forum ein:

1. **Erstes Konto registrieren.** Es wird automatisch zum globalen Super-Admin;
   nur dieses erste Konto benötigt keine E-Mail-Bestätigung.
2. **Forum anlegen.** Im Super-Backend einen Namen und den Hostnamen `localhost`
   eintragen. Hostnamen werden ohne Protokoll und Port angegeben, ein Eintrag pro
   Zeile. Mehrere Einträge können dasselbe Forum aufrufen.
3. **E-Mail-Versand einrichten.** Im Forum unter **Backend → Einstellungen** SMTP
   und Absender konfigurieren, bevor sich weitere Mitglieder registrieren.
4. **Dein Forum gestalten.** Unter **Backend → Aussehen** Logo, Farben und
   Startseitentexte anpassen, Themenbereiche anlegen und das erste Thema eröffnen.

> **Ersteinrichtung schützen:** Das erste registrierte Konto erhält volle
> Verwaltungsrechte für die gesamte Installation. Führe die Einrichtung lokal
> oder hinter einer Zugriffsbeschränkung durch, bevor du Vorum öffentlich freigibst.

Die Compose-Datei baut das Image aus dem Quellcode. Ein bereits veröffentlichtes
Container-Image wird für diesen Schnellstart nicht vorausgesetzt.

## Mehrere Foren betreiben

Als Super-Admin legst du weitere Foren mit eigenen Hostnamen an, etwa
`forum.example.org` und `community.example.org`. DNS und Reverse Proxy müssen
diese Domains an dieselbe Vorum-Installation weiterleiten. Der ursprüngliche
Host-Header muss dabei erhalten bleiben.

Konten können auf ein Forum beschränkt sein oder global gelten. Die Anmeldung
ist dennoch an den jeweiligen Browser-Hostnamen gebunden; dieselben globalen
Zugangsdaten lassen sich auf den verschiedenen Hosts verwenden. Für einen
zweiten lokalen Test kann ein weiteres Forum den Hostnamen `127.0.0.1` bekommen.

## Starten, stoppen und aktualisieren

```sh
docker compose ps                 # Status anzeigen
docker compose logs -f            # Logs verfolgen; Strg+C beendet die Anzeige
docker compose stop               # Beide Dienste stoppen, Daten bleiben erhalten
docker compose start              # Bestehende Container wieder starten
```

Alternativ steht unter macOS/Linux `./server.sh` mit den Befehlen `start`, `stop`,
`restart`, `status` und `logs` zur Verfügung. `start` und `restart` bauen das Image
bei Bedarf aus dem aktuellen Quellcode.

Nach einer Aktualisierung der Projektdateien:

```sh
# Zuerst Daten sichern, siehe Betriebshinweise.
docker compose up --build -d
```

Das benannte Volume `vorum-data` enthält Datenbank, Uploads und Sitzungsschlüssel.
Es bleibt beim normalen Stoppen erhalten. `docker compose down -v` entfernt das
Volume und damit die gespeicherten Daten.

### Konfiguration

| Variable        | Bedeutung                                                                                                                                                          |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `COOKIE_SECURE` | `1` für sicheren Cookie-Versand über HTTPS; lokal über HTTP ist der Standard `0`. Die Compose-Datei übernimmt den Wert aus der Umgebung oder einer lokalen `.env`. |
| `VORUM_DATA`    | Datenverzeichnis, lokal standardmäßig `data/`, im Image `/app/data`. Webserver und Worker müssen auf denselben Datenbestand zugreifen.                             |
| `SECRET_KEY`    | Optionaler Sitzungsschlüssel. Ohne Vorgabe erzeugt Vorum einen persistenten Schlüssel im Datenverzeichnis.                                                         |

`VORUM_DATA` und `SECRET_KEY` werden von der Anwendung gelesen. Wenn du sie im
Docker-Betrieb überschreiben möchtest, musst du sie bei **beiden Diensten** unter
`environment` eintragen und gegebenenfalls das Volume-Ziel anpassen. Eine `.env`
allein übergibt diese beiden Variablen mit der bestehenden Compose-Datei nicht an
die Container.

Für öffentlichen Betrieb brauchst du HTTPS, `COOKIE_SECURE=1` und eine passende
Proxy-Konfiguration. Beachte besonders das Schema automatisch erzeugter Links
bei TLS-Terminierung. Sicherung, Wiederherstellung und Updates beschreibt die
[Betriebsanleitung](docs/operations.md).

## Mit einer bestehenden Anwendung verbinden

Unter **Backend → API** erzeugst du einen API-Schlüssel für das jeweilige Forum.
Dein Server kann damit externe Konten anlegen bzw. aktualisieren und einen
Login-Link für den bereits bei dir authentifizierten Benutzer anfordern.

Login-Links gelten fünf Minuten und können einmal verwendet werden. API-Schlüssel
bleiben auf deinem Server. Die [API-Anleitung](docs/api.md) erklärt Einrichtung,
Profilvorschläge, Beispielanfragen und Fehlercodes.

## Lokal entwickeln

Python **3.9 oder neuer**; das Docker-Image verwendet Python 3.12:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m flask --app vorum run --port 8000
```

Unter Windows aktivierst du die Umgebung mit `.venv\Scripts\Activate.ps1` in
PowerShell. Die Ersteinrichtung entspricht dem Docker-Schnellstart.
Der Flask-Entwicklungsserver ist für die lokale Entwicklung gedacht.

Für ausstehende Benachrichtigungen und Zusammenfassungen in einem zweiten
Terminal mit derselben virtuellen Umgebung und demselben Datenverzeichnis:

```sh
python -m flask --app vorum notification-worker
```

Tests ausführen:

```sh
python -m pip install pytest
python -m pytest -q
```

Die Tests verwenden temporäre Datenbanken und einen Test-Mailausgang.
Hinweise zum optionalen Browser-Test und zu Beiträgen findest du in
[CONTRIBUTING.md](CONTRIBUTING.md).

## Mitmachen und Sicherheit

Fehler gefunden, eine Übersetzung verbessert oder eine Idee für das nächste
Feature? Beiträge sind willkommen. [CONTRIBUTING.md](CONTRIBUTING.md) beschreibt,
wie du Fehler meldest und Änderungen vorbereitest.

Sicherheitslücken bitte vertraulich melden. Den Meldeweg und Hinweise für
Betreiber findest du in [SECURITY.md](SECURITY.md).

## Lizenz

Vorum steht unter der [MIT-Lizenz](LICENSE). Du darfst es auch kommerziell nutzen,
verändern und weitergeben; Copyright- und Lizenzhinweis müssen erhalten bleiben.
Abhängigkeiten unterliegen ihren jeweiligen eigenen Lizenzen.
