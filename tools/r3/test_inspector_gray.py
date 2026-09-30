#!/usr/bin/env python3
"""H1 and H2 of docs/R3_MULTIMODE_PLAN.md 26-3: the inspector's "Gray Levels"
table against the driver's rule, and what the inspector is allowed to touch.

  test_inspector_gray.py        check the real sources, then show each check can fail

H1 compiles OSRDNDisplay/osrdn_graypanel.h itself -- the bytes the bundle
compiles -- as 32-bit C on the host and asks it, then holds the answers to
  (a) a hand-written table: tag 0..3 = "256" "16" "4" "2", the driver reading
      them as 0 16 4 2 (0 means 256 greys);
  (b) for every tag t: the driver's rule (tools/r3/modesel_oracle.py gray(),
      itself held to osrdn_modesel_gray() by test_modesel.py) reads
      values[t] as (L_t, not refused), and tagFor(values[t]) == t;
  (c) for every stored value s, absent included: the cell the panel shows
      stores a value the driver reads as the same number of greys as s.
      `refused' is NOT carried -- a value the driver refuses is shown, and
      saved, as 256, which is the number the driver uses for it;
  (d) a tag no cell has stores "256".
(a) is what catches a table reordered consistently in both directions, which
(b) and (c) cannot see.

H2 reads OSRDNDisplayInspector.m: every valueForStringKey:/insertKey: names
OSRDN_PANEL_GRAY_KEY or (REL3, docs/REL3_DISPLAY_FIX_PLAN.md 3-4)
OSRDN_PANEL_HSYNC_KEY, each read and stored; each key is the driver's own
string (tools/rel3/test_inspector_hsync.py holds the hsync values); the inspector never
names "Display Mode" (the driver's grey rule takes only the Gray Levels
string) and never calls freeString: (Configure's NXStringTable owns its values).
"""

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
BUNDLE = os.path.join(PROJ, 'OSRDNDisplay')
HEADER = os.path.join(BUNDLE, 'osrdn_graypanel.h')
INSPECTOR = os.path.join(BUNDLE, 'OSRDNDisplayInspector.m')
DRIVER_M = os.path.join(BUNDLE, 'OSRDNDisplay_reloc.tproj', 'OSRDNDisplay.m')


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


oracle = _load('modesel_oracle_for_inspector', os.path.join(HERE, 'modesel_oracle.py'))
tm = _load('test_modesel_for_inspector', os.path.join(HERE, 'test_modesel.py'))

EXPECT = [(0, '256', 0), (1, '16', 16), (2, '4', 4), (3, '2', 2)]
INPUTS = list(dict.fromkeys(tm.GRAY_CASES + ['BW:8', 'Gray', '256\t', '0256', '16 ', 'Yes']))
TAGS = list(range(-3, 8))

HARNESS = r'''
int printf(const char *, ...);
void exit(int);
#include "osrdn_graypanel.h"
static const char *const inputs[] = { %(inputs)s };
static const int tags[] = { %(tags)s };
int main(void)
{
    unsigned k;
    printf("N %%d\n", OSRDN_GRAY_COUNT);
    for (k = 0; k < (unsigned)OSRDN_GRAY_COUNT; k++)
        printf("V %%u %%s\n", k, osrdnGrayValues[k]);
    for (k = 0; k < sizeof inputs / sizeof inputs[0]; k++)
        printf("T %%u %%d\n", k, osrdnGrayTagFor(inputs[k]));
    for (k = 0; k < sizeof tags / sizeof tags[0]; k++)
        printf("S %%d %%s\n", tags[k], osrdnGrayValueForTag(tags[k]));
    printf("K %%s\n", OSRDN_PANEL_GRAY_KEY);
    return 0;
}
__attribute__((force_align_arg_pointer))
void _start(void) { exit(main()); }
'''


