# COMEXIO Local 0.3.3

![COMEXIO Local](docs/images/comexio-local-banner.png)

**COMEXIO Local** ist eine eigenständige Home-Assistant-Integration für COMEXIO-IO-Server.

Ziel des Projekts ist eine **dynamische**, **lokale** und **ressourcenschonende** Anbindung, die zu einer bestehenden COMEXIO-Installation passt:

- **keine fest im Quellcode hinterlegten Kanaladressen**
- **keine dauernden Polling-Intervalle** für Zustandsrückmeldungen
- **dynamische Erkennung** aktiver IOs und relevanter Merker
- **Push-Rückmeldungen** von COMEXIO nach Home Assistant über Web-IO/Webhook
- **keine Änderungen an vorhandenen Raumplänen** ohne ausdrückliche Freigabe

Repository: <https://github.com/CrashND/comexio-local>

## Status

**Aktueller Stand:** Entwicklungs- und Testversion.

Praktisch bestätigt:

- HACS-Installation aus dem eigenen GitHub-Repository
- dynamische Erkennung der COMEXIO-Konfiguration
- Steuerung erkannter Licht-Entitäten aus Home Assistant
- Grundgerüst für Rollladen-/Cover-Entitäten

Noch nicht vollständig bestätigt:

- durchgängige Push-Rückmeldung physischer Tastendrücke auf allen Zielsystemen
- vollautomatische Einrichtung aller benötigten Web-IO-Verbindungen auf jedem COMEXIO-Stand
- Laufzeitvalidierung auf unterschiedlichen HAOS-/Firmware-Kombinationen

## Funktionsumfang

### Bereits enthalten

- **Config Flow** für die Einrichtung in Home Assistant
- **dynamisches Discovery** über die COMEXIO-Konfiguration
- **Licht-Entitäten** aus erkannten Ausgängen
- **Cover-Erkennung** aus vorhandenen Soll-/Ist-Merkerpaaren
- **manuelle Neu-Erkennung** per Aktion `comexio_local.refresh_discovery`
- **Push-Einrichtung** per freizugebender Aktion `comexio_local.configure_push`
- **Push-Diagnose** per Aktion `comexio_local.push_diagnose`
- **Gezielte Push-Reparatur** über **Konfigurieren** mit lesender Vorschau und Backup-Bestätigung
- **Ereignisprotokoll** mit COMEXIO-Quelle, Wert und UTC-Empfangszeit
- **Auswertung pro Quelle** per Aktion `comexio_local.get_push_events`
- **einmaliger Snapshot** per Aktion `comexio_local.snapshot_once`

### Architektur

- **COMEXIO → Home Assistant:** Ereignisbasiert über Web-IO/Webhook
- **Home Assistant → COMEXIO:** TCP JSON auf Port `1505`
- **Node-RED:** kann weiterhin separat für Szenen, Logik und Automatisierung verwendet werden

## Installation über HACS

1. Repository in GitHub veröffentlichen bzw. aktuell halten.
2. In HACS: **Benutzerdefiniertes Repository** hinzufügen:
   - URL: `https://github.com/CrashND/comexio-local`
   - Typ: **Integration**
3. COMEXIO Local in HACS installieren.
4. Home Assistant neu starten.
5. Integration unter **Einstellungen → Geräte & Dienste** hinzufügen.

## Wichtige Hinweise zur Push-Rückmeldung

Die Integration ist bewusst **nicht** als zyklisch pollende Lösung aufgebaut.

Für physische Tastendrücke und lokale Zustandsänderungen ist vorgesehen:

1. einmaliger Snapshot beim Start bzw. auf Anforderung
2. Web-IO-basierte Rückmeldung von COMEXIO an einen lokalen HA-Webhook
3. Zuordnung der Ereignisse zu den dynamisch erkannten Entitäten

Die Aktion `comexio_local.configure_push` verändert COMEXIO-Konfigurationen. Deshalb gilt:

- vorher COMEXIO-Konfiguration sichern
- nur bewusst und gezielt ausführen
- keine wiederholten Massen-Schreibzugriffe ohne Prüfung

Die Aktion `comexio_local.push_diagnose` ist dagegen **rein lesend** und dient zur Prüfung des Rückkanals.

## Push-Ereignisse untersuchen (ab v0.3.2)

Die neue Diagnose speichert **nur empfangene, bereits akzeptierte Webhook-Ereignisse**. Sie fragt COMEXIO nicht ab, verändert keine Web-IO-Pläne und verschickt keine zusätzlichen HTTP-Anfragen.

**Direkt in Home Assistant:**

- Unter **Entwicklerwerkzeuge → Zustände** den Sensor `sensor.comexio_push_ereignisprotokoll` aufrufen. Seine Attribute `recent_events` zeigen die letzten 12 Ereignisse (neueste zuerst). `source_counts` zählt pro COMEXIO-Anschluss die akzeptierten Meldungen.
- Unter **Entwicklerwerkzeuge → Aktionen** die neue Aktion `comexio_local.get_push_events` ausführen, mit **Antwort anzeigen**. Sie liefert standardmäßig 30, auf Wunsch bis zu 80 letzte Ereignisse sowie die vollständigen Zähler pro beobachteter Quelle.

Beispiel einer lesenden Aktionsabfrage:

```yaml
action: comexio_local.get_push_events
data:
  limit: 30
```

Jedes Ereignis enthält `received_at_utc` (UTC-Zeit), `source` (z. B. `io:IO-Ext-2/Q2`), `name`, `kind`, `value`, `entity_id` (falls die Entität registriert ist) sowie `previous_cached_value` und `changed_since_cached`. **Wichtig:** `changed_since_cached` vergleicht lediglich den letzten im HA-Cache gespeicherten Wert; es ist kein Nachweis einer physischen Änderung. Derselbe Wert kann mehrfach als gültiger Push empfangen werden.

Die Statistik `sources` in der Aktionsantwort sortiert nach **Häufigkeit**. So kann man unmittelbar erkennen, welche Quellen die Ereignisse erzeugen und welche **noch überhaupt nicht gemeldet** haben. Nicht erwähnte Quellen sind nicht zwingend falsch konfiguriert – sie haben nur seit dem letzten Start der Integration kein akzeptiertes Ereignis geliefert.

Zusätzlich feuert die Integration je akzeptierter Meldung ein Home-Assistant-Ereignis vom Typ `comexio_local_push` mit denselben Quelldaten. Dies kann zum Live-Mithören verwendet werden.

**Datensparsamkeit und Ressourcen:** Das Protokoll liegt nur im Arbeitsspeicher, hält höchstens 80 Ereignisse vor und wird beim Neustart/Neuladen der Integration zurückgesetzt. Der Diagnose-Sensor zeigt bewusst nur die letzten 12 Einträge, um die Home-Assistant-Datenbank nicht unnötig zu belasten. Der ursprüngliche Ereigniszähler bleibt erhalten. Es werden weder Passwörter noch der geheime Webhook-Pfad protokolliert.

**Praxisbefund (03.11.2026):** Nach der ersten Installation funktionierten nicht alle Push-Quellen. Der Büro-Web-IO-Befehl `IO-Ext-2/Q2` ließ sich manuell testen, meldete aber keine Wandtaster-Änderungen. Nach dem gezielten Entfernen des Web-IO-Bausteins und Befehls sowie dem Neuaufbau funktionierten die Meldungen. Die Ursache ist noch nicht technisch bewiesen; zu schnelle COMEXIO-Konfigurationsschreibzugriffe sind eine Arbeitshypothese. Die Diagnose erfasste 504 Ereignisse, davon 477 Positionsmeldungen zweier Rollläden und 27 Lichtmeldungen aus acht Quellen.

## Push-Reparatur in Home Assistant (v0.3.3)

