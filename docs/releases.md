# Docker-Images veröffentlichen

Vorum veröffentlicht Images unter `ghcr.io/sebastianhe/vorum`. Der Ablauf wird
über die Dateien in `.github/workflows/` gesteuert. Ein Image wird erst verfügbar,
wenn der Release-Workflow erfolgreich abgeschlossen wurde.

## Einmalig auf GitHub

1. Die vorbereiteten Änderungen auf `main` committen und pushen.
2. Unter **Actions** prüfen, dass Workflows zugelassen sind. Falls GitHub Actions
   eingeschränkt ist, müssen die verwendeten Actions von `actions/*` und
   `docker/*` erlaubt sein.
3. Den Workflow **CI** öffnen und auf einen erfolgreichen Lauf warten. Er prüft
   Python 3.9 und 3.12, baut ein Image und startet Webserver und Worker mit einem
   getrennten Testvolume.
4. Unter **Releases → Draft a new release** das erste Release anlegen, siehe unten.
5. Nach dem ersten erfolgreichen Upload das Paket **vorum** im GitHub-Profil unter
   **Packages** öffnen. In **Package settings → Change visibility** auf **Public**
   stellen. Die Sichtbarkeit des Repositories allein reicht dafür nicht aus.
6. Den Download ohne Anmeldung prüfen, siehe Abschnitt „Veröffentlichung prüfen“.

Der Upload verwendet den automatisch bereitgestellten `GITHUB_TOKEN`.
Ein eigener Personal Access Token oder Docker-Hub-Account ist nicht nötig.
`packages: write` ist ausschließlich im Upload-Job freigegeben; `contents: write`
ist ausschließlich im Job zum Anhängen der Compose-Datei freigegeben.
Organisationsrichtlinien können diese Berechtigungen zusätzlich beschränken.

## Erstes Release: v0.1.0

Der Workflow muss bereits auf dem Commit vorhanden sein, den du veröffentlichst.
Auf GitHub im Repository unter **Releases → Draft a new release**:

1. Als Tag `v0.1.0` eingeben und **Create new tag** wählen.
2. Als Ziel den erfolgreich geprüften Commit auf `main` auswählen.
3. Titel `Vorum 0.1.0` und kurze Release Notes mit Funktionen, bekannten
   Einschränkungen und Betriebs-/Updatehinweisen eintragen.
4. Für diese reguläre Version **Set as a pre-release** nicht aktivieren.
5. **Publish release** wählen.

Damit startet **Publish Docker image** automatisch. Der Workflow prüft den
Release-Stand erneut, baut Images für `linux/amd64` und `linux/arm64` und lädt
folgende Tags hoch:

```text
ghcr.io/sebastianhe/vorum:0.1.0
ghcr.io/sebastianhe/vorum:0.1
ghcr.io/sebastianhe/vorum:latest
```

Die Images enthalten Metadaten zu Quelle, Commit, Version und Lizenz sowie
Build-Provenienz und eine Software-Stückliste (SBOM).
Danach hängt der Workflow eine `compose.release.yaml` an das Release an. Ihr
Standard-Image ist fest auf `0.1.0` gesetzt. Die Datei im Repository ist dagegen
eine Vorlage mit `latest` als Standard.

Ein bloßer Git-Push oder Tag-Push veröffentlicht kein Image. Entwürfe lösen den
Workflow ebenfalls nicht aus; entscheidend ist **Publish release**.

## Veröffentlichung prüfen

1. Unter **Actions** müssen die Jobs von **Publish Docker image** erfolgreich sein.
   Insbesondere auch **Attach versioned Compose file** prüfen.
2. Auf der Release-Seite muss `compose.release.yaml` unter **Assets** erscheinen.
3. In einer Umgebung ohne GHCR-Anmeldung testen, beispielsweise mit einer
   temporären leeren Docker-Konfiguration auf macOS/Linux:

   ```sh
   docker_config_dir=$(mktemp -d)
   docker --config "$docker_config_dir" pull ghcr.io/sebastianhe/vorum:0.1.0
   rm -rf "$docker_config_dir"
   ```

4. Die Plattformen prüfen:

   ```sh
   docker buildx imagetools inspect ghcr.io/sebastianhe/vorum:0.1.0
   ```

   `linux/amd64` und `linux/arm64` müssen vorhanden sein. Zusätzliche
   `unknown/unknown`-Einträge können die Build-Attestierungen darstellen.
5. Die angehängte Compose-Datei in einem neuen Verzeichnis herunterladen und
   entsprechend der [README](../README.md) starten. Ersteinrichtung, SMTP,
   Benachrichtigungen und Backup/Wiederherstellung separat erproben. Der
   automatisierte Container-Starttest prüft keinen echten SMTP-Server.

## Weitere Versionen und Vorabversionen

Für ein Update einen neuen Tag verwenden, etwa `v0.1.1`. Eine bereits vergebene
Versionsnummer nicht für veränderten Code wiederverwenden.

Eine Vorabversion trägt einen Suffix, beispielsweise `v0.2.0-rc.1`, und muss beim
Veröffentlichen auf GitHub als **pre-release** markiert werden. Sie erhält nur den
Image-Tag `0.2.0-rc.1`; `latest` und der Kurz-Tag bleiben unverändert.
Tag-Suffix und GitHub-Markierung müssen zusammenpassen, sonst bricht der Workflow ab.
Versionsnummern mit Build-Metadaten (`+...`) werden nicht unterstützt.

Jede reguläre Veröffentlichung setzt `latest` und ihren `MAJOR.MINOR`-Kurz-Tag neu.
Auch das Veröffentlichen einer älteren regulären Version würde deshalb `latest`
verschieben. Für ältere Wartungszweige den Workflow vorab um eine passende
Tag-Strategie erweitern. Für den Betrieb eine konkrete vollständige Version oder
einen Digest verwenden.

## Wenn ein Workflow fehlschlägt

Im fehlgeschlagenen Lauf unter **Actions** zuerst den betroffenen Schritt prüfen:

- **Validate release version:** Tagformat und Pre-release-Markierung kontrollieren.
- **Release checks:** Test- oder Startfehler beheben. Für geänderten Code ein neues
  Release mit neuer Versionsnummer veröffentlichen.
- **Log in / Build and publish:** Workflow-/Paketberechtigungen und GHCR prüfen.
- **Upload the Compose file:** Schreibberechtigung für Release-Assets prüfen.

Nach einem vorübergehenden Infrastrukturfehler können fehlgeschlagene Jobs auf
GitHub erneut ausgeführt werden. Wurde das Image bereits hochgeladen, aber das
Anhängen der Compose-Datei schlug fehl, kann das Paket bereits verfügbar sein.

Abhängigkeiten und das Basisimage verwenden Versionsbereiche bzw. einen
beweglichen Python-Tag. Ein erneuter Build desselben Commits kann dadurch andere
Abhängigkeitsstände enthalten. Die vollständige Image-Version nicht absichtlich
überschreiben; für aktualisierte Abhängigkeiten ein neues Release veröffentlichen.
Die verwendeten GitHub Actions sind auf Commit-IDs fixiert und müssen bei Updates
gezielt aktualisiert werden.

Offizielle Anleitungen: [Images mit GitHub Actions veröffentlichen](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images),
[GHCR verwalten](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
und [mehrere Plattformen bauen](https://docs.docker.com/build/ci/github-actions/multi-platform/).
