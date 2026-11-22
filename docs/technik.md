# COMEXIO Local – Technische Dokumentation

> **Stand: v0.4.12 (Offline-Bugfix-Testkandidat).** Die typbasierten EnOcean-Pläne, die v0.4.11-Vorschau und mehrere Live-Pushs wurden auf dem IO-Server/HA praktisch überprüft. Die v0.4.12-Änderungen benötigen weiterhin eine eigene Hardwareabnahme.

COMEXIO Local ist eine lokale, ereignisgesteuerte Home-Assistant-Integration für den COMEXIO IO-Server. Sie erkennt Anschlüsse aus dessen Konfiguration, stellt passende Home-Assistant-Entitäten bereit und verarbeitet Zustandsänderungen über lokale Webhooks. Ein periodisches Status-Polling ist nicht vorgesehen.

Die COMEXIO-Systemübersicht wird nicht zyklisch abgefragt. Bei jedem Start oder expliziten Discovery-Refresh erfolgt ein einmaliger optionaler GET. Nicht beschriftete Versionen werden nicht geraten. Liefert das Dashboard keine nachweisbaren Werte, werden nur ausdrücklich vorhandene Firmware-/Modell-/Seriennummernfelder aus der Controller-Konfiguration übernommen. Die HA-Geräteregistrierung erhält ausschließlich tatsächlich erkannte Modell-, Firmware- und Seriennummernwerte. Bei vorübergehend fehlenden optionalen IO-Server-Daten werden bereits bekannte Werte nicht wieder mit `None` überschrieben. Identifiers, Entitäts-IDs, Namen und Bereiche werden nicht verändert. Diagnoselogging meldet den HTTP-Status oder fehlende Felder, ohne Seriennummern, HTML oder Zugangsdaten auszuschreiben.

Für Installation und Bedienung siehe das [Benutzerhandbuch](benutzerhandbuch.md); für die Projektübersicht die [README](../README.md).

**v0.4.11 - enger Parser-Bugfix:** Das Modul `FubModules["10"][device_id]`
kann als `[]` oder `{}` leer sein. Nur das exakt leere Array wird wie ein
leerer Befehlsindex behandelt. Nichtleere Arrays haben keine gesicherten
Befehls-ID-Schluessel und bleiben gesperrt. Unbekannte Strukturtypen
werden ohne Ausgabe von Skripttext, Adressen oder Webhook-Inhalten
mit Datentyp und ggf. Eintragsanzahl diagnostiziert. Andere sensible
COMEXIO-Operationen behalten ihre strengen Strukturpruefungen.

## 1. Architektur im Überblick

```text
                             Home Assistant
                     ┌───────────────────────────────┐
                     │ COMEXIO Local (Runtime)       │
                     │                               │
                     │ Discovery / Entitäten / Werte │
                     │ Push-Verwaltung / Diagnose    │
                     └───────────────┬───────────────┘
                                     │
         Konfiguration lesen         │          Werte lesen / schalten
     HTTP-Adminoberfläche            │             TCP-JSON
       ┌─────────────────────────────┴──────────────────────┐
       │                                                    │
       ▼                                                    ▼
 COMEXIO HTTP-Admin                                 COMEXIO TCP-API
 (Module, Logikpläne,                              (einmaliger GET,
  Web-IO, Konfiguration)                            gezielter SET)
       │                                                    │
       └────────────────── COMEXIO IO-Server ────────────────┘
                                    │
                          Web-IO-Befehle / Push
                                    │ HTTP POST (JSON)
                                    ▼
                     HA-Webhook /api/webhook/…
                                    │
                       Validierung und Eventjournal
                                    │
                         Entitäten / HA-Eventbus
```

Drei Datenwege sind strikt zu unterscheiden:

| Datenweg | Zweck | Auslöser |
| --- | --- | --- |
| **HTTP-Admin** | Modul- und Logikplanerkennung, Push-Vorschau, ausdrücklich freigegebene Konfigurationsänderungen | Start, manueller Refresh, Wartungsaktion |
| **TCP-JSON** | Einmalige Zustandsaufnahme sowie gezielte Schalt- und Merkerbefehle | Start/Refresh, `snapshot_once`, Bedienung |
| **HTTP-Webhook** | Laufende Zustandsänderungen vom COMEXIO-Server zu HA | COMEXIO-Web-IO-Ereignis |

