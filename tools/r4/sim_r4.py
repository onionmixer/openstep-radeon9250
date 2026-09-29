#!/usr/bin/env python3
"""Run osrdn_engine.m against a fake 2D engine (tools/r4/sim/world4.c), then
every mutation (docs/R4_ENGINE_PLAN.md 12-4 #2).

  sim_r4.py        the baseline must PASS and every mutation must FAIL, in this run

WHAT THIS PROVES: that the driver does what OUR MODEL of the engine expects --
the model was written from the same references as the driver, so a rule both
have wrong passes here.  The hardware is judged on the machine only.

The fake engine is pixel by pixel (a row-buffered model would let a wrong X
direction pass everywhere, docs 13 #2 #9).  What the mutations cannot reach is
said next to them.
"""

import shutil
import atexit
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
TPROJ = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj')
ENGINE = os.path.join(TPROJ, 'osrdn_engine.m')
SNAP = os.path.join(TPROJ, 'osrdn_snap.m')
WORLD = os.path.join(HERE, 'sim', 'world4.c')
INC = os.path.join(PROJ, 'tools', 'r2b', 'sim', 'include')
LIBC32 = '/usr/lib32/libc.so.6'
LD32 = '/lib/ld-linux.so.2'

MUTATIONS = [
    ('X direction bit inverted',
     '    ltr = (c->dx < c->sx);', '    ltr = !(c->dx < c->sx);'),
    ('Y direction bit inverted',
     '    ttb = (c->dy < c->sy);', '    ttb = !(c->dy < c->sy);'),
    ('the start does not move for a right-to-left copy',
     '        sx += c->w - 1UL;\n        dx += c->w - 1UL;\n', ''),
    ('the default scissor is not set (the BIOS left it small)',
     '    rdnMmioWrite32(base, E_DEFAULT_SC_BR, E_SC_MAX);\n', ''),
    ('AUX_CLIP_DIS dropped (an aux scissor left on clips everything)',
     '#define E_GMC_FILL              0x30f036d2UL', '#define E_GMC_FILL              0x10f036d2UL'),
    ('the blit reads the default pitch register (decoy)',
     '#define E_GMC_BLIT              0x32cc36f3UL', '#define E_GMC_BLIT              0x32cc36f2UL'),
    ('only the RB2D cache is flushed',
     '    rdnMmioWrite32(base, E_RB3D_DSTCACHE_CTLSTAT, e->dc3Pre | E_DC_FLUSH_ALL);\n', ''),
    ('only the RB3D cache is flushed',
     '    rdnMmioWrite32(base, E_RB2D_DSTCACHE_CTLSTAT, e->dc2Pre | E_DC_FLUSH_ALL);\n', ''),
    ('the flush is a bare store',
     '    rdnMmioWrite32(base, E_RB2D_DSTCACHE_CTLSTAT, e->dc2Pre | E_DC_FLUSH_ALL);',
     '    rdnMmioWrite32(base, E_RB2D_DSTCACHE_CTLSTAT, E_DC_FLUSH_ALL);'),
    ('no FIFO wait before the batch',
     '    if (!engWait(base, W_FIFO, need, E_FIFO_US, &e->wFifo))\n        return ENG_RC_PRE_TIMEOUT;                          /* nothing written */\n',
     ''),
    ('idle does not wait for the FIFO to drain',
     '        if ((v & E_FIFO_MASK) != E_FIFO_DEPTH)\n            return 0;\n        return (v & E_RBBM_ACTIVE) == 0UL;',
     '        return (v & E_RBBM_ACTIVE) == 0UL;'),
    ('the result is read before the engine is idle',
     '    if (!engWait(base, W_IDLE, 0, E_IDLE_US, &e->wIdle))\n        return engLatch(e, base);\n', ''),
    ('a wait loses its turn bound (a frozen clock never ends it)',
     '        turns++;\n        if (turns >= maxTurns)\n            break;\n', ''),
    ('after an idle timeout the driver carries on',
     '    if (!engWait(base, W_IDLE, 0, E_IDLE_US, &e->wIdle))\n        return engLatch(e, base);',
     '    if (!engWait(base, W_IDLE, 0, E_IDLE_US, &e->wIdle))\n        (void)engLatch(e, base);'),
    ('a latched engine is used again',
     '    else if (e->latched)\n        (void)engRefuse(e, ENG_WHY_LATCHED, 0);\n', ''),
    ('DEFAULT_OFFSET is not put back',
     '    rdnMmioWrite32(base, E_DEFAULT_OFFSET, e->defaultSaved);\n', ''),
    ('RB3D_CNTL is not cleared before a fill (the machine left 0x1800)',
     '    rdnMmioWrite32(base, E_RB3D_CNTL, 0UL);                             /* no 3D (docs 17) */\n    rdnMmioWrite32(base, E_DEFAULT_OFFSET, decoy(e));\n    rdnMmioWrite32(base, E_DST_PITCH_OFFSET,',
     '    rdnMmioWrite32(base, E_DEFAULT_OFFSET, decoy(e));\n    rdnMmioWrite32(base, E_DST_PITCH_OFFSET,'),
    ('the reach gate is dropped',
     '    if (mem < need)\n        return engRefuse(e, ENG_WHY_REACH, mem);\n', ''),
    ('the judge ignores the pre-operation value',
     '            if (v == preValue(op, arg, off))\n                e->notBad++;', '            e->notBad += 0;'),
    ('the blit source is judged after the copy, not before',
     '    *want = preValue(op, arg, c->srcOff', '    *want = 0UL * preValue(op, arg, c->srcOff'),
    ('a fill with the marker colour is allowed (it could not fail)',
     '    else if (op == ENG_OP_FILL && arg == E_MARK)\n        (void)engRefuse(e, ENG_WHY_MARK_COLOUR, arg);\n', ''),
    ('f64 watches the surface, not the rectangle',
     '        return ENG_S0_OFF + E_FILL_Y * ENG_S0_W * 4UL + E_FILL_X * 4UL;', '        return ENG_S0_OFF;'),
    ('no idle check after the flushes',
     '    if (!engWait(base, W_IDLE, 0, E_IDLE_US, &e->wIdle2))\n        return engLatch(e, base);\n', ''),
    # R4c UBLIT (docs/R4C_VMAP_PLAN.md 11-7)
    ('UBLIT indexes the cases by its seed',
     '    if (op == ENG_OP_UBLIT)\n        return &engCases[0];\n', ''),
    ('a reused UBLIT seed is allowed (a leftover could pass)',
     '    else if (op == ENG_OP_UBLIT && e->seedUsed && arg == e->lastSeed)\n        (void)engRefuse(e, ENG_WHY_SEED, arg);\n', ''),
    ('UBLIT does not check the whole block before writing',
     '        if (bad != 0UL)\n            return engRefuse(e, ENG_WHY_USER, bad);\n', ''),
    ('the UBLIT seed is not checked', '    if ((seed & ENG_SEED_LOW_MASK) != 0UL)\n        return 0;\n    return top',
     '    return 1;\n    return top'),
    ('UBLIT expects the pattern in S1',
     '    if (op == ENG_OP_UBLIT && inSurface(off, ENG_S1_OFF, S1P, ENG_S1_H, &x, &y))\n        return ENG_USER_VALUE(arg, off);\n', ''),
    ('the PLL peek does not put the index back',
     '    rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX, (unsigned char)(saved & 0xffUL));\n', ''),
]
# Not reachable here, and why: the read-back fence (the world's alias is plain
# host memory, so a posted write cannot be modelled) -- tools/r4/check_r4_src.py
# pins it in the text; the engine never logs or sleeps -- check_r4_src.py and
# the world's IOSleep counter.


