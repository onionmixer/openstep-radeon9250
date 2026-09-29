#!/usr/bin/env python3
"""Parse and judge the R1 interrogation log (docs/R1_INTERROGATION_PLAN.md).

  parse_r1.py <log> <runid> <build>
                                print the decoded report, exit 1 on a gate failure;
                                <build> is the 8-hex-digit stamp pack_probe.py
                                printed for the module that ran
  parse_r1.py --self-test       synthetic logs: one good, and negative controls

Only lines carrying `RDN-R1 <runid>` are used, so a stale run in the same
log cannot be read as this one's evidence.  Every line carries `seq=<k>`,
counting from 0 on `begin`; `end` carries `lines=<n>`, the number of lines
the probe wrote including itself.  The sequence must be exactly 0..n-1 with
no gap or repeat -- a log missing lines (syslog drops bursts) fails here, with
the first missing number, instead of producing a silently partial report.
(The probe cannot know its line count in advance: the number of bridges it
reports depends on the machine.)

Line grammar (one fact per line, key=value; every line also has seq=<k>):
  RDN-R1 <runid> begin version=<n> build=<hex8>
  RDN-R1 <runid> pci dev=<bb:dd.f> vid=<hex4> did=<hex4> rev=<hex2> class=<hex6> subsys=<hex4:hex4>
  RDN-R1 <runid> cfg dev=<bb:dd.f> off=<hex2> bytes=<32 hex digits>
  RDN-R1 <runid> bridge dev=<bb:dd.f> bus=<hex8> win1c=<hex8> win20=<hex8> win24=<hex8> win28=<hex8> win2c=<hex8>
  RDN-R1 <runid> mmio bar2=<hex8> type=<mem32|mem64|io|reserved> hdr=<hex2> cmdmem=<0|1> wrap=<0|1> inwindow=<0|1> stable=<0|1> map=<ok|fail|skipped>
  RDN-R1 <runid> live i=<n> frame=<hex8> vline=<hex8>
  RDN-R1 <runid> frame60 before=<hex8> after=<hex8>
  RDN-R1 <runid> reg name=<NAME> off=<hex4> val=<hex8>
  RDN-R1 <runid> stop reason=<word>
  RDN-R1 <runid> end lines=<n>
"""

import importlib.util
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    'radeon_decode', os.path.join(HERE, '..', 'oracle', 'radeon_decode.py'))
dec = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dec)

RV280_IDS = {0x5960, 0x5961, 0x5962, 0x5963, 0x5964, 0x5965, 0x5c61, 0x5c63}

# register -> (offset, bit tests reported by name).  Offsets must equal the
# generated table in ANALYSIS.md; --self-test cross-checks against regtable.py.
REGS = {
    'CLOCK_CNTL_INDEX': 0x0008, 'BUS_CNTL': 0x0030, 'GEN_INT_CNTL': 0x0040,
    'GEN_INT_STATUS': 0x0044, 'CRTC_GEN_CNTL': 0x0050, 'CRTC_EXT_CNTL': 0x0054,
    'DAC_CNTL': 0x0058, 'DAC_CNTL2': 0x007c, 'CONFIG_MEMSIZE': 0x00f8,
    'CONFIG_APER_0_BASE': 0x0100, 'CONFIG_APER_SIZE': 0x0108,
    'HOST_PATH_CNTL': 0x0130, 'MC_FB_LOCATION': 0x0148, 'MC_AGP_LOCATION': 0x014c,
    'AIC_CNTL': 0x01d0, 'CRTC_H_TOTAL_DISP': 0x0200, 'CRTC_H_SYNC_STRT_WID': 0x0204,
    'CRTC_V_TOTAL_DISP': 0x0208, 'CRTC_V_SYNC_STRT_WID': 0x020c, 'CRTC_OFFSET': 0x0224,
    'CRTC_PITCH': 0x022c, 'DISPLAY_BASE_ADDR': 0x023c, 'FP_GEN_CNTL': 0x0284,
    'CRTC2_GEN_CNTL': 0x03f8, 'CP_RB_CNTL': 0x0704, 'CP_RB_RPTR': 0x0710,
    'CP_RB_WPTR': 0x0714, 'CP_CSQ_CNTL': 0x0740, 'SURFACE_CNTL': 0x0b00,
    'DISP_OUTPUT_CNTL': 0x0d64, 'RBBM_STATUS': 0x0e40,
    # added after review Q5 (R2 decisions need them)
    'MEM_SDRAM_MODE_REG': 0x0158, 'CRTC_MORE_CNTL': 0x027c, 'GRPH_BUFFER_CNTL': 0x02f0,
    'DAC_MACRO_CNTL': 0x0d04,
}
LIVE_SAMPLES = 8