**Einstellungen → Geräte & Dienste → COMEXIO Local → Konfigurieren → Push-Verbindungen prüfen und reparieren.**

Dort kannst du eine Licht- oder Rollladenquelle, mehrere Quellen oder alle erkannten Push-Quellen auswählen. Die Integration liest deren COMEXIO-Web-IO-Konfiguration **zunächst nur** und zeigt für jede Quelle Namen, COMEXIO-Adresse, vorhandenen Web-IO-Befehl, Logikplan und vorgeschlagene Maßnahme.

**Unterstützte automatische Reparaturen nach Bestätigung und vorhandener Sicherung:**

- Einen fehlenden COMEXIO-Local-Web-IO-Befehl neu erstellen.
- Eine fehlende Quellverbindung ergänzen.
- Einen fehlenden eigenen Push-Plan anlegen und verbinden.
- Alle erforderlichen Konfigurationsschreibzugriffe seriell und gedrosselt ausführen.

Bei einer bereits vollständig vorhandenen Verbindung, deren Push dennoch ausbleibt (wie zuvor im Büro), ist ein **geführter Neuaufbau** vorgesehen: Die Vorschau identifiziert den genauen Befehl und seinen CL-Plan. Du entfernst **ausschließlich den betreffenden Web-IO-Baustein im eigenen Push-Plan und anschließend den zugehörigen Web-IO-Befehl** manuell in COMEXIO. Nach erneuter Vorschau kann die Integration die fehlenden Teile kontrolliert wieder anlegen. **Automatisches Löschen bestehender COMEXIO-Elemente ist in v0.3.3 ausdrücklich deaktiviert**, weil die nötigen Löschschnittstellen für Firmware 11.1.5 noch nicht ausreichend verifiziert wurden. Ein vollständiger automatischer Lösch-und-Neuaufbau aller 29 Komponenten gehört deshalb **nicht** zu v0.3.3.

Die Vorschau weist auch auf nicht auslesbare Web-IO-Felder hin; *„vorhanden“* ist nicht mit *„Ende-zu-Ende getestet“* gleichzusetzen. Die Integration prüft vor dem ersten Schreibzugriff erneut, ob die COMEXIO-Topologie unverändert ist. Bei fremden Logikplänen, Mehrdeutigkeiten, abweichenden lesbaren Parametern oder verwaisten Befehlsbausteinen erfolgt **keine automatische Reparatur**.

**Sicherheitsregeln:** Vor Änderungen selbst eine vollständige COMEXIO-Konfigurationssicherung erstellen. Das Häkchen in Home Assistant bestätigt eine bereits vorhandene Sicherung, erzeugt sie aber **nicht**. Änderungen werden ausschließlich nach ausdrücklicher Freigabe ausgeführt; die Integration startet keine Licht- oder Rollladenfahrten durch TCP-SET. Das erneute **Aktivieren eines geänderten CL-Push-Plans kann jedoch COMEXIO-Logik neu auswerten**. Daher nicht während sicherheitskritischer oder unerwünschter Rollladenfahrten reparieren. Nach jeder Reparatur die Quelle am physischen Taster testen und mit `comexio_local.get_push_events` prüfen.

Technisch werden Web-IO-Befehle **einzeln** angelegt, mit mindestens **1,25 Sekunden Abstand zwischen Konfigurationsschreibzugriffen** und **0,8 Sekunden Beruhigungszeit** vor der erneuten Sichtprüfung. Nach jedem Befehl und jeder neuen Verbindung wird die COMEXIO-Konfiguration erneut gelesen. Bei fehlender Bestätigung wird **nicht blind erneut geschrieben**; die Integration hält an und meldet mögliche Teiländerungen.

Für erfahrene Nutzer gibt es die Home-Assistant-Aktionen `comexio_local.preview_push_repair` (nur lesen) und `comexio_local.repair_push` (Adminaktion; Fingerabdruck aus der Vorschau und `confirm: true` nötig). Die grafische Bedienung ist der Standard.

