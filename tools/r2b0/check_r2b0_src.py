#!/usr/bin/env python3
"""Source and host-object rules for OSRDNDisplay's R2b-0 build (docs/R2B0_IMPL_PLAN.md 6-3).

  check_r2b0_src.py <workdir>    compile host objects into <workdir>, run every
                                 rule on the real files, then every mutation
                                 (each must be caught by the rules it targets,
                                 in this run); exit 1 on any failure

Class (OSRDNDisplay.m; comments and strings blanked):
  class-no-hw        no port, MMIO helper, osrdn_in*/osrdn_out*, IOReadRegister,
                     IOWriteRegister, IOReadModifyWriteRegister or splhigh call
  class-enter-revert enterLinearMode calls IOLog only; revertToVGAMode IOLog and
                     [super revertToVGAMode] once, nothing else
  class-forward      get/setIntValues:forParameter:count: begin with
                     `if (!osrdn_name_is(parameterName, ...))` whose one
                     statement is `return [super <same selector>...];`
  class-no-char      no getCharValues:/setCharValues: override
  class-maps         mapFrameBufferAtPhysicalAddress 1, IOMapPhysicalIntoIOTask 1
                     (length OSRDN_MMIO_LENGTH), setMemoryRangeList 1,
                     IOUnmapPhysicalFromIOTask only in free (OSRDN_MMIO_LENGTH)
  class-key          valueForStringKey: once, in init, then freeString:
  class-init-free    init returns nil when the superclass init fails (the
                     superclass has already freed the object there,
                     conservative, see below) and [self free] on its own failures;
                     [super free] appears only inside -free
Record (osrdn_record.m, osrdn_pll.m):
  mmio-writes        rdnMmioWrite8 2 and rdnMmioWrite32 1 call sites, all in
                     pllGroup (R2a's argument rules); none in osrdn_record.m
  record-no-map      no IOMapPhysicalIntoIOTask/IOUnmapPhysicalFromIOTask call
  raw-ports          no inb/inw/inl/outb/outw/outl call and no ioPorts.h import
  port-args          osrdn_outl(PCI_CFG_ADDR) and osrdn_inl(PCI_CFG_DATA) only in
                     pciRead; osrdn_outb only in vgaSnapshot with VGA_SEQ_INDEX,
                     VGA_GR_INDEX, crtcBase or VGA_ATTR_INDEX; osrdn_inb only in
                     vgaSnapshot with VGA_MISC_READ, VGA_SEQ_INDEX, VGA_SEQ_DATA,
                     VGA_GR_INDEX, VGA_GR_DATA, crtcBase, crtcBase + 1, statusPort,
                     VGA_ATTR_INDEX or VGA_ATTR_READ; no numeric port
  constants          the port, register, length and mask constants
  spl                osrdn_pll.m: R2a's pair in pllGroup; osrdn_record.m: one
                     pair in vgaSnapshot (between: osrdn_inb/osrdn_outb only) and
                     one in osrdn_record_request (between: no call)
  time               IOGetTimestamp never between splhigh and splx; no / or %
                     applied to an ns_time_t variable (only (unsigned int)d / 1000U)
  long-width         no field width with the long modifier (kernel sprintf)
  cc-names           no identifier id/in/out
  no-switch          no switch in any bundle .m
  port-unit          osrdn_port.m defines exactly osrdn_inb/outb/inl/outl, one
                     statement each, no static/inline; it alone imports ioPorts.h
  mmio-copy          RDNR2aMMIO.m and .h equal R2a's byte for byte
  import-only        no #include in the bundle sources
  tables             osrdnRegs equals parse_r2b0.REGS in R2a's order, r2aPll
                     equals parse_r2b0.PLL
  no-lto             no -flto in the makefiles or the target build script
Objects (gcc-12 -m32 against the target headers):
  obj-ports          osrdn_record.o and osrdn_pll.o at -O0 -fno-inline hold no
                     in/out instruction
  obj-div64          no __udivdi3/__umoddi3/__divdi3 reference in either object
  helper-width-O0/O2 RDNR2aMMIO.o as R2a
"""

import importlib.util
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
TPROJ = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj')
R2A_TPROJ = os.path.join(PROJ, 'probe', 'RDNR2aProbe', 'RDNR2aProbe_reloc.tproj')
TARGET_BUILD = os.path.join(HERE, 'target-build-r2b0.sh')
FILES = ('OSRDNDisplay.m', 'osrdn_record.m', 'osrdn_pll.m', 'osrdn_port.m', 'RDNR2aMMIO.m')
HEADERS = ('OSRDNDisplay.h', 'osrdn_record.h', 'osrdn_pll.h', 'osrdn_port.h', 'osrdn_expect.h', 'RDNR2aMMIO.h')


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


c2 = _load('check_r2a_src_for_r2b0', os.path.join(PROJ, 'tools', 'r2a', 'check_r2a_src.py'))
pb = _load('parse_r2b0_for_src', os.path.join(HERE, 'parse_r2b0.py'))
blank, function_bodies, calls, args = c2.blank, c2.function_bodies, c2.calls, c2.args

HW_CALLS = ('inb', 'inw', 'inl', 'outb', 'outw', 'outl', 'osrdn_inb', 'osrdn_outb', 'osrdn_inl', 'osrdn_outl',
            'rdnMmioRead32', 'rdnMmioWrite8', 'rdnMmioWrite32', 'IOReadRegister', 'IOWriteRegister',
            'IOReadModifyWriteRegister', 'splhigh')
