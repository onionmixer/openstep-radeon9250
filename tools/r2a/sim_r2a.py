#!/usr/bin/env python3
"""Run the R2a probe's own source on the host against fake worlds (docs/R1C_R2A_IMPL_PLAN.md section 2-7).

  sim_r2a.py           build, run every world and mutation, exit 1 on any failure

RDNR2aProbe.m is compiled unchanged as 32-bit code with sim/simworld2a.c in
place of RDNR2aMMIO.m.  The fake mapping is PROT_NONE, so every MMIO access
must come through the three helpers, where simworld2a.c models
CLOCK_CNTL_INDEX/CLOCK_CNTL_DATA and refuses what the plan forbids.

Each world's R2a log is judged by parse_r2a.py against an R1 log that R1's
own probe (tools/r1/sim_r1.py build, tools/r1/sim/simworld.c) wrote for the
same world, so the R1 comparison gate sees two real probe outputs.  R1's
worlds are all run again (regression) with R1's expectations.

Mutations are copies of the probe with one forbidden change each; each names
the world that must catch it and what that world must report, and every one
must be caught in this same invocation.

What this cannot show: how RV280 latches PLL_WR_EN, whether it honours byte
lanes on CLOCK_CNTL_INDEX, what its reads change, what cc 2.7.2.1 generates
(check_reloc.py covers the helpers' store widths), or the real kernel's
splhigh.
"""

import shutil
import atexit
import hashlib
import importlib.util
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
TPROJ = os.path.join(PROJ, 'probe', 'RDNR2aProbe', 'RDNR2aProbe_reloc.tproj')
PROBE = os.path.join(TPROJ, 'RDNR2aProbe.m')
MMIO_H = os.path.join(TPROJ, 'RDNR2aMMIO.h')
SIMDIR = os.path.join(HERE, 'sim')
WORLD_C = os.path.join(SIMDIR, 'simworld2a.c')


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


s1 = _load('sim_r1', os.path.join(PROJ, 'tools', 'r1', 'sim_r1.py'))
p2 = _load('parse_r2a', os.path.join(HERE, 'parse_r2a.py'))

BUILD = s1.BUILD
RUNID = 4242
R1_RUNID = 4241
PLL_WORLD = ['clockindex 303', 'pll 3 c', 'pll 7 600ad', 'pll 8 3']
R2A_DIRECTIVE = re.compile(r'^(clockindex|pll|bytelanes|readback6|disturb)\b')


# ---- shim prototypes -------------------------------------------------------

def check_shims():
    bad = s1.check_shims()
    real = open(os.path.join(s1.TARGET_HEADERS, 'kernserv', 'i386', 'spl.h'), errors='replace').read()
    shim = open(os.path.join(SIMDIR, 'include', 'kernserv', 'machine', 'spl.h')).read()
    for n in ('splhigh', 'splx'):
        a, b = s1.prototype(real, n), s1.prototype(shim, n)
        ok = a is not None and a == b
        print('  %-4s %-26s target %s  shim %s' % ('ok' if ok else 'FAIL', n, a, b))
        bad += 0 if ok else 1
    # the simulator's helpers must have the header's prototypes (vm_address_t
    # is unsigned int: mach/i386/vm_types.h natural_t, as the R1 shim has it)
    hdr = open(MMIO_H).read()
    world = open(WORLD_C).read()
    for n in ('rdnMmioRead32', 'rdnMmioWrite8', 'rdnMmioWrite32'):
        a = s1.prototype(hdr, n)
        b = s1.prototype(world, n)
        if a is not None:
            a = (a[0], [p.replace('vm_address_t', 'unsigned int') for p in a[1]])
        ok = a is not None and a == b
        print('  %-4s %-26s header %s  sim %s' % ('ok' if ok else 'FAIL', n, a, b))
        bad += 0 if ok else 1
    return bad


# ---- build and run ---------------------------------------------------------