LINE = re.compile(r'RDN-R1 (\S+) (\w+)(.*)$')

# The exact grammar of every kind, as RDNR1Probe.m prints it (lower-case hex,
# fixed widths).  A line of this run that does not match is a gate failure,
# never an exception and never silently skipped.
_H = lambda n: '[0-9a-f]{%d}' % n
_DEV = '[0-9a-f]{2}:[0-9a-f]{2}\\.[0-7]'
GRAMMAR = {
    'begin': [('version', '[0-9]+'), ('build', '[0-9a-f]{8}')],
    'pci': [('dev', _DEV), ('vid', _H(4)), ('did', _H(4)), ('rev', _H(2)), ('class', _H(6)),
            ('subsys', _H(4) + ':' + _H(4))],
    'cfg': [('dev', _DEV), ('off', '(00|10|20|30)'), ('bytes', _H(32))],
    'bridge': [('dev', _DEV), ('bus', _H(8)), ('win1c', _H(8)), ('win20', _H(8)), ('win24', _H(8)),
               ('win28', _H(8)), ('win2c', _H(8))],
    'mmio': [('bar2', _H(8)), ('type', '(mem32|mem64|io|reserved)'), ('hdr', _H(2)), ('cmdmem', '[01]'),
             ('wrap', '[01]'), ('inwindow', '[01]'), ('stable', '[01]'), ('map', '(ok|fail|skipped)')],
    'live': [('i', '[0-7]'), ('frame', _H(8)), ('vline', _H(8))],
    'frame60': [('before', _H(8)), ('after', _H(8))],
    'reg': [('name', '[A-Z0-9_]+'), ('off', _H(4)), ('val', _H(8))],
    'stop': [('reason', '[a-z0-9-]+')],
    'end': [('lines', '[0-9]+')],
}
KIND_RE = dict((k, re.compile('^' + ''.join(' %s=(%s)' % (n, r) for n, r in f) + ' seq=([0-9]+)\\s*$'))
               for k, f in GRAMMAR.items())
SINGLE = ('begin', 'end', 'mmio', 'frame60')


def parse(text, runid):
    facts = {'pci': [], 'cfg': {}, 'bridge': [], 'live': [], 'reg': {}, 'stop': [],
             'malformed': [], 'duplicate': []}
    lines = 0
    begin = end = None
    seqs = []
    seen = {}
    for raw in text.splitlines():
        m = LINE.search(raw)
        if not m or m.group(1) != runid:
            continue
        kind = m.group(2)
        lines += 1
        g = KIND_RE[kind].match(m.group(3)) if kind in KIND_RE else None
        if not g:
            facts['malformed'].append(raw[m.start():][:120])
            seqs.append(-1)
            continue
        names = [n for n, _ in GRAMMAR[kind]]
        vals = [x for x in g.groups()]
        # each field pattern may contain one group of its own: pick the outer ones
        kv = {}
        gi = 0
        for n, r in GRAMMAR[kind]:
            kv[n] = vals[gi]
            gi += 1 + re.compile(r).groups
        kv['seq'] = vals[-1]
        seqs.append(int(kv['seq']))
        if kind in SINGLE:
            seen[kind] = seen.get(kind, 0) + 1
            if seen[kind] > 1:
                facts['duplicate'].append(kind)
        if kind == 'begin':
            begin = 0
            facts['begin_seq'] = int(kv['seq'])
            facts['version'] = kv['version']
            facts['build'] = kv['build']
        elif kind == 'end':
            end = int(kv['lines'])
            facts['end_seq'] = int(kv['seq'])
        elif kind == 'pci':
            facts['pci'].append(kv)
        elif kind == 'cfg':
            key = (kv['dev'], int(kv['off'], 16))
            if key in facts['cfg']:
                facts['duplicate'].append('cfg %s %s' % key)
            facts['cfg'][key] = bytes.fromhex(kv['bytes'])
        elif kind == 'bridge':
            facts['bridge'].append(kv)
        elif kind == 'mmio':
            facts['mmio'] = kv
        elif kind == 'frame60':
            facts['frame60'] = (int(kv['before'], 16), int(kv['after'], 16))
        elif kind == 'live':
            facts['live'].append((int(kv['i']), int(kv['frame'], 16), int(kv['vline'], 16)))
        elif kind == 'reg':
            if kv['name'] in facts['reg']:
                facts['duplicate'].append('reg ' + kv['name'])
            facts['reg'][kv['name']] = (int(kv['off'], 16), int(kv['val'], 16))
        elif kind == 'stop':
            facts['stop'].append(kv['reason'])
    facts['seqs'] = seqs
    return facts, lines, begin, end


