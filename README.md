# COMEXIO Local

![COMEXIO Local](docs/images/comexio-local-banner.png)

**Lokale Home-Assistant-Integration für COMEXIO IO-Server** – ohne Cloud und ohne regelmäßige Statusabfragen. Sie erkennt COMEXIO-Kanäle dynamisch und überträgt Zustandsänderungen über Web-IO/Webhooks an Home Assistant.

**Aktuelle Version:** 0.3.7 · **Status:** Community-Projekt in Entwicklung; Änderungen zunächst auf dem eigenen System testen.

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
| Synchronisierung | COMEXIO-Konfiguration auf Knopfdruck erneut lesen; Änderungen vor Übernahme anzeigen |
| Bezeichnungen | Ausschließlich einheitliche, menschenlesbare `CL`-Klassen-, Plan- und Befehlsnamen; keine alten Namensvarianten oder entry-ID-Kürzel |

Die Integration lässt sich mit Node-RED kombinieren. Bestehende COMEXIO-Raum- und Zentralpläne bleiben unverändert.

### Voraussetzung für die Rollladensteuerung in Home Assistant

Die Integration erkennt einen Rollladen **nur dann als `cover`-Entität**, wenn in COMEXIO **für diesen Rollladen zwei zusammengehörige Positions-Merker (`M`)** vorhanden sind. Sie werden von der Integration **nicht automatisch angelegt**.

- **Sollwert:** `R_<Name>_soll` – mit dem Eingang **„Stellung (soll) in %“** des COMEXIO-Rollladenbausteins verbinden. Home Assistant schreibt darüber die gewünschte Position.
- **Istwert:** `R_<Name>_ist` – mit dem Ausgang **„Stellung in %“** des Rollladenbausteins verbinden. Die Integration empfängt darüber die von COMEXIO berechnete/gemeldete Position.
- **Paarbildung:** Beide Merker müssen denselben `<Name>` verwenden; die Suffixe `_soll` und `_ist` unterscheiden die Richtung. Beispiel: `R_Buero_soll` und `R_Buero_ist`.
- **Wertebereich:** Die Positionswerte werden in Prozent (`0–100`) verwendet. Die Zuordnung zur Home-Assistant-Skala (`100 % = offen`) kann in den Rollladeneinstellungen invertiert werden.

**Ohne ein vollständiges Soll-/Ist-Merkerpaar erzeugt COMEXIO Local für diesen Rollladen keine `cover`-Entität.** Die lokale COMEXIO-Rollladensteuerung über Taster und Motorrelais kann davon unabhängig funktionieren. Einzelne Motorrelais werden von der Integration bewusst nicht als direkt schaltbare Rollladenersatzsteuerung angeboten. Bereits verwendete Merker-IDs sollten nach der Einrichtung nicht unnötig geändert werden, da die Ist-Merker-ID zur stabilen HA-Entitätsidentität gehört.

**Einheitliches Namensschema ab v0.3.6.3.6:** `CL Push Home Assistant`, `CL Push IO-Ext-3 Q1-Q18`, `CL Push Rollläden M73-M90`, `CL Licht <Bereich> IO-Ext-3/Q1`, `CL Eingänge Home Assistant`, `CL Eingänge IO-Ext-3 I1-I18` und `CL Eingang IO-Ext-3/I1`. Die internen HA-Konfigurationseintrags-IDs kommen ausschließlich in Besitzkommentaren vor, niemals in sichtbaren Namen. **Alte CL-Namensvarianten werden nicht mehr berücksichtigt.**

**Einmaliger sauberer Neuaufbau erforderlich:** Vor dem ersten Neuaufbau mit dieser Version müssen die bisher von COMEXIO Local erzeugten **Licht-/Rollladen- und Eingangs-Web-IO-Klassen mit ihren Befehlen sowie die dazugehörigen eigenen CL-Logikpläne** in COMEXIO manuell bereinigt werden. Zuvor eine vollständige COMEXIO-Sicherung erstellen. **Keine Raumpläne, Zentralpläne, physische Kanäle oder fremde Web-IO-Geräte löschen.** Die Integration enthält keine verifizierte API zum automatischen Löschen. Home Assistant muss nicht zwingend neu als Integration eingerichtet werden; gespeicherte alte Neuaufbau-Checkpoints werden sicher beendet, damit keine Arbeit mit veralteten Plannamen fortgesetzt wird. Die Eingangs-Push-Funktion wird danach wie bisher nur auf ausdrückliche Auswahl eingerichtet.

