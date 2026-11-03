# COMEXIO Local v0.3.3 – Push-Reparatur und sichere Einrichtung

**Tag:** `v0.3.3`  
**Zielbranch:** `main`  
**Commit-Nachricht:** `feat: Push-Reparaturdialog und gedrosselte Einrichtung für v0.3.3`

## Neue Funktionen

- Mehrstufiger Home-Assistant-Dialog über **COMEXIO Local → Konfigurieren** zur Auswahl einzelner, mehrerer oder aller Licht-/Rollladenquellen.
- Rein lesende **Reparaturvorschau** mit COMEXIO-Adresse, vorhandenen Komponenten und geplanten Änderungen.
- Nach ausdrücklicher Bestätigung und Backup-Hinweis: fehlende Web-IO-Befehle und Quellverbindungen gezielt ergänzen.
- **Geführter Neuaufbau** vorhandener, aber nicht funktionierender Web-IO-Befehle: zunächst manuelle Entfernung des betreffenden Bausteins/Befehls; anschließend automatisches Wiederanlegen der fehlenden Komponenten.
- **Langsamere Initialisierung:** Befehle einzeln mit konfigurationsseitigem Mindestabstand von 1,25 s und zusätzlicher Lesekontrolle anlegen.
- Freundlichere Namen für **neu** angelegte Web-IO-Komponenten; alte `CL...`-Namen bleiben unverändert und kompatibel.
- Diagnosesensor für die Integrationsversion und erweiterte Geräteinformationen.

## Sicherheit und Einschränkungen

- Keine automatischen Schreibzugriffe beim Start; keine zyklischen COMEXIO-GETs.
- Keine automatische Massenlöschung bestehender COMEXIO-Komponenten. Bereits verknüpfte Befehle werden in dieser Version **nicht automatisch gelöscht/ersetzt**, da die Lösch-API der verwendeten Firmware noch nicht hinreichend abgesichert ist.
- Eine Reparatur prüft Eigentümerschaft, Zieladresse, bekannte Befehlsparameter und Topologie vor der Ausführung erneut. Bei Konflikten wird abgebrochen.
- Nach COMEXIO-Änderungen können betroffene Push-Pläne erneut aktiviert werden; die Logik ist deshalb nur nach Backup und bewusster Freigabe zu verändern.
- Das fehlende HACS-Symbol bei benutzerdefinierten Integrationen ist ein weiterhin bestehendes Problem des HACS-Frontends; die lokalen Brand-Dateien bleiben enthalten.

## Teststatus

- 29 automatisierte Offline-Tests erfolgreich.
- Home-Assistant-Oberfläche und COMEXIO-Firmware 11.1.5 sind **noch nicht live mit v0.3.3 validiert**.
- Zuerst einzelne bekannte Quelle mit Vorschau testen, nicht sofort alle 29 bearbeiten.

## Credits

**Projekt:** CrashND  
**Generative KI-Unterstützung:** ChatGPT (OpenAI)  
**Technische Referenz:** [homeassistant-comexio von kayl-codes](https://github.com/kayl-codes/homeassistant-comexio)
