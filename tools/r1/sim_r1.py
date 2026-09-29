#!/usr/bin/env python3
"""Run the R1 probe's own source on the host against fake PCI worlds.

  sim_r1.py            build, run every scenario and mutation, exit 1 on any failure

RDNR1Probe.m is compiled unchanged as 32-bit code (so `unsigned long' is 32
bits, as on the target) together with sim/simworld.c, which plays the PCI bus,
the Radeon's MMIO and the kernel functions the probe calls.  The probe's
output is then judged by parse_r1.py -- the same parser the real log will
meet -- so the probe and the parser are tested against each other, not each
against its own expectations.

What the fake world refuses (outb/outw/inb/inw, outl to anything but 0xCF8,
config reads at 0x40 or above, a second mapping or one of the wrong length,
an MMIO write, a sleep inside the liveness window) is listed in simworld.c.

Scenarios check the gate verdict, the failure named, and the probe's
behaviour (did it map, how many 2 ms delays).  Mutations are copies of the
probe with one forbidden change each; every one must make the simulated run
fail in this same invocation (PLAN section 4: a checker that cannot fail
proves nothing).

What this cannot show: how cc 2.7.2.1 compiles the file, what the real
kernel's IOLog drops, or anything about the real card.  hostcheck.sh and the
target build cover the first; R1 itself the rest.
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
WS = os.path.dirname(PROJ)
PROBE = os.path.join(PROJ, 'probe', 'RDNR1Probe', 'RDNR1Probe_reloc.tproj', 'RDNR1Probe.m')
SIMDIR = os.path.join(HERE, 'sim')
TARGET_HEADERS = os.path.join(WS, 'ref', 'openstep', 'headers', 'NextDeveloper', 'Headers')

_spec = importlib.util.spec_from_file_location('parse_r1', os.path.join(HERE, 'parse_r1.py'))
pr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pr)
dec = pr.dec

BUILD = 0x1234abcd
LIBC32 = '/usr/lib32/libc.so.6'
LD32 = '/lib/ld-linux.so.2'


# ---- shim prototypes must be the target's ---------------------------------

def norm(text):
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    text = re.sub(r'//[^\n]*', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def prototype(text, name):
    m = re.search(r'([A-Za-z_][\w \t\n*]*?)\b%s\s*\(([^)]*)\)' % re.escape(name), norm(text))
    if not m:
        return None
    ret = m.group(1).split(';')[-1].split('}')[-1]
    ret = re.sub(r'\b(static|__inline__|inline|extern)\b', ' ', ret)
    params = [re.sub(r'\s*\b\w+$', '', p.strip()) if len(p.split()) > 1 else p.strip()
              for p in m.group(2).split(',')]
    return re.sub(r'\s+', ' ', ret).strip(), [re.sub(r'\s+', ' ', p) for p in params]


def check_shims():
    pairs = [
        ('driverkit/generalFuncs.h', ['IOSleep', 'IODelay', 'IOLog']),
        ('driverkit/kernelDriver.h', ['IOMapPhysicalIntoIOTask', 'IOUnmapPhysicalFromIOTask']),
        ('driverkit/i386/ioPorts.h', ['inb', 'inw', 'inl', 'outb', 'outw', 'outl']),
    ]
    bad = 0
    for hdr, names in pairs:
        real = open(os.path.join(TARGET_HEADERS, hdr), errors='replace').read()
        shim = open(os.path.join(SIMDIR, 'include', hdr)).read()
        for n in names:
            a, b = prototype(real, n), prototype(shim, n)
            ok = a is not None and a == b
            print('  %-4s %-26s target %s  shim %s' % ('ok' if ok else 'FAIL', n, a, b))
            bad += 0 if ok else 1
    return bad


# ---- build -----------------------------------------------------------------

def build(src, out, stamp=BUILD):
    cmd = ['gcc-12', '-m32', '-std=gnu89', '-O0', '-fno-pie', '-no-pie', '-ffreestanding',
           '-fno-builtin', '-nostdinc', '-I', os.path.join(SIMDIR, 'include'),
           '-Wall', '-Werror', '-Wno-deprecated', '-DR1_BUILD=0x%08x' % stamp,
           '-x', 'c', src, os.path.join(SIMDIR, 'simworld.c'),
           '-x', 'none', '-nostdlib', '-nostartfiles', LIBC32,
           '-Wl,-dynamic-linker,' + LD32, '-o', out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0, r.stderr


def run(exe, scenario):
    r = subprocess.run([exe], input=scenario, capture_output=True, text=True, timeout=30)
    return r.returncode, r.stdout, r.stderr


# ---- worlds ----------------------------------------------------------------

def window(base, limit):
    return ((limit >> 16) & 0xfff0) << 16 | ((base >> 16) & 0xfff0)


def device(bdf, vid, did, classcode, rev=0, header=0, command=0, bars=(0, 0, 0), subsys=0,
           bus_numbers=None, win20=None, win24=None, win28=0, win2c=0):
    b, d, f = bdf
    w = {0x00: did << 16 | vid, 0x04: command, 0x08: classcode << 8 | rev,
         0x0c: header << 16, 0x2c: subsys}
    if bus_numbers is not None:
        w[0x18] = bus_numbers
        w[0x20] = win20
        w[0x24] = win24
        w[0x28] = win28
        w[0x2c] = win2c
    else:
        w[0x10], w[0x14], w[0x18] = bars
    return ['cfg %d %d %d %x %x' % (b, d, f, off, val) for off, val in sorted(w.items())]


def world(runid=4242, cards=((3, 13, 0),), bar2=0xe8200000, command=0x0003,
          bridge_win20=(0xe8000000, 0xe82fffff), card_bus_bridges=True, extra=(),
          scan=True, mapfail=False, mode=0, ati_secondary=False, unmapfail=False,
          card_header=0, pref=(0xe0000000, 0xe7ffffff, 0, 0, 0), directives=()):
    lines = ['runid %d' % runid]
    # host bridge and a multi-function ISA bridge with an IDE function
    lines += device((0, 0, 0), 0x8086, 0x2570, 0x060000)
    lines += device((0, 31, 0), 0x8086, 0x24d0, 0x060100, header=0x80)
    lines += device((0, 31, 1), 0x8086, 0x24db, 0x01018a)
    # a subtractive-decode hub bridge, primary 0, secondary and subordinate 3
    if card_bus_bridges:
        lines += device((0, 30, 0), 0x8086, 0x244e, 0x060401, header=0x01,
                        bus_numbers=3 << 16 | 3 << 8 | 0,
                        win20=window(*bridge_win20), win24=window(pref[0], pref[1]) | pref[2],
                        win28=pref[3], win2c=pref[4])
    for c in cards:
        lines += device(c, 0x1002, 0x5960, 0x030000, rev=1, header=(0x80 if ati_secondary else 0) | card_header,
                        command=command, bars=(0xe0000008, 0x0000d001, bar2), subsys=0x2002174b)
        if ati_secondary:
            lines += device((c[0], c[1], 1), 0x1002, 0x5d44, 0x038000, rev=1,
                            bars=(0xd8000008, 0, 0xe8210000), subsys=0x2003174b)
    lines += list(extra)
    m = dec.oracle.MODES[mode]
    words = dec.oracle.rfb_crtc_words(m)
    regs = {0x00f8: 0x08000000, 0x0108: 0x08000000, 0x0100: 0xe0000000,
            0x0148: 0xe7ffe000, 0x014c: 0xefffe800, 0x023c: 0xe0000000,
            0x0200: words[0], 0x0204: words[1], 0x0208: words[2], 0x020c: words[3]}
    lines += ['mmio %x %x' % kv for kv in sorted(regs.items())]
    if scan:
        hz = m['clock'] * 1000.0 / (m['htotal'] * m['vtotal'])
        lines.append('scan %d %d' % (m['vtotal'], round(hz * 1000)))
    else:
        lines.append('scan dead')
    if mapfail:
        lines.append('mapfail')
    if unmapfail:
        lines.append('unmapfail')
    lines += list(directives)
    return '\n'.join(lines) + '\n'


# (label, scenario, expect gate pass?, failure substring, report substring,
#  expect a map attempt?, probe-log substring)
def scenarios():
    return [
        ('good', world(), True, None, '640x480', True, None),
        ('good 1024x768 console words', world(mode=[i for i, m in enumerate(dec.oracle.MODES)
                                                     if m['hdisp'] == 1024][0]), True, None, '1024x768', True, None),
        ('card with ATI secondary function', world(ati_secondary=True), True, None, 'RV280 functions found: 1', True, 'did=5d44'),
        ('card on bus 0, no bridge', world(cards=((0, 13, 0),), card_bus_bridges=False), True, None,
         'over 0 bridge(s)', True, None),
        ('no card', world(cards=()), False, 'expected exactly one RV280', None, False, 'rv280-count-0'),
        ('two cards', world(cards=((3, 13, 0), (3, 14, 0))), False, 'expected exactly one RV280', None, False, 'rv280-count-2'),
        ('BAR2 outside bridge window', world(bar2=0xe9000000), False, 'MMIO pre-check refused', None, False, 'map=skipped'),
        ('memory decode off', world(command=0x0001), False, 'MMIO pre-check refused', None, False, 'cmdmem=0'),
        ('BAR2 64-bit', world(bar2=0xe8200004), False, 'MMIO pre-check refused', None, False, 'type=mem64'),
        ('BAR2 io', world(bar2=0x0000d101), False, 'MMIO pre-check refused', None, False, 'type=io'),
        ('BAR2 zero', world(bar2=0x00000000), False, 'MMIO pre-check refused', None, False, 'map=skipped'),
        ('card bus with no bridge above', world(card_bus_bridges=False), False, 'MMIO pre-check refused', None, False, 'inwindow=0'),
        ('BAR2 straddles window end', world(bar2=0xe82ff000), False, 'MMIO pre-check refused', None, False, 'inwindow=0'),
        ('map fails', world(mapfail=True), False, 'map-failed', None, True, 'map=fail'),
        ('card behind a 64-bit prefetch window above 4 GiB',
         world(bridge_win20=(0xfff00000, 0x000fffff), pref=(0xe8000000, 0xe82fffff, 1, 1, 1)),
         False, 'MMIO pre-check refused', None, False, 'inwindow=0'),
        ('card in a 64-bit prefetch window below 4 GiB',
         world(bridge_win20=(0xfff00000, 0x000fffff), pref=(0xe8000000, 0xe82fffff, 1, 0, 0)),
         True, None, '640x480', True, None),
        ('card on bus 0, BAR2 wraps past 4 GiB', world(cards=((0, 13, 0),), card_bus_bridges=False, bar2=0xfffff000),
         False, 'MMIO pre-check refused', None, False, 'wrap=1'),
        ('selected function has a type-1 header', world(card_header=1),
         False, 'MMIO pre-check refused', None, False, 'hdr=01'),
        ('BAR2 changes between reads', world(directives=['cfgflip 3 13 0 18 e8200008 2']),
         False, 'MMIO pre-check refused', None, False, 'stable=0'),
        ('bridge window changes between reads', world(directives=['cfgflip 0 30 0 20 0000fff0 1']),
         False, 'MMIO pre-check refused', None, False, 'stable=0'),
        ('unmap fails', world(unmapfail=True), False, 'unmap-failed', None, True, 'unmap-failed'),
        ('dead scanout', world(scan=False), False, 'VLINE static', None, True, 'vline-static'),
        ('too many bridges', world(extra=sum([device((5, k, 0), 0x8086, 0x244e, 0x060400, header=1,
                                                      bus_numbers=0x404000, win20=0, win24=0)
                                              for k in range(16)], [])),
         False, 'too-many-bridges', None, False, 'inwindow=0'),
    ]


MUTATIONS = [
    ('MMIO write', 'return *(volatile unsigned long *)(base + offset);',
     '*(volatile unsigned long *)(base + offset) = 0; return 0;', 'crash'),
    ('VGA sequencer write', 'return inl((IOEISAPortAddress)PCI_CFG_DATA);',
     'outb((IOEISAPortAddress)0x3c4, 1); return inl((IOEISAPortAddress)PCI_CFG_DATA);', 'outb'),
    ('config data write', 'return inl((IOEISAPortAddress)PCI_CFG_DATA);',
     'outl((IOEISAPortAddress)PCI_CFG_DATA, 0); return inl((IOEISAPortAddress)PCI_CFG_DATA);', 'outl-port'),
    ('bigger mapping', 'IOMapPhysicalIntoIOTask((unsigned)start, MMIO_MAP_LENGTH, &base)',
     'IOMapPhysicalIntoIOTask((unsigned)start, 0x10000, &base)', 'map-length'),
    ('config read past 0x40', 'w[k] = pciRead(bus, device, function, off + 4 * k);',
     'w[k] = pciRead(bus, device, function, off + 0x40 + 4 * k);', 'cfg-offset'),
    ('lines logged inside the live window', '        liveVline[i] = mmioRead(base, REG_CRTC_VLINE);\n',
     '        liveVline[i] = mmioRead(base, REG_CRTC_VLINE);\n        r1Line("stop reason=x");\n', 'sleep-inside-live-window'),
    ('no unmap', '    if (IOUnmapPhysicalFromIOTask(base, MMIO_MAP_LENGTH) != IO_R_SUCCESS)\n        r1Line("stop reason=unmap-failed");\n',
     '    (void)base;\n', 'left-mapped'),
    ('reads on after a static VLINE', '    if (!moving) {', '    if (!moving && 0) {', 'judge:kept reading'),
    # each map refusal removed: the world it guards must now see a map
    ('no wrap check', '    wrap = (start + (MMIO_MAP_LENGTH - 1UL) < start);', '    wrap = 0 && start;',
     'maps:wrap'),
    ('no header-type check', '    hdrType = (int)((header >> 16) & 0x7fUL);', '    hdrType = 0 && header;',
     'maps:hdr1'),
    ('no re-read comparison', '          cmdMem && !wrap && inWindow && stable);',
     '          cmdMem && !wrap && inWindow && (stable || 1));', 'maps:flip'),
    ('64-bit prefetch taken as usable', '    if (type == 0UL)\n        return 1;', '    if (type == 0UL || 1)\n        return 1;',
     'maps:pref64'),
    ('long hex with a width (target pads nothing)', 'val=%08x", r1Regs[i].name, r1Regs[i].offset, U(v));',
     'val=%08lx", r1Regs[i].name, r1Regs[i].offset, v);', 'judgegood:malformed line'),
    ('bridge overflow ignored', '    if (r1BridgeOverflow)\n        return 0;', '    if (r1BridgeOverflow && 0)\n        return 0;',
     'maps:overflow'),
]

MUTATION_WORLDS = {
    'wrap': dict(cards=((0, 13, 0),), card_bus_bridges=False, bar2=0xfffff000),
    'hdr1': dict(card_header=1),
    'flip': dict(directives=['cfgflip 3 13 0 18 e8200008 2']),
    'pref64': dict(bridge_win20=(0xfff00000, 0x000fffff), pref=(0xe8000000, 0xe82fffff, 1, 1, 1)),
    'overflow': None,       # filled in scenarios(): the too-many-bridges world
}


def stats(stderr):
    m = re.search(r'SIM-STATS maps=(\d+) sleep_ms=(\d+) delay_us=(\d+) delay_calls=(\d+)', stderr)
    return tuple(int(x) for x in m.groups()) if m else None


def main():
    failures = 0
    print('== shim prototypes against the target headers ==')
    failures += check_shims()

    tmp = tempfile.mkdtemp(prefix='sim_r1.', dir=os.environ.get('TMPDIR'))
    atexit.register(shutil.rmtree, tmp, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
    exe = os.path.join(tmp, 'sim')
    ok, err = build(PROBE, exe)
    print('== build the unchanged probe (sha256 %s) ==' % hashlib.sha256(open(PROBE, 'rb').read()).hexdigest()[:16])
    if not ok:
        print(err)
        print('sim_r1: FAIL (build)')
        return 1
    print('  ok')

    print('== scenarios ==')
    for label, sc, want_pass, want_fail, want_text, want_map, want_log in scenarios():
        rc, out, err = run(exe, sc)
        st = stats(err)
        why = []
        if rc != 0 or st is None:
            why.append('sim rc=%d %s' % (rc, err.strip()[:120]))
        else:
            maps, sleep_ms, delay_us, delay_calls = st
            report, fail = pr.judge(out, '4242', '%08x' % BUILD)
            if want_pass and fail:
                why.append('gate failed: %s' % fail[0])
            if not want_pass and not any(want_fail in f for f in fail):
                why.append('gate did not name %r: %s' % (want_fail, fail))
            if want_text and not any(want_text in o for o in report):
                why.append('report lacks %r' % want_text)
            if want_log and want_log not in out:
                why.append('probe log lacks %r' % want_log)
            if any('kept reading' in f for f in fail):
                why.append('probe read on after a static VLINE')
            if want_map != (maps == 1):
                why.append('mapped %d times' % maps)
            if maps == 1 and 'map=ok' in out and (delay_calls, delay_us) != (7, 14000):
                why.append('live window delays %d calls %d us, want 7 / 14000' % (delay_calls, delay_us))
            nlines = len(re.findall(r'RDN-R1 4242 ', out))
            pace = 60 if 'frame60' in out else 0
            if sleep_ms != 20 * nlines + pace:
                why.append('sleep %d ms, want %d' % (sleep_ms, 20 * nlines + pace))
        print('  %-4s %-34s%s' % ('ok' if not why else 'FAIL', label, '' if not why else ' ' + '; '.join(why)))
        failures += 1 if why else 0

    print('== mutations (each must make the simulated run fail) ==')
    src = open(PROBE).read()
    good = world()
    for label, old, new, catcher in MUTATIONS:
        if src.count(old) != 1:
            print('  FAIL %-34s anchor found %d times' % (label, src.count(old)))
            failures += 1
            continue
        mpath = os.path.join(tmp, 'mut.m')
        open(mpath, 'w').write(src.replace(old, new))
        mexe = os.path.join(tmp, 'mut')
        ok, err = build(mpath, mexe)
        if not ok:
            print('  FAIL %-34s mutant does not build: %s' % (label, err.strip()[:160]))
            failures += 1
            continue
        if catcher.startswith('maps:'):
            key = catcher[5:]
            wsc = [sc for lab, sc, *_ in scenarios() if lab == 'too many bridges'][0] if key == 'overflow' \
                else world(**MUTATION_WORLDS[key])
            rc0, _, err0 = run(exe, wsc)
            rc, out, err = run(mexe, wsc)
            s0, s1 = stats(err0), stats(err)
            # the unchanged probe refuses this world; the mutant must map it
            caught = s0 is not None and s0[0] == 0 and (s1 is None or s1[0] == 1)
        elif catcher.startswith('judgegood:'):
            rc, out, err = run(mexe, good)
            report, fail = pr.judge(out, '4242', '%08x' % BUILD)
            caught = rc == 0 and any(catcher[10:] in f for f in fail)
        elif catcher.startswith('judge:'):
            rc, out, err = run(mexe, world(scan=False))
            report, fail = pr.judge(out, '4242', '%08x' % BUILD)
            caught = rc == 0 and any(catcher[6:] in f for f in fail)
        else:
            rc, out, err = run(mexe, good)
        if catcher.startswith(('judge:', 'judgegood:', 'maps:')):
            pass
        elif catcher == 'crash':
            caught = rc < 0
        else:
            caught = rc == 3 and ('SIM-VIOLATION %s ' % catcher) in err
        # a crash also truncates the log, and the parser must see that
        if catcher == 'crash':
            report, fail = pr.judge(out, '4242', '%08x' % BUILD)
            caught = caught and any('begin/end' in f or 'sequence' in f for f in fail)
        print('  %-4s %-34s rc=%d %s' % ('ok' if caught else 'FAIL', label, rc,
                                         (err.strip().splitlines() or [''])[0][:70]))
        failures += 0 if caught else 1

    print('sim_r1:', 'PASS' if failures == 0 else 'FAIL (%d)' % failures)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
