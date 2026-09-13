# Opel Astra G X16XEL / Multec-H - verifiziertes KWP2000-Profil

## Fahrzeug und Steuergerät

Das Profil wurde an einem realen Opel Astra G, Baujahr 1999, X16XEL, Automatik verifiziert.

Die ECU-Identifikation lieferte unter anderem:

~~~text
VIN:            W0L0TGF35Y2071756
Lieferant:      DEL 0109355289
Opel HW:        09355919 DM
Software:       CLPP
Version:        0001
Freigabe:       D98007
Motor/System:   X16XEL
Kalibrierung:   P1299A01
~~~

## Physikalische Verbindung

Für das Motorsteuergerät:

~~~text
DLC K-Line:      Pin 7
KWP Zieladresse: 0x11
Testeradresse:   0xF1
Protokoll:       ISO 14230-4 KWP2000 Fast Init
Keywords:        EF 8F
~~~

Das Automatikgetriebe verwendet beim Astra G eine andere Diagnoseleitung. Fahrzeug-K-Lines dürfen nicht einfach miteinander gebrückt werden.

## Sessionaufbau

Verifizierte StartCommunication-Sequenz:

~~~text
ATSP5
ATSH8111F1
ATFI
81
~~~

Reale positive Antwort:

~~~text
83 F1 11 C1 EF 8F C4
~~~

0xC1 ist die positive Antwort auf StartCommunication 0x81.

## ECU-Identifikation

Request:

~~~text
1A80
~~~

Positive Nutzdaten beginnen mit:

~~~text
5A 80 ...
~~~

Der reale Identifikationsblock enthielt VIN, Delco-/Opel-Hardwarekennung, Software, Motorcode und Kalibrierung.

## Live-Daten

Request:

~~~text
2101
~~~

Ein realer Antwortframe bei ungefähr 3000 rpm:

~~~text
B2 F1 11 61 01 03 14 05 20 04 00 30 3B 8C 00 58 38 6C 98 19 09 0C
00 00 00 00 23 03 00 7A 2B 7F EB EA B4 80 07 7F 02 00 95 00 00 82 08
80 D4 A2 00 00 00 00 27 26
~~~

Der Parser interpretiert nur bereits verifizierte bzw. stark gegengeprüfte Werte. Beispiele:

- Drehzahl: Frame-Byte 30, X * 25 rpm; 0x7A ergibt 3050 rpm
- Bordspannung: Frame-Byte 14, X / 10 V; 0x8C ergibt 14,0 V
- MAP: Frame-Byte 13, X * 104 / 255 kPa
- Kühlmitteltemperatur
- Ansauglufttemperatur
- Zündwinkel
- Motorlast
- Drosselklappenstellung
- Geschwindigkeit
- Lambdasondenspannung

Unbekannte Bytes bleiben absichtlich unbenannt, bis sie am Fahrzeug oder durch belastbare Unterlagen bestätigt sind.

## Fehlerspeicher lesen

Request:

~~~text
1800FF00
~~~

Reale Antwort:

~~~text
8B F1 11 58 03 14 05 20 04 00 30 18 13 38 B8
~~~

Dekodiert:

~~~text
P1405  Status 0x20
P0400  Status 0x30
P1813  Status 0x38
~~~

Der Antwortaufbau ist:

~~~text
58 <Anzahl> <DTC_H> <DTC_L> <Status> ...
~~~

Das Statusbyte wird vollständig erhalten. Herstellerverwendete Bits werden nicht stillschweigend verworfen.

## Fehlerspeicher löschen

Request:

~~~text
14FF00
~~~

Reale positive Antwort:

~~~text
83 F1 11 54 FF 00 D8
~~~

Anschließende Kontrollabfrage:

~~~text
1800FF00
82 F1 11 58 00 DC
~~~

Damit wurde das erfolgreiche Löschen am Fahrzeug bestätigt.

## Softwarearchitektur

Der aktive Protokollcode liegt in:

- opel_kwp2000.py
- opel_multec_profile.py

Fahrzeug-/Easy-Mode-Daten liegen getrennt davon in:

- data/vehicles/opel_astra_g_x16xel_multec_h.json
- data/dtc_codes.json
- locales/de.json
- locales/en.json

Der historische Settings-Token OPEL_KW82_9600 wird nur zur Abwärtskompatibilität beibehalten. Neue Implementierungen sollen ihn nicht als Protokollbeschreibung interpretieren.

## Sicherheit

Normales Live-Daten- und DTC-Lesen ist read-only. Das Löschen des Fehlerspeichers wird in der Benutzeroberfläche bestätigt und kann Readiness-/Fehlerhistorie zurücksetzen. Coding, Security Access, Speicherprogrammierung und Aktuatortests sind nicht Bestandteil dieses Profils.
