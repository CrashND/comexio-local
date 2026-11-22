# COMEXIO Local

![COMEXIO Local](docs/images/comexio-local-logo.png)

**Dein COMEXIO IO-Server in Home Assistant – lokal, ohne Cloud und ohne ständige Statusabfragen.**

COMEXIO Local erkennt die vom IO-Server bereitgestellten Geräte und Kanäle. Zustandsänderungen können über lokale Webhooks direkt in Home Assistant ankommen. Bestehende COMEXIO-Steuerungen bleiben erhalten.

**Aktuelle Version:** 0.4.12

> **Status:** Unabhängiges Community-Projekt in aktiver Entwicklung. Neue Funktionen zunächst kontrolliert testen.

## Was kann COMEXIO Local?

| Bereich | Funktionen |
| --- | --- |
| **Licht & Ausgänge** | Relais erkennen, schalten und Zustände per Push zurückmelden |
| **Rollläden** | Öffnen, schließen und Positionen steuern – mit vorhandenen Soll-/Ist-Merkern |
| **Eingänge & Sensoren** | Taster, Türkontakte, Bewegungs- und Präsenzsensoren einbinden |
| **Geräte & Entitäten** | Erkennung manuell aktualisieren, Erweiterungen zuordnen, Bereiche und Namen verwalten |
| **Push & Rückmeldungen** | Empfangene EnOcean-Ereignisse, Eingangs-Push-Status und gezielte Reparaturen ansehen |
| **Diagnose & Wartung** | Eigenständigen Neuaufbau vorbereiten und Namen kontrollieren |

**Wichtig:** Die Integration verändert beim Installieren keine COMEXIO-Logikpläne. Push-Verbindungen werden erst nach ausdrücklicher Bestätigung eingerichtet.

## Schnellstart

