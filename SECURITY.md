# Sicherheitsrichtlinie

## Eine Sicherheitslücke melden

Bitte melde Sicherheitslücken vertraulich über GitHubs private Sicherheitsmeldungen:

1. Öffne das GitHub-Repository von Vorum.
2. Wähle **Security → Advisories → Report a vulnerability**.
3. Beschreibe die Schwachstelle und die Schritte zur Reproduktion.

Veröffentliche vor der Abstimmung bitte keine Exploit-Details in öffentlichen
Issues, Pull Requests oder Diskussionen. Fehlt die Schaltfläche, kann zunächst
ein öffentliches Issue **ohne technische Details** darum bitten, private
Sicherheitsmeldungen zu aktivieren. Vertrauliche Informationen erst über den
privaten Meldeweg übermitteln.

Hilfreich sind:

- Betroffener Commit bzw. Version sowie Python-/Docker-Umgebung.
- Betroffene Funktion, notwendige Voraussetzungen und erwartetes gegenüber
  tatsächlichem Verhalten.
- Ein möglichst kleines Beispiel mit künstlichen Daten und klaren Schritten.
- Mögliche Auswirkungen, insbesondere Zugriff auf andere Foren oder Konten.

Bitte keine echten Zugangsdaten, Sitzungscookies, API-Schlüssel, Login-Links,
Benutzerdaten oder Datenbankkopien mitsenden. Tests nur an eigenen Installationen
oder mit ausdrücklicher Erlaubnis der Betreiber durchführen.

Die Bewertung und eine mögliche Veröffentlichung eines Sicherheitshinweises
werden im privaten Bericht abgestimmt. Es gibt derzeit keine garantierte
Reaktionszeit und kein Bug-Bounty-Programm.

## Unterstützter Stand

Sicherheitskorrekturen werden auf dem aktuellen Entwicklungsstand vorgenommen.
Es gibt derzeit keine zugesagte Pflege älterer Versionszweige. Betreiber sollten
verfügbare Sicherheitshinweise und Aktualisierungen verfolgen und vor Updates
Backups anlegen.

## Hinweise für Betreiber

- Die Ersteinrichtung abschirmen: Das erste registrierte Konto wird globaler
  Super-Admin. Vor der öffentlichen Freigabe selbst anlegen und ein starkes,
  individuelles Passwort verwenden.
- HTTPS einsetzen und `COOKIE_SECURE=1` für Webserver und Worker setzen. Nur die
  vorgesehenen Domains am Reverse Proxy zulassen und den ursprünglichen
  Host-Header weitergeben. Proxy-, Schema- und Port-Konfiguration prüfen.
- Forenübersicht und Beiträge sind öffentlich lesbar. Die Mandantenzuordnung per
  Hostname ist keine Funktion für private Foren.
- Datenvolume und Backups schützen. Sie enthalten persönliche Daten,
  Passwort-Hashes, SMTP-Zugangsdaten und den persistenten Sitzungsschlüssel.
  SMTP-Passwörter sind in der Datenbank nicht zusätzlich verschlüsselt.
- Für unbestätigte Registrierungen speichert Vorum den aktuell versendeten
  Bestätigungscode zusätzlich im Klartext, damit berechtigte Administratoren ihn
  anzeigen können. Nach Bestätigung oder Sperrung wird er gelöscht; abgelaufene
  Codes werden nicht angezeigt. Das ist bei der Vergabe von Adminrechten und
  beim Umgang mit Datenbanksicherungen zu berücksichtigen.
- API-Schlüssel und einmalige Login-Links wie Passwörter behandeln. Geheime
  Login-Pfade aus Proxy-Zugriffslogs und Analytics ausschließen. Bei vermutetem
  Schlüsselverlust den betroffenen API-Schlüssel widerrufen.
- Anhänge sind von Mitgliedern bereitgestellte Dateien. Vorum ersetzt keine
  Prüfung auf Schadsoftware. Downloads benötigen ein bestätigtes Konto.
- Anwendung und Container-Basis regelmäßig aktualisieren. Den Entwicklungsserver
  und den Debug-Modus nicht öffentlich betreiben.

Details zu [Betrieb und Backups](docs/operations.md) und zur
[API-Integration](docs/api.md) ergänzen diese Hinweise.

## Einrichtung des Meldewegs durch Maintainer

Nach dem Anlegen des öffentlichen GitHub-Repositories muss **Private vulnerability
reporting** aktiviert werden. Die Datei allein schaltet den Meldeweg nicht frei.
Aktiviere außerdem Benachrichtigungen für Sicherheitsmeldungen und prüfe, ob die
Schaltfläche **Report a vulnerability** erreichbar ist.

Die Schritte beschreibt die
[GitHub-Anleitung](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository).
