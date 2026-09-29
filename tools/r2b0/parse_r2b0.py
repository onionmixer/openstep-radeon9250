#!/usr/bin/env python3
"""Parse and judge the R2b-0 activation-boot record (docs/R2B0_IMPL_PLAN.md 6-1).

  parse_r2b0.py <log> <runid> <build> [--tool <rdnr2b0 output>] [--out DIR]
        print the report; exit 0 PASS-ENTER, 3 PASS-REFUSE, 1 FAIL
  parse_r2b0.py --self-test

The R2a parser (tools/r2a/parse_r2a.py) is loaded read-only as a private
instance, and through it R1's gates run on this log: sequence, grammar, one
card, the map decision recomputed from the logged config bytes, liveness,
registers at their offsets.  R2a's PLL group checks run too, on twelve
indices.  R2a's comparison with R1 does NOT run: the activation boot is
expected to differ from R1's VESA boot in exactly the registers this record
exists to measure (Q13 verdict 0-7); those differences are reported as facts.

Line grammar (every record line: RDN-R2B0 <runid> <kind> ... seq=<k>):
  R2a's kinds (bridge with ctl3c, pll k up to 11), and
  begin version=2 boot=<hex8> build=<hex8> enter=<n> revert=<n> cmode=<n> loc=<bb:dd.f> key=<yes|no>
  time d0..d6=<us|unm|sat> s60=<us|unm|sat> f60=<n> s1000=<us|unm|sat> f1000=<n>
  vga part=1 misc=<hex2> dec=<0|1> base=<hex3> sqi=<hex2> sq=<hex10> crtci=<hex2> crtc=<hex50>
  vga part=2 gri=<hex2> gr=<hex18> attri=<hex2> attr=<hex10>
  idxend val=<hex8>          the CLOCK_CNTL_INDEX read after the PLL groups
  gate step=<0|1> name=<name> val=<hex8> want=<hex8> pass=<1|0|na>
  verdict gates=32 refused=<n> result=<enter|refuse>
Lines outside the run: probe, init, enter, revert, refused (RDN-R2B0 <kind> ...),
and the driver's own state line, which the tool's State read makes it write:
  RDN-R2B0 state boot=<hex8> build=<hex8> records=<n> last=<runid> flags=<hex8> cmode=<n> loc=<bb:dd.f>
That line is the in-boot proof: it must stand before the record's begin line
and carry the same boot nonce, build, console mode and location.  A logger marker is NOT used: this
machine's syslog.conf sends user.notice nowhere (docs/R1C_RESULT.md fact 5,
build/r1c/syslog-check.txt), so a logger marker would never arrive.

FAIL: any R1/R2a gate, a gate line that disagrees with the parser's own
evaluation, boot nonce / location / cmode disagreements, a register the
boot cannot change that differs from R2a's raw log, VGA lines after a PLL
stop or missing after a complete PLL snapshot, no driver state line before the
record.  PASS-ENTER: every gate passes.  PASS-REFUSE: a gate refuses.
Time is record-only; VGA differences from the kernel table are record-only.
"""

import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


r2a = _load('parse_r2a_for_r2b0_logs', os.path.join(PROJ, 'tools', 'r2a', 'parse_r2a.py'))
core = r2a.core                     # the private R1 core inside that instance
gen = _load('gen_expect_r2b0_for_parser', os.path.join(HERE, 'gen_expect_r2b0.py'))

R2A_LOG = gen.R2A_LOG
R2A_RUNID = gen.R2A_RUNID
REGS = dict(r2a.REGS)
PLL = list(r2a.PLL) + [('PPLL_DIV_1', 0x05), ('PPLL_DIV_2', 0x06)]
WANT_LOC = '03:0b.0'
# The framebuffer length the driver maps and its apersize/memsize gates compare
# against.  3 MiB up to R3b-0, 8 MiB from R3b-1 (docs/R3_MULTIMODE_PLAN.md 22-2).
# The only archived record was made by build e48c2e8d (run 789526262); a log is
# judged against the value ITS build was compiled with.
FB_LENGTH = 0x800000
FB_LENGTH_BY_BUILD = {'e48c2e8d': 0x300000}


def fb_length(build):
    return FB_LENGTH_BY_BUILD.get(build, FB_LENGTH)
REFCLK_KHZ = 27000                  # docs/R1C_RESULT.md (BIOS refclk)

# Registers the boot cannot change (docs/R2B0_IMPL_PLAN.md 6-1): FAIL if they
# differ from the R2a raw log.
IMMOVABLE = ['CONFIG_MEMSIZE', 'CONFIG_APER_SIZE', 'CONFIG_APER_0_BASE', 'MEM_CNTL', 'MEM_TIMING_CNTL']

# The kernel VGA console's table, bytes as they sit in the mirror kernel
# (ref/openstep/ps2/mach_kernel __TEXT,__const; S17): SEQ at VA 0x1d54de,
# CRTC at 0x1d54e3, ATTR at 0x1d54fc, GR at 0x1d5511.  _VGASetGraphicsMode
# SEQ1 is expected 01: that is what the console leaves, measured on this
# machine in R2a (run 789467668) and R2b-0 (run 789526262), where the driver's
# VGA snapshot equalled this table with SEQ1 = 01.
KERNEL_VA = {'seq': (0x1d54de, 5), 'crtc': (0x1d54e3, 25), 'attr': (0x1d54fc, 21), 'gr': (0x1d5511, 9)}
KERNEL_SEQ = bytes.fromhex('03 21 0f 00 06')
KERNEL_CRTC = bytes.fromhex('5f 4f 50 82 54 80 0b 3e 00 40 00 00 00 00 00 59 ea 8c df 28 00 e7 04 e3 ff')
KERNEL_ATTR = bytes.fromhex('000102030001020300010203000102030100030000')
KERNEL_GR = bytes.fromhex('000f00000000050fff')
KERNEL_MISC = 0xe3
SEQ_EXPECT = {0: 0x03, 1: 0x01, 3: 0x00, 4: 0x06}      # SEQ2 is record only (S30)
CRTC_TIMING = list(range(0x00, 0x0a)) + list(range(0x10, 0x19))
CRTC_CURSOR = list(range(0x0a, 0x10))