Die Integration nutzt die Home-Assistant-Plattformen `light`, `switch`, `cover`, `binary_sensor` und `sensor`. Sie wird als `local_push`-Integration registriert und benötigt die eingebaute Webhook-Komponente.

## 2. Initialisierung und Discovery

Beim Start eines vorhandenen Konfigurationseintrags (`async_setup_entry`):

1. Erstellt die Integration einen HTTP-Adminclient, einen TCP-Client und eine `Runtime`.
2. Liest sie die COMEXIO-Konfiguration (`FubModules`, `Fubs`) und verfügbare Logikplandaten. Optional erfolgt ein **lesender** Abruf der Systeminformationen über `/admin/system_info/home` über dieselbe authentifizierte Adminsitzung (Zeitlimit 10 Sekunden, keine Redirects; nur HTTP 200 akzeptiert). Diese URL ist für COMEXIO 11.1.5 praktisch bestätigt; der vorher verwendete Dashboard-Pfad lieferte dem HA-Client eine andere Ansicht ohne Gerätedaten. Die Auslesung erkennt sowohl reguläre HTML-Textknoten als auch eingebettete JavaScript-HTML-Felder und verwendet nur direkt beschriftete Firmware-, Modell- und Seriennummernwerte. Fehlen Felder, können eindeutig benannte Controller-Felder der COMEXIO-Konfiguration ergänzt werden; allgemeine `Version`-Angaben und feste Werte werden ignoriert. Ein fehlgeschlagener optionaler Abruf führt zu einer Protokollwarnung, nicht zu einem Abbruch der Discovery.
3. Ermittelt sie daraus die Kanäle und die tatsächlichen Erweiterungsmodule.
4. Legt sie passende Home-Assistant-Gerätezuordnungen und den Entitätskatalog an.
5. Führt sie **einmalig** einen TCP-Zustandssnapshot aus; Standard- und EnOcean-Signale werden getrennt abgefragt, jeweils in Batches von höchstens 30 Kanälen.
6. Initialisiert sie die Push-Neuaufbau-Statusverwaltung, registriert den lokalen Webhook und lädt die Entitätsplattformen.

**Beim Start werden keine COMEXIO-Logikpläne und keine Web-IO-Befehle geschrieben.** Das Einlesen von Logikplandetails ist bei der normalen Discovery begrenzt; sicherheitsrelevante Synchronisierungsvorschauen fordern dagegen eine vollständige Prüfung an.

### Identität und Zuordnung

- Kanäle verwenden eine stabile COMEXIO-Quelladresse, z. B. `io:IO-Ext-2/Q2`, `io:EnOcean/EI5_CO` oder `cover:M85`.
- Die Home-Assistant-`unique_id` setzt sich aus der Identität des Konfigurationseintrags und dieser Quelladresse zusammen. Ein geänderter Logikplan- oder Entitätsanzeigename erzeugt daher keine neue Entität, solange die physische COMEXIO-Quelladresse gleich bleibt.
- Physische Erweiterungsmodule werden aus den COMEXIO-Moduldaten erkannt. Es gibt **keinen fest codierten Gerätebestand**; der Modultyp wird anhand ausdrücklich vorhandener Modellfelder oder durch Übersetzung einer für COMEXIO OS 11.1.5 beobachteten, endlichen `TypeId`-Zuordnung erkannt (`4`: EnOcean-Bridge, `10`: IO-Extension, `14`: Universal-Aktor, `16`: Doorstation). Andere IDs sind bewusst unbekannt und bleiben ohne Modell.
- Der physische COMEXIO-`Identifier` wird nur im validierten Seriennummerformat `NNNN-NNNN-NNNN` als HA-`serial_number` übernommen; ausdrücklich benannte gültige Seriennummerfelder haben Vorrang. Geräteidentitäten bleiben **modulindexbasiert** (`module:<Familie>:<Index>`), nicht von dieser austauschbaren Seriennummer oder dem Namen abhängig. Eine ausdrücklich pro Modul übermittelte `FirmwareVersion` oder `Firmware` wird nur nach Versionsvalidierung als `sw_version` für genau dieses Modul verwendet; die IO-Server-Firmware wird nicht vererbt.
- Die beiden Registrierungswege `sync_hardware_registry` und `device_metadata.device_info` übernehmen dieselben Modul-Metadaten. Wiederholte Discovery darf bestehende Nutzer-Namen, Bereiche, Labels, deaktivierte Entitäten und Fremdeinträge nicht ändern. Fehlt ein optionaler System-Info-Wert vorübergehend, bleiben bereits erkannte Controller-Metadaten erhalten.
- EnOcean-Kanäle `EI1` bis `EI7` sind **Signalgruppen**, keine eigenständigen HA-Geräte. Ihre Entitäten liegen am **einen physischen Gerät „EnOcean“**.
- Merkerbasierte Rollläden und Integrationsdiagnosen bleiben dem IO-Server zugeordnet.
- Ab **v0.4.7** erhält der IO-Server `sw_version`, `model` und `serial_number` ausschließlich aus ausdrücklich beschrifteten COMEXIO-System- oder Controller-Konfigurationsfeldern. `COMEXIO Hardware Version` bezeichnet im bekannten Dashboard das **Modell** (z. B. `IO-Server 2G`), nicht automatisch eine separate Hardware-Revision. Anders als v0.4.6 gibt es **keinen fest vorgegebenen Modell-Standardwert**. Ein zuvor nicht bekanntes Feld bleibt leer; bei vorübergehendem Abfragefehler werden bereits erkannte Controller-Werte nicht gelöscht. Die tatsächlichen Seriennummern sind private Kennungen und stehen nicht in öffentlichen Beispielen.
- Eine unklare oder doppelte Hardwarezuordnung wird nicht geraten. Bereits vorhandene fremde Geräte oder Entitäten werden nicht eigenmächtig bereinigt.

