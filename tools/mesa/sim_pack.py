#!/usr/bin/env python3
"""The vertex packing, RUN on the host, slot by slot.

  sim_pack.py

M1g's textured triangle reached the card with a coordinate where a colour
belonged.  The hook wrote both shapes -- the five-word slots unconditionally and
the seven-word ones after -- and for vertex 2 the five-word writes landed inside
vertex 1's seven-word block.  Every host check passed.  It took a hardware run
and a judge that refused to predict to find it.

So the packing moved into the pure-C unit, where one stride is chosen once, and
this runs it: each vertex is given values that say which slot they belong in, and
every word of the buffer is checked -- including the words that must NOT have
been touched.  A packer that overlaps cannot leave the untouched words untouched.
"""

import shutil
import atexit
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
MESA = os.path.join(PROJ, 'mesa')

HARNESS = r'''
int printf(const char *, ...);
#include "OSRDNMesaTri.h"
#include "OSRDNMesaProbe.h"
#include "OSRDNMesaTriTable.h"

/*
 * The unit talks to the card everywhere EXCEPT in the packer, so the rest of it
 * is given somewhere to go and nowhere to arrive: a probe that never reports a
 * card, and Mach calls that fail.  Nothing here calls them -- they exist so the
 * one pure function can be linked and run.
 */
const OSRDNMesaProbeCaps *OSRDNMesaProbeGetCaps(void) { return 0; }
int OSRDNMesaProbeRun(void) { return 0; }
int task_self(void) { return 0; }
int vm_allocate(int t, char **a, int s, int f) { (void)t; (void)a; (void)s; (void)f; return 1; }

#define SPAN (3 * OSRDN_TEX_VERTEX_WORDS)

static void run(int tex)
{
    unsigned long v[SPAN];
    int i, k;

    for (k = 0; k < SPAN; k++)
        v[k] = 0xdeadbeefUL;
    for (i = 0; i < 3; i++)
        osrdn_tri_vertex(v, i, tex,
                         0x10UL + i, 0x20UL + i, 0x30UL + i, 0x40UL + i,
                         0x50UL + i, 0x60UL + i, 0x70UL + i);
    for (k = 0; k < SPAN; k++)
        printf("W %d %d %lx\n", tex, k, v[k]);
}

int main(void)
{
    printf("N %d %d %d\n", OSRDN_TRI_VERTEX_WORDS, OSRDN_TEX_VERTEX_WORDS, SPAN);
    run(0);
    run(1);
    /* out-of-range vertex numbers must write nothing at all */
    {
        unsigned long v[SPAN];
        int k, bad = 0;
        for (k = 0; k < SPAN; k++)
            v[k] = 0xdeadbeefUL;
        osrdn_tri_vertex(v, -1, 1, 1, 2, 3, 4, 5, 6, 7);
        osrdn_tri_vertex(v, 3, 1, 1, 2, 3, 4, 5, 6, 7);
        osrdn_tri_vertex(0, 0, 1, 1, 2, 3, 4, 5, 6, 7);
        for (k = 0; k < SPAN; k++)
            if (v[k] != 0xdeadbeefUL)
                bad++;
        printf("R %d\n", bad);
    }
    return 0;
}
'''

FIELD = [0x10, 0x20, 0x30, 0x40, 0x50, 0x60, 0x70]   # x, y, z, w, colour, s, t


