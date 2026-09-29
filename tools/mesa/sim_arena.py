#!/usr/bin/env python3
"""The texture arena, RUN on the host, block by block (G4-1b, docs/G4_GLQUAKE_PLAN.md 5 T1).

  sim_arena.py

OSRDNMesaTexArena.c is plain C89 with no Mesa and no libc, so it is compiled here
with gcc-12 -m32 against a harness that drives it and prints every answer; this
script computes what each answer must be with its own first-fit model and holds
the two against each other.  Then each mutation of the unit is compiled the same
way, and must be caught.
"""

import atexit
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
MESA = os.path.join(PROJ, 'mesa')
ALIGN = 32
# G5-4: read from the header, not repeated here -- a number kept in two places drifts
BLOCKS = int(re.search(r'#define\s+OSRDN_TEXARENA_BLOCKS\s+(\d+)', open(os.path.join(MESA, 'OSRDNMesaTexArena.h')).read()).group(1))

# (op, args): the script the harness runs.  alloc -> "A bytes epoch", free ->
# "F origin epoch", set -> "S origin bytes epoch", drop -> "D", stat -> "T".
SCRIPT = [
    ('T',),                             # not live: 0 0 0
    ('A', 100, 1),                      # not live: refused
    ('S', 0x780000, 4096, 1),
    ('A', 100, 1),                      # 0x780000, rounded to 128
    ('A', 100, 1),                      # 0x780080
    ('A', 32, 1),                       # 0x780100
    ('A', 100, 2),                      # old epoch: refused
    ('A', 0, 1),                        # zero bytes: refused
    ('F', 0x780080, 1),                 # gap in the middle
    ('A', 96, 1),                       # first fit: the gap
    ('A', 64, 1),                       # the gap is full (128 - 96 = 32 < 64): after the last
    ('F', 0x780080, 2),                 # old epoch: refused, block stays
    ('F', 0x780080, 1),                 # ours: gone
    ('F', 0x780080, 1),                 # already gone: refused
    ('F', 0x700000, 1),                 # never ours
    ('T',),
    ('A', 4096, 1),                     # does not fit (arena holds 4096 total, some used)
    ('A', 3000, 1),                     # fits after the last (0x780160.. needs 3008 within 4096?)
    ('T',),
    ('S', 0x780000, 4096, 1),           # the same arena: keeps everything
    ('T',),
    ('S', 0x780000, 4096, 2),           # a new epoch: empty
    ('T',),
    ('A', 4097, 2),                     # too big for the whole arena
    ('A', 4096, 2),                     # exactly the arena
    ('A', 32, 2),                       # full
    ('D',),
    ('T',),
    ('A', 32, 2),                       # dropped: refused
    ('S', 0x100000, 0x2000000, 7),      # the real arena size
] + [('A', 32, 7)] * (BLOCKS + 2) + [   # the table fills at BLOCKS; the two beyond are refused
    ('T',),
    ('F', 0x100000 + 32 * 5, 7),
    ('A', 32, 7),                       # the freed slot, first fit
    ('T',),
    # G4-4 K5: the chain layout, held to the oracle's texture_bytes (the kernel's cpR7TextureBytes)
    ('C', 8, 8, 1), ('C', 8, 8, 4), ('C', 128, 128, 8), ('C', 128, 128, 5), ('C', 256, 64, 9),
    ('C', 8, 512, 10), ('C', 512, 512, 10), ('C', 2048, 2048, 12), ('C', 64, 64, 8),
    ('C', 12, 12, 1), ('C', 64, 64, 0), ('C', 4096, 4096, 1), ('C', 1, 1, 1), ('C', 1, 1, 2),
]

HARNESS = r'''
int printf(const char *, ...);
#include "OSRDNMesaTexArena.h"

int main(void)
{
    unsigned long o, c, u, b;
    int r;
%(body)s
    return 0;
}
'''