OUTB_PORTS = {'(IOEISAPortAddress)VGA_SEQ_INDEX', '(IOEISAPortAddress)VGA_GR_INDEX', '(IOEISAPortAddress)crtcBase',
              '(IOEISAPortAddress)VGA_ATTR_INDEX'}
INB_PORTS = {'(IOEISAPortAddress)VGA_MISC_READ', '(IOEISAPortAddress)VGA_SEQ_INDEX', '(IOEISAPortAddress)VGA_SEQ_DATA',
             '(IOEISAPortAddress)VGA_GR_INDEX', '(IOEISAPortAddress)VGA_GR_DATA', '(IOEISAPortAddress)crtcBase',
             '(IOEISAPortAddress)(crtcBase + 1)', '(IOEISAPortAddress)statusPort', '(IOEISAPortAddress)VGA_ATTR_INDEX',
             '(IOEISAPortAddress)VGA_ATTR_READ'}
CONSTANTS = {
    'osrdn_record.m': {'PCI_CFG_ADDR': 0xcf8, 'PCI_CFG_DATA': 0xcfc, 'VGA_ATTR_INDEX': 0x3c0, 'VGA_ATTR_READ': 0x3c1,
                       'VGA_SEQ_INDEX': 0x3c4, 'VGA_SEQ_DATA': 0x3c5, 'VGA_MISC_READ': 0x3cc, 'VGA_GR_INDEX': 0x3ce,
                       'VGA_GR_DATA': 0x3cf, 'VGA_CRTC_COLOR': 0x3d4, 'VGA_CRTC_MONO': 0x3b4,
                       'VGA_STATUS_OFFSET': 6, 'VGA_PAS': 0x20, 'VGA_SEQ_COUNT': 5, 'VGA_CRTC_COUNT': 25,
                       'VGA_GR_COUNT': 9, 'VGA_ATTR_FIRST': 0x10, 'VGA_ATTR_COUNT': 5, 'REG_CLOCK_CNTL_INDEX': 8,
                       'BAR0_REG': 0x10, 'BAR2_REG': 0x18, 'LIVE_GAP_US': 2000, 'FRAME_GAP_MS': 60,
                       'SECOND_GAP_MS': 1000, 'LINE_PACE_MS': 20, 'GATE_COUNT': 32},
    'osrdn_pll.m': {'REG_CLOCK_CNTL_INDEX': 8, 'REG_CLOCK_CNTL_DATA': 0xc, 'PLL_WR_EN': 0x80, 'PLL_INDEX_MASK': 0x3f,
                    'LOW_BYTE': 0xff},
    'osrdn_record.h': {'OSRDN_MMIO_LENGTH': 0x4000, 'OSRDN_FB_LENGTH': 0x800000, 'OSRDN_R_INVALID': -706,
                       'OSRDN_R_BUSY': -725, 'OSRDN_R_LATCHED': -728, 'OSRDN_R_KEY_NO': -729, 'OSRDN_STATE_COUNT': 9},
}


def methods(code):
    """{selector-ish name: (start, end)} for Objective-C method definitions at column 0."""
    out = {}
    for m in re.finditer(r'^[-+]\s*(\([^)]*\))?\s*([A-Za-z_]\w*)[^\n{]*(\n[^\n{]*)*?\n\{', code, re.M):
        end = code.find('\n}', m.end())
        out[m.group(2)] = (m.start(), end if end > 0 else len(code))
    return out


def const_value(code, name):
    vals = re.findall(r'^#define\s+%s\s+\(?(-?(?:0x[0-9a-fA-F]+|[0-9]+))[uUlL]*\)?\s*$' % name, code, re.M)
    return [int(v, 0) for v in vals]


def spl_pairs(code, fn_bodies):
    """[(function, splhigh position, splx position)]"""
    pairs = []
    for pos, _ in calls(code, 'splhigh'):
        fn = next((n for n, b in fn_bodies.items() if b[0] <= pos < b[1]), None)
        sx = [p for p, _ in calls(code, 'splx') if p > pos and fn and p < fn_bodies[fn][1]]
        pairs.append((fn, pos, sx[0] if sx else None))
    return pairs


