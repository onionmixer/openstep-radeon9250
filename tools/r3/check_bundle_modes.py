#!/usr/bin/env python3
"""The bundle's Display.modes and the tables' "Display Mode" against the oracle.

  check_bundle_modes.py            check the real files, then show each check can fail

docs/R3_MULTIMODE_PLAN.md 23-5 and 23-9 D1:
  * every Display.modes line is `"<mode string>";`, one of the oracle's twenty
    strings, and selects exactly the combination it names (no default taken);
  * the list is the set verified on the machine so far -- VERIFIED below, which
    grows only when a boot has passed (the gate: "a combination not confirmed
    is taken out of the advertisement");
  * Default.table and Instance0.table each hold exactly one "Display Mode",
    byte-equal to a Display.modes line (Configure writes one of those lines).
"""

import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
BUNDLE = os.path.join(PROJ, 'OSRDNDisplay')


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


oracle = _load('modesel_oracle_for_bundle', os.path.join(HERE, 'modesel_oracle.py'))

# WHAT IS ADVERTISED: all twenty combinations, as the Matrox replacement driver
# advertises its twenty (operator decision, 2026-09-18 -- it overrides the
# earlier "only what a boot has confirmed" reading in 23-9 D1).  The values of
# every row are the oracle's, cross-checked against NetBSD videomode.c and
# Matrox osmgaRes (18-1); what a boot has actually confirmed is listed in
# VERIFIED below, which this checker REPORTS but does not enforce.
VERIFIED = [
    'Height: 600 Width: 800 Refresh: 60Hz ColorSpace: RGB:888/32',     # dfc354ea, e7b39ac9, e723f16f
    'Height: 600 Width: 800 Refresh: 60Hz ColorSpace: RGB:555/16',     # e058cc98, e7bbcd53
    'Height: 600 Width: 800 Refresh: 60Hz ColorSpace: RGB:256/8',      # e12c5d03
    'Height: 600 Width: 800 Refresh: 60Hz ColorSpace: BW:8',           # e092c09b
    'Height: 480 Width: 640 Refresh: 60Hz ColorSpace: RGB:888/32',     # 015dab6c
    'Height: 768 Width: 1024 Refresh: 60Hz ColorSpace: RGB:888/32',    # 0fe38c5a, faca720d
]
LINE = re.compile(r'^"([^"]*)";$')
KEY = re.compile(r'^"Display Mode"\s*=\s*"([^"]*)";')


def check(modes_text, tables):
    """Problems, one string each.  tables: {name: text}."""
    p = []
    lines = modes_text.split('\n')
    if lines and lines[-1] == '':
        lines = lines[:-1]
    strings = []
    for n, l in enumerate(lines, 1):
        m = LINE.match(l)
        if not m:
            p.append('Display.modes line %d is not "<mode>";: %r' % (n, l))
            continue
        strings.append(m.group(1))
    allowed = oracle.display_modes_lines()
    for sline in strings:
        if sline not in allowed:
            p.append('Display.modes lists %r, which is not one of the oracle strings' % sline)
            continue
        idx = allowed.index(sline)
        got = oracle.choose(sline)
        want = (idx // len(oracle.FMT), idx % len(oracle.FMT))
        if (got['res'], got['fmt']) != want or got['resDefault'] or got['fmtDefault'] or got['pairDefault']:
            p.append('%r selects %s, not the combination it names' % (sline, got))
    if sorted(strings) != sorted(allowed) or len(set(strings)) != len(strings):
        p.append('Display.modes lists %d lines; the twenty combinations are advertised (24-21)'
                 % len(strings))
    for name, text in sorted(tables.items()):
        keys = [KEY.match(l) for l in text.split('\n')]
        keys = [k.group(1) for k in keys if k]
        if len(keys) != 1:
            p.append('%s holds %d "Display Mode" lines' % (name, len(keys)))
        elif keys[0] not in strings:
            p.append('%s says %r, which is not a Display.modes line' % (name, keys[0]))
    return p


def main():
    modes = open(os.path.join(BUNDLE, 'Display.modes')).read()
    tables = dict((t, open(os.path.join(BUNDLE, t)).read()) for t in ('Default.table', 'Instance0.table'))
    fails = 0
    base = check(modes, tables)
    for x in base:
        print('  FAIL %s' % x)
    unverified = [l for l in modes.split('\n') if l[1:-2] in oracle.display_modes_lines()
                  and l[1:-2] not in VERIFIED]
    print('  %-4s the bundle: %d modes advertised, %d confirmed by a boot, both tables name one of them'
          % ('FAIL' if base else 'ok', modes.count('\n'), modes.count('\n') - len(unverified)))
    for l in unverified:
        print('  --   not confirmed by a boot yet: %s' % l[1:-2])
    fails += len(base)

    d = tables['Default.table']
    key = KEY.search('\n'.join(l for l in d.split('\n') if l.startswith('"Display Mode"'))).group(0)
    negatives = [
        ('a line listed twice', modes + '"Height: 1200 Width: 1600 Refresh: 60Hz ColorSpace: RGB:888/32";\n', tables),
        ('a verified mode is missing', '\n'.join(modes.split('\n')[1:]), tables),
        ('a line is not quoted', modes.replace('"Height: 768', 'Height: 768', 1), tables),
        ('a mode string the oracle does not know', modes.replace('Width: 1024', 'Width:1024', 1), tables),
        ('the table names a mode that is not a line', modes,
         dict(tables, **{'Default.table': d.replace('Refresh: 60Hz ColorSpace: RGB:888/32";',
                                                    'Refresh: 70Hz ColorSpace: RGB:888/32";')})),
        ('the table names the mode twice', modes, dict(tables, **{'Default.table': d + key + '\n'})),
        ('the table has no mode', modes, dict(tables, **{'Default.table': d.replace(key, '')})),
    ]
    for label, m, t in negatives:
        caught = bool(check(m, t))
        print('  %-4s negative: %s' % ('ok' if caught else 'FAIL', label))
        fails += 0 if caught else 1
    print('check_bundle_modes: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