### Benennung und Geräteinformationen

Neu angelegte Ressourcen erhalten lesbarere Namen wie `HA Licht Buero Q2 E2`, `HA Rollo Buero M85` und `HA Push IO-Ext-2 1`. Alte `CL...`-Namen werden aus Gründen der Rückwärtskompatibilität **beibehalten und erkannt**, nicht automatisch umbenannt. Die Quellenauswahl in Home Assistant nutzt unabhängig davon die tatsächlichen Raumnamen. Das automatische Umbenennen vorhandener COMEXIO-Objekte ist wegen der ungeprüften Schreib-/Löschsemantik noch nicht enthalten.

Das Gerät wird als **COMEXIO IO-Server 2G** mit Link zur lokalen Weboberfläche geführt. Eine Firmwareversion wird nur angezeigt, wenn die COMEXIO-Konfiguration einen eindeutig als Firmwareversion benannten Wert bereitstellt; sonst bleibt sie unbekannt. Der Diagnose-Sensor **COMEXIO Local Version** zeigt die Integrationsversion (`0.3.3`) getrennt davon an.

### GitHub-Release, HACS und Branding

Für HACS einen GitHub-Tag **`v0.3.3`** auf dem Commit mit `manifest.json`-Version **`0.3.3`** erstellen und dazu einen Release mit Versionshinweisen veröffentlichen. Bei HACS-Installationen, die einem Git-Branch statt einem Release folgen, können Kurz-Commit-Hashes als Versionsnummer erscheinen. Branch-Tracking und Release-Markierung daher vor der Fehlersuche prüfen. Eine Veröffentlichung als *Pre-release* wird von HACS möglicherweise nicht wie ein stabiler Release ausgewählt.

Das Logo liegt weiterhin korrekt im lokalen `brand/`-Ordner. Dass die HACS-Update-Kachel dennoch **„icon not available“** zeigt, ist ein bekanntes HACS-Frontend-Problem für benutzerdefinierte Integrationen seit HA 2026.3 und lässt sich nicht zuverlässig durch ein zweites Repository-Logo beheben. Siehe <https://github.com/hacs/integration/issues/5402> und <https://github.com/hacs/integration/issues/5223>.

## Projektstruktur

```text
custom_components/comexio_local/
    __init__.py
    admin_api.py
    binary_sensor.py
    config_flow.py
    constants.py
    cover.py
    discovery.py
    entities.py
    light.py
    manifest.json
    push_audit.py
    push_journal.py
    push_setup.py
    runtime.py
    sensor.py
    services.yaml
    strings.json
    tcp_client.py
    brand/
    translations/

docs/images/
    comexio-local-banner.png
    comexio-local-original.png

tests/
```

## Transparenz / Herkunft

Dieses Projekt ist **eine eigenständige Entwicklung** und **keine Fortführung** der früheren Community-Integration von **kayl-codes**.

Die frühere Integration war dennoch eine wichtige **technische Referenz**, insbesondere für das Verständnis der COMEXIO-Strukturen und Web-IO-Mechanismen:

- Referenzprojekt: <https://github.com/kayl-codes/homeassistant-comexio>

Zusätzlich wurde dieses Projekt **mit Unterstützung generativer KI (ChatGPT / OpenAI)** gemeinsam konzipiert, dokumentiert und in Teilen implementiert.

Das soll ausdrücklich transparent sein:

- Projektidee, Anforderungen und Praxistests: **CrashND**
- Architektur, Formulierung, Codeentwürfe, Dokumentation und Iteration: **gemeinsam mit ChatGPT**

Die fachliche und technische Verantwortung für Tests, Einsatz und Freigabe im produktiven System bleibt natürlich beim Betreiber des Systems.

## Entwicklung / Hinweise

- Version `0.3.3`
- Branding im Repository enthalten
- HACS-kompatible Struktur
- lokale Push-Architektur statt Dauerpolling

Pull Requests, Issues und Verbesserungsvorschläge sind willkommen.