GATE_NAMES = (['aper0', 'apersize', 'memsize', 'displaybase', 'mcfb', 'mcagp', 'hostpath', 'surface',
               'divsel', 'crtc2', 'fpon', 'cpmode', 'rbbm'] +
              [n.lower() for n in gen.R2A_GATES] + ['bridgevga'] +
              ['refdiv', 'ppllcntl', 'vclksrc', 'indexend'])

_H = core._H
_DEV = core._DEV
_US = '([0-9]+|unm|sat)'
GRAMMAR = dict(r2a.GRAMMAR)
GRAMMAR['begin'] = [('version', '[0-9]+'), ('boot', _H(8)), ('build', _H(8)), ('enter', '[0-9]+'),
                    ('revert', '[0-9]+'), ('cmode', '-?[0-9]+'), ('loc', _DEV), ('key', '(yes|no)')]
GRAMMAR['pll'] = [('k', '[0-9]+'), ('idx', _H(2)), ('name', '[A-Z0-9_]+'), ('p', _H(8)), ('c', _H(8)),
                  ('val', _H(8)), ('d', _H(8)), ('e', _H(8))]
GRAMMAR['pllbusy'] = [('k', '[0-9]+'), ('p', _H(8))]
GRAMMAR['pllabort'] = [('k', '[0-9]+'), ('why', '(upper|low|after-data|restore)'), ('p', _H(8)), ('c', _H(8)),
                       ('d', _H(8)), ('e', _H(8)), ('a', _H(8))]
GRAMMAR['time'] = [('d%d' % i, _US) for i in range(7)] + [('s60', _US), ('f60', '[0-9]+'),
                                                         ('s1000', _US), ('f1000', '[0-9]+')]
GRAMMAR['vga1'] = [('part', '1'), ('misc', _H(2)), ('dec', '[01]'), ('base', _H(3)), ('sqi', _H(2)),
                   ('sq', _H(10)), ('crtci', _H(2)), ('crtc', _H(50))]
GRAMMAR['vga2'] = [('part', '2'), ('gri', _H(2)), ('gr', _H(18)), ('attri', _H(2)), ('attr', _H(10))]
GRAMMAR['idxend'] = [('val', _H(8))]
GRAMMAR['gate'] = [('step', '[01]'), ('name', '[a-z0-9_]+'), ('val', _H(8)), ('want', _H(8)),
                   ('pass', '(1|0|na)')]
GRAMMAR['verdict'] = [('gates', '[0-9]+'), ('refused', '[0-9]+'), ('result', '(enter|refuse)')]
KIND_RE = dict((k, re.compile('^' + ''.join(' %s=(%s)' % (n, r) for n, r in f) + ' seq=([0-9]+)\\s*$'))
               for k, f in GRAMMAR.items())
SINGLE = tuple(r2a.SINGLE) + ('time', 'vga1', 'vga2', 'verdict', 'idxend')
LINE = re.compile(r'RDN-R2B0 ([0-9]+) (\w+)(.*)$')
INIT_LINE = re.compile(r'RDN-R2B0 init boot=(%s) build=(%s) loc=(%s) key=(yes|no) cmode=(-?[0-9]+) '
                       r'bar0=(%s) bar2=(%s) (ok|abort=[a-z0-9-]+)\s*$' % (_H(8), _H(8), _DEV, _H(8), _H(8)))
STATE_LINE = re.compile(r'RDN-R2B0 state boot=(%s) build=(%s) records=([0-9]+) last=([0-9]+) flags=(%s) '
                        r'cmode=(-?[0-9]+) loc=(%s)\s*$' % (_H(8), _H(8), _H(8), _DEV))
TOOL_STATE = re.compile(r'RDNR2B0 state when=(before|after) nonce=(%s) build=(%s) .* cmode=([0-9]+) loc=(%s)'
                        % (_H(8), _H(8), _H(3)))


def h(s):
    return int(s, 16)


def parse(text, runid):
    """R2a's parse, with R2b-0's prefix and kinds."""
    facts = {'pci': [], 'cfg': {}, 'bridge': [], 'live': [], 'reg': {}, 'stop': [],
             'malformed': [], 'duplicate': [], 'pll': [], 'gate': []}
    lines = 0
    begin = end = None
    seqs = []
    seen = {}
    for raw in text.splitlines():
        m = LINE.search(raw)
        if not m or m.group(1) != runid:
            continue
        kind = m.group(2)
        rest = m.group(3)
        if kind == 'vga':
            kind = 'vga1' if rest.startswith(' part=1 ') else 'vga2'
        lines += 1
        g = KIND_RE[kind].match(rest) if kind in KIND_RE else None
        if not g:
            facts['malformed'].append(raw[m.start():][:120])
            seqs.append(-1)
            continue
        vals = list(g.groups())
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
            facts['begin'] = kv
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
        elif kind in ('pllstart', 'pllbusy', 'pllabort', 'pllend', 'time', 'vga1', 'vga2', 'verdict', 'idxend'):
            facts[kind] = kv
            facts[kind + '_seq'] = int(kv['seq'])
        elif kind == 'pll':
            facts['pll'].append(kv)
        elif kind == 'gate':
            facts['gate'].append(kv)
    facts['seqs'] = seqs
    return facts, lines, begin, end


# the private R2a instance and its R1 core now read R2b-0 logs
r2a.parse = parse
core.parse = parse
core.R1_VERSION = '2'


