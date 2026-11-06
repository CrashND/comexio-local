# Änderungsprotokoll

## 0.3.6.3.1 – Home Assistant 2026.11 / Marketplace

**Geändert**
- Gerätemetadaten mit `DeviceInfo(...)` statt Dictionary bereitstellen; Firmware nur bei eindeutig erkanntem Wert setzen.
- Installation und Hinweise in der README an den integrierten Marketplace anpassen.

**Unverändert**
- Keine Entity-ID-, Geräte-ID- oder Namensmigration; bestehende Push-Verbindungen, Webhooks und COMEXIO-Konfiguration bleiben unverändert.
- Options-Flow-Aufrufe verwenden bereits `step_id`; keine unnötige Änderung der weiterhin unterstützten Custom-Integration-Setup-/Unload-Rückgaben.
- Eingangs-Push aus 0.3.6.3 bleibt auf Firmware 11.1.5 live zu testen.


## 0.3.6.3 – Dynamische Eingangs-Push-Unterstützung (Praxistest ausstehend)

**Neu**
- Physische COMEXIO-`I`-Eingänge und ausdrücklich digital verwendete `AI`-Eingänge separat per Web-IO-Push anbinden.
- Auswahl als Taster (Drücken/Loslassen) oder rastender Schalter (Ein/Aus); eigene `binary_sensor`-Entitäten und Ereignisse `comexio_local_input`.
- Gesonderte Eingangs-Web-IO-Klasse, gesonderte eigene Logikpläne, lesende Vorschau mit Fingerabdruck und Backup-Freigabe.

**Unverändert**
- Bestehende 30 Licht-/Rollladen-Push-Verbindungen, COMEXIO-Raum- und Zentralpläne sowie der sichere Neuaufbau.
- Keine automatische Doppeldruck-/Langdruckerkennung; die COMEXIO-Logik-Ausgänge bleiben für eine spätere Erweiterung.

**Hinweis**
- Live-Übertragung kurzer Tastimpulse, insbesondere über `AI`, muss auf COMEXIO 11.1.5 getestet werden.


## 0.3.6.2 – Push-Neuaufbau stabilisiert

**Geändert**
- Unnötige vollständige COMEXIO-Abfragen während des Neuaufbaus durch einen lokalen Arbeitsstand ersetzt; Abschlussprüfung bleibt erhalten.
- Vor dem Fortsetzen Prüfung der vorhandenen Verbindungen einschließlich möglicher Teiländerungen beim fehlgeschlagenen Schritt.
- Fortschrittsanzeige und Zeitstempel des letzten abgeschlossenen Schritts verbessert; mindestens 2 Sekunden zwischen Konfigurations-Schreibzugriffen bleiben erhalten.

**Behoben**
- Vorübergehende HTTP-500-/502-/503-/504-Fehler beim Einlesen von Plänen werden begrenzt wiederholt.
- Bereits abgeschlossene Push-Verbindungen werden bei einer sicheren Wiederaufnahme nicht neu angelegt.

**Hinweis**
- Kein automatisches Löschen bestehender CL-Ressourcen; Hardware-Praxistest der Wiederaufnahme steht aus.


## 0.3.6.1 – Push-Verwaltung und Web-IO-Korrektur (Entwicklungsstand)

**Neu**
- Push-Reparatur, Neuaufbau und Fortschritt in einem Menü zusammengefasst.
- Neue Web-IO-Klasse `CL Push Home Assistant` und verständliche CL-Bezeichnungen.

**Geändert**
- Web-IO-Import: alternative Firmware-Antworten und vorhandene Basistypen berücksichtigen; Ergebnis in COMEXIO gegenprüfen.
- Statusmeldungen und Vorschau verständlicher; Wiederaufnahme eines fehlgeschlagenen Auftrags bleibt möglich.

**Weiter offen**
- Automatisches Löschen bestehender CL-Push-Komponenten; bis zur Verifizierung des API-Löschaufrufs nur manuelle Bereinigung.
- Praxistest auf dem COMEXIO IO-Server 2G mit Firmware 11.1.5 steht aus.


## 0.3.5 — Konfigurierbarkeit und manueller Abgleich (Teststand)

