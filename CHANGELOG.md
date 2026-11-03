# Änderungsprotokoll

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