### Kanaltypen

| COMEXIO-Quelle | Home-Assistant-Darstellung | Technische Einschränkung |
| --- | --- | --- |
| `Q…` mit eindeutigem Lichtbezug | `light` | Unbekannte Relais werden nicht automatisch schaltbar |
| Manuell klassifiziertes zulässiges `Q…` | `light`, `switch` oder Statussensor | Motorrelais sind von direkter Schaltung ausgenommen |
| `R_<Name>_soll` und `R_<Name>_ist` | `cover` | Beide Marker müssen existieren und zusammenpassen |
| Freigegebener `I…`- bzw. `AI…`-Eingang | `binary_sensor` | Normale analoge Eingänge werden nicht ungefragt digitalisiert |
| EnOcean `EI…_PIRS` | `binary_sensor` | COMEXIO kann digital **oder** analog liefern; `motion` bzw. `occupancy` entsprechend dem tatsächlichen Transporttyp |
| EnOcean `EI…_CO`, Tasterkanäle | `binary_sensor` | Kontaktpolarität und Tastentelegrammfolge nicht pauschal unterstellen |
| EnOcean `EI…_ILL`, `EI…_SVC` | `sensor` | COMEXIO-Rohwerte ohne unbestätigte physikalische Einheit |

Ab v0.4.6 gilt für bereits als `binary_input` klassifizierte EnOcean- und physische Eingänge optional eine **HA-seitige Signalinvertierung**. Die Einstellung `binary_input_invert_overrides` wird in den ConfigEntry-Optionen pro stabiler Quelladresse gespeichert, standardmäßig ohne Invertierung. `ComexioInput.is_on` bildet den gelesenen Rohwert auf den HA-Zustand ab. Der Transportwert in `Runtime.values`, das Eventjournal, die COMEXIO-Webhooks und die Ereignisse `comexio_local_input` bleiben unverändert. Beim Optionswechsel wird nur das HA-State-Signal ausgelöst; keine neue Entität, kein COMEXIO-Schreibzugriff, kein Reload und keine Änderung an der Geräte-Registry. `None` bleibt `None`.

Bei EnOcean entscheidet die COMEXIO-Typinformation (`InOutputTypeId` und `ConnectionType`) über den Übertragungsmodus – nicht allein ein Suffix wie `PIRS`. Erlaubt sind `(22,2)` analog, `(23,1)` binär und seit v0.4.12 `(24,1)` **binär invertiert durch COMEXIO**. Diese letzte Einstellung wird lediglich als Kanalmetadatum (`comexio_binary_inverted`) geführt: COMEXIO hat die Werte selbst interpretiert, die HA-Verarbeitung führt **keine zweite Invertierung** aus. Eine Änderung `23↔24` löst bei erneuter manueller Discovery eine Metadaten-Aktualisierung ohne Änderung der Source-Key/Unique-ID aus; die HA-seitige `binary_input_invert_overrides`-Option ist unabhängig davon. Analoge EnOcean-Push-Werte werden im Bereich **0–1023** angenommen; die physikalische Skalierung wird nicht erfunden.

