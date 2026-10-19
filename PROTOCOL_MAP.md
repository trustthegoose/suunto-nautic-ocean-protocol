# Suunto Nautic / Ocean: connection, download sequence and data map

Written 2026-10-04. A reference for everything known about talking to a Suunto
Nautic, Nautic S or Ocean ("Vaasa" / "Ylivieska" / "Porvoo" generation) over Bluetooth LE,
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
  (2 Nautic, 4 Ocean), by a matching script. Since checked on all 39 archived dives against the
  schema and on 9 against the cloud (6.6).
- **[schema]** stated by the watch's own per-dive `/Logbook/byId/<id>/Descriptors` schema
  (field names, types, enums, group ids), fetched 2026-10-07 from both watches.
- **[headers]** confirmed by the public Movesense device-library headers
  (https://bitbucket.org/movesense/movesense-device-lib): `whiteboard/metadata/MetadataStructures.h`
  (value types), `whiteboard/WbVersion.h` (versions), `whiteboard/Identifiers.h` and
  `WhiteboardConfig.h` (SuuntoSerial), `sbem/Sbem.hpp`. These give constants and
  structures, not the wire format: Movesense doesn't publish that, so the byte layouts here
  remain reverse-engineered.
- **[max]** first described by Max (GitHub `urbamax`) in his reverse-engineering report,
  libdivecomputer/libdivecomputer#70 (2026-08-28), from a capture of the official app's sync.
  The other tags on the same line say how it was later confirmed.
- **[unknown]** not established; treat as open.

Related: deepsealabs/libdc-swift#29 and #56-#61, libdivecomputer/libdivecomputer#73.


**Models** (internal names; the watch never calls itself "Nautic S"):

| Model | Codename (`Device.Name`) | Hardware (`Device.Info.HW`) | Evidence |
|---|---|---|---|
| Nautic | `Vaasa` | `GT_RevX` | [cloud] app/cloud exports, fw 2.55.46; [max] (libdivecomputer/libdivecomputer#70 gave Vaasa and GT_RevX first, but applied them to the Ocean too) |
| Ocean | `Porvoo` | `Seal_RevA3` | [cloud] app/cloud exports, fw 2.51.28 and 2.40.56 |
| Nautic S | `Ylivieska` | `Seal_Lite_RevA3` | reported by K4pisa from his app exports, deepsealabs/libdc-swift#29 (2026-09-01); not in our own data |

The Nautic S shares the Ocean's "Seal" hardware family, not the Nautic's "GT": consistent
with the Nautic S and some Ocean firmware both writing the 141-byte `16` record where the
Nautic writes 195 bytes (section 7). Match a device on its advertised BLE name, or on
these codenames; a match on the human-readable model name misses the Nautic S.

---

## 1. Layers at a glance

```
Bluetooth LE GATT  service 61353090-8231-49cc-b57a-886370740041
  write-without-response characteristic (host -> watch)
  notify characteristic                (watch -> host)
    HDLC framing      7E ... 7E, escape 7D / XOR 20, no checksum at this layer
      RPC frame       A5 opcode sublen:u16 msgid:u16 ... crc32r:u32 (Movesense Whiteboard
                      comm protocol, version 9 [headers]; wire format not publicly documented)
        resource      path-addressed (e.g. /Logbook/byId/<id>/Data), bound to a 3-byte handle
                      (likely the first 3 bytes of a 4-byte Whiteboard ResourceId; see 4.3)
          content     /Data:    MDS chunks -> Heatshrink -> SBEM0103 (samples)
                      /Summary: paged -> SBEM0103 (uncompressed; GF, gases)
                      /Logbook/Entries: list records (id, end, size)
```

---

## 2. Bluetooth LE layer

| Item | Value | Source |
|---|---|---|
| Service UUID | `61353090-8231-49cc-b57a-886370740041` | [driver] libdc-swift `DeviceConfiguration.swift`, `BLEManager.swift` |
| Characteristics | write without response `17816557-5652-417f-909f-3aee61e5fa85` (ATT handle 18) host -> watch; notify `34802252-7185-4d5d-b431-630e7050e8f0` (handle 21) watch -> host. The drivers pick them by property, not UUID | [wire] [app]: Nautic service discovery in two app captures; Ocean listed live from a Mac (2026-10-14). Max (libdivecomputer/libdivecomputer#70) gave the first UUID, though as the one to subscribe to; it's the write side |
| Other services | Battery `180f` (`2a19` battery level, read + notify); generic `1800`/`1801` | [wire] [app] |
| Advertising | the watch advertises the `61353090-...` service UUID, so a scan can filter on it | [wire] |
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
- **Sharing a phone with the Suunto app.** On one phone, every app talks over the same BLE link,
  and iOS (and macOS) hand every notification to every app subscribed on it: replies to the
  Suunto app's requests, including its `07` PUT replies and its Hello replies, reach DC Tester
  too (confirmed 2026-10-15 with a passive second client on a Mac and with DC Tester idle during
  a real Suunto app sync) [wire]. The build 22 driver (deepsealabs) recognises frames for other
  requests by sequence number and skips them, and while the app's session is already open, its traffic interleaves harmlessly with
  a download. What breaks a download is the app **opening a new session**: the watch answers its
  Hello on the shared link and about 2 s later ends our stream with `UNSUBSCRIBE_REPLY` status
  **404** (our ordinary requests are still answered). A chunk cut short at that moment usually
  swallows the Hello reply in `hdlc.c`. With the app retrying its Hello every ~10.6 s, every
  stream stall coincided with one of those replies, and dives came out truncated (2026-10-15)
  [wire]. A host can find the watch while the app holds it (it doesn't advertise then) via
  `retrieveConnectedPeripherals`. Pause-and-resume handling and test results:
  deepsealabs/libdc-swift#78; session rules in 5.8. (Earlier report: a foregrounded Suunto app made requests fail
  with -9 / timeouts. [app] @urbamax's A/B, 2026-09-06)
- A stale iOS pairing gives "failed to handshake"; forget the watch in iOS settings.
- **Both watches stop advertising when idle, and BLE traffic doesn't count as use** (measured
  2026-10-15/16 with a passive scan every 10-60 s from a Mac, nothing connecting):
  - **Nautic:** stops when it enters Sleep, about **1 hour** after its last use (silent 59 min
    after a tub dive closed, though our connections and a sync came in between). Its user guide:
    always-on display after 5 min, Sleep after 1 h, Deep Sleep (power-off) after 48 h; a button
    press or water contact wakes it from Sleep, raising the wrist only from the always-on display.
    That fits the earlier observation (2026-10-04) that simply moving a dark Nautic made it
    connect: it was presumably still within its first hour.
  - **Ocean:** stops about **33-36 minutes after it last moved** (timed twice, lying still on a
    desk at 42% battery), long after its screen has gone blank, and nothing in its user guide
    describes it. Picking it up, with no button press, had it advertising again within 20 s.
  - For auto download: a worn watch stays reachable; one left on a desk goes quiet after about
    30 min (Ocean) or 1 h (Nautic), and the Nautic then needs a button press.
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
  `7D` followed by the byte XOR `20`. No checksum at this layer (the RPC frame has a CRC). [max]
- libdivecomputer opens the HDLC layer with 244-byte buffers. These are the read cache for
  incoming BLE notifications (each ~60 bytes), not a frame-size limit: frames are reassembled
  into the caller's buffer (`MAX_PACKET`, 512 bytes), and a larger frame fails with "HDLC frame
  is too large" rather than being cut silently. [driver] The largest real frame is **481 bytes**
  (a /Summary page), 31 bytes under that limit; stream chunks are 311 bytes. [wire] (2026-10-15,
  385,565 frames)
- One RPC frame per HDLC frame. A long frame spans several 60-byte BLE notifications. [wire]

---

## 4. RPC frame (Whiteboard protocol)

### 4.1 General layout

```
A5 | opcode:1 | sublen:u16 LE | msgid:u16 LE | payload ... | crc32r:u32 LE
```

- `crc32r` = reflected CRC-32 over every preceding byte of the frame (from `A5`). [driver] [max]
- `msgid` is a per-connection counter the host increments on every request. A reply
  echoes its request's msgid; matching on it is how replies are told apart from other
  traffic on the link. [driver] [wire]
- `sublen` counts the payload after msgid (excluding the CRC). [driver]

### 4.2 Opcodes

| Op | Direction | Meaning | Source |
|---|---|---|---|
| `12` | host -> watch | Hello: comm-protocol versions + host identity (SuuntoSerial) + Whiteboard version; see 5.1 | [driver] [wire] [headers] |
| `13` | watch -> host | Hello reply: the same fields for the watch, including its serial; see 5.1 | [wire] [headers] |
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
| `0E` | host -> watch | PUT: write a value or upload data to a handle a GET bound, e.g. the app marking a dive synced (`/Flags`, value `01 05 00 03 00` = one uint16, 3) or pushing watch-face/app files in parts. Identified as PUT: the app uses it to write `/Flags`, which the app does with a PUT (Max's disassembly, deepsealabs/libdc-swift#29), and PUT follows GET in Whiteboard's request types (`GET, PUT, ...`, [headers]) as `0E` follows the read opcode `0D` | [app] [wire] |
| `07` | watch -> host | PUT reply, echoing the `0E`'s msgid and handle, with a status: 200, 100 (continue, multi-part upload), 202, 400, 500 seen. All 559 `07` frames in the app captures pair with a `0E`. When another client (the Suunto app) shares the link, its PUT replies show up here: skip `07` frames that answer nobody's request on this connection. Earlier described as subscribe-result traffic [driver]; they are PUT replies. **Confirmed 2026-10-15 by an active test**: a `0E` (value 0) sent to the read-only `/Info` handle `F1 2F 00` was answered by a `07` with the same msgid and handle and status **400**, nothing changed, and the handle released normally (`0B` -> `03`, 200) | [app] [wire] |

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
Parameter type ids are Whiteboard's `ValueType` enum: 0 none, 1 bool, 2 int8, 3 uint8,
4 int16, 5 uint16, 6 int32, 7 uint32, 8 int64, 9 uint64, 10 float, 11 double, 12 string,
13 byte stream, 14 hash string, 15 structure. [headers] (the header warns the values
"match fixed data type IDs"). Seen on the wire: 1, 3, 5, 6, 7. [driver] [wire]
Sending the ranged form to `/Logbook/Entries` page 1 gets **400 Bad Request**. [driver]

**DATA** (`05`):
```
A5 05 sublen msgid | handle:3 | flags:3 | status:u16 | content ... | crc
```
**SUBSCRIBE / UNSUBSCRIBE / RELEASE**: same shape as the short fetch, with opcode `10` / `11`,
and for RELEASE (`0B`) the tail is `01 80 00` (6-byte payload). [driver] [wire]

**The `01 80 00` after the handle is not a constant.** The GET's ACK hands it out with the
handle, and every later request and reply on that handle echoes it. Logbook resources and
`/Info` get `01 80 00`; the file-system resources (`/Dev/FileSystem/Stream`, `/FileDelete`,
`/DirectoryCreate`) and `/Meta/Hash` get `03 80 01` (seen in the app's traffic). [app] [wire] Copy
the bytes from the ACK rather than hardcoding them. A likely reading [headers] [inferred]: the
3-byte handle plus the next byte is Whiteboard's 4-byte `ResourceId` (one byte with two 4-bit
fields, instance and execution context; a one-byte whiteboard id; a 16-bit local resource id),
which makes that fourth byte the local resource id's high byte: `0x01..` for the logbook and
`/Info` resources, `0x03..` for the file system and `/Meta/Hash`. The remaining two bytes
(`80 00` / `80 01`) are unexplained. Over 2,363 GET replies in our logs only two forms occur,
always paired: `01 80 00` (every logbook, `/Info` and `/Sync` path we requested) and `03 80 01`
(some of the Suunto app's requests). [wire]

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
   A5 12 20 00 00 00 09 09 20 16 45 56 41 10 04 41 10 0C 00 00 00 04 01 02 ...
   ```
   Reply, shown here for a made-up serial `123456789012` (a real reply carries the watch's
   own serial, see below):
   ```
   A5 13 20 00 00 00 09 09 04 C2 40 14 C6 81 24 4A 20 0C 00 00 00 04 01 02
   00 00 00 00 00 01 00 00 00 00 00 00 00 00 9C 81 E4 E4
   ```
   libdivecomputer only needs the round trip, but the content is mostly decoded. Each watch's
   reply is byte-for-byte the same in every session we recorded (193 log files, 2026-09 to
   10-18), and the two watches' replies differ only in the serial bytes, so none of it is
   session state. [wire] Both are
   42-byte frames: header (4), msgid `00 00` (2), a 32-byte payload, CRC (4). The payload
   layout is the same in both directions:

   | Payload bytes | Host Hello | Watch reply | Meaning | Evidence |
   |---|---|---|---|---|
   | 0 | `09` | `09` | minimum comm-protocol version, 9 | [headers] `WB_COMM_PROTO_MIN_VERSION` |
   | 1 | `09` | `09` | current comm-protocol version, 9 | [headers] `WB_COMM_PROTO_CURRENT_VERSION` |
   | 2 | `20` | `04` | unknown; differs host vs watch, likely a role or device class; `04` on both watches in every reply | [unknown] |
   | 3-14 | `16 45 56 41 10 04 41 10 0C 00 00 00` | the watch's packed serial | `SuuntoSerial`, 12 packed bytes | [headers] size; [wire] content |
   | 15-17 | `04 01 02` | `04 01 02` | Whiteboard library version 4.1.2 | [headers] `WbVersion.h` |
   | 18-22 | `00` x5 | `00` x5 | unknown (zero in every capture) | [unknown] |
   | 23 | `03` | `01` | unknown; likely capability flags; `01` on both watches in every reply | [unknown] |
   | 24-31 | `00` x8 | `00` x8 | unknown (zero in every capture) | [unknown] |

   **Across other people's captures** (shared on deepsealabs/libdc-swift#29, Sep 2026): every
   host Hello is 9/9 with byte 2 `20`, byte 23 `03` and Whiteboard 4.1.2. The host identity is
   `ECSD00000002` from the iOS Suunto app (5 captures) and from DC Tester, and **`ECSD00000003`
   from the Android Suunto app** (3 captures), so the last digit looks like the platform. The watch
   reply is the same on 5 watches (Nautic S x2, Nautic, Ocean x2): 9/9, byte 2 `04`, byte 23 `01`,
   the rest zero apart from the serial. [wire] [#29]

   **What the watch checks in a host Hello** (2026-10-18, Nautic fw 2.55.46, a Mac client on a fresh
   link, each Hello followed by a GET of `/Info`) [wire]:
   - Bytes 0-1 must be exactly `09 09`. 8 or 10 in either byte (min 8 / current 9 included) gets no
     reply at all: the Hello is dropped silently.
   - The host serial (bytes 3-14) must be well-formed: digits and capital letters. `FCSD00000002` or
     `EGSD00000002` work as well as `ECSD00000002`, so there's no allow-list of known apps; a serial
     containing `@` or a lowercase letter, or an all-zero one, gets no reply.
   - Bytes 2 and 23 (any of `00`, `04`, `20`; `00`, `01`, `03`) and the Whiteboard version (bytes
     15-17) are not checked, and the watch's reply is the same whatever the host sends.

   **SuuntoSerial packing** [wire]: 16 six-bit characters filling the 12 bytes exactly
   (16 x 6 = 96 bits), least-significant bit first from the field's first bit. Each
   character is stored as **its ASCII code minus 0x2F** ('0' = 1, '9' = 10, 'C' = 20, range
   ASCII 0x30-0x6E); 0 = unused slot. Checked against four watches whose serials are known,
   one of them containing a letter, which fixes the letter mapping. The headers define the
   type (up to 16 characters in 12 bytes) but `pack()`'s code isn't public.

   The host identity decodes to **`ECSD00000002`**. The official Suunto app sends this exact
   Hello, byte for byte, from different phones [app], and the driver's template is a copy
   of it: a fixed app identity, not a per-phone one. The "EVA" in its bytes is an artefact
   of the packing, not ASCII.

   Across the app/driver Hello and four watch replies, payload bytes 0-1, 15-17 and the
   zero runs are identical; byte 2 is `20` for the host and `04` for every watch; byte 23 is
   `03` for the host and `01` for every watch.

   So the reply tells the host which watch it is talking to (its serial) before any `/Info`
   request.

### 5.2 Liveness and identity (optional)

3. `GET /System/Mode` -> on the Ocean answers handle `FF FF FF`, status **404**. libdivecomputer
   uses it only as a round-trip check. [wire]
4. `GET /Info` -> ACK handle `F1 2F 00`, 200. `FETCH` (short) -> one DATA frame (~270 B)
   holding NUL-separated strings: `Suunto`, `Ocean`/`Nautic`, codename (`Vaasa`/`Porvoo`; `Ylivieska` expected on a Nautic S, see Models),
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
    ~4 minutes. [wire] [driver] [max]
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
  driver never does. Both read with a plain GET + short FETCH (reply type `05`, u16):
  `UnsynchronisedLogs` = 0 and `Flags` = **3** on every dive of both watches with all dives
  synced through the Suunto app (2026-10-07, 33 dives) [wire]. A new entry reads `Flags` = **0**
  and raises `UnsynchronisedLogs` by one; after the app syncs it, `Flags` = 3 and the count is
  back down (seen on both watches, 2026-10-15) [wire]. The app sets it with a PUT (`0E`) on the
  entry's `/Flags` handle, answered by a standard `07` (same handle the watch gave our GET of
  that `/Flags`) [wire]. A host can write it too: the watch accepts the same PUT from another
  client (`07` status 200) and `UnsynchronisedLogs` follows (2026-10-16) [wire]. Don't write it in
  normal use: it decides what the Ocean's cleanup may delete (7.3). The app doesn't re-download an
  entry it has already uploaded (it keeps its own list), so marking one unsynced creates no cloud
  duplicate; across two app syncs the entry simply stayed at 0, and `UnsynchronisedLogs` stayed
  raised, until 3 was written back (2026-10-17) [wire]. Over 2 h with the app in the background and
  the count stuck at 1, it made only its hourly sync, triggered by a watch push and writing weather
  and settings, with no logbook access; logbook syncs came only from opening the app. So the raised
  count is harmless, and marking entries unsynced is a workable way for a host to keep chosen dives
  on an Ocean (2026-10-17) [wire]. Note: the GET binds a handle; ~30 unreleased handles
  make the watch answer 400 until reconnect [wire]. `/Logbook/UnsynchronisedLogs` and
  `/Sync/BusyState` are subscribable values. **BusyState changes are pushed** to a subscriber:
  DC Tester's Auto download got "busy" while connected, about 2 minutes before a tub dive began
  (2026-10-16) [wire]. BusyState is 1 while the watch is in its pre-dive (dive-ready) mode and
  stays 1 through the dive's end-of-dive wait; the link stays up in pre-dive mode. After a dive,
  `UnsynchronisedLogs` rises first and BusyState drops to 0 some 10-20 s later (2026-10-18, both
  watches) [wire]. **`UnsynchronisedLogs` changes are pushed too**, on its handle (`F0 24 0D`
  on both watches), payload type `05` + u32 count: up when an entry is saved (1 after a dive, 2
  after a second entry) and down to 0 when the app marks the entries synced (2026-10-18, phone +
  Ocean and iPad + Nautic, Auto download listening) [wire].
- **On Android the watch also makes requests to the phone**: GET `/Media/Notification/Action`,
  `/Media/Player/Control`, `/Media/Player/State` and `/Media/Track/Info`, answered 200 by the Suunto
  app (music control and notification actions), using the same RPC frames in the other direction.
  Not seen in any iOS capture. [wire] [#29] (pyrignis's Android Bluetooth logs, Sep 2026)
- Re-lists /Logbook/Entries twice per sync and fetches /Summary several times per dive.
- Reads the per-dive schema **`/Logbook/byId/<id>/Descriptors`** before /Summary and /Data
  when a dive is opened (path seen in a PacketLogger capture of the Suunto app; latishab decoded it on
  #29, 2026-09-01). It is an uncompressed SBEM0103 schema (~43.5 KB, ~344 records): GRP
  records map a record id to its ordered field ids; PTH (field name paths such as
  `suunto/sml.Sample.DiveEvents.Alarm.Type`), FRM, DELTAREF and MOD records define names,
  types, scaling and enum values. The global `/DataFormat/Descriptors` is only the
  top-level schema. Now fetched for one dive on each watch and decoded (6.6); it names every
  /Summary field and the /Data event types (7.1). [app] [#29] [schema]

### 5.8 Sharing the link: sessions

Measured 2026-10-18 on the Nautic (fw 2.55.46): a Mac with several client processes on one link,
then the Suunto app (3.15.0) on an iPhone (Ocean, fw 2.51.28) and an iPad (Nautic). [wire]

- **A session belongs to the link, not to a client.** A Hello opens it; afterwards the watch
  answers requests from any client on that link, including one that never sent a Hello. It
  survives another client's streams, UNSUBSCRIBEs and RELEASEs, and the disconnect of the client
  that opened it, as long as some client keeps the link up.
- **With no session, a request without a Hello is ignored** (no reply). So a host can tell
  whether another client already has a session: send a request first and say Hello only if it
  goes unanswered. (Exception: while any client's `/Data` stream is running, a client that never
  sent a Hello gets no reply either; wait until the link is quiet, then ask.)
- **A Hello takes the session over.** The Suunto app answers a foreign Hello with its own,
  usually within a second (the ping-pong). When it doesn't, typically when the Hello lands in a
  quiet gap during its sync, it keeps sending requests but no longer uses the replies: one
  request about every 10 s, each answered by the watch, no follow-up, "sync done" without the
  new dives, until the app is restarted. Seen on both phones (2026-10-18). A host that uses the
  existing session instead of saying Hello avoids it; the same test then left both apps healthy.
- **Likely one `/Data` stream at a time.** The Suunto app's other requests are answered while we
  stream, but its request for the same dive's `/Data` during our stream drew no reply that we could
  see; the app reported "sync failed" and retried by itself about 3.5 min later, successfully
  (one instance, 2026-10-18). [inferred]
- **HDLC sync when joining mid-stream.** Stream frames come back to back (`7E ... 7E 7E ... 7E`).
  A reader that starts inside a frame and treats a closing flag as an opening one returns an
  empty frame at every flag and never resynchronises while the stream lasts, so it sees nothing,
  including replies meant for it. Treat two flags in a row as the start of the next frame.
  [driver]
- Driver changes and test logs: deepsealabs/libdivecomputer#16, deepsealabs/libdc-swift#78.

---

## 6. Content formats

### 6.1 `/Logbook/Entries` DATA content

```
01 24 | BE 25 70 73 | count:u32 | 0C 00 00 00 | 45 00 00 00 | records ...
```
- Header fields, compared over 16 captures (2026-10-03 to 10-07, both watches): `01 24` at +0
  and a u16 at +2 (`FE 24` Nautic, `BE 25` Ocean page 1, `86 24` Ocean page 2) are constant;
  **count** is a u16 at +6 (10, 18, 5); a u32 at +10 is always 12. The bytes at +4 (2), +8 (2)
  and +14 (4) change on every capture and hold ASCII fragments ("tem_", "es.s", "ps") and
  RAM-like addresses (`0x1002xxxx`): **struct alignment padding** copied out uncleared, not
  fields. Tested 2026-10-07 (Ocean, five list reads in ~4 min, read-only, no other activity):
  the gap bytes change between identical back-to-back reads and follow the preceding request
  (`/Summary`, `/Info`), while the fields stay fixed. [wire] One header value falls in the timestamp window and
  must not be read as a dive. [driver]
- **Record**, 24 bytes, all u32 LE: `[start][end][w1][w2][size][pad]` [driver] [wire]
  - `start` = the dive's **LogId** and UNIX start time (seconds). This is the id used in
    `/Logbook/byId/<id>/...`.
  - `end` = end time (within a day of start).
  - `w1`, `w2`: only `w1`'s **low byte** is stable (always `01`, a u8 field). `w1`'s upper 3
    bytes and `w2` change between captures without any watch activity, and sometimes hold the
    watch's clock at capture time (Unix time with its low byte overwritten by the `01`; a packed
    date in `w2`) or `0x1002xxxx` addresses: padding, not flags; not a sync signal. Same test:
    `w1`/`w2` changed on 15 of 23 dives between identical back-to-back reads and changed back
    (e.g. `10024f01/00000002` -> `6ac6f301/24261008` -> `10024f01/00000002`); `w1`'s low byte
    stayed `01` on every dive. [wire]
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
- Header bytes 16-19 (u32 LE) are the chunk's **offset in the compressed stream**: each chunk's
  offset = the previous offset + the previous payload size (verified on every chunk of a
  Nautic and two Ocean downloads, 4,341 / 5,407 / 192 chunks). Described first by Max in
  libdivecomputer/libdivecomputer#70. [wire]
- **End of stream:** the last chunk has payload size **0**, at an offset equal to the total
  compressed length (e.g. 1,502,475 on an Ocean dive, exactly what the driver captured), and
  the watch sends it **twice** (byte-identical; it repeats its last chunk until told to stop).
  Checked 2026-10-14 on every captured stream of all 33 dives on two watches (50 streams,
  Nautic fw 2.55.46 and Ocean fw 2.51.28): present at the end of every stream, never earlier,
  offset chain unbroken. [wire] A driver could stop on it instead of waiting for silence, but
  should keep the silence / `STREAM_END` fallback: other models (Nautic S) and firmware are
  unchecked. An interrupted stream ends **without** the marker: when another client's
  UNSUBSCRIBE ends it, the chunks just stop (seen on both watches, 2026-10-16 to 10-18, Suunto app
  and a second Mac client); after another client's Hello it ends with a torn chunk or a 404
  `UNSUBSCRIBE_REPLY`. So the marker means "complete". [wire]
- The 28-byte "MDS" header is counted from the frame's first byte (`A5`); the payload size
  is the u16 LE at frame offset 20, and the payload starts at offset 28. [driver] [wire] [max]
- Stream chunks carry msgid `0000` and the resource's static handle `F0 24 0E`, not the
  `00 24 0E` slot the GET returned. [wire]
- Concatenated payloads = one **Heatshrink** (LZSS) stream, window_sz2 7, lookahead_sz2 5. [driver] [max]
- Decompressed = an **SBEM0103** sample stream. Example: 91,988 compressed -> 101,550 B. [wire]
- Note: the "always-on telemetry" frames noted on 2026-09-14 (`7EA5 012D 0100 00F0 240E ...`)
  match this chunk shape. Most likely a /Data stream left running by DC Tester's then-missing
  stream stop, not analytics. [inferred]

### 6.4 Chunk/stream boundaries

Chunk boundaries are a transport artifact; only the concatenated, decompressed stream
means anything. [driver]

### 6.5 SBEM0103 container (both /Data and /Summary)

- Starts with the ASCII signature `SBEM0103`. [max]
- Then TLV records: `[id:1][length:1][value]`; length `FF` = a 4-byte LE length follows.
  Unknown ids are skipped. [driver] [max] (TLV layout and the `FF` extended length)
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
DiveFooter 507/658).

**Checked on every archived dive (2026-10-18):** all 39 raw `/Summary` records (14 Nautic, 25 Ocean,
Aug 29 to Oct 18) decoded with the schema, 520 / 434 fields per dive. No enum value outside the
schema and no NaN/inf in any float. Against the Suunto cloud (9 dives with a cloud copy, 6 of them
in the `sml` format with DiveHeader and DiveFooter), 597 field/watch pairs agree on every dive,
timestamps included once the `local64` format is applied, and cloud values rounded to the schema
precision. The only disagreement: Header `ZoneSenseZones` Zone2Duration and Zone2/Zone3LowerLimit
(+346 to +361) hold leftover memory on some Nautic dives (the bytes there resemble a `/Summary`
page header, `0D 00 02 08 00 00 08 ...`, like the padding in 6.1), while the cloud shows 0 / 0.2 /
0.5; don't rely on them. [wire] [cloud] Points the schema settles:
- Gas record (45 B): State enum +0 (0 OC, 1 CCR diluent, 2 CCR oxygen, 3 Suit), **Oxygen
  int16 +1, Helium int16 +3**, PO2 f32 +5, TankSize f32 +9, TransmitterID/2 int32 +13/+17,
  TankFillPressure int32 +21, Start/End pressure +25/+29, Start2/End2 +33/+37 (int32 Pa),
  AvgVentilation f32 +41. **Verified on a watch** (2026-10-16): a Nautic tub dive set to 18/40
  reads O2 18 at +1 and He 40 at +3 in both gas arrays (no match in the swapped order), and an
  Ocean dive on 27% nitrox reads 27 / 0. [wire] Older drivers read He as a u8 at +2 (the high
  byte of O2), so helium came out 0; the deepsealabs driver reads both int16 since build 22.
- DiveHeader: +24 DeactivationTimeout, +41 SafetyStopTime (both int32); +32 Algorithm enum
  (0 Off, 1 Suunto RGBM, 2 Buhlmann); +33 Altitude, +35 Conservatism (int16); +45
  LastDecoStopDepth enum (3 = 3 m, 6 = 6 m); +46 AscentModeStepped, +47 OOAM (bool).
  **Verified on both watches** (2026-10-18, bucket dives with distinct settings): [wire]
  - DeactivationTimeout = the dive end time in seconds (1 min reads 60).
  - Algorithm 2 on both (the Ocean offers no other choice); HighGf +37 / LowGf +39 read 82/34
    (Nautic) and 50/40 (Ocean), as set.
  - Altitude is the menu index, not a height: 0 = 0-980 ft, 1 = 980-4900 ft, 2 = 4900-9800 ft
    (Ocean 1, Nautic 2).
  - SafetyStopTime in seconds: 5 min reads 300. The Ocean's "Adjusted" setting reads 180, the
    same as a 3-minute stop.
  - LastDecoStopDepth 6 (20 ft) and 3 (10 ft); AscentModeStepped 1 (stepped) and 0 (continuous).
  - Gas TankFillPressure (+21) differs in units between the watches: the Nautic stores Pa
    (23200000), the Ocean bar (232). A twin set ("2x AL72") is stored as one gas with the combined
    TankSize (0.02 m3).
- Nautic's extra 151 B per record = 3 more gas slots (8 vs 5) + a 16-B CCR Setpoint block
  (Low/High f32, SwitchDepthLow/High int8, IsAutomatic/IsCustom bool, Custom f32).
- **CCR (Nautic only): header fields verified on a CCR bucket dive** (2026-10-18; set: low 0.5 /
  high 1.6, switch 10 ft / 59 ft, automatic, diluent 15/46 in an AL50; CCR mode adds an oxygen
  gas by itself). On open-circuit dives these bytes are zero. [wire]
  - Setpoint block, DiveHeader +545 and DiveFooter +642 (identical on both CCR dives): Low and High are f32
    **Pa** (read 50000.0 / 160000.0 = 0.5 / 1.6 bar), SwitchDepthLow/High int8 metres (3 / 18),
    SetpointIsAutomatic 1, SetpointIsCustom 0, Custom (f32).
  - Gas record State 1 = CCR diluent (read 15/46, TankSize 0.007 m3), 2 = CCR oxygen (100/0,
    0.003 m3), in both the DiveHeader and DiveFooter gas arrays. The record order is diluent first, then
    oxygen, but the watch's gas menu lists the oxygen (NX100) above the diluent and numbers neither,
    so the record index is not the menu order. Both gases' PO2 field (+5) reads
    1.399; its meaning for a diluent is still unknown.
  - A scrubbed copy of this dive's `/Summary` is attached to deepsealabs/libdc-swift#94.
  - How a dive is flagged as CCR: there is no dive-mode field in `/Summary`. Possibly the
    `/Data` activity chunk `08` (sport id plus a `customModeId` text field), or the gas states.
  - Setpoint switches: **decoded on a Nautic CCR bucket dive with two manual switches** (2026-10-18,
    dive 1792349453, matched against the Suunto cloud copy). [wire] [schema] [cloud]
    - `Sample.DiveEvents.SetpointSwitch` (group id per dive; `0x20` on this one): after the 2-byte
      time delta, PO2 f32 at +2 in **bar** (1.6, 0.5; the header's setpoints are in Pa), Mode enum at
      +6 (0 Automatic, 1 Low, 2 High, 3 Custom).
      Automatic switches use the same event: `SetpointSwitch {Mode: Automatic, PO2: 0.7 / 1.3}` in
      Suunto app exports of two real Nautic CCR dives (deepsealabs/libdc-swift#29, 2026-09-24).
    - `Sample.DiveEvents.Notify` (`0x1a`): Type enum at +2 (21 Setpoint switch, 11 Gas Switch, 61
      Bearing cleared, ...), Active bool at +3. It tracks the on-screen message (on, then off 10 s
      later) and was not logged for the second switch: use the SetpointSwitch records.
    - No SetpointSwitch at dive start: the dive begins on the header's low setpoint.
    - `GasSwitch` (`0x1f`, GasNumber int16 at +2) logs gas 0 (the diluent) at the start.
    - The activity record stays 51 / "51" in CCR mode.
    - On the watch, the switch is in the dive's change menu (down button), next to "add gas".
  - The Ocean's schema has no setpoint block (5 gas slots, records end at the gas array).
  - The libdivecomputer parser currently treats the Nautic and Ocean as open-circuit only:
    every dive is reported as OC, gases get no diluent/oxygen role, and no setpoints are emitted.
    [driver]
    Confirmed with the CCR dive above; reported as deepsealabs/libdc-swift#94.
- GPS: int32 degrees x 1e7 (schema: PI*x/(1e7*180) radians); GPSAltitude uint16, x/5 - 1000 m.
- `local64` times (e.g. DiveFooter `DiveLocation.Start/Stop.DateTime`): **local wall-clock milliseconds**
  in the low 7 bytes, flag byte `0xF0` on top. The GPS start/stop "DateTime" equals the dive's start
  and end time, not the moment the fix was taken, so a stale (reused) fix can't be detected from it.
  [wire] [cloud]

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
| Gas records | from 0xC7 (199), 45 B each | same | O2 % int16 +1, He % int16 +3, PO2 max f32 +5, tank size f32 m^3 +9 | **yes** | [driver] [cloud-matched] [wire] |
| Transmitter IDs, gas 0 (tank 1 / tank 2) | 212 / 216 | same | u32 (inside gas record 0) | no | [cloud-matched] |
| Desaturation time / no-fly time | 589 / 593 | 438 / 442 | u32, s, DiveFooter +8 / +12 | no | [cloud-matched] |
| Footer gas 0: PO2, tank size, transmitter IDs | 868, 872, 876 / 880 | 717, 721, 725 / 729 | as above | no | [cloud-matched] |
| Footer gas 0: start / end pressure, tank 1 | 888 / 892 | 737 / 741 | u32, Pa, DiveFooter +307 / +311 | no (driver uses samples) | [cloud-matched] |
| Footer gas 0: start / end pressure, tank 2 (sidemount) | 896 / 900 | 745 / 749 | u32, Pa, DiveFooter +315 / +319 | no | [cloud-matched] |
| Per-window stats records (max depth, dive time, duration, distance, water temp min/max, vertical speed) | ~1250-1940, records 241 B apart | ~950-1640 | f32 | no | [cloud-matched]; which record is the whole dive is unresolved |
| Dive time / max depth (dive record) | Header +321 / +330 | same | f32, s / m | **yes** | [driver] |
| Average depth | 2306 (also 1938) | 2004 (also 1636) | f32, m, Header +338 (also Window 3 +215) | no (driver averages the samples) | [cloud-matched] |
| Feeling (the post-dive "How was this dive?" answer) | 2239 | 1937 | int32, Header +271 (schema `Header.Feeling`): 1-5, 0 = not answered | no | [schema] [cloud-matched]: all 22 archived Ocean dives match the cloud `feeling` (5 <-> 5, 0 <-> null) |
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
| Gas records (45 B each) | DiveHeader | from +185: O2 int16 +1, He int16 +3, PO2 max f32 +5, tank m^3 f32 +9, transmitter IDs u32 +13/+17, fill pressure (bar) +21 |
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
| Feeling ("How was this dive?", 1-5, 0 = not answered) | Header | +271 int32 |
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
| Dive id / start time | Entries record `start` | u32 UNIX seconds | [wire] [driver] [max] (ids are UNIX timestamps) |
| Dive end time | Entries record `end` | u32 UNIX seconds | [driver] |
| Expected download size | Entries record `size` | u32 = /Data compressed + /Summary bytes | [driver] [wire] |
| Absolute dive start (clock) | /Data GPS record `0B` | UTC ms; start = gps_utc - gps_rel_time | [driver] |
| No-GPS dive start | only the LogId (dive id) | fallback | [driver] |
| Depth | /Data `16` (extended status), every ~10 s | float32 at +2 (m) | [driver] |
| Water temperature | /Data `12` (1 Hz profile) | u16 at +16, centi-kelvin (value/100 - 273.15) | [driver] [max] |
| **Absolute pressure, ~1 Hz** | /Data `12` | u32 at +6, Pa (`FFFFFFFF` = none). depth = (P - surface pressure from `17`) / (rho x 9.81), rho from the water type (1000 fresh / 1020 EN13319 / 1030 salt), matching the `16` depths to ~1 cm. **Not decoded by the parser.** The Suunto app's max depth is the peak of these (25.00/16.21/25.13/16.32 m vs the 10 s samples' 24.72/16.00/24.92/16.07 m on four Sep 14 dives) | [wire-derived 2026-10-04] [max] |
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
| IMU (accel/gyro/mag) | /Data group `23` (Nautic) / `22` (Ocean): the id is assigned in the watch's Descriptors GRP table, so look it up there rather than inferring it from payload size | 10 Hz. `[dt int16][AlgoRelativeTimestamp u32 ms][DiveRouteAcc XYZ][DiveRouteGyro XYZ][DiveRouteMagn XYZ]`, all int16 raw counts (the schema gives no scaling). Gyro x 1/131 = deg/s (~0.01 deg/s when still; scale and per-axis asymmetry untested). Accel x 1/4096 reads ~2% low: fitting per-axis scale + bias to ~6-7k near-still samples per watch (Sep 14 AM) gives scale x1.019-1.023 (axes within 0.3% of each other), bias up to ~11 mg, residual 7-8 mg; cross-axis terms add nothing. Magnetometer needs full hard/soft-iron calibration: offsets ~600-1,750 counts (larger than the ~750-860-count Earth field), axis gains up to 1.39 relative to X, 12-17% residual even after fitting; no accel or magnetometer calibration is exported (only the gyro bias) | [driver] [schema] [wire-derived] |
| Dive-route features | /Data group `24` (Nautic) / `23` (Ocean) | 5 x uint16 `DiveRouteFeatures`, inputs to the app's dead reckoning; meanings unknown. The X/Y/Z route itself is computed by the app, not stored | [driver] [schema] |
| Gyro bias | /Summary DiveFooter +17/+21/+25 (f32), FigureOfMerit +29 | `DiveRouteGyroBias`; units unclear (1.04/0.31/1.08 on the Nautic vs ~0.01 deg/s measured when still) | [schema] [unknown] |
| Events | /Data `18` alarm, `19` warning, `1A` notify, `1B` state | `[dt][Type][Active]`. Type names from the per-dive schema (same on both watches; ids from the 2026-10 firmware): **alarm** 1 PO2 Low, 2 PO2 High, 3 Tank Pressure, 4 Gas Time, 5 Ascent Speed, 7 CNS100%, 8 OTU300, 10 Deco Stop Broken, 12 Deep Stop Broken, 13 Safety Stop Broken, 31 Depth, 50 Battery; **warning** 6 User PO2 High, 14 CNS80%, 15 OTU250, 20 NoDecoTime, 28 User Tank Pressure, 29 User Gas Time, 30 Sidemount, 31 Depth, 32 Dive Time, 42 User Ndl, 44 Recovery time, 50 Battery; **notify** 11 Gas Switch, 21 Setpoint switch (Nautic only), 28 User Tank Pressure, 29 User Gas Time, 30 Sidemount, 31 Depth, 32 Dive Time, 41 Stop done, 42 User Ndl, 44 Recovery time, 60 Bearing set, 61 Bearing cleared, 62 Stopwatch started, 63 Stopwatch reset; **state** 19 Ndl exceeded, 35-37 At Deco / Deep / Safety Stop, 38-40 Deco / Deep / Safety Stop Ahead. Seen on a watch: alarm 3 Tank Pressure on at a deliberate valve shut-off and purge (the tank pressure sample dropped to the purged hose pressure) and off 10 s later, after the valve was reopened; notify 60/61 bearing set/cleared | [driver] [schema] [wire] |
| Dive state | /Data `1C` | 0 idling, 1 diving, 2 recovering | [driver] |
| Dive active flag | /Data `1E` | | [driver] |
| Dive-end reason | /Data `1D` (OOAM) | 1 Out of battery, 2 Ceiling broken, 3 SW crash, 4 Max depth, 5 Algorithm changed, 6 Gauge dive | [driver] [schema] |
| Gas switch | /Data `1F` | int16 gas number (0-based = cylinder slot) | [driver] |
| Gradient factors | /Summary | u16 at 0x33 (high) and 0x35 (low), from the SBEM signature | [driver] |
| Water type | /Summary byte 0x3E (from the SBEM signature) | 0 fresh, 1 EN13319, 2 salt. Consistent on all 33 of my dives against the density fitted from `12`/`16`, and confirmed against the cloud `DiveHeader.WaterType` (Fresh/EN13319/Salt dives, 2026-10-04). Prior art: latishab already decodes it as DC_FIELD_SALINITY in libdivecomputer#73 (commit `cd3dbc890`, 2026-09-08), but the deepsealabs fork that libdc-swift ships does not | [wire-derived] [cloud] |
| More /Summary fields (avg depth, tank start/end pressures per transmitter, temperatures, desat/no-fly, tissue) | /Summary | see 6.6 | [cloud-matched] |
| Gas mixes | /Summary from 0xC7 | 45-byte record per gas: O2% +1, He% +2, PO2 max float32 +5, cylinder volume float32 m^3 +9; record index = GasNumber = cylinder slot | [driver] |
| Daily trend data | `/Activity/TrendData`: GET, then FETCH with one parameter `[01][08 00][since u64 ms]` (type 8); reply 202 with a page of records | 40-byte records every 10 min, each starting with a u64 ms timestamp. On the Ocean (2026-10-08) "since 0" returned records from 2026-10-01 00:30 UTC, ~7.8 days back: **about one week kept on the watch**. A since of 2026-01-01 returned 416 | [wire] |
| Sleep timeline | `/Daily/Sleep/Timeline/Data`: the app's FETCH names a file (`mdsSlp.sbm`) and the watch answers 201 Created, i.e. it **writes an export file** that the app then reads via `/Dev/FileSystem` | not read-only; not used by our tools | [app] |
| Activity history | `/Activity/History/App/LastFourWeeks`: plain GET + FETCH, 78-byte reply | format unknown. Two Ocean reads 10 days apart (2026-10-08, 10-18, chores and bucket dives in between): the first 54 bytes stayed identical (u32 values 2, 8, 0, 0, 4, 40, 51, 0, 4, 56; 51 is the dive ActivityType), the remaining f32 values changed (e.g. 52509.4 -> 8699.2, 3335.5, 8665.6, 2399.4), perhaps per-week totals | [wire] |
| Serial, firmware, MACs | `/Info` | NUL-separated strings: maker, model, codename (Vaasa = Nautic, Porvoo = Ocean), serial, firmware version (e.g. 2.55.46 / 2.51.28), hardware revision, build identifiers, BLE and Wi-Fi MAC. No build date | [wire] [driver] |
| Firmware per dive | /Summary Header `Device.Info.SW` | enum index; its text (the version the dive was recorded with) is in that dive's Descriptors (`enum:0=2.51.28`). The cloud record carries the same `SW` | [schema] [cloud] |

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

### 7.3 How long dives stay on the watch

- **If `/Logbook/Entries` lists an entry, its raw data is there.** Every listed dive on two
  watches has downloaded complete (exact size check, repeated daily on the oldest dive, byte
  comparisons against archived copies). Entries are removed whole: they leave the list and then
  answer **404** by id, with no partial or degraded state before that. [wire]
- **Ocean: saving any new entry deletes every synced entry that started more than 31 days earlier.**
  The age runs from the old entry's **start** (its id) to the moment the new entry is **saved**,
  and the cutoff is 31 days to within about 2 minutes. Any new entry triggers it, a dive or any
  other activity; age alone does not (dives sat untouched for 51 days while nothing new was
  recorded). **Only synced entries (`Flags` = 3) are deleted:** with an entry's `Flags` written to 0
  (unsynced) it survived a save 31 d + 2 h after its start, and with 3 written back the next save
  deleted it (2026-10-16; the watch accepts a host's PUT to `/Flags`, see 5.7). Not
  in the user guide, which only mentions deleting the oldest dives when the logbook memory is
  full. [wire] (2026-10-15/16)
- **Nautic: no such cleanup.** Dives 34-35 days older than new tub dives were all kept; its user
  guide's rule is the memory-full one. [wire]
- For a host app: on an Ocean, download promptly, and before the watch records anything new if
  the last download is more than a month old. Comparing every listed id and size against the
  host's database catches entries missed by an interrupted run.
- Evidence: four controlled tests (a full read and complete downloads before, one new entry with
  nothing else connected, a full read and 404 checks after), with timelines and every entry's
  age, are in the deepsealabs/libdc-swift#29 comment on Ocean retention. The deciding one: a dive
  saved at ~19:59:48 deleted an entry that started at 19:58:13 thirty-one days earlier (31 d +
  95 s) and kept one from 20:02:10 (31 d - 142 s); measured from the new dive's start, or from
  the old entry's end, both would have been kept.

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
| Suunto app "sync done" without the new dive, requests every ~10 s | another client's Hello took its session; the app didn't re-open it | no Hello over an existing session (5.8; deepsealabs/libdivecomputer#16); restart the app to recover |
| Nothing received while another client streams | HDLC reader out of sync on back-to-back frames | skip empty frames (5.8; deepsealabs/libdivecomputer#16) |

---

## 9. Open questions

- The constant Entries header fields (the u16 at +2, the u32 = 12 at +10) and `w1`'s low byte
  (always 1); the varying bytes look like struct padding (6.1).
- The meaning of the Hello's bytes 2 and 23 (the watch doesn't check them, and accepts any
  well-formed host identity; 5.1).
- Whether the watch serves only one `/Data` stream at a time (5.8; seen once).
- What the Activity History reply's float fields are (7.1).
- Porting the transport fixes upstream: libdivecomputer/libdivecomputer#73 has carried per-dive
  handles and their release since 2026-10-16, but not the rest of the libdc-swift 1.16.1 / 1.17.1
  fixes (paging, size check, foreach gap, message ids, the dive time / max depth parser fix); Jef's
  review there (2026-10-18) flags the /Summary page CRC and the ignored /Summary errors. latishab
  plans to port them (deepsealabs/libdc-swift#29, 2026-10-04); subscription and auto-sync stay on
  the deepsealabs fork. Open until the port lands.

Answered since and removed from this list: dive retention (7.3); whether `UnsynchronisedLogs`
changes are pushed (5.7); whether the watch accepts another host identity (5.1); the water type /
salinity decode missing from the deepsealabs fork (it decodes `/Summary` 0x3E now).