1. Unter **Einstellungen → Marketplace** das Repository [`CrashND/comexio-local`](https://github.com/CrashND/comexio-local) als benutzerdefiniertes **Integrations-Repository** hinzufügen (bei älteren Home-Assistant-Versionen über HACS).
2. **COMEXIO Local** installieren und Home Assistant neu starten.
3. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** COMEXIO Local auswählen und den IO-Server verbinden.

Danach kannst du unter **COMEXIO Local → Konfigurieren** fünf native Home-Assistant-Bereiche öffnen: **Verbindung**, **Geräte & Entitäten**, **Eingänge & Sensoren**, **Push & Rückmeldungen** und **Diagnose & Wartung**. Die Verbindung kann dort nach Kontrolle angepasst werden; eine schon genutzte COMEXIO-Web-IO-Zieladresse wird nicht stillschweigend mitgeändert.

## Dokumentation

- **[Benutzerhandbuch](docs/benutzerhandbuch.md)** – Einrichtung, Licht, Rollläden, EnOcean und typische Bedienabläufe.
- **[Technische Dokumentation](docs/technik.md)** – Architektur, Webhooks, Ressourcenverwaltung und Sicherheitsmechanismen.
- **[Änderungsverlauf](CHANGELOG.md)** – Neuerungen und Fehlerbehebungen nach Version.


## Hinweis zu v0.4.12 (Testkandidat)

Die COMEXIO-Einstellung **„Binär invertiert“** bei EnOcean-Kontakten wird als
`InOutputTypeId=24` erkannt. Die fünf bestehenden, invertierten Türkontakte
bleiben damit ebenso im Katalog wie neue, normal-binäre Kontakte (`23`).
Eine Umschaltung in COMEXIO erfordert **keine** Neuverknüpfung und erhält
die HA-Entitätskennung; nach der Umschaltung lassen sich die aktuellen
COMEXIO-Metadaten und Zustände unter **Konfigurieren → Geräte & Entitäten →
Erkennung jetzt aktualisieren** neu einlesen. COMEXIO liefert bereits den
interpretierten `0/1`-Wert: Die Integration invertiert wegen Typ `24` **nicht
noch einmal**. Die vorhandene zusätzliche HA-Invertierung ist davon unabhängig.

Ein echter Türkontakt-Live-Push nach dem Update und die Einrichtung des neuen
`EI11_CO` sind noch zu prüfen. Bestehende Kontaktpläne und Web-IO-Befehle
müssen nicht erneut bereinigt werden.

## Hinweis zu v0.4.11 (historischer Bugfix)

Nach einem EnOcean-Clean-Cut kann die COMEXIO-Web-IO-Befehlsliste als leeres
Array `[]` statt als leeres Objekt `{}` vorliegen. Diese exakt leere
Listenform wird jetzt in der Eingangs-Push-Vorschau akzeptiert. Nichtleere
Listen und unbekannte Strukturen bleiben gesperrt. Die Diagnose nennt
Strukturtyp und ggf. Eintragszahl, aber keine Befehlsinhalte oder Webhooks.
Ob der IO-Server 2G nach der Bereinigung genau `[]` geliefert hat, ist bisher
nicht nachgewiesen. Die v0.4.11-Vorschau und der typbasierte Sync wurden anschließend auf dem IO-Server erfolgreich ausgeführt; die automatische Türkontakt-Rückmeldung blieb offen.

## Wichtige Hinweise

- **Rollläden** benötigen ein zusammengehöriges Positionsmerker-Paar `R_<Name>_soll` und `R_<Name>_ist`. Die Integration legt diese Merker nicht selbst an.
- **EnOcean-Sensoren** erscheinen am bestehenden Home-Assistant-Gerät „EnOcean“. Für Pushs werden die Signale nach **Taster, Kontakte, Bewegung, Helligkeit, Versorgung** und ggf. weitere analoge/digitale Signale in gemeinsame Logikpläne gruppiert; nicht mehr je EnOcean-Teilnehmer. Bestehende alte `CL Eingänge EnOcean EI...`-Pläne werden **nicht** automatisch gelöscht und blockieren den neuen Aufbau bis zur gezielten manuellen Bereinigung. Die gemeinsame Eingangs-Web-IO-Klasse darf dabei nicht pauschal entfernt werden.
- **Push-Prüfung:** Eine abgeschlossene COMEXIO-Topologieprüfung ist kein Live-Funktionstest. Der neue Menüpunkt „Letzte EnOcean-Ereignisse“ zeigt tatsächlich in HA empfangene Signale aus dem flüchtigen Ereignisjournal, ohne zusätzliche COMEXIO-Abfragen.
- **Konfigurationsänderungen** am COMEXIO-Server werden nicht ungefragt übernommen. Für schreibende Push-Aufträge sind Vorschau und Bestätigung vorgesehen.
- **Binäre Eingänge** können in Home Assistant einzeln invertiert werden, beispielsweise bei Türkontakten mit umgekehrter Polarität. Die COMEXIO-Rohwerte und Push-Ereignisse bleiben unverändert.
- **Geräteinformationen**: Der IO-Server erhält Firmware, Modell und Seriennummer aus der echten System-Info-Seite (für COMEXIO OS 11.1.5 praktisch bestätigt). Physische Erweiterungen erhalten ihren Gerätenamen, den über den von COMEXIO gelieferten `TypeId` ermittelten Produkttyp und eine geprüfte Seriennummer aus der Modulkonfiguration. Bekannt sind IO-Extension, Universal-Aktor, Doorstation und EnOcean-Bridge; bei unbekannten Typen wird kein Modell erfunden. Eine Erweiterungs-Firmware erscheint nur, wenn COMEXIO sie ausdrücklich pro Gerät liefert. Bereits erkannte Metadaten bleiben bei einem vorübergehend fehlgeschlagenen optionalen Abruf erhalten.
- **Doorstation** wird als physisches COMEXIO-Gerät mit Modell und Seriennummer erkannt. Die eigentlichen Kamera- und Intercom-Funktionen sind noch nicht integriert.

## Mitmachen & Kontakt

Fehler melden oder Ideen vorschlagen: **[GitHub Issues](https://github.com/CrashND/comexio-local/issues)**.

Entwicklung und Praxistests: **CrashND** · KI-gestützte Konzeption, Code und Dokumentation: **ChatGPT (OpenAI)**.

Die frühere [COMEXIO-Integration von kayl-codes](https://github.com/kayl-codes/homeassistant-comexio) diente als technische Referenz.

## Markenhinweis

**COMEXIO** ist eine Marke des jeweiligen Rechteinhabers. Die Rechte am Namen **COMEXIO** sowie an zugehörigen Marken- und Produktkennzeichen verbleiben beim Hersteller beziehungsweise den jeweiligen Rechteinhabern. Die Bezeichnung wird hier ausschließlich verwendet, um die Kompatibilität mit COMEXIO-Geräten zu beschreiben.

**COMEXIO Local** ist ein unabhängiges, inoffizielles Community-Projekt und steht in keiner geschäftlichen Verbindung zum Hersteller. Es wird weder vom Hersteller noch von Home Assistant offiziell entwickelt, unterstützt oder zertifiziert.
