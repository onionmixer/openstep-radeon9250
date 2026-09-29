#!/usr/bin/env python3
"""Parse and judge the R2a MMIO and PLL snapshot log (docs/R1C_R2A_IMPL_PLAN.md section 2-5).

  parse_r2a.py <log> <runid> <build> <r1log> <r1runid> [--out DIR]
        print the report; exit 0 PASS, 1 FAIL, 2 REPLAN (only undefined register
        bits differ from R1); with --out, write r2a-facts-<runid>.txt
  parse_r2a.py --self-test

The R1 parser (tools/r1/parse_r1.py) is used read-only: this file loads a
private instance of it and points that instance's line parser and register
table at R2a's, so every R1 gate (sequence, grammar, one card, the map
decision recomputed from the logged config bytes, liveness, registers present
at their offsets) runs unchanged on the R2a log.  tools/r1/parse_r1.py itself
is not modified, so R1's own verdict stays reproducible.

Line grammar: R1's kinds with the prefix RDN-R2A, the bridge line with one more
field, and five new kinds (every line also has seq=<k>):
  bridge dev=<bb:dd.f> bus=<hex8> win1c=<hex8> win20=<hex8> win24=<hex8> win28=<hex8> win2c=<hex8> ctl3c=<hex8>
  pllstart p0=<hex8>
  pll k=<n> idx=<hex2> name=<NAME> p=<hex8> c=<hex8> val=<hex8> d=<hex8> e=<hex8>
  pllbusy k=<n> p=<hex8>
  pllabort k=<n> why=<upper|low|after-data|restore> p=<hex8> c=<hex8> d=<hex8> e=<hex8> a=<hex8>
  pllend groups=<n>

Hardware gates (on top of R1's):
  - ten pll lines, k = 0..9, idx and name as the probe's table
  - every group: p bit 7 clear, c = (p & ~0xff) | idx, d = c, e = p
  - every p equal to p0 (no other writer between groups)
  - no pllbusy, no pllabort (an abort is reported as safe when a = p)
  - p0 bits 8-9 equal R1's CLOCK_CNTL_INDEX bits 8-9
  - R1's registers again: GEN_INT_STATUS and RBBM_STATUS are volatile and
    skipped, CLOCK_CNTL_INDEX is compared in bits 8-31 only (the low byte is
    whoever touched the PLL last); a difference in a documented bit fails, a
    difference only in bits no header defines (DAC_CNTL 14/21/22,
    CRTC_EXT_CNTL 19/25/26/28/29) is REPLAN, not FAIL
The group checks recompute what the probe already checked before it logged:
they are an independent re-computation (they fail on a probe defect or a
target miscompile), not further evidence about the card.
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


R1_PARSER = os.path.join(PROJ, 'tools', 'r1', 'parse_r1.py')
pr1 = _load('parse_r1_for_r1_logs', R1_PARSER)          # untouched: reads R1 logs
core = _load('parse_r1_for_r2a_logs', R1_PARSER)        # private: re-pointed below

# register table: R1's 35 plus 15 (must equal RDNR2aProbe.m r2aRegs)
REGS = dict(pr1.REGS)
REGS.update({
    'CRTC_OFFSET_CNTL': 0x0228, 'DISP_MERGE_CNTL': 0x0d60, 'TV_DAC_CNTL': 0x088c,
    'DISP_HW_DEBUG': 0x0d14, 'OVR_CLR': 0x0230, 'OVR_WID_LEFT_RIGHT': 0x0234,
    'OVR_WID_TOP_BOTTOM': 0x0238, 'OV0_SCALE_CNTL': 0x0420, 'SUBPIC_CNTL': 0x0540,
    'VIPH_CONTROL': 0x0c40, 'I2C_CNTL_1': 0x0094, 'CAP0_TRIG_CNTL': 0x0950,
    'CAP1_TRIG_CNTL': 0x09c0, 'MEM_CNTL': 0x0140, 'MEM_TIMING_CNTL': 0x0144,
})
# PLL indices in probe order (must equal RDNR2aProbe.m r2aPll)
PLL = [('PPLL_CNTL', 0x02), ('PPLL_REF_DIV', 0x03), ('PPLL_DIV_0', 0x04), ('PPLL_DIV_3', 0x07),
       ('VCLK_ECP_CNTL', 0x08), ('HTOTAL_CNTL', 0x09), ('X_MPLL_REF_FB_DIV', 0x0a),
       ('SCLK_CNTL', 0x0d), ('MCLK_CNTL', 0x12), ('PIXCLKS_CNTL', 0x2d)]
VOLATILE = {'GEN_INT_STATUS', 'RBBM_STATUS'}
# bits no reference header defines (docs/R1_RESULT.md section 3)
UNDEFINED_BITS = {'DAC_CNTL': (1 << 14) | (1 << 21) | (1 << 22),
                  'CRTC_EXT_CNTL': (1 << 19) | (1 << 25) | (1 << 26) | (1 << 28) | (1 << 29)}
INTERFERING = ['OVR_CLR', 'OVR_WID_LEFT_RIGHT', 'OVR_WID_TOP_BOTTOM', 'OV0_SCALE_CNTL', 'SUBPIC_CNTL',
               'VIPH_CONTROL', 'I2C_CNTL_1', 'CAP0_TRIG_CNTL', 'CAP1_TRIG_CNTL']

_H = core._H
_DEV = core._DEV
GRAMMAR = dict(core.GRAMMAR)
GRAMMAR['bridge'] = core.GRAMMAR['bridge'] + [('ctl3c', _H(8))]
GRAMMAR['pllstart'] = [('p0', _H(8))]
GRAMMAR['pll'] = [('k', '[0-9]'), ('idx', _H(2)), ('name', '[A-Z0-9_]+'), ('p', _H(8)), ('c', _H(8)),
                  ('val', _H(8)), ('d', _H(8)), ('e', _H(8))]
GRAMMAR['pllbusy'] = [('k', '[0-9]'), ('p', _H(8))]
GRAMMAR['pllabort'] = [('k', '[0-9]'), ('why', '(upper|low|after-data|restore)'), ('p', _H(8)), ('c', _H(8)),
                       ('d', _H(8)), ('e', _H(8)), ('a', _H(8))]
GRAMMAR['pllend'] = [('groups', '[0-9]+')]
KIND_RE = dict((k, re.compile('^' + ''.join(' %s=(%s)' % (n, r) for n, r in f) + ' seq=([0-9]+)\\s*$'))
               for k, f in GRAMMAR.items())
SINGLE = tuple(core.SINGLE) + ('pllstart', 'pllbusy', 'pllabort', 'pllend')
LINE = re.compile(r'RDN-R2A (\S+) (\w+)(.*)$')


def parse(text, runid):
    """R1's parse, with R2a's prefix, grammar and PLL kinds."""
    facts = {'pci': [], 'cfg': {}, 'bridge': [], 'live': [], 'reg': {}, 'stop': [],
             'malformed': [], 'duplicate': [], 'pll': []}
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
        elif kind in ('pllstart', 'pllbusy', 'pllabort', 'pllend'):
            facts[kind] = kv
        elif kind == 'pll':
            facts['pll'].append(kv)
    facts['seqs'] = seqs
    return facts, lines, begin, end


# the private R1 core now reads R2a logs
core.parse = parse
core.REGS = REGS


def judge(text, runid, build, r1text, r1runid):
    """Return (report, failures, replan, facts).  Never raises on log content."""
    try:
        return _judge(text, runid, build, r1text, r1runid)
    except Exception as e:
        return [], ['parser raised %s: %s' % (type(e).__name__, e)], [], {}


def h(s):
    return int(s, 16)


def _judge(text, runid, build, r1text, r1runid):
    out, fail = core._judge(text, runid, build)
    replan = []
    rec = {}
    facts, _, begin, end = parse(text, runid)
    if begin is None or end is None:
        return out, fail, replan, rec
    for br in facts['bridge']:
        c = h(br['ctl3c'])
        out.append('bridge %s control %04x: VGA forwarding %d' % (br['dev'], c >> 16, (c >> 19) & 1))
        rec['bridge_%s_vga' % br['dev'].replace(':', '_').replace('.', '_')] = (c >> 19) & 1

    # PLL groups
    ps = facts.get('pllstart')
    pe = facts.get('pllend')
    plls = facts['pll']
    if 'vline-static' in facts['stop'] or facts.get('mmio', {}).get('map') != 'ok':
        if ps or plls:
            fail.append('PLL lines after a static VLINE or without a mapping')
        return out, fail, replan, rec
    if ps is None or pe is None:
        fail.append('pllstart or pllend line missing')
        return out, fail, replan, rec
    p0 = h(ps['p0'])
    if 'pllbusy' in facts:
        fail.append('PLL index busy (write enable set) at group %s, p=%s: no index was stored'
                    % (facts['pllbusy']['k'], facts['pllbusy']['p']))
    if 'pllabort' in facts:
        a = facts['pllabort']
        safe = a['a'] == a['p']
        fail.append('PLL group %s aborted (%s): p=%s c=%s d=%s e=%s, wrote p back, re-read %s -- %s'
                    % (a['k'], a['why'], a['p'], a['c'], a['d'], a['e'], a['a'],
                       'SAFE (index back at p)' if safe else 'UNSAFE (index not back at p: reboot before any further run)'))
    if int(pe['groups']) != len(plls):
        fail.append('pllend groups=%s but %d pll lines' % (pe['groups'], len(plls)))
    if [int(x['k']) for x in plls] != list(range(len(plls))):
        fail.append('pll lines out of order: %s' % [x['k'] for x in plls])
    if len(plls) != len(PLL) and 'pllabort' not in facts and 'pllbusy' not in facts:
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

    # R1 comparison
    r1facts, _, r1begin, r1end = pr1.parse(r1text, r1runid)
    r1reg = {n: v for n, (off, v) in r1facts['reg'].items()}
    if r1begin is None or r1end is None or set(r1reg) != set(pr1.REGS):
        fail.append('R1 log does not hold a complete R1 run %s with its %d registers' % (r1runid, len(pr1.REGS)))
    else:
        reg = {n: v for n, (off, v) in facts['reg'].items()}
        if (p0 >> 8) & 3 != (r1reg['CLOCK_CNTL_INDEX'] >> 8) & 3:
            fail.append('PLL_DIV_SEL %d now, %d in R1' % ((p0 >> 8) & 3, (r1reg['CLOCK_CNTL_INDEX'] >> 8) & 3))
        for n in sorted(pr1.REGS):
            if n in VOLATILE or n not in reg:
                continue
            diff = reg[n] ^ r1reg[n]
            if n == 'CLOCK_CNTL_INDEX':
                diff &= 0xffffff00
            if not diff:
                continue
            undef = UNDEFINED_BITS.get(n, 0)
            if diff & ~undef:
                fail.append('%s %08x now, %08x in R1 (documented bits differ: %08x)' % (n, reg[n], r1reg[n], diff & ~undef))
            else:
                replan.append('%s %08x now, %08x in R1 (only undefined bits %08x differ)' % (n, reg[n], r1reg[n], diff))
        if not fail:
            out.append('R1 registers again: %d compared, volatile skipped %s' % (
                len([n for n in pr1.REGS if n not in VOLATILE]), sorted(VOLATILE)))

    # records (R2 plan section 9)
    reg = {n: v for n, (off, v) in facts['reg'].items()}
    if len(vals) == len(PLL):
        pc = vals['PPLL_CNTL']
        vc = vals['VCLK_ECP_CNTL']
        rd = vals['PPLL_REF_DIV']
        d3 = vals['PPLL_DIV_3']
        ht = vals['HTOTAL_CNTL']
        rec.update(ppll_ref_div='%08x' % rd, ppll_div_3='%08x' % d3, ppll_div_0='%08x' % vals['PPLL_DIV_0'],
                   ppll_cntl='%08x' % pc, vclk_ecp_cntl='%08x' % vc, htotal_cntl='%08x' % ht,
                   pixclks_cntl='%08x' % vals['PIXCLKS_CNTL'], mclk_cntl='%08x' % vals['MCLK_CNTL'],
                   sclk_cntl='%08x' % vals['SCLK_CNTL'], x_mpll_ref_fb_div='%08x' % vals['X_MPLL_REF_FB_DIV'],
                   clock_cntl_index_p0='%08x' % p0)
        out.append('PPLL_REF_DIV %08x: refdiv %d, atomic update R/W bit %d' % (rd, rd & 0x3ff, (rd >> 15) & 1))
        out.append('PPLL_DIV_3 %08x: feedback %d, post code %d' % (d3, d3 & 0x7ff, (d3 >> 16) & 7))
        out.append('PPLL_CNTL %08x: RESET %d SLEEP %d bit4 %d bit5 %d ATOMIC_UPDATE_EN %d VGA_ATOMIC_UPDATE_EN %d ATOMIC_UPDATE_VSYNC %d'
                   % (pc, pc & 1, pc >> 1 & 1, pc >> 4 & 1, pc >> 5 & 1, pc >> 16 & 1, pc >> 17 & 1, pc >> 18 & 1))
        out.append('VCLK_ECP_CNTL %08x: source %d (3 = PPLL), PIXCLK_ALWAYS_ONb %d, PIXCLK_DAC_ALWAYS_ONb %d'
                   % (vc, vc & 3, vc >> 6 & 1, vc >> 7 & 1))
        out.append('HTOTAL_CNTL %08x: HTOT_CNTL_VGA_EN %d' % (ht, ht >> 28 & 1))
        rec.update(refdiv=rd & 0x3ff, ppll_cntl_vsync=pc >> 18 & 1, ppll_cntl_vga_atomic=pc >> 17 & 1,
                   vclk_source=vc & 3)
    if all(n in reg for n in INTERFERING):
        nonzero = [n for n in INTERFERING if reg[n]]
        rec['interfering_nonzero'] = ','.join(nonzero) or 'none'
        out.append('interfering clients non-zero: %s' % (', '.join(nonzero) or 'none'))
    for n in ('TV_DAC_CNTL', 'DISP_HW_DEBUG', 'MEM_CNTL', 'MEM_TIMING_CNTL', 'MEM_SDRAM_MODE_REG',
              'CRTC_OFFSET_CNTL', 'DISP_MERGE_CNTL', 'DAC_CNTL2', 'DISP_OUTPUT_CNTL', 'GRPH_BUFFER_CNTL'):
        if n in reg:
            rec[n.lower()] = '%08x' % reg[n]
    if 'MEM_CNTL' in reg:
        out.append('MEM_CNTL %08x: channels bit %d -> RamWidth %d (radeon_driver.c:1632-1637)'
                   % (reg['MEM_CNTL'], reg['MEM_CNTL'] & 1, 128 if reg['MEM_CNTL'] & 1 else 64))
    for r in replan:
        out.append('REPLAN: ' + r)
    return out, fail, replan, rec


# ---- self-test -----------------------------------------------------------

def synthetic(runid='t2', build='1234abcd', p0=0x00000303, plls=None, extra_regs=None, reg_override=None,
              drop_kind=None, abort=None, busy=None, bridge_ctl=True, index_reg=None):
    """An R2a log built from R1's synthetic log: same PCI world and registers,
    R2a prefix, bridge ctl3c, 15 more registers, ten PLL groups.  The
    CLOCK_CNTL_INDEX register line reads p0 unless index_reg is given."""
    r1 = pr1.synthetic(runid='x')
    reg_override = dict(reg_override or {})
    reg_override.setdefault('CLOCK_CNTL_INDEX', p0 if index_reg is None else index_reg)
    body = []
    for l in r1.splitlines():
        m = re.search(r'RDN-R1 x (\w+)(.*) seq=\d+$', l)
        kind, rest = m.group(1), m.group(2)
        if kind in ('begin', 'end'):
            continue
        if kind == 'bridge' and bridge_ctl:
            rest += ' ctl3c=00080000'
        if kind == 'reg' and reg_override:
            name = re.search(r'name=(\w+)', rest).group(1)
            if name in reg_override:
                rest = re.sub(r'val=[0-9a-f]{8}', 'val=%08x' % reg_override[name], rest)
        body.append(kind + rest)
    more = dict((n, 0) for n in REGS if n not in pr1.REGS)
    more.update(extra_regs or {})
    for n in REGS:
        if n not in pr1.REGS:
            body.append('reg name=%s off=%04x val=%08x' % (n, REGS[n], more[n]))
    body.append('pllstart p0=%08x' % p0)
    values = {'PPLL_REF_DIV': 0x0000000c, 'PPLL_DIV_3': 0x000600ad, 'VCLK_ECP_CNTL': 0x00000003}
    groups = PLL if plls is None else PLL[:plls]
    for k, (name, idx) in enumerate(groups):
        c = (p0 & ~0xff) | idx
        body.append('pll k=%d idx=%02x name=%s p=%08x c=%08x val=%08x d=%08x e=%08x'
                    % (k, idx, name, p0, c, values.get(name, 0), c, p0))
    if busy is not None:
        body.append('pllbusy k=%d p=%08x' % (len(groups), busy))
        body.append('stop reason=pll-index-busy')
    if abort is not None:
        body.append('pllabort k=%d why=%s p=%08x c=%08x d=00000000 e=00000000 a=%08x' % ((len(groups),) + abort))
        body.append('stop reason=pll-index-disturbed')
    body.append('pllend groups=%d' % len(groups))
    if drop_kind:
        body = [b for b in body if not b.startswith(drop_kind)]
    n = len(body) + 2
    lines = ['RDN-R2A %s begin version=1 build=%s seq=0' % (runid, build)] + \
            ['RDN-R2A %s %s seq=%d' % (runid, b, i + 1) for i, b in enumerate(body)] + \
            ['RDN-R2A %s end lines=%d seq=%d' % (runid, n, n - 1)]
    return '\n'.join('Sep 15 10:00:00 nextonion mach: ' + l for l in lines) + '\n'


R1_INDEX = 0x00000303          # R1's measured CLOCK_CNTL_INDEX (build/r1/rdn-r1-789453017.log)


def r1_log(index=R1_INDEX):
    """R1's synthetic log, with CLOCK_CNTL_INDEX as R1 measured it."""
    t = pr1.synthetic(runid='r1')
    old = 'name=CLOCK_CNTL_INDEX off=0008 val=00000000'
    assert t.count(old) == 1
    return t.replace(old, 'name=CLOCK_CNTL_INDEX off=0008 val=%08x' % index)