def pll_checks(facts, out, fail):
    """R2a's PLL group checks, on twelve indices.  Returns ({name: value}, p0, complete)."""
    ps = facts.get('pllstart')
    pe = facts.get('pllend')
    plls = facts['pll']
    if ps is None or pe is None:
        fail.append('pllstart or pllend line missing')
        return {}, None, False
    p0 = h(ps['p0'])
    if 'pllbusy' in facts:
        fail.append('PLL index busy (write enable set) at group %s, p=%s: no index was stored'
                    % (facts['pllbusy']['k'], facts['pllbusy']['p']))
    if 'pllabort' in facts:
        a = facts['pllabort']
        fail.append('PLL group %s aborted (%s): p=%s c=%s d=%s e=%s, wrote p back, re-read %s -- %s'
                    % (a['k'], a['why'], a['p'], a['c'], a['d'], a['e'], a['a'],
                       'SAFE (index back at p)' if a['a'] == a['p']
                       else 'UNSAFE (index not back at p: reboot before any further run)'))
    if int(pe['groups']) != len(plls):
        fail.append('pllend groups=%s but %d pll lines' % (pe['groups'], len(plls)))
    if [int(x['k']) for x in plls] != list(range(len(plls))):
        fail.append('pll lines out of order: %s' % [x['k'] for x in plls])
    stopped = 'pllabort' in facts or 'pllbusy' in facts
    if len(plls) != len(PLL) and not stopped:
        fail.append('%d pll lines, expected %d' % (len(plls), len(PLL)))
    if p0 & 0x80:
        fail.append('p0 %08x has write enable set' % p0)
    vals = {}
    for x in plls:
        k = int(x['k'])
        if k >= len(PLL):
            fail.append('pll k=%d beyond the table' % k)
            continue
        name, idx = PLL[k]
        p, c, v, d, e = h(x['p']), h(x['c']), h(x['val']), h(x['d']), h(x['e'])
        if x['name'] != name or h(x['idx']) != idx:
            fail.append('pll k=%d is %s/%s, table says %s/%02x' % (k, x['name'], x['idx'], name, idx))
        if p & 0x80:
            fail.append('pll %s: p %08x has write enable set' % (name, p))
        if c != (p & ~0xff & 0xffffffff) | idx:
            fail.append('pll %s: after the index store c=%08x, want %08x' % (name, c, (p & ~0xff) | idx))
        if d != c:
            fail.append('pll %s: after the data read d=%08x, want c=%08x' % (name, d, c))
        if e != p:
            fail.append('pll %s: after the restore e=%08x, want p=%08x' % (name, e, p))
        if p != p0:
            fail.append('pll %s: p=%08x differs from p0=%08x (another writer between groups)' % (name, p, p0))
        vals[name] = v
    out.append('PLL groups completed: %d, CLOCK_CNTL_INDEX p0=%08x (PLL_DIV_SEL %d)' % (len(plls), p0, (p0 >> 8) & 3))
    return vals, p0, len(vals) == len(PLL) and not stopped


def r2a_reference():
    """R2a's raw registers, or None."""
    if not os.path.exists(R2A_LOG):
        return None
    f, _, b, e = r2a_orig.parse(open(R2A_LOG, errors='replace').read(), R2A_RUNID)
    if b is None or e is None:
        return None
    return {n: v for n, (off, v) in f['reg'].items()}


r2a_orig = _load('parse_r2a_for_r2a_logs', os.path.join(PROJ, 'tools', 'r2a', 'parse_r2a.py'))


def expected_gates(facts, vals, p0, complete, card, fb=FB_LENGTH):
    """The parser's own gate evaluation: [(step, name, val, want, pass)]."""
    got, bad = gen.values()
    if bad:
        raise ValueError('expectations from raw logs: %s' % bad[0])
    reg = {n: v for n, (off, v) in facts['reg'].items()}
    cfg1 = facts['cfg'][(card, 0x10)]
    bar0 = int.from_bytes(cfg1[0:4], 'little') & 0xfffffff0
    g = []

    def eq(step, name, val, want):
        g.append((step, name, val & 0xffffffff, want & 0xffffffff, '1' if val == want else '0'))

    eq(0, 'aper0', reg['CONFIG_APER_0_BASE'], bar0)
    g.append((0, 'apersize', reg['CONFIG_APER_SIZE'], fb, '1' if reg['CONFIG_APER_SIZE'] >= fb else '0'))
    g.append((0, 'memsize', reg['CONFIG_MEMSIZE'], fb, '1' if reg['CONFIG_MEMSIZE'] >= fb else '0'))
    eq(0, 'displaybase', reg['DISPLAY_BASE_ADDR'], (reg['MC_FB_LOCATION'] & 0xffff) << 16)
    for gate, name in gen.R1_GATES:
        eq(0, gate, reg[name], got[name][2])
    eq(0, 'divsel', reg['CLOCK_CNTL_INDEX'] & 0x300, 0x300)          # radeon_reg.h 291
    eq(0, 'crtc2', reg['CRTC2_GEN_CNTL'] & (1 << 25), 0)             # 414
    eq(0, 'fpon', reg['FP_GEN_CNTL'] & 1, 0)                         # 840
    eq(0, 'cpmode', reg['CP_CSQ_CNTL'] >> 28, 0)                     # 3143
    eq(0, 'rbbm', reg['RBBM_STATUS'] & (1 << 31), 0)                 # 1487
    for name in gen.R2A_GATES:
        eq(0, name.lower(), reg[name], got[name][2])
    cbus = int(card.split(':')[0], 16)
    path = [b for b in facts['bridge'] if (h(b['bus']) >> 8 & 0xff) <= cbus <= (h(b['bus']) >> 16 & 0xff)]
    allc = 0xffffffff
    for b in path:
        allc &= h(b['ctl3c'])
    if not path:
        allc = 0
    g.append((0, 'bridgevga', allc & 0x80000, 0x80000, '1' if allc & 0x80000 else '0'))
    if complete:
        rd = vals['PPLL_REF_DIV'] & 0x3ff
        g.append((1, 'refdiv', rd, 6, '1' if rd in (6, 12) else '0'))
        eq(1, 'ppllcntl', vals['PPLL_CNTL'] & 0x70003, 0)
        eq(1, 'vclksrc', vals['VCLK_ECP_CNTL'] & 3, 3)
        g.append(('indexend-from-idxend-line', None))    # filled in by the caller from the idxend line
    else:
        g += [(1, 'refdiv', 0, 6, 'na'), (1, 'ppllcntl', 0, 0, 'na'), (1, 'vclksrc', 0, 3, 'na'),
              (1, 'indexend', 0, p0 or 0, 'na')]
    return g