def source_rules(src, makefiles, build_script):
    """src: {file name: text}.  Return {rule: [problems]}."""
    r = {}
    cls = blank(src['OSRDNDisplay.m'])
    rec = blank(src['osrdn_record.m'])
    pll = blank(src['osrdn_pll.m'])
    port = blank(src['osrdn_port.m'])
    meth = methods(cls)

    r['class-no-hw'] = ['%s called in the class' % n for n in HW_CALLS if calls(cls, n)]

    p = []
    for name, allowed in (('enterLinearMode', {'IOLog'}), ('revertToVGAMode', {'IOLog'})):
        if name not in meth:
            p.append('%s not defined' % name)
            continue
        body = cls[meth[name][0]:meth[name][1]].split('{', 1)[1]
        called = set(re.findall(r'\b([A-Za-z_]\w*)\s*\(', body)) - {'unsigned', 'int', 'if'}
        if not called <= allowed:
            p.append('%s calls %s' % (name, sorted(called - allowed)))
        sends = re.findall(r'\[\s*(\w+)\s+(\w+)', body)
        want = [('super', 'revertToVGAMode')] if name == 'revertToVGAMode' else []
        if sends != want:
            p.append('%s message sends %s, want %s' % (name, sends, want))
    r['class-enter-revert'] = p

    # the one-owner latch: claimed only after our own accept and before the
    # superclass probe, released only when the superclass says NO, and never
    # released anywhere else (a latch left held means no display owner at all)
    p = []
    if 'probe' not in meth:
        p.append('+probe: not defined')
    else:
        body = cls[meth['probe'][0]:meth['probe'][1]].split('{', 1)[1]
        ia = body.find('osrdn_probe_accept(')
        ic = body.find('osrdn_probe_claim(')
        isup = body.find('[super probe:')
        ir = body.find('osrdn_probe_release(')
        if min(ia, ic, isup, ir) < 0:
            p.append('+probe: wants osrdn_probe_accept, osrdn_probe_claim, [super probe: and '
                     'osrdn_probe_release, found at %s' % [ia, ic, isup, ir])
        elif not (ia < ic < isup < ir):
            p.append('+probe: order accept=%d claim=%d super=%d release=%d, want accept < claim < super < release'
                     % (ia, ic, isup, ir))
        for n, want in (('osrdn_probe_claim', 1), ('osrdn_probe_release', 1), ('osrdn_probe_accept', 1)):
            if len(re.findall(r'\b%s\s*\(' % n, body)) != want:
                p.append('+probe: calls %s %d times, want %d' % (n, len(re.findall(r'\b%s\s*\(' % n, body)), want))
    for name in ('free', 'initFromDeviceDescription', 'enterLinearMode', 'revertToVGAMode'):
        if name in meth and 'osrdn_probe_release' in cls[meth[name][0]:meth[name][1]]:
            p.append('%s releases the probe latch' % name)
    r['class-latch'] = p

    p = []
    for name, param in (('getIntValues', 'OSRDN_STATE_PARAM'), ('setIntValues', 'OSRDN_RECORD_PARAM')):
        if name not in meth:
            p.append('%s not defined' % name)
            continue
        body = cls[meth[name][0]:meth[name][1]].split('{', 1)[1]
        m = re.match(r'\s*if\s*\(\s*!\s*osrdn_name_is\s*\(\s*parameterName\s*,\s*%s\s*\)\s*\)\s*'
                     r'return\s*\[\s*super\s+%s\s*:\s*parameterArray\s+forParameter\s*:\s*parameterName\s+'
                     r'count\s*:\s*count\s*\]\s*;' % (param, name), body)
        if not m:
            p.append('%s does not begin with the forwarding if and its one return [super %s:...]' % (name, name))
    r['class-forward'] = p

    r['class-no-char'] = ['%s overridden' % n for n in ('getCharValues', 'setCharValues') if n in meth]

    p = []
    for n, want in (('mapFrameBufferAtPhysicalAddress', 1), ('setMemoryRangeList', 1)):
        k = len(re.findall(r'\b%s\s*:' % n, cls))
        if k != want:
            p.append('%s %d, want %d' % (n, k, want))
    mp = calls(cls, 'IOMapPhysicalIntoIOTask')
    if len(mp) != 1 or len(args(mp[0][1])) != 3 or args(mp[0][1])[1] != 'OSRDN_MMIO_LENGTH':
        p.append('IOMapPhysicalIntoIOTask calls %s' % [a for _, a in mp])
    for pos, a in calls(cls, 'IOUnmapPhysicalFromIOTask'):
        if 'free' not in meth or not (meth['free'][0] <= pos < meth['free'][1]) or args(a)[1:] != ['OSRDN_MMIO_LENGTH']:
            p.append('IOUnmapPhysicalFromIOTask(%s) outside free or with another length' % a)
    r['class-maps'] = p

    p = []
    keys = [m.start() for m in re.finditer(r'valueForStringKey\s*:', cls)]
    init = meth.get('initFromDeviceDescription')
    if len(keys) != 1 or not init or not (init[0] <= keys[0] < init[1]):
        p.append('valueForStringKey: at %d places, want once in init' % len(keys))
    elif not re.search(r'freeString\s*:', cls[keys[0]:init[1]]):
        p.append('no freeString: after valueForStringKey:')
    r['class-key'] = p

    p = []
    freem = meth.get('free')
    for m in re.finditer(r'\[\s*super\s+free\s*\]', cls):
        if freem is None or not (freem[0] <= m.start() < freem[1]):
            p.append('[super free] outside -free (at %d): on the init failure path the superclass has '
                     'already freed the object -- conservative: this rule is not '
                     'sourced from a reference this project trusts (plan 15-5)' % m.start())
    if init:
        body = cls[init[0]:init[1]]
        if not re.search(r'initFromDeviceDescription\s*:\s*deviceDescription\s*\]\s*==\s*nil\s*\)\s*'
                         r'return\s+nil\s*;', body):
            p.append('init does not return nil when the superclass init fails')
        selfs = re.findall(r'return\s*\[\s*self\s+free\s*\]', body)
        if len(selfs) < 1:
            p.append('no return [self free] in init')
    r['class-init-free'] = p

    p = []
    pllb = function_bodies(pll)
    w8, w32 = calls(pll, 'rdnMmioWrite8'), calls(pll, 'rdnMmioWrite32')
    if len(w8) != 2 or any(not c2.within(pos, pllb.get('pllGroup')) for pos, _ in w8):
        p.append('rdnMmioWrite8 sites %d (want 2, in pllGroup)' % len(w8))
    for _, a in w8:
        a = args(a)
        if len(a) != 3 or a[1] != 'REG_CLOCK_CNTL_INDEX' or not re.search(r'&\s*(PLL_INDEX_MASK|LOW_BYTE)\s*\)*$', a[2]):
            p.append('rdnMmioWrite8 arguments %s' % a)
    if len(w32) != 1 or any(not c2.within(pos, pllb.get('pllGroup')) for pos, _ in w32) or \
            any(args(a)[1:] != ['REG_CLOCK_CNTL_INDEX', 'p'] for _, a in w32):
        p.append('rdnMmioWrite32 sites %s (want 1, in pllGroup, of p)' % [a for _, a in w32])
    for n in ('rdnMmioWrite8', 'rdnMmioWrite32'):
        if calls(rec, n):
            p.append('%s called in osrdn_record.m' % n)
    r['mmio-writes'] = p

    r['record-no-map'] = ['%s in %s' % (n, f) for f, c in (('osrdn_record.m', rec), ('osrdn_pll.m', pll))
                          for n in ('IOMapPhysicalIntoIOTask', 'IOUnmapPhysicalFromIOTask') if calls(c, n)]

    p = []
    for f, c, raw in (('osrdn_record.m', rec, src['osrdn_record.m']), ('osrdn_pll.m', pll, src['osrdn_pll.m'])):
        for n in ('inb', 'inw', 'inl', 'outb', 'outw', 'outl'):
            if calls(c, n):
                p.append('%s called in %s' % (n, f))
        if re.search(r'^\s*#\s*import\s*<driverkit/i386/ioPorts\.h>', raw, re.M):
            p.append('%s imports ioPorts.h' % f)
    r['raw-ports'] = p

    p = []
    recb = function_bodies(rec)
    for n, fn, allowed in (('osrdn_outl', 'pciRead', {'(IOEISAPortAddress)PCI_CFG_ADDR'}),
                           ('osrdn_inl', 'pciRead', {'(IOEISAPortAddress)PCI_CFG_DATA'}),
                           ('osrdn_outb', 'vgaSnapshot', OUTB_PORTS),
                           ('osrdn_inb', 'vgaSnapshot', INB_PORTS)):
        cs = calls(rec, n)
        if not cs:
            p.append('%s never called: the rule saw nothing' % n)
        for pos, a in cs:
            port_arg = args(a)[0] if args(a) else ''
            if not c2.within(pos, recb.get(fn)):
                p.append('%s outside %s' % (n, fn))
            if re.sub(r'\s+', ' ', port_arg) not in allowed:
                p.append('%s port %s not allowed' % (n, port_arg))
        if calls(pll, n):
            p.append('%s in osrdn_pll.m' % n)
    r['port-args'] = p

    p = []
    for f, want in CONSTANTS.items():
        code = blank(src[f])
        for n, v in want.items():
            got = const_value(code, n)
            if got != [v]:
                p.append('%s %s defined as %s, want one %s' % (f, n, got, v))
    r['constants'] = p

    p = []
    pairs = spl_pairs(pll, pllb)
    if len(pairs) != 1 or pairs[0][0] != 'pllGroup' or pairs[0][2] is None:
        p.append('osrdn_pll.m spl pairs %s, want one in pllGroup' % [(f, s is not None) for f, _, s in pairs])
    else:
        between = pll[pairs[0][1] + len('splhigh('):pairs[0][2]]
        for m in re.finditer(r'\b([A-Za-z_]\w*)\s*\(', between):
            if m.group(1) not in c2.HELPERS + ('if', 'while', 'for'):
                p.append('call of %s between splhigh and splx in pllGroup' % m.group(1))
    pairs = spl_pairs(rec, recb)
    fns = sorted(f or '?' for f, _, _ in pairs)
    if fns != ['osrdn_record_request', 'vgaSnapshot'] or any(x is None for _, _, x in pairs):
        p.append('osrdn_record.m spl pairs in %s, want osrdn_record_request and vgaSnapshot' % fns)
    else:
        for fn, sh, sx in pairs:
            between = rec[sh + len('splhigh('):sx]
            ok = {'vgaSnapshot': ('osrdn_inb', 'osrdn_outb', 'if', 'for'), 'osrdn_record_request': ('if',)}[fn]
            for m in re.finditer(r'\b([A-Za-z_]\w*)\s*\(', between):
                if m.group(1) not in ok:
                    p.append('call of %s between splhigh and splx in %s' % (m.group(1), fn))
    if len(calls(rec, 'splx')) != 2 or len(calls(pll, 'splx')) != 1:
        p.append('splx call sites %d/%d, want 2/1' % (len(calls(rec, 'splx')), len(calls(pll, 'splx'))))
    r['spl'] = p

    p = []
    for f, c, b in (('osrdn_record.m', rec, recb), ('osrdn_pll.m', pll, pllb)):
        for fn, sh, sx in spl_pairs(c, b):
            if sx is not None and 'IOGetTimestamp' in c[sh:sx]:
                p.append('IOGetTimestamp between splhigh and splx in %s %s' % (f, fn))
        for name, (a, e, params) in b.items():
            body = c[a:e]
            nsvars = set(re.findall(r'\bns_time_t\s+([A-Za-z_]\w*)', params + ' ' + body))
            nsvars |= set(re.findall(r'\bns_time_t\s+[A-Za-z_]\w*\s*,\s*([A-Za-z_]\w*)', params + ' ' + body))
            for m in re.finditer(r'([A-Za-z_]\w*|\))\s*([/%])(?![*/=])', body):
                left = m.group(1)
                if left in nsvars and not re.search(r'\(\s*unsigned\s+int\s*\)\s*$', body[:m.start()]):
                    p.append('%s applied to ns_time_t %s in %s' % (m.group(2), left, name))
                if left == ')':
                    head = body[:m.start() + 1]
                    if re.search(r'\(\s*(%s)\s*[-+]' % '|'.join(nsvars), head[-40:]) if nsvars else False:
                        p.append('%s applied to an ns_time_t expression in %s' % (m.group(2), name))
    r['time'] = p

    r['long-width'] = ['%s: %s' % (f, x) for f in FILES
                       for x in re.findall(r'%[-+ #0]*[0-9]+l[a-zA-Z]', blank(src[f], strings=False))]
    r['cc-names'] = ['%s line %d' % (f, blank(src[f])[:m.start()].count('\n') + 1) for f in FILES
                     for m in re.finditer(r'(?<![A-Za-z0-9_.])(id|in|out)(?![A-Za-z0-9_:])', blank(src[f]))]
    r['no-switch'] = ['switch in %s' % f for f in FILES if re.search(r'\bswitch\b', blank(src[f]))]

    p = []
    pb_ = function_bodies(port)
    if sorted(pb_) != ['osrdn_inb', 'osrdn_inl', 'osrdn_outb', 'osrdn_outl']:
        p.append('osrdn_port.m defines %s' % sorted(pb_))
    if re.search(r'\b(static|inline|__inline__)\b', port):
        p.append('static or inline in osrdn_port.m')
    for n, (a, b, _) in pb_.items():
        if port[a:b].split('{', 1)[1].count(';') != 1:
            p.append('%s is not one statement' % n)
    for f in FILES + HEADERS:
        if f != 'osrdn_port.m' and re.search(r'^\s*#\s*import\s*<driverkit/i386/ioPorts\.h>', src[f], re.M):
            p.append('%s imports ioPorts.h' % f)
    r['port-unit'] = p

    r['mmio-copy'] = ['%s differs from R2a\'s' % f for f in ('RDNR2aMMIO.m', 'RDNR2aMMIO.h')
                      if src[f] != open(os.path.join(R2A_TPROJ, f)).read()]
    r['import-only'] = ['#include in %s' % f for f in FILES + HEADERS if re.search(r'^\s*#\s*include\b', src[f], re.M)]

    p = []
    m = re.search(r'static const osrdn_reg osrdnRegs\[\] = \{(.*?)\n\};', src['osrdn_record.m'], re.S)
    regs = re.findall(r'\{\s*"([A-Z0-9_]+)",\s*(0x[0-9a-fA-F]+)\s*\}', m.group(1)) if m else []
    r2a_src = open(os.path.join(R2A_TPROJ, 'RDNR2aProbe.m')).read()
    m2 = re.search(r'static const r2a_reg r2aRegs\[\] = \{(.*?)\n\};', r2a_src, re.S)
    r2a_regs = re.findall(r'\{\s*"([A-Z0-9_]+)",\s*(0x[0-9a-fA-F]+)\s*\}', m2.group(1))
    if [(n, int(o, 16)) for n, o in regs] != [(n, int(o, 16)) for n, o in r2a_regs] or \
            dict((n, int(o, 16)) for n, o in regs) != pb.REGS:
        p.append('osrdnRegs (%d) is not R2a\'s table in R2a\'s order and the parser\'s' % len(regs))
    m = re.search(r'const r2a_reg r2aPll\[R2A_PLL_COUNT\] = \{(.*?)\n\};', src['osrdn_pll.m'], re.S)
    plls = [(n, int(o, 16)) for n, o in re.findall(r'\{\s*"([A-Z0-9_]+)",\s*(0x[0-9a-fA-F]+)\s*\}', m.group(1))] if m else []
    if plls != pb.PLL or const_value(blank(src['osrdn_pll.h']), 'R2A_PLL_COUNT') != [len(pb.PLL)]:
        p.append('r2aPll %s differs from the parser %s' % (plls, pb.PLL))
    r['tables'] = p

    r['no-lto'] = ['-flto in %s' % n for n, t in list(makefiles.items()) + [('target-build-r2b0.sh', build_script)]
                   if '-flto' in t]
    return r


