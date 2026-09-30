#!/usr/bin/env python3
"""REL3 (docs/REL3_DISPLAY_FIX_PLAN.md 3-4): the inspector's "RDN HSync Adjust"
header against the driver's rule.

  test_inspector_hsync.py        check the real header, then show each check can fail

Compiles OSRDNDisplay/osrdn_hsyncpanel.h itself -- the bytes the bundle
compiles -- as strict 32-bit C89 on the host, and holds its answers to the
driver's rule (tools/r3/modesel_oracle.py hsync(), itself held to
osrdn_modesel_hsync() by tools/r3/test_modesel.py):
  (a) for every stored string s, absent included: the panel shows the
      number the driver will use for s -- its own when the driver takes it,
      the default when the driver refuses it;
  (b) for every slider value v in a range wider than the panel's: the string
      the panel stores for v is one the driver takes (not refused), and the
      driver reads it as v clamped into the panel's range;
  (c) the panel's range and default are the driver's, and its key is the
      driver's key.
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
HEADER = os.path.join(BUNDLE, 'osrdn_hsyncpanel.h')
DRIVER_M = os.path.join(BUNDLE, 'OSRDNDisplay_reloc.tproj', 'OSRDNDisplay.m')
R3 = os.path.join(PROJ, 'tools', 'r3')


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


oracle = _load('modesel_oracle_for_hsync', os.path.join(R3, 'modesel_oracle.py'))
tm = _load('test_modesel_for_hsync', os.path.join(R3, 'test_modesel.py'))

INPUTS = list(dict.fromkeys(tm.HSYNC_CASES + ['-1', '1', '47', '-15', '100', '+48', '-48']))
VALUES = list(range(-40, 81))

HARNESS = r'''
int printf(const char *, ...);
void exit(int);
#include "osrdn_hsyncpanel.h"
static const char *const inputs[] = { %(inputs)s };
int main(void)
{
    unsigned k;
    int v;
    char buf[4];
    for (k = 0; k < sizeof inputs / sizeof inputs[0]; k++)
        printf("F %%u %%d\n", k, osrdnHsyncFor(inputs[k]));
    for (v = %(lo)d; v <= %(hi)d; v++)
        printf("T %%d %%s\n", v, osrdnHsyncText(v, buf));
    printf("R %%d %%d %%d\n", OSRDN_PANEL_HSYNC_MIN, OSRDN_PANEL_HSYNC_MAX, OSRDN_PANEL_HSYNC_DEFAULT);
    printf("K %%s\n", OSRDN_PANEL_HSYNC_KEY);
    return 0;
}
__attribute__((force_align_arg_pointer))
void _start(void) { exit(main()); }
'''


def ask(header_dir, work):
    """The header's answers, or an error string."""
    src = os.path.join(work, 'hs.c')
    open(src, 'w').write(HARNESS % dict(
        inputs=', '.join('0' if t is None else tm.c_escape(t) for t in INPUTS),
        lo=VALUES[0], hi=VALUES[-1]))
    exe = os.path.join(work, 'hs')
    r = subprocess.run(['gcc-12', '-m32', '-std=c89', '-pedantic-errors', '-O0', '-Wall', '-Werror',
                        '-Wno-main', '-I', header_dir, src, '-nostdlib', '-nostartfiles', tm.LIBC32,
                        '-Wl,-dynamic-linker,' + tm.LD32, '-o', exe], capture_output=True, text=True)
    if r.returncode != 0:
        return 'does not build: ' + r.stderr[-300:]
    r = subprocess.run([exe], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return 'exited %d' % r.returncode
    out = {'F': {}, 'T': {}}
    for line in r.stdout.splitlines():
        kind, rest = line.split(' ', 1)
        if kind == 'R':
            out['R'] = tuple(int(x) for x in rest.split())
        elif kind == 'K':
            out['K'] = rest
        else:
            a, b = rest.split(' ', 1)
            out[kind][int(a)] = b
    return out


def driver_key():
    m = re.search(r'^#define\s+OSRDN_HSYNC_KEY\s+"([^"]*)"', open(DRIVER_M).read(), re.M)
    return m.group(1) if m else None


def check(header_dir, work):
    got = ask(header_dir, work)
    if isinstance(got, str):
        return [got]
    bad = []
    # (c)
    want_r = (oracle.HSYNC_MIN, oracle.HSYNC_MAX, oracle.HSYNC_DEFAULT)
    if got.get('R') != want_r:
        bad.append('(c) panel range/default %s, driver %s' % (got.get('R'), want_r))
    if got.get('K') != driver_key():
        bad.append('(c) panel key %r, driver key %r' % (got.get('K'), driver_key()))
    # (a)
    for k, s in enumerate(INPUTS):
        shown = int(got['F'].get(k, 'nan')) if k in got['F'] else None
        if shown != oracle.hsync(s)[0]:
            bad.append('(a) %r shows %s, the driver uses %s' % (s, shown, oracle.hsync(s)[0]))
    # (b)
    for v in VALUES:
        text = got['T'].get(v)
        want = min(max(v, oracle.HSYNC_MIN), oracle.HSYNC_MAX)
        if oracle.hsync(text) != (want, 0):
            bad.append('(b) slider %d stores %r, the driver reads %s, want (%d, 0)'
                       % (v, text, oracle.hsync(text), want))
    if len(got['F']) != len(INPUTS) or len(got['T']) != len(VALUES):
        bad.append('the harness answered %d/%d of %d/%d questions'
                   % (len(got['F']), len(got['T']), len(INPUTS), len(VALUES)))
    return bad


def main():
    fails = 0
    work = tempfile.mkdtemp(prefix='test_inspector_hsync.', dir=os.environ.get('TMPDIR'))
    try:
        base = check(BUNDLE, work)
        for x in base[:8]:
            print('  FAIL %s' % x)
        print('  %-4s the panel against the driver rule (%d stored values, %d slider values)'
              % ('FAIL' if base else 'ok', len(INPUTS), len(VALUES)))
        fails += 1 if base else 0

        header = open(HEADER).read()
        muts = [
            ('the minus sign dropped when shown', header.replace('            sign = -1;', '            sign = 1;')),
            ('a refused value shown as written', header.replace(
                '        v < OSRDN_PANEL_HSYNC_MIN || v > OSRDN_PANEL_HSYNC_MAX)\n        return OSRDN_PANEL_HSYNC_DEFAULT;',
                '        v < OSRDN_PANEL_HSYNC_MIN || v > OSRDN_PANEL_HSYNC_MAX)\n        return v;')),
            ('the clamp removed', header.replace('    v = osrdnHsyncClamp(v);\n', '')),
            ('two-digit values lose their tens', header.replace(
                "        buf[n++] = (char)('0' + a / 10);", "        ;")),
            ('the panel default differs', header.replace('#define OSRDN_PANEL_HSYNC_DEFAULT   7',
                                                         '#define OSRDN_PANEL_HSYNC_DEFAULT   5')),
            ('the panel range is wider', header.replace('#define OSRDN_PANEL_HSYNC_MAX       48',
                                                        '#define OSRDN_PANEL_HSYNC_MAX       64')),
            ('the key misspelt', header.replace('"RDN HSync Adjust"', '"RDN Hsync Adjust"')),
        ]
        mdir = os.path.join(work, 'mut')
        os.makedirs(mdir)
        for label, text in muts:
            if text == header:
                print('  FAIL negative: %s (the mutation did not apply)' % label)
                fails += 1
                continue
            open(os.path.join(mdir, 'osrdn_hsyncpanel.h'), 'w').write(text)
            caught = bool(check(mdir, work))
            print('  %-4s negative: %s' % ('ok' if caught else 'FAIL', label))
            fails += 0 if caught else 1
    finally:
        shutil.rmtree(work, True)
    print('test_inspector_hsync: %s' % ('FAIL (%d)' % fails if fails else 'PASS'))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