### Web-IO-Befehle werden beim Einrichten aktiviert (v0.3.7)

**Ursache der schwarzen Balken gefunden:** COMEXIO legt automatisch importierte bzw. ergänzte Web-IO-Befehle mitunter **deaktiviert** an. Im COMEXIO-Studio erscheinen diese dann als schwarze Balken mit rotem **„Fehler“**, obwohl die Verdrahtung korrekt ist. Ein vom Betreiber manuell eingeschalteter eigener CL-Befehl wurde unmittelbar korrekt mit Bezeichnung dargestellt. Das frühere Feld `DefaultActive=1` genügt **nicht**, um den tatsächlich gespeicherten Status `Active` zu setzen.

**Ab v0.3.7:** Die regulären freigegebenen Einrichtungswege (Erstinstallation, geführter Neuaufbau mit Wiederaufnahme, gezielte Push-Reparatur und Eingangs-Push-Installation) stellen nach der Befehlsanlage und **vor** dem Verknüpfen sicher, dass nur die ausgewählten eigenen `CL`-Web-IO-Befehle aktiv sind. Der Aktivierungsaufruf verwendet die getrennten COMEXIO-Kennungen für **Web-IO-Eintrag**, **Web-IO-Gerät** und **Web-Befehl**, vergleicht die API-Antwort und liest den gespeicherten Aktivierungszustand erneut aus. Fehlende IDs oder eine abweichende Rückmeldung stoppen weitere Schreibschritte; es wird nicht blind wiederholt. Bereits aktive Befehle werden nicht erneut geschrieben.

Es gibt **keine separate Funktion zum pauschalen Einschalten**, keine automatische Löschung, keine Änderung fremder Web-IO-Befehle und keinen Neuaufbau beim Update selbst. Die reguläre Push-Abschlussprüfung meldet deaktivierte oder nicht auslesbare Befehle statt „bereit“. Der für diese API angenommene vollständige Endpunkt und die Metadaten-Verfügbarkeit müssen auf COMEXIO 11.1.5 noch im Praxistest bestätigt werden; die Tests sind offline simuliert. Für einen ausdrücklich gewünschten sauberen Neuaufbau gelten weiterhin COMEXIO-Sicherung, Vorschau und nur die manuelle Entfernung eindeutig eigener `CL`-Ressourcen.

### Web-IO-Bausteine: getrennte Anlage und Verbindung (v0.3.6.3.10, Testkandidat)

Die im COMEXIO-Editor auf Firmware 11.1.5 aufgezeichnete Anlage eines **korrekt dargestellten** manuellen Web-IO-Bausteins verwendet `POST /admin/function_function_module/add_element/` mit `type=10`, **leerem** `name` und **ohne** `connection`-Parameter. Seine gespeicherte Referenz ist `type=10` mit der ID des ausgewählten Web-IO-Befehls. Ein fehlender Elementname ist deshalb allein kein Darstellungsfehler. Die bisherigen automatisierten Bausteine sendeten dagegen die Verbindung bereits im `add_element/`-Aufruf mit.

**Ab v0.3.6.3.10:** COMEXIO Local legt Quell- und Web-IO-Baustein zunächst ohne eingebettete Verbindung an und speichert den Link anschließend separat über `saveconnection/` mit den **echten** Element-IDs. Der sichtbare `CL ...`-Befehlsname und die eindeutige Referenz bleiben erhalten. Dieser eine Erzeugungsweg wird gemeinsam für Licht-, Rollladen- und Eingangs-Push verwendet. Teilweise abgeschlossene Operationen werden über die bestehenden Graphprüfungen wiedererkannt, statt Elemente blind erneut zu erstellen.

**Historischer Stand von v0.3.6.3.10:** Die damalige Graph-Änderung war ein **gezielter Korrekturversuch**, keine nachgewiesene Behebung der schwarzen Balken. Alle 216 Offline-Tests bestehen; ein Test mit COMEXIO-Firmware 11.1.5 ist noch offen. Das Update allein löst **keinen** Neuaufbau und **keine** automatische Löschung aus. Für dieses Update ist keine pauschale erneute Bereinigung vorhandener CL-Ressourcen erforderlich; der tatsächliche COMEXIO-Zustand bleibt vor einer Neuanlage im bestehenden Vorschauablauf maßgeblich. Bestehende originale Logikpläne bleiben geschützt. Für einen Neuaufbau gelten weiterhin Vorschau und ausdrückliche Bestätigung.

### Web-IO-Befehle im Neuaufbau: v0.3.6.3.9 (historischer Stand)

