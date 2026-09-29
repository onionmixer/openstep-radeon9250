#!/usr/bin/env python3
"""R7 design 2: which registers the verifier must range-check, derived from the DRM, not asserted.

  python3 build/r7/design2.py

The plan says the verifier range-checks three registers: RB3D_COLOROFFSET, RB3D_DEPTHOFFSET and
PP_TXOFFSET_0.  "Those are the only address-bearing ones a client can write" is an ABSENCE claim,
and a cross-review's word for it is not evidence.  So it is computed:

  1. read every `RADEON_EMIT_*` / `R200_EMIT_*` id and its number   (radeon_drm.h)
  2. read packet[], indexed by that number, for the id's first register and length  (radeon_state.c)
  3. read radeon_check_and_fixup_packets and work out, for each checked id, WHICH WORD of the
     packet it fixes up -- the DRM writes that as `data[(ADDRESS_REG - FIRST_REG) / 4]`, so the
     register being treated as an address is recoverable exactly  (radeon_state.c)
  4. intersect that set of address registers with the 41 a client may write

A first attempt compared whole packet SPANS and produced two false positives (PP_MISC and PP_CNTL
span registers we allow), which is why step 3 exists: the packet spans our registers, but the word
it treats as an address is the one we already check.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
DRM = os.path.join(PROJ, 'ref', 'upstream', 'freebsd-stable9', 'sys', 'dev', 'drm')
# the 41 a client may write (build/r7/design1.py, less the four reserved to the driver)
CLIENT = set(int(x, 16) for x in
             '1c20 1c24 1c28 1c2c 1c38 1c3c 1c40 1c44 1c48 1c4c 1c50 1cd8 1cdc 1ce0 1ce4 1ce8 1cec '
             '1d60 1d7c 1d84 2080 2088 208c 20b0 2140 2180 2284 26c0 26f0 2c00 2c04 2c08 2c0c 2c10 '
             '2c1c 2cc4 2d00 2f00 2f04 2f08 2f0c'.split())
RANGE_CHECKED = {0x1c40: 'RB3D_COLOROFFSET', 0x1c24: 'RB3D_DEPTHOFFSET', 0x2d00: 'PP_TXOFFSET_0'}


def defines(*texts):
    out = {}
    for t in texts:
        for m in re.finditer(r'#define\s+([A-Za-z_][A-Za-z0-9_]*)\s+(0x[0-9a-fA-F]+)\b', t):
            out.setdefault(m.group(1), int(m.group(2), 16))
    return out


def main():
    state = open(os.path.join(DRM, 'radeon_state.c'), errors='replace').read()
    drm = open(os.path.join(DRM, 'radeon_drm.h'), errors='replace').read()
    drv = open(os.path.join(DRM, 'radeon_drv.h'), errors='replace').read()
    sym = defines(drv, drm)
    ids = dict((m.group(1), int(m.group(2)))
               for m in re.finditer(r'#define\s+((?:RADEON|R200)_EMIT_[A-Z0-9_]+)\s+(\d+)', drm))
    i = state.index('} packet[RADEON_MAX_STATE_PACKETS] = {')
    rows = re.findall(r'\{\s*([A-Za-z0-9_]+)\s*,\s*(\d+)\s*,\s*"([^"]+)"\s*\}', state[i:state.index('\n};', i)])
    packet = [(sym.get(r[0]), int(r[1]), r[2]) for r in rows]

    # step 3: the address word of each checked id
    head = state[:i]
    addrs, cur = {}, []
    for line in head.splitlines():
        m = re.match(r'\s*case ((?:RADEON|R200)_EMIT_[A-Z0-9_]+):', line)
        if m:
            cur.append(m.group(1))
            continue
        m = re.search(r'&data\[\((\w+) - (\w+)\) / 4\]', line)
        if m and cur:
            for c in cur:
                addrs[c] = sym.get(m.group(1))       # the register named as the address
        elif re.search(r'&data\[(\d+)\]', line) and cur:
            k = int(re.search(r'&data\[(\d+)\]', line).group(1))
            for c in cur:
                n = ids.get(c)
                if n is not None and n < len(packet) and packet[n][0] is not None:
                    addrs[c] = packet[n][0] + 4 * k
        elif re.search(r'&data\[i\]', line) and cur:  # the cubic loops: every word is an address
            for c in cur:
                n = ids.get(c)
                if n is not None and n < len(packet) and packet[n][0] is not None:
                    off, ln, _ = packet[n]
                    addrs[c] = [off + 4 * k for k in range(ln)]
        if line.strip() == 'break;':
            cur = []

    flat = set()
    for v in addrs.values():
        flat.update(v if isinstance(v, list) else [v])
    flat.discard(None)
    print('state-packet ids the DRM offset-checks : %d' % len(addrs))
    print('distinct registers it treats as addresses: %d' % len(flat))
    inside = sorted(flat & CLIENT)
    print()
    print('of those, the ones a client of OURS may write:')
    for a in inside:
        print('    0x%04x  %-18s %s' % (a, RANGE_CHECKED.get(a, '(unnamed here)'),
                                        'range-checked' if a in RANGE_CHECKED else '*** NOT CHECKED ***'))
    outside = sorted(flat - CLIENT)
    print('the other %d are outside our allow-list, so they are refused outright:' % len(outside))
    print('    ' + ' '.join('%04x' % a for a in outside))
    missing = [a for a in inside if a not in RANGE_CHECKED]
    extra = [a for a in RANGE_CHECKED if a not in flat]
    if extra:
        print('we range-check registers the DRM does not call addresses: %s' %
              ' '.join('%04x' % a for a in extra))
    ok = not missing
    print('design2: %s' % ('PASS -- the address registers a client can write are exactly the three '
                           'we check' if ok else 'FAIL: %s' % [hex(a) for a in missing]))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