def harness():
    lines = []
    for op in SCRIPT:
        if op[0] == 'T':
            lines.append('    osrdn_texarena_stat(&c, &u, &b); printf("T %lu %lu %lu\\n", c, u, b);')
        elif op[0] == 'A':
            lines.append('    r = osrdn_texarena_alloc(%dUL, %dUL, &o); printf("A %%d %%lu\\n", r, o);' % (op[1], op[2]))
        elif op[0] == 'F':
            lines.append('    r = osrdn_texarena_free(%dUL, %dUL); printf("F %%d\\n", r);' % (op[1], op[2]))
        elif op[0] == 'S':
            lines.append('    osrdn_texarena_set(%dUL, %dUL, %dUL); printf("S %%lu\\n", osrdn_texarena_epoch());' % (op[1], op[2], op[3]))
        elif op[0] == 'D':
            lines.append('    osrdn_texarena_drop(); printf("D %lu\\n", osrdn_texarena_epoch());')
        elif op[0] == 'C':
            lines.append('    { unsigned long offs[OSRDN_TEXARENA_MAX_LEVELS]; unsigned long i; '
                         'r = osrdn_texarena_chain(%dUL, %dUL, %dUL, offs, &b); printf("C %%d", r); '
                         'if (r) { printf(" %%lu", b); for (i = 0; i < %dUL; i++) printf(" %%lu", offs[i]); } printf("\\n"); }'
                         % (op[1], op[2], op[3], op[3]))
    return HARNESS % dict(body='\n'.join(lines))


def chain_model(w, h, levels):
    """the r200 layout (r200_texstate.c 272, 282-285), as verify_oracle.texture_bytes counts it"""
    import importlib.util
    spec = importlib.util.spec_from_file_location('vo', os.path.join(os.path.dirname(MESA), 'tools', 'r7', 'verify_oracle.py'))
    vo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vo)
    def log2(v):
        return v.bit_length() - 1 if v and (v & (v - 1)) == 0 else None
    lw, lh = log2(w), log2(h)
    if lw is None or lh is None or lw > 11 or lh > 11 or levels < 1 or levels > 16 or levels > max(lw, lh) + 1:
        return 'C 0'
    tfmt = vo.TXFORMAT_ARGB8888 | (lw << vo.TXFORMAT_W_SHIFT) | (lh << vo.TXFORMAT_H_SHIFT)
    total = vo.texture_bytes(tfmt, (levels - 1) << vo.TXFILTER_MIP_SHIFT)
    offs, at = [], 0
    for i in range(levels):
        cw, ch = max(1, w >> i), max(1, h >> i)
        at = (at + 31) & ~31
        offs.append(at)
        at += ((cw * 4 + 31) & ~31) * ch
    assert at == total, (w, h, levels, at, total)
    return 'C 1 %d %s' % (total, ' '.join(str(o) for o in offs))