Der Erstimport eines COMEXIO-Web-IO-Befehls und das anschließende Hinzufügen
weiterer Befehle benötigen weiterhin unterschiedliche COMEXIO-Firmware-APIs.
Beide nutzen jetzt die zentrale, validierte Befehlsdefinition aus
`webio_command.py`. Die **gesendeten Schreibdaten sind gegenüber v0.3.6.3.8
unverändert**; das Refactoring allein beseitigt den Darstellungsfehler nicht.

**Zusätzliche Absicherung im geführten Neuaufbau:** Unmittelbar nach dem ersten
mittels `save_command` angefügten Befehl erfolgt genau **eine** lesende
Konfigurationsprüfung. Sie vergleicht dessen sichtbare Befehlsfelder mit dem
zuvor importierten ersten Befehl sowie mit den erwarteten fachlichen Werten.
Sind die beiden Schreibwege in der COMEXIO-Konfiguration erkennbar verschieden,
stoppt der Neuaufbau **vor dem Anlegen der CL-Logikpläne**. Es werden keine
COMEXIO-Kommandos automatisch gelöscht oder neu gesendet. Fehlen Werte in
beiden Datensätzen, ist deren Gleichheit weiterhin nicht belegt.

**Wichtig: Die schwarzen Web-IO-Balken wurden auch mit v0.3.6.3.8 in COMEXIO
11.1.5 beobachtet. v0.3.6.3.9 ist eine Diagnose- und Absicherungsversion,
keine nachgewiesene grafische Fehlerbehebung.** Vor einem erneuten
vollständigen Neuaufbau COMEXIO sichern und nur eigene CL-Push-Ressourcen
bereinigen. Ein 100-%-Neuaufbau ist kein Ersatz für einen Test der Darstellung
und tatsächlicher Webhook-Meldungen.

### Web-IO-Bausteine im COMEXIO-Logikplan (v0.3.6.3.8; durch v0.3.6.3.10 ersetzt)

Die automatische Anlage eines Web-IO-Bausteins überträgt jetzt den vollständigen, bereits
kanonisch erzeugten `CL ...`-Befehlsnamen zusätzlich im Feld `name` an COMEXIO.
Physische Q-/I-Quellbausteine und Positionsmerker behalten ihr bisheriges Verhalten.
Befehlsreferenzen, Verdrahtung, Push-Ziele und Logikplangruppierung sind unverändert.

**Hintergrund:** Der Betreiber beobachtete nach zwei erfolgreich abgeschlossenen
Licht-/Rollladen-Neuaufbauten (`70/70`) schwarze Balken statt lesbarer
Web-IO-Bausteine in allen automatisch erzeugten CL-Plänen. Manuell angelegte
Web-IO-Bausteine werden normal angezeigt. Der leere Bausteinname ist eine
**im Praxistest widerlegte Fehlerhypothese**: Auch mit dem expliziten
Bausteinnamen sind schwarze Balken auf COMEXIO 11.1.5 aufgetreten.

Bereits vorhandene Bausteine werden durch das Update nicht nachträglich umbenannt.
Ein gewünschter vollständiger Neuaufbau erfordert zuerst eine aktuelle COMEXIO-Sicherung
und die **manuelle, gezielte** Entfernung ausschließlich der eigenen CL-Push-Klasse,
der zugehörigen Befehle und CL-Push-Pläne. COMEXIO Local löscht keine
COMEXIO-Ressourcen automatisch. Originalpläne, fremde Web-IO-Geräte und die
HA-Entitätsregistrierung bleiben unangetastet. Die Eingangs-Push-Ressourcen
werden nur bei ausdrücklich gewolltem separatem Eingangs-Neuaufbau bereinigt.

### Home-Assistant-Entitäten vollständig synchronisieren (v0.3.6.3.7)

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

**Home Assistant 2026.11:** Der Marketplace ersetzt HACS. Home Assistant zeigt Geräte- und Entitätsnamen teilweise kombiniert an. Das Wartungsupdate 0.3.6.3.1 modernisiert die `DeviceInfo`-Rückgabe, ändert aber keine COMEXIO-Gerätekennungen, Entity-IDs, Namen oder Bereichszuordnungen. Bestehende Automationen bleiben von diesem Update unverändert.

## Einstellungen und Wartung

Unter **Einstellungen → Geräte & Dienste → COMEXIO Local → Konfigurieren**:

| Menü | Wirkung |
|---|---|
| **Push & Eingänge** | Physische Taster/Schalter anbinden; Licht-/Rollladen-Push prüfen und reparieren; Neuaufbau, Status und Steuerung. Eigene Vorschau und Backup-Bestätigung vor Änderungen an COMEXIO. |
| **Geräte & Bereiche** | Automatische und manuelle Bereichszuordnung sowie Klassifizierung von Q-Ausgängen als Licht, Schalter oder Statussensor. |
| **Rollläden & Positionen** | Globale Positions-/Fahrbefehls-Invertierung oder individuelle Einstellung pro Rollladen. Nur Home Assistant wird geändert. |
| **Wartung & Diagnose** | Konfigurationsänderungen synchronisieren (mit Vorschau) und das aktuelle CL-Namensschema lesend prüfen. |

**Codebereinigung und Neuanlage v0.3.6.3.6:** Die gemeinsamen Sicherheitsprüfungen aus v0.3.6.3.5 bleiben erhalten. Alte Befehls-, Klassen- und Planbezeichnungen, Migrationsvorschauen und der ID-basierte Fallback für Web-IO-Befehle wurden aus den Erstellungs-/Wiederaufnahmewegen entfernt. Nur das aktuelle Schema wird gelesen und geschrieben. Nach dem Upgrade werden ältere Checkpoints nicht wiederaufgenommen; ein neuer Auftrag erfordert eine neue Vorschau und COMEXIO-Sicherung. Die Home-Assistant-Entitäts-IDs, gespeicherten Webhook-Daten und sonstigen Einstellungen werden nicht automatisch geändert.

**Stabile Planbereiche:** Lichtausgänge werden pro Hardwaremodul nach festen Q-Kanalbereichen (z. B. `Q1-Q18`, `Q19-Q36`) gruppiert; Rollladen-Istpositionsmerker verwenden feste 18er-Merkerbereiche. Eingangspläne verwenden entsprechend I-/AI-Kanalbereiche. Die Zeilenposition innerhalb eines Push-Plans ergibt sich ebenfalls aus der physischen Kanal-/Merker-ID, nicht aus der Erkennungsreihenfolge. Ein COMEXIO-Praxistest der Eingangs-Push-Flanken und der neuen Plannamen bleibt erforderlich.

**Eingangs-Push bei Fehlern:** Schlägt die rein lesende Vorschau fehl, zeigt der Dialog den konkreten COMEXIO-Fehler und behält die Eingangs- und Bedienartauswahl bei. Die Sammelauswahl aller I-Eingänge erfolgt nie automatisch. Die eigentliche Eingangs-Push-Übertragung ist auf COMEXIO-Firmware 11.1.5 noch nicht erfolgreich im Live-Test bestätigt. Die für den sauberen Neuaufbau vereinbarte manuelle Bereinigung betrifft ausschließlich eindeutig eigene CL-Ressourcen.

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

**Eingänge ab v0.3.6.3:** Neue Eingänge werden separat in der Web-IO-Klasse **`CL Eingänge Home Assistant`** und in eindeutigen Plänen wie **`CL Eingänge IO-Ext-3 I1-I18`** angelegt. Die sichtbaren Namen enthalten keine zufälligen Home-Assistant-Konfigurations-IDs. Es gibt **keinen automatischen Massenimport beim Update**. Für den ersten Praxistest ist der digitale Taster `IO-Ext-3/I1` im Flur vorgesehen; er ist in COMEXIO an den Baustein **Multifunktionstaste** angeschlossen. Für die ersten Tests werden nur die rohen Drücken-/Loslassen-Flanken übertragen, noch keine separaten Einfach-/Doppel-/Lang-Ereignisse. Die eigenen Licht-/Rollladen-Push-Komponenten werden beim vereinbarten einmaligen Neuaufbau separat neu angelegt. Die Integration zeigt bestätigte digitale Eingänge als `binary_sensor` an. Automationen können `comexio_local_input` abonnieren (Felder: `source`, `mode`, `action`, `value`, `entity_id`), mit Aktionen `gedrueckt`/`losgelassen` für Taster oder `ein`/`aus` für rastende Schalter. Ein Signal wird nur bei einem wirklichen Zustandswechsel als Bedienereignis publiziert. COMEXIO-Bausteine für *Einfach/Doppel/Lang* sind noch nicht als eigene Ereignisquellen angebunden. Bei AI-Eingängen ist der Digitalmodus ausdrücklich zu bestätigen; andere AI-Eingänge können echte Analogsignale sein. Vor dem Praxistest ist die Übertragung von kurzen Impulsen über Firmware 11.1.5 **nicht bestätigt**.