def build_and_run(work, src, hdr=None):
    """M1t moved the slot layout into a MACRO in the header, so a mutation of
    the packing now has to be able to edit the header too.  Both files are
    copied into the work directory and it goes FIRST on the include path; when
    `hdr` is None the real header is copied unchanged."""
    open(os.path.join(work, 'h.c'), 'w').write(HARNESS)
    unit = os.path.join(work, 'OSRDNMesaTri.c')
    open(unit, 'w').write(src)
    if hdr is None:
        hdr = open(os.path.join(MESA, 'OSRDNMesaTri.h')).read()
    open(os.path.join(work, 'OSRDNMesaTri.h'), 'w').write(hdr)
    exe = os.path.join(work, 'h')
    # NOT -m32: this machine has no 32-bit crt, and the packing is indexed by
    # ELEMENT, so the word size cannot change which slot a value lands in.  What
    # is being tested is the arithmetic, and that is the same in both.
    r = subprocess.run(['gcc-12', '-std=gnu89', '-O0', '-Wall',
                        '-I', work,
                        '-I', MESA,
                        '-I', os.path.join(PROJ, 'OSRDNDisplay',
                                           'OSRDNDisplay_reloc.tproj'),
                        unit, os.path.join(work, 'h.c'),
                        os.path.join(MESA, 'OSRDNMesaVerify.c'),      # G4-2 B1: the unit asks the generated verifier
                        os.path.join(MESA, 'OSRDNMesaTime.c'),        # G5-0: and the instrument (off: no RDNMesaTime here)
                        '-o', exe],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr[-700:]
    r = subprocess.run([exe], capture_output=True, text=True, timeout=60)
    return r.stdout, None


def judge(out):
    p = []
    words, n5, n7, span, rest = {}, None, None, None, None
    for ln in out.split('\n'):
        f = ln.split()
        if not f:
            continue
        if f[0] == 'N':
            n5, n7, span = int(f[1]), int(f[2]), int(f[3])
        elif f[0] == 'W':
            words[(int(f[1]), int(f[2]))] = int(f[3], 16)
        elif f[0] == 'R':
            rest = int(f[1])
    if n5 != 5 or n7 != 7:
        p.append('the vertex widths are %s and %s, want 5 and 7' % (n5, n7))
        return p
    for tex in (0, 1):
        n = n7 if tex else n5
        for k in range(span):
            got = words.get((tex, k))
            i, off = k // n, k % n
            if i < 3 and off < n:
                want = FIELD[off] + i
            else:
                want = 0xdeadbeef        # past the three vertices
            if i >= 3:
                want = 0xdeadbeef
            if got != want:
                p.append('tex=%d word %d (vertex %d field %d) is %x, want %x'
                         % (tex, k, i, off, got, want))
    if rest != 0:
        p.append('a vertex number outside 0..2, or a null buffer, wrote %d words' % rest)
    return p


MUTATIONS = [
    # M1t: these two now live in the header's macros, because the hook's inline
    # path writes the same slots and the layout may only be spelled out ONCE.
    # The anchors moved with them -- and check-all caught that they had stopped
    # applying, which is the whole point of counting "anchor found 0 times" as a
    # failure rather than skipping it.
    ('the stride is the plain one even when textured', 'hdr',
     '((vtx) + (long)(i) * (long)((tex) ? OSRDN_TEX_VERTEX_WORDS                \\\n                                      : OSRDN_TRI_VERTEX_WORDS))',
     '((vtx) + (long)(i) * (long)OSRDN_TRI_VERTEX_WORDS)'),
    ('s and t are written whatever the shape', 'hdr',
     '        if (tex) {                                                            \\\n            (q)[5] = (s);                                                     \\\n            (q)[6] = (t);                                                     \\\n        }',
     '        (q)[5] = (s);                                                         \\\n        (q)[6] = (t);'),
    ('the range check goes', 'src',
     '    if (vtx == 0 || i < 0 || i >= TRI_VERTS)\n        return;', ''),
]


def main():
    if subprocess.run(['which', 'gcc-12'], capture_output=True).returncode != 0:
        print('  --   gcc-12 not present, skipped')
        return 0
    src = open(os.path.join(MESA, 'OSRDNMesaTri.c')).read()
    work = tempfile.mkdtemp(prefix='simpack')
    atexit.register(shutil.rmtree, work, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
    fails = 0
    out, err = build_and_run(work, src)
    if out is None:
        print('  FAIL the harness does not build: %s' % err)
        return 1
    bad = judge(out)
    for s in bad[:6]:
        print('  FAIL %s' % s)
    if bad:
        fails += 1
    else:
        print('  ok   every word of both shapes is the field it should be, and '
              'nothing else was touched')
    hdr0 = open(os.path.join(MESA, 'OSRDNMesaTri.h')).read()
    for label, which, old, new in MUTATIONS:
        text = hdr0 if which == 'hdr' else src
        if text.count(old) != 1:
            print('  FAIL mutation %-46s anchor found %d times in the %s'
                  % (label, text.count(old), 'header' if which == 'hdr' else 'unit'))
            fails += 1
            continue
        mutated = text.replace(old, new, 1)
        if which == 'hdr':
            o, e = build_and_run(work, src, hdr=mutated)
        else:
            o, e = build_and_run(work, mutated)
        caught = (o is None) or bool(judge(o))
        print('  %-4s mutation %-46s %s' % ('ok' if caught else 'FAIL', label,
                                            'caught' if caught else 'NOT CAUGHT'))
        if not caught:
            fails += 1
    print('sim_pack: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