R1_VERSION = '1'


def window_contains(word, start, length):
    """Type-1 header memory window word (base low 16, limit high 16, each the
    top 12 bits of an address) -- the host's own reading, to cross-check the
    probe's inwindow bit."""
    base = (word & 0xfff0) << 16
    limit = (((word >> 16) & 0xfff0) << 16) | 0xfffff
    return base <= limit and base <= start and start + length - 1 <= limit


MAX_LINES = 5000       # 8 buses x 32 devices x 8 functions of pci+bridge lines is far below


def prefetch_usable(win24, win28, win2c):
    """NetBSD pcireg.h:1409-1412: type in bits 3-0 of 0x24 (nonzero = 64-bit),
    upper halves at 0x28/0x2c.  Only a window wholly below 4 GiB counts."""
    t = win24 & 0xf
    return t == 0 or (t == 1 and win28 == 0 and win2c == 0)


def host_precheck(facts, dev, mm, out):
    """Recompute every field of the probe's map decision from the logged
    config bytes, independently of the probe's C code, and compare."""
    fail = []
    cfg0 = facts['cfg'][(dev, 0x00)]
    cfg1 = facts['cfg'][(dev, 0x10)]
    command = int.from_bytes(cfg0[4:6], 'little')
    hdr = cfg0[14] & 0x7f
    bar2 = int.from_bytes(cfg1[8:12], 'little')
    if bar2 & 1:
        btype = 'io'
    else:
        btype = {0: 'mem32', 4: 'mem64'}.get(bar2 & 6, 'reserved')     # pcireg.h:491-495
    start = bar2 & 0xfffffff0
    wrap = start + 0x2000 - 1 > 0xffffffff
    cbus = int(dev.split(':')[0], 16)
    on_path = [br for br in facts['bridge']
               if (int(br['bus'], 16) >> 8 & 0xff) <= cbus <= (int(br['bus'], 16) >> 16 & 0xff)]
    overflow = 'too-many-bridges' in facts['stop']
    inw = (not wrap and not overflow and (cbus == 0 or len(on_path) > 0) and
           all(window_contains(int(br['win20'], 16), start, 0x2000) or
               (prefetch_usable(int(br['win24'], 16), int(br['win28'], 16), int(br['win2c'], 16)) and
                window_contains(int(br['win24'], 16), start, 0x2000)) for br in on_path))
    host = {'bar2': '%08x' % bar2, 'type': btype, 'hdr': '%02x' % hdr, 'cmdmem': str(command >> 1 & 1),
            'wrap': '1' if wrap else '0', 'inwindow': '1' if inw else '0'}
    out.append('host recomputed from cfg: %s over %d bridge(s) on the path' % (
        ' '.join('%s=%s' % kv for kv in sorted(host.items())), len(on_path)))
    for k, v in sorted(host.items()):
        if mm[k] != v:
            fail.append('probe %s=%s but host computes %s from the logged config' % (k, mm[k], v))
    host_ok = btype == 'mem32' and start != 0 and hdr == 0 and command >> 1 & 1 and not wrap and inw
    if mm['map'] != 'skipped' and not host_ok:
        fail.append('probe attempted a map the host pre-check refuses')
    return fail


def judge(text, runid, build):
    """Return (report_lines, failures).  Never raises on log content: an
    unexpected exception becomes a failure naming it."""
    try:
        return _judge(text, runid, build)
    except Exception as e:          # a hostile log must fail the gate, not crash it
        return [], ['parser raised %s: %s' % (type(e).__name__, e)]


