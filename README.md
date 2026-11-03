# COMEXIO Local 0.3.0 — Push-Rueckkanal mit Diagnose

Repository: https://github.com/CrashND/comexio-local

**HACS (Entwicklerversion):** HACS → Benutzerdefinierte Repositories → `https://github.com/CrashND/comexio-local` → Typ **Integration**. Ohne Release wird der Standardbranch verwendet. Nach der Installation Home Assistant neu starten und die Integration in Geräte & Dienste hinzufügen.


**Status: Entwickler-/Testversion; keine Live-Validierung mit dem COMEXIO 2G und keine Laufzeitvalidierung innerhalb von Home Assistant.** Der Code wurde offline mit synthetischen COMEXIO-Antworten getestet. Bitte vor einer produktiven Installation sichern.


## Neu in 0.3.0: rueckkanalorientierte Diagnose

**0.3.0 ist eine Entwicklungsversion, noch nicht am realen COMEXIO IO-Server 2G 11.1.4 geprueft.**
Die bestehende dynamische Entdeckung, Licht-/Rollladenplattform, TCP-Schaltung und
Webhook-Registrierung bleiben erhalten. Regelmaessiges Polling ist weiterhin ausgeschaltet.

**Wesentlich:** Die reine Installation der Integration registriert zwar den HA-Webhook,
legt aber aus Sicherheitsgruenden **keine Web-IO-Bausteine automatisch** im COMEXIO an.
Deshalb funktioniert die Schaltung in HA moeglicherweise bereits, waehrend lokale
Taster noch keine Zustandsmeldung ausloesen.

**Neue rein lesende Aktion** `comexio_local.push_diagnose` (Entwicklerwerkzeuge → Aktionen):
Sie erkennt, ob die COMEXIO-Local-eigene Web-IO-Geraeteinstanz vorhanden ist,
ob ihre IP-Adresse zur konfigurierten lokalen HA-Adresse passt, ob die benoetigten
Kommandos existieren, ob die eigenen Logikplaene aktiv sind und ob Quell-Ausgang
mit der entsprechenden Web-IO-Funktion **verbunden** ist. Sie liest nur die
notwendigen eigenen Logikplaene; sie veraendert nichts.

Das Ergebnis steht sowohl als Aktionsantwort (falls angefordert) als auch beim
Diagnosesensor **COMEXIO Push Konfiguration** bereit:

- `ready`: Ziel, Kommandos und Verdrahtung anhand der auslesbaren Daten passend;
  bedeutet noch **nicht**, dass COMEXIO eine echte HTTP-Nachricht erfolgreich gesendet hat.
- `linked_unverified`: Verdrahtung vorhanden, aber einige Befehlsfelder werden
  vom COMEXIO-Konfigurationsdump nicht geliefert. Keine unbelegte Erfolgsaussage.
- `incomplete`: Web-IO-Kommandos oder Verbindungen fehlen, falsche Zieladresse
  oder ein sonstiger Konflikt ist sichtbar.
- `not_checked`: Noch keine Diagnose angefordert.

Die weiteren Diagnose-Entitaeten **COMEXIO Push Ereignisse** und
**COMEXIO Push abgelehnte Ereignisse** zeigen, ob der HA-Webhook angesprochen
wurde und ob die Daten zur dynamischen Quelladresse passten. Der letzte Ablehnungsgrund
wird ohne Webhook-Geheimnis angezeigt. Der HA-Webhook nimmt hoechstens 4096 Bytes an.

