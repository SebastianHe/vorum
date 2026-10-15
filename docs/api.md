# Vorum API: Benutzer übertragen und anmelden

Die API legt lokale Konten im angesprochenen Forum an, aktualisiert sie anhand
einer externen Benutzer-ID und erstellt einen einmalig verwendbaren Login-Link.
Die andere Anwendung muss den Benutzer selbst authentifizieren, bevor sie einen
Link für ihn anfordert. API-Schlüssel gehören ausschließlich auf ihren Server.

## 1. API-Schlüssel erstellen

Als Admin oder Super-Admin das gewünschte Forum öffnen und im **Backend → API**
einen benannten Schlüssel generieren. Der vollständige Schlüssel erscheint nur
einmal. Vorum speichert ausschließlich seinen SHA-256-Hash. Mehrere Schlüssel
sind möglich; alle Schlüssel eines Forums verwenden denselben Namensraum für
externe Benutzer-IDs. Bei mehreren unabhängigen Quellsystemen daher IDs mit einem
eigenen Präfix verwenden, beispielsweise `crm:customer-0042`.

Unter **Backend → API → Entfernen** wird der Schlüssel sofort ungültig. Auch noch
nicht verwendete Login-Links dieses Schlüssels werden ungültig. Bereits angemeldete
Browser-Sitzungen und angelegte Konten bleiben erhalten. Zur Rotation einen neuen
Schlüssel erstellen, die Integration umstellen und den alten entfernen.

## 2. Anfrage

```http
POST /api/v1/users/login HTTP/1.1
Host: forum.example.org
Authorization: Bearer vorum_DEIN_API_SCHLUESSEL
Content-Type: application/json
Accept: application/json
```

```json
{
  "external_id": "crm:customer-0042",
  "email": "alex@example.org",
  "email_verified": true,
  "username": "Alex",
  "username_suggestion": true,
  "avatar_url": "https://app.example.org/avatars/alex.png",
  "avatar_suggestion": true
}
```

| Feld | Typ | Bedeutung |
| --- | --- | --- |
| `external_id` | String, erforderlich | Dauerhafte ID im Quellsystem, 1–255 Zeichen, nicht nur Leerzeichen, keine Steuerzeichen. Groß-/Kleinschreibung und Leerzeichen sind Bestandteil der ID. Zahlen müssen als String gesendet werden. |
| `email` | String, erforderlich | Gültige E-Mail-Adresse, maximal 254 Zeichen. Wird in Kleinschreibung übernommen. |
| `email_verified` | Boolean, erforderlich | `true`, wenn die andere Anwendung diese Adresse bereits bestätigt hat. |
| `username` | String, erforderlich | Name oder Namensvorschlag, 1–25 Zeichen, keine äußeren oder doppelten Leerzeichen, keine Tabs oder Zeilenumbrüche. |
| `username_suggestion` | Boolean, optional, Standard `false` | `false`: Namen verbindlich übernehmen. `true`: Bei einem neuen Konto darf der Benutzer den vorausgefüllten Namen ändern; bei bestehenden, fertig eingerichteten Konten bleibt der gewählte Name erhalten. |
| `avatar_url` | String oder `null`, optional | Öffentliche HTTP-/HTTPS-Bild-URL ohne Zugangsdaten, maximal 2048 Zeichen. Weglassen, `null` oder `""` bedeutet kein externes Bild. |
| `avatar_suggestion` | Boolean, optional, Standard `false` | `false`: Avatar verbindlich übernehmen, lokale Änderung sperren. `true`: Der Benutzer darf seinen Avatar selbst ändern; neue Benutzer können den vorgeschlagenen Avatar bestätigen oder ablehnen. |

Booleans müssen echte JSON-Werte `true`/`false` sein, keine Strings oder Zahlen.
Jede Anfrage überträgt den vollständigen aktuellen Zustand; sie ist kein partielles
Update. Unbekannte Felder werden abgelehnt. Maximale Größe des JSON-Dokuments:
16 KiB. Es gibt keine Felder für Rollen oder Passwörter. Neue Konten erhalten
immer die Rolle `user`.

Beispiel mit curl, nach Setzen von `VORUM_API_KEY` auf dem aufrufenden Server:

```sh
curl --request POST 'https://forum.example.org/api/v1/users/login' \
  --header "Authorization: Bearer ${VORUM_API_KEY}" \
  --header 'Content-Type: application/json' \
  --data '{
    "external_id": "crm:customer-0042",
    "email": "alex@example.org",
    "email_verified": true,
    "username": "Alex",
    "username_suggestion": true,
    "avatar_url": "https://app.example.org/avatars/alex.png",
    "avatar_suggestion": true
  }'
```

## 3. Antwort und Browser-Anmeldung

Erfolgreiche Neuanlage: **201 Created**. Aktualisierung eines vorhandenen externen
Kontos: **200 OK**. Beispiel:

```json
{
  "created": true,
  "login_url": "https://forum.example.org/api-login/ZUFAELLIGER_GEHEIMER_STRING",
  "expires_in": 300,
  "expires_at": "2026-10-15T12:05:00+00:00",
  "user": {
    "external_id": "crm:customer-0042",
    "email": "alex@example.org",
    "email_verified": true,
    "username": "Alex",
    "profile_required": true
  }
}
```

Den Browser des authentifizierten Benutzers zur vollständigen `login_url`
weiterleiten, beispielsweise mit einer HTTP-302-Antwort. Den Link nicht selbst
serverseitig öffnen: Die Vorum-Sitzung muss im Browser entstehen. Die JSON-Anfrage
erzeugt keine Browser-Anmeldung und benötigt weder Browser-Cookies noch CSRF-Token.

Der geheime String ist zufällig und wird in Vorum nur als Hash gespeichert.
Der Link gilt exakt **300 Sekunden ab Ausstellung**, für das jeweilige Forum und
für **eine erfolgreiche Anmeldung**. Jeder neue API-Aufruf für dieselbe externe
ID ersetzt den vorherigen noch offenen Link. Abgelaufene, ersetzte, widerrufene
oder bereits verwendete Links ergeben im Browser **410 Gone**. Falsche oder nicht
eingerichtete Forum-Hosts ergeben 410 bzw. 404. Parallele Aufrufe können denselben
Link nicht mehrfach einlösen.

Wenn `profile_required` wahr ist, erscheint zuerst eine Profilseite. Der
Namensvorschlag ist vorausgefüllt und bearbeitbar; ein verbindlicher Name bleibt
fest. Ein vorgeschlagener Avatar wird angezeigt und kann über eine Checkbox
übernommen oder abgelehnt werden. Auch der Abschluss dieser Seite muss innerhalb
der fünf Minuten erfolgen. Erst die erfolgreiche Bestätigung verbraucht den Link
und meldet den Benutzer an. Ist kein Profilabschluss nötig, erfolgt die Anmeldung
beim Öffnen des Links sofort.

Bei noch nicht bestätigter E-Mail-Adresse wird die Sitzung angelegt und anschließend
die Vorum-E-Mail-Bestätigung angezeigt. Bis zur Bestätigung gelten die üblichen
Beschränkungen für unbestätigte Konten. SMTP muss dafür konfiguriert sein; ein
Versandfehler kann über „Neuen Code anfordern“ nach behobener Konfiguration erneut
versucht werden. Alternativ kann das Quellsystem die Adresse bestätigen und beim
nächsten API-Aufruf `email_verified: true` senden.

## 4. Regeln für bestehende Konten

- Zuordnung ausschließlich über `(Forum, external_id)`, niemals automatisch über
  E-Mail-Adresse. Dieselbe ID kann in einem anderen Forum ein anderes Konto sein.
  Alle eingerichteten Host-Aliase eines Forums gehören zum selben Forum.
- Die übertragene E-Mail-Adresse wird übernommen. Ist sie einem anderen lokalen
  Konto dieses Forums oder einem globalen Konto zugeordnet, folgt `409 email_conflict`.
  Auch ausstehende E-Mail-Änderungen reservieren eine Adresse. Es werden keine
  Konten zusammengeführt. Lokale Konten anderer Foren dürfen dieselbe Adresse haben.
- Bei unveränderter Adresse bleibt eine Bestätigung erhalten: Ein späteres
  `email_verified: false` setzt sie nicht zurück, auch wenn sie direkt in Vorum
  bestätigt wurde. Bei einer **neuen Adresse** gilt der übertragene Bestätigungsstatus.
- Verbindliche Namen aktualisieren den Benutzernamen bei jeder Übertragung.
  Namensvorschläge überschreiben den selbst gewählten Namen bestehender Konten
  nicht. Ein noch nicht abgeschlossenes neues Profil erhält den aktuellen Vorschlag.
- Verbindliche Avatare ersetzen das vorhandene Bild. Fehlt die URL bei
  `avatar_suggestion: false`, wird der Avatar entfernt und der Initialen-Avatar
  angezeigt. Ein vorgeschlagener Avatar überschreibt bei bereits eingerichteten
  Konten weder ein selbst gewähltes Bild noch eine frühere Ablehnung.
- Für die Avatar-Bearbeitbarkeit ist immer `avatar_suggestion` der **letzten
  erfolgreichen Übertragung** maßgeblich, auch wenn keine Bild-URL mitgesendet wurde.
- API-Konten besitzen keinen lokalen Passwortzugang. E-Mail und Passwort können
  weder in den persönlichen Einstellungen noch über das Backend geändert werden.
  Ein verbindlicher Avatar ist dort ebenfalls gesperrt. Rollen können berechtigte
  Admins weiterhin ändern; API-Konten bleiben an ihr Forum gebunden und können
  nicht global oder zum Super-Admin gemacht werden.
