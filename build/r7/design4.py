#!/usr/bin/env python3
"""R7 design 4: how the verifier knows a vertex's word count, and why PACKET0 must carry one register.

  python3 build/r7/design4.py

Two holes in the plan's first draft of the verifier rules, both found by asking what a hostile
stream could do that the rule as written would let through.

(a) PACKET0's count field.  A type-0 header is (count-1) << 16 | (reg >> 2), so one header can
    write reg, reg+4, reg+8 ...  A rule that checks only the FIRST register lets a client start
    inside the allow-list and walk straight out of it.  Every PACKET0 our harness has ever emitted
    writes exactly one register, so the rule can simply be "count == 1" -- checked here against
    every header in the driver, not assumed.

(b) The draw header's count.  3D_DRAW_IMMD_2 carries VF_CNTL then the vertices, and the words per
    vertex come from SE_VTX_FMT_0/1 -- which are themselves PACKET0 writes in the same stream.  So
    the verifier cannot be stateless: it has to TRACK those two registers as it walks.  The formula
    is derived here from Mesa's bit names and then checked against every case row the driver
    carries: if it reproduces all of their headers, it is the rule the hardware has been agreeing
    with all along.
"""
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
CP = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_cp.m')


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


zo = _load('zclear_oracle', os.path.join(PROJ, 'tools', 'r6', 'zclear_oracle.py'))


# SE_VTX_FMT_0 / _1 bit layout, read out of Mesa's r200_reg.h 376-410 (not from memory).
# Only the fields our harness has ever set are given a width here; everything else is REFUSED
# rather than guessed -- a normal (N0/N1) or a weight count we have never emitted has a word
# width this project has not measured, and a verifier that guesses it wrong either refuses a
# legal stream or, worse, lets a short one through and the CP reads past the vertices.
VTX0_KNOWN = {
    0: ('Z0', 1),                               # R200_VTX_Z0
    1: ('W0', 1),                               # R200_VTX_W0
}
VTX0_COLOR_SHIFT = 11                           # R200_VTX_COLOR_0_SHIFT; 2 bits per unit
VTX0_COLOR_WORDS = {0: 0, 1: 1}                 # NOT_PRESENT, PK_RGBA.  FP_RGB/FP_RGBA unmeasured
VTX0_ALLOWED_MASK = (1 << 0) | (1 << 1) | (3 << VTX0_COLOR_SHIFT)
VTX1_UNITS = 6                                  # TEX0..TEX5_COMP_CNT, 3 bits each


def vertex_words(fmt0, fmt1):
    """(words per vertex, or None if the format uses a field we have never measured)"""
    if fmt0 & ~VTX0_ALLOWED_MASK:
        return None                             # a bit outside what we have emitted
    n = 2                                       # R200_VTX_XY: "always have xy"
    for bit, (_name, w) in VTX0_KNOWN.items():
        n += w if (fmt0 >> bit) & 1 else 0
    c = (fmt0 >> VTX0_COLOR_SHIFT) & 3
    if c not in VTX0_COLOR_WORDS:
        return None                             # FP_RGB / FP_RGBA: unmeasured width
    n += VTX0_COLOR_WORDS[c]
    for unit in range(VTX1_UNITS):
        k = (fmt1 >> (3 * unit)) & 7
        if k not in (0, 2):
            return None                         # only two ST components have been measured
        n += k
    if fmt1 >> (3 * VTX1_UNITS):
        return None
    return n


def main():
    src = open(CP).read()
    bad = 0

    # ---- (a) every PACKET0 header the driver emits writes exactly one register
    heads = []
    i = src.index('static const unsigned long cpR6State[')
    for w in [int(x, 0) for x in re.findall(r'0x[0-9a-fA-F]+', src[i:src.index('};', i)])][0::2]:
        if (w >> 30) == 0:
            heads.append(w)
    multi = [w for w in heads if ((w >> 16) & 0x3fff) != 0]
    one_reg = [w for w in heads if (w >> 15) & 1]
    print('(a) PACKET0 headers in the driver state block : %d' % len(heads))
    print('    with a count field other than 1           : %d' % len(multi))
    print('    with the ONE_REG_WR bit set               : %d' % len(one_reg))
    if multi or one_reg:
        print('    -> the rule "count == 1, ONE_REG_WR clear" would refuse our own stream')
        bad += 1
    else:
        print('    -> the verifier may demand count == 1 and ONE_REG_WR clear: it always holds')

    # ---- (b) the vertex word count, against every case row's own header
    m = re.search(r'cpR6Cases\[CP_R6_CASES\] = \{(.*?)\n\};', src, re.S)
    rows = re.findall(r'\{([^{}]*)\}', m.group(1))
    checked = mism = 0
    for k, row in enumerate(rows):
        v = [int(x, 0) for x in re.findall(r'(0x[0-9a-fA-F]+|\d+)UL|\b(\d+)\b(?=,|\s*$)', row) for x in x if x]
        if len(v) < 20:
            continue
        fmt, hdr, vf = v[12], v[14], v[15]       # SE_VTX_FMT_0 word, the draw header, VF_CNTL
        if hdr == 0 or (hdr & 0xc000ffff) != 0xc0003500:
            continue                              # not a plain 3D_DRAW_IMMD_2 row
        cnt = (hdr >> 16) & 0x3fff
        nv = (vf >> 16) & 0xffff
        # the case rows carry SE_VTX_FMT_0 in the 'fmt' slot; FMT_1 is the texture row's business
        fmt1 = 0
        tidx = v[30] if len(v) > 30 else 0
        if tidx:
            fmt1 = 0x2                            # R6h: two ST words on unit 0 (VTX_FMT_1 = 2)
        want = vertex_words(fmt, fmt1)
        checked += 1
        if nv and cnt != want * nv:
            mism += 1
            if mism <= 5:
                print('    case %-4d fmt0=%#x fmt1=%#x -> %d words/vertex, header says %d for %d vertices'
                      % (k + 1, fmt, fmt1, want, cnt, nv))
    print()
    print('(b) case rows with a plain 3D_DRAW_IMMD_2 header : %d' % checked)
    print('    the derived word count reproduces the header : %d' % (checked - mism))
    if mism:
        print('    MISMATCHES: %d' % mism)
        bad += 1
    print()
    print('what this means for the verifier:')
    print('  - PACKET0: count == 1 and ONE_REG_WR clear, then one register to look up (rule 2)')
    print('  - the verifier TRACKS SE_VTX_FMT_0/1 while it walks, and checks')
    print('      draw header count == vertex_words(fmt0, fmt1) * (VF_CNTL >> 16)   (rule 3)')
    print('  - a stream that draws before setting them is refused: the driver prefix sets a known')
    print('    pair, so "unset" never means "whatever the last client left"')
    print('design4: %s' % ('PASS' if not bad else 'FAIL (%d)' % bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