**Einrichtung bleibt ausdruecklich freigabepflichtig:**
`comexio_local.configure_push` mit `confirm: true` darf erst nach einem
vollstaendigen COMEXIO-Backup verwendet werden. Die Aktion legt nur eigene,
namensgebundene Web-IO-Kommandos/Logikplaene fuer erkannte Lichtausgaenge und
Istpositionen an; vorhandene Raumplaene bleiben unveraendert.
Der Aufruf fuehrt jetzt eine Schutzpruefung vor den ersten Schreibbefehlen und
anschliessend eine einmalige Rueckkontrolle durch. Bei einer veralteten IP oder
einem falschen Webhook in bestehenden Kommandos stoppt er mit einer eindeutigen
Meldung, **statt fremde oder vorhandene Objekte stillschweigend zu ueberschreiben**.
Ein erneuter Aufruf ist keine Reparatur fuer beliebige Fehlkonfigurationen.

Fuer die erste Inbetriebnahme nur eine abgestimmte Folge: (1) HACS-Version
aktualisieren und HA neu starten; (2) `comexio_local.push_diagnose` einmal
aufrufen; (3) nur nach Sicherung und bewusster Freigabe bei fehlender Verkabelung
`comexio_local.configure_push` ausfuehren; (4) Rueckmeldung durch einen
physischen Schaltvorgang bewerten. **Keine wiederholten Blindversuche bei Fehlern.**

**Wichtige Begrenzung:** `ready` belegt die Konfiguration, nicht den erfolgreichen
Ende-zu-Ende-Push. Ob Web-IO auf COMEXIO OS 11.1.4 den HTML-Pfad korrekt sendet,
bleibt bis zur Echtgeraetepruefung offen. Ist der Pfad auf eine andere HA-IP oder
einen alten Webhook gesetzt, wird das in der Diagnose angezeigt, aber nicht
ungefragt repariert.

## Was gegenüber 0.1 geändert wurde

| Thema | 0.1.0 | 0.2.0 |
|---|---|---|
| COMEXIO-Anschlüsse | 16 fest eingetragene Lichtadressen | Alle aktiven IOs und Merker werden aus der COMEXIO-Konfiguration eingelesen; keine feste Zuordnung im Quellcode |
| Licht / Rollläden | Nur Licht | Automatische Klassifikation aus Signalbezeichnungen und Zuordnung zu vorhandenen Logikplänen; Rollläden aus `R_…_soll`/`R_…_ist`-Paaren |
| Rückmeldungen | periodisches TCP-GET | COMEXIO sendet Web-IO-Events direkt an einen lokalen HA-Webhook; **kein periodisches GET** |
| Änderungen am Server | Neue ZIP notwendig | `comexio_local.refresh_discovery` entdeckt neue/umbenannte Signale; bei neuen Push-Quellen `comexio_local.configure_push` einmalig erneut ausführen |
| COMEXIO-Logik | Nicht verändert | Bestehende Räume unverändert; optional nur eigene, namensgebundene Web-IO-Pläne |

## Aufbau

- COMEXIO 2G: lokale Taster, Stromstoß-/Rollo-Funktionsbausteine und reale IOs.
- COMEXIO Local: entdeckt COMEXIO-Konfigurationsdaten über die Admin-Weboberfläche. Die bisherigen manuell dokumentierten PDFs dienen als Plausibilitätsreferenz, aber **nicht als feste Mapping-Datei**.
- COMEXIO → HA: Nur Statusänderungen von erkannten Lichtausgängen und Istpositionsmerkern werden über Web-IO/LUA/HTTP als JSON an HA gesendet.
- HA → COMEXIO: TCP JSON auf Port 1505. Für Licht wird der Ausgang explizit gesetzt und **einmalig per GET bestätigt**. Für Rollläden wird ausschließlich der **Sollwert-Merker** beschrieben; die spätere Istposition kommt per Web-IO-Push. Motorrelais dürfen nicht als normale Lichtschalter verwendet werden.
- Node-RED bleibt separat für Szenen, Beschattung, zentrale Abläufe.

### Wie klassifiziert wird

