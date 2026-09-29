#!/usr/bin/env python3
"""Judge one R5 boot's RDN-R5 lines against docs/R5_PLAN.md 8 and 9-2.

  check_cp.py <rdn-all.log> [--tail-submit N]
                                 judge the log (the boot is the last select line's); N: one
                                 SUBMIT of N words after NEGCTL (docs/R5_STOPFIX_PLAN.md 8)
  check_cp.py --self-test        the rules on built-in logs, each shown to fail

Recomputed here, not taken from the log: every GART entry from the block's
physical address (the table's sum and xor), the markers from each seed, and
where REG1 must straddle a 1 KiB ring boundary.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
MODELOG = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_modelog.m')
CLASS = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'OSRDNDisplay.m')

POISON = 0x5a5a0005
RING = 4096
SCHEDULE = [1024, 1024, 1024, 1024, 1008, 1024, 1024, 1024]       # plan 7-2 B4
R1_AGP = 0x27ff2000                                               # docs/R1_RESULT.md 36
R1_FB = 0x1fff0000
M32 = 0xffffffff
HI_WANT = 0x207fffff
HI_OK = set(HI_WANT & ~((1 << k) - 1) for k in range(13))      # docs/R5_PLAN.md 12-5 G2
MG_REG = {0x0704: 'RB_CNTL', 0x0770: 'SCRATCH_UMSK', 0x01d8: 'AIC_PT_BASE', 0x01dc: 'AIC_LO_ADDR',
          0x01e0: 'AIC_HI_ADDR', 0x01d0: 'AIC_CNTL', 0x0700: 'CP_RB_BASE', 0x070c: 'CP_RB_RPTR_ADDR',
          0x0710: 'CP_RB_RPTR', 0x0714: 'CP_RB_WPTR', 0x0040: 'GEN_INT_CNTL', 0x014c: 'MC_AGP_LOCATION',
          0x15f4: 'SCRATCH_REG5'}


def pte(phys, e):
    off = 0x4000 + e * 0x1000 if e < 4 else (0x3000 if e == 4 else 0x2000)
    return (phys + off) & 0xfffff000


def table_sums(phys):
    s = x = 0
    for e in range(2048):
        v = pte(phys, e)
        s = (s + v) & M32
        x ^= v
    return s, x


def marker(seed, k):
    return (seed ^ (0x9e3779b9 * (k + 1))) & M32


def straddle(p, n):
    b = (p // 1024 + 1) * 1024
    if b - 1 >= p + 2 and b + 1 <= p + n - 3:
        return 1, b % RING
    return 0, 0


def parse(text):
    sel = re.findall(r'RDN-R3 select boot=(\w+) ', text)
    boot = sel[-1] if sel else None
    blocks, ops, cur = [], [], None
    for line in text.splitlines():
        m = re.search(r'RDN-R5 block boot=(\w+) va=([0-9a-f]{8}) phys=([0-9a-f]{8}) len=([0-9a-f]{8}) (\S+)', line)
        if m and m.group(1) == boot:
            blocks.append(dict(phys=int(m.group(3), 16), len=int(m.group(4), 16), why=m.group(5)))
            continue
        m = re.search(r'RDN-R5 (record|load|map|reset|start|submit|negctl|stop|inject|rec3d|zprep|zclear|bad) boot=(\w+) n=(\d+) arg=([0-9a-f]{8}) '
                      r'len=(\d+) rc=(-?\d+) why=(\d+) gv=([0-9a-f]{8})(?: greg=([0-9a-f]{4}))? us=(\d+)', line)
        if m:
            cur = None
            if m.group(2) == boot:
                cur = dict(op=m.group(1), arg=int(m.group(4), 16), len=int(m.group(5)), rc=int(m.group(6)),
                           why=int(m.group(7)), gv=m.group(8), greg=int(m.group(9) or '0', 16), rec={}, mg={})
                ops.append(cur)
            continue
        if cur is None:
            continue
        m = re.search(r'RDN-R5 state state=(\d+) latched=(\d) reset=(\d) failed=(\d) wptr=(\d+) phys=([0-9a-f]{8})', line)
        if m:
            cur.update(state=int(m.group(1)), latched=int(m.group(2)), reset=int(m.group(3)), failed=int(m.group(4)),
                       wptr=int(m.group(5)), phys=int(m.group(6), 16))
        m = re.search(r'RDN-R5 state .* csqstat=([0-9a-f]{8})(?: csq2stat=([0-9a-f]{8}) csqread=(\d))?', line)
        if m:
            cur['csq'] = (m.group(1), m.group(2), m.group(3))
        m = re.search(r'RDN-R5 io wr=(\d+) rd=(\d+) aicstat=([0-9a-f]{8}) inject=(\d+) injected=(\d)', line)
        if m:
            cur.update(wr=int(m.group(1)), rd=int(m.group(2)), aicstat=int(m.group(3), 16),
                       inject=int(m.group(4)), injected=int(m.group(5)))
        m = re.search(r'RDN-R5 mapgate bad=([0-9a-f]{4})', line)
        if m:
            cur['mgbad'] = int(m.group(1), 16)
        m = re.search(r'RDN-R5 mg\d ((?:\w+=[0-9a-f]{8} ?)+)', line)
        if m:
            for k, v in re.findall(r'(\w+)=([0-9a-f]{8})', m.group(1)):
                cur['mg'][k] = int(v, 16)
        m = re.search(r'RDN-R5 rec\d ((?:\w+=[0-9a-f]{8} ?)+)', line)
        if m:
            for k, v in re.findall(r'(\w+)=([0-9a-f]{8})', m.group(1)):
                cur['rec'][k] = int(v, 16)
        m = re.search(r'RDN-R5 reset mclk=(\w{8}) forced=(\w{8}) after=(\w{8}) idx=(\w{8}) idxafter=(\w{8}) '
                      r'soft=(\w{8}) softafter=(\w{8})', line)
        if m:
            cur['reset_vals'] = [int(x, 16) for x in m.groups()]
        m = re.search(r'RDN-R5 marks m0=(\w{8}) m1=(\w{8}) m2=(\w{8}) s0=(\w{8}) s1=(\w{8}) s2=(\w{8})', line)
        if m:
            v = [int(x, 16) for x in m.groups()]
            cur['m'], cur['s'] = v[:3], v[3:]
        m = re.search(r'RDN-R5 got g0=(\w{8}) g1=(\w{8}) g2=(\w{8}) straddle=(\d) boundary=(\d+)', line)
        if m:
            cur['g'] = [int(x, 16) for x in m.groups()[:3]]
            cur['straddle'] = (int(m.group(4)), int(m.group(5)))
        m = re.search(r'RDN-R5 ptrs rbefore=(\d+) rafter=(\d+) wafter=(\d+) reg5=(\w{8})(?: roff=(\w{8}) woff=(\w{8}))?', line)
        if m:
            cur.update(rbefore=int(m.group(1)), rafter=int(m.group(2)), wafter=int(m.group(3)), reg5=int(m.group(4), 16))
            if m.group(5):
                cur.update(roff=int(m.group(5), 16), woff=int(m.group(6), 16))
        m = re.search(r'RDN-R5 block table=(\d+) guard=(\d+) spare=(\d+) canary=(\d+) ring=(\d+) sum=(\w{8}) xor=(\w{8})', line)
        if m:
            cur['bad'] = [int(x) for x in m.groups()[:5]]
            cur['sum'], cur['xor'] = int(m.group(6), 16), int(m.group(7), 16)
        # M2b appended /t<turns> to every field; the limit flags stay where they were
        m = re.search(r'RDN-R5 wait fifo=\d+/(\d)(?:/t\d+)? idle=\d+/(\d)/\d+(?:/t\d+)? '
                      r'rptr=\d+/(\d)/\d+(?:/t\d+)? idle2=\d+/(\d)(?:/t\d+)? dc=\d+/(\d)(?:/t\d+)?', line)
        if m:
            cur['limits'] = [int(x) for x in m.groups()]
    cycle = None
    lines = text.splitlines()
    idx = [k for k, l in enumerate(lines) if boot and re.search(r'RDN-R2B cycled boot=%s live=1' % re.escape(boot), l)]
    if idx:
        for l in lines[idx[-1] + 1:]:
            m = re.search(r'RDN-R2B cycle n=\d+ why=-?\d+ checked=(\d+) cwhy=-?\d+ bad=(\d+) vga=(\d+) palette=(\d+) '
                          r'kernel=\d+ verdict=(-?\d+)', l)
            if m:
                cycle = m.groups()
                break
    return boot, blocks, ops, cycle


def judge(text, skip_key_refusals=False, tail=None):
    """skip_key_refusals: drop INJECT calls the driver refused for want of its key
    (R5d boot B runs one before the R5 procedure; tools/r5/check_r5d.py judges it)"""
    p, notes = [], []
    boot, blocks, ops, cycle = parse(text)
    if skip_key_refusals:
        ops = [o for o in ops if not (o['op'] == 'inject' and o['rc'] == 1 and o['why'] == 1)]
    if boot is None:
        return ['no RDN-R3 select line'], notes
    if len(blocks) != 1:
        return ['%d block lines for boot %s' % (len(blocks), boot)], notes
    blk = blocks[0]
    if blk['why'] != 'ok' or blk['len'] != 0x10000 or blk['phys'] & 0xffff or blk['phys'] + 0x10000 > 0xa0000:
        p.append('block: %s' % blk)
    phys = blk['phys']
    # tail: one more SUBMIT of that length after NEGCTL, so STOP runs away from
    # wptr 0 (docs/R5_STOPFIX_PLAN.md 8; the schedule alone ends at 8192 = 0 mod 4096)
    want_order = ['record', 'load', 'map', 'record', 'reset', 'record', 'start'] + ['submit'] * 8 + ['negctl'] + \
        (['submit'] if tail else []) + ['stop', 'record']
    sched = SCHEDULE + ([tail] if tail else [])
    names = [o['op'] for o in ops]
    if names != want_order:
        p.append('the operations were %s, the procedure is %s' % (names, want_order))
    for o in ops:
        tag = o['op']
        if o.get('latched'):
            p.append('%s: the CP is latched' % tag)
        if o['rc'] != 0:
            p.append('%s: rc %d why %d gv %s%s' % (tag, o['rc'], o['why'], o['gv'],
                                                  ' greg %04x (%s)' % (o['greg'], MG_REG.get(o['greg'], '?'))
                                                  if o['greg'] else ''))
        if tag in ('map', 'reset', 'start') and o.get('mgbad', -1) != 0:
            p.append('%s: the MAP gate mask %s, read-backs %s' % (tag, o.get('mgbad'), dict(
                (k, '%08x' % v) for k, v in o['mg'].items())))
        if o['mg']:
            # judged here again, not taken from the driver's mask
            g = o['mg']
            want = dict(rbcntl=0x0804090b, umsk=0, ptbase=phys, lo=0x20000000, rbbase=0x20000000, rptraddr=0x20004000,
                        intcntl=0, agploc=0xffffffc0, s5=POISON)
            wrong = ['%s=%08x' % (k, g.get(k, 0)) for k, v in want.items() if g.get(k) != v]
            if g.get('hi') not in HI_OK:
                wrong.append('hi=%08x' % g.get('hi', 0))
            if g.get('aic', 0) & 3 != 3:
                wrong.append('aic=%08x' % g.get('aic', 0))
            if (g.get('rptr', -1) & 4095) != (g.get('wptr', -2) & 4095):
                wrong.append('rptr=%08x wptr=%08x' % (g.get('rptr', 0), g.get('wptr', 0)))
            if wrong:
                p.append('%s: read back %s' % (tag, ' '.join(wrong)))
        if o.get('failed'):
            p.append('%s: failed' % tag)
        if o.get('phys') not in (None, phys):
            p.append('%s: phys %08x, the block line says %08x' % (tag, o.get('phys'), phys))
        if any(o.get('limits', [0])) and tag != 'negctl':
            p.append('%s: a wait ended on its limit %s' % (tag, o.get('limits')))
        if tag not in ('record', 'load') and o.get('bad') and any(o['bad']):
            p.append('%s: block words changed (table guard spare canary ring) %s' % (tag, o['bad']))
    # records, shown on a failing run too (never judged: docs/R5_PLAN.md 12-5 G3)
    for o in ops:
        if o.get('csq'):
            notes.append('%s: CSQ_STAT %s CSQ2_STAT %s read %s (a record, not judged)' % ((o['op'],) + o['csq']))
        if o['mg']:
            notes.append('%s: read-backs %s' % (o['op'], ' '.join('%s=%08x' % kv for kv in o['mg'].items())))
    if p:
        return p, notes
    rec = [o for o in ops if o['op'] == 'record']
    first, last = rec[0]['rec'], rec[3]['rec']
    if first.get('csq', 1) & 0xf0000000 or first.get('aic', 1) & 1 or first.get('intcntl', 1) != 0:
        p.append('record 1: CSQ %08x AIC %08x GEN_INT_CNTL %08x' % (first.get('csq', 0), first.get('aic', 0),
                                                                    first.get('intcntl', 0)))
    if first.get('agploc') != R1_AGP or first.get('mcfb') != R1_FB:
        p.append('record 1: MC_AGP %08x MC_FB %08x, R1 read %08x %08x' % (first.get('agploc', 0), first.get('mcfb', 0),
                                                                         R1_AGP, R1_FB))
    notes.append('record 1: CSQ_MODE %08x SCLK %08x MCLK %08x AGP_COMMAND %08x BUS %08x' % (
        first.get('csqmode', 0), first.get('sclk', 0), first.get('mclk', 0), first.get('agpcmd', 0), first.get('bus', 0)))
    s, x = table_sums(phys)
    mp = [o for o in ops if o['op'] == 'map'][0]
    if (mp.get('sum'), mp.get('xor')) != (s, x):
        p.append('map: the table reads back sum %08x xor %08x, the PTEs from phys %08x give %08x %08x' % (
            mp.get('sum', 0), mp.get('xor', 0), phys, s, x))
    for where, mid in (('record 2 (after MAP)', rec[1]['rec']), ('record 3 (after RESET)', rec[2]['rec'])):
        if mid.get('aic', 0) & 3 != 3 or mid.get('lo') != 0x20000000 or mid.get('hi') not in HI_OK or \
                mid.get('ptbase') != phys or mid.get('rbcntl') != 0x0804090b or mid.get('umsk') != 0 or \
                mid.get('agploc') != 0xffffffc0 or mid.get('rbbase') != 0x20000000 or mid.get('s5') != POISON:
            p.append('%s: %s' % (where, dict((k, '%08x' % mid.get(k, 0)) for k in
                                             ('aic', 'lo', 'hi', 'ptbase', 'rbcntl', 'umsk', 'agploc', 'rbbase', 's5'))))
    rs = [o for o in ops if o['op'] == 'reset'][0].get('reset_vals')
    if not rs or rs[2] != rs[0] or rs[1] != (rs[0] | 0x003f0000) or (rs[4] & 0xff) != (rs[3] & 0xff) or rs[6] != rs[5]:
        p.append('reset: MCLK/index/soft reset not put back: %s' % (['%08x' % v for v in rs] if rs else None))
    st = [o for o in ops if o['op'] == 'start'][0]
    if st.get('state') != 3 or st.get('rafter') != 16 or st.get('wafter') != 16 or st.get('reg5') != POISON:
        p.append('start: state %s rptr %s wptr %s reg5 %s' % (st.get('state'), st.get('rafter'), st.get('wafter'),
                                                              st.get('reg5')))
    wp = 16
    wp_neg = None
    for i, o in enumerate([o for o in ops if o['op'] == 'submit']):
        if i == len(SCHEDULE):
            wp_neg = wp                     # NEGCTL ran between the schedule and the tail
        n = sched[i] if i < len(sched) else -1
        want = [marker(o['arg'], k) for k in range(3)]
        if o['len'] != n:
            p.append('submit %d: len %d, the schedule says %d' % (i, o['len'], n))
        if o.get('m') != want or o.get('g') != want:
            p.append('submit %d: markers %s read back %s, want %s' % (i, o.get('m'), o.get('g'), want))
        if o.get('s') != [(~v) & M32 for v in want]:
            p.append('submit %d: sentinels are not the markers inverted' % i)
        if o.get('rbefore') != wp:
            p.append('submit %d: started at %s, want %d' % (i, o.get('rbefore'), wp))
        if o.get('straddle') != straddle(wp, n):
            p.append('submit %d: straddle %s, want %s' % (i, o.get('straddle'), straddle(wp, n)))
        wp = (wp + n) % RING
        if o.get('wafter') != wp or o.get('rafter') != wp or o.get('reg5') != POISON:
            p.append('submit %d: rptr %s wptr %s reg5 %s, want %d' % (i, o.get('rafter'), o.get('wafter'), o.get('reg5'), wp))
    if wp_neg is None:
        wp_neg = wp
    ng = [o for o in ops if o['op'] == 'negctl'][0]
    if ng.get('g') != ng.get('s') or ng.get('rafter') != wp_neg or ng.get('g') == [marker(ng['arg'], k) for k in range(3)]:
        p.append('negctl: got %s sentinels %s rptr %s (want %d)' % (ng.get('g'), ng.get('s'), ng.get('rafter'), wp_neg))
    sp = [o for o in ops if o['op'] == 'stop'][0]
    if sp.get('state') != 4:
        p.append('stop: state %s, want 4 (STOPPED)' % sp.get('state'))
    if sp.get('rafter') != wp:
        p.append('stop: RPTR %s before the CSQ went off, want the last WPTR %d' % (sp.get('rafter'), wp))
    # after the CSQ is off: records only (RPTR reads 0 there, boot eae3072b)
    notes.append('stop: wptr %d, after CSQ off RPTR %s WPTR %s; the last RECORD rptr %s wptr %s' % (
        wp, sp.get('roff'), sp.get('woff'), last.get('rptr'), last.get('wptr')))
    if last.get('csq', 1) & 0xf0000000 or last.get('aic', 1) & 1 or last.get('agploc') != first.get('agploc') or \
            last.get('agpcmd') != first.get('agpcmd'):
        p.append('record 4 (after STOP): CSQ %08x AIC %08x AGP %08x/%08x cmd %08x/%08x' % (
            last.get('csq', 0), last.get('aic', 0), last.get('agploc', 0), first.get('agploc', 0),
            last.get('agpcmd', 0), first.get('agpcmd', 0)))
    if cycle != ('1', '0', '0', '0', '0'):
        p.append('the cycle after STOP: %s' % (cycle,))
    return p, notes


# ---- a synthetic clean boot, built from the same rules as the driver --------------------
def good_log(phys=0x00070000, tail=None):
    L = ['mach: RDN-R3 select boot=aaaa0001 res=800x600 fmt=RGB:888/32 rdflt=0',
         'mach: RDN-R5 keys boot=aaaa0001 test=1 inject=0 3d=0 build=65b66543',
         'mach: RDN-R5 block boot=aaaa0001 va=12340000 phys=%08x len=00010000 ok' % phys]
    n = [0]

    def op(name, arg=0, ln=0, state=0, extra=(), rec=None, rb=0, ra=0, wa=0, reg5=0, bad=(0, 0, 0, 0, 0), sums=(0, 0)):
        n[0] += 1
        L.append('mach: RDN-R5 %s boot=aaaa0001 n=%d arg=%08x len=%d rc=0 why=0 gv=00000000 greg=0000 us=100'
                 % (name, n[0], arg, ln))
        L.append('mach: RDN-R5 state state=%d latched=0 reset=1 failed=0 wptr=%d phys=%08x post=00000000 csqstat=02000603 '
                 'csq2stat=00000000 csqread=1 nowb=0 spin=0 time=0' % (state, wa, phys))
        if name in ('map', 'reset', 'start'):
            mg = [('rbcntl', 0x0804090b), ('umsk', 0), ('ptbase', phys), ('lo', 0x20000000), ('hi', 0x207ff000),
                  ('aic', 3), ('rbbase', 0x20000000), ('rptraddr', 0x20004000), ('rptr', wa), ('wptr', wa),
                  ('intcntl', 0), ('agploc', 0xffffffc0), ('s5', POISON), ('agpcmd', 0), ('aicstat', 4)]
            L.append('mach: RDN-R5 mapgate bad=0000')
            for k in range(0, 15, 5):
                L.append('mach: RDN-R5 mg%d ' % (k // 5) + ' '.join('%s=%08x' % kv for kv in mg[k:k + 5]))
        if rec:
            names = list(rec)
            for k in range(0, len(names), 6):
                L.append('mach: RDN-R5 rec%d ' % (k // 6) + ' '.join('%s=%08x' % (x, rec[x]) for x in names[k:k + 6]))
        L.append('mach: RDN-R5 io wr=3 rd=40 aicstat=00000004 inject=0 injected=0')
        L.extend(extra)
        L.append('mach: RDN-R5 ptrs rbefore=%d rafter=%d wafter=%d reg5=%08x roff=00000000 woff=%08x' % (rb, ra, wa, reg5, wa))
        L.append('mach: RDN-R5 block table=%d guard=%d spare=%d canary=%d ring=%d sum=%08x xor=%08x' % (bad + sums))
        L.append('mach: RDN-R5 wait fifo=1/0/t0 idle=1/0/10/t0 rptr=1/0/10/t0 '
                 'idle2=1/0/t0 dc=0/0/t0 retry=0 resets=0')     # G4-3 K1: the two fields at the END

    rec1 = dict(rbbm=0x140, csq=0x02010080, aic=0, intcntl=0, agploc=R1_AGP, mcfb=R1_FB, csqmode=0, sclk=0x7ffa,
                mclk=0x1234, agpcmd=0xabcd, bus=0, lo=0, hi=0, ptbase=0, rbcntl=0, rptraddr=0, isync=0,
                rbbase=0xcdcdcdcc, s5=0xcdcdcdcd)
    s, x = table_sums(phys)
    op('record', rec=rec1)
    op('load', state=1)
    op('map', state=2, sums=(s, x))
    rec2 = dict(rec1, aic=3, lo=0x20000000, hi=0x207ff000, ptbase=phys, rbcntl=0x0804090b, umsk=0, agploc=0xffffffc0,
                rbbase=0x20000000, s5=POISON, csq=0x02010080)
    op('record', state=2, rec=rec2, sums=(s, x))
    op('reset', state=2, extra=['mach: RDN-R5 reset mclk=00001234 forced=003f1234 after=00001234 idx=00000300 '
                                'idxafter=00000300 soft=00000000 softafter=00000000'], sums=(s, x))
    op('record', state=2, rec=rec2, sums=(s, x))
    op('start', state=3, rb=0, ra=16, wa=16, reg5=POISON, sums=(s, x))
    wp = 16
    for i, ln in enumerate(SCHEDULE):
        seed = (0x1000 + i) * 2654435761 & M32
        m = [marker(seed, k) for k in range(3)]
        sd, b = straddle(wp, ln)
        nwp = (wp + ln) % RING
        op('submit', seed, ln, 3, extra=['mach: RDN-R5 marks m0=%08x m1=%08x m2=%08x s0=%08x s1=%08x s2=%08x' %
                                         tuple(m + [(~v) & M32 for v in m]),
                                         'mach: RDN-R5 got g0=%08x g1=%08x g2=%08x straddle=%d boundary=%d' % tuple(m + [sd, b])],
           rb=wp, ra=nwp, wa=nwp, reg5=POISON, sums=(s, x))
        wp = nwp
    seed = 0x77777777
    m = [marker(seed, k) for k in range(3)]
    sv = [(~v) & M32 for v in m]
    op('negctl', seed, 16, 3, extra=['mach: RDN-R5 marks m0=%08x m1=%08x m2=%08x s0=%08x s1=%08x s2=%08x' % tuple(m + sv),
                                     'mach: RDN-R5 got g0=%08x g1=%08x g2=%08x straddle=0 boundary=0' % tuple(sv)],
       rb=wp, ra=wp, wa=wp, reg5=POISON, sums=(s, x))
    if tail:
        seed = 0x88888888
        m = [marker(seed, k) for k in range(3)]
        sd, b = straddle(wp, tail)
        nwp = (wp + tail) % RING
        op('submit', seed, tail, 3, extra=['mach: RDN-R5 marks m0=%08x m1=%08x m2=%08x s0=%08x s1=%08x s2=%08x' %
                                           tuple(m + [(~v) & M32 for v in m]),
                                           'mach: RDN-R5 got g0=%08x g1=%08x g2=%08x straddle=%d boundary=%d' % tuple(m + [sd, b])],
           rb=wp, ra=nwp, wa=nwp, reg5=POISON, sums=(s, x))
        wp = nwp
    op('stop', state=4, rb=0, ra=wp, wa=wp, sums=(s, x))
    op('record', state=4, rec=dict(rec1), sums=(s, x))
    L.append('mach: RDN-R2B cycled boot=aaaa0001 live=1')
    L.append('mach: RDN-R2B cycle n=1 why=0 checked=1 cwhy=0 bad=0 vga=0 palette=0 kernel=0 verdict=0')
    # M1x: the stage line, ONCE, after the operations.
    #
    # The driver prints it only for CP_OP_TDUMP, so putting it on every
    # operation (the first attempt) changed the operation shapes and broke four
    # mutations that count them.  The rule it satisfies is that every IOLog
    # format the driver has must have a synthetic line matching it -- a format
    # no judge has ever parsed is one that can be malformed on the machine with
    # nobody the wiser.
    L.append('mach: RDN-R5 tstage boot=aaaa0001 ops=100 gates=1000 pre=2000 '
             's1ring=3000 s1read=10000 s2asm=4000 s2ring=5000 flush=6000 '
             'tail=5600 fence=4000 wait=3000 put=1000')   # M1z and M2b appended these
    # G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 10-1): the accepted submissions' line, printed on ASUBMIT,
    # RETIRE, TDUMP and a latch -- the same place as the tstage line, for the same reason
    L.append('mach: RDN-R5 async boot=aaaa0001 asubmits=21 inflight=0 retires=1 waited=1 retireus=900 last=900 '
             'markbad=0 lost=0 space=19 spaceus=20000 sres=5 kickskip=0')
    # REL1 B7 (docs/REL1_PACKAGING_PLAN.md 16): the first client's open brings the CP up and says
    # so in one line -- not an operation line (no n=), so the operation counts are unchanged
    L.append('mach: RDN-R5 autostart boot=aaaa0001 try=1 ran=6 rc=0 why=0 val=00000000 state=3')
    return '\n'.join(L) + '\n'


BAD = [
    ('the block is above 640 KiB', lambda t: t.replace('phys=00070000 len=00010000 ok', 'phys=000a0000 len=00010000 ok', 1)),
    ('an operation latched', lambda t: t.replace('latched=0', 'latched=1', 3)),
    ('a PTE is wrong', lambda t: re.sub(r'(RDN-R5 map [^\n]*\n(?:[^\n]*\n)*?[^\n]*sum=)([0-9a-f]{8})', lambda m: m.group(1) + '%08x' % (int(m.group(2), 16) ^ 1), t, count=1)),
    ('the AGP aperture was not moved', lambda t: t.replace('agploc=ffffffc0', 'agploc=27ff2000', 1)),
    ('writeback left on', lambda t: t.replace('rbcntl=0804090b', 'rbcntl=0004090b', 1)),
    ('the reset left MCLK forced', lambda t: t.replace('after=00001234', 'after=003f1234', 1)),
    ('a marker read back wrong', lambda t: re.sub(r'got g0=([0-9a-f]{8})', 'got g0=deadbeef', t, count=1)),
    ('REG1 did not straddle', lambda t: t.replace('straddle=1', 'straddle=0', 1)),
    ('the spare page changed (writeback)', lambda t: re.sub(r'(RDN-R5 submit[^\n]*\n(?:[^\n]*\n){5})mach: RDN-R5 block table=0 guard=0 spare=0',
                                                            lambda m: m.group(1) + 'mach: RDN-R5 block table=0 guard=0 spare=1', t, count=1)),
    ('negctl ran the markers', lambda t: re.sub(r'(RDN-R5 negctl[^\n]*\n[^\n]*\n[^\n]*\n[^\n]*\n)mach: RDN-R5 got g0=([0-9a-f]{8})',
                                                lambda m: m.group(1) + 'mach: RDN-R5 got g0=%08x' % (~int(m.group(2), 16) & M32), t, count=1)),
    ('STOP did not put the AGP aperture back', lambda t: t[:t.rindex('agploc=')] + 'agploc=ffffffc0' + t[t.rindex('agploc=') + 15:]),
    ('the MAP gate saw a mismatch', lambda t: t.replace('mapgate bad=0000', 'mapgate bad=0010', 1)),
    ('HI read back with a hole in its low bits', lambda t: t.replace('hi=207ff000', 'hi=207ff7ff', 1)),
    ('HI read back 4 MiB lower', lambda t: t.replace('hi=207ff000', 'hi=20400000', 2)),
    ('a MAP that refused (with greg)', lambda t: re.sub(r'RDN-R5 map (boot=\w+ n=\d+ arg=\w+ len=\d+) rc=0 why=0 gv=00000000 greg=0000',
                                                         r'RDN-R5 map \1 rc=7 why=10 gv=207ff7ff greg=01e0', t, count=1)),
    ('the record after MAP is missing', lambda t: re.sub(r'(RDN-R5 map [^\n]*\n(?:mach: RDN-R5 (?:state|io|mapgate|mg\d|ptrs|block|wait)[^\n]*\n)+)'
                                                          r'mach: RDN-R5 record boot[^\n]*\n(?:mach: RDN-R5 (?:state|io|rec\d|ptrs|block|wait)[^\n]*\n)+',
                                                          r'\1', t, count=1)),
    ('the cycle failed', lambda t: t.replace('palette=0 kernel=0 verdict=0', 'palette=2 kernel=0 verdict=1')),
    ('a submit is missing', lambda t: re.sub(r'mach: RDN-R5 submit boot[^\n]*\n(?:mach: RDN-R5 (?:state|io|marks|got|ptrs|block|wait)[^\n]*\n)+', '', t, count=1)),
]


def driver_formats():
    text = open(MODELOG).read() + open(CLASS).read()
    fm = []
    for m in re.finditer(r'IOLog\(((?:"[^"]*"\s*)+)', text):
        s = ''.join(re.findall(r'"([^"]*)"', m.group(1)))
        if s.startswith('RDN-R5 '):
            fm.append(s.replace('\\n', ''))
    return fm


def format_check():
    """every RDN-R5 line the synthetic log uses has a driver format that renders to it"""
    fm = driver_formats()
    heads = set(re.match(r'RDN-R5 (%s|\w+)', f).group(1) for f in fm)
    need = {'%s', 'state', 'rec', 'reset', 'marks', 'got', 'ptrs', 'block', 'wait', 'begin', 'skip', 'mapgate', 'mg',
            'io', 'keys'}
    miss = need - heads
    p = ['driver formats missing for %s' % sorted(miss)] if miss else []
    g = good_log()
    for f in fm:
        pat = re.escape(f)
        pat = pat.replace(re.escape('%08x'), '[0-9a-f]{8}').replace(re.escape('%04x'), '[0-9a-f]{4}').replace(re.escape('%u'), r'\d+').replace(re.escape('%d'), r'-?\d+')
        pat = pat.replace(re.escape('%s'), r'\w+')
        if f.startswith('RDN-R5 block boot=') or f.startswith('RDN-R5 begin') or f.startswith('RDN-R5 skip'):
            continue
        # M3e: `kept` is printed only by a RECORD a LATCH refused -- a good run has
        # no latch, so the good log cannot hold it.  The parser's head pattern
        # does not take `kept`, so the re-printed record's own head (the kept
        # operation's) is what it would read; that happens only after a latch,
        # which fails a boot on its own (docs/M3E_PLAN.md 2).
        if f.startswith('RDN-R5 kept boot='):
            continue
        # M3i: the latch dump -- `latch` in the record, `fifo`/`near` from the second
        # refused RECORD -- exists only after a latch, which fails a boot on its own
        if f.startswith('RDN-R5 latch ') or f.startswith('RDN-R5 fifo boot=') or f.startswith('RDN-R5 near boot='):
            continue
        if not re.search(pat, g):
            p.append('no synthetic line matches the driver format %r' % f[:70])
    return p


def self_test():
    fails = 0
    fp = format_check()
    for x in fp:
        print('  FAIL %s' % x)
    print('  %-4s the synthetic lines match the driver\'s own IOLog formats' % ('FAIL' if fp else 'ok'))
    fails += len(fp)
    g = good_log()
    p, _ = judge(g)
    print('  %-4s the clean boot passes%s' % ('FAIL' if p else 'ok', '' if not p else ': %s' % p[:3]))
    fails += 1 if p else 0
    t16 = good_log(tail=16)
    p16, _ = judge(t16, tail=16)
    print('  %-4s the clean boot with a tail SUBMIT 16 passes%s' % ('FAIL' if p16 else 'ok', '' if not p16 else ': %s' % p16[:3]))
    fails += 1 if p16 else 0
    for label, t, tl in (
            ('tail: STOP read RPTR 0 (the old check\'s value)', re.sub(r'(RDN-R5 stop boot=[^\n]*\n(?:[^\n]*\n){2})mach: RDN-R5 ptrs rbefore=0 rafter=16 ',
                                                                   r'\1mach: RDN-R5 ptrs rbefore=0 rafter=0 ', t16), 16),
            ('tail: judged without --tail-submit', t16, None),
            ('tail: the tail SUBMIT missing', good_log(), 16)):
        bp, _ = judge(t, tail=tl)
        print('  %-4s %-44s %s' % ('ok' if bp else 'FAIL', label, bp[:1] if bp else 'NOT CAUGHT'))
        fails += 0 if bp else 1
    for label, f in BAD:
        t = f(g)
        if t == g:
            print('  FAIL %-44s the mutation changed nothing' % label)
            fails += 1
            continue
        bp, _ = judge(t)
        print('  %-4s %-44s %s' % ('ok' if bp else 'FAIL', label, bp[:1] if bp else 'NOT CAUGHT'))
        fails += 0 if bp else 1
    print('check_cp self-test: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


def main():
    if sys.argv[1:] == ['--self-test']:
        return self_test()
    args = sys.argv[1:]
    tail = None
    if len(args) == 3 and args[1] == '--tail-submit':
        tail = int(args[2])
        args = args[:1]
    if len(args) != 1:
        sys.exit(__doc__)
    p, notes = judge(open(args[0], errors='replace').read(), tail=tail)
    for n in notes:
        print('  --   %s' % n)
    for x in p:
        print('  FAIL %s' % x)
    print('check_cp: %s' % ('PASS' if not p else 'FAIL (%d)' % len(p)))
    return 1 if p else 0


if __name__ == '__main__':
    sys.exit(main())
