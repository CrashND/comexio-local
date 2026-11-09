# COMEXIO Local

![COMEXIO Local](docs/images/comexio-local-banner.png)

**Lokale Home-Assistant-Integration für COMEXIO IO-Server** – ohne Cloud und ohne regelmäßige Statusabfragen. Sie erkennt COMEXIO-Kanäle dynamisch und überträgt Zustandsänderungen über Web-IO/Webhooks an Home Assistant.

**Aktuelle Version:** 0.4.1 · **Status:** Community-Projekt in Entwicklung; Änderungen zunächst auf dem eigenen System testen.

## Funktionen

| Bereich | Möglichkeiten |
|---|---|
| Licht | Relaisausgänge automatisch erkennen und schalten; Zustandsrückmeldung per Push |
| Rollläden | Vorhandene Soll-/Istpositions-Merker erkennen, Position setzen, öffnen und schließen; Richtung global oder einzeln invertierbar |
| Weitere Ausgänge | Unbekannte Ausgänge als Statussensor anzeigen; Q-Ausgänge bei Bedarf manuell als Licht, Schalter oder Statussensor klassifizieren |
| Physische Eingänge | Digitale I-Eingänge sowie ausdrücklich ausgewählte digitale AI-Eingänge als Taster oder rastende Schalter einbinden; Push-Ereignisse und Binary-Sensor-Zustände |
| Push | Eigene Web-IO-Verbindungen einrichten, gezielt reparieren oder mit gespeichertem Fortschritt vollständig neu aufbauen |
| Diagnose | Ereignisprotokoll mit Quelle, Wert und Zeitpunkt; Quellstatistik und Statussensoren |
| Bereiche | Home-Assistant-Bereiche automatisch bei eindeutigem Namen vorschlagen oder manuell zuordnen |
| COMEXIO-Geräte | Physische Erweiterungen einzeln in der Home-Assistant-Geräteliste erfassen; Anschlüsse dem passenden Gerät zuordnen |
| Synchronisierung | COMEXIO-Konfiguration auf Knopfdruck erneut lesen; Änderungen vor Übernahme anzeigen |
| Bezeichnungen | Eigene Push-Ressourcen verwenden ausschließlich das aktuelle lesbare `CL`-Namensschema. |

Die Integration lässt sich mit Node-RED kombinieren. Bestehende COMEXIO-Raum- und Zentralpläne bleiben unverändert.

### Voraussetzung für die Rollladensteuerung in Home Assistant

Die Integration erkennt einen Rollladen **nur dann als `cover`-Entität**, wenn in COMEXIO **für diesen Rollladen zwei zusammengehörige Positions-Merker (`M`)** vorhanden sind. Sie werden von der Integration **nicht automatisch angelegt**.

- **Sollwert:** `R_<Name>_soll` – mit dem Eingang **„Stellung (soll) in %“** des COMEXIO-Rollladenbausteins verbinden. Home Assistant schreibt darüber die gewünschte Position.
- **Istwert:** `R_<Name>_ist` – mit dem Ausgang **„Stellung in %“** des Rollladenbausteins verbinden. Die Integration empfängt darüber die von COMEXIO berechnete/gemeldete Position.
- **Paarbildung:** Beide Merker müssen denselben `<Name>` verwenden; die Suffixe `_soll` und `_ist` unterscheiden die Richtung. Beispiel: `R_Buero_soll` und `R_Buero_ist`.
- **Wertebereich:** Die Positionswerte werden in Prozent (`0–100`) verwendet. Die Zuordnung zur Home-Assistant-Skala (`100 % = offen`) kann in den Rollladeneinstellungen invertiert werden.

**Ohne ein vollständiges Soll-/Ist-Merkerpaar erzeugt COMEXIO Local für diesen Rollladen keine `cover`-Entität.** Die lokale COMEXIO-Rollladensteuerung über Taster und Motorrelais kann davon unabhängig funktionieren. Einzelne Motorrelais werden von der Integration bewusst nicht als direkt schaltbare Rollladenersatzsteuerung angeboten. Bereits verwendete Merker-IDs sollten nach der Einrichtung nicht unnötig geändert werden, da die Ist-Merker-ID zur stabilen HA-Entitätsidentität gehört.