**Eingangs-Rückleseprüfung:** COMEXIO kann den gespeicherten Web-IO-Callback relativ oder als vollständige URL zurückliefern. Nur dasselbe Home-Assistant-Ziel wird akzeptiert. Wenn COMEXIO die Felder `Data` (Lua-Skript) oder `Parameter` im Konfigurations-Snapshot nicht oder leer liefert, gilt der Befehl ausdrücklich als **nicht vollständig verifiziert**. Die Anlage ist dann nur bei eindeutig zugeordneter eigener Eingangs-Web-IO-Klasse, korrekt benanntem Kommando, passender Zieladresse und übereinstimmenden weiteren Befehlsmetadaten zulässig. Vorhandene, tatsächlich abweichende Lua-Skripte, Callback-Adressen oder Pflichtmetadaten blockieren weiterhin alle Schreibzugriffe. Der erste **Live-Push-Test ist zwingend**, da fehlende Rücklesefelder keinen Funktionsnachweis darstellen.

**Neuaufbau-Performance:** Der Lauf verwendet einen temporären Arbeitsstand statt alle Pläne vor und nach jedem Schritt abzufragen. Ein vollständiger Vergleich erfolgt beim Start, nach einer Unterbrechung und einmal am Ende. Kurzzeitige HTTP-500-/502-/503-/504-Antworten beim **Lesen** von Plänen werden höchstens zweimal mit Wartezeiten wiederholt. Schreibbefehle werden niemals automatisch wiederholt, ohne den COMEXIO-Zustand erneut zu prüfen. Die Fortschrittsentität zeigt Zeitpunkt und Anzahl abgeschlossener Schritte an.

COMEXIO-Statusabfragen erfolgen beim Start, nach Steuerbefehlen oder auf ausdrückliche Anforderung. **Kein zyklisches Polling.** Der TCP-Port ist standardmäßig `1505`.

## Grenzen und Sicherheit

- **Einmalige Bereinigung für v0.3.6.3.6:** Alte *eigene* CL-Eingangspläne und -Klassen sowie die *eigenen* Licht-/Rollladen-CL-Komponenten müssen vor dem vollständigen Neuaufbau manuell entfernt werden. Es gibt keine automatische Löschung oder Umbenennung und keine Kompatibilität mit alten sichtbaren Namen. Nur nach frischer, rein lesender Vorschau neu anlegen.
- **Wiederaufnahme nur innerhalb des aktuellen Schemas:** Ein bestätigter COMEXIO-API-Löschaufruf fehlt. Gespeicherte Aufträge aus v0.3.6.3.5 und älter sind ausdrücklich **nicht fortsetzbar**. Nach der einmaligen manuellen Bereinigung über eine neue Vorschau starten. Nur einen mit v0.3.6.3.6 gestarteten, später unterbrochenen Auftrag unter **Fortschritt / Pausieren → Nach Prüfung fortsetzen** fortführen. Vor dem Fortsetzen werden Pläne und abgeschlossene Arbeitsschritte abgeglichen; unerwartete Veränderungen blockieren Schreibzugriffe.
- Die **Namensprüfung** liest ausschließlich aktuelle CL-Namen. Sie benennt keine COMEXIO-Objekte um und erkennt absichtlich keine früheren Namensvarianten. Ein Austausch alter Namen erfordert manuelle Bereinigung und vollständigen Neuaufbau.
- Die Doorstation-Integration mit Klingel-Push, Kamera und Benutzerzuordnung ist geplant, **noch nicht implementiert**.
- Bei Änderungen der Entitätsdomäne können bestehende Automationen betroffen sein. COMEXIO-Motor- und Sicherheitslogik darf nicht durch direkte Relaisschaltung umgangen werden.
- Release-Versionen, Changelog und Quellcode gehören ins öffentliche Repository. Private Projektstände und Release-Entwürfe werden **nicht** eingecheckt.

## Projekt und Herkunft

**Entwicklung und Praxistests:** CrashND · **KI-gestützte Konzeption, Code und Dokumentation:** ChatGPT (OpenAI).

Eigenständige Community-Integration; die frühere [COMEXIO-Integration von kayl-codes](https://github.com/kayl-codes/homeassistant-comexio) diente als technische Referenz. Keine offizielle COMEXIO- oder Home-Assistant-Erweiterung.

Fehlerberichte und Beiträge: [GitHub Issues](https://github.com/CrashND/comexio-local/issues).