def ask(header_dir, work):
    """The header's answers, or an error string."""
    src = os.path.join(work, 'h1.c')
    open(src, 'w').write(HARNESS % dict(
        inputs=', '.join('0' if t is None else tm.c_escape(t) for t in INPUTS),
        tags=', '.join(str(t) for t in TAGS)))
    exe = os.path.join(work, 'h1')
    # strict C89 with -Wall: the header must be clean where cc 2.7.2.1 will see it
    r = subprocess.run(['gcc-12', '-m32', '-std=c89', '-pedantic-errors', '-O0', '-Wall', '-Werror',
                        '-Wno-main', '-I', header_dir, src, '-nostdlib', '-nostartfiles', tm.LIBC32,
                        '-Wl,-dynamic-linker,' + tm.LD32, '-o', exe], capture_output=True, text=True)
    if r.returncode != 0:
        return 'does not build: ' + r.stderr[-300:]
    r = subprocess.run([exe], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return 'exited %d' % r.returncode
    out = {'V': {}, 'T': {}, 'S': {}}
    for line in r.stdout.splitlines():
        kind, rest = line.split(' ', 1)
        if kind == 'N':
            out['N'] = int(rest)
        elif kind == 'K':
            out['K'] = rest
        else:
            a, b = (rest.split(' ', 1) + [''])[:2]
            out[kind][int(a)] = b
    return out


def h1(header_dir, work):
    got = ask(header_dir, work)
    if isinstance(got, str):
        return [got]
    bad = []
    values = [got['V'].get(t) for t in range(got.get('N', 0))]
    # (a)
    if [(t, v, oracle.gray(v)[0]) for t, v in enumerate(values)] != EXPECT:
        bad.append('(a) table %r, want %r' % (values, [v for _, v, _ in EXPECT]))
    # (b)
    for t, v in enumerate(values):
        if oracle.gray(v) != (EXPECT[t][2] if t < len(EXPECT) else None, 0):
            bad.append('(b) tag %d stores %r, the driver reads %s' % (t, v, oracle.gray(v)))
    tag_of = dict((INPUTS[k], int(x)) for k, x in got['T'].items())
    for t, v in enumerate(values):
        if tag_of.get(v) != t:
            bad.append('(b) %r selects tag %s, not its own %d' % (v, tag_of.get(v), t))
    # (c)
    for s in INPUTS:
        t = tag_of.get(s)
        if t is None or not 0 <= t < len(values):
            bad.append('(c) %r selects tag %s, which no cell has' % (s, t))
            continue
        if oracle.gray(values[t])[0] != oracle.gray(s)[0]:
            bad.append('(c) %r (driver: %d greys-code) shows cell %d = %r (driver: %d)'
                       % (s, oracle.gray(s)[0], t, values[t], oracle.gray(values[t])[0]))
    # (d)
    for t in TAGS:
        want = values[t] if 0 <= t < len(values) else '256'
        if got['S'].get(t) != want:
            bad.append('(d) tag %d stores %r, want %r' % (t, got['S'].get(t), want))
    if len(got['T']) != len(INPUTS) or len(got['S']) != len(TAGS):
        bad.append('the harness answered %d/%d of %d/%d questions'
                   % (len(got['T']), len(got['S']), len(INPUTS), len(TAGS)))
    if got.get('K') != 'Gray Levels':
        bad.append('the panel key is %r' % got.get('K'))
    return bad


def driver_key():
    m = re.search(r'^#define\s+OSRDN_GRAY_KEY\s+"([^"]*)"', open(DRIVER_M).read(), re.M)
    return m.group(1) if m else None


PANEL_KEYS = ('OSRDN_PANEL_GRAY_KEY', 'OSRDN_PANEL_HSYNC_KEY')


def driver_hsync_key():
    m = re.search(r'^#define\s+OSRDN_HSYNC_KEY\s+"([^"]*)"', open(DRIVER_M).read(), re.M)
    return m.group(1) if m else None


def panel_hsync_key():
    m = re.search(r'^#define\s+OSRDN_PANEL_HSYNC_KEY\s+"([^"]*)"',
                  open(os.path.join(BUNDLE, 'osrdn_hsyncpanel.h')).read(), re.M)
    return m.group(1) if m else None


def h2(text):
    bad = []
    body = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    for sel in ('valueForStringKey:', 'insertKey:'):
        for m in re.finditer(re.escape(sel) + r'\s*([^\]\s]+)', body):
            if m.group(1) not in PANEL_KEYS:
                bad.append('%s names %s' % (sel, m.group(1)))
    for key in PANEL_KEYS:
        if not re.search(r'valueForStringKey:\s*' + key, body):
            bad.append('the panel never reads ' + key)
        if not re.search(r'insertKey:\s*' + key, body):
            bad.append('the panel never stores ' + key)
    if driver_hsync_key() is None or driver_hsync_key() != panel_hsync_key():
        bad.append('the hsync key is %r in the driver, %r in the panel' % (driver_hsync_key(), panel_hsync_key()))
    if '"Display Mode"' in body:
        bad.append('the inspector names "Display Mode"')
    if 'freeString:' in body:
        bad.append('the inspector calls freeString:')
    if driver_key() != 'Gray Levels':
        bad.append('the driver key is %r' % driver_key())
    return bad


def main():
    fails = 0
    work = tempfile.mkdtemp(prefix='test_inspector_gray.')
    try:
        base1 = h1(BUNDLE, work)
        base2 = h2(open(INSPECTOR).read())
        for x in base1 + base2:
            print('  FAIL %s' % x)
        print('  %-4s H1 the panel table against the driver rule (%d stored values, %d tags)'
              % ('FAIL' if base1 else 'ok', len(INPUTS), len(TAGS)))
        print('  %-4s H2 the inspector touches Gray Levels and RDN HSync Adjust only'
              % ('FAIL' if base2 else 'ok'))
        fails += len(base1) + len(base2)

        header = open(HEADER).read()
        m1 = [
            ('the table reversed', header.replace('{ "256", "16", "4", "2" }', '{ "2", "4", "16", "256" }')),
            ('"4" became "8"', header.replace('"4", "2" }', '"8", "2" }')),
            ('an unknown value selects tag 1', header.replace(
                '            return tag;\n    return 0;', '            return tag;\n    return 1;')),
            ('the tag clamp removed', header.replace('if (tag < 0 || tag >= OSRDN_GRAY_COUNT)',
                                                     'if (tag < 0 && tag >= OSRDN_GRAY_COUNT)')),
            ('the key misspelt', header.replace('"Gray Levels"', '"Grey Levels"')),
        ]
        mdir = os.path.join(work, 'mut')
        os.makedirs(mdir)
        for label, text in m1:
            if text == header:
                print('  FAIL negative: %s (the mutation did not apply)' % label)
                fails += 1
                continue
            open(os.path.join(mdir, 'osrdn_graypanel.h'), 'w').write(text)
            caught = bool(h1(mdir, work))
            print('  %-4s negative: %s' % ('ok' if caught else 'FAIL', label))
            fails += 0 if caught else 1

        insp = open(INSPECTOR).read()
        m2 = [
            ('reads "Display Mode"', insp.replace('[super setTable:instance];',
                                                  '[super setTable:instance];\n    [table valueForStringKey:"Display Mode"];')),
            ('stores another key', insp.replace('[table insertKey:OSRDN_PANEL_GRAY_KEY',
                                                '[table insertKey:"Display Mode"')),
            ('REL3: the slider stores under the Gray Levels key',
             insp.replace('[table insertKey:OSRDN_PANEL_HSYNC_KEY', '[table insertKey:OSRDN_PANEL_GRAY_KEY')),
            ('REL3: the panel does not read the hsync key back',
             insp.replace('[table valueForStringKey:OSRDN_PANEL_HSYNC_KEY]', '0')),
            ('frees a table value', insp.replace('return self;\n}\n\n- grayChanged',
                                                 '[table freeString:0];\n    return self;\n}\n\n- grayChanged')),
        ]
        for label, text in m2:
            if text == insp:
                print('  FAIL negative: %s (the mutation did not apply)' % label)
                fails += 1
                continue
            caught = bool(h2(text))
            print('  %-4s negative: %s' % ('ok' if caught else 'FAIL', label))
            fails += 0 if caught else 1
    finally:
        shutil.rmtree(work)
    print('test_inspector_gray: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