### Eigenständige COMEXIO-Geräte (v0.4.0)

COMEXIO Local ermittelt physische Erweiterungen **generisch aus den vom IO-Server gelieferten Moduldatensätzen**. IO-Erweiterungen, Universal-Aktoren und Funk-Bridges werden als separate Home-Assistant-Geräte registriert, sofern COMEXIO sie mit einem eigenen `extension`-Datensatz und einer eindeutigen Modul-ID meldet. Auch Erweiterungen ohne aktuell aktive IO-Kanäle können registriert werden.

Physische Licht-, Schalter- und Eingangskanäle werden dem eindeutig zugehörigen Modul zugeordnet. Die bestehenden Home-Assistant-Entity-IDs, Unique-IDs und individuellen Namen/Bereiche werden dabei nicht neu erzeugt oder umbenannt. **Sämtliche Positionsmerker (`M`), daraus abgeleitete Rollläden und die Integrationsdiagnose bleiben am IO-Server.** Bei doppelt gemeldeten oder unlesbaren Modulzuordnungen wird keine Hardwarezuordnung geraten; bestehende Zuordnungen bleiben unangetastet.

EnOcean-Bridge und weitere COMEXIO-Module werden nach demselben Prinzip berücksichtigt. **Separate EnOcean-Funksensoren und ihre Messwerte** lassen sich jedoch nur abbilden, wenn der COMEXIO-Admin-Datenbestand diese Geräte mit eindeutigen Identitäten und auswertbaren Quellen tatsächlich liefert. Eine direkte EnOcean-Integration, das Auslesen bisher unbekannter Firmware-Datenstrukturen oder das Erfinden von Sensoren ist nicht Bestandteil dieses Releases. Die reale Erkennung des konkreten Hardwarebestands ist noch zu prüfen.

### Push-Neuaufbau und aktuelles CL-Namensschema

Der aktuelle Push-Aufbau verwendet ausschließlich diese sichtbaren Namen: `CL Push Home Assistant`, `CL Push IO-Ext-3 Q1-Q18`, `CL Push Rollläden M73-M90`, `CL Licht <Bereich> IO-Ext-3/Q1`, `CL Eingänge Home Assistant`, `CL Eingänge IO-Ext-3 I1-I18` und `CL Eingang IO-Ext-3/I1`. Die interne Home-Assistant-Konfigurationseintrags-ID steht nur im Besitzerkommentar eigener Pläne, nicht in den Namen.

**v0.4.1 erzeugt für jedes neu angelegte Web-IO-Gerät eine eigene, zuvor nicht existierende Befehlsvorlage.** Die Integration übernimmt keine bestehenden Basistypen über ähnliche Namen. Die Geräte-Befehlsliste muss nach dem Import vollständig mit den geplanten Befehlen übereinstimmen; zusätzliche oder nicht eindeutig zugeordnete Befehle stoppen die Anlage vor dem Verknüpfen. Auch die Prüfung bestehender Ressourcen akzeptiert nur aktuelle, exakt zuordenbare Befehle. Inkompatible gespeicherte Neuaufbau-Checkpoints können nicht fortgesetzt werden. Jeder neue Auftrag erfordert eine lesende Vorschau und die vorgesehenen Zustimmungen.

**Bereits auf dem COMEXIO-Server gespeicherte Befehlsvorlagen werden durch das Update nicht gelöscht.** Eine bestätigte Lösch-API für Vorlagen liegt nicht vor. Neu angelegte Geräte verwenden daher eigene, unabhängige Vorlagen. Das Verhalten und die grafische Anzeige sind auf Firmware 11.1.5 noch praktisch zu prüfen.

Der geführte Licht-/Rollladen-Neuaufbau kann nach aktueller Sicherung, Eigentumsprüfung und **separater Löschbestätigung** ausschließlich seine eigenen `CL Push`-Pläne und danach das exklusive Push-Web-IO-Gerät bereinigen. Bestehende Raum-/Zentralpläne, fremde Web-IO-Geräte und die **separate Eingangs-Push-Klasse** bleiben geschützt. COMEXIO-Geräte und ursprüngliche Steuerungslogik werden durch Geräteerkennung niemals bearbeitet.

