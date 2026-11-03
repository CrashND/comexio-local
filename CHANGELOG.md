## 0.3.0 - COMEXIO Push Rueckkanal Diagnose (Entwicklung)

- Lesende Aktion `comexio_local.push_diagnose` mit Antwort und Diagnosesensor.
- Pruefung der aktuellen COMEXIO-LAN-Zieladresse, Webhook-Pfade, Web-IO-Kommandos,
  eigenen aktiven Logikplaene und tatsaechlichen Quelle-zu-Web-IO-Verbindungen.
- Erkennung veralteter Zieladressen und veralteter Callback-Pfade; kein automatisches
  Ueberschreiben und keine unsichtbare Massen-Reparatur.
- `configure_push` prueft vor dem Schreiben auf bekannte Konflikte und nach der
  Einrichtung einmalig den Zustand. Erstellung weiterhin nur nach Backup und
  ausdruecklichem `confirm: true`.
- Diagnose fuer empfangene und abgelehnte Webhook-Ereignisse; lokale Payload-Grenze.
- Bestehende Licht- und Rollo-Steuerung unveraendert; kein zyklisches Polling.
- 14 Offline-Unit-Tests. COMEXIO 2G / HAOS Laufzeittest weiterhin ausstehend.

# Änderungsprotokoll

## 0.2.0 — Architekturwechsel

- Feste Ausgangsliste entfernt; dynamisches Einlesen der aktiven COMEXIO-IOs und Merker.
- Raumplan-Kontext und Erkennung der IO-Signaltypen (Licht / Motorrelais / unbekannt) ergänzt.
- Dynamische Cover-Entitäten anhand existierender Soll-/Ist-Merkerpaare.
- Periodische Statusabfragen vollständig entfernt.
- Echtzeit-Rückmeldung über lokal geschützten Webhook und gezielte Web-IO-Kommandos.
- COMEXIO-Web-IO-Bereitstellung ausschließlich nach ausdrücklicher Backup-Freigabe über HA-Aktion, keine automatische Schreibzugriffe beim Start.
- Einmalige Statusinitialisierung und gezieltes Refresh nach Konfigurationsänderung.
- Aktuelle Statusanzeige nach HA-Schaltbefehlen durch einmaligen GET überprüft.
- Inkrementelle, eigene COMEXIO-Push-Pläne statt pauschaler Merker-Synchronisierung.
- Offline-Tests zu dynamischem Discovery, Marker-Paaren, TCP, Lua-Payloads und Plan-Referenzen.

**Vorsicht:** noch nicht live auf COMEXIO IO-Server 2G / HAOS geprüft. Version 0.2.0 ist ein umfassender Entwicklungsstand und keine stabile produktive Freigabe.
