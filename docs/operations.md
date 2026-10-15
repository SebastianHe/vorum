# Vorum: Betrieb und Funktionsdetails

Diese Anleitung ergänzt den [Schnellstart](../README.md) um technische Details
zu Rollen, E-Mail-Versand und dem Betrieb einer Installation.

## Daten und Sicherungen

Im Docker-Betrieb enthält das Volume `vorum-data` unter `/app/data` die
SQLite-Datenbank, Uploads, Branding-Dateien und den automatisch erzeugten
Sitzungsschlüssel `secret.key`. Ohne Docker liegt das Datenverzeichnis
standardmäßig unter `data/` im Arbeitsverzeichnis.

Für eine einfache konsistente Dateisicherung:

1. Webserver und Benachrichtigungs-Worker stoppen, mit Docker beispielsweise
   `docker compose stop`.
2. Den gesamten Inhalt des Datenvolumes bzw. Datenverzeichnisses in ein geschütztes
   Backup kopieren. SQLite-WAL-Dateien gehören zum Datenbestand.
3. Dienste mit `docker compose start` wieder starten.

Eine Wiederherstellung erfolgt bei gestoppten Diensten in ein leeres Datenvolume.
Dateirechte müssen zum Container-Benutzer (UID `10001`) passen. Anschließend beide
Dienste starten und Anmeldung, Anhänge und E-Mail-Versand prüfen. Backups und
Wiederherstellungen regelmäßig mit einer separaten Installation erproben.

SMTP-Zugangsdaten sind in der Datenbank gespeichert. Auch Benutzerdaten,
Bestätigungscodes und Sitzungsschlüssel machen Datenvolume und Backups vertraulich.
Sie gehören niemals ins Repository, in ein Docker-Image oder in öffentliche Issues.

## Updates

Vor jeder Aktualisierung ein vollständiges Backup anlegen und Hinweise zur neuen
Version lesen. Bei einer aus dem Quellcode betriebenen Docker-Installation nach
dem Aktualisieren der Projektdateien `docker compose up --build -d` ausführen.
Bestehende Datenbanken werden beim Start automatisch um benötigte Felder ergänzt.
Ein älterer Programmstand ist danach nicht zwangsläufig mit der Datenbank
kompatibel; für einen Rückwechsel das dazugehörige Backup verwenden.

## HTTPS und Reverse Proxy

Für öffentlichen Betrieb HTTPS vorsehen und `COOKIE_SECURE=1` setzen. Der Proxy
muss den ursprünglichen Host-Header weitergeben, weil Vorum darüber das Forum
bestimmt. Nur konfigurierte Domains zum Dienst durchlassen und den direkten
Zugriff auf den Anwendungsport per Firewall oder Port-Bindung begrenzen.

Vorum vertraut Forwarded-Headern nicht automatisch. Bei TLS-Terminierung am Proxy
wird das öffentliche HTTPS-Schema deshalb nicht allein durch
`X-Forwarded-Proto: https` übernommen. Für automatisch erzeugte externe Links,
insbesondere API-Login-Links, muss Vorum das richtige Schema sehen, etwa durch
HTTPS auch auf der Verbindung vom Proxy zum Anwendungsserver. Die mitgelieferte
Gunicorn-Konfiguration bietet auf Port 8000 zunächst HTTP; ein solcher Aufbau
braucht eine angepasste Server- und Proxy-Konfiguration. Vor einer Freigabe die
erzeugten URLs prüfen. Ein HTTP-Ziel mit sicheren Cookies kann die Anmeldung
verhindern.

Geheime API-Login-Pfade nicht in Proxy-Zugriffslogs oder Analytics speichern.
Weitere Hinweise stehen in [SECURITY.md](../SECURITY.md).


## Funktionen und Regeln