def build(engine, snap, out):
    cmd = ['gcc-12', '-m32', '-std=gnu89', '-O0', '-Wall', '-Wno-deprecated', '-nostdinc',
           '-I', INC, '-I', TPROJ, '-x', 'c', engine, snap, WORLD,
           '-x', 'none', '-nostdlib', '-nostartfiles', LIBC32, '-Wl,-dynamic-linker,' + LD32, '-o', out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0, r.stderr


def run(exe):
    try:
        r = subprocess.run([exe], capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return 124, 'world4: FAIL (it never came back: a wait with no bound)\n'
    return r.returncode, r.stdout + r.stderr


def main():
    if not os.path.exists(LIBC32):
        print('  --   %s not present, engine simulation skipped' % LIBC32)
        return 0
    work = tempfile.mkdtemp(prefix='simr4.', dir=os.environ.get('TMPDIR'))
    atexit.register(shutil.rmtree, work, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
    failures = 0
    exe = os.path.join(work, 'base')
    ok, err = build(ENGINE, SNAP, exe)
    if not ok:
        print('  FAIL baseline does not build\n' + err[-1500:])
        return 1
    rc, out = run(exe)
    if rc == 0 and 'world4: PASS' in out:
        print('  ok   baseline: %d world checks' % sum(1 for l in out.splitlines() if l.strip().startswith('ok')))
    else:
        print('  FAIL baseline\n' + out)
        failures += 1
    etext = open(ENGINE).read()
    stext = open(SNAP).read()
    for n, (label, old, new) in enumerate(MUTATIONS):
        src = SNAP if 'REG_CLOCK_CNTL_INDEX' in old else ENGINE
        text = stext if src == SNAP else etext
        if text.count(old) != 1:
            print('  FAIL mutation %-60s anchor found %d times' % (label, text.count(old)))
            failures += 1
            continue
        path = os.path.join(work, 'mut%d.m' % n)
        open(path, 'w').write(text.replace(old, new))
        exe = os.path.join(work, 'mut%d' % n)
        ok, err = build(path if src == ENGINE else ENGINE, path if src == SNAP else SNAP, exe)
        if not ok:
            print('  FAIL mutation %-60s does not build\n%s' % (label, err[-400:]))
            failures += 1
            continue
        rc, out = run(exe)
        # a signal (negative rc) is caught too: an index out of the case table
        # can fault before the world prints anything
        caught = (rc != 0 and 'world4: FAIL' in out) or rc < 0
        if rc < 0 and 'world4: FAIL' not in out:
            out += '\nFAIL killed by signal %d' % -rc
        first = [l.strip() for l in out.splitlines() if l.strip().startswith('FAIL')]
        print('  %-4s mutation %-60s %s' % ('ok' if caught else 'FAIL', label,
                                            (first[0][:70] if first else 'caught') if caught else 'NOT CAUGHT'))
        failures += 0 if caught else 1
    print('sim_r4: %s' % ('PASS' if not failures else 'FAIL (%d)' % failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