Der native OptionsFlow-Menüpunkt **Geräte & Entitäten → Erkennung jetzt aktualisieren** ruft `Runtime.refresh_discovery()` einmalig auf (wie der weiterhin verfügbare HA-Dienst `comexio_local.refresh_discovery`). Resultat sind neue/entfernte Signale und geänderte Kanalmetadaten. Keine dauerhafte Polling-Schleife, keine Änderung von COMEXIO-Web-IO, Logikplänen oder bestehenden Registry-Einträgen.

## 3. Laufende Zustandsverarbeitung

### COMEXIO → Home Assistant (Push)

COMEXIO-eigene Web-IO-Befehle senden ein JSON-Objekt an den bei der Einrichtung erzeugten Webhook:

```json
{"type":"io","ext":"EnOcean","io":"EI5_CO","value":1}
```

Für Positionsmerker wird stattdessen eine Markerquelle übertragen, sinngemäß:

```json
{"type":"marker","id":"85","value":42}
```

Der Webhook akzeptiert nur bekannte, für Push freigegebene Quellen und gültige Werte. Digitalsignale müssen `0` oder `1` sein; analoge Werte müssen endlich und innerhalb des zulässigen Bereichs liegen. Ungültige Nachrichten werden zurückgewiesen. Bei akzeptierten Ereignissen:

1. Aktualisiert `Runtime.apply_event()` den zwischengespeicherten Wert.
2. Schreibt das Ereignis in ein begrenztes, **flüchtiges** Diagnosejournal.
3. Veröffentlicht HA das Event `comexio_local_push`; geeignete Binäreingänge erzeugen zusätzlich `comexio_local_input`.
4. Aktualisieren Dispatcher-Signale die zugehörigen HA-Entitäten.

Taster liefern Rohzustände beziehungsweise Druck-/Loslassereignisse; die Integration konstruiert **keine** Doppel-, Lang- oder Kurzdruckgesten aus unvollständigen Telegrammen.

### Home Assistant → COMEXIO (Steuerung)

- **Licht / ausdrücklich freigegebene Schalter:** Ein TCP-`SET` ändert den Ausgang. Danach erfolgt ein **einmaliger TCP-`GET`**, um den tatsächlichen Zustand zu bestätigen; keine optimistische Zustandsannahme.
- **Rollläden:** HA schreibt die Sollposition auf den `R_…_soll`-Merker. Die angezeigte Istposition stammt vom separaten `R_…_ist`-Merker und dessen Zustandsmeldung.
- **Unbekannte Relais und Motor-Ausgänge:** Keine automatische, potenziell gefährliche Direktsteuerung.

Die Umrechnung der Rollladenposition zwischen COMEXIO und HA (`100 % = offen`) erfolgt über gespeicherte HA-Optionen, nicht durch Veränderung der COMEXIO-Rollladenlogik.

## 4. Push-Ressourcen und Namensräume

COMEXIO Local verwaltet zwei getrennte Familien von Web-IO-Ressourcen:

| Familie | Web-IO-Gerät/Klasse | Beispiele für Logikpläne | Zweck |
| --- | --- | --- | --- |
| **Licht/Rollläden** | `CL Push Home Assistant` | `CL Push …` | Rückmeldung von Ausgängen und Istpositionsmerkern |
| **Eingänge/EnOcean** | `CL Eingänge Home Assistant` | `CL Eingänge EnOcean Kontakte`, `CL Eingänge … I1-I18` | Eingangssignale und EnOcean-Telegramme |

Eigene Befehle heißen beispielsweise `CL Licht …` oder `CL Eingang EnOcean/EI5_CO`.

**Wichtig:** Ein Name allein beweist keine Besitzberechtigung. Eigene Logikpläne tragen einen Besitzerkommentar mit der konkreten HA-Konfigurationseintrags-ID. Vor Änderungen werden Identität, Web-IO-Gerät, Befehlsnamen, Quellen, Logikplanreferenzen und vorhandene Verbindungen kontrolliert. Mehrdeutige oder fremde Inhalte führen zum Abbruch.

