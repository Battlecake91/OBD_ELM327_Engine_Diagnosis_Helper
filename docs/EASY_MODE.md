# Easy-/Expert-Modus und geführte Diagnose

Ab Version 3.2 besitzt die Anwendung zwei Bedienebenen. Beide verwenden denselben Diagnosekern und dieselben Messdaten. Der Easy-Modus ist keine zweite Diagnoseimplementierung, sondern eine vereinfachte Oberfläche über den vorhandenen Transport-, DTC-, Live-Daten- und CSV-Funktionen.

## Startauswahl

Beim Programmstart erscheint eine Auswahl:

- **Geführter Assistent / Easy** für eine möglichst einfache Diagnose.
- **Expertenmodus / Expert** für Rohdaten, Protokollauswahl, Diagnosekommandos, Tests und erweiterte Einstellungen.

Oben im Hauptfenster bleibt dauerhaft eine kompakte Umschaltung **Easy | Expert** sichtbar. Zwischen den Modi kann jederzeit gewechselt werden.

## Geführte Verbindung

Der Verbindungsassistent arbeitet in drei Schritten:

1. Adapter bzw. seriellen Port auswählen.
2. Fahrzeug-/Schnittstellenprofil auswählen oder **Automatisch erkennen** verwenden.
3. Verbindungs- und Erkennungsstatus beobachten.

Bei automatischer Erkennung werden derzeit nacheinander Standard-OBD-II-Protokolle und anschließend bekannte herstellerspezifische Profile getestet. Jeder Versuch wird im Statusfenster angezeigt.

Für den verifizierten Opel Astra G X16XEL/Multec-H wird nach den Standardversuchen die bekannte KWP2000-Fast-Init-Verbindung auf K-Line geprüft.

## Bluetooth-ELM327

Der Assistent zeigt abhängig vom Betriebssystem eine Kurzanleitung.

### Windows

1. ELM327 am Fahrzeug einstecken.
2. Zündung einschalten.
3. Adapter in **Bluetooth & Geräte** koppeln.
4. Bei einfachen SPP-Adaptern werden häufig PIN **1234** oder **0000** verwendet.
5. Den von Windows erzeugten COM-Port im Assistenten auswählen.

### Linux

1. ELM327 am Fahrzeug einstecken und Zündung einschalten.
2. Adapter über die Desktop-Bluetooth-Einstellungen oder bluetoothctl koppeln.
3. Danach kann ein RFCOMM-Port verwendet bzw. von der vorhandenen Linux-Hilfe angelegt werden.

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
