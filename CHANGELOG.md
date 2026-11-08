# Änderungsprotokoll

## 0.3.6.3.10 – Web-IO-Bausteine wie im COMEXIO-Editor anlegen (Testkandidat)

**Geändert**
- Licht-/Rollladen- und Eingangs-Push erstellen einen neuen Web-IO-Baustein (`type=10`) nun zunächst als eigenständiges Element **ohne** eingebetteten `connection`-Parameter und mit leerem Elementnamen (`name=""`). Das entspricht dem am 08.11.2026 aufgezeichneten, korrekt dargestellten manuellen `add_element/`-Aufruf auf COMEXIO 11.1.5.
- Die Verbindung wird **anschließend separat** über den bereits vorhandenen `saveconnection/`-Aufruf mit den tatsächlich zurückgegebenen Element-IDs gespeichert. Der kanonische `CL ...`-Name des referenzierten Web-IO-*Befehls* bleibt erhalten; die leere Elementbezeichnung ist nicht die Befehlsbezeichnung.
- Bei einem Verbindungsfehler werden die erfolgreich angelegten Elemente nicht blind erneut angelegt. Vorhandene Elemente und fehlende Verknüpfungen können über die bereits vorhandene Graph-/Wiederaufnahmeprüfung erkannt werden.

**Tests und Grenzen**
- 216 automatisierte Offline-/Mocktests bestanden, einschließlich neuer Regressionen zur POST-Reihenfolge, unveränderten Web-IO-Referenz, Analog-/Binärverbindungen, Idempotenz und Wiederaufnahme nach fehlgeschlagener Verbindungsanlage.
- **Keine bestätigte Behebung der schwarzen Balken auf COMEXIO 11.1.5.** Der echte Firmware- und Webhook-Praxistest steht aus; ein bestandener Offline-Test kann die Darstellung nicht nachweisen.
- Kein automatischer Neuaufbau beim Update, keine COMEXIO-Lösch-/Umbenennungs-API, keine Änderung an bestehenden Raum-/Zentralplänen oder HA-Entitätskennungen. Die einzelnen Verbindungsschreibzugriffe können den vollständigen Neuaufbau verlängern.

## 0.3.6.3.9 – Gemeinsame Web-IO-Befehlsdefinition und frühzeitiger Strukturabgleich (Testkandidat)

**Verbessert**
- Eine streng validierte gemeinsame `WebIOCommand`-Definition liefert sowohl die JSON-Befehle des ersten Web-IO-Imports als auch die Formularfelder für weitere Befehle. Der erste Import und die nachfolgenden `save_command`-POSTs bleiben getrennt; kein ungeprüfter Massenimport.
- Der kontrollierte Neuaufbau liest **einmal nach dem ersten angehängten Befehl** die gespeicherten Befehle aus COMEXIO zurück. Er prüft Werte, vorhandene Felder und vergleichbare Einstellungen auf Übereinstimmung zwischen Erstimport und Formularweg. Erkennbare Differenzen stoppen vor der Erstellung von Logikplänen (keine blinden POST-Retries, kein Löschen).
- Die bereits bestehende Rückleseprüfung aller Befehle vor Beginn der Verknüpfungsphase bleibt erhalten. Zusätzliche Tests decken unterschiedliche Firmware-Feldschemata und fehlerhafte Werte ab.

**Wichtige Einschränkung**
- **Die Schreibdaten beider Web-IO-Wege sind gegenüber v0.3.6.3.8 unverändert.** Die Ursache der schwarzen Balken ist weiterhin nicht nachgewiesen. Diese Version ist ein sicherer Diagnoseschritt und **keine bestätigte Behebung**. Eine weitere vollständige Löschung und Neuerstellung sollte nicht allein wegen einer erwarteten grafischen Korrektur erfolgen.
- Bestehende Raum-, Zentral- und Rollladenpläne, Hardwarekanäle, eigene Marker, HA-Entity-Registry und die bekannte Push-Topologie werden nicht verändert. Neue COMEXIO-Lösch-APIs gibt es nicht.

