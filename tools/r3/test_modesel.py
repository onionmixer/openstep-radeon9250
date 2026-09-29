#!/usr/bin/env python3
"""Compile osrdn_modesel.m on the host and hold it to the oracle, with teeth.

  test_modesel.py

docs/R3_MULTIMODE_PLAN.md 23-2, 23-9 E4 and 12-4 proposal 2.  Three layers:

  1. hand-written expectations check the ORACLE (tools/r3/modesel_oracle.py)
     against the rule as a person wrote it, so the oracle cannot drift;
  2. the driver's unit, compiled as it is, must give the oracle's answer for
     every input: the 20 advertisable strings in the spaced form, the same 20
     without spaces (Matrox's Display.modes form), blank and tab variants, and
     broken inputs;
  3. each mutation of the unit (a plausible defect) must make layer 2 fail,
     in this same run.

The unit is compiled and RUN as 32-bit code, as the target runs it: unsigned
long is 32 bits there, and a number that wraps is a 32-bit question.  The
host has the 32-bit libc but no 32-bit start files, so the driver program
brings its own _start, as tools/r2b/sim does.
"""

import importlib.util
import shutil
import atexit
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
TPROJ = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj')
UNIT = os.path.join(TPROJ, 'osrdn_modesel.m')
LIBC32 = '/usr/lib32/libc.so.6'
LD32 = '/lib/ld-linux.so.2'


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


oracle = _load('modesel_oracle_for_test', os.path.join(HERE, 'modesel_oracle.py'))

# 1. what a person expects, index by index (res: 0 640, 1 800, 2 1024, 3 1280,
#    4 1600; fmt: 0 888/32, 1 555/16, 2 256/8, 3 BW:8)
HAND = [
    ('Height: 600 Width: 800 Refresh: 60Hz ColorSpace: RGB:888/32', (1, 0, 0, 0, 0)),
    ('Height: 768 Width: 1024 Refresh: 60Hz ColorSpace: RGB:888/32', (2, 0, 0, 0, 0)),
    ('Height: 600 Width: 800 Refresh: 60Hz ColorSpace: RGB:555/16', (1, 1, 0, 0, 0)),
    ('Height:1200 Width:1600 Refresh:60Hz ColorSpace:BW:8', (4, 3, 0, 0, 0)),
    ('Height: 480 Width: 640 Refresh: 75Hz ColorSpace: RGB:256/8', (0, 2, 0, 0, 0)),   # refresh not compared
    (None, (1, 0, 1, 1, 0)),
    ('', (1, 0, 1, 1, 0)),
    ('Width: 800 Height: 600 Refresh: 60Hz ColorSpace: RGB:555/16', (1, 1, 1, 0, 0)),  # order fixed; format still taken
    ('Height: 768 Width: 1024 Refresh: 60 Hz ColorSpace: RGB:555/16', (1, 1, 1, 0, 0)),  # "60 Hz"
    ('Height: 768 Width: 1024 Refresh: 0Hz ColorSpace: RGB:555/16', (1, 1, 1, 0, 0)),
    ('Height: 0 Width: 1024 Refresh: 60Hz', (1, 0, 1, 1, 0)),
    ('Height: 768 Width: 1024 Refresh: 60Hz', (2, 0, 0, 1, 0)),
    ('Height: 768 Width: 1024 Refresh: 60Hz junk', (1, 0, 1, 1, 0)),
    ('Height: 768 Width: 1024 Refresh: 60Hz ColorSpace:', (1, 0, 1, 1, 0)),
    ('Height: 768 Width: 1024 Refresh: 60Hz ColorSpace: RGB:888/32x', (2, 0, 0, 0, 0)),
    ('Height: 768 Width: 1024 Refresh: 60Hz ColorSpace: BW:8 RGB:555/16', (2, 1, 0, 0, 0)),  # table order wins
    ('height: 768 width: 1024 refresh: 60Hz ColorSpace: RGB:555/16', (1, 1, 1, 0, 0)),
    ('Height: 1050 Width: 1400 Refresh: 60Hz ColorSpace: RGB:555/16', (1, 1, 1, 0, 0)),
    ('Height: 768 Width: 1024 Refresh: 60Hz ColorSpace: RGB:444/12', (2, 0, 0, 1, 0)),
]


