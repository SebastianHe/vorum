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
Zugriffssperre: Standardmäßig sind Forenübersicht und Beiträge öffentlich lesbar.
Unter **Backend → Einstellungen → Zugriff** lassen sich die Suchmaschinenindizierung,
der Gastzugriff auf das Forum und das Öffnen einzelner Themen durch Gäste steuern.
Alle drei Optionen sind standardmäßig aktiviert. Bei deaktiviertem Themenzugriff
bleibt die Themenliste sichtbar; einzelne Themen führen Gäste zum Login.
Die deaktivierte Indizierung setzt den HTTP-Header `X-Robots-Tag: noindex, nofollow`.
Die Datei `/robots.txt` erlaubt oder untersagt das Crawlen entsprechend dieser
Einstellung und bleibt auch bei deaktiviertem Gastzugriff öffentlich erreichbar.
Downloads von Anhängen benötigen ein angemeldetes, bestätigtes Konto.

## Installation mit Docker (empfohlen)

Für den Betrieb empfehlen wir das fertige Docker-Image aus der GitHub Container
Registry: `ghcr.io/sebastianhe/vorum`. Du brauchst Docker mit Docker Compose und
für Bestätigungsmails bzw. Benachrichtigungen einen SMTP-Zugang.

Ein Klonen des Quellcodes und ein eigener Image-Build sind nicht erforderlich.
Die Compose-Datei aus den Release-Assets verwendet die feste Version des jeweiligen
Releases. Sie steht nach dem erfolgreichen Abschluss des Release-Workflows bereit.

