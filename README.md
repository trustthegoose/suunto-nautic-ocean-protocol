# Suunto Nautic / Ocean protocol map

A community reference for talking to the Suunto Nautic, Nautic S and Ocean dive computers over Bluetooth LE: connection preconditions, HDLC/RPC framing, the dive download sequence, content formats, and where each piece of dive data lives.

It grew out of testing the [libdc-swift](https://github.com/deepsealabs/libdc-swift) / libdivecomputer driver ([#29](https://github.com/deepsealabs/libdc-swift/issues/29), [libdivecomputer#73](https://github.com/libdivecomputer/libdivecomputer/pull/73)) and is meant as an easy place to spot where the driver, the watch and the Suunto app disagree.

## Contents

- [`PROTOCOL_MAP.md`](PROTOCOL_MAP.md): the map. Every statement carries an evidence tag ([wire], [driver], [app], [cloud], [cloud-matched], [unknown]) saying how it is known.
- [`schema/`](schema/): every `/Summary` field with its byte offset, type, scaling and enum values, decoded from the watch's own per-dive `/Logbook/byId/<id>/Descriptors` schema (one Nautic and one Ocean, firmware as of 2026-10).
- [`tools/descriptors_decode.py`](tools/descriptors_decode.py): decoder for a `Descriptors` file (`python3 tools/descriptors_decode.py FILE [GROUP_ID ...]`).

## Contributing

Corrections and additions are welcome, especially from other watches, firmware versions and dive setups (multi-gas, trimix, CCR, sidemount).

- Something wrong or missing: open an issue, saying what you saw and on which watch and firmware.
- A fix you can show: open a pull request that changes the map and states the evidence (a trace, a capture, a cloud file, driver code), with the matching evidence tag.

Please don't post watch serial numbers, real GPS positions or other personal data; use placeholders such as `<serial>`.

## License

[CC0 1.0](LICENSE): public domain. Use, copy and adapt anything here for any purpose, no credit needed.