def compile_obj(work, src, name, out, opt, extra=()):
    path = os.path.join(work, name)
    open(path, 'w').write(src[name])
    cmd = ['gcc-12', '-m32', '-nostdinc', '-fno-pic', '-ffreestanding', '-fno-builtin', '-I', work, '-I', c2.HOSTSHIM,
           '-isystem', c2.R, '-isystem', c2.R + '/ansi', '-isystem', c2.R + '/bsd', '-isystem', c2.R + '/mach',
           '-isystem', c2.R + '/kernserv', '-isystem', c2.R + '/architecture',
           '-DKERNEL', '-DMACH_USER_API', '-DMACH', '-DNeXT=1', '-D__NeXT__', '-D_NEXT_SOURCE', '-Di386',
           '-D__ARCHITECTURE__="i386"', '-x', 'objective-c', '-fnext-runtime', '-w'] + list(opt) + list(extra) + \
          ['-c', path, '-o', out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0, r.stderr


def all_rules(work, src, makefiles, build_script):
    os.makedirs(work, exist_ok=True)
    for h in HEADERS:
        open(os.path.join(work, h), 'w').write(src[h])
    res = source_rules(src, makefiles, build_script)
    res['obj-ports'], res['obj-div64'] = [], []
    for name in ('osrdn_record.m', 'osrdn_pll.m'):
        obj = os.path.join(work, name + '.o')
        ok, err = compile_obj(work, src, name, obj, ['-O0', '-fno-inline'])
        if not ok:
            res['compile-' + name] = [err.strip()[:300]]
            continue
        dis = c2.disasm(obj)
        for fn, ins in c2.st.functions(dis).items():
            for _, i, _ in ins:
                if re.match(r'(in|out)[bwl]?\s|(rep[a-z]* )?(ins|outs)[bwld]?\b', i):
                    res['obj-ports'].append('%s: %s in %s' % (name, i, fn))
        und = subprocess.run(['nm', '-u', obj], capture_output=True, text=True).stdout
        for s in ('__udivdi3', '__umoddi3', '__divdi3', '__moddi3'):
            if re.search(r'\b%s\b' % s, und):
                res['obj-div64'].append('%s references %s' % (name, s))
    for opt in ('O0', 'O2'):
        obj = os.path.join(work, 'mmio-%s.o' % opt)
        ok, err = compile_obj(work, src, 'RDNR2aMMIO.m', obj, ['-' + opt])
        res['helper-width-' + opt] = c2.helper_rule(c2.disasm(obj)) if ok else ['compile: ' + err.strip()[:200]]
    return res


REC = 'osrdn_record.m'
PLL = 'osrdn_pll.m'
CLS = 'OSRDNDisplay.m'

# (label, file, old, new, rules that must fail)
MUTATIONS = [
    ('port read in the class', CLS, '    rdnState.enterCount++;\n',
     '    rdnState.enterCount++;\n    (void)osrdn_inb(0x3c4);\n', ['class-no-hw', 'class-enter-revert']),
    ('MMIO write in enterLinearMode', CLS, '    rdnState.enterCount++;\n',
     '    rdnState.enterCount++;\n    rdnMmioWrite8(mmioBase, 8, 0);\n', ['class-no-hw', 'class-enter-revert']),
    ('revert calls the record', CLS, '    rdnState.revertCount++;\n',
     '    rdnState.revertCount++;\n    (void)osrdn_record_request(&rdnState, 0, 0);\n', ['class-enter-revert']),
    ('revert without super', CLS, '    [super revertToVGAMode];\n', '', ['class-enter-revert']),
    ('unknown set name swallowed', CLS,
     '        return [super setIntValues:parameterArray forParameter:parameterName count:count];\n',
     '        return IO_R_UNSUPPORTED;\n', ['class-forward']),
    ('get forwards after doing something', CLS,
     '    if (!osrdn_name_is(parameterName, OSRDN_STATE_PARAM))\n',
     '    rdnState.enterCount += 0;\n    if (!osrdn_name_is(parameterName, OSRDN_STATE_PARAM))\n', ['class-forward']),
    ('char override added', CLS, '- setBrightness:(int)level token:(int)token\n',
     '- (IOReturn)getCharValues:(unsigned char *)a forParameter:(IOParameterName)n count:(unsigned *)c\n{\n'
     '    return [super getCharValues:a forParameter:n count:c];\n}\n\n- setBrightness:(int)level token:(int)token\n',
     ['class-no-char']),
    ('second MMIO map', CLS, '    mmioMapped = YES;\n',
     '    mmioMapped = YES;\n    (void)IOMapPhysicalIntoIOTask(0, OSRDN_MMIO_LENGTH, &fb);\n', ['class-maps']),
    ('map with a literal length', CLS, 'IOMapPhysicalIntoIOTask((unsigned)rdnState.bar2, OSRDN_MMIO_LENGTH, &mmioBase)',
     'IOMapPhysicalIntoIOTask((unsigned)rdnState.bar2, 0x2000, &mmioBase)', ['class-maps']),
    ('key read in setIntValues', CLS,
     '    return osrdn_record_request(&rdnState, parameterArray, count);\n',
     '    (void)[[[self deviceDescription] configTable] valueForStringKey:"RDN R2B0 Record"];\n'
     '    return osrdn_record_request(&rdnState, parameterArray, count);\n', ['class-key']),
    ('key string not freed', CLS, '    if (key != 0)\n        [table freeString:key];\n', '', ['class-key']),
    ('probe latch: latch claimed before our own accept', CLS, '    if (!osrdn_probe_accept((int)rc, (int)bus, (int)dev, (int)fn))\n        return NO;\n    if (!osrdn_probe_claim())\n        return NO;                 /* a second instance for the one card */\n    if ([super probe:deviceDescription])\n        return YES;\n    osrdn_probe_release();\n    return NO;',
     '    if (!osrdn_probe_claim())\n        return NO;\n    if (!osrdn_probe_accept((int)rc, (int)bus, (int)dev, (int)fn))\n        return NO;\n    if ([super probe:deviceDescription])\n        return YES;\n    osrdn_probe_release();\n    return NO;', ['class-latch']),
    ('probe latch: latch claimed after the superclass probe', CLS, '    if (!osrdn_probe_claim())\n        return NO;                 /* a second instance for the one card */\n    if ([super probe:deviceDescription])\n        return YES;\n    osrdn_probe_release();\n    return NO;',
     '    if (![super probe:deviceDescription])\n        return NO;\n    if (!osrdn_probe_claim())\n        return NO;\n    osrdn_probe_release();\n    return YES;', ['class-latch']),
    ('probe latch: latch never released', CLS, '    if (!osrdn_probe_claim())\n        return NO;                 /* a second instance for the one card */\n    if ([super probe:deviceDescription])\n        return YES;\n    osrdn_probe_release();\n    return NO;',
     '    if (!osrdn_probe_claim())\n        return NO;\n    return [super probe:deviceDescription];', ['class-latch']),
    ('probe latch: latch released in free', CLS, '- free\n{\n',
     '- free\n{\n    osrdn_probe_release();\n', ['class-latch']),
    ('init failure frees super', CLS, '        rdnState.initWhy = "mmio-map";\n        mmioBase = 0;\n        osrdn_init_line(&rdnState);\n        return [self free];\n',
     '        rdnState.initWhy = "mmio-map";\n        mmioBase = 0;\n        osrdn_init_line(&rdnState);\n        return [super free];\n',
     ['class-init-free']),
    ('superclass init failure double-frees', CLS,
     '    if ([super initFromDeviceDescription:deviceDescription] == nil)\n        return nil;\n',
     '    if ([super initFromDeviceDescription:deviceDescription] == nil)\n        return [super free];\n',
     ['class-init-free']),
    ('third rdnMmioWrite8 site', PLL,
     '        rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX, (unsigned char)(index & PLL_INDEX_MASK));\n',
     '        rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX, (unsigned char)(index & PLL_INDEX_MASK));\n'
     '        rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX, (unsigned char)(index & PLL_INDEX_MASK));\n', ['mmio-writes']),
    ('MMIO write in the record', REC, '    indexEnd = 0;\n', '    indexEnd = 0;\n    rdnMmioWrite32(base, 0x50, 0);\n',
     ['mmio-writes']),
    ('map in the record', REC, '    indexEnd = 0;\n',
     '    indexEnd = 0;\n    (void)IOUnmapPhysicalFromIOTask(base, OSRDN_MMIO_LENGTH);\n', ['record-no-map']),
    ('raw outb in the record', REC, '    osrdn_outl((IOEISAPortAddress)PCI_CFG_ADDR, address);\n',
     '    outb(0x80, 0);\n    osrdn_outl((IOEISAPortAddress)PCI_CFG_ADDR, address);\n', ['raw-ports']),
    ('data port stored', REC, '        osrdn_outb((IOEISAPortAddress)VGA_GR_INDEX, v->grIndex);\n',
     '        osrdn_outb((IOEISAPortAddress)VGA_GR_DATA, v->grIndex);\n', ['port-args']),
    ('DAC port read', REC, '        v->grIndex = osrdn_inb((IOEISAPortAddress)VGA_GR_INDEX);\n',
     '        v->grIndex = osrdn_inb((IOEISAPortAddress)0x3c9);\n', ['port-args']),
    ('PCI latch outside pciRead', REC, '    if (rc == 0) {\n        idWord = pciRead(bus, dev, fn, 0x00);\n',
     '    if (rc == 0) {\n        osrdn_outl((IOEISAPortAddress)PCI_CFG_ADDR, 0x80000000UL);\n        idWord = pciRead(bus, dev, fn, 0x00);\n',
     ['port-args']),
    ('attribute PAS constant changed', REC, '#define VGA_PAS             0x20\n', '#define VGA_PAS             0x00\n',
     ['constants']),
    ('MMIO length changed', 'osrdn_record.h', '#define OSRDN_MMIO_LENGTH   0x4000', '#define OSRDN_MMIO_LENGTH   0x8000',
     ['constants']),
    ('IOLog inside the VGA step', REC, '        v->seqIndex = osrdn_inb((IOEISAPortAddress)VGA_SEQ_INDEX);\n',
     '        IOLog("x\\n");\n        v->seqIndex = osrdn_inb((IOEISAPortAddress)VGA_SEQ_INDEX);\n', ['spl']),
    ('call inside the test-and-set', REC, '        st->inProgress = 1;\n',
     '        st->inProgress = 1;\n        IODelay(1);\n', ['spl']),
    ('third masked section', REC, '    moving = 0;\n', '    moving = splhigh();\n    splx(moving);\n    moving = 0;\n',
     ['spl']),
    ('timestamp inside the test-and-set', REC, '        st->inProgress = 1;\n',
     '        st->inProgress = 1;\n        IOGetTimestamp(&t);\n', ['time', 'spl', 'compile-osrdn_record.m']),
    ('64-bit division of the clock', REC, '    return (unsigned long)((unsigned int)d / 1000U);\n',
     '    return (unsigned long)(d / 1000U);\n', ['time', 'obj-div64']),
    ('64-bit remainder', REC, '    return (unsigned long)((unsigned int)d / 1000U);\n',
     '    return (unsigned long)(d % 1000000000ULL);\n', ['time', 'obj-div64']),
    ('long hex with a width', REC,
     '"reg name=%s off=%04x val=%08x", osrdnRegs[i].name, osrdnRegs[i].offset, U(osrdnRegVal[i]));',
     '"reg name=%s off=%04x val=%08lx", osrdnRegs[i].name, osrdnRegs[i].offset, osrdnRegVal[i]);', ['long-width']),
    ('identifier out', REC, '    int s, i;\n    unsigned int crtcBase, statusPort;\n',
     '    int s, i, out;\n    unsigned int crtcBase, statusPort;\n', ['cc-names']),
    ('switch on the gate step', REC, '    gateLine(0, "apersize", v, OSRDN_FB_LENGTH, v >= OSRDN_FB_LENGTH, &refused);\n',
     '    switch (refused) { default: break; }\n    gateLine(0, "apersize", v, OSRDN_FB_LENGTH, v >= OSRDN_FB_LENGTH, &refused);\n',
     ['no-switch']),
    ('fifth port function', 'osrdn_port.m', '\nvoid\nosrdn_outl(',
     '\nunsigned short\nosrdn_inw(IOEISAPortAddress port)\n{\n    return inw(port);\n}\n\nvoid\nosrdn_outl(', ['port-unit']),
    ('ioPorts.h in the record', REC, '#import "osrdn_port.h"\n', '#import <driverkit/i386/ioPorts.h>\n#import "osrdn_port.h"\n',
     ['raw-ports', 'port-unit']),
    ('MMIO helper edited', 'RDNR2aMMIO.m', '    return *(volatile unsigned long *)(base + offset);\n',
     '    return *(volatile unsigned long *)(base + offset) = 0;\n', ['mmio-copy', 'helper-width-O0', 'helper-width-O2']),
    ('#include in the record', REC, '#import <stdio.h>                   /* sprintf */\n',
     '#include <stdio.h>\n', ['import-only']),
    ('register table reordered', REC, '    { "BUS_CNTL",              0x0030 },\n    { "GEN_INT_CNTL",          0x0040 },\n',
     '    { "GEN_INT_CNTL",          0x0040 },\n    { "BUS_CNTL",              0x0030 },\n', ['tables']),
    ('PLL table index changed', PLL, '    { "PPLL_DIV_1",            0x05 },\n', '    { "PPLL_DIV_1",            0x04 },\n',
     ['tables']),
]


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    work = argv[1]
    src = dict((f, open(os.path.join(TPROJ, f)).read()) for f in FILES + HEADERS)
    # The class rules below describe the R2b-0 build, which is finished and was
    # verified on the machine (docs/R2B0_RESULT.md, run 789526262).  The live
    # OSRDNDisplay.m has since become R2b's, which drives the hardware, so the
    # class is read from the archive of exactly what ran -- extracted from the
    # tar that built that run -- while every other file is still read live,
    # because R2b reuses them unchanged.  R2b's own class rules are in
    # tools/r2b/check_r2b_src.py.
    archive = os.path.join(PROJ, 'build', 'r2b0', 'src-789526262',
                           'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj')
    for f in ('OSRDNDisplay.m', 'OSRDNDisplay.h'):
        if os.path.exists(os.path.join(archive, f)):
            src[f] = open(os.path.join(archive, f)).read()
    makefiles = dict((n, open(os.path.join(TPROJ, n)).read()) for n in os.listdir(TPROJ) if n.startswith('Makefile'))
    makefiles.update(dict(('../' + n, open(os.path.join(TPROJ, '..', n)).read())
                          for n in os.listdir(os.path.join(TPROJ, '..')) if n.startswith('Makefile')))
    build_script = open(TARGET_BUILD).read() if os.path.exists(TARGET_BUILD) else ''
    failures = 0
    base = all_rules(os.path.join(work, 'base'), src, makefiles, build_script)
    print('== rules on the real files ==')
    for rule in sorted(base):
        ok = not base[rule]
        print('  %-4s %-20s %s' % ('ok' if ok else 'FAIL', rule, '' if ok else '; '.join(map(str, base[rule]))[:300]))
        failures += 0 if ok else 1
    if not os.path.exists(TARGET_BUILD):
        print('  FAIL no-lto: target-build-r2b0.sh not found')
        failures += 1
    print('== mutations (each caught by the rules it targets) ==')
    for label, which, old, new, want in MUTATIONS:
        if src[which].count(old) != 1:
            print('  FAIL %-42s anchor found %d times' % (label, src[which].count(old)))
            failures += 1
            continue
        ms = dict(src)
        ms[which] = src[which].replace(old, new)
        res = all_rules(os.path.join(work, 'mut'), ms, makefiles, build_script)
        caught = [w for w in want if res.get(w)]
        unexpected_compile = [k for k in res if k.startswith('compile') and res[k] and k not in want]
        ok = len(caught) == len(want) and not unexpected_compile
        print('  %-4s %-42s caught by %s%s' % ('ok' if ok else 'FAIL', label, caught or 'nothing',
                                              '' if not unexpected_compile else ' (did not compile: %s)' % unexpected_compile))
        failures += 0 if ok else 1
    lto = dict(makefiles)
    lto['Makefile.preamble'] = lto.get('Makefile.preamble', '') + '\nOTHER_CFLAGS += -flto\n'
    ok = bool(source_rules(src, lto, build_script)['no-lto'])
    print('  %-4s %-42s caught by %s' % ('ok' if ok else 'FAIL', '-flto in a makefile', ['no-lto'] if ok else 'nothing'))
    failures += 0 if ok else 1
    print('check_r2b0_src: %s' % ('PASS' if failures == 0 else 'FAIL (%d)' % failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
