#!/usr/bin/env python3
"""The offscreen window's start and ceiling (osrdn_window.m) against the
Matrox rule computed here, for all twenty modes (docs/R4_ENGINE_PLAN.md 11, 12-4 #5).

  check_window.py      compile the unit for 32 bits, compare, then every mutation

Three independent sources must agree: this python, the C unit, and the five
32 bpp starts a person wrote into docs/R4_ENGINE_PLAN.md 11-2 (read from the
document, not restated here).
"""

import shutil
import atexit
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
TPROJ = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj')
UNIT = os.path.join(TPROJ, 'osrdn_window.m')
DOC = os.path.join(PROJ, 'docs', 'R4_ENGINE_PLAN.md')
LIBC32 = '/usr/lib32/libc.so.6'
LD32 = '/lib/ld-linux.so.2'
PAGE = 8192
MIB = 1 << 20
RES = [(640, 480), (800, 600), (1024, 768), (1280, 1024), (1600, 1200)]
BYTES = [4, 2, 1]

# odd inputs: page not a power of two, zero sizes, products that overflow 32 bits
ODD = [(1024, 768, 4, 0), (1024, 768, 4, 3000), (0, 768, 4, PAGE), (1024, 0, 4, PAGE),
       (1024, 768, 0, PAGE), (70000, 70000, 4, PAGE), (0x40000000, 1, 4, PAGE),
       (65536, 16383, 4, PAGE), (65536, 16384 - 256, 4, PAGE)]


def py_start(w, h, b, page):
    if page == 0 or page & (page - 1) or w == 0 or h == 0 or b == 0:
        return 0
    v = w * b * h + 256 * w * b
    if v > 0xFFFFFFFF or w * b > 0xFFFFFFFF:
        return 0
    r = (v + page - 1) // page * page
    return 0 if r > 0xFFFFFFFF else r


def py_ceiling(vram, page):
    if page == 0 or page & (page - 1) or vram <= 4 * MIB:
        return 0
    return (vram - 4 * MIB) & ~(page - 1)


HARNESS = r'''
int printf(const char *, ...);
void exit(int);
#include "osrdn_window.h"
static const unsigned long in[][4] = { %(rows)s };
int main(void)
{
    unsigned k;
    for (k = 0; k < sizeof in / sizeof in[0]; k++)
        printf("S %%lu\n", osrdn_window_start(in[k][0], in[k][1], in[k][2], in[k][3]));
    printf("C %%lu\n", osrdn_window_ceiling(OSRDN_WIN_VRAM, 8192UL));
    printf("C %%lu\n", osrdn_window_ceiling(0x400000UL, 8192UL));
    printf("C %%lu\n", osrdn_window_ceiling(OSRDN_WIN_VRAM, 3000UL));
    return 0;
}
__attribute__((force_align_arg_pointer))
void _start(void) { exit(main()); }
'''


def rows():
    out = [(w, h, b, PAGE) for w, h in RES for b in BYTES] + ODD
    return out


def run_unit(unit, work):
    src = os.path.join(work, 'h.c')
    open(src, 'w').write(HARNESS % dict(rows=', '.join('{%dUL, %dUL, %dUL, %dUL}' % r for r in rows())))
    shutil_unit = os.path.join(work, 'osrdn_window.m')
    if unit != shutil_unit:
        open(shutil_unit, 'w').write(open(unit).read())
    exe = os.path.join(work, 'h')
    r = subprocess.run(['gcc-12', '-m32', '-std=gnu89', '-O0', '-Wall', '-Werror', '-Wno-main', '-Wno-deprecated',
                        '-I', TPROJ, '-x', 'c', shutil_unit, src, '-x', 'none', '-nostdlib', '-nostartfiles',
                        LIBC32, '-Wl,-dynamic-linker,' + LD32, '-o', exe], capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr[-400:]
    r = subprocess.run([exe], capture_output=True, text=True, timeout=30)
    return [int(l.split()[1]) for l in r.stdout.splitlines()], ''


def doc_starts():
    """the 32 bpp column of the 11-2 table: '| 640×480 | 1 884 160 → ...'"""
    text = open(DOC, encoding='utf-8').read()
    sec = text.split('### 11-2.', 1)[1].split('###', 1)[0]
    got = {}
    for w, h in RES:
        m = re.search(r'\|\s*%d×%d\s*\|\s*\**([\d ]+)\**\s*→' % (w, h), sec)
        got[(w, h)] = int(m.group(1).replace(' ', '')) if m else None
    return got


def check(values):
    p = []
    want = [py_start(*r) for r in rows()]
    got = values[:len(want)]
    for r, g, w in zip(rows(), got, want):
        if g != w:
            p.append('start%s: unit %d, python %d' % (r, g, w))
    cw = [py_ceiling(128 * MIB, PAGE), py_ceiling(4 * MIB, PAGE), py_ceiling(128 * MIB, 3000)]
    if values[len(want):] != cw:
        p.append('ceilings: unit %s, python %s' % (values[len(want):], cw))
    doc = doc_starts()
    for (w, h), v in doc.items():
        if v != py_start(w, h, 4, PAGE):
            p.append('doc 11-2 says %dx%d starts at %s, python %d' % (w, h, v, py_start(w, h, 4, PAGE)))
    return p


MUTATIONS = [
    ('255 guard rows', 'guard = row * OSRDN_WIN_GUARD_ROWS;', 'guard = row * (OSRDN_WIN_GUARD_ROWS - 1UL);'),
    ('rounded down, not up', 'return (start + pageBytes - 1UL) & ~(pageBytes - 1UL);',
     'return start & ~(pageBytes - 1UL);'),
    ('no top margin', 'return (vramBytes - OSRDN_WIN_TOP_MARGIN) & ~(pageBytes - 1UL);',
     'return vramBytes & ~(pageBytes - 1UL);'),
    ('the overflow test on the sum is gone', '    if (visible > 0xFFFFFFFFUL - guard)\n        return 0UL;\n', ''),
    ('a page that is not a power of two is accepted',
     '    return pageBytes != 0UL && (pageBytes & (pageBytes - 1UL)) == 0UL;', '    return pageBytes != 0UL;'),
]


def main():
    if not os.path.exists(LIBC32):
        print('  --   %s not present, skipped' % LIBC32)
        return 0
    work = tempfile.mkdtemp(prefix='chkwin.')
    atexit.register(shutil.rmtree, work, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
    fails = 0
    values, err = run_unit(UNIT, work)
    if values is None:
        print('  FAIL the unit does not build\n' + err)
        return 1
    base = check(values)
    for x in base:
        print('  FAIL %s' % x)
    print('  %-4s %d geometries (the 20 modes; both 8 bpp formats share one) and %d odd inputs: unit = python = docs 11-2'
          % ('FAIL' if base else 'ok', len(RES) * len(BYTES), len(ODD)))
    fails += len(base)
    text = open(UNIT).read()
    for label, old, new in MUTATIONS:
        if text.count(old) != 1:
            print('  FAIL mutation %s: anchor found %d times' % (label, text.count(old)))
            fails += 1
            continue
        mdir = tempfile.mkdtemp(prefix='chkwinm.')
        atexit.register(shutil.rmtree, mdir, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
        path = os.path.join(mdir, 'osrdn_window.m')
        open(path, 'w').write(text.replace(old, new))
        v, err = run_unit(path, mdir)
        caught = v is None or bool(check(v))
        print('  %-4s mutation %s' % ('ok' if caught else 'FAIL', label))
        fails += 0 if caught else 1
    print('check_window: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
