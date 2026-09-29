#!/usr/bin/env python3
"""d_mmap's decision (osrdn_vmap.m) against an independent python oracle, then
every mutation (docs/R4C_VMAP_PLAN.md 6-1, 11-1, 11-7).

  check_vmap.py      compile the unit for 32 bits, compare, then every mutation

Inputs: the 15 window geometries of the 20 modes (both 8 bpp formats share one,
tools/r4/check_window.py) at BAR0 e0000000 and page 8192, walked page by page
from 0 to end + 2 pages; a fixed boundary list; 20 000 seeded random (dev,
offset, prot) triples; odd fix inputs; and raw windows that bypass fix, so the
checks fix makes unreachable (wrap, PFN range) are still exercised.

Two judges per run: the oracle, and the unit's own boot self-test -- a
mutation must be caught by the oracle, and the self-test's verdict on it is
printed so its power is visible (it is not required to catch the checks only
raw windows reach).
"""

import atexit
import os
import random
import subprocess
import sys
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
TPROJ = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj')
UNIT = os.path.join(TPROJ, 'osrdn_vmap.m')
LIBC32 = '/usr/lib32/libc.so.6'
LD32 = '/lib/ld-linux.so.2'
PAGE = 8192
MIB = 1 << 20
BAR0 = 0xE0000000
CEIL = (128 * MIB - 4 * MIB) & ~(PAGE - 1)
RES = [(640, 480), (800, 600), (1024, 768), (1280, 1024), (1600, 1200)]
INT_MAX = 0x7FFFFFFF
RW = 3
BATCH_BASE = 0x40000000        # OSRDN_VMAP_BATCH_BASE, R7b


def start_of(w, h, b):
    v = w * b * h + 256 * w * b
    return (v + PAGE - 1) // PAGE * PAGE


def s32(x):
    x &= 0xFFFFFFFF
    return x - (1 << 32) if x & 0x80000000 else x


# ---- the oracle ------------------------------------------------------------

def o_fix(start, end, bar0, page):
    if page == 0 or page & (page - 1):
        return 2, None
    if start % page or end % page or bar0 % page:
        return 3, None
    if start >= end or end - start < page:
        return 4, None
    if bar0 + end > 0xFFFFFFFF:
        return 5, None
    if end > INT_MAX - 2 * page:
        return 7, None
    if (bar0 + end - page) // page > INT_MAX:
        return 6, None
    return 0, dict(start=start, end=end, bar0=bar0, page=page)


def o_fix_batch(w, phys, n):
    """R7b: the batch window, in the same order the unit asks its questions"""
    if w is not None and w.get('bfixed'):
        return 8                                        # BAGAIN
    if w is None:
        return 9                                        # BFIRST: no page, no shift
    if n != w['page']:
        return 10                                       # BSIZE
    if phys % w['page']:
        return 11                                       # BALIGN
    if phys > 0xFFFFFFFF - n:
        return 12                                       # BWRAP
    if BATCH_BASE <= w['end'] + 2 * w['page']:
        return 13                                       # BLOW: the self-test walks that far
    if BATCH_BASE > INT_MAX - n:
        return 14                                       # BRANGE
    if phys // w['page'] > INT_MAX:
        return 15                                       # BPFN
    w['bfixed'], w['bbase'], w['bphys'], w['bbytes'] = True, BATCH_BASE, phys, n
    return 0


def o_pfn(w, dev, off, prot):
    """the physical page the kernel would get, or -1 -- stated from the plan,
    not from the C"""
    if w is None:
        return -1
    if dev & 0xFF:
        return -1
    if off < 0 or prot != RW:
        return -1
    if w.get('bfixed') and off >= w['bbase']:
        rel = off - w['bbase']
        if w['bbytes'] < w['page'] or rel > w['bbytes'] - w['page']:
            return -1
        if w['bphys'] > 0xFFFFFFFF - rel:
            return -1
        phys = w['bphys'] + rel
        if phys % w['page']:
            return -1
        pfn = phys // w['page']
        return pfn if pfn <= INT_MAX else -1
    if not (w['start'] <= off < w['end']):
        return -1
    phys = w['bar0'] + off
    if phys > 0xFFFFFFFF or phys % w['page']:
        return -1
    pfn = phys // w['page']
    return pfn if pfn <= INT_MAX else -1