def cases():
    """Every input of layer 2 (None stands for an absent key)."""
    lines = oracle.display_modes_lines()
    out = list(lines)
    out += [l.replace(': ', ':') for l in lines]
    out += [l.replace(' ', '\t') for l in lines[:6]]
    out += ['   ' + l + '   ' for l in lines[:6]]
    out += [t for t, _ in HAND]
    out += ['Height: 99999999999 Width: 1024 Refresh: 60Hz', 'Height: 65536 Width: 1024 Refresh: 60Hz',
            'Height: 768 Width: 1024 Refresh: 4294968Hz', 'Height: 768 Width: 1024 Refresh: 4294967Hz',
            'Height: 768 Width: 1024 Refresh: 60Hz\n', 'Height: 768 Width: 1024 Refresh: 60Hz ColorSpace: \t',
            'Height: 768\tWidth: 1024 Refresh: 60Hz ColorSpace: BW:8', 'Height: -768 Width: 1024 Refresh: 60Hz',
            'Height: 768 Width: 1024 Refresh: 60hz', 'RGB:256/8', 'BW:8', 'Height: 768 Width: 1024',
            'Height: 768 Width: 1024 Refresh: 60Hz ColorSpace:RGB:256/8 trailing words',
            # 2**32 + 768: wraps to 768 in 32 bits unless the overflow is caught
            'Height: 4294968064 Width: 1024 Refresh: 60Hz ColorSpace: RGB:555/16']
    return out


def c_escape(t):
    return '"' + ''.join('\\%03o' % b if b < 32 or b > 126 or b in (34, 92) else chr(b)
                         for b in t.encode()) + '"'


GRAY_CASES = [None, '256', '16', '4', '2', '8', '0', '', '256 ', ' 16', '1', '2x', '-4', '64']
GRAY_HAND = {None: (0, 0), '256': (0, 0), '16': (16, 0), '4': (4, 0), '2': (2, 0), '8': (0, 1),
             '256 ': (0, 1), '': (0, 1)}

DRIVER = r'''
int printf(const char *, ...);
void exit(int);
void osrdn_modesel_choose(const char *, unsigned long, void *);
int osrdn_modesel_gray(const char *, int *);
static const char *const grays[] = { %(grays)s };
typedef struct { int res, fmt, resDefault, fmtDefault, pairDefault; } sel_t;
static const char *const inputs[] = { %(inputs)s };
static const unsigned long mapped[] = { %(mapped)s };
int main(void)
{
    unsigned k;
    sel_t s;
    for (k = 0; k < sizeof inputs / sizeof inputs[0]; k++) {
        osrdn_modesel_choose(inputs[k], mapped[k], &s);
        printf("%%d %%d %%d %%d %%d\n", s.res, s.fmt, s.resDefault, s.fmtDefault, s.pairDefault);
    }
    for (k = 0; k < sizeof grays / sizeof grays[0]; k++) {
        int refused = 7, n = osrdn_modesel_gray(grays[k], &refused);
        printf("G %%d %%d\n", n, refused);
    }
    return 0;
}
__attribute__((force_align_arg_pointer))
void _start(void) { exit(main()); }
'''