## 0.3.6.3.8 – Explizite Namen für automatisch erzeugte Web-IO-Bausteine

**Gezielte Änderung**
- `admin_api.add_element()` überträgt bei Web-IO-Bausteinen (`type=10`) den kanonischen `CL ...`-Befehlsnamen im bisher leeren Feld `name`.
- Licht-, Rollladen- und Eingangs-Push nutzen dieselbe Funktion; die Namensquelle entspricht jeweils dem angelegten Web-IO-Befehl.
- Neue Regressionstests prüfen den tatsächlichen POST-Payload, die drei Quellarten und die Idempotenz. 181 Offline-Tests bestanden.

**Unverändert / Grenze**
- Bestehende CL-Bausteine werden nicht nachträglich geändert; ein Neuaufbau erfolgt ausschließlich nach manueller, gezielter Bereinigung und aktueller COMEXIO-Sicherung.
- COMEXIO-Push-Verbindungen, Originalpläne, HA-Entity-Registry und Synchronisierung bleiben im Code ansonsten unverändert.
- **Hypothesentest:** Der Darstellungsfehler „schwarze Web-IO-Balken“ ist auf echter COMEXIO-Hardware noch nicht nachweislich behoben. Der zuvor erfolgreiche 70/70-Aufbau belegt die Anlage, nicht die grafische Darstellung.


## 0.3.6.3.7 – Sicherer HA-Entitätslebenszyklus und Wartungsmenü

**Neu / behoben**
- Vollständige, nur lesende COMEXIO-Bestandsaufnahme für bestätigte HA-Entitätsbereinigung (ohne 50-Pläne-Limit; fehlerhafte oder fehlende Pläne blockieren Löschungen).
- Gemeinsamer Vergleich von COMEXIO-Katalog und HA-Entity-Registry mit Eigentumsprüfung, Fingerabdruck und gezielter Entfernung veralteter **eigener** Hardware-Entitäten.
- Domänenwechsel und Umklassifizierung über Vorschau, zusätzliche Löschbestätigung und kontrolliertes HA-Neuladen; manuelle Namen, Bereiche, Icons/Labels soweit möglich übernehmen. Automationen/Dashboards werden nicht automatisch umgeschrieben.
- Manuelle Q-Ausgangsklassifizierung verwendet dieselbe geprüfte Registry-Bereinigung, ausschließlich für den ausgewählten Kanal. Schutz für erkannte Rollladenmotoren bleibt aktiv.
- Hardwareadressen als Diagnoseattribute aller dynamischen COMEXIO-Entitäten; neue Diagnose für reine Metadatenänderungen ohne Namenswechsel.
- Abschluss des Push-Neuaufbaus ohne überflüssige „Aktualisieren“-Radioauswahl; lesbare Abbruch-/Fehlertexte bei der Synchronisierung.

**Unverändert / Hinweise**
- Keine Schreib- oder Löschzugriffe auf COMEXIO Web-IO, CL-Pläne, Raum-/Zentralpläne oder die bestätigte Licht-/Rollladen-Push-Topologie.
- Normale Discovery, Start und Push-Ereignisse löschen keinerlei HA-Entitäten; Bereinigung nur im bestätigten Wartungsdialog.
- Domänenwechsel können neue HA-Entity-IDs benötigen. Keine automatische Migration von Automationen oder Dashboards und kein transaktionaler Registry-Rollback.
- Automatisierte Tests ergänzt; realer HA-/COMEXIO-Praxistest weiterhin erforderlich.

## 0.3.6.3.6 – Einheitliches CL-Namensschema und sauberer Neuaufbau

