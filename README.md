# COMEXIO Local v0.1.0 - eigenstaendige Home-Assistant-Integration

**Status:** Erster vollstaendiger Entwicklungsstand, offline getestet. Noch nicht auf dem realen Home-Assistant-System installiert oder gegen die Firmware 11.1.4 live getestet.

## Ziel

Diese Integration verbindet COMEXIO IO-Server 2G (Firmware 11.1.4 als Zielumgebung) mit Home Assistant ueber die lokale JSON-TCP-API, **Port 1505**. Sie ist bewusst wesentlich einfacher als `kayl-codes/homeassistant-comexio`.

- 16 bereits dokumentierte physische Licht-Relaisausgaenge (eine feste Zuordnungstabelle)
- **Eine gemeinsame GET-Anfrage fuer alle aktiven Ausgaenge pro Intervall** statt Einzelabfragen im Sekundentakt
- Initiale Statusabfrage und regelmaessiger Abgleich; Zustand nach physischem Tastendruck beim naechsten Intervall
- Ausgangszustaende nur aus echten `GET`-Antworten, nicht aus optimistischen Schaltbefehlen
- Direkte `SET`-Schaltbefehle **nur nach bewusster Aktivierung** in den Integrationsoptionen
- Kurze TCP-Verbindungen, eine Request-Sperre, 250 ms Minimalabstand, 5 s Timeout
- Keine automatischen Konfigurationsaenderungen an COMEXIO; keine Web-IO-, Merker- oder Logikplan-Erzeugung
- Diagnose-Sensoren fuer Anzahl Requests, Fehler und letzte TCP-Latenz
- Setup und Optionen direkt in Home Assistant

## Sicherheits- und Funktionsgrenzen

1. **Read-only ist voreingestellt.** Die 16 Lichtzustaende werden als `binary_sensor` in Home Assistant sichtbar. Erst mit `allow_writes` erscheinen sie als schaltbare `light`-Entitaeten.
2. **Wichtig:** Bestehende COMEXIO-Stromstoss-/RS-Bausteine steuern die Lichtausgaenge. Ein `SET` direkt auf das Relais kann deren internen Zustand umgehen oder durch die Logik ueberschrieben werden. Die Integration kann diese Wirkung nicht ausschliessen. Direktes Schreiben nur aktivieren, wenn das bestehende Verhalten dafuer geeignet ist. Keine automatische Manipulation der bestehenden Logik.
3. Die alte Integration ist nicht Teil dieses Pakets und sollte deaktiviert bleiben. Die neue Integration erzeugt keinerlei COMEXIO-Bausteine.
4. **Das TCP-GET fuer einen Ausgang wurde am echten System bestaetigt:** `{"licht":0}` (und nach physischem Tastendruck `1`). Dass mehrere GET-Elemente innerhalb eines einzigen TCP-JSON-Objekts von Firmware 11.1.4 verarbeitet werden, ergibt sich aus dem dokumentierten JSON-API-Schema sowie den vorhandenen Mehrfach-SET-Nachrichten von Node-RED; **es ist am echten IO-Server noch nicht separat bestaetigt.** Bei unerwarteter Antwort wiederholt der Code nicht automatisch alle 16 Abfragen einzeln.
5. Polling ist **kein Push**. Ein lokaler Tastendruck wird nach hoechstens einem regulaeren Abfrageintervall sichtbar, vorausgesetzt Netzwerk und Server antworten normal. Standard: 15 s. Das Intervall ist zwischen 5 und 300 s einstellbar. Echtzeit-Web-IO kann spaeter optional hinzukommen, ohne die TCP-Basis neu zu bauen.
6. Die drei Treppenhaus-Shellys sind **nicht Teil** der 16 COMEXIO-Relaisausgaenge und sollten ueber ihre jeweilige native Shelly-Anbindung behandelt werden.
7. Keine Rollladen- oder Markisenfahrten in dieser Version; die Soll-/Ist-Merker bleiben unangetastet.
8. Das Verzeichnis enthaelt keinen Netzwerkmitschnitt oder Zugangsdaten. Keine API-Konfiguration von COMEXIO wird veraendert.

## Einbindung in Home Assistant

Das ZIP ist ein vollstaendiges Custom-Integration-Quellpaket mit `hacs.json`. **HACS kann das ZIP selbst nicht als Repository installieren**; fuer HACS muss der Code zuerst in ein GitHub-Repository gestellt werden. Fuer einen lokalen Test reicht die direkte Installation:

1. Den Ordner `custom_components/comexio_local` in den HA-Konfigurationsordner `/config/custom_components/comexio_local` kopieren.
2. Home Assistant neu starten.
3. Unter *Einstellungen > Geraete & Dienste > Integration hinzufuegen* nach **COMEXIO Local** suchen.
4. Vorgegebener Host `192.168.10.254`, TCP-Port `1505`, Intervall `15` Sekunden. Die 16 aus den Logikplaenen dokumentierten Ausgaenge sind vorausgewaehlt.
5. **Direkte Schreibbefehle sind aus Sicherheitsgruenden standardmaessig deaktiviert.** Bei Bedarf ueber die Integrationsoptionen explizit aktivieren.

Nach einer Optionsaenderung wird der Eintrag neu geladen. Beim Wechsel zwischen lesendem und schreibendem Modus wechselt die Entitaetenplattform zwischen `binary_sensor` und `light`; nicht mehr aktive Registry-Eintraege lassen sich bei Bedarf in Home Assistant entfernen.

## Lichtkatalog

Die 16 physischen Relaisausgaenge werden aus den bereitgestellten COMEXIO-Raumplaenen uebernommen. Die Bezeichnungen an den Hardware-IOs koennen veraltet sein (z. B. ehemalige Kind-1/Kind-2-Bezeichnungen).

| HA-Bezeichnung | COMEXIO-Ausgang |
| --- | --- |
| Wohnzimmer Hauptlicht | IO-Ext-2#Q4 |
| Wohnzimmer LED | IO-Ext-2#Q5 |
| Wohnzimmer indirekt | IO-Ext-2#Q6 |
| Esszimmer Hauptlicht | IO-Ext-2#Q7 |
| Esszimmer indirekt | IO-Ext-2#Q8 |
| Kueche Licht | IO-Ext-2#Q9 |
| Schlafzimmer Licht | IO-Ext-3#Q7 |
| Kinderzimmer Licht | IO-Ext-2#Q3 |
| Gaestezimmer Licht | IO-Ext-2#Q1 |
| Buero Licht | IO-Ext-2#Q2 |
| Wannenbad Licht | IO-Ext-1#Q7 |
| Duschbad Licht | IO-Ext-1#Q4 |
| Gaeste-WC Licht | IO-Ext-1#Q1 |
| Flur Licht | IO-Server-1#Q1 |
| Bibliothek Licht | IO-Server-1#Q2 |
| Kleiner Flur Licht | IO-Server-1#Q3 |

## Protokoll

GET-Beispiel (ein Ausgang):

```json
{"licht":{"action":"get","ext":"IO-Ext-2","io":"Q1"}}
```

COMEXIO-Antwort:

```json
{"licht":0}
```

Batched GET (alle ausgewaehlten Ausgaenge, genau eine TCP-Nachricht):

```json
{"c0":{"action":"get","ext":"IO-Ext-2","io":"Q4"},"c1":{"action":"get","ext":"IO-Ext-2","io":"Q5"}}
```

Erwartete Antwort mit denselben Schluesseln:

```json
{"c0":0,"c1":1}
```

Alle JSON-Anfragen und -Antworten werden mit `\n` terminiert. Keine Dauerverbindung. Bei Netzwerkproblemen werden keine unkontrollierten Wiederholungsschleifen gestartet.

## Offline-Tests

In der Wurzel des Pakets ausfuehren:

```shell
python -m unittest discover -s tests -v
```

Der Fake-TCP-Server testet Batch-GET, reale Zustandsaenderung im simulierten COMEXIO, SET + GET, fehlende Kanalausgaenge, Protokollwerte und einen Verbindungsfehler ohne Retry. Python-Syntax wird ebenfalls geprueft. **Eine echte HA-/COMEXIO-Laufzeitpruefung kann dieser Offline-Test nicht ersetzen.**

## Quellen

- Node-RED-Export `Eingefuegter Text(1).txt` (bestehender TCP-API-Flow, Port 1505, SET und Rate-Limit)
- Bestaetigte GET-Antwort aus dem Chat vom 02.11.2026
- Projektstand `COMEXIO_HACS_Integration_Projektstand_v0.1.md` und 16 COMEXIO-Logikplan-PDFs
- COMEXIO-API-Dokumentation und offizielle Handbuecher
- Home-Assistant-Entwicklerdokumentation fuer Config Flow, Coordinator und Light/Binary Sensor
- Externe Referenzintegration `kayl-codes/homeassistant-comexio` zur Orientierung; **kein kopierter Fremdcode**