def self_test():
    failures = 0

    def check(label, ok, detail=''):
        nonlocal failures
        print('%-4s %s%s' % ('ok' if ok else 'FAIL', label, '' if ok else ' -- ' + detail))
        failures += not ok

    # the 15 new offsets against the headers
    rt = _load('regtable', os.path.join(PROJ, 'tools', 'oracle', 'regtable.py'))
    tabs = {k: rt.load(p) for k, p in rt.HEADERS}
    for n, off in list(REGS.items()) + [(n, i) for n, i in PLL]:
        hv = {tabs[k][n][0][0] for k in tabs if n in tabs[k]}
        check('offset of %s' % n, hv == {off}, 'here %04x, headers %s' % (off, sorted(hv)))

    # (label, log, r1 log, want: 'PASS'|'FAIL:<substring>'|'REPLAN:<substring>')
    base_r1 = r1_log()
    cases = [
        ('good', synthetic(), base_r1, 'PASS'),
        ('good: records refdiv', synthetic(), base_r1, 'PASS:PPLL_REF_DIV 0000000c: refdiv 12'),
        ('dropped pll line (seq gap)', ''.join(l for l in synthetic().splitlines(True) if ' pll k=4 ' not in l), base_r1,
         'FAIL:sequence broken'),
        ('pll line never written', synthetic(drop_kind='pll k=4'), base_r1, 'FAIL:out of order'),
        ('other runid asked', synthetic(runid='t3'), base_r1, 'FAIL:begin/end'),
        ('c bit 9 changed', synthetic().replace('c=00000302', 'c=00000102', 1), base_r1, 'FAIL:after the index store'),
        ('low byte mismatch', synthetic().replace('c=00000302', 'c=00000342', 1), base_r1, 'FAIL:after the index store'),
        ('d differs from c', synthetic().replace('d=00000307', 'd=00000308', 1), base_r1, 'FAIL:after the data read'),
        ('e differs from p', synthetic().replace('e=00000303 seq=', 'e=00000302 seq=', 1), base_r1, 'FAIL:after the restore'),
        ('p changed between groups', synthetic().replace('idx=09 name=HTOTAL_CNTL p=00000303', 'idx=09 name=HTOTAL_CNTL p=00000203'),
         base_r1, 'FAIL:another writer'),
        ('abort, safe', synthetic(plls=3, abort=('upper', 0x303, 0x103, 0x303)), base_r1, 'FAIL:SAFE (index back at p)'),
        ('abort, unsafe', synthetic(plls=3, abort=('upper', 0x303, 0x103, 0x103)), base_r1, 'FAIL:UNSAFE'),
        ('busy', synthetic(plls=0, busy=0x383, p0=0x383), base_r1, 'FAIL:busy'),
        ('R1 index low byte differs only', synthetic(index_reg=0x00000302), base_r1, 'PASS'),
        ('R1 index bit 12 differs', synthetic(index_reg=0x00001303), base_r1, 'FAIL:CLOCK_CNTL_INDEX'),
        ('documented bit differs', synthetic(reg_override={'CRTC_GEN_CNTL': 0x01000000}), base_r1,
         'FAIL:CRTC_GEN_CNTL'),
        ('undefined bits only differ', synthetic(reg_override={'CRTC_EXT_CNTL': 1 << 25}), base_r1,
         'REPLAN:only undefined bits'),
        ('volatile differs', synthetic(reg_override={'GEN_INT_STATUS': 7, 'RBBM_STATUS': 0x140}), base_r1, 'PASS'),
        ('ctl3c missing', synthetic(bridge_ctl=False), base_r1, 'FAIL:malformed line'),
        ('pll lines out of order', synthetic().replace('pll k=1 ', 'pll k=2 ', 1).replace('pll k=2 idx=04', 'pll k=1 idx=04', 1),
         base_r1, 'FAIL:out of order'),
        ('pll name wrong', synthetic().replace('name=SCLK_CNTL', 'name=MCLK_CNTL', 1), base_r1, 'FAIL:table says'),
        ('PLL_DIV_SEL differs from R1', synthetic(p0=0x00000003, index_reg=0x00000303), base_r1, 'FAIL:PLL_DIV_SEL'),
        ('R1 log of another run', synthetic(), r1_log().replace('RDN-R1 r1', 'RDN-R1 r9'), 'FAIL:R1 log'),
    ]
    for label, text, r1text, want in cases:
        out, fail, replan, rec = judge(text, 't2', '1234abcd', r1text, 'r1')
        kind, _, sub = want.partition(':')
        if kind == 'PASS':
            ok = not fail and not replan and (not sub or any(sub in o for o in out))
        elif kind == 'FAIL':
            ok = any(sub in f for f in fail)
        else:
            ok = not fail and any(sub in r for r in replan)
        check(label, ok, 'fail=%s replan=%s' % (fail[:2], replan[:2]))
    # the R1 log R1 really passed with (if present) is accepted as the comparison base
    real = os.path.join(PROJ, 'build', 'r1', 'rdn-r1-789453017.log')
    if os.path.exists(real):
        rt1 = open(real, errors='replace').read()
        _, f1 = pr1.judge(rt1, '789453017', 'ba397d2b')
        r1f, _, _, _ = pr1.parse(rt1, '789453017')
        idx = r1f['reg'].get('CLOCK_CNTL_INDEX', (0, None))[1]
        check('real R1 log passes R1 and has index %08x' % (idx or 0), not f1 and idx == R1_INDEX, str(f1[:2]))
    # every single-line corruption of the good log fails without raising
    good = synthetic().splitlines()
    ok0 = judge('\n'.join(good) + '\n', 't2', '1234abcd', base_r1, 'r1')
    check('baseline for corruption passes', not ok0[1] and not ok0[2], str(ok0[1][:2]))
    corrupt = [lambda l: l.replace('seq=', 'seq=x'), lambda l: l.replace('p=', 'p=g'),
               lambda l: l.replace('idx=', 'idx=1'), lambda l: l.replace('ctl3c=', 'ctl3c=z'),
               lambda l: l.replace('groups=', 'groups=-'), lambda l: l[:len(l) // 2],
               lambda l: l + ' extra=1', lambda l: l.replace('p0=', 'q0=')]
    tried = leaked = 0
    for c in corrupt:
        for i in range(len(good)):
            t = good[:]
            t[i] = c(t[i])
            if t[i] == good[i]:
                continue
            tried += 1
            _, fail, _, _ = judge('\n'.join(t) + '\n', 't2', '1234abcd', base_r1, 'r1')
            if not fail or any('parser raised' in f for f in fail):
                leaked += 1
                print('FAIL corruption passed or raised: %s' % t[i][-80:])
    check('single-line corruption: %d logs, %d leaked' % (tried, leaked), leaked == 0 and tried > 100)
    print('parse_r2a self-test: %s' % ('PASS' if failures == 0 else 'FAIL (%d)' % failures))
    return failures == 0


def main(argv):
    if argv[1:] == ['--self-test']:
        return 0 if self_test() else 1
    args = argv[1:]
    outdir = None
    if '--out' in args:
        i = args.index('--out')
        outdir = args[i + 1]
        args = args[:i] + args[i + 2:]
    if len(args) != 5:
        print(__doc__)
        return 2
    log, runid, build, r1log, r1runid = args
    out, fail, replan, rec = judge(open(log, errors='replace').read(), runid, build,
                                   open(r1log, errors='replace').read(), r1runid)
    for o in out:
        print(o)
    for f in fail:
        print('FAIL ' + f)
    verdict = 'FAIL' if fail else ('REPLAN' if replan else 'PASS')
    if outdir:
        path = os.path.join(outdir, 'r2a-facts-%s.txt' % runid)
        with open(path, 'w') as fh:
            fh.write('verdict=%s\n' % verdict)
            for k in sorted(rec):
                fh.write('%s=%s\n' % (k, rec[k]))
        print('facts: %s' % path)
    print('R2A: %s' % verdict)
    return {'PASS': 0, 'FAIL': 1, 'REPLAN': 2}[verdict]


if __name__ == '__main__':
    sys.exit(main(sys.argv))