**Geändert**
- Ein einziges, menschenlesbares Namensschema für Web-IO-Klassen, Befehle und Licht-/Rollladen-/Eingangspläne; keine Kürzel aus Home-Assistant-entry-IDs in sichtbaren Bezeichnungen.
- Alte Namensvarianten und migrationsspezifische Suchwege entfernt; Web-IO-Befehle erfordern ausdrücklich einen lesbaren Namen.
- Die frühere Namensmigration durch eine rein lesende Prüfung des aktuellen Namensschemas ersetzt.
- Nicht kompatible, gespeicherte Neuaufbau-Checkpoints werden kontrolliert beendet; anschließend nur neuer Aufbau nach Vorschau.
- Push-Logikpläne und Zeichenkoordinaten sind an feste physische Q-/Merkerbereiche gebunden, damit zusätzliche Kanäle bestehende Zuordnungen nicht verschieben.

**Wichtig**
- Einmalige, **manuelle Bereinigung aller eindeutig eigenen CL-Push- und Eingangsressourcen** und anschließender kompletter Neuaufbau erforderlich. Vorher COMEXIO sichern; originale Raum-/Zentralpläne und fremde Ressourcen unangetastet lassen.
- Keine automatischen COMEXIO-Lösch-/Umbenennungsoperationen. Live-Push-Tests weiterhin ausstehend.


## 0.3.6.3.5 – Konsolidierung und lesbare COMEXIO-Namen

**Behoben**
- Die Wiederaufnahme eines Licht-/Rollladen-Neuaufbaus ignoriert eindeutig als **INPUT** markierte Eingangspläne jetzt ebenso wie die Bestandsaufnahme.
- Doppelte Web-IO-Befehlsnamen, gleichnamige Logikpläne und ungültige IDs werden vor schreibenden Vorgängen erkannt und blockiert.
- Mehrdeutige/unerwartete Planantworten und Verknüpfungen führen zu einem sicheren Abbruch statt zu doppelten Bausteinen; neu angelegte Pläne werden nach dem Schreiben eindeutig geprüft.
- Inkrementelle negative Platzhalter-IDs sind nur innerhalb des laufenden Arbeitsstands mit expliziter Markierung zulässig.

**Geändert**
- Gemeinsame Bibliotheksfunktionen für Eigentumskennzeichnung, Web-IO-/Plan-Lookups, Verknüpfungen und lokales Push-Ziel; redundante Speziallogik reduziert.
- Neue `CL`-Befehle und Pläne nutzen lesbare, vollständige COMEXIO-Hardwareadressen statt `E3`/`S1`/Hash-Abkürzungen; alte Namen bleiben als Alias verfügbar.
- Öffentliche Konfigurationsvorgaben enthalten keine installationsspezifischen LAN-Adressen mehr; gespeicherte Integrationen bleiben unverändert.
- Fehler- und Wiederaufnahmetests erweitert; Dokumentation zu Namensmigration und verbleibenden Grenzen ergänzt.

**Hinweis**
- Keine automatische Umbenennung oder Löschung bestehender COMEXIO-Objekte und keine Änderung der funktionierenden Licht-/Rollladen-Push-Verbindungen.
- 152 Offline-Tests erfolgreich; Hardwareprüfung mit COMEXIO 11.1.5 steht aus.


## 0.3.6.3.4 – Eingangs-Push-Rücklesen und verständliche COMEXIO-Namen

**Behoben**
- `Data`-Rückleseprüfung unterscheidet fehlende/leere Lua-Skriptfelder von einem nachweislich abweichenden Skript. Nur vorhandene, übereinstimmende Skripte gelten als bestätigt; fehlende Angaben erfordern den realen Push-Test.
- Sichere Erkennung älterer Eingangs-Web-IO-Klassen und Eingangspläne; eine parallele oder doppelte Anlage wird blockiert.
- Neue Eingangspläne werden auch nach der Umbenennung anhand ihrer ausdrücklichen Besitzkennung aus dem bestehenden Licht-/Rollladen-Neuaufbau ausgeschlossen.

