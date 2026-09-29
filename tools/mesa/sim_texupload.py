#!/usr/bin/env python3
"""sim_texupload.py -- the texture level upload's read-back, run on the host.

G5-1a (docs/G5_1A_TEX_READBACK_PLAN.md 2).  mesa/OSRDNMesaTex.c writes a level
into the surface window and reads part of it back: four corner words by
default, the whole level under RDNMesaTexVerify.  This links the real unit
against a fake window (a malloc'd block) and checks the read-back's SHAPE --
how many words it compares, and that the corners are the corners:

  1. default: verifyWords grows by 4 for a w,h > 1 level, by 2 for 1 x N and
     N x 1, by 1 for 1 x 1 -- each corner once;
  2. RDNMesaTexVerify set: by w x h;
  3. readBad stays 0 either way (the fake window keeps what is written), and a
     level past the window is refused NO_WINDOW without touching the counters;
  4. three mutations are caught: the last row not sampled, the knob ignored,
     a duplicate corner counted twice.

What it cannot test: a word that comes back wrong -- the fake window returns
what was written.  The refusal on a mismatch is the same two lines both loops
share (readBad, refused[READBACK]) and the target's picture is the real gate.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.normpath(os.path.join(HERE, '..', '..'))
MESA = os.path.join(PROJ, 'mesa')
SRC = os.path.join(MESA, 'OSRDNMesaTex.c')

DRIVER = r'''
#include <stdio.h>
#include <stdlib.h>
#include "OSRDNMesaTex.h"
#include "OSRDNMesaTriTable.h"      /* OSRDN_TEX_W, OSRDN_TEX_H */
static unsigned long winBuf[1 << 18];
void *osrdn_surf_window(unsigned long *bytes) { *bytes = sizeof winBuf; return winBuf; }
/* G5-2: the retire, counted, with the window as it stood when it was asked -- a write before it
   would already be in that sum */
static unsigned long retires, sumAtRetire;
static unsigned long sumWin(void)
{
    unsigned long i, s = 0UL;
    for (i = 0; i < sizeof winBuf / sizeof winBuf[0]; i++) s += winBuf[i] * (i + 1UL);
    return s;
}
int osrdn_tri_retire_if_inflight(void) { retires++; sumAtRetire = sumWin(); return 1; }
static void retireLine(const char *what, unsigned long r0, unsigned long s0)
{
    printf("RETIRE %s n=%lu early=%d\n", what, retires - r0, (retires - r0 == 1UL && sumAtRetire != s0) ? 1 : 0);
}
int main(void)
{
    static unsigned char px[256 * 256 * 4];
    static const int dims[4][2] = { {8, 8}, {1, 8}, {8, 1}, {1, 1} };
    const osrdn_tex_counts *c = OSRDNMesaTexCounts();
    unsigned long v0, b0, r0, s0;
    static unsigned long argb[OSRDN_TEX_W * OSRDN_TEX_H];
    int k, why, ok;
    for (k = 0; k < (int)sizeof px; k++) px[k] = (unsigned char)(k * 7 + 3);
    for (k = 0; k < 4; k++) {
        int w = dims[k][0], h = dims[k][1];
        unsigned long rb = ((unsigned long)w * 4UL + 31UL) & ~31UL;
        v0 = c->verifyWords; b0 = c->readBad;
        px[0] = (unsigned char)(px[0] + 1); px[1] = (unsigned char)(px[1] + 3);   /* each upload changes the window */
        r0 = retires; s0 = sumWin();
        ok = osrdn_tex_upload_level(px, 4, w, h, 0UL, rb, 16, 8, 0, 24, &why);
        printf("TEX w=%d h=%d ok=%d why=%d verify=%lu readbad=%lu\n", w, h, ok, why, c->verifyWords - v0, c->readBad - b0);
        retireLine("level", r0, s0);
    }
    for (k = 0; k < OSRDN_TEX_W * OSRDN_TEX_H; k++) argb[k] = 0x80000000UL | ((unsigned long)k * 2654435761UL);
    r0 = retires; s0 = sumWin();
    ok = osrdn_tex_upload(argb, OSRDN_TEX_W, OSRDN_TEX_H, &why);
    retireLine("fixed", r0, s0);
    v0 = c->verifyWords;
    ok = osrdn_tex_upload_level(px, 4, 8, 8, sizeof winBuf, 32UL, 16, 8, 0, 24, &why);
    printf("TEX past-window ok=%d why=%d verify=%lu\n", ok, why, c->verifyWords - v0);
    return 0;
}
'''

MUTATIONS = [
    ('G5-2: the level upload does not retire',
     '    /* G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2-4): an accepted batch may still be reading these texels */\n    (void)osrdn_tri_retire_if_inflight();\n', ''),
    ('G5-2: the fixed-size upload does not retire',
     '    (void)osrdn_tri_retire_if_inflight();     /* G5-2: as the level upload */\n', ''),
    ('the last row is not sampled',
     "        if (h > 1) { rows[1] = (unsigned long)h - 1UL; nr = 2UL; }", "        if (0) { rows[1] = (unsigned long)h - 1UL; nr = 2UL; }"),
    ('the knob is ignored (the whole loop always)',
     'texVerifyAll = (getenv("RDNMesaTexVerify") != 0) ? 1 : 0;', 'texVerifyAll = 1;'),
    ('a duplicate corner is compared twice',
     "        if (w > 1) { cols[1] = (unsigned long)w - 1UL; nc = 2UL; }", "        cols[1] = (unsigned long)w - 1UL; nc = 2UL;"),
]


# G5-2: the same call MOVED past the write loop -- present, once, and too late.  Built from the
# source so the span between the two places is the file's own.
_RET = '    /* G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2-4): an accepted batch may still be reading these texels */\n    (void)osrdn_tri_retire_if_inflight();\n'
_VER = '    if (texVerify()) {\n        p = px;\n'
_t = open(SRC).read()
if _t.count(_RET) == 1 and _t.count(_VER) == 1 and _t.index(_RET) < _t.index(_VER):
    _span = _t[_t.index(_RET):_t.index(_VER) + len(_VER)]
    MUTATIONS.append(('G5-2: the level upload retires after it writes', _span,
                      _span.replace(_RET, '', 1).replace(_VER, _RET + _VER, 1)))
else:
    MUTATIONS.append(('G5-2: the level upload retires after it writes', '<anchor not found>', ''))


def build(src_text, tmp):
    src = os.path.join(tmp, 'OSRDNMesaTex.c')
    drv = os.path.join(tmp, 'drv.c')
    exe = os.path.join(tmp, 'drv')
    open(src, 'w').write(src_text)
    open(drv, 'w').write(DRIVER)
    r = subprocess.run(['gcc', '-O1', '-w', '-I', MESA, '-o', exe, drv, src,
                        os.path.join(MESA, 'OSRDNMesaTime.c')], capture_output=True, text=True)
    return (exe, '') if r.returncode == 0 else (None, r.stderr)


def run(exe, knob):
    env = dict(os.environ)
    env.pop('RDNMesaTexVerify', None)
    env.pop('RDNMesaTime', None)
    if knob:
        env['RDNMesaTexVerify'] = '1'
    return subprocess.run([exe], capture_output=True, text=True, env=env).stdout


def judge(out, knob):
    p = []
    got = {}
    for m in re.finditer(r'TEX w=(\d+) h=(\d+) ok=(\d+) why=(\d+) verify=(\d+) readbad=(\d+)', out):
        got[(int(m.group(1)), int(m.group(2)))] = (int(m.group(3)), int(m.group(4)), int(m.group(5)), int(m.group(6)))
    want = {(8, 8): 4, (1, 8): 2, (8, 1): 2, (1, 1): 1}
    for k, corners in want.items():
        if k not in got:
            p.append('no line for %dx%d' % k)
            continue
        ok, why, v, rb = got[k]
        exp = k[0] * k[1] if knob else corners
        if ok != 1 or why != 0 or rb != 0 or v != exp:
            p.append('%dx%d: ok=%d why=%d verify=%d (want %d) readbad=%d' % (k[0], k[1], ok, why, v, exp, rb))
    rl = re.findall(r'RETIRE (\w+) n=(\d+) early=(\d+)', out)
    if len(rl) != 5 or any(n != '1' or e != '0' for _, n, e in rl):
        p.append('G5-2: each upload must retire once, before it writes: %s' % rl)
    m = re.search(r'TEX past-window ok=(\d+) why=(\d+) verify=(\d+)', out)
    if not m or m.group(1) != '0' or m.group(2) != '1' or m.group(3) != '0':
        p.append('a level past the window was not refused NO_WINDOW untouched: %s' % (m.group(0) if m else 'no line'))
    return p


def main():
    src = open(SRC).read()
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        exe, e = build(src, tmp)
        if exe is None:
            print('sim_texupload: FAIL (the unit does not build on the host)\n' + e)
            return 1
        for knob in (False, True):
            p = judge(run(exe, knob), knob)
            name = 'the whole level under RDNMesaTexVerify' if knob else 'four corners by default, each once'
            if p:
                bad += 1
                print('  FAIL %s: %s' % (name, '; '.join(p)))
            else:
                print('  ok   ' + name)
        for name, a, b in MUTATIONS:
            if src.count(a) != 1:
                print('  FAIL mutation %-46s anchor found %d times' % (name, src.count(a)))
                bad += 1
                continue
            with tempfile.TemporaryDirectory() as t2:
                exe2, e2 = build(src.replace(a, b), t2)
                if exe2 is None:
                    print('  ok   mutation %-46s does not build' % name)
                    continue
                caught = bool(judge(run(exe2, False), False)) or bool(judge(run(exe2, True), True))
                print('  %s mutation %-46s %s' % ('ok  ' if caught else 'FAIL', name, 'caught' if caught else 'NOT caught'))
                bad += 0 if caught else 1
    print('sim_texupload: %s' % ('PASS' if bad == 0 else 'FAIL (%d)' % bad))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
