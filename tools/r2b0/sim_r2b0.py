#!/usr/bin/env python3
"""Run OSRDNDisplay's record code on the host against fake worlds (docs/R2B0_IMPL_PLAN.md 6-2).

  sim_r2b0.py           build, run every world and mutation, exit 1 on any failure

osrdn_record.m and osrdn_pll.m are compiled unchanged as 32-bit C with
sim/simworld2b0.c standing in for osrdn_port.m, RDNR2aMMIO.m and the class.
Each world's log is judged by parse_r2b0.py; each world also names the
simulator's counters and request return codes it must produce.

Mutations are copies of a source file with one forbidden change each; each
names the world that must catch it and what that world must report, and
every one is caught in this same invocation (baseline PASS in the same run).

What this cannot show: the card, the kernel's spl and clock, cc 2.7.2.1's
code, and the class (tools/r2b0/check_r2b0_src.py holds it to structure).
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
TPROJ = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj')
RECORD = os.path.join(TPROJ, 'osrdn_record.m')
PLLSRC = os.path.join(TPROJ, 'osrdn_pll.m')
SIMDIR = os.path.join(HERE, 'sim')
WORLD_C = os.path.join(SIMDIR, 'simworld2b0.c')


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


s1 = _load('sim_r1_for_r2b0', os.path.join(PROJ, 'tools', 'r1', 'sim_r1.py'))
pb = _load('parse_r2b0_for_sim', os.path.join(HERE, 'parse_r2b0.py'))

BUILD = 0x1234abcd
RUNID = 4343

# The R2a boot's values (build/r2a/789467668, docs/R1_RESULT.md): with these
# every gate passes.
PLL_R2A = ['clockindex 303', 'pll 2 a700', 'pll 3 6', 'pll 4 70086', 'pll 7 30047', 'pll 8 c3',
           'pll 9 0', 'pll a 6a510c', 'pll d 7ffa', 'pll 12 aa3f1212', 'pll 2d f8c0']
MMIO_R2A = ['mmio 148 1fff0000', 'mmio 14c 27ff2000', 'mmio 23c 0', 'mmio 130 70000000', 'mmio b00 100',
            'mmio 420 807f0000', 'mmio 88c 07660142', 'mmio d14 20000', 'mmio d64 10000000',
            'mmio 228 10000000', 'mmio 140 32003200', 'mmio 144 1a395323', 'mmio 740 02010080',
            'mmio 3f8 04000000', 'mmio e40 140']
BRIDGE_VGA = ['cfg 0 30 0 3c 000c0000']


def world(pll=PLL_R2A, mmio=MMIO_R2A, directives=(), cards=((3, 11, 0),), bridge=BRIDGE_VGA, **kw):
    return s1.world(runid=RUNID, cards=cards, directives=list(pll) + list(mmio) + list(bridge) + list(directives), **kw)


# ---- shims -----------------------------------------------------------------

def check_shims():
    bad = 0
    pairs = [('driverkit/generalFuncs.h', ['IOSleep', 'IODelay', 'IOLog', 'IOGetTimestamp']),
             ('kernserv/i386/spl.h', ['splhigh', 'splx'])]
    for hdr, names in pairs:
        real = open(os.path.join(s1.TARGET_HEADERS, hdr), errors='replace').read()
        shimname = hdr.replace('kernserv/i386', 'kernserv/machine')
        shim = open(os.path.join(SIMDIR, 'include', shimname)).read()
        for n in names:
            a, b = s1.prototype(real, n), s1.prototype(shim, n)
            ok = a is not None and a == b
            print('  %-4s %-26s target %s  shim %s' % ('ok' if ok else 'FAIL', n, a, b))
            bad += 0 if ok else 1
    clock = open(os.path.join(s1.TARGET_HEADERS, 'kernserv', 'clock_timer.h'), errors='replace').read()
    gf = open(os.path.join(SIMDIR, 'include', 'driverkit', 'generalFuncs.h')).read()
    want = re.search(r'typedef\s+unsigned long long\s+ns_time_t;', clock)
    have = re.search(r'typedef\s+unsigned long long\s+ns_time_t;', gf)
    print('  %-4s ns_time_t is unsigned long long in both' % ('ok' if want and have else 'FAIL'))
    bad += 0 if want and have else 1
    world_c = open(WORLD_C).read()
    for hdr, names in ((os.path.join(TPROJ, 'osrdn_port.h'), ['osrdn_inb', 'osrdn_outb', 'osrdn_inl', 'osrdn_outl']),
                       (os.path.join(TPROJ, 'RDNR2aMMIO.h'), ['rdnMmioRead32', 'rdnMmioWrite8', 'rdnMmioWrite32'])):
        text = open(hdr).read()
        for n in names:
            a = s1.prototype(text, n)
            b = s1.prototype(world_c, n)
            if a is not None:
                a = (a[0], [p.replace('vm_address_t', 'unsigned int') for p in a[1]])
            ok = a is not None and a == b
            print('  %-4s %-26s header %s  sim %s' % ('ok' if ok else 'FAIL', n, a, b))
            bad += 0 if ok else 1
    return bad


# ---- build and run ---------------------------------------------------------

def build(record, pll, out):
    cmd = ['gcc-12', '-m32', '-std=gnu89', '-O0', '-fno-pie', '-no-pie', '-ffreestanding',
           '-fno-builtin', '-nostdinc', '-I', os.path.join(SIMDIR, 'include'), '-I', TPROJ,
           '-Wall', '-Werror', '-Wno-deprecated',
           '-x', 'c', record, pll, WORLD_C,
           '-x', 'none', '-nostdlib', '-nostartfiles', s1.LIBC32,
           '-Wl,-dynamic-linker,' + s1.LD32, '-o', out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0, r.stderr


def stats(stderr):
    m = re.search(r'SIM-STATS hw=(\d+) sleep_ms=(\d+) delay_us=(\d+) delay_calls=(\d+) write8=(\d+) '
                  r'write32=(\d+) groups=(\d+) data_reads=(\d+) final_index=([0-9a-f]{8}) vga_out=(\d+) '
                  r'vga_in=(\d+) stamps=(\d+)', stderr)
    if not m:
        return None
    k = ('hw', 'sleep_ms', 'delay_us', 'delay_calls', 'w8', 'w32', 'groups', 'data')
    d = dict(zip(k, (int(x) for x in m.groups()[:8])))
    d['final'] = m.group(9)
    d['vga_out'], d['vga_in'], d['stamps'] = int(m.group(10)), int(m.group(11)), int(m.group(12))
    return d


# expectations: klass 'PASS-ENTER' | 'PASS-REFUSE' | 'FAIL:<sub>' | 'NORECORD';
# rcs: request return codes in order; counters; log / nolog substrings
def worlds():
    good = dict(rcs=[0], w8=24, w32=0, groups=12, data=12, final='00000303', vga_out=48, vga_in=57)
    return [
        ('good (kernel console)', world(), 'PASS-ENTER',
         dict(good, log=['pllend groups=12', 'vga part=1 misc=e3 dec=1 base=3d4',
                         'vga part=2 gri=08 gr=000f00000000050fff attri=20 attr=0100030000',
                         'verdict gates=32 refused=0 result=enter'])),
        ('refdiv 12 and PLL_DIV_SEL 0 (refuses)', world(pll=['clockindex 3', 'pll 2 a700', 'pll 3 c', 'pll 7 600ad', 'pll 8 3']),
         'PASS-REFUSE', dict(good, final='00000003', log=['name=divsel val=00000000 want=00000300 pass=0',
                                                          'name=refdiv val=0000000c want=00000006 pass=1'])),
        ('refdiv 9 refuses', world(pll=['clockindex 303', 'pll 3 9', 'pll 8 3']), 'PASS-REFUSE',
         dict(good, log=['name=refdiv val=00000009 want=00000006 pass=0'])),
        ('boot loader state (cmode 2, other VGA)', world(directives=['cmode 2', 'vgabyte crtc 0 67', 'vgamisc 67']),
         'PASS-ENTER', dict(good, log=['cmode=2', 'misc=67'], report=['vga-state-differs'])),
        ('monochrome MISC', world(directives=['vgamisc e2']), 'PASS-ENTER',
         dict(good, log=['base=3b4'], report=['vga-state-differs'])),
        ('VGA not decoded', world(directives=['vga undecoded']), 'PASS-ENTER',
         dict(good, vga_out=0, vga_in=1, log=['misc=ff dec=0'], report=['not decoded'])),
        ('clock goes back in the live window', world(directives=['clockback 4 12000']), 'PASS-ENTER',
         dict(good, log=['d1=unm'], report=['unmeasured or saturated: 1'])),
        ('static scan: stop and latch', world(scan=False, directives=['request %d' % RUNID, 'request %d' % (RUNID + 1)]),
         'FAIL:VLINE static', dict(rcs=[0, -728], w8=0, groups=0, vga_out=0, nolog=['pllstart', 'vga part'])),
        ('PLL disturbed: no VGA, latch', world(directives=['disturb 2 afterstore 00000204', 'request %d' % RUNID,
                                                          'request %d' % (RUNID + 1)]),
         'FAIL:aborted (upper)', dict(rcs=[0, -728], w8=5, w32=1, groups=3, vga_out=0, nolog=['vga part'],
                                log=['stop reason=pll-index-disturbed', 'name=refdiv val=00000000 want=00000006 pass=na'])),
        ('PLL write enable at the start', world(pll=['clockindex 383', 'pll 3 6']), 'FAIL:busy',
         dict(rcs=[0], w8=0, groups=1, vga_out=0, log=['pllbusy k=0'])),
        ('two records, then a third is refused', world(directives=['request %d' % RUNID, 'request %d' % (RUNID + 1),
                                                                   'request %d' % (RUNID + 2)]),
         'PASS-ENTER', dict(rcs=[0, 0, -725])),
        ('reentry from inside a record', world(directives=['reenter 5']), 'PASS-ENTER',
         dict(good, log=['SIM-REENTER rc=-725 hw=0'])),
        ('key no', world(directives=['key no']), 'NORECORD', dict(rcs=[-729], hw_record=0, log=['key=no'])),
        ('bad magic and count and runid', world(directives=['request %d 52324231 2' % RUNID, 'request %d 52324230 3' % RUNID,
                                                            'request 0 52324230 2']),
         'NORECORD', dict(rcs=[-706, -706, -706])),
        ('same runid twice', world(directives=['request %d' % RUNID, 'request %d' % RUNID]), 'PASS-ENTER',
         dict(rcs=[0, -706])),
        ('BAR2 changed after init', world(directives=['cfgflip 3 11 0 18 e8210000 2', 'request %d' % RUNID,
                                                       'request %d' % (RUNID + 1)]),
         'FAIL:probe stopped early', dict(rcs=[0, -728], w8=0, groups=0, vga_out=0, log=['stop reason=pci-bar2-changed'])),
        ('no card: probe declines', world(cards=()), 'NOINIT', dict(log=['probe rc=-704', 'decline'])),
        ('two cards: init refuses', world(cards=((3, 11, 0), (3, 14, 0))), 'NOINIT', dict(log=['abort=rv280-count'])),
        ('card elsewhere: location check', world(directives=['probe 0 3 13 0']), 'NOINIT', dict(log=['decline'])),
        # the init BAR0 check needs the bridge's prefetch window to hold the
        # MAPPED length from BAR0 (osrdn_record.m checkBar): 8 MiB from R3b-1
        # (docs/R3_MULTIMODE_PLAN.md 22-5 V7).  The default window ends at e7ffffff.
        ('prefetch window exactly 8 MiB', world(pref=(0xe0000000, 0xe07fffff, 0, 0, 0)), 'PASS-ENTER', dict(good)),
        ('prefetch window 7 MiB: init refuses', world(pref=(0xe0000000, 0xe06fffff, 0, 0, 0)), 'NOINIT',
         dict(log=['abort=bar0'])),
        ('bridge VGA forwarding off refuses', world(bridge=['cfg 0 30 0 3c 00040000']), 'PASS-REFUSE',
         dict(good, log=['name=bridgevga val=00000000 want=00080000 pass=0'])),
    ]


def run_world(exe, label, sc, klass, exp):
    why = []
    r = subprocess.run([exe], input=sc, capture_output=True, text=True, timeout=60)
    st = stats(r.stderr)
    if r.returncode != 0 or st is None:
        return ['sim rc=%d %s' % (r.returncode, r.stderr.strip()[:200])]
    out = r.stdout
    if 'SIM-LATCH first=1 second=0 after_release=1' not in out:
        why.append('the one-owner probe latch: %r' %
                   ([l for l in out.splitlines() if l.startswith('SIM-LATCH')] or 'no SIM-LATCH line'))
    rcs = [int(x) for x in re.findall(r'SIM-REQ runid=\d+ rc=(-?\d+)', out)]
    if klass == 'NOINIT':
        if 'SIM-INIT ok=1' in out and 'mapped=1' in out:
            why.append('init accepted')
    else:
        if 'rcs' in exp and rcs != exp['rcs']:
            why.append('request codes %s, want %s' % (rcs, exp['rcs']))
    report = []
    if klass not in ('NORECORD', 'NOINIT'):
        tool = '\n'.join(l for l in out.splitlines() if l.startswith('RDNR2B0 state '))
        report, fail, rec, got = pb.judge(out, str(RUNID), '%08x' % BUILD, tool)
        kind, _, sub = klass.partition(':')
        if kind == 'FAIL':
            if got != 'FAIL' or not any(sub in f for f in fail):
                why.append('judge %s, want FAIL naming %r: %s' % (got, sub, fail[:3]))
        elif got != klass:
            why.append('judge %s, want %s: %s' % (got, klass, fail[:3]))
    elif re.search(r'RDN-R2B0 \d+ begin', out):
        why.append('a record ran')
    for k in ('w8', 'w32', 'groups', 'data', 'final', 'vga_out', 'vga_in'):
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
    # pacing: 20 ms per record line, 60 + 1000 ms windows; 7 x 2 ms live gaps
    nlines = len(re.findall(r'RDN-R2B0 %d ' % RUNID, out)) + len(re.findall(r'RDN-R2B0 %d ' % (RUNID + 1), out)) \
        + len(re.findall(r'RDN-R2B0 %d ' % (RUNID + 2), out))
    pace = (60 + 1000) * len(re.findall(r' frame60 before=', out))
    if st['sleep_ms'] != 20 * nlines + pace:
        why.append('sleep %d ms, want %d' % (st['sleep_ms'], 20 * nlines + pace))
    if ' live i=7 ' in out and st['delay_us'] != 14000 * len(re.findall(r' live i=7 ', out)):
        why.append('live window delays %d us' % st['delay_us'])
    return why


# ---- mutations -------------------------------------------------------------

REC, PLLF = 'record', 'pll'

# (label, file, old, new, world label, substring of that world's failure reasons)
MUTATIONS = [
    # R2a's PLL group mutations that still apply (anchors in osrdn_pll.m)
    ('index store as 32 bits', PLLF,
     '        rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX, (unsigned char)(index & PLL_INDEX_MASK));\n',
     '        rdnMmioWrite32(base, REG_CLOCK_CNTL_INDEX, index);\n', 'good (kernel console)', 'SIM-VIOLATION write32-value'),
    ('upper-bits readback check removed', PLLF, '        if ((c & ~LOW_BYTE) != (p & ~LOW_BYTE))\n            why = WHY_UPPER;\n',
     '', 'PLL disturbed: no VGA, latch', 'SIM-VIOLATION data-from-wrong-index'),
    ('restore removed', PLLF, '            rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX, (unsigned char)(p & LOW_BYTE));\n', '',
     'good (kernel console)', 'SIM-VIOLATION write32-no-abort'),
    ('splhigh removed from a PLL group', PLLF, '    s = splhigh();\n    p = rdnMmioRead32', '    s = 100;\n    p = rdnMmioRead32',
     'good (kernel console)', 'SIM-VIOLATION index-store-unmasked'),
    ('write enable check removed', PLLF, '    if (p & PLL_WR_EN) {\n', '    if (p & 0UL) {\n',
     'PLL write enable at the start', 'SIM-VIOLATION store-while-busy'),
    ('groups go on after an abort', PLLF, '        if (why != WHY_NONE)\n            break;\n', '',
     'PLL disturbed: no VGA, latch', 'SIM-VIOLATION group-after-stop'),
    ('data register written', PLLF, '            v = rdnMmioRead32(base, REG_CLOCK_CNTL_DATA);\n',
     '            v = rdnMmioRead32(base, REG_CLOCK_CNTL_DATA);\n            rdnMmioWrite8(base, REG_CLOCK_CNTL_DATA, 0);\n',
     'good (kernel console)', 'SIM-VIOLATION write8-offset'),
    ('twelfth group skipped', PLLF, '    for (k = 0; k < R2A_PLL_COUNT; k++) {\n',
     '    for (k = 0; k < R2A_PLL_COUNT - 1; k++) {\n', 'good (kernel console)', '11 pll lines, expected 12'),
    ('twelfth index wrong', PLLF, '    { "PPLL_DIV_2",            0x06 }\n', '    { "PPLL_DIV_2",            0x07 }\n',
     'good (kernel console)', 'table says'),
    ('direct MMIO read in the record', REC, '        liveFrame[i] = rdnMmioRead32(base, REG_CRTC_FRAME);\n',
     '        liveFrame[i] = *(unsigned long *)(base + REG_CRTC_FRAME);\n', 'good (kernel console)', 'sim rc=-11'),
    ('long hex with a width (target pads nothing)', REC,
     '"reg name=%s off=%04x val=%08x", osrdnRegs[i].name, osrdnRegs[i].offset, U(osrdnRegVal[i]));',
     '"reg name=%s off=%04x val=%08lx", osrdnRegs[i].name, osrdnRegs[i].offset, osrdnRegVal[i]);',
     'good (kernel console)', 'malformed line'),
    ('PLL groups after a static scan', REC, '    if (!moving) {\n', '    if (!moving && 0) {\n',
     'static scan: stop and latch', 'log has'),
    # VGA
    ('SEQ index not restored', REC, '        osrdn_outb((IOEISAPortAddress)VGA_SEQ_INDEX, v->seqIndex);\n', '',
     'good (kernel console)', 'SIM-VIOLATION vga-index-not-restored'),
    ('data port write added', REC, '            v->seq[i] = osrdn_inb((IOEISAPortAddress)VGA_SEQ_DATA);\n',
     '            v->seq[i] = osrdn_inb((IOEISAPortAddress)VGA_SEQ_DATA);\n            osrdn_outb((IOEISAPortAddress)VGA_SEQ_DATA, v->seq[i]);\n',
     'good (kernel console)', 'SIM-VIOLATION vga-data-write'),
    ('attribute index without PAS', REC, '(unsigned char)((VGA_ATTR_FIRST + i) | VGA_PAS));',
     '(unsigned char)(VGA_ATTR_FIRST + i));', 'good (kernel console)', 'SIM-VIOLATION attr-index-value'),
    ('flip-flop reset removed', REC,
     '        for (i = 0; i < VGA_ATTR_COUNT; i++) {\n            (void)osrdn_inb((IOEISAPortAddress)statusPort);\n',
     '        for (i = 0; i < VGA_ATTR_COUNT; i++) {\n', 'good (kernel console)', 'SIM-VIOLATION attr-data-write'),
    ('attribute 0x00 read', REC, '#define VGA_ATTR_FIRST      0x10\n', '#define VGA_ATTR_FIRST      0x00\n',
     'good (kernel console)', 'SIM-VIOLATION attr-palette-read'),
    ('DAC read added', REC, '        v->seqIndex = osrdn_inb((IOEISAPortAddress)VGA_SEQ_INDEX);\n',
     '        v->seqIndex = osrdn_inb((IOEISAPortAddress)VGA_SEQ_INDEX);\n        (void)osrdn_inb((IOEISAPortAddress)0x3c9);\n',
     'good (kernel console)', 'SIM-VIOLATION port-read-not-allowed'),
    ('splhigh removed from the VGA step', REC, '    s = splhigh();\n    v->misc', '    s = 100;\n    v->misc',
     'good (kernel console)', 'SIM-VIOLATION vga-unmasked'),
    ('VGA goes on after a PLL stop', REC, '    if (pllComplete) {\n        indexEnd', '    if (1) {\n        indexEnd',
     'PLL disturbed: no VGA, latch', 'SIM-VIOLATION hardware-after-stop'),
    ('mono base ignored', REC, '        crtcBase = (v->misc & 1) ? VGA_CRTC_COLOR : VGA_CRTC_MONO;\n',
     '        crtcBase = VGA_CRTC_COLOR;\n', 'monochrome MISC', 'SIM-VIOLATION vga-wrong-base'),
    # time
    ('t1<=t0 check removed', REC, '    if (t1 <= t0)\n        return ELAPSED_UNMEASURED;\n', '',
     'clock goes back in the live window', "log lacks 'd1=unm'"),
    ('timestamp inside the VGA step', REC, '    v->misc = osrdn_inb((IOEISAPortAddress)VGA_MISC_READ);\n',
     '    { ns_time_t tx; IOGetTimestamp(&tx); }\n    v->misc = osrdn_inb((IOEISAPortAddress)VGA_MISC_READ);\n',
     'good (kernel console)', 'SIM-VIOLATION timestamp-while-masked'),
    # request guard
    ('test-and-set as a plain flag', REC, '    s = splhigh();\n    if (st->latched) {', '    s = 100;\n    if (st->latched) {',
     'good (kernel console)', 'SIM-VIOLATION splx'),
    ('log inside the test-and-set', REC, '        st->inProgress = 1;\n        st->bootRecords++;\n',
     '        st->inProgress = 1;\n        st->bootRecords++;\n        IOLog("x\\n");\n',
     'good (kernel console)', 'SIM-VIOLATION log-while-masked'),
    ('latch not set', REC, '    if (result == OSRDN_RESULT_STOP)\n        st->latched = 1;\n', '',
     'PLL disturbed: no VGA, latch', 'SIM-VIOLATION hardware-after-latch'),
    ('in progress not cleared', REC, '    st->inProgress = 0;\n    return 0;\n', '    return 0;\n',
     'good (kernel console)', 'SIM-VIOLATION in-progress-left'),
    ('in-progress check removed', REC, '    } else if (st->inProgress) {\n        verdict = OSRDN_R_BUSY;\n', '',
     'reentry from inside a record', 'SIM-VIOLATION reentered-request-touched-hardware'),
    ('per-boot limit removed', REC, '    } else if (st->bootRecords >= 2) {\n        verdict = OSRDN_R_BUSY;\n', '',
     'two records, then a third is refused', 'request codes'),
    ('key check removed', REC, '    if (!st->recordEnabled) {\n', '    if (0) {\n', 'key no', 'request codes'),
    # gates
    ('gate table entry flipped', REC, '    gateEqual(0, "fpon", regValue(0x0284) & FP_FPON, 0, &refused);\n',
     '    gateEqual(0, "fpon", regValue(0x0284) & FP_FPON, 1, &refused);\n', 'good (kernel console)', 'gate fpon'),
    ('expectation header name swapped', 'expect', '    { "mcfb", "MC_FB_LOCATION", 0x0148,', '    { "mcfb", "MC_FB_LOCATION", 0x014c,',
     'good (kernel console)', 'gate mcfb'),
    ('bridge VGA gate inverted', REC, '(all & BRIDGE_CTL_VGA) != 0UL, &refused);', '(all & BRIDGE_CTL_VGA) == 0UL, &refused);',
     'good (kernel console)', 'gate bridgevga'),
    ('probe latch always grants', REC, '    if (!held)\n        osrdnProbeHeld = 1;\n',
     '    osrdnProbeHeld = 1;\n    held = 0;\n', 'good (kernel console)', 'one-owner probe latch'),
    ('probe latch never releases', REC, 'osrdn_probe_release(void)\n{\n    osrdnProbeHeld = 0;\n',
     'osrdn_probe_release(void)\n{\n', 'good (kernel console)', 'one-owner probe latch'),
]


def main():
    failures = 0
    print('== shim prototypes against the target headers ==')
    failures += check_shims()

    tmp = tempfile.mkdtemp(prefix='sim_r2b0.', dir=os.environ.get('TMPDIR'))
    atexit.register(shutil.rmtree, tmp, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
    exe = os.path.join(tmp, 'sim')
    print('== build the unchanged record (sha256 %s, pll %s) ==' % (
        hashlib.sha256(open(RECORD, 'rb').read()).hexdigest()[:16], hashlib.sha256(open(PLLSRC, 'rb').read()).hexdigest()[:16]))
    ok, err = build(RECORD, PLLSRC, exe)
    if not ok:
        print(err)
        print('sim_r2b0: FAIL (build)')
        return 1
    print('  ok')

    print('== worlds ==')
    table = worlds()
    labels = [t[0] for t in table]
    if len(set(labels)) != len(labels):
        print('  FAIL duplicate world labels')
        failures += 1
    byname = dict((t[0], t) for t in table)
    for label, sc, klass, exp in table:
        why = run_world(exe, label, sc, klass, exp)
        print('  %-4s %-48s%s' % ('ok' if not why else 'FAIL', label, '' if not why else ' ' + '; '.join(why)[:400]))
        failures += 1 if why else 0

    print('== mutations (each must be caught by its world, in this run) ==')
    srcs = {REC: RECORD, PLLF: PLLSRC, 'expect': os.path.join(TPROJ, 'osrdn_expect.h')}
    for label, which, old, new, wlabel, catch in MUTATIONS:
        text = open(srcs[which]).read()
        if text.count(old) != 1:
            print('  FAIL %-44s anchor found %d times' % (label, text.count(old)))
            failures += 1
            continue
        mdir = os.path.join(tmp, 'mut')
        os.makedirs(mdir, exist_ok=True)
        for f in os.listdir(TPROJ):
            if f.endswith('.h'):
                open(os.path.join(mdir, f), 'w').write(open(os.path.join(TPROJ, f)).read())
        rec_path, pll_path = os.path.join(mdir, 'osrdn_record.m'), os.path.join(mdir, 'osrdn_pll.m')
        open(rec_path, 'w').write(open(RECORD).read())
        open(pll_path, 'w').write(open(PLLSRC).read())
        target = {REC: rec_path, PLLF: pll_path, 'expect': os.path.join(mdir, 'osrdn_expect.h')}[which]
        open(target, 'w').write(text.replace(old, new))
        mexe = os.path.join(tmp, 'mutexe')
        cmd_ok, err = build_in(mdir, rec_path, pll_path, mexe)
        if not cmd_ok:
            print('  FAIL %-44s mutant does not build: %s' % (label, err.strip()[:200]))
            failures += 1
            continue
        _, sc, klass, exp = byname[wlabel]
        base_why = run_world(exe, wlabel, sc, klass, exp)
        why = run_world(mexe, wlabel, sc, klass, exp)
        caught = not base_why and any(catch in w for w in why)
        print('  %-4s %-44s [%s] %s' % ('ok' if caught else 'FAIL', label, wlabel, ('; '.join(why) or 'not caught')[:160]))
        failures += 0 if caught else 1

    print('sim_r2b0:', 'PASS' if failures == 0 else 'FAIL (%d)' % failures)
    return 1 if failures else 0


def build_in(incdir, record, pll, out):
    cmd = ['gcc-12', '-m32', '-std=gnu89', '-O0', '-fno-pie', '-no-pie', '-ffreestanding',
           '-fno-builtin', '-nostdinc', '-I', os.path.join(SIMDIR, 'include'), '-I', incdir,
           '-Wall', '-Werror', '-Wno-deprecated',
           '-x', 'c', record, pll, WORLD_C,
           '-x', 'none', '-nostdlib', '-nostartfiles', s1.LIBC32,
           '-Wl,-dynamic-linker,' + s1.LD32, '-o', out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0, r.stderr


if __name__ == '__main__':
    sys.exit(main())
