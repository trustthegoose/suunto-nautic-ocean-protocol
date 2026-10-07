# Suunto Nautic / Ocean: connection, download sequence and data map

Written 2026-10-04. A reference for everything known about talking to a Suunto
Nautic, Nautic S or Ocean ("Vaasa" / "Porvoo" generation) over Bluetooth LE,
downloading its dives, and where each piece of dive data lives.

**Evidence tags** used throughout:

- **[wire]** seen in a real byte trace: a debug log of a full download
  (2026-10-04, Ocean, firmware 2.51.28, libdc-swift 1.17.1 with `--debug`).
- **[driver]** stated in the libdivecomputer driver as of deepsealabs/libdivecomputer
  `9cbc430c` (libdc-swift 1.17.1): `src/suunto_nautic.c`, `src/suunto_nautic.h`,
  `src/suunto_nautic_parser.c`. Its comments record what was confirmed on hardware.
- **[app]** seen in PacketLogger captures of the official Suunto app
  (Nautic 2026-09-14, Ocean 2026-10-03).
- **[cloud]** seen in Suunto cloud `workouts/<key>/sml` JSON.
- **[cloud-matched]** a `/Summary` field found by matching every cloud dive-header number to
  the raw `/Summary` bytes (same offset on every dive of that watch). 2026-10-06, 6 dives
  (2 Nautic, 4 Ocean), by a matching script. Offsets not yet checked on all dives.
- **[unknown]** not established; treat as open.

Related: deepsealabs/libdc-swift#29 and #56-#61, libdivecomputer/libdivecomputer#73.

---

## 1. Layers at a glance

```
Bluetooth LE GATT  service 61353090-8231-49cc-b57a-886370740041
  write-without-response characteristic (host -> watch)
  notify characteristic                (watch -> host)
    HDLC framing      7E ... 7E, escape 7D / XOR 20, no checksum at this layer
      RPC frame       A5 opcode sublen:u16 msgid:u16 ... crc32r:u32 (Whiteboard protocol)
        resource      path-addressed (e.g. /Logbook/byId/<id>/Data), bound to a 3-byte handle
          content     /Data:    MDS chunks -> Heatshrink -> SBEM0103 (samples)
                      /Summary: paged -> SBEM0103 (uncompressed; GF, gases)
                      /Logbook/Entries: list records (id, end, size)
```

---

## 2. Bluetooth LE layer

| Item | Value | Source |
|---|---|---|
| Service UUID | `61353090-8231-49cc-b57a-886370740041` | [driver] libdc-swift `DeviceConfiguration.swift`, `BLEManager.swift` |
| Characteristics | one write (without response) and one notify, picked by property, not by UUID | [driver] `BLEManager.swift` |
| Advertised name | `Suunto Ocean <serial>` / `Suunto Nautic <serial>` (name contains the serial) | [wire] |
| MTU | never extended; notifications arrive as 60-byte pieces of an HDLC frame; host writes are split with an 8 ms gap | [wire] [driver] |
| Notify enable | the CCCD write can raise an iOS pairing dialog on first connect (allow 20 s) | [driver] |
| iOS peripheral UUID | can rotate between sessions (re-scan rather than reuse) | [driver] |

**Preconditions for a connection** (all observed):

- The watch only advertises to other devices while its bound phone is **not** connected.
  Closing the Suunto app is not enough: the bound iPhone keeps a system-level connection
  (shown as Connected in Settings > Bluetooth) whenever its Bluetooth is on, and the watch
  then stays invisible to other devices. Turn the bound phone's Bluetooth off. (Observed
  2026-10-04: the Nautic invisible to the iPad until the bound iPhone was ruled out.)