### Zwei getrennte Wartungsverfahren

**Licht-/Rollladen-Push** (`push_rebuild.py`, `push_repair.py`):

- Kann einzelne fehlende Verbindungen ergänzen oder nach separater Freigabe einen vollständigen Neuaufbau eigener Ressourcen durchführen.
- Besitzt einen dauerhaft in HA gespeicherten Auftrags-Checkpoint, Fortschritt, Pause, Abbruch und kontrollierte Wiederaufnahme.
- Ein HA-Neustart setzt unterbrochene Schreibarbeiten **nicht automatisch** fort. Vor Fortsetzung wird erneut geprüft.
- Eine vollständige Bereinigung darf nur eindeutig eigene Pläne und danach das exklusive eigene Web-IO-Gerät entfernen; fremde COMEXIO-Pläne bleiben geschützt.

**Eingangs-/EnOcean-Push** (`input_push.py`):

- Arbeitet **additiv**: Bereits vorhandene passende eigene Web-IO-Befehle und Verknüpfungen werden wiederverwendet; fehlende Bestandteile werden ergänzt.
- Eingangspläne sind getrennt von den bestehenden Licht-/Rollladen-Push-Plänen.
- EnOcean-Aufträge laufen unabhängig vom Optionsdialog als HA-Aufgabe. Der Status wird **im Arbeitsspeicher**, nicht als dauerhafter Neuaufbau-Checkpoint geführt.
- Bei Fehlern oder Unterbrechung gilt: neue Vorschau, erneute bewusste Bestätigung; **keine automatische Wiederholung und keine stillschweigende Löschung**.

## 5. Sicherheitsregeln für Schreibaktionen

COMEXIO-Konfigurationsänderungen sind nicht mit einem normalen HA-Lichtschaltbefehl gleichzusetzen. Für eigene Web-IO- und Logikplanänderungen gilt:

1. **Vorschau nur lesend:** Vorab werden aktuelle Ressourcen und Änderungen ermittelt.
2. **Prüffingerabdruck:** Die Vorschau erstellt einen SHA-256-Fingerprint über die relevanten Daten. Vor dem Schreiben wird erneut gelesen; bei abweichendem Fingerprint erfolgt keine Änderung.
3. **Explizite Bestätigung:** Die Schreibaktion erfordert eine Bestätigung einer vorhandenen COMEXIO-Konfigurationssicherung. Für den destruktiven Licht-/Rollladen-Neuaufbau ist zusätzlich die Löschung ausdrücklich freizugeben.
4. **Eigentums- und Strukturprüfung:** Fremde, doppelte, umbenannte oder widersprüchliche Ressourcen werden nicht stillschweigend übernommen.
5. **Gedrosselte Schreibzugriffe:** HTTP-Konfigurationsänderungen erfolgen serialisiert. Der Eingangs-Push erhöht den Schreibabstand auf mindestens zwei Sekunden; der geführte Neuaufbau nutzt ebenfalls einen konservativen Abstand.
6. **Kein automatisches Rollback-Versprechen:** Ein Abbruch kann bereits angelegte **eigene** Ressourcen hinterlassen. Der nächste Durchlauf beginnt deshalb mit einer frischen Bestandsaufnahme statt mit einem unkontrollierten Wiederholen.

### Rücklesedaten und `callback_unverified`

COMEXIO-Firmware kann einzelne Felder eines Web-IO-Befehls in der maschinenlesbaren Konfiguration auslassen, obwohl sie im Studio-Editor vorhanden sind. Die Eingangs-Push-Prüfung unterscheidet deshalb:

| Beobachtung | Konsequenz |
| --- | --- |
| Feld vorhanden und korrekt | Wert ist insoweit verifiziert |
| `Data`, `HeaderModifier`, Grenzwerte oder `Parameter` in der Rücklesung teilweise nicht sichtbar | Das betreffende Feld bleibt **nicht verifiziert**; die gezielt begrenzte Eingangs-Einrichtung kann unter weiteren Identitäts-/Typprüfungen fortfahren |
| Auslesbarer Header, Lua-Inhalt, Zielpfad, Typ oder Wertebereich widerspricht dem Erwarteten | **Abbruch**, keine weitere Änderung |