- Vier Rollen: Super-Admin, Admin, Moderator, User. Super-Admins verwalten Mandanten und können Rollen vergeben. Lokale Admins verwalten Benutzer, Moderatoren und Admins ihres Forums. Globale Konten können nur Super-Admins bearbeiten. Super-Admins können lokale Benutzer global verfügbar machen; globale Rollen gelten in allen Foren.
- Konten sind lokal oder global. Gleiche lokale E-Mail-Adressen sind in verschiedenen Mandanten erlaubt. Globale Adressen sind überall reserviert, auch während ausstehender E-Mail-Änderungen.
- Verifizierung: fünfstellige zufällige Codes, gehasht gespeichert, 15 Minuten gültig. Nach fünf Fehlern 30 Minuten Sperre, mindestens 60 Sekunden zwischen Sendungen. Erneutes Senden setzt den Fehlerzähler nicht zurück. Ohne funktionierendes SMTP bleibt die Registrierung unbestätigt. Für unbestätigte Registrierungen wird der aktuelle Code zusätzlich gespeichert und berechtigten Administratoren in der Benutzeransicht angezeigt, solange er gültig ist. Bei Bestätigung oder Sperrung wird er gelöscht. Codes erscheinen niemals in Produktionslogs. Bereits vor dieser Erweiterung versendete Codes sind erst nach erneutem Versand anzeigbar.
- E-Mail-Änderungen benötigen einen neuen Code; bis zur Bestätigung bleibt die alte Adresse gültig. Das gilt auch für Änderungen durch Administratoren. Die betroffene Person meldet sich mit ihrer bisherigen Adresse an und öffnet „E-Mail bestätigen“ im Benutzermenü.
- Themenbereiche sind verpflichtend, sofern vorhanden. Löschen eines Themenbereichs entfernt nur die Zuordnung bestehender Topics. Titel und Metadaten liegen am Topic, Text und Anhänge ausschließlich am Beitrag.
- HTML-Rich-Text-Editor mit serverseitiger HTML-Bereinigung. Ohne JavaScript steht ein Textfeld zur Verfügung. Anhänge: maximal 10 MiB je Datei, bis zu fünf Dateien je Upload, 60 MiB Anfragegrenze. Downloads erfordern ein bestätigtes Konto. Avatare werden geprüft und als PNG bis 256 Pixel neu gespeichert; sonst erscheint ein Initialen-Avatar aus 20 gespeicherten Farben.
- Autoren und Moderation können Beiträge bearbeiten; vorherige Versionen und Bearbeiter werden protokolliert. Moderatoren und Administratoren dürfen Beiträge löschen. Beim letzten Beitrag wird auch das Topic entfernt.
- Die Übersicht zeigt die 100 zuletzt aktiven Topics mit Mitwirkenden, Antworten, Aufrufen und persistentem Lesestatus. Neue Beiträge und Bearbeitungen markieren Topics als ungelesen.
- Benachrichtigungen oben rechts: Forum-Abos für alle neuen Themen und Beiträge, nur neue Themen, tägliche/wöchentliche Zusammenfassung oder keine Mails. Topic-Abos für jeden neuen Beitrag, tägliche/wöchentliche Zusammenfassung oder keine Mails. Standardmäßig sind beide deaktiviert. Forum- und Topic-Abos gelten unabhängig; das Abschalten eines Abos deaktiviert das andere nicht. Überlappende direkte Benachrichtigungen werden pro Beitrag und Empfänger zusammengefasst, überlappende Zusammenfassungen gleicher Frequenz pro Forum und Empfänger ebenfalls.
- Kontolöschung erhält Topics und Beiträge mit dem zuletzt verwendeten Benutzernamen als „Gast“. Der letzte Super-Admin kann weder gelöscht noch herabgestuft werden.
- Unter **Backend → Aussehen** lässt sich das Farbschema wählen. Unter **Logo** kann ein eigenes Bild hochgeladen oder entfernt werden; es wird als Foren-Logo und Favicon verwendet (maximal 10 MB und 20 Millionen Pixel).
- Die Kurzzeile, Überschrift und Beschreibung der Startseite lassen sich unter **Backend → Aussehen → Startseitentexte** jeweils für **Deutsch und Englisch** bearbeiten. Neue und bestehende Foren verwenden zunächst die bisherigen Texte. Die Anzeige folgt der gewählten Sprache.
- Zeitzone je Forum unter **Backend → Einstellungen → Dein Forum** aus einer Liste von IANA-Zeitzonen auswählen. Standard für neue und bestehende Foren ist **UTC**. Datums- und Uhrzeitangaben werden in der gewählten Zeitzone angezeigt, Sommer- und Winterzeit automatisch berücksichtigt. Gespeicherte Zeitstempel bleiben in UTC; die Versandzeitzone für Zusammenfassungen wird separat eingestellt.
- CSRF-Schutz, parametrisierte SQL-Abfragen, Passwort-Hashes, Login-Drosselung, sichere lokale Rücksprungadressen, isolierte Mandantenabfragen und Security-Header.