def judge(text, runid, build, tool=None):
    """Return (report, failures, facts-record, klass).  Never raises on log content."""
    try:
        return _judge(text, runid, build, tool)
    except Exception as e:
        return [], ['parser raised %s: %s' % (type(e).__name__, e)], {}, 'FAIL'


def _judge(text, runid, build, tool):
    out, fail = core._judge(text, runid, build)
    rec = {}
    facts, _, begin, end = parse(text, runid)
    if begin is None or end is None:
        return out, fail, rec, 'FAIL'
    bg = facts['begin']
    rec.update(boot=bg['boot'], cmode=bg['cmode'], loc=bg['loc'], enter=bg['enter'], revert=bg['revert'])
    out.append('begin boot=%s cmode=%s loc=%s key=%s enter=%s revert=%s' % (
        bg['boot'], bg['cmode'], bg['loc'], bg['key'], bg['enter'], bg['revert']))
    if bg['loc'] != WANT_LOC:
        fail.append('record location %s, R2a measured the card at %s' % (bg['loc'], WANT_LOC))
    if bg['key'] != 'yes':
        fail.append('record ran with key=%s' % bg['key'])
    if int(bg['enter']) < 1:
        fail.append('enterLinearMode was never called before the record (enter=%s)' % bg['enter'])
    if int(bg['enter']) > 1:
        out.append('enter=%s: the window server entered more than once (recorded)' % bg['enter'])

    # the driver's state line (the in-boot proof) and the init line
    lines = text.splitlines()
    bi = next((i for i, l in enumerate(lines) if LINE.search(l) and LINE.search(l).group(1) == runid
               and LINE.search(l).group(2) == 'begin'), None)
    states = [(i, STATE_LINE.search(l)) for i, l in enumerate(lines) if ' state boot=' in l]
    if any(m is None for _, m in states):
        fail.append('malformed state line')
    before = [(i, m) for i, m in states if m is not None and i < bi]
    if not before:
        fail.append('no driver state line before the record: the in-boot syslog proof is missing')
    for _, m in before:
        if m.group(1) != bg['boot'] or m.group(2) != bg['build']:
            fail.append('state line boot=%s build=%s, the record says %s/%s (not the same boot)'
                        % (m.group(1), m.group(2), bg['boot'], bg['build']))
        if m.group(6) != bg['cmode'] or m.group(7) != bg['loc']:
            fail.append('state line cmode=%s loc=%s, the record says %s/%s'
                        % (m.group(6), m.group(7), bg['cmode'], bg['loc']))
        rec['state_records'] = m.group(3)
    inits = [INIT_LINE.search(l) for l in lines if 'RDN-R2B0 init ' in l]
    if any(m is None for m in inits):
        fail.append('malformed init line')
    inits = [m for m in inits if m]
    if inits:
        m = inits[-1]
        if m.group(1) != bg['boot']:
            fail.append('boot nonce: init %s, record %s (not the same boot)' % (m.group(1), bg['boot']))
        if m.group(3) != bg['loc'] or m.group(5) != bg['cmode'] or m.group(2) != bg['build']:
            fail.append('init line loc/cmode/build %s/%s/%s differ from the record %s/%s/%s'
                        % (m.group(3), m.group(5), m.group(2), bg['loc'], bg['cmode'], bg['build']))
    if tool is not None:
        states = [TOOL_STATE.search(l) for l in tool.splitlines() if l.startswith('RDNR2B0 state ')]
        if not states or any(s is None for s in states):
            fail.append('tool output holds no well-formed state line')
        for s in states:
            if s is None:
                continue
            loc = int(s.group(5), 16)
            tloc = '%02x:%02x.%x' % (loc >> 8, (loc >> 3) & 0x1f, loc & 7)
            if s.group(2) != bg['boot'] or s.group(3) != bg['build'] or s.group(4) != bg['cmode'] or tloc != bg['loc']:
                fail.append('tool state %s nonce/build/cmode/loc %s/%s/%s/%s differ from the record'
                            % (s.group(1), s.group(2), s.group(3), s.group(4), tloc))

    # time: record only
    t = facts.get('time')
    if t is None:
        if 'vline-static' not in facts['stop'] and facts.get('mmio', {}).get('map') == 'ok' and 'frame60' in facts:
            fail.append('time line missing')
    else:
        unm = [k for k, v in t.items() if v in ('unm', 'sat')]
        rec['time'] = ' '.join('%s=%s' % (k, t[k]) for k in ['d%d' % i for i in range(7)] + ['s60', 'f60', 's1000', 'f1000'])
        out.append('time (record only): %s; unmeasured or saturated: %d' % (rec['time'], len(unm)))

    if 'vline-static' in facts['stop'] or facts.get('mmio', {}).get('map') != 'ok':
        for k in ('pllstart', 'vga1', 'vga2', 'verdict'):
            if k in facts:
                fail.append('%s line after a static VLINE or without a checked map' % k)
        if facts['gate']:
            fail.append('gate lines after a static VLINE or without a checked map')
        return out, fail, rec, 'FAIL'

    vals, p0, complete = pll_checks(facts, out, fail)

    # immovable registers against R2a's raw log
    reg = {n: v for n, (off, v) in facts['reg'].items()}
    ref = r2a_reference()
    if ref is None:
        fail.append('R2a raw log %s not readable: immovable registers unchecked' % os.path.relpath(R2A_LOG, PROJ))
    elif all(n in reg for n in IMMOVABLE):
        for n in IMMOVABLE:
            if reg[n] != ref[n]:
                fail.append('%s %08x now, %08x in R2a: a register the boot cannot change differs' % (n, reg[n], ref[n]))
        diffs = ['%s %08x (R2a %08x)' % (n, reg[n], ref[n]) for n in sorted(reg) if n in ref and reg[n] != ref[n]]
        rec['differs_from_r2a'] = ','.join(n.split()[0] for n in diffs) or 'none'
        out.append('registers differing from R2a (record): %s' % (', '.join(diffs) or 'none'))

    # the post-PLL index read, as its own fact
    if complete and 'idxend' not in facts:
        fail.append('idxend line missing after a complete PLL snapshot')
    if not complete and 'idxend' in facts:
        fail.append('idxend line after a PLL stop')
    if 'idxend' in facts:
        rec['idxend'] = facts['idxend']['val']

    # VGA
    v1, v2 = facts.get('vga1'), facts.get('vga2')
    pe_seq = facts.get('pllend_seq')
    if not complete:
        if v1 or v2:
            fail.append('VGA lines after a PLL stop')
    else:
        if v1 is None or v2 is None:
            fail.append('VGA lines missing after a complete PLL snapshot')
        else:
            if pe_seq is None or not (pe_seq < facts['vga1_seq'] < facts['vga2_seq']):
                fail.append('VGA lines out of place')
            vga_facts(v1, v2, out, rec, fail)

    # gates
    cards = [p for p in facts['pci'] if int(p['vid'], 16) == 0x1002 and int(p['did'], 16) in core.RV280_IDS]
    gl = facts['gate']
    refused = None
    if len(cards) != 1 or (cards[0]['dev'], 0x10) not in facts['cfg'] or not all(n in reg for n in REGS):
        if gl:
            fail.append('gate lines without a card, its config or its registers')
    else:
        want = expected_gates(facts, vals, p0, complete, cards[0]['dev'], fb_length(build))
        if [x['name'] for x in gl] != GATE_NAMES:
            fail.append('gate lines: %d in order %s, want the 32 of the plan' % (len(gl), [x['name'] for x in gl][:5]))
        else:
            idx = facts.get('idxend')
            for x, w in zip(gl, want):
                if isinstance(w, tuple) and w[0] == 'indexend-from-idxend-line':
                    # judged from the raw idxend line, never from the gate line itself
                    v = h(idx['val']) if idx else None
                    w = (1, 'indexend', v if v is not None else -1, p0, '1' if v == p0 else '0')
                got = (int(x['step']), x['name'], h(x['val']), h(x['want']), x['pass'])
                if got != w:
                    fail.append('gate %s: driver says step=%d val=%08x want=%08x pass=%s, parser %d %08x %08x %s'
                                % ((x['name'],) + got[:1] + got[2:] + w[:1] + w[2:]))
            refused = sum(1 for x in gl if x['pass'] != '1')
            bad = [x['name'] for x in gl if x['pass'] != '1']
            out.append('gates: %d of 32 refuse: %s' % (refused, ', '.join(bad) or 'none'))
            rec['gates_refused'] = ','.join(bad) or 'none'
        vd = facts.get('verdict')
        if vd is None:
            fail.append('verdict line missing')
        elif refused is not None:
            if int(vd['gates']) != 32 or int(vd['refused']) != refused or vd['result'] != ('refuse' if refused else 'enter'):
                fail.append('verdict line %s disagrees with the gate lines (%d refused)' % (vd, refused))

    pll_facts(vals, p0, out, rec)
    if fail:
        return out, fail, rec, 'FAIL'
    return out, fail, rec, 'PASS-REFUSE' if refused else 'PASS-ENTER'