- Rollladenpositionen und Fahrbefehle global bzw. pro Rollladen invertierbar; bestehender Standard bleibt bis zur Änderung erhalten.
- Manueller Typwechsel für physische Q-Ausgänge: Licht, Schalter oder lesbarer Statussensor mit Vorschau, Sicherheitswarnung und dauerhafter Konfiguration.
- COMEXIO-Konfiguration über einen neuen Dialog manuell neu einlesen; vor dem Aktualisieren von Home Assistant werden hinzugefügte, entfernte und umbenannte Quellen angezeigt.
- Erkanntes Entitätstypverhalten bleibt bei COMEXIO-Umbenennungen geschützt; ein Domänenwechsel erfordert eine bestätigte Klassifizierung.
- Bereichsvergleich auf vollständige Namen beschränkt (Umlaute/ae, oe, ue und Groß-/Kleinschreibung), keine Geschosspräfix- oder Abkürzungsregeln.
- README auf den aktuellen Funktionsumfang gekürzt; Release-Texte und interne Projektstände bleiben außerhalb des Repositorys.
- Offline-Tests erweitert; Live-Validierung auf HAOS/COMEXIO steht noch aus.


## 0.3.4 - Bereichszuordnung und sichere Namensvorschau (Entwicklungsstand)

- Menue **Konfigurieren -> Bereichsvorschlaege**: prueft eindeutige Uebereinstimmungen zwischen COMEXIO-Raumplannamen und vorhandenen Home-Assistant-Bereichen.
- **Manuelle Bereichszuordnung** fuer eine oder mehrere Licht-/Rollladenentitaeten; vorhandene explizite Bereichszuordnungen bleiben ohne bewusste Freigabe unangetastet.
- Rein lesende Vorschau vor dem Speichern, mit Fingerabdruck gegen zwischenzeitliche Aenderungen; kein COMEXIO-Schreibzugriff, keine Entity-ID-Migration.
- Neue Push-Ressourcen erhalten CL-Namen wie `CL Licht Buero E2/Q2`, `CL Rollladen Buero M85`, `CL Push E2`.
- Alte kryptische CL-Namen und die HA-Namen aus 0.3.3 werden parallel erkannt, um Push-Diagnose und Reparatur nicht zu unterbrechen.
- **Namensmigration vorhandener COMEXIO-Komponenten vorerst nur als Vorschau**: automatische Umbenennung aus Sicherheitsgruenden ausgesetzt, bis der API-Schreibzugriff auf Firmware 11.1.5 verifiziert ist.
- Dynamische Raumerkennung blendet eigene CL-Push-Plaene als Raumquellen aus.
- 42 automatisierte Offline-Tests erfolgreich; Home-Assistant-Options-Flow und Hardware weiterhin live zu validieren.

## 0.3.3 — Kontrollierte Push-Reparatur und langsame Einrichtung (Entwicklung)

- HA-Konfigurationsdialog **Konfigurieren → Push-Verbindungen prüfen und reparieren** mit Mehrfachauswahl und lesender Vorschau.
- Gezieltes, bestätigungspflichtiges Wiederherstellen fehlender Web-IO-Befehle, Verknüpfungen und eigener Push-Pläne.
- Sicherheitsprüfungen: aktuelle Konfigurationssicherung, Topologie-Fingerabdruck, Eigentümerprüfung, Mehrdeutigkeiten und verwaiste Verweise; ohne bestätigte Vorschau keine Änderungen.
- Geführter Neuaufbau bereits vorhandener, aber nicht sendender Quellen; automatische Löschung weiterhin gesperrt, bis die Lösch-API verifiziert ist.
- Neue COMEXIO-Web-IO-Kommandos einzeln anlegen, mindestens 1,25 s zwischen Schreibzugriffen plus Beruhigungszeit und sofortige Lesekontrolle.
- Lesbarere Namen für **neue** Befehle und Pläne; vorhandene CL-Namen werden erkannt und nicht unkontrolliert umbenannt.
- Eigene Diagnose-Entität für Integrationsversion, Hersteller/Modell und lokale Konfigurationsadresse; Firmware nur aus eindeutig auslesbaren Daten.
- Release-Dokumentation für GitHub/HACS einschließlich Hinweis auf das weiterhin bestehende externe HACS-Branding-Problem.
- 29 Offline-Tests erfolgreich; Live-Hardwaretest und Home-Assistant-UI-Test ausstehend.

