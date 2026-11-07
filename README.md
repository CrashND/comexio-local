# COMEXIO Local

![COMEXIO Local](docs/images/comexio-local-banner.png)

**Lokale Home-Assistant-Integration für COMEXIO IO-Server** – ohne Cloud und ohne regelmäßige Statusabfragen. Sie erkennt COMEXIO-Kanäle dynamisch und überträgt Zustandsänderungen über Web-IO/Webhooks an Home Assistant.

**Aktuelle Version:** 0.3.6.3.6 · **Status:** Community-Projekt in Entwicklung; Änderungen zunächst auf dem eigenen System testen.

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

**Einheitliches Namensschema ab v0.3.6.3.6:** `CL Push Home Assistant`, `CL Push IO-Ext-3 Q1-Q18`, `CL Push Rollläden M73-M90`, `CL Licht <Bereich> IO-Ext-3/Q1`, `CL Eingänge Home Assistant`, `CL Eingänge IO-Ext-3 I1-I18` und `CL Eingang IO-Ext-3/I1`. Die internen HA-Konfigurationseintrags-IDs kommen ausschließlich in Besitzkommentaren vor, niemals in sichtbaren Namen. **Alte CL-Namensvarianten werden nicht mehr berücksichtigt.**

**Einmaliger sauberer Neuaufbau erforderlich:** Vor dem ersten Neuaufbau mit dieser Version müssen die bisher von COMEXIO Local erzeugten **Licht-/Rollladen- und Eingangs-Web-IO-Klassen mit ihren Befehlen sowie die dazugehörigen eigenen CL-Logikpläne** in COMEXIO manuell bereinigt werden. Zuvor eine vollständige COMEXIO-Sicherung erstellen. **Keine Raumpläne, Zentralpläne, physische Kanäle oder fremde Web-IO-Geräte löschen.** Die Integration enthält keine verifizierte API zum automatischen Löschen. Home Assistant muss nicht zwingend neu als Integration eingerichtet werden; gespeicherte alte Neuaufbau-Checkpoints werden sicher beendet, damit keine Arbeit mit veralteten Plannamen fortgesetzt wird. Die Eingangs-Push-Funktion wird danach wie bisher nur auf ausdrückliche Auswahl eingerichtet.

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