1. Aktive `Q`-Ausgänge mit Licht-/LED-/Spot-/Lampe-/Indirekt-Bezeichnungen werden **Licht-Entitäten**.
2. Motorrelais mit `Roll`, `Rollo`, `Jalousie`, `Markise` usw. werden erkannt und **nicht direkt als Licht oder Schalter angeboten**.
3. Die Analogmerkerpaare `R_<Name>_soll` und `R_<Name>_ist` werden zu **Cover-Entitäten** mit Prozentposition zusammengefasst. Bei Markise wird als Gerätetyp Markise verwendet.
4. Noch nicht eindeutig zuordenbare Ausgänge erscheinen vorsichtig als **nur lesbare Relais-Binary-Sensoren**, nicht spekulativ als Licht. Ohne Web-IO-Ereignis für sie aktualisieren sich diese nur beim einmaligen Statusabruf.
5. Vorhandene Funktionsplannamen werden für die beschreibenden Namen berücksichtigt. Die reale Klassifikation basiert auf der aktuell gelesenen COMEXIO-Konfiguration, nicht den alten PDFs.

**Grenzen:** Ob ein Ausgang tatsächlich eine Lampe versorgt, kann COMEXIO aus der Hardware allein nicht erkennen. Bei irreführenden alten Beschriftungen muss der Name am IO-Server korrigiert werden. Für Rollläden ohne konsistente Soll-/Istmarker lässt sich der individuelle Fahrzustand nicht zuverlässig ableiten; die Motorrelais bleiben sicherheitshalber ausgeschlossen. Eine individuelle STOP-Funktion ist mangels dokumentierter individueller Stop-Adresse nicht implementiert.

## Installation (erste Testinstallation noch manuell)

1. Inhalt von `custom_components/comexio_local/` nach `/config/custom_components/comexio_local/` auf dem HAOS kopieren (nicht parallel zur alten Version 0.1 betreiben) und Home Assistant neu starten.
2. Home Assistant → Einstellungen → Geräte & Dienste → Integration hinzufügen → **COMEXIO Local**. IP des IO-Servers, TCP-Port 1505, COMEXIO-Adminzugang und die **direkte lokale HA-Adresse** angeben. Beispiel: `http://192.168.10.6:8123` (kein öffentlicher Reverse Proxy). IPs sind nur editierbare Startwerte, keine hartcodierten Kanaladressen.
3. Nach erfolgreicher Einbindung erscheinen dynamisch erkannte Licht- und Rollladen-Entitäten. Beim ersten Start erfolgt ein **einmaliger** GET-Snapshot. Ohne Push-Einrichtung bleiben spätere lokale Änderungen zunächst unbekannt. **Die Integration verändert bei Start/Discovery nichts in COMEXIO.**
4. **Nach vollständiger COMEXIO-Konfigurationssicherung und deiner ausdrücklichen Freigabe** im Home-Assistant-Aktionsdialog genau einmal `comexio_local.configure_push` mit `confirm: true` ausführen. Dieser Aufruf erzeugt *ausschließlich* namensgebundene `CL...`-Web-IO-Objekte für erkannte **Lichtausgänge** und **Rollo-Istmarker**. Keine massenhafte Kopplung aller sonstigen Merker. Die Verbindungen werden danach beim physischen Tastendruck direkt an HA gesendet.

Ein Backup ist wichtig: Dieser vierte Schritt ändert die COMEXIO-Konfiguration. Auf dem realen IO-Server wurde die automatische Anlage **noch nicht ausgeführt**. Eine Abweichung der Firmware kann einen Abbruch oder unvollständige Anlage verursachen. Der Vorgang darf nicht wiederholt werden, ohne zuerst die COMEXIO-Pläne zu prüfen.

### Änderungen an der COMEXIO-Installation

- Unter Entwicklerwerkzeuge → Aktionen `comexio_local.refresh_discovery` aufrufen: liest einmalig die aktive Konfiguration, die betroffenen Pläne sowie die aktuellen Zustände, erzeugt neue Entitäten und markiert verschwundene Entitäten als nicht verfügbar.
- Neue Lichter oder Positionsmerker benötigen zusätzlich einen **einmaligen** erneuten `configure_push`-Aufruf mit Backup/Freigabe, damit auch deren Änderungen aktiv übertragen werden. Bereits angelegte namensgebundene Verbindungen werden soweit möglich wiederverwendet.
- `comexio_local.snapshot_once` ist eine **manuelle** einmalige Zustandsabfrage nach HA-/Netzausfall, nicht ein Hintergrundtimer.

