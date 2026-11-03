# COMEXIO Local 0.3.2

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

**Aktueller Praxisbefund (03.11.2026):** Die vom System erzeugten 29 Web-IO-Quellen sind verdrahtet. Manuelle Web-IO-Tests erreichen Home Assistant. Das Duschbad meldet nach Wandtaster-Bedienung Zustandswechsel; beim Büro fehlt diese Rückmeldung trotz sichtbarer Zustandsänderung im COMEXIO-Plan. Die Ursache ist noch nicht geklärt. Die neue Diagnose soll diesen Unterschied sichtbar machen, ohne weitere COMEXIO-Umbauten.

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

- Version `0.3.2`
- Branding im Repository enthalten
- HACS-kompatible Struktur
- lokale Push-Architektur statt Dauerpolling

Pull Requests, Issues und Verbesserungsvorschläge sind willkommen.