# ---- the harness -------------------------------------------------------------

HARNESS = r'''
int printf(const char *, ...);
void exit(int);
#include "osrdn_vmap.h"
static const unsigned long fixes[][5] = { %(fixes)s };     /* start end bar0 page raw */
static const unsigned long bfixes[][4] = { %(bfixes)s };     /* window phys bytes raw */
static const long asks[][4] = { %(asks)s };                  /* window dev off prot */
int main(void)
{
    static osrdn_vmap w[%(nw)d];
    unsigned k, i;
    unsigned long cases, allowed, bad;
    for (k = 0; k < sizeof fixes / sizeof fixes[0]; k++) {
        if (fixes[k][4]) {                     /* raw: bypass fix */
            unsigned long s = 0;
            w[k].fixed = (fixes[k][4] == 1); w[k].start = fixes[k][0]; w[k].end = fixes[k][1];
            w[k].bar0 = fixes[k][2]; w[k].page = fixes[k][3];
            while ((1UL << s) != fixes[k][3]) s++;
            w[k].shift = s;
            printf("F %%u 0\n", k);
        } else {
            printf("F %%u %%d\n", k, osrdn_vmap_fix(&w[k], fixes[k][0], fixes[k][1], fixes[k][2], fixes[k][3]));
        }
    }
    for (k = 0; k < sizeof bfixes / sizeof bfixes[0]; k++) {
        if (bfixes[k][3]) {                    /* raw: bypass fix_batch */
            w[bfixes[k][0]].bbase  = 0x40000000UL;
            w[bfixes[k][0]].bphys  = bfixes[k][1];
            w[bfixes[k][0]].bbytes = bfixes[k][2];
            w[bfixes[k][0]].bfixed = 1;
            printf("B %%lu 0\n", bfixes[k][0]);
        } else {
            printf("B %%lu %%d\n", bfixes[k][0],
                   osrdn_vmap_fix_batch(&w[bfixes[k][0]], bfixes[k][1], bfixes[k][2]));
        }
    }
    /* write-once: a second fix of window 0 must be refused and change nothing */
    printf("A %%d %%lu\n", osrdn_vmap_fix(&w[0], 0x100000UL, 0x200000UL, 0UL, 8192UL), w[0].start);
    for (i = 0; i < sizeof asks / sizeof asks[0]; i++)
        printf("P %%d\n", osrdn_vmap_pfn(&w[asks[i][0]], (int)asks[i][1], (int)asks[i][2], (int)asks[i][3]));
    for (k = 0; k < %(nself)d; k++) {
        bad = osrdn_vmap_selftest(&w[k], &cases, &allowed);
        printf("S %%u %%lu %%lu %%lu\n", k, bad, cases, allowed);
    }
    printf("G %%d\n", osrdn_vmap_window.fixed);
    return 0;
}
__attribute__((force_align_arg_pointer))
void _start(void) { exit(main()); }
'''