Beim Neuanlegen von Web-IO-Befehlen sendet die Integration den gesonderten Aktivierungsaufruf. Die grafischen Web-IO-Bausteine werden zuerst angelegt und anschließend über echte Element-IDs verbunden. COMEXIO-Antworten werden nach Schreiboperationen erneut gelesen; ein HTTP 200 allein ist kein Löschbeweis. **Der Neuaufbau und die korrekte grafische Darstellung auf COMEXIO OS 11.1.5 bleiben bis zum realen Praxistest offen.** Ein reines Update führt keine COMEXIO-Schreiboperation aus.

### Home-Assistant-Entitäten vollständig synchronisieren

Der Bereich **Wartung & Diagnose → Konfigurationsänderungen synchronisieren**
liest die COMEXIO-Hardware- und **sämtliche** Logikpläne vor einer
Entitätsbereinigung vollständig. Nicht lesbare Plan-/Hardwaredaten stoppen die
Vorschau, statt vermeintlich entfernte Geräte zu erzeugen. Der Vergleich
berücksichtigt den HA-Entity-Registry-Bestand der **eigenen** Konfigurationsinstanz
und zeigt hinzugefügte, umbenannte, entfernte, umklassifizierte und verwaiste
Entitäten samt physischer Adresse und bisheriger Entity-ID.

**Löschungen erfolgen ausschließlich nach ausdrücklicher Zustimmung in der
Vorschau einschließlich eines eigenen Lösch-Häkchens.** Direkt anschließend
wird der vollständige aktuelle Zustand erneut geprüft. Nur nachweislich dieser
COMEXIO-Local-Instanz gehörende Hardware-Entitätsregistrierungen dürfen entfernt
werden. Normales Discovery beim Start, `refresh_discovery`, Snapshots und Pushs
entfernen **niemals** HA-Entitäten. Fremde Registrierungen und die permanenten
Diagnosesensoren werden nicht angerührt. An COMEXIO wird dabei **nichts** geschrieben.

Beim Plattformwechsel (`light`/`switch`/`binary_sensor`/`cover`) wird die alte
Registry-Entität nach Prüfung entfernt und die Integration zum kontrollierten
Neuaufbau der HA-Plattformen neu geladen. Innerhalb derselben Entitätsdomäne
(z. B. Relais → digitaler Eingang) bleibt die vorhandene Registry-Identität
erhalten. Manuell gesetzte Namen, Bereiche, Icons und Labels werden bei
Domänenwechseln soweit technisch möglich übernommen. **Die alte Entity-ID
kann bei einem Wechsel der HA-Domäne nicht erhalten bleiben.** Betroffene
Automationen und Dashboards müssen gegebenenfalls angepasst werden; Deaktiviert-
und Versteckt-Einstellungen sind nach einem Wechsel zu kontrollieren.

Die separate manuelle Q-Klassifizierung verwendet dieselbe Bestandsprüfung,
beschränkt etwaige Registry-Löschungen jedoch auf **den ausgewählten Ausgang**.
Der Schutz für erkannte Rollladenmotor-Ausgänge bleibt erhalten. Alle dynamischen
Entitäten zeigen jetzt ihre physische COMEXIO-Quelle als Diagnoseattribut
`comexio_anschluss`. Der Code zeigt beim erneuten Öffnen des bereits abgeschlossenen Neuaufbaus einen Abschlussdialog. **Offen:** Ein schon während des Laufs geöffneter Statusdialog kann weiterhin die veraltete Aktion „Aktualisieren“ anzeigen; das ist eine separate UI-Aufgabe.

**Grenzen:** Keine automatische Reparatur von HA-Automationen/Dashboards, keine
transaktionale Registry-Rollback-API. Bei einem unerwarteten Fehler nach einer
teilweisen Löschung wird die bereits erfolgte Anzahl gemeldet; der Vorgang darf
nicht blind erneut bestätigt werden. Die Home-Assistant- und COMEXIO-Live-Tests
dieser neuen Entitätssynchronisierung stehen aus. Die getesteten
Licht-/Rollladen-Push-Verbindungen bleiben unverändert.