### API und technische Entscheidungen

- COMEXIO-TCP-Protokoll: zeilenweises JSON auf Port 1505, `action: get/set`, reale Antworten `{"licht":0}`/`{"licht":1}` über den Gästezimmer-Test bestätigt.
- Initialisierung: konfigurierbare, nur einmalige GET-Snapshots (in Gruppen bis 30 Quellen) sowie ein einziges GET nach dem Schalten eines Lichts; keine Poll-Schleife, keine periodische Abfrage von IO-Server-/CPU-Status.
- Push: HTTP-POST auf einen mit Zufallskennung geschützten, in HA ausschließlich lokal registrierten Webhook. JSON enthält die tatsächliche COMEXIO-Adresse und den neuen Wert.
- Push-Verwaltung: selbst angelegte Namen `CL<entry-ID-Kurzform> ...`, gruppiert nach COMEXIO-Erweiterungsmodul. Die vorhandenen Raum- und Zentralpläne werden nie bearbeitet. Es gibt **keine Auto-Reparatur im Hintergrund**, kein Massen-Audit, keine Löschroutine.
- Steuerung: `SET` auf den realen Lichtausgang. **Vorsicht**: Bei COMEXIO-R/S-Bausteinen ist noch zu validieren, ob diese Art des direkten Setzens zum internen Speicherzustand passt. Die lokale Schaltung funktioniert unabhängig vom HA-Betrieb.
- Änderungen werden **nicht** automatisch durch eine Netzwerksuche im Sekundenrhythmus erkannt: Neu-Erkennung auf Wunsch oder beim HA-Neustart. Dies ist bewusst ressourcenschonend.

### Was noch nicht nachgewiesen ist

- Ob COMEXIO-Firmware **11.1.4** die HTML-/Web-IO-Konfigurationsaufrufe beim 2G in genau der angenommenen Form anbietet. Grundlage ist öffentlich zugänglicher **älterer** Quellcode der Fremdintegration (0.7.5); die aktuell eingesetzte Fremdversion 0.30.1-rc1 war nicht direkt lesbar.
- Ob LUA-Web-IO-Statusmeldungen tatsächlich bei jedem lokalen Stromstoß-Schalten ausgelöst werden. Das Konzept deckt die gewünschte Ereignisübertragung ab, der Live-Nachweis fehlt.
- Ob beim COMEXIO eine mehrere Quellen umfassende einmalige GET-Abfrage über TCP in einem Paket funktioniert (Einzel-GET ist bestätigt).
- Ob bei jedem `SET` der interne Stromstoßzustand konsistent bleibt. Bis zum Live-Nachweis daher zunächst nicht unbeaufsichtigt einsetzen.
- Ob die Config-Flow-Implementierung auf deiner konkreten HAOS-Version ohne Kompatibilitätsanpassung startet. Die sieben Offline-Tests prüfen Parser, dynamische Erkennung, TCP-Client und Push-Erzeugungsdaten, nicht die komplette HA-Laufzeit.

## Dateien

```text
custom_components/comexio_local/
    __init__.py, config_flow.py, constants.py
    admin_api.py, discovery.py, runtime.py, tcp_client.py, push_setup.py
    entities.py, light.py, cover.py, binary_sensor.py, sensor.py
    manifest.json, strings.json, services.yaml, translations/
tests/ — Offline-Protokolltests ohne COMEXIO-Hardware
```

Referenz zum Kommunikationskonzept (nicht mit unserem Projekt verwechseln): https://github.com/kayl-codes/homeassistant-comexio .