def build_inputs():
    fixes = []          # (start, end, bar0, page, raw)
    geos = sorted({start_of(w, h, b) for w, h in RES for b in (4, 2, 1)})
    assert len(geos) == 15, len(geos)
    for s in geos:
        fixes.append((s, CEIL, BAR0, PAGE, 0))
    nself = len(fixes)
    odd = [(0x100000, CEIL, BAR0, 3000, 0), (0x100000, CEIL, BAR0, 0, 0),
           (0x100004, CEIL, BAR0, PAGE, 0), (0x100000, CEIL, BAR0 + 4, PAGE, 0),
           (0x100000, 0x101000, BAR0, PAGE, 0), (CEIL, 0x100000, BAR0, PAGE, 0),
           (0x100000, 0x200000, 0xFFF00000, PAGE, 0), (0x100000, 0x7FFFE000, 0x0, PAGE, 0),
           (0x100000, 0x200000, 0x80000000, 1, 0),
           # raw windows fix would refuse, so the late checks are reached
           (0x0, 0x10000, 0xFFFFE000, PAGE, 1), (0x0, 0x10000, 0xF0000000, 1, 1),
           # an end past 2^31, where only the sign test refuses offset -2^31
           (0x0, 0xF0000000, 0x0, PAGE, 1),
           # a window whose range covers the batch base: which branch wins (R7b)
           (0x0, 0x60000000, 0x0, PAGE, 1),
           # values in place but never fixed (raw 2): every answer must be -1
           (0x100000, 0x200000, BAR0, PAGE, 2)]
    fixes += odd
    asks = []
    wins = []
    for k, (s, e, b, p, raw) in enumerate(fixes):
        if raw == 2:
            rc, w = 0, None
        else:
            rc, w = o_fix(s, e, b, p) if not raw else (0, dict(start=s, end=e, bar0=b, page=p))
        wins.append((rc, w))
    # R7b: batch windows.  The good one goes on window 0; the rest walk fix_batch's
    # refusals, including a second fix of the same window (which must change nothing).
    brc = []
    raw2 = next(k for k, f in enumerate(fixes) if f[4] == 2)
    big = next(k for k, f in enumerate(fixes) if f[1] == 0xF0000000)
    small = next(k for k, f in enumerate(fixes) if f[4] == 1 and f[1] == 0x10000 and f[3] == PAGE)
    cover = next(k for k, f in enumerate(fixes) if f[1] == 0x60000000)
    bfixes = [(0, 0x60000, PAGE, 0),            # ok
              (0, 0x62000, PAGE, 0),            # BAGAIN: write-once
              (1, 0x60004, PAGE, 0),            # BALIGN
              (2, 0x60000, 4096, 0),            # BSIZE
              (3, 0xFFFFE000, PAGE, 0),         # BWRAP
              (big, 0x60000, PAGE, 0),          # BLOW: the window reaches past the base
              (raw2, 0x60000, PAGE, 0),         # BFIRST: never fixed
              (4, 0x60000, PAGE, 0),            # ok, a second good one
              # raw: sizes fix_batch refuses, so its bound and its page-start
              # check are asked at a size where they can be wrong
              (small, 0x100000, 3 * PAGE + 4096, 1),
              (cover, 0x200000, 2 * PAGE, 1)]  # and where the VRAM window covers the base
    for k, phys, n, raw in bfixes:
        if raw:
            w = wins[k][1]
            w['bfixed'], w['bbase'], w['bphys'], w['bbytes'] = True, BATCH_BASE, phys, n
            brc.append(0)
        else:
            brc.append(o_fix_batch(wins[k][1], phys, n))
    rnd = random.Random(0x5234D30)
    for k, (s, e, b, p, raw) in enumerate(fixes):
        w = wins[k][1]
        if w is None:
            for off in (s, s + PAGE, e - PAGE, 0):
                asks.append((k, 0, off, RW))
            continue
        pg = w['page'] if w['page'] >= 4 else 4096
        if k < nself:
            for off in range(0, e + 2 * pg + 1, pg):
                asks.append((k, 0, off, RW))
        for off in (s, s + pg, e - pg, e, e + pg, s - pg, s + 4, s + 1, 0, INT_MAX - 8191, -1, -8192,
                    -2 ** 31, e - 1, e - pg + 4):
            if -2 ** 31 <= off <= INT_MAX:
                asks.append((k, 0, off, RW))
        for dev in (1, 0xFF, 0x100, -28416, -32768, 0x7F00, 0x80):     # -28416 = rdev 0x9100 sign-extended
            asks.append((k, dev, s, RW))
        for prot in (0, 1, 2, 4, 5, 6, 7, 11, -1):
            asks.append((k, 0, s, prot))
        for off in (BATCH_BASE, BATCH_BASE + PAGE, BATCH_BASE - PAGE, BATCH_BASE + 4,
                    BATCH_BASE + PAGE - 4, BATCH_BASE + 2 * PAGE, BATCH_BASE + 3 * PAGE,
                    BATCH_BASE + 4 * PAGE, BATCH_BASE + 5 * PAGE, BATCH_BASE + PAGE + 4,
                    BATCH_BASE + 2 * PAGE - 4, BATCH_BASE + 3 * PAGE + 4096,
                    INT_MAX - PAGE + 1):
            asks.append((k, 0, off, RW))
        for dev, prot in ((1, RW), (0x100, RW), (0, 1), (0, 7), (0, 0)):
            asks.append((k, dev, BATCH_BASE, prot))
    for _ in range(20000):
        k = rnd.randrange(len(fixes))
        lo, hi = sorted(fixes[k][:2])
        lo, hi = max(0, lo - 3 * PAGE), min(INT_MAX, hi + 3 * PAGE)
        off = rnd.choice([rnd.randrange(-2 ** 31, 2 ** 31), rnd.randrange(lo, hi),
                          rnd.randrange(lo, hi) & ~(PAGE - 1)])
        dev = rnd.choice([0, 0, 0, 0x100, 0x1f00, -32768, rnd.randrange(-32768, 32768)])
        prot = rnd.choice([3, 3, 3, 1, 7, 2, 0])
        asks.append((k, dev, off, prot))
    return fixes, wins, asks, nself, bfixes, brc


