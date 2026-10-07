#!/usr/bin/env python3
"""Decode a Suunto per-dive /Logbook/byId/<id>/Descriptors schema (SBEM0103, text records).

Record: [0x00][len u8, or FF + u32][id u16 LE][text, NUL-terminated]; len counts id + text. Text is one or more lines:
<PTH> field path, <FRM> format, <MOD> modifier, <DELTAREF> delta base, <GRP> field-id list.
A GRP's record id is the data record (chunk) id it describes.
usage: descriptors_decode.py FILE [GROUP_ID ...]   (ids in hex or decimal)
"""
import re, struct, sys

def parse(buf):
    pos = buf.find(b"SBEM0103") + 8
    recs = {}
    while pos + 4 <= len(buf):
        if buf[pos] != 0:
            pos += 1; continue
        ln = buf[pos + 1]; hdr = 2
        if ln == 0xFF:  # long record: FF + u32 length, as in SBEM data records
            ln = struct.unpack_from("<I", buf, pos + 2)[0]; hdr = 6
        rid = struct.unpack_from("<H", buf, pos + hdr)[0]
        text = buf[pos + hdr + 2: pos + hdr + ln].split(b"\x00")[0].decode("utf-8", "replace")
        if not text.startswith("<"):
            pos += 1; continue
        d = {}
        for line in text.split("\n"):
            m = re.match(r"<([A-Z]+)>(.*)", line)
            if m: d.setdefault(m.group(1), []).append(m.group(2))
        recs[rid] = d
        pos += hdr + ln
    return recs

SIZES = {"uint8": 1, "int8": 1, "uint16": 2, "int16": 2, "uint32": 4, "int32": 4, "float32": 4,
         "uint64": 8, "int64": 8, "float64": 8, "local64": 8, "dint16": 2, "d0": 0, "bool": 1}

def size_of(frm):
    base = frm.split(",")[0]
    if base.startswith("enum"): return 1
    return SIZES.get(base)

if __name__ == "__main__":
    recs = parse(open(sys.argv[1], "rb").read())
    groups = [int(g, 0) for g in sys.argv[2:]] or sorted(r for r, d in recs.items() if "GRP" in d)
    for g in groups:
        d = recs.get(g)
        if not d or "GRP" not in d:
            print(f"GRP 0x{g:02x}: not present"); continue
        ids = [int(x) for x in d["GRP"][0].split(",") if x]
        print(f"== GRP 0x{g:02x} ({len(ids)} fields)")
        off = 0; prev = None; rep = 0
        def flush():
            if prev and rep > 1: print(f"         ... x{rep} (same field repeated)")
        for fid in ids:
            if fid == prev:
                rep += 1
                f = recs.get(fid, {}); sz = size_of((f.get("FRM") or ["?"])[0])
                off = None if (off is None or sz is None) else off + sz
                continue
            flush(); prev = fid; rep = 1
            f = recs.get(fid, {})
            path = (f.get("PTH") or f.get("DELTAREF") and [f"<delta of {f['DELTAREF'][0]}>"] or ["?"])[0]
            frm = (f.get("FRM") or ["?"])[0]; mod = ",".join(f.get("MOD", []))
            sz = size_of(frm)
            print(f"   +{off if off is not None else '?':<5} {fid:4d} {frm[:44]:44s} {mod[:24]:24s} {path.replace('Samples.TimelineSample.Attributes.suunto/sml.', '')}")
            off = None if (off is None or sz is None) else off + sz
        flush()
        print(f"   record length from schema: {off if off is not None else '?'} B")