- Eine Kontolöschung bleibt möglich, für API-Konten mit expliziter Bestätigung
  statt Passwortabfrage. Beiträge bleiben entsprechend den Vorum-Regeln erhalten.
  Eine spätere API-Übertragung derselben externen ID legt wieder ein neues Konto an.

Avatar-URLs werden gespeichert und vom Browser geladen. Vorum lädt keine Bilder
serverseitig von fremden URLs herunter. Die URL muss daher ohne Bearer-Token und
ohne vorausgesetzte Sitzung im Quellsystem als Bild abrufbar sein. Für HTTPS-Foren
auch HTTPS-Bilder verwenden. Der externe Bildserver erhält bei der Anzeige eine
Browser-Anfrage ohne Referrer; lokale hochgeladene Avatare werden wie bisher geprüft
und verkleinert.

## 5. Fehler

API-Fehlerantworten haben JSON-Format:

```json
{
  "error": {
    "code": "email_conflict",
    "message": "Diese E-Mail-Adresse wird bereits von einem anderen Benutzer verwendet."
  }
}
```

| HTTP | `error.code` | Ursache |
| --- | --- | --- |
| 400 | `invalid_request` | Fehlerhaftes JSON, kein Objekt oder unbekannte Felder. |
| 400 | `invalid_external_id` | Externe ID fehlt oder ist ungültig. |
| 400 | `invalid_email` | E-Mail-Adresse fehlt oder ist ungültig. |
| 400 | `invalid_username` | Name fehlt oder verletzt die Namensregeln. |
| 400 | `invalid_boolean` | Erforderlicher Bestätigungsstatus fehlt oder ein Boolean hat den falschen Typ. |
| 400 | `invalid_avatar_url` | Avatar-URL hat einen ungültigen Typ oder Inhalt. |
| 401 | `unauthorized` | Bearer-Token fehlt, ist falsch/widerrufen oder gehört zu einem anderen Forum; auch bei unbekanntem Host. |
| 404 | `not_found` | API-Pfad existiert nicht. |
| 405 | `method_not_allowed` | Falsche HTTP-Methode. |
| 409 | `email_conflict` | Adresse ist bereits anderweitig belegt. |
| 413 | `payload_too_large` | Anfrage überschreitet das Größenlimit. |
| 415 | `unsupported_media_type` | `Content-Type: application/json` fehlt. |

`error.code` ist für die programmatische Auswertung vorgesehen. Fehlermeldungen
sind lesbarer Text. Fehlerhafte Anfragen ändern keine Benutzerdaten und erzeugen
keinen Login-Link. Netzwerkfehler und 5xx-Antworten können mit begrenztem Backoff
wiederholt werden. Dabei kann bereits ein Konto angelegt worden sein; erneute
Übertragung derselben ID aktualisiert dieses Konto und erstellt einen neuen Link.

## 6. Webseite, Betrieb und Sicherheit

Unter **Backend → Einstellungen** lassen sich Registrierung und Login getrennt
steuern. Beide sind standardmäßig erlaubt; externe URLs und AGB-Text sind leer.
Eine konfigurierte HTTP-/HTTPS-URL leitet GET- und POST-Aufrufe des jeweiligen
lokalen Formulars mit 302 zur anderen Anwendung weiter, auch wenn das lokale
Formular deaktiviert ist. Ohne externe URL ergibt ein deaktiviertes Formular 403.
Formulareingaben, Passwörter und Rücksprungparameter werden nicht an die externe
URL angehängt. Die externe Anwendung kann nach eigener Anmeldung über die API
wieder einen Vorum-Link erzeugen.

Ein hinterlegter AGB-Text wird bei lokaler Registrierung als Text angezeigt und
muss über eine Checkbox akzeptiert werden. API-Profilbestätigung und API-Login
bleiben von den lokalen Formular-Einstellungen unabhängig. API-Schlüsselverwaltung,
E-Mail-Bestätigung und vorhandene Sitzungen bleiben ebenfalls verfügbar. Vor dem
Deaktivieren des lokalen Logins einen funktionierenden externen Zugang für die
Administratoren einrichten.

Produktiv ausschließlich HTTPS verwenden. Schlüssel und Login-URLs wie Passwörter
behandeln, nicht in öffentlichen Frontends, Analytics oder Nachrichten ausgeben.
Reverse-Proxy- und Zugriffslogs so konfigurieren, dass geheime Login-Pfade nicht
gespeichert werden. Vorum setzt `Cache-Control: no-store` und für Login-Link-Seiten
`Referrer-Policy: no-referrer`. Schlüssel und Links sind je Forum isoliert; Cookies
gelten weiterhin pro Hostname. Für Login-URLs wird der Host und das Schema der
API-Anfrage verwendet. Bei TLS-Terminierung die Hinweise zum Reverse Proxy in der
README beachten.
