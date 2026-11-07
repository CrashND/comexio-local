# COMEXIO Local

![COMEXIO Local](docs/images/comexio-local-banner.png)

**Lokale Home-Assistant-Integration für COMEXIO IO-Server** – ohne Cloud und ohne regelmäßige Statusabfragen. Sie erkennt COMEXIO-Kanäle dynamisch und überträgt Zustandsänderungen über Web-IO/Webhooks an Home Assistant.

**Aktuelle Version:** 0.3.6.3.5 · **Status:** Community-Projekt in Entwicklung; Änderungen zunächst auf dem eigenen System testen.

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
| Bezeichnungen | Neue Push-Objekte mit lesbaren `CL`-Namen (Web-IO-Klasse `CL Push Home Assistant`); alte Namen bleiben kompatibel, bestehende Namen werden nicht automatisch geändert |

Die Integration lässt sich mit Node-RED kombinieren. Bestehende COMEXIO-Raum- und Zentralpläne bleiben unverändert.

**Namenskonvention ab v0.3.6.3.5:** Neue, von COMEXIO Local erzeugte Objekte erhalten ausschließlich menschenlesbare Namen mit vollständiger Moduladresse: `CL Push Home Assistant`, `CL Push IO-Ext-3`, `CL Licht <Bereich> IO-Ext-3/Q1`, `CL Eingänge Home Assistant`, `CL Eingänge IO-Ext-3 I1-I18`, `CL Eingang IO-Ext-3/I1`. Technische HA-IDs stehen nur in internen Besitzkommentaren. Bereits vorhandene alte Namen werden zur Wiedererkennung weiterhin unterstützt und **nicht automatisch umbenannt oder dupliziert**.

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
| **Wartung & Diagnose** | Konfigurationsänderungen synchronisieren (mit Vorschau) und mögliche COMEXIO-Namensanpassungen nur lesend prüfen. |

**Codebereinigung v0.3.6.3.5:** Gemeinsame Prüfung von Besitzmarkierungen, Befehls-IDs und Logikplannamen für Licht, Rollläden und Eingänge; gemeinsame Graph-Verknüpfung und LAN-Zielvalidierung. Unbekannte oder widersprüchliche COMEXIO-Antworten blockieren Schreibzugriffe. Die gespeicherten Geräte-IDs, Entitäts-IDs, Webhook-IDs und bestehenden Checkpoints werden nicht migriert. Neue Installation: COMEXIO-Serveradresse und lokale Home-Assistant-URL müssen explizit angegeben werden; bisher gespeicherte Einstellungen bleiben erhalten.

**Bereits vorhandene COMEXIO-Namen:** Alte Web-IO-Klassen/-Befehle und eigene Push-Pläne bleiben nach dem Update absichtlich bestehen. Eine vollständige Umbenennung bereits angelegter Objekte ist nicht implementiert, weil der COMEXIO-Umbenennungs-/Löschaufruf für Firmware 11.1.5 nicht verifiziert ist. Wer **auch bisherige** Push-Pläne und Web-IO-Kommandos mit neuen lesbaren Namen haben möchte, benötigt eine **separat geplante manuelle Bereinigung plus bestätigten Neuaufbau** nach vollständiger COMEXIO-Sicherung. Hierbei ausschließlich von COMEXIO Local verwaltete Licht-/Rollladen-Push-Objekte bearbeiten, niemals Raum-/Zentralpläne oder fremde Web-IO-Geräte. Der bestehende Push-Bestand bleibt bis dahin funktional unverändert.

**Bekannte Grenze:** Licht-/Rollladen-Push-Pläne gruppieren Quellen derzeit nach Modul und Quellreihenfolge. Bei einer späteren Erweiterung *innerhalb desselben Moduls* kann eine neue Quelle die Gruppenzuordnung beeinflussen. Daher bestehende Push-Pläne nach einer Hardware-/Kanalerweiterung nicht blind neu anlegen. Eingangspläne verwenden dagegen stabile, physische I-/AI-Kanalblöcke. Ein COMEXIO-Praxistest der Eingangs-Push-Flanken und der neuen Plannamen bleibt erforderlich.

**Eingangs-Push bei Fehlern:** Schlägt die rein lesende Vorschau fehl, zeigt der Dialog den konkreten COMEXIO-Fehler und behält die Eingangs- und Bedienartauswahl bei. Die Sammelauswahl aller I-Eingänge erfolgt nie automatisch. Die ursprüngliche Ursache des Flurtests muss weiterhin auf der COMEXIO-Firmware ermittelt werden; bis dahin keine vorhandenen Web-IO- oder Logikkomponenten löschen.

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

**Eingänge ab v0.3.6.3:** Neue Eingänge werden separat in der Web-IO-Klasse **`CL Eingänge Home Assistant`** und in eindeutigen Plänen wie **`CL Eingänge IO-Ext-3 I1-I18`** angelegt. Die sichtbaren Namen enthalten keine zufälligen Home-Assistant-Konfigurations-IDs. Es gibt **keinen automatischen Massenimport beim Update**. Für den ersten Praxistest ist der digitale Taster `IO-Ext-3/I1` im Flur vorgesehen; er ist in COMEXIO an den Baustein **Multifunktionstaste** angeschlossen. Für die ersten Tests werden nur die rohen Drücken-/Loslassen-Flanken übertragen, noch keine separaten Einfach-/Doppel-/Lang-Ereignisse. Bestehende Licht-/Rollladen-Push-Komponenten bleiben unverändert. Die Integration zeigt bestätigte digitale Eingänge als `binary_sensor` an. Automationen können `comexio_local_input` abonnieren (Felder: `source`, `mode`, `action`, `value`, `entity_id`), mit Aktionen `gedrueckt`/`losgelassen` für Taster oder `ein`/`aus` für rastende Schalter. Ein Signal wird nur bei einem wirklichen Zustandswechsel als Bedienereignis publiziert. COMEXIO-Bausteine für *Einfach/Doppel/Lang* sind noch nicht als eigene Ereignisquellen angebunden. Bei AI-Eingängen ist der Digitalmodus ausdrücklich zu bestätigen; andere AI-Eingänge können echte Analogsignale sein. Vor dem Praxistest ist die Übertragung von kurzen Impulsen über Firmware 11.1.5 **nicht bestätigt**.