**Geändert**
- Neue Klasse `CL Eingänge Home Assistant` und stabile, verständliche Plannamen wie `CL Eingänge IO-Ext-3 I1-I18` statt abgeschnittener Home-Assistant-IDs.
- Eingangs-Vorschau kennzeichnet nicht vollständig lesbare `Data`-/`Parameter`-Felder und empfiehlt einen Live-Push-Test.
- Bestehende Licht-, Rollladen-, Raum- und Zentralpläne sowie Entitäts-IDs bleiben unverändert.

**Hinweis**
- Die alte Eingangs-Klasse und ggf. eigene alte Eingangspläne müssen manuell entfernt werden. Keine automatischen Lösch- oder Umbenennungsoperationen.
- Ein erfolgreicher Test der Eingangsübertragung auf COMEXIO-Firmware 11.1.5 steht aus.

## 0.3.6.3.3 - Diagnose der Eingangs-Vorschau und Auswahl beibehalten

**Behoben**
- Nach einem fehlgeschlagenen Eingangs-Vorschauaufruf bleiben die ausgewählten physischen Eingänge und die Bedienart sichtbar erhalten; keine automatische Sammelauswahl.
- Die Sammelauswahl aller I-Eingänge steht nicht mehr an erster Stelle; neue Dialoge starten ohne vorausgewählte Quellen.
- Bei einem Fehler vor der Vorschau werden die konkrete AdminError-Ursache und der jeweilige Aufrufabschnitt angezeigt und protokolliert. Webhook-IDs, Tokens und URLs werden aus Diagnosemeldungen entfernt.
- Beim Fehler nach der Backup-Bestätigung bleibt die Ursache auch im Abbruchdialog sichtbar; sicherer Abbruch und erneute Vorschau bleiben erforderlich.

**Unverändert**
- COMEXIO-Schreiblogik, vorhandene Licht-/Rollladen- und Eingangs-Push-Komponenten, physische Quelladressen, Entitäts-IDs und alle Verknüpfungs-Sicherheitsprüfungen.

**Hinweis**
- Die tatsächliche Fehlerursache des Flurtests ist noch nicht ermittelt; dazu wird die neue Diagnose auf Firmware 11.1.5 benötigt. Die Version verspricht noch keine erfolgreiche Eingangs-Push-Einrichtung.

## 0.3.6.3.2 – Eingangs-Push-Rücklesen und Konfigurationsmenü

**Behoben / verbessert**
- Web-IO-Callback-Parameter sicher normalisieren: exakter Pfad oder vollständige URL mit identischem, lokalem Home-Assistant-Ziel; fremde Zieladressen bleiben gesperrt.
- Ein von COMEXIO **nicht zurückgeliefertes** `Parameter`-Feld wird nicht länger mit einem nachweislich falschen Wert verwechselt. In der eindeutig eigenen Eingangs-Web-IO-Klasse darf die Verknüpfung bei passenden übrigen Metadaten ergänzt werden; die Callback-Funktion bleibt dabei **ausdrücklich unbestätigt** und erfordert einen Live-Push-Test.
- Vorhandene fremde bzw. nachweislich abweichende Web-IO-Befehle werden weiterhin weder ersetzt noch verknüpft; fehlende Pflichtfelder wie `Data` blockieren weiterhin die Einrichtung.

**Geändert**
- Konfigurationsmenü nach Funktionsbereichen gegliedert: **Push & Eingänge**, **Geräte & Bereiche**, **Rollläden & Positionen**, **Wartung & Diagnose**.
- Eindeutige Menütitel und deutsch-/englischsprachige Beschriftungen; alle bisherigen Funktionen bleiben erhalten.
- Bestehende Licht-/Rollladen-Push-Verbindungen und COMEXIO-Raum-/Zentralpläne bleiben unangetastet.

**Hinweis**
- Realer COMEXIO-Test des Eingangssignals `IO-Ext-3/I1` und der Callback-Rücklesevariante auf Firmware 11.1.5 steht aus. Es wird keine COMEXIO-Lösch- oder Überschreiboperation eingeführt.


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