`callback_unverified` ist die **Anzahl der Befehle mit unvollständig verifizierbarer Rücklesung**. Es ist weder eine Fehlerquote noch ein Beweis für eine fehlende Zustandsübertragung. `completed` bedeutet, dass der Auftrag die vorgesehenen Bestands- und Verknüpfungsprüfungen abgeschlossen hat. Ob das Signal tatsächlich im HA-Zustand ankommt, zeigt erst ein **realer Ereignistest**.

## 6. Kommunikation und Sicherheit

- **HTTP-Adminzugriff:** Lokaler COMEXIO-Webzugang mit administrativer Anmeldung; für die geprüfte Firmware verwendet `ComexioAdmin` das RSA-basierte Loginverfahren der Geräteoberfläche.
- **TCP-JSON:** Standardport `1505` (konfigurierbar), je Anfrage eine kurzlebige Verbindung, JSON-Nachricht mit Zeilenumbruch, begrenzte Laufzeit und Mindestabstand zwischen Anfragen.
- **Push-Ziel:** Nur HTTP-URLs mit privater IPv4-Adresse und explizitem Port werden für die Einrichtung akzeptiert. Öffentliche Adressen, Loopback und URLs mit Zugangsdaten oder zusätzlichen Pfaden werden abgewiesen.
- **Webhook:** HA erzeugt pro Konfigurationseintrag eine schwer erratbare ID und registriert den Webhook mit `local_only=True`. Der empfangene JSON-Body ist auf **4096 Byte** begrenzt; unbekannte Quellen und ungültige Werte werden verworfen.
- **Anmeldedaten:** Der COMEXIO-Adminzugang liegt im Home-Assistant-Konfigurationseintrag. Der Schutz der HA-Konfigurationsdateien und Sicherungen ist deshalb sicherheitsrelevant. Es wird **keine automatische Verschlüsselung dieser gespeicherten Zugangsdaten behauptet**.
- **Transport:** HTTP und die TCP-API sind **nicht durch TLS abgesichert**. Die Integration gehört in ein kontrolliertes, vertrauenswürdiges lokales Netzwerk; den Webhook nicht ins Internet veröffentlichen.
- **Protokollierung:** Abgelehnte Webhooks werden mit einem Fehlergrund protokolliert, nicht mit ihrem vollständigen Body oder der geheimen Webhook-Adresse.

## 7. Home-Assistant-Speicherung und Lebenszyklus

| Daten | Speicherort bzw. Lebensdauer |
| --- | --- |
| Serveradresse, TCP-Port, Adminzugang, Push-Basisadresse, Webhook-ID | HA-ConfigEntry (`entry.data`) |
| Individuelle Klassifizierungen, Eingangsart, Rollladenrichtung | HA-Optionen (`entry.options`) |
| Geräte, Entitäten, Bereiche, eigene Namen | HA-Geräte-/Entitäts-/Bereichsregistrierung |
| Licht-/Rollladen-Neuaufbau-Checkpoint | HA-`Store`, Schlüssel `comexio_local_push_rebuild_<entry_id>` |
| EnOcean-/Eingangs-Push-Auftragsstatus, letzte Ereignisse, aktuelle Werte | `Runtime` im Speicher; nach Neustart erneut aufgebaut bzw. geleert |

Beim Entladen stoppt die Integration aktive eigene Aufträge, entlädt Plattformen und registriert den Webhook ab. TCP-Verbindungen werden je Anfrage beendet.

**Keine manuelle Bearbeitung der HA-`.storage`-Dateien als regulärer Wartungsweg:** Dafür stehen die vorgesehenen HA-Registrierungen, Optionsflows und Dienste zur Verfügung. Die Integration enthält keine automatischen Routinen zur Bereinigung historischer EnOcean-Platzhaltergeräte.

## 8. Diagnose und öffentliche Schnittstellen

### Home-Assistant-Dienste

Die folgenden Services sind in `__init__.py` und `services.yaml` registriert (Aufruf über `comexio_local.<dienst>`):