## E-Mail-Benachrichtigungen

Direkte Mails gehen nach dem erfolgreichen Speichern eines neuen Topics oder Beitrags über das SMTP des jeweiligen Forums an bestätigte Abonnenten. Eigene Beiträge, Bearbeitungen, Löschungen und fehlgeschlagene Veröffentlichungen lösen keine Mails aus. Ein Forum-Abo „nur neue Themen“ meldet den ersten Beitrag eines neuen Topics, keine späteren Antworten. Globale Benutzer haben separate Abos je Forum. Mails enthalten einen Textauszug und einen Link zum Beitrag; die Sprache wird beim Einstellen des Abos übernommen.

Zusammenfassungen werden **täglich um 16:00 Uhr Europe/Berlin**, wöchentlich **samstags um 16:00 Uhr Europe/Berlin** verschickt. Sommer- und Winterzeit gelten automatisch. Uhrzeit, IANA-Zeitzone und Wochentag lassen sich unter **Backend → Einstellungen → Zusammenfassungen** ändern. Der Worker prüft jede Minute; nach einer Unterbrechung holt er fällige Zusammenfassungen nach.

Eine Zusammenfassung enthält ausschließlich fremde Beiträge, die seit dem Aktivieren des Abos und seit dem letzten erfolgreich verarbeiteten Versand neu erstellt wurden. Forum-Zusammenfassungen berücksichtigen zusätzlich den letzten Besuch der Forumsübersicht oder eines Topics im Forum. Topic-Zusammenfassungen berücksichtigen den letzten Besuch dieses Topics. Bereits gelesene Beiträge und leere Zusammenfassungen werden nicht verschickt. Die bloße Bearbeitung eines alten Beitrags nimmt ihn nicht erneut auf. Tages- und Wochen-Abos gelten als unterschiedliche Frequenzen.

Docker Compose und `./server.sh start` starten neben dem Webserver automatisch den Benachrichtigungs-Worker mit demselben Datenvolume. Ohne Docker muss ein zusätzlicher Prozess laufen:

```sh
flask --app vorum notification-worker
```

Alternativ kann ein externer Scheduler mindestens einmal pro Minute den einmaligen Durchlauf starten:

```sh
flask --app vorum send-notifications
```

Webserver und Worker benötigen dasselbe `VORUM_DATA`. Direkte Benachrichtigungen werden gemeinsam mit dem Beitrag dauerhaft vorgemerkt. Bei SMTP-Fehlern bleiben sie sowie ausstehende Zusammenfassungen für den nächsten Versuch erhalten; das Erstellen des Beitrags bleibt erfolgreich. Mehrere Worker werden beim Versand per Datenbanksperre koordiniert. Wie bei SMTP üblich kann ein Prozessabbruch nach Mailannahme, aber vor dem Speichern der Versandbestätigung, zu einem erneuten Versand führen.

## API und externe Anmeldung

Unter **Backend → API** können Admins API-Schlüssel für das jeweilige Forum
generieren und entfernen. Die JSON-API mit Bearer-Authentifizierung erstellt und
aktualisiert externe Benutzer und liefert einmalig verwendbare Login-Links mit
fünf Minuten Gültigkeit. Die vollständige Integrationsanleitung mit JSON-Beispielen,
Vorschlagsregeln und Fehlercodes steht in [API-Anleitung](api.md) und kann im
API-Bereich heruntergeladen werden.

Unter **Backend → Einstellungen** lassen sich die lokale Registrierung und der
lokale Login erlauben, sperren oder auf eine externe URL umleiten. Optionaler
AGB-Text wird bei lokaler Registrierung mit einer erforderlichen Zustimmung
angezeigt. Die API bleibt unabhängig von diesen Website-Einstellungen verfügbar.
Bestehende Datenbanken werden beim Start automatisch um die neuen Felder ergänzt.

