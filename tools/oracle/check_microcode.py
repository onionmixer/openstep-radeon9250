#!/usr/bin/env python3
"""Confirm the two copies of the R200 CP microcode are the same data.

  header  FreeBSD sys/dev/drm/radeon_microcode.h  R200_cp_microcode[256][2]
  binary  linux-firmware radeon/R200_cp.bin        (2048 bytes)

FreeBSD loads it as DATAH = cp[i][1], DATAL = cp[i][0] (radeon_cp.c:528-531).
The binary is expected to be that write order as big-endian 32-bit words.
Exit 0 only if the binary equals the header in that order AND does not equal
it in the swapped order (so a checker that compares nothing cannot pass).
"""

import hashlib
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
UP = os.path.join(HERE, '..', '..', 'ref', 'upstream')
HEADER = os.path.join(UP, 'freebsd-stable9/sys/dev/drm/radeon_microcode.h')
BINARY = os.path.join(UP, 'linux-firmware/radeon/R200_cp.bin')
BIN_SHA256 = '2b7b4bf988c3f7c69f98ea2ec6c4155fa85e2c9d5f5aee77912baaf50f5f7bac'


def header_pairs():
    text = open(HEADER).read()
    start = text.index('R200_cp_microcode[][2]')
    body = text[text.index('{', start) + 1:]
    body = body[:body.index('};')]
    pairs = re.findall(r'\{\s*(0x[0-9a-fA-F]+|0+)\s*,\s*(0x[0-9a-fA-F]+|0+)\s*\}', body)
    return [(int(a, 16) if a.startswith('0x') else 0,
             int(b, 16) if b.startswith('0x') else 0) for a, b in pairs]


def main():
    pairs = header_pairs()
    data = open(BINARY, 'rb').read()
    digest = hashlib.sha256(data).hexdigest()
    words = list(struct.unpack('>%dI' % (len(data) // 4), data))
    load_order = [w for lo_hi in pairs for w in (lo_hi[1], lo_hi[0])]
    swapped = [w for lo_hi in pairs for w in lo_hi]
    ok = (len(pairs) == 256 and len(data) == 2048 and digest == BIN_SHA256
          and words == load_order and words != swapped)
    print('pairs=%d bytes=%d sha256=%s' % (len(pairs), len(data), digest))
    print('binary == (DATAH, DATAL) load order: %s' % (words == load_order))
    print('binary == swapped order (must be False): %s' % (words == swapped))
    print('microcode copies:', 'IDENTICAL' if ok else 'MISMATCH')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