## 0.3.2 — Ereignisprotokoll pro Push-Quelle (Entwicklung)

- Neuer Diagnosesensor `COMEXIO Push Ereignisprotokoll` mit den letzten 12 akzeptierten Meldungen und Quellenzählung.
- Neue rein lesende Home-Assistant-Aktion `comexio_local.get_push_events` mit bis zu 80 Ereignissen, Empfangszeit (UTC), Quelle, Wert und Zuordnung zur HA-Entität.
- Erfasst Wiederholungen identischer Zustände getrennt von Änderungen gegenüber dem zuletzt in Home Assistant bekannten Wert.
- Für jede akzeptierte Meldung wird das interne HA-Ereignis `comexio_local_push` ausgelöst; keine HTTP-Zugangsdaten werden gespeichert.
- Journal ausschließlich im Arbeitsspeicher, begrenzt auf 80 Einträge. Wird beim Neuladen der Integration zurückgesetzt.
- Kein Polling, keine Änderung am Web-IO-/COMEXIO-Setup, Licht-/Rollo-Steuerung unverändert.
- 20 Offline-Tests erfolgreich. Live-Funktion der neuen Diagnose auf HAOS noch zu prüfen.

## 0.3.1 — Branding, README-Überarbeitung, Push-Diagnose

- Neues Branding für **COMEXIO Local** integriert.
- Home-Assistant-Brandingdateien unter `custom_components/comexio_local/brand/` ergänzt.
- GitHub-/Dokumentationsgrafiken unter `docs/images/` ergänzt.
- README grundlegend überarbeitet und auf den aktuellen Projektstand gebracht.
- Transparenzhinweise ergänzt: Referenz auf die frühere Integration von **kayl-codes** und Offenlegung der Unterstützung durch generative KI bei Konzeption, Dokumentation und Codeerstellung.
- Push-Diagnose aus 0.3.0 bleibt enthalten; bestehende Licht- und Rollladensteuerung unverändert.

## 0.3.0 — COMEXIO Push Rückkanal Diagnose (Entwicklung)

- Lesende Aktion `comexio_local.push_diagnose` mit Antwort und Diagnosesensor.
- Prüfung der aktuellen COMEXIO-LAN-Zieladresse, Webhook-Pfade, Web-IO-Kommandos,
  eigenen aktiven Logikpläne und tatsächlichen Quelle-zu-Web-IO-Verbindungen.
- Erkennung veralteter Zieladressen und veralteter Callback-Pfade; kein automatisches
  Überschreiben und keine unsichtbare Massen-Reparatur.
- `configure_push` prüft vor dem Schreiben auf bekannte Konflikte und nach der
  Einrichtung einmalig den Zustand. Erstellung weiterhin nur nach Backup und
  ausdrücklichem `confirm: true`.
- Diagnose für empfangene und abgelehnte Webhook-Ereignisse; lokale Payload-Grenze.
- Bestehende Licht- und Rollo-Steuerung unverändert; kein zyklisches Polling.
- 14 Offline-Unit-Tests. COMEXIO 2G / HAOS Laufzeittest weiterhin ausstehend.

## 0.2.0 — Architekturwechsel

- Feste Ausgangsliste entfernt; dynamisches Einlesen der aktiven COMEXIO-IOs und Merker.
- Raumplan-Kontext und Erkennung der IO-Signaltypen (Licht / Motorrelais / unbekannt) ergänzt.
- Dynamische Cover-Entitäten anhand existierender Soll-/Ist-Merkerpaare.
- Periodische Statusabfragen vollständig entfernt.
- Echtzeit-Rückmeldung über lokal geschützten Webhook und gezielte Web-IO-Kommandos.
- COMEXIO-Web-IO-Bereitstellung ausschließlich nach ausdrücklicher Backup-Freigabe über HA-Aktion, keine automatischen Schreibzugriffe beim Start.
- Einmalige Statusinitialisierung und gezieltes Refresh nach Konfigurationsänderung.
- Aktuelle Statusanzeige nach HA-Schaltbefehlen durch einmaligen GET überprüft.
- Inkrementelle, eigene COMEXIO-Push-Pläne statt pauschaler Merker-Synchronisierung.
- Offline-Tests zu dynamischem Discovery, Marker-Paaren, TCP, Lua-Payloads und Plan-Referenzen.