- A foregrounded (even idle) Suunto app on the same phone blocks other clients: requests
  fail with -9 / timeouts. [app] (@urbamax's A/B, 2026-09-06)
- A stale iOS pairing gives "failed to handshake"; forget the watch in iOS settings.
- The Nautic stops advertising after a period without use: not found ~13 h after its last
  connection (2026-10-04), well short of the 48 h deep sleep. Press the top button before
  connecting. Whether the timer counts from the last connection or the last button use is [unknown].
- A Nautic showing its **standby screen** is not reachable either: on 2026-10-04 the iPad's
  idle auto-download link dropped while the iPad slept, the watch sat on its standby screen,
  and DC Tester scanned without finding it (iPad Bluetooth: Not Connected) until one button
  press made it connect at once. Whether standby and the ~13 h timeout are the same
  mechanism is [unknown]. Later the same day (DC Tester 1.0 (16) on the iPad): scanning found
  nothing until the Nautic was simply **moved**, then it connected at once, and stayed connected
  with its screen still dark. So the display state is not the indicator: the watch stops
  advertising after a period without motion, and movement restarts advertising without waking
  the screen. How long that period is, and whether it is the ~13 h case, is [unknown].
- Connections from iPad, iPhone and the Mac all work, one at a time.
- **A watch can be paired with several hosts at once.** Both watches stay paired with the Mac
  and with the iPhone and/or iPad together. Any paired host whose Bluetooth is on may
  reconnect at the OS level (or through an app with auto download) and take the link, so a
  test from one host can be disturbed by another. Test routine: turn Bluetooth **off at the
  OS level** on every host not under test (e.g. iPhone and iPad for Mac captures and
  `daily.sh`), rather than relying on closed apps. Re-pairing a host does not remove the
  others' pairings; forgetting the watch on one host (iOS Settings > Bluetooth) means
  re-pairing there later. (Observed 2026-10-03 to 10-06.)

---

## 3. HDLC framing

- Every frame on the link is `7E <body> 7E`; inside the body `7E`/`7D` are escaped as
  `7D` followed by the byte XOR `20`. No checksum at this layer (the RPC frame has a CRC).
- libdivecomputer opens the HDLC layer with 244-byte buffers. [driver]
- One RPC frame per HDLC frame. A long frame spans several 60-byte BLE notifications. [wire]

---

## 4. RPC frame (Whiteboard protocol)

### 4.1 General layout

```
A5 | opcode:1 | sublen:u16 LE | msgid:u16 LE | payload ... | crc32r:u32 LE
```

- `crc32r` = reflected CRC-32 over every preceding byte of the frame (from `A5`). [driver]
- `msgid` is a per-connection counter the host increments on every request. A reply
  echoes its request's msgid; matching on it is how replies are told apart from other
  traffic on the link. [driver] [wire]
- `sublen` counts the payload after msgid (excluding the CRC). [driver]

### 4.2 Opcodes

| Op | Direction | Meaning | Source |
|---|---|---|---|
| `12` | host -> watch | Hello ("EVA" handshake) | [driver] [wire] |
| `13` | watch -> host | Hello reply | [wire] |
| `0A` | host -> watch | GET a path (resolves it to a handle) | [driver] [wire] |
| `02` | watch -> host | ACK of a GET: carries the handle + status | [wire] |
| `03` | watch -> host | ACK (alternate), e.g. the answer to RELEASE | [wire] |
| `0D` | host -> watch | FETCH on a handle (whole resource, or one page with a parameter) | [driver] [wire] |
| `05` | watch -> host | DATA: the answer to a FETCH (status 200 = done, 100 = more pages) | [wire] |
| `10` | host -> watch | SUBSCRIBE to a handle (starts the /Data stream) | [driver] [wire] |
| `08` | watch -> host | subscribe reply / stream start, with status (200, or 423 Locked) | [wire] [driver] |
| `01` | watch -> host | NOTIFICATION: one stream chunk (or a subscribed value) | [wire] |
| `11` | host -> watch | UNSUBSCRIBE / stream stop | [driver] [wire] |
| `09` | watch -> host | stream end (answers `11`) | [wire] |
| `0B` | host -> watch | RELEASE a handle a GET bound | [driver] [wire] |
| `07` | watch -> host | subscribe-result traffic of another client (e.g. the app's logbook subscription); skip it | [driver] |

### 4.3 Frame formats used in a download

**GET** (`0A`):
```
A5 0A sublen msgid | 01 80 00 | pathlen:1 | path ASCII | crc
```
**ACK** (`02`/`03`), 18 bytes:
```
A5 02 08 00 msgid | handle:3 | 01 80 00 | status:u16 | crc
```
**FETCH, whole resource** (`0D`, "short fetch", no range):
```
A5 0D 07 00 msgid | handle:3 | 01 80 00 00 | crc
```
**FETCH with one parameter** (`0D`): a /Summary page offset or an Entries StartAfterId:
```
A5 0D 0D 00 msgid | handle:3 | 01 80 00 | count=01 | type:u16 | value:u32 LE | crc
type 06 = int32 (Summary offset, in data bytes)
type 07 = uint32 (Entries StartAfterId)
```
Parameter type ids follow Movesense Whiteboard: 1 bool, 3 u8, 5 u16, 6 i32, 7 u32. [driver]
Sending the ranged form to `/Logbook/Entries` page 1 gets **400 Bad Request**. [driver]

**DATA** (`05`):
```
A5 05 sublen msgid | handle:3 | flags:3 | status:u16 | content ... | crc
```
**SUBSCRIBE / UNSUBSCRIBE / RELEASE**: same shape as the short fetch, with opcode `10` / `11`,
and for RELEASE (`0B`) the tail is `01 80 00` (6-byte payload). [driver] [wire]

### 4.4 Status codes (HTTP-like, u16 LE)

| Value | Bytes | Meaning |
|---|---|---|
| 200 | `C8 00` | OK / last page |
| 100 | `64 00` | more pages follow |
| 400 | `90 01` | bad request (wrong fetch form) |
| 404 | `94 01` | no such resource (handle `FF FF FF`) |
| 423 | `A7 01` | locked: a previous stream's handle is still bound |

### 4.5 Handles

- **Static paths** (`/Logbook/Entries`, `/Info`, ...) resolve to `F0 xx xx` / `F1 xx xx`
  handles. [wire] Entries = `F0 24 00`, Info = `F1 2F 00`.
- **Per-dive paths** (`/Logbook/byId/<id>/...`) bind the id to a slot
  `[00|10] 24 <resource>` until RELEASE. `/Data` = `00 24 0E`, `/Summary` = `00 24 12`.
  A second GET while slot `00` is still bound gets `10 24 0E`. [driver] [wire]
- **Unknown path**: handle `FF FF FF` with status 404. [driver] [wire]
- Not releasing the /Data slot made the next dive's GET stream the **previous dive's**
  bytes (fixed in deepsealabs/libdivecomputer#8, libdc-swift 1.17.1). [driver]
- Stream notifications for /Data carry msgid `0000` and handle `F0 24 0E`, see 6.3. [wire]

---

## 5. Nominal session, step by step

Every step below is in the 2026-10-04 Ocean trace unless marked. Hex is the RPC frame
inside the HDLC `7E ... 7E`.

### 5.1 Connect and Hello

1. Scan for the service / advertised name; connect; enable notify (may prompt pairing).
2. **Hello** (42 bytes, sent verbatim from a captured template; the identity inside is
   not tied to a phone): [driver] [wire]
   ```
   A5 12 20 00 00 00 09 09 20 16 45 56 41 10 04 41 10 0C 00 00 00 04 01 02 ...  ("EVA")
   ```
   Reply: `A5 13 20 00 00 00 09 09 04 83 21 10 42 10 04 C2 40 0C ...`. The reply's content
   is not understood; only the round trip is required.

### 5.2 Liveness and identity (optional)

3. `GET /System/Mode` -> on the Ocean answers handle `FF FF FF`, status **404**. libdivecomputer
   uses it only as a round-trip check. [wire]
4. `GET /Info` -> ACK handle `F1 2F 00`, 200. `FETCH` (short) -> one DATA frame (~270 B)
   holding NUL-separated strings: `Suunto`, `Ocean`/`Nautic`, codename (`Vaasa`/`Porvoo`),
   serial (12 hex chars), part numbers, firmware `N.N.N`, `BLE Mac Address`, `WiFi Mac Address`.
   Then `RELEASE F1 2F 00` -> `03`, 200. [wire] [driver]

### 5.3 List the dives: `/Logbook/Entries`

5. `GET /Logbook/Entries` -> ACK handle `F0 24 00`, 200.
6. Page 1: short `FETCH` -> DATA, status **100** on the Ocean (more pages).
7. Page 2+: `FETCH` with `type 07` `StartAfterId = <last id of the previous page>`
   (e.g. `01 07 00 3C F0 A7 6A`) -> DATA, status **200** on the last page.
   - Page 1 holds the **oldest** dives; the newest are on the last page. On the Ocean:
     18 entries on page 1, 5 on page 2. [wire]
   - Decoded from the app's own schema reads, handles `F0 00 03/04/07/05/0C/0B`, in
     a PacketLogger capture of the Suunto app. [app]
8. See section 7.1 for the record format.

### 5.4 Download one dive: `/Data` (the profile stream)

9. `GET /Logbook/byId/<id>/Data` -> ACK handle `00 24 0E`, 200.
10. `SUBSCRIBE 00 24 0E` (`A5 10 ...`) -> `A5 08`, status 200: stream accepted
    (a non-200 here, notably **423 Locked**, means retry after a pause).
11. The watch pushes `A5 01` chunks continuously, **unacknowledged**, ~278 B of payload
    each. The host reads until **2 s of silence** (or a `09`). A 1.3-1.7 MB dive takes
    ~4 minutes. [wire] [driver]
12. `UNSUBSCRIBE 00 24 0E` (`A5 11`) -> `A5 09`, 200. A chunk or two may still arrive before
    the `09`; they belong to this dive. Without this stop the watch keeps streaming, and the
    next GET can be answered by a leftover chunk or refused with 423. [driver] [wire]
13. `RELEASE 00 24 0E` (`A5 0B`) -> `A5 03`, 200. [wire]

### 5.5 Download the dive's `/Summary`

14. `GET /Logbook/byId/<id>/Summary` -> ACK handle `00 24 12`, 200.
15. Repeated `FETCH` with `type 06` offset = data bytes received so far (0, 451, 902,
    1353, 1804 on the Ocean) -> DATA status 100 ... last page status 200. [wire]
16. `RELEASE 00 24 12` -> `03`, 200.
17. Total /Summary: **2036 B on the Ocean, 2338 B on the Nautic**. [wire] [driver]

### 5.6 Verify, then the next dive

18. **Completeness check**: Entries' listed size == compressed /Data bytes + /Summary
    data bytes, exactly. Example (Ocean dive 1789516930): /Data 91,988 compressed + /Summary
    2,036 = listed size. A short download is retried once, then flagged incomplete. [driver] [wire]
19. Repeat 9-18 for each dive, newest first; stop at the first id equal to the stored
    fingerprint (the newest dive already downloaded). [driver]

### 5.7 What the official app does differently [app]

- Also calls `/Logbook/byId/<id>/Flags` and `/Logbook/UnsynchronisedLogs`, which the
  driver never does. `/Logbook/UnsynchronisedLogs` is a subscribable value (a counter);
  whether the watch updates it over BLE after a new dive is **[unknown]** (DC Tester's
  auto-download step 7 is testing it).
- Re-lists /Logbook/Entries twice per sync and fetches /Summary several times per dive.
- Reads the per-dive schema **`/Logbook/byId/<id>/Descriptors`** before /Summary and /Data
  when a dive is opened (path seen in a PacketLogger capture of the Suunto app; latishab decoded it on
  #29, 2026-09-01). It is an uncompressed SBEM0103 schema (~43.5 KB, ~344 records): GRP
  records map a record id to its ordered field ids; PTH (field name paths such as
  `suunto/sml.Sample.DiveEvents.Alarm.Type`), FRM, DELTAREF and MOD records define names,
  types, scaling and enum values. The global `/DataFormat/Descriptors` is only the
  top-level schema. Not yet fetched or archived by us; the /Summary GRPs (0x20-0x27) would
  name every /Summary field (map 6.6). [app] [#29]

---

## 6. Content formats

### 6.1 `/Logbook/Entries` DATA content

```
01 24 | BE 25 70 73 | count:u32 | 0C 00 00 00 | 45 00 00 00 | records ...
```
- `count`: 0x12 = 18 on Ocean page 1, 5 on page 2. [wire] The other header words are
  [unknown]; one header value falls in the timestamp window and must not be read as a dive. [driver]
- **Record**, 24 bytes, all u32 LE: `[start][end][w1][w2][size][pad]` [driver] [wire]
  - `start` = the dive's **LogId** and UNIX start time (seconds). This is the id used in
    `/Logbook/byId/<id>/...`.
  - `end` = end time (within a day of start).
  - `w1`, `w2`: [unknown] (`w1` is 1 in the records seen).
  - `size` = compressed /Data + /Summary data bytes (the completeness check).
- Example: `A1228E6A 10248E6A 01000000 00000000 70DB0000 00000000` = start 0x6A8E22A1,
  end 0x6A8E2410, size 56,176. [wire]
- Ids are 4-aligned; scanning unaligned can invent a phantom dive. [driver]

### 6.2 `/Summary` pages

Each DATA content is one page: `[header:11][data][crc:4]`.
- Header example: `0D 00 02 C3 01 00 C3 01 00 C3 01`; the **data length** is the u16 at
  offset 3 (`C3 01` = 451). [wire] [driver]
- The paging offset counts **data bytes only**. Keeping headers/CRCs, or advancing by the
  whole page, loses 15 real bytes per boundary (deepsealabs/libdc-swift#57). [driver]
- The concatenated data is one uncompressed **SBEM0103** document (see 6.5).

### 6.3 `/Data` stream chunk (`A5 01`)

```
offset  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 | 28 ...
       A5 01 2D 01 00 00 F0 24 0E 01 80 00 02 24 22 25 00 00 00 00 16 01 00 10 0C 00 00 00 | payload
       ^ opcode 01, msgid 0000, handle F0 24 0E            payload size u16 = 0x0116 (278) ^
```
- The 28-byte "MDS" header is counted from the frame's first byte (`A5`); the payload size
  is the u16 LE at frame offset 20, and the payload starts at offset 28. [driver] [wire]
- Stream chunks carry msgid `0000` and the resource's static handle `F0 24 0E`, not the
  `00 24 0E` slot the GET returned. [wire]
- Concatenated payloads = one **Heatshrink** (LZSS) stream, window_sz2 7, lookahead_sz2 5. [driver]
- Decompressed = an **SBEM0103** sample stream. Example: 91,988 compressed -> 101,550 B. [wire]
- Note: the "always-on telemetry" frames noted on 2026-09-14 (`7EA5 012D 0100 00F0 240E ...`)
  match this chunk shape. Most likely a /Data stream left running by DC Tester's then-missing
  stream stop, not analytics. [inferred]

### 6.4 Chunk/stream boundaries

Chunk boundaries are a transport artifact; only the concatenated, decompressed stream
means anything. [driver]

### 6.5 SBEM0103 container (both /Data and /Summary)

- Starts with the ASCII signature `SBEM0103`.
- Then TLV records: `[id:1][length:1][value]`; length `FF` = a 4-byte LE length follows.
  Unknown ids are skipped. [driver]
- In a sample stream every record except the timeline base (`01`) starts with a signed
  **int16 LE millisecond delta** from the previous record. [driver]
- Heatshrink artifacts can fake a header; fixed-length ids are validated
  (`08`=6, `0B`=20, `0E`=6, `14`=7, `16`=195, `17`=14) and the walk resyncs byte by byte. [driver]
- The ids are not universal across firmware: some are assigned per watch from a descriptor
  schema (see the IMU note below). [driver]

---

### 6.6 `/Summary` field map

**Authoritative schema (2026-10-07).** The watch's own per-dive schema,
`/Logbook/byId/<id>/Descriptors`, names every /Summary field with its type, unit scaling and
enum values. Fetched for one dive on both watches (Nautic 43,505 B, Ocean 43,140 B; a 64-page fetch cap
truncates it at 28,864 B) and decoded with `tools/descriptors_decode.py`; the full field lists
with byte offsets are in `schema/summary_schema_{nautic,ocean}.txt`. Every cloud-matched
offset below agrees with it, and its record lengths equal the real ones (DiveHeader 410/561,
DiveFooter 507/658). Points it settles:
- Gas record (45 B): State enum +0 (0 OC, 1 CCR diluent, 2 CCR oxygen, 3 Suit), **Oxygen
  int16 +1, Helium int16 +3**, PO2 f32 +5, TankSize f32 +9, TransmitterID/2 int32 +13/+17,
  TankFillPressure int32 +21, Start/End pressure +25/+29, Start2/End2 +33/+37 (int32 Pa),
  AvgVentilation f32 +41. **The driver reads He as a u8 at +2 (the high byte of O2): helium
  always reads 0** (trimix untested anywhere).
- DiveHeader: +24 DeactivationTimeout, +41 SafetyStopTime (both int32); +32 Algorithm enum
  (0 Off, 1 Suunto RGBM, 2 Buhlmann); +33 Altitude, +35 Conservatism (int16); +45
  LastDecoStopDepth enum (3 = 3 m, 6 = 6 m); +46 AscentModeStepped, +47 OOAM (bool).
- Nautic's extra 151 B per record = 3 more gas slots (8 vs 5) + a 16-B CCR Setpoint block
  (Low/High f32, SwitchDepthLow/High int8, IsAutomatic/IsCustom bool, Custom f32).
- GPS: int32 degrees x 1e7 (schema: PI*x/(1e7*180) radians); GPSAltitude uint16, x/5 - 1000 m.

**Record layout.** The /Summary is six SBEM records, in the same order as the six Summary
samples of the cloud JSON (the cloud lists keys alphabetically inside each sample, so key
order there says nothing about byte order):

| # | Cloud sample | Record id Nautic / Ocean | Data length Nautic / Ocean | Data starts at (Nautic / Ocean) |
|---|---|---|---|---|
| 1 | DiveHeader | 0x21 / 0x20 (6-byte header) | 561 / 410 B | 14 / 14 |
| 2 | DiveFooter | 0x22 / 0x21 (6-byte header) | 658 / 507 B | 581 / 430 |
| 3-5 | Windows x3 | 0x27 / 0x26 (2-byte header) | 239 B each | 1241, 1482, 1723 / 939, 1180, 1421 |
| 6 | Header | 0x25 / 0x24 (6-byte header) | 370 B | 1968 / 1666 |

**Offsets inside a record are the same on both watches**; the Nautic's DiveHeader and
DiveFooter are each 151 B longer, which is the whole shift between the models. The extra
151 B are **appended at the end** of each record and are **all zero on all 10 Nautic dives**:
both records end in the 45-byte gas-record array (DiveHeader from +185, DiveFooter from
+282), which holds **5 slots on the Ocean** (225 B, ending exactly at the record end) and
continues on the Nautic: 151 = 3 x 45 + 16, i.e. room for **8 gas slots plus 16 bytes**.
The schema confirms it: 8 gas slots on the Nautic, and the 16 trailing bytes are the CCR
Setpoint block. [wire-derived] [schema] Record ids
differ by one between models (likely assigned by the watch's format descriptors), so find
records by position, not by a fixed id. The table below gives absolute offsets from the
SBEM signature for the two files checked; the record-relative offset is in the Type column
where known (e.g. DiveFooter +8). Multi-byte values are little-endian. [cloud-matched]

| Field | Nautic | Ocean | Type, unit | Driver | Evidence |
|---|---|---|---|---|---|
| Relative timestamp (DiveHeader) | 22 | 22 | u32, DiveHeader +8 | no | [cloud-matched] |
| Surface interval before the dive | 26 | 26 | f32, s, DiveHeader +12 | no | [cloud-matched] |
| Depth threshold with water contact | 30 | 30 | f32, m | no | [cloud-matched] |
| Depth threshold without water contact | 34 | 34 | f32, m | no | [cloud-matched] |
| Safety stop time / deactivation timeout | 38 | 38 | u16 (two cloud fields share the value; which is which unresolved) | no | [cloud-matched] |
| Dive number in the series | 42 | 42 | u16 | no | [cloud-matched] |
| GF high / GF low | 0x33 (51) / 0x35 (53) | same | u16, % | **yes** | [driver] [cloud-matched] |
| Water type | 0x3E (62) | same | u8: 0 fresh, 1 EN13319, 2 salt | no (reported on #29) | [wire-derived] [cloud] |
| Start tissue: CNS / OTU | 63 / 67 | same | u16 | no | [cloud-matched] |
| Start tissue: N2, 16 compartments | 71-131 | same | 16 x f32 | no | [cloud-matched] |
| Gas records | from 0xC7 (199), 45 B each | same | O2 % +1, He % +2, PO2 max f32 +5, tank size f32 m^3 +9 | **yes** | [driver] [cloud-matched] |
| Transmitter IDs, gas 0 (tank 1 / tank 2) | 212 / 216 | same | u32 (inside gas record 0) | no | [cloud-matched] |
| Desaturation time / no-fly time | 589 / 593 | 438 / 442 | u32, s, DiveFooter +8 / +12 | no | [cloud-matched] |
| Footer gas 0: PO2, tank size, transmitter IDs | 868, 872, 876 / 880 | 717, 721, 725 / 729 | as above | no | [cloud-matched] |
| Footer gas 0: start / end pressure, tank 1 | 888 / 892 | 737 / 741 | u32, Pa, DiveFooter +307 / +311 | no (driver uses samples) | [cloud-matched] |
| Footer gas 0: start / end pressure, tank 2 (sidemount) | 896 / 900 | 745 / 749 | u32, Pa, DiveFooter +315 / +319 | no | [cloud-matched] |
| Per-window stats records (max depth, dive time, duration, distance, water temp min/max, vertical speed) | ~1250-1940, records 241 B apart | ~950-1640 | f32 | no | [cloud-matched]; which record is the whole dive is unresolved |
| Dive time / max depth (dive record) | Header +321 / +330 | same | f32, s / m | **yes** | [driver] |
| Average depth | 2306 (also 1938) | 2004 (also 1636) | f32, m, Header +338 (also Window 3 +215) | no (driver averages the samples) | [cloud-matched] |
| Water temperature min / max | ~1342 / 1346 | ~1044 / 1040 | f32, K | no (driver uses samples) | [cloud-matched] |

**Record-relative offsets** (second pass, 2026-10-06: each cloud field searched only inside its
own record on all 6 dives at once) [cloud-matched]:

| Field | Record | Offset, type |
|---|---|---|
| Relative timestamp / surface interval (s) | DiveHeader | +8 u32 / +12 f32 |
| Depth threshold with / without water contact (m) | DiveHeader | +16 / +20 f32 |
| Deactivation timeout / safety stop time (s) | DiveHeader | +24 / +41 int32 (schema) |
| Dive number in series | DiveHeader | +28 u16 |
| GF high / low | DiveHeader | +37 / +39 u16 |
| Water type | DiveHeader | +48 u8 (0 fresh, 1 EN13319, 2 salt) |
| Start tissue CNS / OTU; N2 x16 | DiveHeader | +49 / +53; +57.. f32 |
| Gas records (45 B each) | DiveHeader | from +185: O2 +1, He +2, PO2 max f32 +5, tank m^3 f32 +9, transmitter IDs u32 +13/+17, fill pressure (bar) +21 |
| Desaturation / no-fly time (s) | DiveFooter | +8 u32 / +12 u32 |
| Dive-route gyro bias X, Y, Z, figure of merit | DiveFooter | +17, +21, +25, +29 f32 |
| End tissue CNS / OTU | DiveFooter | +34 / +38 u16 |
| GPS start lat / lon | DiveFooter | +50 / +54 int32, degrees x 1e7 |
| GPS start EHPE (m) | DiveFooter | +60 u8 |
| GPS stop (= last known) lat / lon | DiveFooter | +70 / +74 int32, degrees x 1e7 (repeated at +82 / +86) |
| GPS stop EHPE (m) | DiveFooter | +80 u8 |
| End tissue N2 x16 | DiveFooter | from +90 f32 |
| Tissue level (bar-graph segments) | DiveFooter | from +218 u8 |
| Footer gas records (45 B each) | DiveFooter | from +282; start / end pressure tank 1 +307 / +311, tank 2 +315 / +319 (u32 Pa) |
| Duration (s) / distance (m) | each Windows | +13 / +17 f32 |
| Water temp min / max / avg (K) | each Windows | +101 / +105 / +109 f32 |
| Max depth / average depth incl. surface / dive time | each Windows | +190 / +194 / +198 f32 |
| Average depth while diving | Windows 3 | +215 f32 |
| Minimum altitude | Header | +64 f32 |
| Water temp min / max (K) | Header | +313 / +317 f32 |
| Dive time / max depth / **average depth** | Header | +321 / +330 / +338 f32 |

Two averages exist: Windows `Depth.Avg` (11.91 m on 976, includes surface time) and Header /
Windows-3 `DepthAverage` (12.45 m, diving only, the app's figure).

Not located: text values stored as codes (Algorithm, tank State "OC", window Type
Dive/Activity/Move); settings identical on every dive (conservatism, altitude setting,
setpoints, which u16 is safety stop vs deactivation); GPS altitude, ascent/descent speeds,
descent time/distance, vertical speed, header duration, pause duration, average ventilation
(possibly computed by the cloud, not stored).

## 7. Data map: where each piece of dive data lives

### 7.1 On the watch (BLE)

| Data | Where | Format / offset | Source |
|---|---|---|---|
| Dive id / start time | Entries record `start` | u32 UNIX seconds | [wire] [driver] |
| Dive end time | Entries record `end` | u32 UNIX seconds | [driver] |
| Expected download size | Entries record `size` | u32 = /Data compressed + /Summary bytes | [driver] [wire] |
| Absolute dive start (clock) | /Data GPS record `0B` | UTC ms; start = gps_utc - gps_rel_time | [driver] |
| No-GPS dive start | only the LogId (dive id) | fallback | [driver] |
| Depth | /Data `16` (extended status), every ~10 s | float32 at +2 (m) | [driver] |
| Water temperature | /Data `12` (1 Hz profile) | u16 at +16, centi-kelvin (value/100 - 273.15) | [driver] |
| **Absolute pressure, ~1 Hz** | /Data `12` | u32 at +6, Pa (`FFFFFFFF` = none). depth = (P - surface pressure from `17`) / (rho x 9.81), rho from the water type (1000 fresh / 1020 EN13319 / 1030 salt), matching the `16` depths to ~1 cm. **Not decoded by the parser.** The Suunto app's max depth is the peak of these (25.00/16.21/25.13/16.32 m vs the 10 s samples' 24.72/16.00/24.92/16.07 m on four Sep 14 dives) | [wire-derived 2026-10-04] |
| Cylinder pressures | /Data `16` (extended status) | 18-byte slots from +42: `[idx][?][Pressure u32 Pa][Pressure2 u32 Pa][GasTime u32 s]...`; tank 0 Pressure at +44 | [driver] |
| Second transmitter (sidemount) | /Data `16` slot `Pressure2` (+6 in the slot) | Pa; real only if non-zero twice | [driver] |
| Gas time remaining | /Data `16` slot +10 | u32 s; `FFFFFFFF` = not computed | [driver] |
| Time to surface | /Data `16` | u16 at +22 (s) | [driver] |
| NDL | /Data `16` | int16 at +30 (s) | [driver] |
| Ceiling | /Data `16` | float32 at +38 (m) | [driver] |
| GF99 / surface GF / leading tissue | /Data `16` | int16 at +186 / +190 / +78 (%) | [driver] |
| `16` length | 195 B (Ocean/Nautic), 141 B (Nautic S, some Ocean firmware: slots 0-4 only) | | [driver] |
| Surface pressure | /Data `17` | 3 float32 at +2/+6/+10 (current, max, min), Pa | [driver] |
| Activity / dive mode | /Data `08` | `[dt][sportId][customModeId ascii]`; 51 scuba, 61 freedive, 62 mermaiding | [driver] |
| Heart rate | /Data `0F` (Ocean only) | u8 bpm | [driver] |
| GPS fix | /Data `0B` | 20 B, includes absolute UTC ms | [driver] |
| GPS accuracy | /Data `0E` | int8 deltas EHPE/EVPE | [driver] |
| Battery | /Data `14` | int16 current, u16 mV, u8 % | [driver] |
| IMU (accel/gyro/mag) | /Data `23` (195-B-status watches) or `22` (141-B) | 9 x int16 after a u32 timestamp | [driver] |
| Dive-route features | /Data `24` (or `23` on 141-B watches) | 5 x u16, inputs to the app's dead reckoning (the track itself isn't stored) | [driver] |
| Events | /Data `18` alarm, `19` warning, `1A` notify, `1B` state | `[dt][Type][Active]` | [driver] |
| Dive state | /Data `1C` | 0 idling, 1 diving, 2 recovering | [driver] |
| Dive active flag | /Data `1E` | | [driver] |
| Dive-end reason | /Data `1D` (OOAM) | | [driver] |
| Gas switch | /Data `1F` | int16 gas number (0-based = cylinder slot) | [driver] |
| Gradient factors | /Summary | u16 at 0x33 (high) and 0x35 (low), from the SBEM signature | [driver] |
| Water type | /Summary byte 0x3E (from the SBEM signature) | 0 fresh, 1 EN13319, 2 salt. Consistent on all 33 of my dives against the density fitted from `12`/`16`, and confirmed against the cloud `DiveHeader.WaterType` (Fresh/EN13319/Salt dives, 2026-10-04). Prior art: latishab already decodes it as DC_FIELD_SALINITY in libdivecomputer#73 (commit `cd3dbc890`, 2026-09-08), but the deepsealabs fork that libdc-swift ships does not | [wire-derived] [cloud] |
| More /Summary fields (avg depth, tank start/end pressures per transmitter, temperatures, desat/no-fly, tissue) | /Summary | see 6.6 | [cloud-matched] |
| Gas mixes | /Summary from 0xC7 | 45-byte record per gas: O2% +1, He% +2, PO2 max float32 +5, cylinder volume float32 m^3 +9; record index = GasNumber = cylinder slot | [driver] |
| Serial, firmware, MACs | `/Info` | NUL-separated strings | [wire] [driver] |

### 7.2 In the Suunto cloud (`workouts/<key>/sml` JSON) [cloud]

Top level `{"Summary": {"Samples": [...]}, "Data": {"Samples": [...]}}`; every sample has
`Source` (`suunto-<serial>`), `TimeISO8601` (local time with offset) and
`Attributes["suunto/sml"]`.

- `Summary` sample types:
  - `Header`: `DateTime`, `Device {Name codename, SerialNumber, Info {SW, HW}}`, `Depth`,
    `DiveTime`, `Temperature` (K), `Notes`, `Personal`, fitness fields.
  - `DiveHeader`: `Gases[]` (`Oxygen`/`Helium` %, `TankSize` m^3, `TankFillPressure`,
    `StartPressure`/`StartPressure2`, `EndPressure`/`EndPressure2`, `TransmitterID`,
    `TransmitterID2`, `State`), `LowGf`/`HighGf`, `Algorithm`, `Conservatism`, `StartTissue`, ...
  - `DiveFooter`: `DiveLocation {Start, Stop}` (radians), `EndTissue`, `LastKnownCoordinates`,
    `DesaturationTime`, `NoFlyTime`, ...
  - `Windows`: per-window stats.
- `Data` samples (`Sample` object), by kind:
  - dive: `Depth`, `Ceiling`, `NoDecTime`, `TimeToSurface`, `Cylinders[]` (`GasNumber`,
    `Pressure`, `Pressure2` in Pa, `GasTime`, `Ventilation`), `RtGradientFactors`.
  - `DiveEvents` (object) and `Events[]` (array): gas switches, alarms, states.
  - `DiveRoute {X, Y, Z}` (relative metres), `DiveRouteOrigin` (degrees).
  - GPS: `Latitude`/`Longitude` (radians), `GPSAltitude`, `UTC`.
  - Also battery, satellite, barometric samples.
- Sidemount: both transmitters under one gas: `Cylinders[GasNumber 0].Pressure` and
  `.Pressure2` (Submersion fixed in #2518).
- The app's own JSON export (`DeviceLog`) has no `DiveHeader`: no gases or GF.

---

## 8. Failure modes and their causes

| Symptom | Cause | Fixed in |
|---|---|---|
| End of large dives missing | 4096-chunk cap on the stream | libdc-swift#60 / 1.16.1 |
| /Summary 404 after a long download | a leftover `01` chunk taken as the GET's ACK | message-id matching (#59) |
| 15 bytes lost per /Summary page | header/CRC kept, offset advanced wrongly | #57 |
| Newest dives missing from the list | only page 1 (oldest) read | StartAfterId paging (#61) |
| Silent short downloads | no size check | listed-size check (#58) |
| Second dive gets the first dive's bytes | /Data slot never released | handle release (deepsealabs/libdivecomputer#8, 1.17.1) |
| 423 Locked | previous stream handle still bound | stream stop + release, retry with backoff |
| -9 / timeouts while the Suunto app is open | the app's traffic on the same link | close the app (driver now skips foreign frames) |
| "failed to handshake" | stale iOS pairing | forget the watch in iOS |

---

## 9. Open questions

- The Entries header words, and `w1`/`w2` in each record.
- Whether `/Logbook/UnsynchronisedLogs` notifies over BLE when a new dive is logged.
- What `/Logbook/byId/<id>/Flags` holds, and whether the app writes to it after a sync.
- The meaning of the Hello reply, and whether the watch would accept a different identity.
- Dive retention on the watch (what makes a dive's raw profile unavailable; under study).
- libdivecomputer#73, the upstream branch, does not yet carry any of the 1.16.1 / 1.17.1 fixes
  (still at `7288977`, last updated 2026-09-26). Answered by latishab on #29 (2026-10-04): the
  transport fixes (complete downloads, paging, size check, foreach gap, per-dive handles,
  message ids) and the dive time / max depth parser fix are portable and she'll update #73
  when they go on; subscription and auto-sync stay on the deepsealabs fork, since #73 has no
  Nautic-specific public API. Open only until the port lands.
- The two driver copies have drifted both ways: #73 lacks the transport fixes above, and the
  deepsealabs fork lacks #73's water type / salinity decode (`cd3dbc890`).