def model():
    """The same script, run through an independent model; the lines it must print."""
    live = False
    origin = bytes_ = epoch = 0
    blocks = []                         # sorted (origin, bytes)
    out = []
    for op in SCRIPT:
        if op[0] == 'C':
            out.append(chain_model(op[1], op[2], op[3]))
            continue
        if op[0] == 'T':
            out.append('T %d %d %d' % (len(blocks), sum(b for _, b in blocks), bytes_ if live else 0))
        elif op[0] == 'S':
            if not (live and (origin, bytes_, epoch) == op[1:]):
                blocks = []
                origin, bytes_, epoch = op[1:]
                live = bytes_ != 0
            out.append('S %d' % epoch)
        elif op[0] == 'D':
            blocks = []
            live = False
            origin = bytes_ = epoch = 0
            out.append('D 0')
        elif op[0] == 'F':
            o, e = op[1], op[2]
            hit = live and e == epoch and any(bo == o for bo, _ in blocks)
            if hit:
                blocks = [(bo, bb) for bo, bb in blocks if bo != o]
            out.append('F %d' % (1 if hit else 0))
        elif op[0] == 'A':
            n, e = op[1], op[2]
            want = -(-n // ALIGN) * ALIGN
            got = 0
            if live and n and e == epoch and len(blocks) < BLOCKS:
                # every gap, in order: before each block, then after the last
                at = origin
                for bo, bb in blocks:
                    if bo - at >= want:
                        break
                    at = bo + bb
                if at + want <= origin + bytes_:
                    got = at
                    blocks.append((at, want))
                    blocks.sort()
            out.append('A %d %d' % (1 if got else 0, got))
    return out


def build_and_run(work, src):
    open(os.path.join(work, 'OSRDNMesaTexArena.c'), 'w').write(src)
    open(os.path.join(work, 'h.c'), 'w').write(harness())
    shutil.copy(os.path.join(MESA, 'OSRDNMesaTexArena.h'), work)
    exe = os.path.join(work, 'h')
    r = subprocess.run(['gcc-12', '-std=gnu89', '-Wall', '-Werror', '-O0', '-I', work,
                        os.path.join(work, 'h.c'), os.path.join(work, 'OSRDNMesaTexArena.c'), '-o', exe],
                       capture_output=True, text=True)
    if r.returncode:
        return None, r.stderr.strip().splitlines()[-1] if r.stderr.strip() else 'gcc failed'
    r = subprocess.run([exe], capture_output=True, text=True, timeout=30)
    return r.stdout.splitlines(), None


def judge(got):
    want = model()
    bad = []
    if len(got) != len(want):
        bad.append('%d lines from the unit, %d from the model' % (len(got), len(want)))
    for i, (g, w) in enumerate(zip(got, want)):
        if g != w:
            bad.append('step %d %s: unit says %r, model says %r' % (i, SCRIPT[i], g, w))
    return bad


MUTATIONS = [
    ('the alignment is dropped',
     'want = (bytes + OSRDN_TEXARENA_ALIGN - 1UL) & ~(OSRDN_TEXARENA_ALIGN - 1UL);', 'want = bytes;'),
    ('the epoch is not checked on alloc', 'bytes == 0UL || epoch != arenaEpoch)', 'bytes == 0UL)'),
    ('the epoch is not checked on free', 'if (!arenaLive || epoch != arenaEpoch)\n        return 0;\n    for',
     'if (!arenaLive)\n        return 0;\n    for'),
    ('a gap is never reused (always after the last)',
     'if (blocks[i].origin >= at && blocks[i].origin - at >= want)\n            break;', ''),
    ('the end of the arena is not checked', 'if (arenaBytes - (at - arenaOrigin) < want)\n        return 0;', ''),
    ('the block table has no limit', 'if (blockCount >= (unsigned long)OSRDN_TEXARENA_BLOCKS)\n        return 0;', ''),
    ('the blocks are not kept sorted', 'if (blocks[i - 1UL].origin < at)\n            break;', 'break;'),
    ('a free forgets to close the hole', 'for (; i + 1UL < blockCount; i++)\n                blocks[i] = blocks[i + 1UL];', ''),
    ('a new epoch keeps the old blocks', 'epoch == arenaEpoch)\n        return;', 'epoch == epoch)\n        return;'),
    ('stat counts the blocks it lost', 'if (count != 0) *count = blockCount;', 'if (count != 0) *count = blockCount + 1UL;'),
    # G4-4 K5: the chain layout
    # (no mutation for the level alignment `total = (total + 31UL) & ~31UL`: with every row already a
    #  multiple of 32 bytes it can never change `total`, so dropping it is unobservable -- it is kept
    #  because the kernel's cpR7TextureBytes and the oracle keep it, and a check that cannot fail is
    #  not listed as one)
    ('a level\'s rows are not rounded to 32', '        row = (cw * 4UL + 31UL) & ~31UL;', '        row = cw * 4UL;'),
    ('more levels than the base can halve into', '    if (levels > (lw > lh ? lw : lh) + 1UL)\n        return 0;', ''),
    ('a level past the last halving is not clamped to 1', '        cw = (lw > i) ? (1UL << (lw - i)) : 1UL;', '        cw = (1UL << lw) >> i;'),
]


def main():
    if subprocess.run(['which', 'gcc-12'], capture_output=True).returncode != 0:
        print('  --   gcc-12 not present, skipped')
        return 0
    src = open(os.path.join(MESA, 'OSRDNMesaTexArena.c')).read()
    work = tempfile.mkdtemp(prefix='simarena')
    atexit.register(shutil.rmtree, work, True)
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
        print('  ok   %d steps: every answer of the unit is the model\'s' % len(SCRIPT))
    for label, old, new in MUTATIONS:
        if src.count(old) != 1:
            print('  FAIL mutation %-46s anchor found %d times' % (label, src.count(old)))
            fails += 1
            continue
        o, e = build_and_run(work, src.replace(old, new, 1))
        caught = (o is None) or bool(judge(o))
        print('  %-4s mutation %-46s %s' % ('ok' if caught else 'FAIL', label, 'caught' if caught else 'NOT CAUGHT'))
        if not caught:
            fails += 1
    print('sim_arena: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