def build(src, out, stamp=BUILD, tproj=TPROJ):
    cmd = ['gcc-12', '-m32', '-std=gnu89', '-O0', '-fno-pie', '-no-pie', '-ffreestanding',
           '-fno-builtin', '-nostdinc', '-I', os.path.join(SIMDIR, 'include'), '-I', tproj,
           '-Wall', '-Werror', '-Wno-deprecated', '-DR2A_BUILD=0x%08x' % stamp,
           '-x', 'c', src, WORLD_C,
           '-x', 'none', '-nostdlib', '-nostartfiles', s1.LIBC32,
           '-Wl,-dynamic-linker,' + s1.LD32, '-o', out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0, r.stderr


def stats(stderr):
    m = re.search(r'SIM-STATS maps=(\d+) sleep_ms=(\d+) delay_us=(\d+) delay_calls=(\d+) write8=(\d+) '
                  r'write32=(\d+) groups=(\d+) data_reads=(\d+) final_index=([0-9a-f]{8})', stderr)
    if not m:
        return None
    k = ('maps', 'sleep_ms', 'delay_us', 'delay_calls', 'w8', 'w32', 'groups', 'data')
    d = dict(zip(k, (int(x) for x in m.groups()[:8])))
    d['final'] = m.group(9)
    return d


def r1_world(sc):
    """The same world for R1's probe: no PLL directives, and CLOCK_CNTL_INDEX
    as a plain register holding the world's starting index."""
    lines = sc.splitlines()
    ci = [l.split()[1] for l in lines if l.startswith('clockindex ')]
    out = [l.replace('runid %d' % RUNID, 'runid %d' % R1_RUNID) for l in lines if not R2A_DIRECTIVE.match(l)]
    if ci:
        out.append('mmio 8 %s' % ci[-1])
    return '\n'.join(out) + '\n'


def world(runid=RUNID, **kw):
    directives = list(kw.pop('directives', ()))
    pll = kw.pop('pll', PLL_WORLD)
    return s1.world(runid=runid, directives=list(pll) + directives, **kw)


# ---- worlds ----------------------------------------------------------------

# expectations: verdict 'PASS' | 'FAIL:<sub>' | 'REPLAN:<sub>'; maps, w8, w32,
# groups (splhigh count), data, final (hex8); log / nolog substrings
def worlds():
    good = dict(maps=1, w8=20, w32=0, groups=10, data=10, final='00000303')
    w = [
        ('good', world(), 'PASS', dict(good, log=['pll k=1 idx=03 name=PPLL_REF_DIV p=00000303 c=00000303 val=0000000c',
                                               'pll k=3 idx=07 name=PPLL_DIV_3 p=00000303 c=00000307 val=000600ad',
                                               'pllend groups=10'])),
        ('byte lanes ignored', world(directives=['bytelanes ignore']), 'FAIL:SAFE (index back at p)',
         dict(maps=1, w8=1, w32=1, groups=1, data=0, final='00000303',
              log=['pllabort k=0 why=upper p=00000303 c=00000002', 'a=00000303', 'stop reason=pll-index-disturbed'],
              nolog=['pll k=0'])),
        ('byte lanes and 32-bit store ignored', world(directives=['bytelanes ignore-all']), 'FAIL:UNSAFE',
         dict(maps=1, w8=1, w32=1, groups=1, data=0, final='00000002', log=['why=upper', 'a=00000002'])),
        ('index changed at the store', world(directives=['disturb 2 afterstore 00000204']), 'FAIL:aborted (upper)',
         dict(maps=1, w8=5, w32=1, groups=3, data=2, final='00000303',
              log=['pllabort k=2 why=upper p=00000303 c=00000204', 'a=00000303'])),
        ('index changed around the data read', world(directives=['disturb 4 afterdata 00000208']),
         'FAIL:aborted (after-data)',
         dict(maps=1, w8=9, w32=1, groups=5, data=5, final='00000303',
              log=['pllabort k=4 why=after-data p=00000303 c=00000308 d=00000208', 'a=00000303'])),
        ('owner changes bits 8-9 between groups', world(directives=['disturb 5 before 00000203']),
         'FAIL:another writer',
         dict(maps=1, w8=20, w32=0, groups=10, data=10, final='00000203',
              log=['pll k=5 idx=09 name=HTOTAL_CNTL p=00000203 c=00000209', 'pllend groups=10'])),
        ('owner changes bits 10-31 between groups', world(directives=['disturb 3 before 00100303']),
         'FAIL:another writer', dict(maps=1, w8=20, w32=0, groups=10, data=10, final='00100303')),
        ('bits 10-31 change at the store', world(directives=['disturb 3 afterstore 00100307']),
         'FAIL:aborted (upper)',
         dict(maps=1, w8=7, w32=1, groups=4, data=3, final='00000303', log=['pllabort k=3 why=upper'])),
        ('low byte changes at the store', world(directives=['disturb 1 afterstore 00000305']),
         'FAIL:aborted (low)',
         dict(maps=1, w8=3, w32=1, groups=2, data=1, final='00000303', log=['pllabort k=1 why=low', 'c=00000305'])),
        ('index changed after the restore at k=9', world(directives=['disturb 9 afterrestore 00000302']),
         'FAIL:aborted (restore)',
         dict(maps=1, w8=20, w32=1, groups=10, data=10, final='00000303',
              log=['pll k=8 ', 'pllabort k=9 why=restore p=00000303 c=0000032d', 'e=00000302 a=00000303',
                   'pllend groups=9'], nolog=['pll k=9 '])),
        ('reserved bit 6 reads back as 1', world(directives=['readback6']), 'FAIL:SAFE (index back at p)',
         # the 32-bit store writes back P as read, bit 6 included
         dict(maps=1, w8=1, w32=1, groups=1, data=0, final='00000343',
              log=['pllabort k=0 why=low p=00000343 c=00000342', 'a=00000343'])),
        ('write enable set at the start', world(pll=['clockindex 383', 'pll 3 c']), 'FAIL:busy',
         dict(maps=1, w8=0, w32=0, groups=1, data=0, final='00000383',
              log=['pllstart p0=00000383', 'pllbusy k=0 p=00000383', 'stop reason=pll-index-busy', 'pllend groups=0'])),
        ('write enable set before k=4', world(directives=['disturb 4 before 00000383']), 'FAIL:busy',
         dict(maps=1, w8=8, w32=0, groups=5, data=4, final='00000383',
              log=['pllbusy k=4 p=00000383', 'pllend groups=4'])),
        ('static scan', world(scan=False), 'FAIL:VLINE static',
         dict(maps=1, w8=0, w32=0, groups=0, data=0, final='00000303', nolog=['pllstart', 'reg name='])),
        ('map fails', world(mapfail=True), 'FAIL:map-failed',
         dict(maps=1, w8=0, w32=0, groups=0, data=0, nolog=['pllstart'])),
        ('unmap fails', world(unmapfail=True), 'FAIL:unmap-failed',
         dict(maps=1, w8=20, w32=0, groups=10, data=10, final='00000303', log=['pllend groups=10'])),
        ('no card', world(cards=()), 'FAIL:expected exactly one RV280',
         dict(maps=0, w8=0, w32=0, groups=0, log=['rv280-count-0'])),
        ('two cards', world(cards=((3, 13, 0), (3, 14, 0))), 'FAIL:expected exactly one RV280',
         dict(maps=0, w8=0, w32=0, groups=0, log=['rv280-count-2'])),
        ('bridge VGA forwarding recorded', world(), 'PASS', dict(good, report=['VGA forwarding 0'])),
        ('undefined CRTC_EXT_CNTL bit differs from R1', world(directives=['mmio 54 02000000']),
         'REPLAN:only undefined bits', dict(good, r1_mmio={0x54: 0})),
        ('documented CRTC_GEN_CNTL bit differs from R1', world(directives=['mmio 50 02000000']),
         'FAIL:CRTC_GEN_CNTL', dict(good, r1_mmio={0x50: 0})),
    ]
    # R1's worlds (regression): R1's verdict and log expectations on the R2a probe
    for label, sc, want_pass, want_fail, want_text, want_map, want_log in s1.scenarios():
        sc2 = sc.replace('runid 4242', 'runid %d' % RUNID)
        lines = sc2.splitlines()
        sc2 = '\n'.join(lines[:1] + PLL_WORLD + lines[1:]) + '\n'
        exp = dict(maps=1 if want_map else 0, log=[want_log] if want_log else [],
                   report=[want_text] if want_text else [])
        w.append(('R1: ' + label, sc2, 'PASS' if want_pass else 'FAIL:' + want_fail, exp))
    return w


def run_world(exe, r1exe, label, sc, verdict, exp):
    """Return the list of reasons this world's run does not meet its expectations."""
    why = []
    r = subprocess.run([exe], input=sc, capture_output=True, text=True, timeout=60)
    st = stats(r.stderr)
    if r.returncode != 0 or st is None:
        return ['sim rc=%d %s' % (r.returncode, r.stderr.strip()[:160])]
    r1sc = r1_world(sc)
    for off, val in sorted(exp.get('r1_mmio', {}).items()):
        r1sc += 'mmio %x %x\n' % (off, val)
    r1 = subprocess.run([r1exe], input=r1sc, capture_output=True, text=True, timeout=60)
    if r1.returncode != 0:
        return ['R1 sim rc=%d %s' % (r1.returncode, r1.stderr.strip()[:160])]
    out = r.stdout
    report, fail, replan, rec = p2.judge(out, str(RUNID), '%08x' % BUILD, r1.stdout, str(R1_RUNID))
    kind, _, sub = verdict.partition(':')
    if kind == 'PASS' and (fail or replan):
        why.append('judge: %s' % ((fail or replan)[0]))
    if kind == 'FAIL' and not any(sub in f for f in fail):
        why.append('judge did not name %r: %s' % (sub, fail[:3]))
    if kind == 'REPLAN' and (fail or not any(sub in x for x in replan)):
        why.append('judge not REPLAN %r: fail=%s replan=%s' % (sub, fail[:2], replan[:2]))
    for k in ('maps', 'w8', 'w32', 'groups', 'data', 'final'):
        if k in exp and st[k] != exp[k]:
            why.append('%s=%s, want %s' % (k, st[k], exp[k]))
    for s in exp.get('log', []):
        if s not in out:
            why.append('log lacks %r' % s)
    for s in exp.get('nolog', []):
        if s in out:
            why.append('log has %r' % s)
    for s in exp.get('report', []):
        if not any(s in o for o in report):
            why.append('report lacks %r' % s)
    if any('kept reading' in f for f in fail):
        why.append('probe read on after a static VLINE')
    # pacing as R1: 20 ms per line, 60 ms frame window; 7 x 2 ms live gaps
    nlines = len(re.findall(r'RDN-R2A %d ' % RUNID, out))
    pace = 60 if 'frame60' in out else 0
    if st['sleep_ms'] != 20 * nlines + pace:
        why.append('sleep %d ms, want %d' % (st['sleep_ms'], 20 * nlines + pace))
    if 'map=ok' in out and (st['delay_calls'], st['delay_us']) != (7, 14000):
        why.append('live window delays %d calls %d us' % (st['delay_calls'], st['delay_us']))
    return why


# ---- mutations -------------------------------------------------------------

W8_INDEX = '        rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX, (unsigned char)(index & PLL_INDEX_MASK));\n'
W8_RESTORE = '            rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX, (unsigned char)(p & LOW_BYTE));\n'
READ_C = '        c = rdnMmioRead32(base, REG_CLOCK_CNTL_INDEX);\n'
READ_V = '            v = rdnMmioRead32(base, REG_CLOCK_CNTL_DATA);\n'

# (label, old, new, world label, substring of that world's failure reasons)
MUTATIONS = [
    ('index store as 32 bits', W8_INDEX, '        rdnMmioWrite32(base, REG_CLOCK_CNTL_INDEX, index);\n',
     'good', 'SIM-VIOLATION write32-value'),
    ('upper-bits readback check removed', '        if ((c & ~LOW_BYTE) != (p & ~LOW_BYTE))\n            why = WHY_UPPER;\n',
     '', 'byte lanes ignored', 'SIM-VIOLATION data-from-wrong-index'),
    ('low-byte readback check removed', '            if ((c & LOW_BYTE) != index)\n                why = WHY_LOW;\n',
     '', 'low byte changes at the store', 'SIM-VIOLATION data-from-wrong-index'),
    ('readback after the data read removed', '            if (d != c)\n                why = WHY_AFTER_DATA;\n',
     '', 'index changed around the data read', 'log lacks'),
    # E then reads C, the probe aborts on its own unprovoked mismatch
    ('restore removed', W8_RESTORE, '', 'good', 'SIM-VIOLATION write32-no-abort'),
    ('abort writes C back instead of P', '            rdnMmioWrite32(base, REG_CLOCK_CNTL_INDEX, p);\n',
     '            rdnMmioWrite32(base, REG_CLOCK_CNTL_INDEX, c);\n', 'byte lanes ignored', 'SIM-VIOLATION write32-value'),
    ('restore as a 32-bit store', W8_RESTORE, '            rdnMmioWrite32(base, REG_CLOCK_CNTL_INDEX, p);\n',
     'good', 'SIM-VIOLATION write32-no-abort'),
    ('upper compare on bits 8-9 only', '        if ((c & ~LOW_BYTE) != (p & ~LOW_BYTE))\n',
     '        if ((c & 0x300UL) != (p & 0x300UL))\n', 'bits 10-31 change at the store',
     'SIM-VIOLATION data-from-wrong-index'),
    ('data read before the index store', W8_INDEX, READ_V.replace('    v =', 'v =') + W8_INDEX,
     'good', 'SIM-VIOLATION data-without-index'),
    ('splhigh removed', '    s = splhigh();\n', '    s = 100;\n', 'good', 'SIM-VIOLATION index-store-unmasked'),
    ('sleep inside the group', READ_C, READ_C + '        IOSleep(1);\n', 'good', 'SIM-VIOLATION sleep-while-masked'),
    ('write enable check removed', '    if (p & PLL_WR_EN) {\n', '    if (p & 0UL) {\n',
     'write enable set at the start', 'SIM-VIOLATION store-while-busy'),
    ('PLL groups after a static scan', '    if (!moving) {\n', '    if (!moving && 0) {\n', 'static scan', 'w8='),
    ('data register written', READ_V, READ_V + '            rdnMmioWrite8(base, REG_CLOCK_CNTL_DATA, 0);\n',
     'good', 'SIM-VIOLATION write8-offset'),
    ('eleventh PLL index', '    { "PIXCLKS_CNTL",          0x2d }\n',
     '    { "PIXCLKS_CNTL",          0x2d },\n    { "PPLL_DIV_1",            0x05 }\n', 'good', 'judge:'),
    ('groups go on after an abort', '        if (why != WHY_NONE)\n            break;\n', '',
     'byte lanes ignored', 'SIM-VIOLATION group-after-stop'),
    ('direct MMIO read in the probe', '    p = rdnMmioRead32(base, REG_CLOCK_CNTL_INDEX);\n',
     '    p = *(unsigned long *)(base + REG_CLOCK_CNTL_INDEX);\n', 'good', 'sim rc=-11'),
    ('long hex with a width (target pads nothing)',
     'val=%08x", r2aRegs[i].name, r2aRegs[i].offset, U(regVal[i]));',
     'val=%08lx", r2aRegs[i].name, r2aRegs[i].offset, regVal[i]);', 'good', 'malformed line'),
    ('no unmap', '    if (IOUnmapPhysicalFromIOTask(base, MMIO_MAP_LENGTH) != IO_R_SUCCESS)\n        r2aLine("stop reason=unmap-failed");\n',
     '    (void)base;\n', 'good', 'SIM-VIOLATION left-mapped'),
    ('VGA sequencer write', '    return inl((IOEISAPortAddress)PCI_CFG_DATA);\n',
     '    outb((IOEISAPortAddress)0x3c4, 1);\n    return inl((IOEISAPortAddress)PCI_CFG_DATA);\n', 'good',
     'SIM-VIOLATION outb'),
]


def main():
    failures = 0
    print('== shim prototypes against the target headers ==')
    failures += check_shims()

    tmp = tempfile.mkdtemp(prefix='sim_r2a.', dir=os.environ.get('TMPDIR'))
    atexit.register(shutil.rmtree, tmp, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
    exe = os.path.join(tmp, 'sim')
    r1exe = os.path.join(tmp, 'sim_r1')
    print('== build the unchanged probe (sha256 %s) and R1\'s ==' % hashlib.sha256(open(PROBE, 'rb').read()).hexdigest()[:16])
    ok, err = build(PROBE, exe)
    ok1, err1 = s1.build(s1.PROBE, r1exe)
    if not ok or not ok1:
        print(err, err1)
        print('sim_r2a: FAIL (build)')
        return 1
    print('  ok')

    print('== worlds ==')
    table = worlds()
    labels = [t[0] for t in table]
    if len(set(labels)) != len(labels):
        print('  FAIL duplicate world labels')
        failures += 1
    byname = dict((t[0], t) for t in table)
    for label, sc, verdict, exp in table:
        why = run_world(exe, r1exe, label, sc, verdict, exp)
        print('  %-4s %-48s%s' % ('ok' if not why else 'FAIL', label, '' if not why else ' ' + '; '.join(why)[:300]))
        failures += 1 if why else 0

    print('== mutations (each must be caught by its world, in this run) ==')
    src = open(PROBE).read()
    for label, old, new, wlabel, catch in MUTATIONS:
        if src.count(old) != 1:
            print('  FAIL %-44s anchor found %d times' % (label, src.count(old)))
            failures += 1
            continue
        mpath = os.path.join(tmp, 'mut.m')
        open(mpath, 'w').write(src.replace(old, new))
        mexe = os.path.join(tmp, 'mut')
        ok, err = build(mpath, mexe)
        if not ok:
            print('  FAIL %-44s mutant does not build: %s' % (label, err.strip()[:200]))
            failures += 1
            continue
        _, sc, verdict, exp = byname[wlabel]
        base_why = run_world(exe, r1exe, wlabel, sc, verdict, exp)
        why = run_world(mexe, r1exe, wlabel, sc, verdict, exp)
        caught = not base_why and any(catch in w for w in why)
        print('  %-4s %-44s [%s] %s' % ('ok' if caught else 'FAIL', label, wlabel, ('; '.join(why) or 'not caught')[:150]))
        failures += 0 if caught else 1

    print('sim_r2a:', 'PASS' if failures == 0 else 'FAIL (%d)' % failures)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