| Dienst | Wirkung |
| --- | --- |
| `refresh_discovery` | COMEXIO-Katalog neu lesen und Zustand einmalig aktualisieren |
| `snapshot_once` | Einmalige TCP-Zustandsabfrage |
| `push_diagnose` | Lesende Prüfung der Push-Topologie |
| `get_push_events` | Flüchtiges Journal akzeptierter Push-Ereignisse, ohne COMEXIO-Abfrage |
| `preview_push_repair` / `repair_push` | Vorschau / bestätigte gezielte Licht-/Rollladen-Reparatur |
| `preview_push_rebuild` / `start_push_rebuild` | Vorschau / bestätigter vollständiger Neuaufbau |
| `get_push_rebuild_status` / `control_push_rebuild` | Fortschritt bzw. Pause/Fortsetzung/Abbruch |
| `configure_push` | Kompatibilitätsdienst: benutzt den vorhandenen Reparatur-Worker, keinen zweiten Schreiber |

Bei mehreren COMEXIO-Installationen muss gegebenenfalls `entry_id` angegeben werden. **Schreibende Dienste nicht ohne aktuelle Vorschau und die geforderte Bestätigung aufrufen.** Die Eingangs-/EnOcean-Einrichtung erfolgt über den Konfigurationsdialog, nicht über einen separat öffentlich registrierten Eingangs-Service.

### Diagnose-Entitäten und Ereignisse

Die Integration stellt u. a. die Zahl erkannter Kanäle, akzeptierte/abgewiesene Push-Ereignisse, das aktuelle Ereignisjournal, den Eingangs-Push-Auftrag und den Licht-/Rollladen-Neuaufbau-Fortschritt als HA-Diagnose-Entitäten bereit.

| HA-Event | Bedeutung |
| --- | --- |
| `comexio_local_push` | Jedes gültig akzeptierte Push-Ereignis einer bekannten Quelle |
| `comexio_local_input` | Zustands-/Tasteraktion eines passenden Binäreingangs |

Ein sinnvolles Diagnoseverfahren unterscheidet **Kanal erkannt**, **Web-IO-Befehl vorhanden**, **Plan verbunden/aktiv**, **Webhook-Ereignis in HA angekommen** und **HA-Zustand aktualisiert**. Eine positive Aussage auf einer früheren Stufe beweist die spätere Stufe nicht.

## 9. Codeübersicht für Mitwirkende

Alle Pfade beziehen sich auf `custom_components/comexio_local/`:

| Modul | Zuständigkeit |
| --- | --- |
| `__init__.py`, `config_flow.py` | HA-Setup, Webhook, Dienste, Konfigurations- und Optionsdialoge |
| `runtime.py` | Zentrales Laufzeitmodell, Zustände, Ereignisverarbeitung, Koordination |
| `admin_api.py`, `tcp_client.py` | HTTP-Adminprotokoll bzw. TCP-JSON-Protokoll |
| `discovery.py`, `hardware_devices.py`, `device_metadata.py` | Kanal-/Modulerkennung, physische HA-Gerätezuordnung |
| `entity_sync.py`, `preferences.py`, `area_assignment.py` | Entitätsabgleich, HA-seitige Optionen, Bereichszuordnung |
| `light.py`, `switch.py`, `cover.py`, `binary_sensor.py`, `sensor.py` | HA-Entitätsplattformen |
| `webio_command.py`, `managed_resources.py`, `managed_graph.py` | Web-IO-Kommandoschema, Besitzprüfung, Planverbindungen |
| `input_push.py` | Eingangs- und EnOcean-Push-Vorschau und -Einrichtung |
| `push_repair.py`, `push_rebuild.py`, `push_cleanup.py`, `push_audit.py` | Licht-/Rollladen-Push-Reparatur, Neuaufbau, Bereinigung und Prüfung |
| `push_journal.py`, `error_text.py` | Ereignisdiagnose und begrenzte, sichere Fehlermeldungen |

Die Tests liegen unter `tests/`. v0.4.5 besteht **347 automatisierte Offline-Tests**; der zugrunde liegende v0.4.4-HeaderFix bestand 333. Diese prüfen Programmverhalten mit Testdaten und Fake-Implementierungen; sie ersetzen keinen Test am echten COMEXIO-Gerät.

## 10. Verifizierter Stand und offene Punkte

**Praktisch bestätigt:** Die bestehende Licht-Push-Einrichtung aus v0.4.3 funktionierte am realen COMEXIO-Server. Für den v0.4.4-HeaderFix wurden danach EnOcean-Push-Ereignisse von **Türkontakt `EI5_CO`** und **PIR `EI4_PIRS`** bis in Home Assistant beobachtet. Damit ist der Ende-zu-Ende-Datenweg für diese Beispiele nachgewiesen.

