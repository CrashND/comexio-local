# COMEXIO Local – Benutzerhandbuch

**COMEXIO mit Home Assistant verbinden, Geräte bedienen und Zustände live empfangen.**

Dieses Handbuch richtet sich an Anwender von Home Assistant. Du musst dafür weder Python kennen noch COMEXIO-Logikpläne programmieren können. Für bestimmte Funktionen – insbesondere Rollläden – sind allerdings passende Einstellungen auf dem COMEXIO-Server erforderlich.

> **Stand: v0.4.5.** Die zugrunde liegende Push-Logik entspricht der praktisch geprüften v0.4.4; die neuen Menü- und Statusdialoge sind im v0.4.5-Quellcode umgesetzt, aber noch nicht in Home Assistant praktisch getestet.

## Inhalt

1. [Installation und erste Verbindung](#1-installation-und-erste-verbindung)
2. [Geräte und Entitäten verstehen](#2-geräte-und-entitäten-verstehen)
3. [Licht und Ausgänge](#3-licht-und-ausgänge)
4. [Rollläden](#4-rollläden)
5. [EnOcean, Türkontakte und Bewegungsmelder](#5-enocean-türkontakte-und-bewegungsmelder)
6. [Push-Verbindungen einrichten und prüfen](#6-push-verbindungen-einrichten-und-prüfen)
7. [Bereiche und Einstellungen](#7-bereiche-und-einstellungen)
8. [Synchronisierung, Diagnose und typische Fragen](#8-synchronisierung-diagnose-und-typische-fragen)

## 1. Installation und erste Verbindung

**Voraussetzungen:** Ein erreichbarer COMEXIO IO-Server, dessen Administrator-Zugangsdaten sowie eine laufende Home-Assistant-Installation. Für Push muss COMEXIO die angegebene Home-Assistant-Adresse im lokalen Netz erreichen können.

1. Öffne in Home Assistant **Einstellungen → Marketplace** und füge `https://github.com/CrashND/comexio-local` als benutzerdefiniertes *Integrations-Repository* hinzu. Bei älteren HA-Versionen erfolgt dies über HACS.
2. Installiere **COMEXIO Local** und starte Home Assistant neu.
3. Öffne **Einstellungen → Geräte & Dienste → Integration hinzufügen → COMEXIO Local**.
4. Trage die IP-Adresse des COMEXIO-Servers, den TCP-Port (üblicherweise `1505`), die Administrator-Zugangsdaten und die für COMEXIO erreichbare Home-Assistant-Push-Adresse ein.
5. Schließe die Einrichtung ab.

Die Integration liest zunächst die vorhandene COMEXIO-Konfiguration. **Durch die Installation allein werden keine Logikpläne oder Web-IO-Befehle angelegt.**

Anschließend findest du die Geräte unter **Einstellungen → Geräte & Dienste → COMEXIO Local**. Über **Konfigurieren** öffnest du die Funktionen der Integration.

## 2. Geräte und Entitäten verstehen

Die Integration trennt *Geräte* und *Entitäten*:

- **Gerät:** Beispielsweise der IO-Server, eine physische IO-Erweiterung oder die EnOcean-Erweiterung.
- **Entität:** Ein einzelnes Licht, ein Taster, ein Türkontakt, eine Messgröße oder ein Rollladen.

Ein Gerät kann deshalb mehrere Entitäten enthalten. Alle erkannten EnOcean-Eingänge erscheinen **unter dem vorhandenen Gerät „EnOcean“**. Es werden keine künstlichen Geräte für `EI1`, `EI2` usw. erzeugt.

Bestehende Namen und Bereiche kannst du wie gewohnt in Home Assistant anpassen. Die technische Kanalzuordnung bleibt davon getrennt.

## 3. Licht und Ausgänge

Erkannte Lichtausgänge werden als schaltbare **Licht-Entitäten** eingebunden. Du kannst sie beispielsweise über ein Dashboard oder eine Home-Assistant-Automation steuern.

Die Rückmeldung des tatsächlichen COMEXIO-Zustands erfolgt über **lokale Push-Verbindungen**. Ohne passende Push-Verbindung ist die Entität zwar möglicherweise sichtbar, erhält aber nicht automatisch jede externe Zustandsänderung.

**Andere Q-Ausgänge:** Unter **Konfigurieren → Geräte & Bereiche → Ausgänge klassifizieren** lässt sich ein geeigneter Ausgang als *Licht*, *Schalter* oder *Statussensor (nur lesen)* behandeln.

> **Achtung:** Die direkte Schaltung eines physischen Ausgangs kann vorhandene COMEXIO-Logik umgehen. Motor- und sicherheitsrelevante Ausgänge sind dafür nicht vorgesehen. Wenn sich durch eine Klassifizierung die Entitätsdomäne ändert (z. B. `sensor` zu `light`), kann sich auch die `entity_id` ändern.

## 4. Rollläden

Damit ein Rollladen als **Cover-Entität** erscheint, müssen in COMEXIO zwei passende Positionsmerker existieren:

| Merker | Aufgabe |
| --- | --- |
| `R_Buero_soll` | Gewünschte Position; mit „Stellung (soll) in %“ verbinden |
| `R_Buero_ist` | Gemeldete Position; mit „Stellung in %“ verbinden |

Die Namen müssen dasselbe Mittelstück enthalten, hier `Buero`. Die Integration erstellt diese Merker **nicht selbst**.

**Positionsrichtung:** In Home Assistant bedeutet `0 %` *geschlossen* und `100 %` *offen*. Falls die COMEXIO-Skala umgekehrt ist, ändere die Zuordnung unter:

**Konfigurieren → Rollläden & Positionen → Positionen für alle Rollläden einstellen**

Alternativ kannst du die Richtung für einen einzelnen Rollladen einstellen. Die Änderung betrifft die Umrechnung in Home Assistant; die COMEXIO-Rollladenlogik bleibt bestehen. Prüfe die Fahrtrichtung vor dem ersten vollständigen Fahrbefehl.

## 5. EnOcean, Türkontakte und Bewegungsmelder

COMEXIO Local übernimmt die von COMEXIO erkannten EnOcean-Eingänge – beispielsweise:

| Signal | Anzeige in Home Assistant |
| --- | --- |
| `EI5_CO` | Tür-/Fensterkontakt |
| `EI3_PIRS`, `EI4_PIRS` | Bewegungs- oder Präsenzsensor, abhängig vom COMEXIO-Signaltyp |
| `EI7_A0`, `EI7_AI` usw. | Tasterkanäle |
| `ILL`, `SVC` | Analoge Messwerte ohne ungeprüfte Einheit |

**Wichtig:** Dass eine Entität unter „EnOcean“ angezeigt wird, bedeutet noch nicht, dass sie Live-Ereignisse empfängt. Dazu muss die **Eingangs-Push-Verbindung** eingerichtet sein (nächstes Kapitel).

Analoge EnOcean-Werte werden derzeit als Rohwerte angezeigt. Für `ILL` und `SVC` sind Skalierung und Einheit nicht allgemein verifiziert. Bei EnOcean-Tastern werden Rohzustände und unterstützte Eingangsereignisse übertragen; Einfach-/Doppel-/Langdruck wird nicht automatisch erfunden.

## 6. Push-Verbindungen einrichten und prüfen

**Push** bedeutet: COMEXIO meldet Zustandsänderungen aktiv an Home Assistant. Eine dauernde Abfrage aller Kanäle ist dafür nicht nötig.

### EnOcean-Sensoren und physische Eingänge anbinden

1. Öffne **COMEXIO Local → Konfigurieren → Push & Eingänge → Eingänge & EnOcean → EnOcean-Sensoren anbinden**.
2. Wähle gezielt die gewünschten Kanäle, zum Beispiel `EI3_PIRS`, `EI4_PIRS` und `EI5_CO`.
3. Öffne die **Vorschau**. Sie liest den geplanten Stand, ohne COMEXIO zu verändern.
4. Prüfe die Angaben und bestätige den Schreibauftrag nur, wenn die im Dialog verlangte **aktuelle COMEXIO-Konfigurationssicherung** vorhanden ist.
5. Sieh den Fortschritt unter **Push & Eingänge → Eingänge & EnOcean → Eingangs-Push-Auftrag anzeigen** nach.
6. Nach dem Abschluss löse einen Sensor gezielt aus und beobachte seinen Zustand bzw. den Verlauf in Home Assistant.

Bei EnOcean wird die Signalart automatisch aus COMEXIO übernommen. Die EnOcean-Auswahl fragt daher **keine Taster-/Schalter-Bedienart** ab. Für physische I-/AI-Eingänge gibt es einen separaten Menüpunkt mit dieser Auswahl.

Die Integration legt eigene Eingangs-Web-IO-Befehle und eigene Eingangs-Logikpläne an. Bestehende Licht- und Rollladen-Push-Pläne werden bei diesem Vorgang nicht neu aufgebaut. Vorhandene, eindeutig passende eigene Web-IO-Befehle können bei einer erneuten bestätigten Einrichtung weiterverwendet werden.

### Auftragsstatus richtig lesen

| Status/Hinweis | Bedeutung |
| --- | --- |
| `running` | Der Auftrag bearbeitet die COMEXIO-Konfiguration. |
| `completed` | Die vorgesehene Einrichtung wurde abgeschlossen und geprüft. |
| `failed` | Der Auftrag wurde gestoppt; die angezeigte Fehlermeldung ist für die Diagnose maßgeblich. |
| `callback_unverified` | Mindestens ein Rücklesewert des Web-IO-Callbacks ist nicht vollständig überprüfbar. Das ist **kein Nachweis eines Übertragungsfehlers**. |

Auch bei `completed` ist ein **echter Sensorwechsel** die entscheidende Funktionsprüfung. In v0.4.5 zeigt der Dialog bei `running` **Aktualisieren** und bei `completed` oder `failed` **Schließen**. Das Aktualisieren startet keinen neuen Auftrag. Die Bedienung dieser Korrektur muss noch in Home Assistant praktisch geprüft werden.

### Wenn Licht oder Rollläden keine Push-Rückmeldungen liefern

Öffne **Push & Eingänge → Licht- & Rollladen-Push → Bestehende Verbindungen prüfen & reparieren**. Wähle zunächst die betroffenen Quellen aus und prüfe die Vorschau.

Der Menüpunkt **„Push-Neuaufbau prüfen“** ist ein eigenständiger, deutlich größerer Eingriff. Verwende ihn **nicht** als erste Maßnahme bei einem einzelnen fehlerhaften Eingang oder EnOcean-Sensor.

## 7. Bereiche und Einstellungen

Unter **Konfigurieren → Geräte & Bereiche** findest du:

- **Bereiche automatisch zuordnen:** Eindeutige Vorschläge auf Basis der vorhandenen Bezeichnungen anzeigen und prüfen.
- **Bereiche manuell zuordnen:** Ausgewählte Licht- und Rollladenquellen einem HA-Bereich zuweisen.
- **Ausgänge klassifizieren:** Geeignete Q-Ausgänge als Licht, Schalter oder Statussensor behandeln.

Die Bereichszuordnung betrifft Home Assistant, nicht die COMEXIO-Logik. Vorhandene individuelle Zuordnungen werden nicht ohne entsprechende Auswahl überschrieben.

## 8. Synchronisierung, Diagnose und typische Fragen

### Ich habe etwas in COMEXIO umbenannt oder geändert

Öffne **Konfigurieren → Wartung & Diagnose → COMEXIO-Konfiguration synchronisieren**. Prüfe die angezeigte Vorschau, bevor du Änderungen in Home Assistant übernimmst. Die physische Kanaladresse ist für die Zuordnung maßgeblich; deine individuellen HA-Einstellungen werden nicht einfach ungefragt ersetzt.

### Die EnOcean-Entität wird angezeigt, reagiert aber nicht

Prüfe zunächst, ob für den betreffenden Kanal ein Eingangs-Push-Auftrag abgeschlossen wurde. **Ein sichtbarer Sensor allein beweist keine aktive Push-Verbindung.** Prüfe danach den Verlauf bei einer realen Zustandsänderung.

### Der Auftrag meldet `completed`, aber ich sehe kein Ereignis

`completed` belegt den Abschluss des Einrichtungsauftrags, nicht automatisch den erfolgreichen Live-Callback. Kontrolliere, ob der gewählte COMEXIO-Kanal tatsächlich einen neuen Zustand meldet, und nutze bei Bedarf die Diagnose der Integration. Starte nicht ungeprüft einen vollständigen Push-Neuaufbau.

### Mein Rollladen fehlt oder fährt in die falsche Richtung

Prüfe zuerst das vollständige Soll-/Ist-Merkerpaar mit identischem Namen. Bei vertauschter Positionsrichtung verwende **Rollläden & Positionen** statt Änderungen an den Motorrelais vorzunehmen.

### Unterstützt COMEXIO Local die Doorstation-Kamera?

Nein. Kamera-Streaming und Intercom der COMEXIO Doorstation gehören derzeit **nicht** zum implementierten Funktionsumfang.

---

**Unterstützung und Fehlermeldungen:** [GitHub Issues](https://github.com/CrashND/comexio-local/issues) · [Zur Projektübersicht](https://github.com/CrashND/comexio-local)

*Dieses Handbuch dokumentiert den bekannten Funktionsstand. Die konkrete Verfügbarkeit einzelner Signale hängt von COMEXIO-Konfiguration, Hardware und Firmware ab.*