## Installation

1. Unter **Einstellungen → Marketplace** das öffentliche Repository `https://github.com/CrashND/comexio-local` als benutzerdefiniertes **Integration**-Repository hinzufügen. In Home Assistant vor 2026.11 stattdessen **HACS** verwenden.
2. **COMEXIO Local** aus dem Marketplace installieren und Home Assistant neu starten.
3. Unter **Einstellungen → Geräte & Dienste** die Integration hinzufügen und die COMEXIO-Verbindung konfigurieren.

Für physische Schaltvorgänge werden Push-Verbindungen benötigt. Ihre Anlage erfolgt **nur nach ausdrücklicher Bestätigung und mit vorhandener COMEXIO-Konfigurationssicherung**.

**Home Assistant 2026.11:** Die Integration verwendet `DeviceInfo` in der von HA 2026.11 unterstützten Form. v0.4.0 teilt die Gerätezuordnung auf, behält dabei aber die bisherigen Entity-IDs und Unique-IDs bei. Gerätebezogene Automationen sollten nach dem Update überprüft werden; bereichs- und entitätsbezogene Anpassungen werden nicht automatisch überschrieben.

## Einstellungen und Wartung

Unter **Einstellungen → Geräte & Dienste → COMEXIO Local → Konfigurieren**:

| Menü | Wirkung |
|---|---|
| **Push & Eingänge** | Physische Taster/Schalter anbinden; Licht-/Rollladen-Push prüfen und reparieren; Neuaufbau, Status und Steuerung. Eigene Vorschau und Backup-Bestätigung vor Änderungen an COMEXIO. |
| **Geräte & Bereiche** | Automatische und manuelle Bereichszuordnung sowie Klassifizierung von Q-Ausgängen als Licht, Schalter oder Statussensor. |
| **Rollläden & Positionen** | Globale Positions-/Fahrbefehls-Invertierung oder individuelle Einstellung pro Rollladen. Nur Home Assistant wird geändert. |
| **Wartung & Diagnose** | Konfigurationsänderungen synchronisieren (mit Vorschau) und das aktuelle CL-Namensschema lesend prüfen. |

**Aktueller Stand v0.4.1:** Push-Namen werden ausschließlich nach dem aktuellen Schema geprüft; die Anlage verwendet keine wiederverwendeten COMEXIO-Basistypen. Checkpoints aus inkompatiblen Versionen werden abgewiesen. Home-Assistant-Entitätskennungen und gespeicherte Webhook-Einstellungen bleiben erhalten. Die Geräteaufteilung führt keine COMEXIO-Schreibzugriffe aus.

**Stabile Planbereiche:** Lichtausgänge werden pro Hardwaremodul nach festen Q-Kanalbereichen (z. B. `Q1-Q18`, `Q19-Q36`) gruppiert; Rollladen-Istpositionsmerker verwenden feste 18er-Merkerbereiche. Eingangspläne verwenden entsprechend I-/AI-Kanalbereiche. Die Zeilenposition innerhalb eines Push-Plans ergibt sich ebenfalls aus der physischen Kanal-/Merker-ID, nicht aus der Erkennungsreihenfolge. Ein COMEXIO-Praxistest der Eingangs-Push-Flanken und der neuen Plannamen bleibt erforderlich.

**Eingangs-Push bei Fehlern:** Schlägt die rein lesende Vorschau fehl, zeigt der Dialog den konkreten COMEXIO-Fehler und behält die Eingangs- und Bedienartauswahl bei. Die Sammelauswahl aller I-Eingänge erfolgt nie automatisch. Die eigentliche Eingangs-Push-Übertragung ist auf COMEXIO-Firmware 11.1.5 noch nicht erfolgreich im Live-Test bestätigt. Die automatische Bereinigung des Licht-/Rollladen-Neuaufbaus betrifft keine Eingangs-Push-Ressourcen.

**Wichtig zur Rollladenrichtung:** In Home Assistant bedeutet `100 %` **offen**. Wenn COMEXIO bei dir `0 = oben/offen` verwendet, aktiviere **global invertieren**. Standardmäßig bleibt die bisherige Zuordnung erhalten, bis du sie bewusst änderst. Prüfe die Fahrtrichtung vor dem ersten HA-Fahrbefehl.