1. Öffne die [Releases](https://github.com/SebastianHe/vorum/releases) und wähle
   eine reguläre Version aus.
2. Lade unter **Assets** die Datei `compose.release.yaml` in ein eigenes
   Verzeichnis herunter, beispielsweise `vorum`.
3. Öffne ein Terminal in diesem Verzeichnis und starte Vorum:

```sh
docker compose -f compose.release.yaml pull
docker compose -f compose.release.yaml up -d
```

Die Images liegen unter `ghcr.io/sebastianhe/vorum` und unterstützen Linux auf
AMD64 und ARM64. Webserver und Benachrichtigungs-Worker werden gemeinsam gestartet.
Standardmäßig ist Port 8000 nur am lokalen Rechner (`127.0.0.1`) erreichbar.
Für Zugriff von einem anderen Rechner oder von einem Proxy-Container muss die
Port-/Netzwerkkonfiguration angepasst werden; Details stehen weiter unten.

### Erstes Forum einrichten

Öffne [localhost:8000](http://localhost:8000) und richte dein erstes Forum ein:

1. **Erstes Konto registrieren.** Es wird automatisch zum globalen Super-Admin;
   nur dieses erste Konto benötigt keine E-Mail-Bestätigung.
2. **Forum anlegen.** Im Super-Backend einen Namen und den Hostnamen `localhost`
   eintragen. Hostnamen werden ohne Protokoll und Port angegeben, ein Eintrag pro
   Zeile. Mehrere Einträge können dasselbe Forum aufrufen.
3. **E-Mail-Versand einrichten.** Im Forum unter **Backend → Einstellungen → Mail** SMTP
   und Absender konfigurieren, bevor sich weitere Mitglieder registrieren. Dort lassen
   sich auch die Versandzeiten für Zusammenfassungen einstellen und eine Testmail
   mit der gespeicherten Konfiguration senden. Als Empfänger ist die eigene
   E-Mail-Adresse vorausgefüllt und kann geändert werden.
4. **Dein Forum gestalten.** Unter **Backend → Aussehen** Logo, Farben und
   Startseitentexte anpassen, Themenbereiche anlegen und das erste Thema eröffnen.

> **Ersteinrichtung schützen:** Das erste registrierte Konto erhält volle
> Verwaltungsrechte für die gesamte Installation. Führe die Einrichtung lokal
> oder hinter einer Zugriffsbeschränkung durch, bevor du Vorum öffentlich freigibst.

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

Die folgenden Befehle gelten für die empfohlene Installation mit der
Release-Compose-Datei. Führe sie im Installationsverzeichnis aus.

```sh
docker compose -f compose.release.yaml ps       # Status anzeigen
docker compose -f compose.release.yaml logs -f  # Logs verfolgen; Strg+C beendet die Anzeige
docker compose -f compose.release.yaml stop     # Beide Dienste stoppen, Daten bleiben erhalten
docker compose -f compose.release.yaml start    # Bestehende Container wieder starten
```

**Auf eine neue feste Version aktualisieren:** Zuerst beide Dienste stoppen und das gesamte
Datenvolume sichern (siehe [Betriebsanleitung](docs/operations.md)). Anschließend
die `compose.release.yaml` der neuen Version aus den Release-Assets laden und
im **gleichen Verzeichnis** ersetzen. Dann:

```sh
docker compose -f compose.release.yaml pull
docker compose -f compose.release.yaml up -d
```

Falls du mit `VORUM_IMAGE` eine Version überschreibst, passe diese ebenfalls an.
Das Projektverzeichnis beibehalten, damit Compose dasselbe benannte Volume nutzt.
Eine ältere Programmversion kann nach Datenbankänderungen ein passendes Backup
erfordern.

Das benannte Volume `vorum-data` enthält Datenbank, Uploads und Sitzungsschlüssel.
Es bleibt beim normalen Stoppen erhalten.
`docker compose -f compose.release.yaml down -v` entfernt das Volume und damit
die gespeicherten Daten.

### Feste Versionen und `latest`

Für nachvollziehbare Updates empfehlen wir eine feste Version, wie sie die
Compose-Datei aus den Release-Assets bereits verwendet. Über `VORUM_IMAGE` in
einer lokalen `.env` kannst du den gewünschten Image-Tag für beide Dienste wählen:

| Beispiel                           | Verhalten                                                                       |
| ---------------------------------- | ------------------------------------------------------------------------------- |
| `ghcr.io/sebastianhe/vorum:0.1.0`  | Konkrete Version; ein Wechsel auf eine neue Version erfolgt ausdrücklich.       |
| `ghcr.io/sebastianhe/vorum:0.1`    | Wird bei regulären Veröffentlichungen innerhalb der Reihe `0.1.x` neu gesetzt.  |
| `ghcr.io/sebastianhe/vorum:latest` | Wird bei jedem erfolgreichen Image-Upload eines regulären Releases neu gesetzt. |

`latest` folgt der Reihenfolge erfolgreicher Uploads, ohne Versionsnummern zu
vergleichen. Wird nach `v0.2.0` noch `v0.1.1` regulär veröffentlicht, zeigt
`latest` anschließend auf `0.1.1`. Pre-releases wie `v0.3.0-rc.1`, normale Commits
und CI-Builds verändern `latest` nicht. Die GitHub-Markierung „Latest release“
steuert den Docker-Tag ebenfalls nicht.

Wenn du bewusst `latest` verwenden möchtest, trage in `.env` ein:

```dotenv
VORUM_IMAGE=ghcr.io/sebastianhe/vorum:latest
```

Laufende Container aktualisieren sich dadurch nicht automatisch. Sichere vor
einem Update die Daten wie oben beschrieben und führe dann aus:

```sh
docker compose -f compose.release.yaml pull
docker compose -f compose.release.yaml up -d
```

Bei einer festen Version lädt `pull` allein keine neuere Versionsnummer.

### Konfiguration

| Variable        | Bedeutung                                                                                                                                                          |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `COOKIE_SECURE` | `1` für sicheren Cookie-Versand über HTTPS; lokal über HTTP ist der Standard `0`. Die Compose-Datei übernimmt den Wert aus der Umgebung oder einer lokalen `.env`. |
| `VORUM_DATA`    | Datenverzeichnis, lokal standardmäßig `data/`, im Image `/app/data`. Webserver und Worker müssen auf denselben Datenbestand zugreifen.                             |
| `SECRET_KEY`    | Optionaler Sitzungsschlüssel. Ohne Vorgabe erzeugt Vorum einen persistenten Schlüssel im Datenverzeichnis.                                                         |

Die Release-Compose-Datei unterstützt zusätzlich eine lokale `.env`, zum Beispiel:

```dotenv
VORUM_IMAGE=ghcr.io/sebastianhe/vorum:0.1.0
VORUM_BIND=127.0.0.1
VORUM_PORT=8000
COOKIE_SECURE=0
```

Die Versionsnummer muss bereits veröffentlicht sein. `VORUM_IMAGE` überschreibt
das Image für **beide Dienste**. Ohne diese Variable verwendet die Datei aus dem
Release dessen feste Version; die Vorlage aus dem Repository verwendet `latest`.
`VORUM_PORT` ändert den Port auf dem Host. Für gezielten Zugriff über das Netzwerk
kann `VORUM_BIND` auf eine passende Host-IP oder `0.0.0.0` gesetzt werden; dabei
Firewall, HTTPS und den Schutz der Ersteinrichtung berücksichtigen. Ein Proxy auf
dem Host kann den Standard `127.0.0.1` nutzen. Ein Proxy in einem eigenen Container
benötigt eine passende Docker-Netzwerkanbindung.

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

Für eigene Änderungen kannst du das Repository klonen und Vorum aus dem
Quellcode starten. Die enthaltene `compose.yaml` baut das Image lokal:

```sh
docker compose up --build -d
```

Nach Änderungen am Quellcode denselben Befehl erneut ausführen. Für Status,
Logs und Start/Stopp gelten hier die Compose-Befehle ohne
`-f compose.release.yaml`. Unter macOS/Linux steht dafür auch `./server.sh` mit
`start`, `stop`, `restart`, `status` und `logs` zur Verfügung; `start` und `restart`
bauen das Image bei Bedarf neu.

Alternativ ohne Docker mit Python **3.9 oder neuer** starten; das Docker-Image
verwendet Python 3.12:

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

## Docker-Releases veröffentlichen

Die [Release-Anleitung](docs/releases.md) erklärt die einmalige Einrichtung auf
GitHub, die Veröffentlichung einer Version und das Prüfen öffentlicher Downloads.

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
