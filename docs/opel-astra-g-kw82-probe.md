# Historischer Hinweis: früherer KW82-Probe-Modus

Diese Datei beschreibt einen frühen experimentellen Ansatz und ist **nicht mehr der aktuelle Protokollstand**.

Messungen am realen 1999er Opel Astra G X16XEL haben inzwischen eindeutig gezeigt, dass das Motorsteuergerät über **ISO 14230-4 KWP2000 Fast Init** angesprochen wird.

Verifiziert wurden:

- Fahrzeug-DLC Pin 7
- ECU-Adresse 0x11
- Tester-Adresse 0xF1
- Fast Init
- KWP-Keywords EF 8F
- StartCommunication 0x81 / positive Antwort 0xC1
- ECU-Identifikation 0x1A80
- Live-Daten 0x2101
- DTC-Lesen 0x1800FF00
- DTC-Löschen 0x14FF00

Die aktuelle Dokumentation befindet sich in:

**docs/opel-astra-g-x16xel-kwp2000.md**

Der historische Settings-Token OPEL_KW82_9600 bleibt vorerst aus Kompatibilitätsgründen erhalten. Er bezeichnet intern heute das verifizierte KWP2000-Profil und wird nicht als Benutzerbezeichnung angezeigt.
