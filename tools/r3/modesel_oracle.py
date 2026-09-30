#!/usr/bin/env python3
"""Which resolution and format a "Display Mode" string selects -- the host oracle.

Written separately from OSRDNDisplay_reloc.tproj/osrdn_modesel.m, in a
different style (one regular expression, not a hand scanner), from the rule as
the Matrox replacement driver states it (docs/R3_MULTIMODE_PLAN.md 23-2, 23-9
E4):

  resolution  "Height:" n "Width:" n "Refresh:" n "Hz" ["ColorSpace:" x], spaces
              and tabs allowed between parts (not inside "60Hz"), keys
              case-sensitive, height and width 1..65535, refresh 1..4294967,
              refresh not compared; matched on width and height
  format      first format token in table order found anywhere in the string
  pair        replaced whole by the default when it does not fit the mapping
              or the width is not a multiple of 8

The tables come from tools/oracle/radeon_modeset.py, not from the generated
header, so a wrong header cannot make the two sides agree.
"""

import importlib.util
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


rm = _load('radeon_modeset_for_modesel', os.path.join(PROJ, 'tools', 'oracle', 'radeon_modeset.py'))

RES = [(m['hdisp'], m['vdisp']) for m in rm.MODES]
FMT = [(f['token'], f['bytes']) for f in rm.FORMATS]
RES_DEFAULT = [m['name'] for m in rm.MODES].index('800x600@60')
FMT_DEFAULT = 0
MAPPED = 0x800000

_B = '[ \t]*'
_N = '([0-9]+)'
GRAMMAR = re.compile('^' + _B + 'Height:' + _B + _N + _B + 'Width:' + _B + _N + _B +
                     'Refresh:' + _B + _N + 'Hz' + _B + '(?:ColorSpace:' + _B + '(.+))?\\Z', re.S)   # \\Z: `$` would also
                                                                     # match before a final newline


def parse_size(text):
    """(width, height) or None."""
    m = GRAMMAR.match(text)
    if not m:
        return None
    h, w, r = (int(x) for x in m.group(1, 2, 3))
    for v, top in ((h, 65535), (w, 65535), (r, 4294967)):
        if not 1 <= v <= top:
            return None
    if m.group(4) is not None and m.group(4).strip(' \t') == '':
        return None
    return w, h


def choose(text, mapped=MAPPED):
    """{res, fmt, resDefault, fmtDefault, pairDefault} for the string (None = key absent)."""
    res, fmt, rd, fd, pd = RES_DEFAULT, FMT_DEFAULT, 1, 1, 0
    if text is not None:
        size = parse_size(text)
        if size in RES:
            res, rd = RES.index(size), 0
        hits = [i for i, (tok, _) in enumerate(FMT) if tok in text]
        if hits:
            fmt, fd = hits[0], 0
    w, h = RES[res]
    if w % 8 or w * FMT[fmt][1] * h > mapped:
        res, fmt, pd = RES_DEFAULT, FMT_DEFAULT, 1
    return dict(res=res, fmt=fmt, resDefault=rd, fmtDefault=fd, pairDefault=pd)


def display_modes_lines():
    """The 20 advertisable strings, in the spaced form NeXT's own S3 driver uses."""
    out = []
    for m in rm.MODES:
        for f in rm.FORMATS:
            out.append('Height: %d Width: %d Refresh: 60Hz ColorSpace: %s' % (m['vdisp'], m['hdisp'], f['token']))
    return out


HSYNC_MIN, HSYNC_MAX, HSYNC_DEFAULT = -16, 48, 7


def hsync(text):
    """(pixels, refused) for "RDN HSync Adjust" (docs/REL3_DISPLAY_FIX_PLAN.md 3-2 4):
    an optional sign and one to three digits, nothing else, in -16..48."""
    import re
    if text is None:
        return HSYNC_DEFAULT, 0
    if not re.fullmatch(r'[+-]?[0-9]{1,3}', text):
        return HSYNC_DEFAULT, 1
    v = int(text)
    if not HSYNC_MIN <= v <= HSYNC_MAX:
        return HSYNC_DEFAULT, 1
    return v, 0


def gray(text):
    """(levels, refused) for a "Gray Levels" string: exact 256/16/4/2 only."""
    if text is None:
        return 0, 0
    table = {'256': 0, '16': 16, '4': 4, '2': 2}
    if text in table:
        return table[text], 0
    return 0, 1