def vga_facts(v1, v2, out, rec, bad):
    misc = h(v1['misc'])
    rec['vga_misc'] = v1['misc']
    if v1['dec'] != '1':
        out.append('VGA: not decoded (MISC reads ff): recorded, nothing compared')
        rec['vga'] = 'undecoded'
        return
    seq = bytes.fromhex(v1['sq'])
    crtc = bytes.fromhex(v1['crtc'])
    attr = bytes.fromhex(v2['attr'])
    base = h(v1['base'])
    if base != (0x3d4 if misc & 1 else 0x3b4):
        bad.append('VGA: base %03x does not follow MISC bit 0 (%02x): the record read the wrong port pair'
                   % (base, misc))
    diffs = []
    if misc != KERNEL_MISC:
        diffs.append('misc %02x' % misc)
    for i, b in sorted(SEQ_EXPECT.items()):
        if seq[i] != b:
            diffs.append('seq%d %02x' % (i, seq[i]))
    timing = [i for i in CRTC_TIMING if crtc[i] != KERNEL_CRTC[i]]
    cursor = [i for i in CRTC_CURSOR if crtc[i] != KERNEL_CRTC[i]]
    if timing:
        diffs.append('crtc timing %s' % ','.join('%02x' % i for i in timing))
    if attr != KERNEL_ATTR[0x10:0x15]:
        diffs.append('attr10-14 %s' % v2['attr'])
    rec['vga'] = 'vga-state-differs' if diffs else 'kernel-table'
    rec['vga_attr10'] = '%02x' % attr[0]
    rec['vga_crtc_cursor_differs'] = ','.join('%02x' % i for i in cursor) or 'none'
    out.append('VGA against the kernel console table: %s%s; cursor/start bytes differing: %s; MISC clock select %d; ATTR10 %02x'
               % ('vga-state-differs: ' if diffs else 'equal', ', '.join(diffs), rec['vga_crtc_cursor_differs'],
                  (misc >> 2) & 3, attr[0]))


