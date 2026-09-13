# Experimental Opel Astra G KW82 probe

This mode is intended for early Opel/Vauxhall vehicles that have the 16-pin DLC but do not necessarily provide standard EOBD/SAE J1979 diagnostics.

The initial target is the 1999 Astra G X16XEL engine ECU on the vehicle K-line at DLC pin 7.

## What the probe does

The program deliberately does **not** send the normal `0100` OBD-II discovery request. Instead it configures the ELM327 for a read-only K-line initialization experiment:

1. reset the adapter and disable echo/linefeeds;
2. select ISO protocol 3 first;
3. disable standard keyword validation with `ATKW0`;
4. request 9600 bit/s with `ATIB96`;
5. set the slow-init address to `0x01` with `ATIIA01`;
6. perform a 5-baud slow initialization with `ATSI`;
7. if that fails, repeat the experiment using protocol 4;
8. read back `ATKW`, `ATDP`, `ATDPN` and `ATBD` as diagnostic evidence.

No standard PID polling starts in this mode. DTC read/clear, Mode 06 and RPM-test controls are disabled while the probe connection is active.

## Why this is only a probe

ELM327 firmware exposes useful ISO/K-line primitives, including a custom 5-baud init address and selectable ISO baud rate. KW82 itself is not one of the ELM327 application protocols, however. A successful `ATSI` therefore proves only that the adapter and ECU got through an ISO-style physical/session initialization step. It does not prove that the ELM can satisfy the subsequent KW82 block framing and timing requirements.

That distinction is important: the purpose of this first implementation is to collect real responses from the actual car before inventing an application-layer implementation from incomplete public protocol descriptions.

## Running the experiment

1. Connect the ELM327 to the Astra G and turn ignition on.
2. Start the application.
3. On **Settings**, select the ELM serial/COM port.
4. For **OBD protocol**, choose **Opel Astra G KW82 probe (experimental, 9600 baud)**.
5. Press **Connect**.
6. Open **Diagnostics** and **ELM raw log**.
7. Save/copy the complete probe report and raw log, especially the responses to:
   - `ATI` / `ATZ`
   - `ATIB96`
   - `ATIIA01`
   - `ATSI`
   - `ATKW`
   - `ATDP`
   - `ATDPN`
   - `ATBD`

If `ATIB96` or `ATSI` returns `?`, the adapter firmware/clone does not implement the required ELM command sufficiently for this experiment.

If `ATSI` returns `BUS INIT: ...ERROR`, that is still a useful result. Possible causes include an incorrect init address, a different Opel wake-up sequence, clone firmware limitations, or a control unit that uses a different protocol.

## Hardware scope

The engine ECU is expected on vehicle DLC pin 7. Other Astra G control units may use different K-line pins. A normal ELM327 generally routes only its standard K-line path to DLC pin 7, so probing other modules can require an external pin selector. Do not bridge several vehicle K-lines together.

## Safety

This experiment performs adapter setup and connection initialization only. It does not clear faults, actuate outputs, alter coding or write ECU memory.