def clong(x):
    """a 32-bit long literal C89 takes without a warning (-2147483648L does not)"""
    return '(-2147483647L - 1L)' if x == -2 ** 31 else '%dL' % x


def run_unit(unit, work, fixes, asks, nself, bfixes):
    src = os.path.join(work, 'h.c')
    fx = ', '.join('{%dUL, %dUL, %dUL, %dUL, %dUL}' % f for f in fixes)
    ak = ', '.join('{%s}' % ', '.join(clong(x) for x in a) for a in asks)
    bf = ', '.join('{%dUL, %dUL, %dUL, %dUL}' % b for b in bfixes)
    open(src, 'w').write(HARNESS % dict(fixes=fx, asks=ak, bfixes=bf, nw=len(fixes), nself=nself))
    copy = os.path.join(work, 'osrdn_vmap.m')
    if unit != copy:
        open(copy, 'w').write(open(unit).read())
    exe = os.path.join(work, 'h')
    r = subprocess.run(['gcc-12', '-m32', '-std=gnu89', '-O0', '-Wall', '-Werror', '-Wno-main', '-Wno-deprecated',
                        '-I', TPROJ, '-x', 'c', copy, src, '-x', 'none', '-nostdlib', '-nostartfiles',
                        LIBC32, '-Wl,-dynamic-linker,' + LD32, '-o', exe], capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr[-600:]
    try:
        r = subprocess.run([exe], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None, 'hangs (it never came back)'
    return r.stdout.splitlines(), ''


def judge(lines, fixes, wins, asks, nself, bfixes, brc):
    probs = []
    F = [l.split() for l in lines if l.startswith('F ')]
    P = [int(l.split()[1]) for l in lines if l.startswith('P ')]
    S = [l.split() for l in lines if l.startswith('S ')]
    A = [l.split() for l in lines if l.startswith('A ')]
    G = [l.split() for l in lines if l.startswith('G ')]
    for (k, rc), (want, _w) in zip([(int(a[1]), int(a[2])) for a in F], wins):
        if fixes[k][4]:
            continue
        if rc != want:
            probs.append('fix%s: unit %d, oracle %d' % (fixes[k][:4], rc, want))
    B = [l.split() for l in lines if l.startswith('B ')]
    if len(B) != len(bfixes):
        probs.append('%d batch fixes, %d answers' % (len(bfixes), len(B)))
    else:
        for (k, phys, n, _raw), b, want in zip(bfixes, B, brc):
            if int(b[1]) != k or int(b[2]) != want:
                probs.append('fix_batch(win %d, %#x, %d): unit %s, oracle %d' % (k, phys, n, b[2], want))
    if not A or A[0][1] != '1' or int(A[0][2]) != fixes[0][0]:
        probs.append('a second fix was not refused, or it changed the window: %s' % A)
    if len(P) != len(asks):
        probs.append('asked %d, answered %d' % (len(asks), len(P)))
    bad = 0
    for (k, dev, off, prot), got in zip(asks, P):
        rc, w = wins[k]
        want = o_pfn(w if rc == 0 else None, dev, off, prot)
        if got != want:
            bad += 1
            if bad <= 5:
                probs.append('win %d dev=%d off=%#x prot=%d: unit %d, oracle %d' % (k, dev, off, prot, got, want))
    if bad > 5:
        probs.append('... %d answers differ in all' % bad)
    selfbad = sum(int(s[2]) for s in S)
    for s in S:
        k = int(s[1])
        w = wins[k][1]
        if int(s[4]) != (w['end'] - w['start']) // w['page']:
            probs.append('self-test window %d allowed %s pages, want %d' % (k, s[4], (w['end'] - w['start']) // w['page']))
    if G != [['G', '0']]:
        probs.append('the global instance is not zero-initialised or was written: %s' % G)
    return probs, selfbad, S


MUTATIONS = [
    ('the end page is refused (>= for >)', 'off > v->end - v->page)\n        return -1;',
     'off >= v->end - v->page)\n        return -1;'),
    ('the page past the end is allowed', 'off > v->end - v->page)\n        return -1;',
     'off > v->end)\n        return -1;'),
    ('the minor is not checked', '    if ((dev & 0xFF) != 0)\n        return -1;\n', ''),
    ('the whole dev is compared', '    if ((dev & 0xFF) != 0)\n        return -1;', '    if (dev != 0)\n        return -1;'),
    ('prot is a partial match', '    if (prot != OSRDN_VMAP_PROT_RW)', '    if ((prot & OSRDN_VMAP_PROT_RW) != OSRDN_VMAP_PROT_RW)'),
    ('a negative offset is not refused', '    if (offset < 0)\n        return -1;\n', ''),
    ('the alignment is not checked', '    phys = v->bar0 + off;\n    if ((phys & (v->page - 1UL)) != 0UL)\n        return -1;\n',
     '    phys = v->bar0 + off;\n'),
    ('the wrap is not checked', '    if (v->bar0 > 0xFFFFFFFFUL - off)\n        return -1;\n', ''),
    ('the PFN range is not checked',
     '    if ((phys >> v->shift) > VMAP_INT_MAX)\n        return -1;\n    return (int)', '    return (int)'),
    ('the start is not checked', 'off < v->start || off > v->end', 'off > v->end'),
    ('an unfixed window answers', '    if (!v->fixed)\n        return -1;\n', ''),
    ('fix can be called again', '    if (v->fixed)\n        return OSRDN_VMAP_AGAIN;\n', ''),
    ('fix accepts an unaligned bar0', ' ||\n        (bar0 & (page - 1UL)) != 0UL)', ')'),
    ('fix accepts a page that is not a power of two', 'page == 0UL || (page & (page - 1UL)) != 0UL',
     'page == 0UL'),
    ('fix does not check the wrap', '    if (bar0 > 0xFFFFFFFFUL - end)\n        return OSRDN_VMAP_WRAP;\n', ''),
    ('the shift is one short', '    v->shift = shift;', '    v->shift = shift - 1UL;'),
    ('the global starts fixed', 'osrdn_vmap osrdn_vmap_window = { 0,', 'osrdn_vmap osrdn_vmap_window = { 1,'),
    # R7b, the batch window
    ('the batch bound is asked of the offset, not the whole page',
     'rel > v->bbytes - v->page', 'rel >= v->bbytes'),
    ('the batch branch is entered without a batch window',
     'if (v->bfixed && off >= v->bbase)', 'if (off >= v->bbase)'),
    ('the batch window swallows the VRAM window', 'off >= v->bbase)', 'off >= v->start)'),
    ('fix_batch accepts an unaligned physical base',
     '    if ((phys & (v->page - 1UL)) != 0UL)\n        return OSRDN_VMAP_BALIGN;\n', ''),
    ('fix_batch accepts a size that is not one page',
     '    if (bytes != v->page)\n        return OSRDN_VMAP_BSIZE;', '    if (bytes == 0UL)\n        return OSRDN_VMAP_BSIZE;'),
    ('fix_batch can be called again',
     '    if (v->bfixed)\n        return OSRDN_VMAP_BAGAIN;\n', ''),
    ('fix_batch does not keep clear of the VRAM window',
     '    if (OSRDN_VMAP_BATCH_BASE <= v->end + 2UL * v->page)\n        return OSRDN_VMAP_BLOW;\n', ''),
    ('fix_batch does not need the other window first',
     '    if (!v->fixed)\n        return OSRDN_VMAP_BFIRST;', '    if (0)\n        return OSRDN_VMAP_BFIRST;'),
]


def main():
    if not os.path.exists(LIBC32):
        print('  --   %s not present, skipped' % LIBC32)
        return 0
    fixes, wins, asks, nself, bfixes, brc = build_inputs()
    work = tempfile.mkdtemp(prefix='chkvmap.', dir=os.environ.get('TMPDIR'))
    # 2026-09-24: none of these tools removed what they made, and /tmp
    # reached 35.6 GiB of our scratch.  atexit, so a failure path cleans
    # up too -- the tool exits on a bad verdict from several places.
    atexit.register(shutil.rmtree, work, True)
    fails = 0
    lines, err = run_unit(UNIT, work, fixes, asks, nself, bfixes)
    if lines is None:
        print('  FAIL the unit does not build\n' + err)
        return 1
    probs, selfbad, S = judge(lines, fixes, wins, asks, nself, bfixes, brc)
    for p in probs:
        print('  FAIL %s' % p)
    fails += len(probs)
    print('  %-4s %d windows (15 geometries + %d odd/raw), %d answers: unit = oracle'
          % ('FAIL' if probs else 'ok', len(fixes), len(fixes) - nself, len(asks)))
    if selfbad:
        print('  FAIL the boot self-test finds %d wrong answers in the good unit' % selfbad)
        fails += 1
    else:
        print('  ok   the boot self-test passes the good unit on all 15 windows (%s cases on the first)'
              % S[0][3])
    text = open(UNIT).read()
    for label, old, new in MUTATIONS:
        if text.count(old) != 1:
            print('  FAIL mutation %s: anchor found %d times' % (label, text.count(old)))
            fails += 1
            continue
        mdir = tempfile.mkdtemp(prefix='chkvmapm.', dir=os.environ.get('TMPDIR'))
        path = os.path.join(mdir, 'osrdn_vmap.m')
        open(path, 'w').write(text.replace(old, new))
        ls, err = run_unit(path, mdir, fixes, asks, nself, bfixes)
        if ls is None:
            caught, st = True, err if err.startswith('hangs') else 'does not build'
        else:
            p2, sb, _ = judge(ls, fixes, wins, asks, nself, bfixes, brc)
            caught = bool(p2)
            st = 'self-test %s' % ('catches it too' if sb else 'does not see it')
        print('  %-4s mutation %-50s %s' % ('ok' if caught else 'FAIL', label, st if caught else 'NOT CAUGHT'))
        fails += 0 if caught else 1
        # ONE MUTATION'S SCRATCH GOES BEFORE THE NEXT IS MADE.  Measured
        # 2026-09-24: this loop had left 2,548 directories and 25.7 GiB in
        # /tmp -- more than every other tool in the project put together --
        # and it is what finally filled the root filesystem.  Cleaning at exit
        # would not have been enough: they pile up DURING the run.
        shutil.rmtree(mdir, ignore_errors=True)
    print('check_vmap: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