def pll_facts(vals, p0, out, rec):
    for name, v in sorted(vals.items()):
        rec[name.lower()] = '%08x' % v
    if 'PPLL_REF_DIV' not in vals:
        return
    rd = vals['PPLL_REF_DIV'] & 0x3ff
    rec['refdiv'] = rd
    rec['pll_div_sel'] = (p0 >> 8) & 3
    for slot in ('PPLL_DIV_0', 'PPLL_DIV_1', 'PPLL_DIV_2', 'PPLL_DIV_3'):
        if slot in vals and rd:
            fb = vals[slot] & 0x7ff
            vco = REFCLK_KHZ * fb / rd
            rec[slot.lower() + '_vco_khz'] = '%.1f' % vco
            out.append('%s %08x: fb %d post code %d, VCO %.1f kHz (%s 200000-400000)' % (
                slot, vals[slot], fb, (vals[slot] >> 16) & 7, vco,
                'inside' if 200000 <= vco <= 400000 else 'OUTSIDE'))


# ---- self-test -----------------------------------------------------------

# Hand-written gate lines for the R2a boot's values (docs/R2A_RESULT.md,
# build/r2a/789467668): every gate passes there.  Written out, not computed,
# so the parser's evaluation is checked against something it did not produce.
GOOD_GATES = [
    '0 aper0 e0000000 e0000000 1', '0 apersize 08000000 00800000 1', '0 memsize 08000000 00800000 1',
    '0 displaybase 00000000 00000000 1', '0 mcfb 1fff0000 1fff0000 1', '0 mcagp 27ff2000 27ff2000 1',
    '0 hostpath 70000000 70000000 1', '0 surface 00000100 00000100 1', '0 divsel 00000300 00000300 1',
    '0 crtc2 00000000 00000000 1', '0 fpon 00000000 00000000 1', '0 cpmode 00000000 00000000 1',
    '0 rbbm 00000000 00000000 1', '0 ovr_clr 00000000 00000000 1', '0 ovr_wid_left_right 00000000 00000000 1',
    '0 ovr_wid_top_bottom 00000000 00000000 1', '0 ov0_scale_cntl 807f0000 807f0000 1',
    '0 subpic_cntl 00000000 00000000 1', '0 viph_control 00000000 00000000 1', '0 i2c_cntl_1 00000000 00000000 1',
    '0 cap0_trig_cntl 00000000 00000000 1', '0 cap1_trig_cntl 00000000 00000000 1',
    '0 tv_dac_cntl 07660142 07660142 1', '0 disp_hw_debug 00020000 00020000 1',
    '0 disp_output_cntl 10000000 10000000 1', '0 dac_cntl2 00000000 00000000 1',
    '0 crtc_offset_cntl 10000000 10000000 1', '0 bridgevga 00080000 00080000 1',
    '1 refdiv 00000006 00000006 1', '1 ppllcntl 00000000 00000000 1', '1 vclksrc 00000003 00000003 1',
    '1 indexend 00000303 00000303 1',
]
GOOD_VGA1 = 'vga part=1 misc=e3 dec=1 base=3d4 sqi=01 sq=03010f0006 crtci=11 crtc=%s' % KERNEL_CRTC.hex()
GOOD_VGA2 = 'vga part=2 gri=08 gr=000f00000000050fff attri=20 attr=0100030000'


def synthetic(runid='77', build='1234abcd', gates=None, drop=None, replace=None, extra=None, marker=True,
              init=True, pll_extra=True, vga=True, time_line=True):
    """An R2b-0 log built from R2a's real log (build/r2a/789467668): its PCI,
    liveness, registers and PLL lines with R2b-0's prefix, two more PLL
    groups, a time line, the kernel-table VGA lines and hand-written gates."""
    body = []
    src = open(R2A_LOG, errors='replace').read()
    for l in src.splitlines():
        m = re.search(r'RDN-R2A %s (\w+)(.*) seq=\d+$' % R2A_RUNID, l)
        if not m:
            continue
        kind, rest = m.group(1), m.group(2)
        if kind in ('begin', 'end', 'pllend'):
            continue
        if kind == 'frame60' and time_line:
            body.append(kind + rest)
            body.append('time d0=2050 d1=2049 d2=2051 d3=2050 d4=2050 d5=2049 d6=2050 s60=60012 f60=4 s1000=1000030 f1000=60')
            continue
        body.append(kind + rest)
    if pll_extra:
        body.append('pll k=10 idx=05 name=PPLL_DIV_1 p=00000303 c=00000305 val=00000000 d=00000305 e=00000303')
        body.append('pll k=11 idx=06 name=PPLL_DIV_2 p=00000303 c=00000306 val=00000000 d=00000306 e=00000303')
        body.append('pllend groups=12')
    else:
        body.append('pllend groups=10')
    if pll_extra:
        body.append('idxend val=00000303')
    if vga:
        body += [GOOD_VGA1, GOOD_VGA2]
    gl = GOOD_GATES if gates is None else gates
    refused = sum(1 for g in gl if not g.endswith(' 1'))
    for g in gl:
        s, n, v, w, p = g.split()
        body.append('gate step=%s name=%s val=%s want=%s pass=%s' % (s, n, v, w, p))
    body.append('verdict gates=32 refused=%d result=%s' % (refused, 'refuse' if refused else 'enter'))
    for k, v in (replace or {}).items():
        body = [b.replace(k, v) for b in body]
    if drop:
        body = [b for b in body if not b.startswith(drop)]
    if extra:
        body += extra
    n = len(body) + 2
    head = 'begin version=2 boot=0badf00d build=%s enter=1 revert=1 cmode=1 loc=03:0b.0 key=yes' % build
    lines = ['RDN-R2B0 %s %s seq=0' % (runid, head)] + \
            ['RDN-R2B0 %s %s seq=%d' % (runid, b, i + 1) for i, b in enumerate(body)] + \
            ['RDN-R2B0 %s end lines=%d seq=%d' % (runid, n, n - 1)]
    pre = []
    if init:
        pre.append('RDN-R2B0 init boot=0badf00d build=%s loc=03:0b.0 key=yes cmode=1 bar0=e0000000 bar2=d0200000 ok' % build)
    if marker:
        pre.append('RDN-R2B0 state boot=0badf00d build=%s records=0 last=0 flags=03580101 cmode=1 loc=03:0b.0'
                   % build)
    return '\n'.join('Sep 16 10:00:00 nextonion mach: ' + l for l in pre + lines) + '\n'