def _judge(text, runid, build):
    out = []
    fail = []
    facts, lines, begin, end = parse(text, runid)
    for bad in facts['malformed']:
        fail.append('malformed line: %s' % bad)
    for d in facts['duplicate']:
        fail.append('duplicate line kind: %s' % d)
    if begin is None or end is None:
        fail.append('begin/end line missing or malformed (run %s incomplete or wrong runid)' % runid)
        return out, fail
    # provenance (PLAN section 4): the log must name the module that was built
    if facts.get('version') != R1_VERSION:
        fail.append('probe version %s, parser expects %s' % (facts.get('version'), R1_VERSION))
    b = facts.get('build')
    if b is None or not re.fullmatch(r'[0-9a-f]{8}', b):
        fail.append('build stamp missing or malformed: %r' % b)
    elif b == '00000000':
        fail.append('module is unstamped (not built by target-build.sh)')
    elif b != build:
        fail.append('build stamp %s is not the expected %s' % (b, build))
    out.append('probe version %s build %s' % (facts.get('version'), b))
    seqs = facts['seqs']
    if end > MAX_LINES:
        fail.append('end lines=%d is beyond any possible probe run (%d)' % (end, MAX_LINES))
        return out, fail
    want = list(range(end))
    if seqs != want:
        missing = sorted(set(want) - set(seqs))
        fail.append('sequence broken: probe wrote %d lines, log holds %d; first missing seq %s%s' % (
            end, lines, missing[0] if missing else 'none',
            '' if len(set(seqs)) == len(seqs) else ' (repeats present)'))
    if facts.get('begin_seq') != 0 or facts.get('end_seq') != end - 1:
        fail.append('begin must be seq 0 and end the last seq (begin %s, end %s of %d)' % (
            facts.get('begin_seq'), facts.get('end_seq'), end))
    for kind, key in (('pci', 'dev'), ('bridge', 'dev')):
        devs = [r[key] for r in facts[kind]]
        if len(devs) != len(set(devs)):
            fail.append('duplicate line kind: %s for the same device' % kind)
    cards = [p for p in facts['pci'] if int(p['vid'], 16) == 0x1002 and int(p['did'], 16) in RV280_IDS]
    out.append('RV280 functions found: %d' % len(cards))
    if len(cards) != 1:
        fail.append('expected exactly one RV280 function, found %d' % len(cards))
    for p in cards:
        out.append('  %s 1002:%s rev %s class %s subsys %s' % (p['dev'], p['did'], p['rev'], p['class'], p['subsys']))
    if facts['stop']:
        fail.append('probe stopped early: %s' % ', '.join(facts['stop']))
    mm = facts.get('mmio')
    if len(cards) == 1:
        dev = cards[0]['dev']
        missing_cfg = [o for o in (0x00, 0x10, 0x20, 0x30) if (dev, o) not in facts['cfg']]
        if missing_cfg:
            fail.append('cfg dump of the card incomplete: offsets %s missing' % ', '.join('%02x' % o for o in missing_cfg))
    if mm is None:
        fail.append('mmio line missing')
    else:
        out.append('BAR2 %s type=%s hdr=%s cmdmem=%s wrap=%s inwindow=%s stable=%s map=%s' % tuple(
            mm[k] for k in ('bar2', 'type', 'hdr', 'cmdmem', 'wrap', 'inwindow', 'stable', 'map')))
        if mm['map'] != 'ok':
            fail.append('MMIO pre-check refused or map failed: %s' % mm)
        if mm['map'] != 'skipped' and not (mm['type'] == 'mem32' and mm['hdr'] == '00' and mm['cmdmem'] == '1'
                                           and mm['wrap'] == '0' and mm['inwindow'] == '1' and mm['stable'] == '1'
                                           and int(mm['bar2'], 16) & 0xfffffff0):
            fail.append('probe attempted a map its own pre-check fields refuse: %s' % mm)
        if len(cards) == 1 and not missing_cfg:
            fail.extend(host_precheck(facts, dev, mm, out))
    # liveness (review Q5 item 2): the gate is VLINE only.  Eight samples
    # 2 ms apart span 14 ms = 0.839 frames at 59.94 Hz, so a frame edge is
    # not guaranteed; FRAME is recorded over 60 ms (> 2 frames = 33.4 ms)
    # and is NOT a gate, because whether it counts in VGA mode is unconfirmed.
    live = sorted(facts['live'])
    if [i for i, _, _ in live] != list(range(LIVE_SAMPLES)):
        fail.append('liveness samples: indices %s, want 0..%d once each' % ([i for i, _, _ in live], LIVE_SAMPLES - 1))
    else:
        vlines = {(v >> 16) & 0x7ff for _, _, v in live}
        out.append('liveness: %d distinct VLINE values in %d samples' % (len(vlines), LIVE_SAMPLES))
        if len(vlines) < 2:
            fail.append('liveness: VLINE static (%d distinct value)' % len(vlines))
            # plan 4-B step 1: nothing more is read through a mapping that
            # may not decode
            if facts['reg'] or 'frame60' in facts:
                fail.append('probe kept reading after a static VLINE')
    f60 = facts.get('frame60')
    if f60 is None:
        fail.append('frame60 line missing')
    else:
        d = (f60[1] - f60[0]) & 0xffffffff
        out.append('CRTC_CRNT_FRAME over 60 ms: +%d (recorded, not a gate; 3-5 expected if it counts: 3.6 at 59.94 Hz, 4.2 at 70.09 Hz)' % d)
    # registers
    reg = facts['reg']
    missing = [n for n in REGS if n not in reg]
    wrongoff = [n for n in reg if n in REGS and reg[n][0] != REGS[n]]
    if missing:
        fail.append('registers missing: %s' % ', '.join(missing))
    if wrongoff:
        fail.append('registers at an unexpected offset: %s' % ', '.join(wrongoff))
    if missing:
        return out, fail
    v = {n: reg[n][1] for n in reg}
    mib = 1024 * 1024
    # HDP_APER_CNTL is bit 23 of HOST_PATH_CNTL (radeonfbreg.h:1047, radeon_reg.h:994)
    out.append('CONFIG_MEMSIZE %d MiB, CONFIG_APER_SIZE %d MiB, HDP_APER_CNTL=%d' % (
        v['CONFIG_MEMSIZE'] // mib, v['CONFIG_APER_SIZE'] // mib, (v['HOST_PATH_CNTL'] >> 23) & 1))
    fb0, fb1 = dec.decode_mc_location(v['MC_FB_LOCATION'])
    ag0, ag1 = dec.decode_mc_location(v['MC_AGP_LOCATION'])
    out.append('MC_FB_LOCATION %08x-%08x, MC_AGP_LOCATION %08x-%08x, APER_0_BASE %08x, DISPLAY_BASE_ADDR %08x' % (
        fb0, fb1, ag0, ag1, v['CONFIG_APER_0_BASE'], v['DISPLAY_BASE_ADDR']))
    t = dec.decode_crtc(v['CRTC_H_TOTAL_DISP'], v['CRTC_H_SYNC_STRT_WID'],
                        v['CRTC_V_TOTAL_DISP'], v['CRTC_V_SYNC_STRT_WID'])
    out.append('CRTC1 words say %dx%d, totals %dx%d, hsync %s, vsync %s' % (
        t['hdisp'], t['vdisp'], t['htotal'], t['vtotal'],
        'negative' if t['nhsync'] else 'positive', 'negative' if t['nvsync'] else 'positive'))
    out.append('PLL_DIV_SEL (console divider slot) = %d' % dec.decode_pll_div_sel(v['CLOCK_CNTL_INDEX']))
    out.append('CRTC_GEN_CNTL %08x  CRTC_EXT_CNTL %08x  CRTC2_GEN_CNTL %08x' % (
        v['CRTC_GEN_CNTL'], v['CRTC_EXT_CNTL'], v['CRTC2_GEN_CNTL']))
    out.append('DAC_CNTL %08x  DAC_CNTL2 %08x  DISP_OUTPUT_CNTL %08x  FP_GEN_CNTL %08x  SURFACE_CNTL %08x' % (
        v['DAC_CNTL'], v['DAC_CNTL2'], v['DISP_OUTPUT_CNTL'], v['FP_GEN_CNTL'], v['SURFACE_CNTL']))
    out.append('CP_CSQ_CNTL %08x  CP_RB_CNTL %08x  RPTR %08x  WPTR %08x  AIC_CNTL %08x  BUS_CNTL %08x  RBBM_STATUS %08x' % (
        v['CP_CSQ_CNTL'], v['CP_RB_CNTL'], v['CP_RB_RPTR'], v['CP_RB_WPTR'], v['AIC_CNTL'], v['BUS_CNTL'], v['RBBM_STATUS']))
    out.extend(findings(facts, v))
    return out, fail


def findings(facts, v):
    """R2 design inputs, not R1 gate failures.  Bit positions:
    CSQ mode bits 28-31 (radeonfbreg.h:3228-3232), PCIGART_TRANSLATE_EN bit 0
    (radeonfbreg.h:3249), BUS_MASTER_DIS bit 6 (radeonfbreg.h:276),
    CRTC_DISPLAY_DIS bit 10 (radeonfbreg.h:426), CRTC_EXT_DISP_EN / CRTC_EN /
    CRTC_DISP_REQ_EN_B bits 24/25/26 (radeonfbreg.h:446-448),
    RBBM_ACTIVE bit 31 (radeonfbreg.h:1549).  RV280 FB location aligned to the
    memory size: xf86 radeon_driver.c:1498-1513."""
    out = ['findings (R2 inputs):']
    mode = (v['CP_CSQ_CNTL'] >> 28) & 0xf
    out.append('  CP command queue mode %d (%s)' % (mode, 'off' if mode == 0 else 'ON -- R2 step 3 must stop'))
    out.append('  on-chip PCI GART translate %s' % ('ON' if v['AIC_CNTL'] & 1 else 'off'))
    out.append('  BUS_CNTL.BUS_MASTER_DIS=%d (chip-internal)' % ((v['BUS_CNTL'] >> 6) & 1))
    cards = [p for p in facts['pci'] if int(p['vid'], 16) == 0x1002 and int(p['did'], 16) in RV280_IDS]
    if len(cards) == 1:
        hdr = facts['cfg'].get((cards[0]['dev'], 0x00))
        if hdr is not None and len(hdr) >= 6:
            cmd = hdr[4] | (hdr[5] << 8)
            out.append('  PCI command %04x: memory=%d io=%d busmaster=%d' % (cmd, cmd >> 1 & 1, cmd & 1, cmd >> 2 & 1))
        else:
            out.append('  PCI command register: cfg dump at offset 00 missing')
    g = v['CRTC_GEN_CNTL']
    out.append('  CRTC1: EXT_DISP_EN=%d CRTC_EN=%d DISP_REQ_EN_B=%d, DISPLAY_DIS=%d (EXT_CNTL)' % (
        g >> 24 & 1, g >> 25 & 1, g >> 26 & 1, v['CRTC_EXT_CNTL'] >> 10 & 1))
    out.append('  engine RBBM_ACTIVE=%d' % (v['RBBM_STATUS'] >> 31 & 1))
    mem = v['CONFIG_MEMSIZE'] or 0x800000
    aper = v['CONFIG_APER_SIZE']
    if aper > mem:
        mem = aper
    base = v['CONFIG_APER_0_BASE']
    want = base & ~(mem - 1) & 0xffffffff
    fb0, _ = dec.decode_mc_location(v['MC_FB_LOCATION'])
    out.append('  MC_FB start %08x vs RV280-aligned aperture base %08x: %s' % (
        fb0, want, 'same' if fb0 == want else 'DIFFERENT -- R2 would rewrite the MC map'))
    return out


# ---- self-test -----------------------------------------------------------

def synthetic(runid='t1', drop=None, other_runid_line=False, dead=False, mcfb=0xe7ffe000,
              build='1234abcd'):
    m = dec.oracle.MODES[0]          # a 640x480 console
    words = dec.oracle.rfb_crtc_words(m)
    vals = dict((n, 0) for n in REGS)
    vals.update(CONFIG_MEMSIZE=0x08000000, CONFIG_APER_SIZE=0x08000000,
                CONFIG_APER_0_BASE=0xe0000000, MC_FB_LOCATION=mcfb,
                MC_AGP_LOCATION=0xefffe800, DISPLAY_BASE_ADDR=0xe0000000,
                CLOCK_CNTL_INDEX=0x00000000, CRTC_H_TOTAL_DISP=words[0],
                CRTC_H_SYNC_STRT_WID=words[1], CRTC_V_TOTAL_DISP=words[2],
                CRTC_V_SYNC_STRT_WID=words[3])
    # config words, packed little-endian the way the probe prints them:
    # vendor 1002 device 5960, command 0x0003 (io+mem, no bus master),
    # class 030000 rev 01; BAR0 e0000008 (prefetchable VRAM), BAR1 d001 (io),
    # BAR2 e8200000 (MMIO)
    def cfgline(off, words):
        return 'cfg dev=04:00.0 off=%02x bytes=%s' % (off, struct.pack('<4I', *words).hex())
    def window(base, limit):
        return ((limit >> 16) & 0xfff0) << 16 | ((base >> 16) & 0xfff0)
    body = ['bridge dev=00:1e.0 bus=%08x win1c=00000000 win20=%08x win24=%08x win28=00000000 win2c=00000000' % (
                0x00040400, window(0xe8000000, 0xe82fffff), window(0xe0000000, 0xe7ffffff)),
            'pci dev=04:00.0 vid=1002 did=5960 rev=01 class=030000 subsys=1002:0000',
            cfgline(0x00, (0x59601002, 0x00000003, 0x03000001, 0)),
            cfgline(0x10, (0xe0000008, 0x0000d001, 0xe8200000, 0)),
            cfgline(0x20, (0, 0, 0, 0x2002174b)),
            cfgline(0x30, (0, 0, 0, 0x0000010b)),
            'mmio bar2=e8200000 type=mem32 hdr=00 cmdmem=1 wrap=0 inwindow=1 stable=1 map=ok',
            'frame60 before=00000064 after=%08x' % (0x64 if dead else 0x68)]
    for i in range(LIVE_SAMPLES):
        body.append('live i=%d frame=%08x vline=%08x' % (i, 100 + (0 if dead else i), (0 if dead else (i * 37) % 525) << 16))
    for n, off in REGS.items():
        body.append('reg name=%s off=%04x val=%08x' % (n, off, vals[n]))
    n = len(body) + 2
    lines = ['RDN-R1 %s begin version=1 build=%s seq=0' % (runid, build)] + \
            ['RDN-R1 %s %s seq=%d' % (runid, b, i + 1) for i, b in enumerate(body)] + \
            ['RDN-R1 %s end lines=%d seq=%d' % (runid, n, n - 1)]
    if drop is not None:
        del lines[drop]
    if other_runid_line:
        lines.insert(3, 'RDN-R1 old reg name=CONFIG_MEMSIZE off=00f8 val=01000000')
    return '\n'.join('Sep 15 10:00:00 nextonion mach: ' + l for l in lines) + '\n'


def self_test():
    failures = 0
    # offsets must match the generated register table source
    spec = importlib.util.spec_from_file_location('regtable', os.path.join(HERE, '..', 'oracle', 'regtable.py'))
    rt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rt)
    tabs = {k: rt.load(p) for k, p in rt.HEADERS}
    for n, off in REGS.items():
        hv = {tabs[k][n][0][0] for k in tabs if n in tabs[k]}
        if hv != {off}:
            print('FAIL offset of %s here %04x, headers %s' % (n, off, sorted(hv)))
            failures += 1
    # (label, log, failure substring that must be present -- None means the
    # gate must pass --, report substring that must be present)
    cases = [
        ('good', synthetic(), None, '640x480'),
        ('good: command decoded', synthetic(), None, 'memory=1 io=1 busmaster=0'),
        ('good: window recomputed', synthetic(), None, 'wrap=0 over 1 bridge'),
        ('MC map differs', synthetic(mcfb=0xefffe800), None, 'DIFFERENT'),
        ('dropped reg line', synthetic(drop=20), 'first missing seq 20', None),
        ('stale runid mixed in', synthetic(other_runid_line=True), None, 'CONFIG_MEMSIZE 128 MiB'),
        ('dead scanout', synthetic(dead=True), 'VLINE static', None),
        ('dead scanout, probe read on', synthetic(dead=True), 'kept reading', None),
        ('BAR2 64-bit refused', synthetic().replace('type=mem32', 'type=mem64'), 'own pre-check fields refuse', None),
        ('repeated line', synthetic() + synthetic().splitlines()[5] + '\n', 'repeats present', None),
        ('wrong runid asked', synthetic(runid='t2'), 'begin/end line missing', None),
        ('unstamped build', synthetic(build='00000000'), 'unstamped', None),
        ('other build', synthetic(build='1234abce'), 'not the expected', None),
        ('no build field', synthetic().replace(' build=1234abcd', ''), 'malformed line: RDN-R1 t1 begin', None),
        ('probe says outside window', synthetic().replace('inwindow=1', 'inwindow=0'), 'host computes 1', None),
        ('bridge window excludes BAR2', synthetic().replace('win20=e820e800', 'win20=e810e800'), 'host computes 0', None),
        ('bar2 differs from cfg', synthetic().replace('bar2=e8200000', 'bar2=e8300000'), 'probe bar2=e8300000 but host computes e8200000', None),
        ('malformed value', synthetic().replace('val=08000000', 'val=g8000000', 1), 'malformed line', None),
        ('malformed seq', synthetic().replace('seq=3\n', 'seq=x3\n', 1), 'malformed line', None),
        ('field missing', synthetic().replace(' win20=e820e800', ''), 'malformed line', None),
        ('extra seq key', synthetic().replace(' seq=5\n', ' seq=1 seq=5\n', 1), 'malformed line', None),
        ('odd-length bytes', synthetic().replace('bytes=0210', 'bytes=00210', 1), 'malformed line', None),
        ('negative sample index', synthetic().replace('live i=0 ', 'live i=-0 ', 1), 'malformed line', None),
        ('duplicate sample index', synthetic().replace('live i=7 ', 'live i=6 ', 1), 'liveness samples', None),
        ('duplicate register', synthetic().replace('reg name=BUS_CNTL off=0030', 'reg name=CLOCK_CNTL_INDEX off=0008', 1), 'duplicate line kind', None),
        ('unknown kind', synthetic().replace('frame60 before', 'frame61 before', 1), 'malformed line', None),
        ('cfg chunk missing', '\n'.join(l for l in synthetic().splitlines() if 'off=30 ' not in l) + '\n', 'offsets 30 missing', None),
        ('huge end count', synthetic().replace('end lines=', 'end lines=99999', 1), 'beyond any possible', None),
        ('probe hdr lies', synthetic().replace('hdr=00', 'hdr=01'), 'host computes 00', None),
        ('probe wrap lies', synthetic().replace('wrap=0', 'wrap=1'), 'host computes 0', None),
        ('map with stable=0', synthetic().replace('stable=1', 'stable=0'), 'own pre-check fields refuse', None),
        ('64-bit prefetch above 4 GiB', synthetic().replace('win20=e820e800', 'win20=0000fff0').replace('win24=e7f0e000', 'win24=e82fe801').replace('win28=00000000', 'win28=00000001'), 'host computes 0', None),
        ('64-bit prefetch below 4 GiB', synthetic().replace('win20=e820e800', 'win20=0000fff0').replace('win24=e7f0e000', 'win24=e82fe801'), None, 'wrap=0 over 1 bridge'),
    ]
    for label, text, want_fail, want_text in cases:
        out, fail = judge(text, 't1', '1234abcd')
        if want_fail is None:
            ok = not fail
        else:
            ok = any(want_fail in f for f in fail)
        ok = ok and (want_text is None or any(want_text in o for o in out))
        print('%-4s %-28s failures=%d%s' % ('ok' if ok else 'FAIL', label, len(fail),
                                             '' if not fail else ' (' + fail[0] + ')'))
        failures += 0 if ok else 1
    # every single-line corruption of the good log must fail the gate without
    # raising: bad hex, missing or extra keys, truncation, sign, case
    corrupt = [lambda l: l.replace('seq=', 'seq=x'), lambda l: l.replace('lines=', 'lines=z'),
               lambda l: l.replace('bytes=', 'bytes=0'), lambda l: l.replace('val=', 'val=g'),
               lambda l: l.replace('bus=', 'bus=q'), lambda l: l.replace('win20=', 'nope='),
               lambda l: l.replace('vid=', 'vid=zz'), lambda l: l.replace('dev=04:00.0', 'dev=zz'),
               lambda l: l.replace('i=', 'i=-'), lambda l: l.replace('before=', 'before=xyz'),
               lambda l: l[:len(l) // 2], lambda l: l.replace(' seq=', ' seq=1 seq='),
               lambda l: l.replace('mem32', 'MEM32'), lambda l: l + ' extra=1']
    good = synthetic().splitlines()
    tried = leaked = 0
    for c in corrupt:
        for i in range(len(good)):
            t = good[:]
            t[i] = c(t[i])
            if t[i] == good[i]:
                continue
            tried += 1
            _, fail = judge('\n'.join(t) + '\n', 't1', '1234abcd')
            if not fail or any('parser raised' in f for f in fail):
                leaked += 1
                print('FAIL corruption passed or raised: %s' % t[i][-70:])
    print('%-4s %-28s %d corrupted logs, %d leaked' % ('ok' if leaked == 0 and tried > 200 else 'FAIL',
                                                     'single-line corruption', tried, leaked))
    failures += 0 if leaked == 0 and tried > 200 else 1
    return failures


def main(argv):
    if argv[1:] == ['--self-test']:
        f = self_test()
        print('parse_r1 self-test:', 'PASS' if f == 0 else 'FAIL (%d)' % f)
        return 1 if f else 0
    if len(argv) != 4:
        sys.stderr.write(__doc__)
        return 2
    out, fail = judge(open(argv[1], errors='replace').read(), argv[2], argv[3])
    print('\n'.join(out))
    for f in fail:
        print('GATE FAIL:', f)
    print('R1 gate:', 'PASS' if not fail else 'FAIL')
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
