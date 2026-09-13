# Easy-/Expert-Modus und geführte Diagnose

Ab Version 3.2 besitzt die Anwendung zwei Bedienebenen. Beide verwenden denselben Diagnosekern und dieselben Messdaten. Der Easy-Modus ist keine zweite Diagnoseimplementierung, sondern eine vereinfachte Oberfläche über den vorhandenen Transport-, DTC-, Live-Daten- und CSV-Funktionen.

## Startauswahl

Beim Programmstart erscheint eine Auswahl:

- **Geführter Assistent / Easy** für eine möglichst einfache Diagnose.
- **Expertenmodus / Expert** für Rohdaten, Protokollauswahl, Diagnosekommandos, Tests und erweiterte Einstellungen.

Oben im Hauptfenster bleibt dauerhaft eine kompakte Umschaltung **Expert | Easy** sichtbar. Zwischen den Modi kann jederzeit gewechselt werden.

## Geführte Verbindung

Der Verbindungsassistent trennt zuerst bewusst zwischen:

- **ELM327 USB**
- **ELM327 Bluetooth**

Danach folgt die zur Verbindung passende Einrichtung. Erst wenn ein echter serieller Port vorhanden ist, geht es weiter zur Fahrzeug-/Schnittstellenauswahl.

Anschließend:

1. Fahrzeug-/Schnittstellenprofil auswählen oder **Automatisch erkennen** verwenden.
2. Verbindungs- und Erkennungsstatus beobachten.

Bei automatischer Erkennung werden derzeit nacheinander Standard-OBD-II-Protokolle und anschließend bekannte herstellerspezifische Profile getestet. Jeder Versuch wird im Statusfenster angezeigt.

Für den verifizierten Opel Astra G X16XEL/Multec-H wird nach den Standardversuchen die bekannte KWP2000-Fast-Init-Verbindung auf K-Line geprüft.

## ELM327 USB

1. ELM327 mit USB verbinden.
2. Adapter am Fahrzeug einstecken und Zündung einschalten.
3. Seriellen COM-/tty-Port auswählen.
4. Falls der Port noch nicht sichtbar ist, **Ports aktualisieren** verwenden.

## ELM327 Bluetooth

### Windows

1. ELM327 am Fahrzeug einstecken und Zündung einschalten.
2. Im Assistenten **Windows-Bluetooth-Einstellungen öffnen** wählen.
3. ELM327 koppeln. Bei einfachen Bluetooth-SPP-Adaptern werden häufig PIN **1234** oder **0000** verwendet.
4. Zum Assistenten zurückkehren und **Ports aktualisieren** verwenden.
5. Den von Windows erzeugten Bluetooth-COM-Port auswählen. Falls Windows mehrere Bluetooth-COM-Ports erzeugt, ist normalerweise der ausgehende serielle Port relevant.

Windows stellt klassische Bluetooth-SPP-Verbindungen als COM-Port bereit. Die Diagnoseanwendung übernimmt deshalb nicht selbst das Betriebssystem-Pairing, sondern führt den Benutzer gezielt durch den Pairing-Schritt und übernimmt danach den erzeugten seriellen Port.

### Linux

1. ELM327 am Fahrzeug einstecken und Zündung einschalten.
2. Adapter über die Desktop-Bluetooth-Einstellungen oder bluetoothctl koppeln.
3. Im Assistenten **Gekoppelte Bluetooth-Geräte suchen** verwenden.
4. ELM327 auswählen.
5. RFCOMM-Kanal wählen; Kanal 1 ist bei vielen einfachen ELM327-SPP-Adaptern üblich.
6. **Bluetooth-Seriell-Port erstellen** wählen.

Der Assistent verwendet dabei den bereits vorhandenen BlueZ-/RFCOMM-Unterbau und legt standardmäßig /dev/rfcomm0 an. Anschließend wird dieser Port automatisch in die Portauswahl übernommen.

## Easy-Modus

Der Easy-Modus zeigt absichtlich nur zwei Diagnose-Tabs.

### Fehlerspeicher

- Fehlerspeicher auslesen
- Fehlercode anzeigen
- lokalisierte Bedeutung aus der Repo-Datenbank anzeigen
- Fehlerspeicher nach Bestätigung löschen

Beim Opel-X16XEL-Profil werden die verifizierten KWP2000-Dienste verwendet. Bei generischem OBD-II verwendet der normale Diagnosekern die Standarddienste.

### Live-Daten

Das aktive Fahrzeugprofil liefert Mess-Presets aus JSON. Beispiele beim X16XEL:

- Forum - Basiswerte
- AGR / EGR Diagnose
- Kaltstart
- Ladesystem
- Alle verifizierten Live-Daten

Das Preset bestimmt nur, welche bekannten Messwerte angezeigt und aufgezeichnet werden. Es verändert nicht die ECU.

Der Easy-Tab zeigt:

- aktuelle Werte in einer Tabelle,
- einen eigenen kleinen Plot pro Messwert,
- Start/Stop der vorhandenen CSV-Aufzeichnung,
- CSV-Export,
- PNG-Export der aktuellen Easy-Ansicht.

## Datenstruktur

Fahrzeugwissen soll nicht im GUI-Code fest verdrahtet werden.

~~~text
data/
  dtc_codes.json
  vehicles/
    generic_obd2.json
    opel_astra_g_x16xel_multec_h.json

locales/
  de.json
  en.json
~~~

### Fahrzeugprofile

Ein Fahrzeugprofil enthält unter anderem:

- Anzeigename,
- Hersteller,
- Schnittstelle/Transport,
- ggf. herstellerspezifischen Protokoll-Token,
- verfügbare Live-Daten,
- Einsteiger-Presets,
- Zuordnung zur DTC-Datenbank.

### Fehlerdatenbank

data/dtc_codes.json verknüpft Hersteller + DTC mit einem deutschen und englischen Erklärungstext. Unbekannte Fehler dürfen niemals unterdrückt werden; sie werden weiterhin als Code angezeigt, auch wenn noch kein Beschreibungstext vorhanden ist.

## Nächste Architekturphase

Der bestehende Expert-Plot wird anschließend modularisiert. Ziel ist:

- Plot hinzufügen/entfernen,
- Messwerte per Drag & Drop einem Plot zuweisen,
- PID-/Messwertkatalog als eigener Tab,
- benutzerdefinierte PIDs/Messwerte,
- fahrzeugspezifische Verfügbarkeitsprofile in JSON,
- getrennte Anzeige-/Plot-Presets.

Diese Erweiterung soll auf derselben Sample-Pipeline aufsetzen, die bereits Dashboard, Easy-Modus, CSV und Opel-KWP2000 versorgt.