def self_test():
    failures = 0

    def check(label, ok, detail=''):
        nonlocal failures
        print('%-4s %s%s' % ('ok' if ok else 'FAIL', label, '' if ok else ' -- ' + detail))
        failures += not ok

    # the kernel table constants against the mirror kernel, when it is here
    kern = os.path.join(os.path.dirname(PROJ), 'ref', 'openstep', 'ps2', 'mach_kernel')
    if os.path.exists(kern):
        import struct
        d = open(kern, 'rb').read()
        ncmds = struct.unpack_from('<I', d, 16)[0]
        off = 28
        secs = []
        for _ in range(ncmds):
            cmd, sz = struct.unpack_from('<II', d, off)
            if cmd == 1:
                for s in range(struct.unpack_from('<I', d, off + 48)[0]):
                    so = off + 56 + s * 68
                    addr, size, foff = struct.unpack_from('<III', d, so + 32)
                    secs.append((addr, size, foff))
            off += sz

        def at(va, n):
            for addr, size, foff in secs:
                if addr <= va < addr + size and foff:
                    return d[foff + va - addr:foff + va - addr + n]
            return None
        for k, want in (('seq', KERNEL_SEQ), ('crtc', KERNEL_CRTC), ('attr', KERNEL_ATTR), ('gr', KERNEL_GR)):
            va, n = KERNEL_VA[k]
            check('kernel %s table at VA %x' % (k, va), at(va, n) == want, '%s vs %s' % (at(va, n), want.hex()))
        check('kernel MISC byte e3 before SEQ', at(0x1d54dc, 1) == bytes([KERNEL_MISC]), str(at(0x1d54dc, 1)))
    else:
        print('--   mirror kernel not present; kernel table constants unchecked')
    check('32 gate names', len(GATE_NAMES) == 32 and len(set(GATE_NAMES)) == 32, str(len(GATE_NAMES)))
    check('12 PLL indices, bits 6-7 clear', len(PLL) == 12 and not any(i & 0xc0 for _, i in PLL))

    good = synthetic()
    bad_gate = list(GOOD_GATES)
    bad_gate[1] = '0 apersize 08000000 00800000 0'
    # the length a gate line names belongs to the build that printed it (22-2):
    # both directions must fail, or a table that is never consulted would pass
    old_gates = list(GOOD_GATES)
    old_gates[1] = '0 apersize 08000000 00300000 1'
    old_gates[2] = '0 memsize 08000000 00300000 1'
    refuse = list(GOOD_GATES)
    refuse[28] = '1 refdiv 00000009 00000006 0'
    cases = [
        ('good', good, None, 'PASS-ENTER'),
        ('each kind missing: time', synthetic(time_line=False), None, 'FAIL:time line missing'),
        ('each kind missing: vga', synthetic(vga=False), None, 'FAIL:VGA lines missing'),
        ('each kind missing: gates', synthetic(drop='gate '), None, 'FAIL:gate lines'),
        ('each kind missing: verdict', synthetic(drop='verdict'), None, 'FAIL:verdict line missing'),
        ('each kind missing: twelfth PLL', synthetic(pll_extra=False), None, 'FAIL:10 pll lines, expected 12'),
        ('each kind missing: idxend', synthetic(drop='idxend'), None, 'FAIL:idxend line missing'),
        ('idxend disagrees with the gate line', synthetic(replace={'idxend val=00000303': 'idxend val=00000203'}),
         None, 'FAIL:gate indexend'),
        ('VGA base does not follow MISC', synthetic(replace={'misc=e3 dec=1 base=3d4': 'misc=e2 dec=1 base=3d4'}),
         None, 'FAIL:does not follow MISC'),
        ('gate verdict flipped', synthetic(gates=bad_gate), None, 'FAIL:gate apersize'),
        ('verdict line lies', synthetic(replace={'refused=0 result=enter': 'refused=1 result=refuse'}), None,
         'FAIL:verdict line'),
        ('VGA line length', synthetic(replace={'sq=03010f0006': 'sq=03010f00'}), None, 'FAIL:malformed line'),
        ('VGA differs from the kernel table', synthetic(replace={'misc=e3': 'misc=67'}), None,
         'PASS-ENTER:vga-state-differs'),
        ('CRTC cursor bytes only differ', synthetic(replace={KERNEL_CRTC.hex(): KERNEL_CRTC[:0x0e].hex() + '01' + KERNEL_CRTC[0x0f:].hex()}),
         None, 'PASS-ENTER:cursor/start bytes differing: 0e'),
        ('time unmeasured', synthetic(replace={'d3=2050': 'd3=unm', 's60=60012': 's60=unm'}), None, 'PASS-ENTER'),
        ('nonce mismatch with init', good.replace('init boot=0badf00d', 'init boot=0badf00e'), None,
         'FAIL:boot nonce'),
        ('no state line', synthetic(marker=False), None, 'FAIL:in-boot syslog proof'),
        ('state line of another boot', synthetic().replace('state boot=0badf00d', 'state boot=0badf00e'), None,
         'FAIL:not the same boot'),
        ('malformed state line', synthetic().replace('records=0 last=0', 'records=x last=0'), None,
         'FAIL:malformed state line'),
        ('state line of another console mode', synthetic().replace('flags=03580101 cmode=1', 'flags=03580101 cmode=2'),
         None, 'FAIL:state line cmode'),
        ('location differs', synthetic().replace('loc=03:0b.0 key=yes seq=0', 'loc=03:0d.0 key=yes seq=0'), None,
         'FAIL:record location'),
        ('immovable register differs', synthetic(replace={'name=MEM_CNTL off=0140 val=32003200': 'name=MEM_CNTL off=0140 val=32003201'}),
         None, 'FAIL:MEM_CNTL'),
        ('CRTC_GEN_CNTL and PLL_DIV_SEL differ from R1', synthetic(replace={'name=CRTC_GEN_CNTL off=0050 val=02000200': 'name=CRTC_GEN_CNTL off=0050 val=03000200'}),
         None, 'PASS-ENTER:differing from R2a'),
        ('a gate refuses', synthetic(gates=refuse, replace={'name=PPLL_REF_DIV p=00000303 c=00000303 val=00000006': 'name=PPLL_REF_DIV p=00000303 c=00000303 val=00000009'}),
         None, 'PASS-REFUSE'),
        ('VGA after pllabort', synthetic(pll_extra=False, extra=None,
                                         replace={'pllend groups=10': 'pllabort k=10 why=upper p=00000303 c=00000205 d=00000000 e=00000000 a=00000303'}),
         None, 'FAIL:VGA lines after a PLL stop'),
        ('build stamp differs', synthetic(build='deadbeef'), None, 'FAIL:build stamp'),
        ('the archived build keeps its 3 MiB', synthetic(build='e48c2e8d', gates=old_gates), None,
         'PASS-ENTER', 'e48c2e8d'),
        ('the archived build judged at 8 MiB', synthetic(build='e48c2e8d'), None, 'FAIL:gate apersize',
         'e48c2e8d'),
        ('a new build that prints 3 MiB', synthetic(gates=old_gates), None, 'FAIL:gate apersize'),
        ('tool state disagrees', good,
         'RDNR2B0 state when=before nonce=0badf00d build=1234abcd enter=1 revert=1 records=0 lastrunid=0 lastresult=0 lastlines=0 flags=03580101 key=1 latched=0 busy=0 cmode=2 loc=358\n',
         'FAIL:tool state'),
        ('tool state agrees', good,
         'RDNR2B0 state when=before nonce=0badf00d build=1234abcd enter=1 revert=1 records=0 lastrunid=0 lastresult=0 lastlines=0 flags=03580101 key=1 latched=0 busy=0 cmode=1 loc=358\n',
         'PASS-ENTER'),
    ]
    for case in cases:
        label, text, tool, want = case[:4]
        out, fail, rec, klass = judge(text, '77', case[4] if len(case) > 4 else '1234abcd', tool)
        kind, _, sub = want.partition(':')
        if kind == 'FAIL':
            ok = klass == 'FAIL' and any(sub in f for f in fail)
        else:
            ok = klass == kind and not fail and (not sub or any(sub in o for o in out))
        check(label, ok, '%s fail=%s' % (klass, fail[:3]))
    # every single-line corruption of the good log fails without raising
    lines = good.splitlines()
    tried = leaked = 0
    corrupt = [lambda l: l.replace('seq=', 'seq=x'), lambda l: l.replace('val=', 'val=g'),
               lambda l: l.replace('pass=1', 'pass=2'), lambda l: l[:len(l) // 2], lambda l: l + ' extra=1']
    for c in corrupt:
        for i in range(len(lines)):
            if 'RDN-R2B0 77 ' not in lines[i]:
                continue
            t = lines[:]
            t[i] = c(t[i])
            if t[i] == lines[i]:
                continue
            tried += 1
            _, fail, _, klass = judge('\n'.join(t) + '\n', '77', '1234abcd')
            if klass != 'FAIL' or any('parser raised' in f for f in fail):
                leaked += 1
                print('FAIL corruption passed or raised: %s' % t[i][-80:])
    check('single-line corruption: %d logs, %d leaked' % (tried, leaked), leaked == 0 and tried > 300)
    print('parse_r2b0 self-test: %s' % ('PASS' if failures == 0 else 'FAIL (%d)' % failures))
    return failures == 0


def main(argv):
    if argv[1:] == ['--self-test']:
        return 0 if self_test() else 1
    args = argv[1:]
    outdir = tool = None
    if '--out' in args:
        i = args.index('--out')
        outdir = args[i + 1]
        args = args[:i] + args[i + 2:]
    if '--tool' in args:
        i = args.index('--tool')
        tool = open(args[i + 1], errors='replace').read()
        args = args[:i] + args[i + 2:]
    if len(args) != 3:
        print(__doc__)
        return 2
    log, runid, build = args
    out, fail, rec, klass = judge(open(log, errors='replace').read(), runid, build, tool)
    for o in out:
        print(o)
    for f in fail:
        print('FAIL ' + f)
    if outdir:
        path = os.path.join(outdir, 'r2b0-facts-%s.txt' % runid)
        with open(path, 'w') as fh:
            fh.write('verdict=%s\n' % klass)
            for k in sorted(rec):
                fh.write('%s=%s\n' % (k, rec[k]))
        print('facts: %s' % path)
    print('R2B0: %s' % klass)
    return {'PASS-ENTER': 0, 'PASS-REFUSE': 3, 'FAIL': 1}[klass]


if __name__ == '__main__':
    sys.exit(main(sys.argv))