**Eingangs-Rückleseprüfung (v0.3.6.3.4):** COMEXIO kann den gespeicherten Web-IO-Callback relativ oder als vollständige URL zurückliefern. Nur dasselbe Home-Assistant-Ziel wird akzeptiert. Wenn COMEXIO die Felder `Data` (Lua-Skript) oder `Parameter` im Konfigurations-Snapshot nicht oder leer liefert, gilt der Befehl ausdrücklich als **nicht vollständig verifiziert**. Die Anlage ist dann nur bei eindeutig zugeordneter eigener Eingangs-Web-IO-Klasse, korrekt benanntem Kommando, passender Zieladresse und übereinstimmenden weiteren Befehlsmetadaten zulässig. Vorhandene, tatsächlich abweichende Lua-Skripte, Callback-Adressen oder Pflichtmetadaten blockieren weiterhin alle Schreibzugriffe. Der erste **Live-Push-Test ist zwingend**, da fehlende Rücklesefelder keinen Funktionsnachweis darstellen.

**Neuaufbau-Performance:** Der Lauf verwendet einen temporären Arbeitsstand statt alle Pläne vor und nach jedem Schritt abzufragen. Ein vollständiger Vergleich erfolgt beim Start, nach einer Unterbrechung und einmal am Ende. Kurzzeitige HTTP-500-/502-/503-/504-Antworten beim **Lesen** von Plänen werden höchstens zweimal mit Wartezeiten wiederholt. Schreibbefehle werden niemals automatisch wiederholt, ohne den COMEXIO-Zustand erneut zu prüfen. Die Fortschrittsentität zeigt Zeitpunkt und Anzahl abgeschlossener Schritte an.

COMEXIO-Statusabfragen erfolgen beim Start, nach Steuerbefehlen oder auf ausdrückliche Anforderung. **Kein zyklisches Polling.** Der TCP-Port ist standardmäßig `1505`.

## Grenzen und Sicherheit

- **Manuelle Bereinigung beim Wechsel auf v0.3.6.3.4:** Eine bereits angelegte alte Klasse namens `CL Input <Kennung>` und eventuell dazugehörige alte `CL Eing <Kennung> ...`-Logikpläne gehören **nur zur Eingangs-Push-Einrichtung**. Die neue Version erstellt verständlich benannte Komponenten und verweigert eine parallele Anlage, solange betroffene alte Eingangs-Ressourcen noch sichtbar sind. Es erfolgt **keine automatische Löschung**. Vorhandene Licht-/Rollladen-Push-Klassen und -Pläne dürfen nicht entfernt werden. Eine erneute lesende Vorschau prüft nach der manuellen Bereinigung den tatsächlichen Stand.

- **Neuaufbau v0.3.6.3:** Die bestehenden eigenen Push-Pläne und Web-IO-Klasse müssen bei einem vollständigen Neubeginn weiterhin einmalig **manuell in COMEXIO entfernt** werden. Ein bestätigter API-Löschaufruf fehlt noch; die Integration löscht deshalb selbst nichts. **Einen fehlgeschlagenen, bereits begonnenen Auftrag nicht neu starten:** Unter **Fortschritt / Pausieren → Nach Prüfung fortsetzen** bleiben vorhandene Komponenten erhalten. Vor einer Wiederaufnahme werden einmalig die vorhandenen CL-Pläne und die gespeicherten Arbeitsschritte abgeglichen; bei unerwarteten Veränderungen verweigert die Integration weitere Schreibzugriffe.
- Die Umbenennung **bereits vorhandener** COMEXIO-Komponenten bleibt eine rein lesende Vorschau, bis die API sicher geprüft ist.
- Die Doorstation-Integration mit Klingel-Push, Kamera und Benutzerzuordnung ist geplant, **noch nicht implementiert**.
- Bei Änderungen der Entitätsdomäne können bestehende Automationen betroffen sein. COMEXIO-Motor- und Sicherheitslogik darf nicht durch direkte Relaisschaltung umgangen werden.
- Release-Versionen, Changelog und Quellcode gehören ins öffentliche Repository. Private Projektstände und Release-Entwürfe werden **nicht** eingecheckt.

## Projekt und Herkunft

**Entwicklung und Praxistests:** CrashND · **KI-gestützte Konzeption, Code und Dokumentation:** ChatGPT (OpenAI).

Eigenständige Community-Integration; die frühere [COMEXIO-Integration von kayl-codes](https://github.com/kayl-codes/homeassistant-comexio) diente als technische Referenz. Keine offizielle COMEXIO- oder Home-Assistant-Erweiterung.

Fehlerberichte und Beiträge: [GitHub Issues](https://github.com/CrashND/comexio-local/issues).