**Nicht pauschal bestätigt:** Alle übrigen EnOcean-Signale, beliebige andere COMEXIO-Firmwarestände, die Skalierung von `ILL`/`SVC`, die Polarität aller Kontaktmeldungen und sämtliche möglichen Tastentelegrammfolgen. `EI3_PIRS` war Teil des Einrichtungsauftrags, ist dadurch aber nicht automatisch als real getestet zu werten.

**In v0.4.5 umgesetzt (Praxistest der UI noch offen):**

- Der Eingangs-Push-Statusdialog verwendet bei `running` **Aktualisieren** und bei `completed`/`failed` **Schließen**.
- Der Eingangs-Menübereich trennt **physische I-/AI-Eingänge** und **EnOcean-Kanäle**; nur die physischen Eingänge benötigen die Wahl zwischen Taster und Schalter.
- Die Abschlussanzeige nennt geprüfte Quellen, ergänzte Web-IO-Befehle/Verknüpfungen und nicht vollständig verifizierte Rücklesedaten in verständlicher Form.
- Die Hauptmenüs und Untermenüs enthalten kurze Beschreibungen. Änderungen an der Push-Implementierung waren dafür nicht erforderlich.

Das Entwicklungsprinzip bleibt: **Erst konkrete Ursache belegen, dann klein und gezielt korrigieren; funktionierende COMEXIO-Ressourcen nicht unnötig anfassen.**


## v0.4.10: typbasierte Eingangspläne und HA-Konfiguration

- Ein eigener Eingangs-Web-IO-Befehl pro EI-Kanal bleibt wegen der jeweiligen Callback-Quelladresse erforderlich. Es wird jedoch **kein eigener Logikplan pro `EI`-Teilnehmer** mehr erstellt. Die Gruppierung anhand des stabilen EI-Signal-Suffixes unterscheidet Taster (`A0/AI/B0/BI`), Kontakte (`CO`), Bewegung/Präsenz (`PIRS`), Helligkeit (`ILL`), Versorgung (`SVC`) sowie unbekannte analoge/digitale Signale. `InOutputTypeId=22/23/24` beschreibt Analog-, Binär- beziehungsweise in COMEXIO invertierten Binärtransport, nicht die semantische Sensorart.
- Die Anlagereihenfolge neuer Signale verwendet freie, hinter bestehende Bausteinpositionen angehängte Rasterplätze. Alle 18 Zeilen beginnt eine weitere Spalte. Es gibt keine künstliche Plananzahlbegrenzung nach Teilnehmerplätzen; die reale Firmware-Ressourcengrenze ist unbekannt.
- Die alte eigene Planfamilie `CL Eingänge EnOcean EI<n>` wird nicht automatisch migriert oder gelöscht. Vor neuen EnOcean-Schreibaufträgen ist ein ausdrücklich freigegebener, gezielter manueller Clean-Cut dieser Pläne und ihrer eigenen EI-Befehle erforderlich. Die Web-IO-Klasse `CL Eingänge Home Assistant` wird zwischen EI und physischen I/AI gemeinsam genutzt. Fremde, produktive und Licht-/Rollladen-Ressourcen dürfen nicht bereinigt werden.
- Der native OptionsFlow gliedert sich in fünf Abschnitte. Ein neuer Verbindungseinstellungsdialog prüft die gewünschte COMEXIO-Adresse lesend. Bei IP-Wechsel des **gleichen** physischen Servers bleibt die historische HA-ConfigEntry-`unique_id` erhalten, weil sie bestehende Entity-/Device-Identifiers beeinflusst. Keine automatische Web-IO-Zieländerung.
- Die neuen Push-Menüs unterscheiden rein lesenden COMEXIO-Graphstatus und tatsächlich angenommene EI-Ereignisse aus dem vorhandenen 80-Ereignis-RAM-Journal. Der Erfolg eines Neuaufbauauftrags bestätigt keinen realen Sensor-Push. Keine zusätzlichen periodischen Abfragen.
- Relevante Offline-Regressionen: initialer Typplan, späterer Zusatz von weiteren 19 Kanälen in denselben Plan (insgesamt 21), unveränderte Quellenpositionen, Idempotenz, Schutz bestehender Lichtpläne, Altplan-Sperre, sprachabhängige UI-Menüs und Verbindungsidentität. Firmware-/HA-Praxistest steht aus.