**Wichtig zur Klassifizierung:** Ein Wechsel von `binary_sensor` zu `light` oder `switch` erzeugt eine neue HA-Entitäts-ID mit anderer Domäne. Der Dialog zeigt dies vorher an. Bestehende Automationen oder Dashboards, die die alte ID verwenden, müssen gegebenenfalls angepasst werden. Motorrelais sind von der manuellen Schaltklassifizierung ausgeschlossen. Die Auswahl wird dauerhaft in Home Assistant gespeichert, nicht in COMEXIO.

**Synchronisierung:** Raum- und Anzeigenamen können neu eingelesen werden. Die physische Quelladresse bleibt für die Identifikation maßgeblich. Manuelle Zuordnungen bleiben bestehen. Neue oder entfernte Signale werden angezeigt; ein Wechsel des Entitätstyps erfolgt nicht stillschweigend. Neu erkannte Quellen benötigen gegebenenfalls eigene Push-Verbindungen.

## Home-Assistant-Aktionen

| Aktion | Zweck |
|---|---|
| `comexio_local.refresh_discovery` | Kanäle neu erkennen (direkte Aktion ohne Vorschau) |
| `comexio_local.snapshot_once` | Zustände einmalig per TCP lesen |
| `comexio_local.get_push_events` | Letzte empfangene Push-Ereignisse und Quellenstatistik |
| `comexio_local.push_diagnose` | Web-IO-Befehle und Verbindungen prüfen |
| `comexio_local.preview_push_repair` | Vorschau für ausgewählte Quellen |
| `comexio_local.repair_push` | Fehlende Komponenten nach Bestätigung ergänzen |
| `comexio_local.configure_push` | Eigene Push-Pläne/Web-IO-Befehle nach Bestätigung einrichten |
| `comexio_local.preview_push_rebuild` | Eigenen Push-Bestand und Neuaufbau prüfen (lesend) |
| `comexio_local.start_push_rebuild` | Bestätigten Neuaufbau vorbereiten/starten |
| `comexio_local.get_push_rebuild_status` | Checkpoint, Prozent und Zeit abrufen |
| `comexio_local.control_push_rebuild` | Neuaufbau pausieren, fortsetzen oder abbrechen |

**Eingänge:** Neue Eingänge werden separat in der Web-IO-Klasse **`CL Eingänge Home Assistant`** und in eindeutigen Plänen wie **`CL Eingänge IO-Ext-3 I1-I18`** angelegt. Die sichtbaren Namen enthalten keine zufälligen Home-Assistant-Konfigurations-IDs. Es gibt **keinen automatischen Massenimport beim Update**. Für den ersten Praxistest ist der digitale Taster `IO-Ext-3/I1` im Flur vorgesehen; er ist in COMEXIO an den Baustein **Multifunktionstaste** angeschlossen. Für die ersten Tests werden nur die rohen Drücken-/Loslassen-Flanken übertragen, noch keine separaten Einfach-/Doppel-/Lang-Ereignisse. Die eigenen Licht-/Rollladen-Push-Komponenten werden beim vereinbarten einmaligen Neuaufbau separat neu angelegt. Die Integration zeigt bestätigte digitale Eingänge als `binary_sensor` an. Automationen können `comexio_local_input` abonnieren (Felder: `source`, `mode`, `action`, `value`, `entity_id`), mit Aktionen `gedrueckt`/`losgelassen` für Taster oder `ein`/`aus` für rastende Schalter. Ein Signal wird nur bei einem wirklichen Zustandswechsel als Bedienereignis publiziert. COMEXIO-Bausteine für *Einfach/Doppel/Lang* sind noch nicht als eigene Ereignisquellen angebunden. Bei AI-Eingängen ist der Digitalmodus ausdrücklich zu bestätigen; andere AI-Eingänge können echte Analogsignale sein. Vor dem Praxistest ist die Übertragung von kurzen Impulsen über Firmware 11.1.5 **nicht bestätigt**.