def run_unit(unit_path, inputs, work):
    """[(res, fmt, rd, fd, pd)] from the compiled unit, or an error string."""
    drv = os.path.join(work, 'drv.c')
    open(drv, 'w').write(DRIVER % dict(
        inputs=', '.join('0' if t is None else c_escape(t) for t, _ in inputs),
        mapped=', '.join('%#xUL' % m for _, m in inputs),
        grays=', '.join('0' if t is None else c_escape(t) for t in GRAY_CASES)))
    exe = os.path.join(work, 'drv')
    cmd = ['gcc-12', '-m32', '-std=gnu89', '-O0', '-Wall', '-Wno-deprecated', '-Wno-main', '-I', TPROJ,
           '-x', 'c', unit_path, drv, '-x', 'none', '-nostdlib', '-nostartfiles', LIBC32,
           '-Wl,-dynamic-linker,' + LD32, '-o', exe]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return 'does not build: ' + r.stderr[-300:]
    r = subprocess.run([exe], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return 'exited %d' % r.returncode
    return [tuple(int(x) for x in l.split()) if not l.startswith('G ') else ('G',) + tuple(int(x) for x in l.split()[1:])
            for l in r.stdout.splitlines()]


def layer2(unit_path, work):
    inputs = [(t, oracle.MAPPED) for t in cases()]
    # the pair check: at a 3 MiB mapping 1280x1024x4 does not fit, 800x600x4 does
    small = 0x300000
    lines = oracle.display_modes_lines()            # index = resolution * 4 + format
    inputs += [(lines[3 * 4 + 0], small),               # 1280x1024 x4 = 5 242 880: replaced whole
               (lines[1 * 4 + 0], small),               # 800x600 x4 = 1 920 000: kept
               (lines[4 * 4 + 2], small),               # 1600x1200 x1 = 1 920 000: kept
               (lines[4 * 4 + 1], small)]               # 1600x1200 x2 = 3 840 000: replaced whole,
                                                        # format included
    got = run_unit(unit_path, inputs, work)
    if isinstance(got, str):
        return [got]
    bad = []
    grays = [g for g in got if g[0] == 'G']
    got = [g for g in got if g[0] != 'G']
    for t, g in zip(GRAY_CASES, grays):
        if g[1:] != oracle.gray(t):
            bad.append('Gray Levels %r: unit %s, oracle %s' % (t, g[1:], oracle.gray(t)))
    if len(grays) != len(GRAY_CASES):
        bad.append('%d Gray Levels answers for %d inputs' % (len(grays), len(GRAY_CASES)))
    for (t, m), g in zip(inputs, got):
        w = oracle.choose(t, m)
        want = (w['res'], w['fmt'], w['resDefault'], w['fmtDefault'], w['pairDefault'])
        if g != want:
            bad.append('%r at %#x: unit %s, oracle %s' % (t, m, g, want))
    if len(got) != len(inputs):
        bad.append('%d answers for %d inputs' % (len(got), len(inputs)))
    return bad


MUTATIONS = [
    ('the format table is searched from the end',
     '        for (k = 0; k < OSRDN_FMT_COUNT; k++)\n            if (contains(displayMode, osrdnFmtAll[k].token)) {',
     '        for (k = OSRDN_FMT_COUNT - 1; k >= 0; k--)\n            if (contains(displayMode, osrdnFmtAll[k].token)) {'),
    ('width and height are swapped in the match',
     '(unsigned long)osrdnResAll[k].width == width &&',
     '(unsigned long)osrdnResAll[k].width == height &&'),
    ('the token must start the string',
     '        if (*b == \'\\0\')\n            return 1;\n    }',
     '        if (*b == \'\\0\')\n            return 1;\n        break;\n    }'),
    ('a refresh of 0 is accepted',
     'refresh == 0 || refresh > MODESEL_REFRESH_MAX',
     'refresh > MODESEL_REFRESH_MAX'),
    ('tabs are not blanks',
     "    while (*text == ' ' || *text == '\\t')",
     "    while (*text == ' ')"),
    ('text after Hz is ignored',
     '        if (!takeWord(&text, "ColorSpace:"))\n            return 0;',
     '        if (!takeWord(&text, "ColorSpace:"))\n            return 1;'),
    ('the format is taken only when the resolution parsed',
     '        for (k = 0; k < OSRDN_FMT_COUNT; k++)\n            if (contains(',
     '        for (k = 0; sel->resDefault == 0 && k < OSRDN_FMT_COUNT; k++)\n            if (contains('),
    ('the pair check is gone',
     '    if (!pairFits(sel->res, sel->fmt, mapped)) {',
     '    if (0) {'),
    ('only the resolution is reset by the pair check',
     '        sel->res = OSRDN_RES_DEFAULT;\n        sel->fmt = OSRDN_FMT_DEFAULT;\n        sel->pairDefault = 1;',
     '        sel->res = OSRDN_RES_DEFAULT;\n        sel->pairDefault = 1;'),
    ('a number that overflows wraps instead of failing',
     '        if (result > (4294967295UL - digit) / 10UL)\n            return 0;\n',
     ''),
    ('Gray Levels takes 8 as well',
     '    if (sameText(text, "2"))\n        return 2;',
     '    if (sameText(text, "2"))\n        return 2;\n    if (sameText(text, "8"))\n        return 8;'),
    ('Gray Levels matches a prefix',
     '    return *a == \'\\0\' && *b == \'\\0\';',
     '    return *b == \'\\0\';'),
    ('an absent Gray Levels key is refused',
     '    if (text == 0 || sameText(text, "256"))\n        return 0;',
     '    if (text == 0) {\n        *refused = 1;\n        return 0;\n    }\n    if (sameText(text, "256"))\n        return 0;'),
    ('an empty ColorSpace is accepted',
     '        text = skipBlanks(text);\n        if (*text == \'\\0\')\n            return 0;\n    }',
     '    }'),
]


def main():
    work = tempfile.mkdtemp(prefix='modesel.', dir=os.environ.get('TMPDIR'))
    atexit.register(shutil.rmtree, work, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
    fails = 0

    for t, want in HAND:
        w = oracle.choose(t)
        got = (w['res'], w['fmt'], w['resDefault'], w['fmtDefault'], w['pairDefault'])
        if got != want:
            print('  FAIL oracle: %r gives %s, a person wrote %s' % (t, got, want))
            fails += 1
    for t, want in GRAY_HAND.items():
        if oracle.gray(t) != want:
            print('  FAIL oracle: Gray Levels %r gives %s, a person wrote %s' % (t, oracle.gray(t), want))
            fails += 1
    print('  %-4s oracle agrees with %d hand-written cases' % ('FAIL' if fails else 'ok', len(HAND) + len(GRAY_HAND)))

    r = subprocess.run(['gcc-12', '-m32', '-std=gnu89', '-O0', '-Wall', '-Wextra', '-Wno-deprecated',
                        '-I', TPROJ, '-x', 'c', '-c', UNIT, '-o', os.path.join(work, 'm32.o')],
                       capture_output=True, text=True)
    ok32 = r.returncode == 0 and 'warning' not in r.stderr
    print('  %-4s the unit compiles for 32 bits without a warning %s' % ('ok' if ok32 else 'FAIL', r.stderr[-200:]))
    fails += 0 if ok32 else 1

    bad = layer2(UNIT, work)
    for b in bad[:5]:
        print('  FAIL %s' % b)
    print('  %-4s the unit equals the oracle on %d inputs' % ('FAIL' if bad else 'ok', len(cases()) + 4))
    fails += 1 if bad else 0

    text = open(UNIT).read()
    for n, (label, old, new) in enumerate(MUTATIONS):
        if text.count(old) != 1:
            print('  FAIL mutation %-48s anchor found %d times' % (label, text.count(old)))
            fails += 1
            continue
        mwork = os.path.join(work, 'm%d' % n)
        os.makedirs(mwork)
        mpath = os.path.join(mwork, 'osrdn_modesel.m')
        open(mpath, 'w').write(text.replace(old, new))
        bad = layer2(mpath, mwork)
        caught = bool(bad) and not (len(bad) == 1 and bad[0].startswith('does not build'))
        print('  %-4s mutation %-48s %s' % ('ok' if caught else 'FAIL', label,
                                            bad[0][:60] if caught else ('NOT CAUGHT' if not bad else bad[0][:60])))
        fails += 0 if caught else 1
    print('test_modesel: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