**Eingangs-Rückleseprüfung:** COMEXIO kann den gespeicherten Web-IO-Callback relativ oder als vollständige URL zurückliefern. Nur dasselbe Home-Assistant-Ziel wird akzeptiert. Wenn COMEXIO die Felder `Data` (Lua-Skript) oder `Parameter` im Konfigurations-Snapshot nicht oder leer liefert, gilt der Befehl ausdrücklich als **nicht vollständig verifiziert**. Die Anlage ist dann nur bei eindeutig zugeordneter eigener Eingangs-Web-IO-Klasse, korrekt benanntem Kommando, passender Zieladresse und übereinstimmenden weiteren Befehlsmetadaten zulässig. Vorhandene, tatsächlich abweichende Lua-Skripte, Callback-Adressen oder Pflichtmetadaten blockieren weiterhin alle Schreibzugriffe. Der erste **Live-Push-Test ist zwingend**, da fehlende Rücklesefelder keinen Funktionsnachweis darstellen.

**Neuaufbau-Performance:** Der Lauf verwendet einen temporären Arbeitsstand statt alle Pläne vor und nach jedem Schritt abzufragen. Ein vollständiger Vergleich erfolgt beim Start, nach einer Unterbrechung und einmal am Ende. Kurzzeitige HTTP-500-/502-/503-/504-Antworten beim **Lesen** von Plänen werden höchstens zweimal mit Wartezeiten wiederholt. Schreibbefehle werden niemals automatisch wiederholt, ohne den COMEXIO-Zustand erneut zu prüfen. Die Fortschrittsentität zeigt Zeitpunkt und Anzahl abgeschlossener Schritte an.

COMEXIO-Statusabfragen erfolgen beim Start, nach Steuerbefehlen oder auf ausdrückliche Anforderung. **Kein zyklisches Polling.** Der TCP-Port ist standardmäßig `1505`.

## Grenzen und Sicherheit

- **Push-Inventar v0.4.1:** Ein vorhandenes Web-IO-Gerät darf nur exakt zuordenbare Befehle enthalten. Eine fehlgeschlagene Prüfung stoppt die Bereinigung und den Neuaufbau. Das Update entfernt keine gespeicherten COMEXIO-Basistyp-Vorlagen. Alle ursprünglichen COMEXIO-Pläne und fremden Web-IOs bleiben geschützt.
- **Checkpoints:** Neuaufbau-Aufträge aus inkompatiblen früheren Versionen können nicht übernommen werden. Jeder neue Neuaufbau benötigt eine frische Vorschau und die vorgesehenen Bestätigungen.
- **Hardware- und EnOcean-Erkennung:** Eigene Geräte entstehen ausschließlich aus expliziten COMEXIO-Hardwaremetadaten. Funkteilnehmer ohne bestätigte, einzeln identifizierbare Datenpunkte werden nicht als Sensoren vorgetäuscht.
- **Gerätezuordnung:** Die Entitäten behalten ihre Entity-IDs. Gerätebezogene Automationen oder Gerätebereiche sollten nach dem Update kontrolliert werden; nichts wird automatisch umbenannt oder gelöscht.
- **Doorstation:** Kamera, Klingel und Intercom sind für v0.5.0 geplant und in v0.4.x nicht implementiert.
- Bei Änderungen der Entitätsdomäne können bestehende Automationen betroffen sein. COMEXIO-Motor- und Sicherheitslogik darf nicht durch direkte Relaisschaltung umgangen werden.
- Release-Versionen, Changelog und Quellcode gehören ins öffentliche Repository. Private Projektstände gehören nicht dazu.

## Projekt und Herkunft

**Entwicklung und Praxistests:** CrashND · **KI-gestützte Konzeption, Code und Dokumentation:** ChatGPT (OpenAI).

Eigenständige Community-Integration; die frühere [COMEXIO-Integration von kayl-codes](https://github.com/kayl-codes/homeassistant-comexio) diente als technische Referenz. Keine offizielle COMEXIO- oder Home-Assistant-Erweiterung.

Fehlerberichte und Beiträge: [GitHub Issues](https://github.com/CrashND/comexio-local/issues).

