#!/usr/bin/env python3
"""Judge the two R5d boots (docs/R5D_PLAN.md 7).

  check_r5d.py <log A> <log B> --boot-a N --boot-b N --build-a X --build-b Y
  check_r5d.py --self-test

Boot A: the R5 head, a healthy SUBMIT, INJECT (a latch after a clean read-back),
a RECORD with the CSQ still on, every refusal, the latched STOP (wr=1 rd=1),
two RECORDs with the GART left on, then a warm reboot.  Boot B: the inject key
off, a first RECORD whose driver-only registers are back at their boot values,
INJECT refused for its key, then the whole R5 procedure (tools/r5/check_cp.py).

Every boot is picked by its nonce, never by position: the lines are cut at the
boot's own select line and the next select line.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_cp as cc  # noqa: E402

A_HEAD = ['record', 'load', 'map', 'record', 'reset', 'record', 'start', 'submit', 'inject']
A_REFUSALS = ['inject', 'load', 'map', 'reset', 'start', 'submit']   # after the latch, in any order
A_TAIL = ['stop', 'record', 'record']
# between INJECT and STOP: the one RECORD with the CSQ still on and the six refusals, in any
# order (boot eae3072b ran the INJECT refusal first, by an operator slip -- docs/R5D_PLAN.md 9)
OPNUM = {'record': 1, 'load': 2, 'map': 3, 'reset': 4, 'start': 5, 'submit': 6, 'negctl': 7, 'stop': 8, 'inject': 9}
WHY_KEY, WHY_LATCHED, WHY_INJECTED = 1, 3, 22
RC_RAN, RC_REFUSED, RC_LATCHED = 0, 1, 3
CSQ_ON = 0x40000000
AGP_OFF = 0xffffffc0
AGP_BOOT = 0x27ff2000                     # R1, and every boot since
MODE_WHY_CP = 15
ENG_RC_CP = 6


def cut(text, nonce):
    """the lines of one boot: from the first line naming its nonce to the first
    later line naming another (the block and keys lines come BEFORE the select
    line on the machine -- boot fdca7cd1's log, lines 17-18)"""
    lines = text.splitlines()
    sel = [k for k, l in enumerate(lines) if re.search(r'RDN-R3 select boot=%s ' % re.escape(nonce), l)]
    if len(sel) != 1:
        return None, lines
    mine = [k for k, l in enumerate(lines) if 'boot=%s' % nonce in l]
    s = mine[0]
    other = [k for k, l in enumerate(lines) if k > s and re.search(r'boot=(?!%s)[0-9a-f]{8}\b' % re.escape(nonce), l)]
    e = other[0] if other else len(lines)
    return '\n'.join(lines[s:e]) + '\n', lines[e:]


def begins(text, nonce):
    return [int(m.group(1)) for m in re.finditer(r'RDN-R5 begin boot=%s op=(\d+) ' % re.escape(nonce), text)]


def keys(text, nonce):
    m = re.findall(r'RDN-R5 keys boot=%s test=(\d) inject=(\d)(?: 3d=\d)? build=([0-9a-f]{8})' % re.escape(nonce), text)
    return m


def after_inject(text, nonce):
    """the lines after this boot's INJECT result line: the refusals must come after the latch"""
    lines = text.splitlines()
    k = [i for i, l in enumerate(lines) if re.search(r'RDN-R5 inject boot=%s n=\d+ ' % re.escape(nonce), l)]
    return lines[k[0] + 1:] if k else []


def cycle_refused(lines, nonce):
    idx = [k for k, l in enumerate(lines) if re.search(r'RDN-R2B cycled boot=%s live=' % re.escape(nonce), l)]
    got = []
    for k in idx:
        live = int(re.search(r'live=(\d+)', lines[k]).group(1))
        for l in lines[k + 1:k + 6]:
            m = re.search(r'RDN-R2B cycle n=(\d+) why=(-?\d+) ', l)
            if m:
                got.append((live, int(m.group(1)), int(m.group(2))))
                break
    return got


def engine_rc(lines, nonce):
    """any engine result line: a refused call keeps the op name of the last one
    that ran (osrdn_mode.m engine wrapper), so only rc is judged"""
    return [int(m.group(1)) for l in lines
            for m in [re.search(r'RDN-R4 \w+ boot=%s n=\d+ arg=[0-9a-f]{8} rc=(-?\d+)' % re.escape(nonce), l)] if m]


def judge_a(text, nonce, build, notes):
    p = []
    sl, after = cut(text, nonce)
    if sl is None:
        return ['boot A %s: not exactly one select line' % nonce], None
    k = keys(sl, nonce)
    if k != [('1', '1', build)]:
        p.append('boot A: keys line %s, want test=1 inject=1 build=%s' % (k, build))
    boot, blocks, ops, _ = cc.parse(sl)
    if boot != nonce or len(blocks) != 1 or blocks[0]['why'] != 'ok':
        return p + ['boot A: block line %s' % blocks], None
    phys = blocks[0]['phys']
    names = [o['op'] for o in ops]
    mid = names[len(A_HEAD):len(names) - len(A_TAIL)]
    if names[:len(A_HEAD)] != A_HEAD or names[len(names) - len(A_TAIL):] != A_TAIL or \
            sorted(x for x in mid if x != 'record') != A_REFUSALS or mid.count('record') != 1:
        return p + ['boot A: operations %s, want %s + one record and %s in any order + %s' % (
            names, A_HEAD, A_REFUSALS, A_TAIL)], None
    rix = len(A_HEAD) + mid.index('record')
    refused = [len(A_HEAD) + k for k, x in enumerate(mid) if x != 'record']
    six = len(names) - len(A_TAIL)
    if begins(sl, nonce) != [OPNUM[n] for n in names]:
        p.append('boot A: begin lines %s do not match the operations' % begins(sl, nonce))
    for i in range(8):
        if ops[i]['rc'] != RC_RAN or ops[i].get('latched'):
            p.append('boot A op %d %s: rc %d why %d' % (i, names[i], ops[i]['rc'], ops[i]['why']))
    for i in (2, 4, 6):                    # MAP, RESET, START: the gate's own read-backs
        if ops[i].get('mgbad', -1) != 0 or ops[i]['mg'].get('hi') not in cc.HI_OK:
            p.append('boot A %s: MAP gate mask %s hi %s' % (names[i], ops[i].get('mgbad'), ops[i]['mg'].get('hi')))
    sb = ops[7]
    if sb.get('m') != [cc.marker(sb['arg'], j) for j in range(3)] or sb.get('g') != sb.get('m'):
        p.append('boot A submit: markers %s read back %s' % (sb.get('m'), sb.get('g')))
    ij = ops[8]
    want = [cc.marker(ij['arg'], j) for j in range(3)]
    if ij['rc'] != RC_LATCHED or ij['why'] != WHY_INJECTED or ij.get('latched') != 1 or ij.get('injected') != 1 or \
            ij.get('inject') != 1 or ij.get('failed') or ij.get('state') != 3:
        p.append('inject: rc %d why %d latched %s injected %s count %s state %s' % (
            ij['rc'], ij['why'], ij.get('latched'), ij.get('injected'), ij.get('inject'), ij.get('state')))
    if ij.get('m') != want or ij.get('g') != want or ij.get('reg5') != cc.POISON:
        p.append('inject: markers %s read back %s reg5 %s, want %s' % (ij.get('m'), ij.get('g'), ij.get('reg5'), want))
    lim = ij.get('limits', [1, 1, 1, 1, 1])
    if lim[1] or lim[2]:
        p.append('inject: a wait ran out (%s) -- a real latch, not the injected one' % lim)
    if ij.get('bad') and any(ij['bad']):
        p.append('inject: block words changed %s' % ij['bad'])
    r1 = ops[rix]
    if r1['rc'] != RC_RAN or [r1['rec'].get('s%d' % j) for j in range(3)] != want:
        p.append('record after inject: rc %d s0-2 %s' % (r1['rc'], [r1['rec'].get('s%d' % j) for j in range(3)]))
    # whether CSQ_CNTL reads its mode bits back while on was never measured: a record
    notes.append('record after inject: CSQ_CNTL %08x (mode bits %x; 4 = on as written)' % (
        r1['rec'].get('csq', 0), r1['rec'].get('csq', 0) >> 28))
    for i in refused:
        o = ops[i]
        if o['rc'] != RC_REFUSED or o['why'] != WHY_LATCHED or o.get('wr') != 0 or o.get('rd') != 0:
            p.append('%s after the latch: rc %d why %d wr %s rd %s' % (o['op'], o['rc'], o['why'], o.get('wr'), o.get('rd')))
    sp = ops[six]
    if sp['rc'] != RC_LATCHED or sp.get('wr') != 1 or sp.get('rd') != 1:
        p.append('latched stop: rc %d wr %s rd %s, want 3 1 1' % (sp['rc'], sp.get('wr'), sp.get('rd')))
    recs = [ops[six + 1]['rec'], ops[six + 2]['rec']]
    for n, r in enumerate(recs):
        o = ops[six + 1 + n]
        if o['rc'] != RC_RAN or r.get('aic') != 3 or r.get('ptbase') != phys or r.get('lo') != 0x20000000 or \
                r.get('hi') not in cc.HI_OK or r.get('agploc') != AGP_OFF or (r.get('csq', 1) & 0xf0000000) or \
                [r.get('s%d' % j) for j in range(3)] != want or r.get('s5') != cc.POISON:
            p.append('record %d after the latched stop: %s' % (n + 1, dict((x, '%08x' % r.get(x, 0)) for x in
                                                                       ('aic', 'ptbase', 'lo', 'hi', 'agploc', 'csq', 's0', 's5'))))
        if o.get('bad') and any(o['bad']):
            p.append('record %d after the latched stop: block words changed %s' % (n + 1, o['bad']))
    skip = {'rbbm', 'intstat', 'aicstat'}     # aicstat: the open question (docs/R5_PLAN.md 13), a record
    diff = sorted(x for x in set(recs[0]) | set(recs[1]) if x not in skip and recs[0].get(x) != recs[1].get(x))
    if diff:
        p.append('the two records after the latched stop differ in %s' % diff)
    ai = after_inject(sl, nonce)
    if cycle_refused(sl.splitlines(), nonce) != [(0, 0, MODE_WHY_CP)] or cycle_refused(ai, nonce) != [(0, 0, MODE_WHY_CP)]:
        p.append('cycle: %s in the boot, want one refusal (live=0 n=0 why=%d) after INJECT' % (
            cycle_refused(sl.splitlines(), nonce), MODE_WHY_CP))
    if engine_rc(sl.splitlines(), nonce) != [ENG_RC_CP] or engine_rc(ai, nonce) != [ENG_RC_CP]:
        p.append('engine: rc %s in the boot, want one refusal rc=%d after INJECT' % (
            engine_rc(sl.splitlines(), nonce), ENG_RC_CP))
    if not any(re.search(r'reboot: rebooted by', l) for l in ai):
        p.append('no "rebooted by" line after the INJECT (a warm reboot is the procedure)')
    return p, want


def judge_b(text, nonce, build, markers):
    p = []
    sl, _ = cut(text, nonce)
    if sl is None:
        return ['boot B %s: not exactly one select line' % nonce]
    k = keys(sl, nonce)
    if k != [('1', '0', build)]:
        p.append('boot B: keys line %s, want test=1 inject=0 build=%s' % (k, build))
    boot, blocks, ops, _ = cc.parse(sl)
    if len(ops) < 2 or ops[0]['op'] != 'record' or ops[1]['op'] != 'inject':
        return p + ['boot B: the first two operations are %s, want record, inject' % [o['op'] for o in ops[:2]]]
    r = ops[0]['rec']
    want = dict(aic=0, lo=0, hi=0, ptbase=0, agploc=AGP_BOOT, rbcntl=0, rptraddr=0, isync=0)
    wrong = ['%s=%08x' % (x, r.get(x, 0)) for x, v in want.items() if r.get(x) != v]
    if r.get('s5') == cc.POISON:
        wrong.append('s5 is the poison')
    if r.get('rbbase') == 0x20000000:
        wrong.append('rbbase is the ring')
    if markers and [r.get('s%d' % j) for j in range(3)] == markers:
        wrong.append('s0-2 are boot A\'s markers')
    if wrong:
        p.append('boot B first record: not reset -- %s' % ' '.join(wrong))
    ij = ops[1]
    if ij['rc'] != RC_REFUSED or ij['why'] != WHY_KEY or ij.get('wr') != 0:
        p.append('boot B inject: rc %d why %d wr %s, want refused for the key' % (ij['rc'], ij['why'], ij.get('wr')))
    q, _ = cc.judge(sl, skip_key_refusals=True)
    p.extend('boot B (R5): %s' % x for x in q)
    return p


def judge(ta, tb, na, nb, ba, bb, notes=None):
    if notes is None:
        notes = []
    if na == nb:
        return ['boot A and boot B are the same boot %s' % na]
    pa, markers = judge_a(ta, na, ba, notes)
    return pa + judge_b(tb, nb, bb, markers)


# ---- self-test: synthetic boots from the driver's own formats ----------------------------
def synth_a(nonce='aaaa0001', build='11111111', phys=0x00040000):
    # the machine's order: keys and block lines, then the select line
    L = ['mach: RDN-R5 keys boot=%s test=1 inject=1 3d=0 build=%s' % (nonce, build),
         'mach: RDN-R5 block boot=%s va=00040000 phys=%08x len=00010000 ok' % (nonce, phys),
         'mach: RDN-R3 select boot=%s res=800x600 fmt=RGB:888/32 rdflt=0' % nonce]
    s, x = cc.table_sums(phys)
    n = [0]

    def op(name, rc=0, why=0, state=2, latched=0, injected=0, inject=0, wr=3, rd=40, rec=None, extra=(),
           arg=0, ln=0, limits=(0, 0, 0, 0, 0), reg5=cc.POISON, csq='02000000'):
        n[0] += 1
        L.append('mach: RDN-R5 begin boot=%s op=%d arg=%08x len=%d' % (nonce, OPNUM[name], arg, ln))
        L.append('mach: RDN-R5 %s boot=%s n=%d arg=%08x len=%d rc=%d why=%d gv=00000000 greg=0000 us=100'
                 % (name, nonce, n[0], arg, ln, rc, why))
        L.append('mach: RDN-R5 state state=%d latched=%d reset=1 failed=0 wptr=0 phys=%08x post=00000000 '
                 'csqstat=%s csq2stat=04010080 csqread=1 nowb=0 spin=0 time=0' % (state, latched, phys, csq))
        L.append('mach: RDN-R5 io wr=%d rd=%d aicstat=00000004 inject=%d injected=%d' % (wr, rd, inject, injected))
        if rec:
            names = list(rec)
            for k in range(0, len(names), 6):
                L.append('mach: RDN-R5 rec%d ' % (k // 6) + ' '.join('%s=%08x' % (y, rec[y]) for y in names[k:k + 6]))
        L.extend(extra)
        L.append('mach: RDN-R5 ptrs rbefore=0 rafter=0 wafter=0 reg5=%08x roff=00000000 woff=00000000' % reg5)
        L.append('mach: RDN-R5 block table=0 guard=0 spare=0 canary=0 ring=0 sum=%08x xor=%08x' % (s, x))
        L.append('mach: RDN-R5 wait fifo=1/%d idle=1/%d/10 rptr=1/%d/10 idle2=1/%d dc=0/%d' % limits)

    seed = 0x12345678
    m = [cc.marker(seed, k) for k in range(3)]
    base = dict(csq=0x02010080, aic=0, intcntl=0, agploc=AGP_BOOT, mcfb=cc.R1_FB, ptbase=0, lo=0, hi=0, s5=0xcdcdcdcd)
    mgl = ['mach: RDN-R5 mapgate bad=0000',
           'mach: RDN-R5 mg0 rbcntl=0804090b umsk=00000000 ptbase=%08x lo=20000000 hi=207ff000' % phys,
           'mach: RDN-R5 mg1 aic=00000003 rbbase=20000000 rptraddr=20004000 rptr=00000000 wptr=00000000',
           'mach: RDN-R5 mg2 intcntl=00000000 agploc=ffffffc0 s5=5a5a0005 agpcmd=00000200 aicstat=00000004']
    s1 = 0x0badf00d
    m1 = [cc.marker(s1, k) for k in range(3)]
    for nm in ('record', 'load', 'map', 'record', 'reset', 'record', 'start'):
        op(nm, rec=base if nm == 'record' else None, extra=mgl if nm in ('map', 'reset', 'start') else ())
    op('submit', arg=s1, ln=1024, state=3,
       extra=['mach: RDN-R5 marks m0=%08x m1=%08x m2=%08x s0=%08x s1=%08x s2=%08x' % tuple(m1 + [(~v) & cc.M32 for v in m1]),
              'mach: RDN-R5 got g0=%08x g1=%08x g2=%08x straddle=1 boundary=1024' % tuple(m1)])
    op('inject', rc=3, why=22, state=3, latched=1, injected=1, inject=1, arg=seed, ln=1024,
       extra=['mach: RDN-R5 marks m0=%08x m1=%08x m2=%08x s0=%08x s1=%08x s2=%08x' % tuple(m + [(~v) & cc.M32 for v in m]),
              'mach: RDN-R5 got g0=%08x g1=%08x g2=%08x straddle=0 boundary=0' % tuple(m)])
    live = dict(csq=0x02010080 | CSQ_ON, aic=3, ptbase=phys, lo=0x20000000, hi=0x207ff000, agploc=AGP_OFF,
                s0=m[0], s1=m[1], s2=m[2], s5=cc.POISON)
    op('record', state=3, latched=1, injected=1, inject=1, rec=live)
    for nm in ('submit', 'map', 'reset', 'start', 'load', 'inject'):
        op(nm, rc=1, why=3, state=3, latched=1, injected=1, inject=1, wr=0, rd=0)
    op('stop', rc=3, state=3, latched=1, injected=1, inject=1, wr=1, rd=1)
    dead = dict(live, csq=0x02010080)
    op('record', state=3, latched=1, injected=1, inject=1, rec=dead)
    op('record', state=3, latched=1, injected=1, inject=1, rec=dict(dead))
    L.append('mach: RDN-R2B cycled boot=%s live=0' % nonce)
    L.append('mach: RDN-R2B cycle n=0 why=15 checked=0 cwhy=0 bad=0 vga=0 palette=0 kernel=0 verdict=0')
    L.append('mach: RDN-R4 bad boot=%s n=0 arg=00000000 rc=6 why=0 gv=00000000 us=0 latched=0 win=00000000' % nonce)
    L.append('reboot: rebooted by root')
    return '\n'.join(L) + '\n'


def synth_b(nonce='bbbb0002', build='22222222'):
    g = cc.good_log(phys=0x00040000).replace('aaaa0001', nonce).replace('inject=0 3d=0 build=65b66543', 'inject=0 3d=0 build=%s' % build)
    lines = g.splitlines()
    # INJECT refused for its key, right after the first RECORD's lines
    first = [k for k, l in enumerate(lines) if 'RDN-R5 load boot=' in l][0]
    ins = ['mach: RDN-R5 inject boot=%s n=99 arg=00000001 len=1024 rc=1 why=1 gv=00000009 greg=0000 us=1' % nonce,
           'mach: RDN-R5 state state=0 latched=0 reset=0 failed=0 wptr=0 phys=00040000 post=00000000 csqstat=02000603 '
           'csq2stat=04010080 csqread=1 nowb=0 spin=0 time=0',
           'mach: RDN-R5 io wr=0 rd=6 aicstat=00000004 inject=0 injected=0']
    lines[first:first] = ins
    return '\n'.join(lines) + '\n'


def self_test():
    fails = 0
    a, b = synth_a(), synth_b()
    p = judge(a, b, 'aaaa0001', 'bbbb0002', '11111111', '22222222')
    print('  %-4s the clean pair passes%s' % ('FAIL' if p else 'ok', '' if not p else ': %s' % p[:4]))
    fails += 1 if p else 0
    BAD = [
        ('A: the latch was a real timeout', 'a', lambda t: t.replace('rptr=1/0/10', 'rptr=1/1/10', 9)),
        ('A: INJECT did not latch', 'a', lambda t: t.replace('rc=3 why=22', 'rc=0 why=0', 1)),
        ('A: a submit accepted after the latch', 'a', lambda t: re.sub(r'(RDN-R5 submit boot=\w+ n=11 \S+ \S+) rc=1 why=3',
                                                                        r'\1 rc=0 why=0', t)),
        ('A: a refusal touched the card', 'a', lambda t: re.sub(r'(RDN-R5 map boot=\w+ n=12 [^\n]*\n[^\n]*\n)mach: RDN-R5 io wr=0',
                                                                 r'\1mach: RDN-R5 io wr=1', t)),
        ('A: the latched stop turned the GART off', 'a', lambda t: t.replace('aic=00000003 ptbase', 'aic=00000002 ptbase', 3)),
        ('A: the latched stop wrote twice', 'a', lambda t: t.replace('io wr=1 rd=1', 'io wr=2 rd=1')),
        ('A: a late write between the two records', 'a', lambda t: t[:t.rindex('spare=0')] + 'spare=1' + t[t.rindex('spare=0') + 7:]),
        ('A: the cycle ran', 'a', lambda t: t.replace('cycled boot=aaaa0001 live=0', 'cycled boot=aaaa0001 live=1')),
        ('A: the engine ran', 'a', lambda t: t.replace('rc=6 why=0', 'rc=0 why=0')),
        ('A: the inject key was off', 'a', lambda t: t.replace('test=1 inject=1', 'test=1 inject=0')),
        ('A: another build', 'a', lambda t: t.replace('build=11111111', 'build=33333333')),
        ('A: no warm reboot line', 'a', lambda t: t.replace('reboot: rebooted by root', '')),
        ('A: a begin line missing', 'a', lambda t: t.replace('RDN-R5 begin boot=aaaa0001 op=9 ', 'RDN-R5 bogus boot=aaaa0001 op=9 ', 1)),
        ('A: the injected markers not read back', 'a', lambda t: t.replace('got g0=%08x' % cc.marker(0x12345678, 0), 'got g0=00000000', 1)),
        ('B: the card kept our AGP value', 'b', lambda t: t.replace('agploc=%08x' % AGP_BOOT, 'agploc=ffffffc0', 1)),
        ('B: translation still on', 'b', lambda t: t.replace('aic=00000000', 'aic=00000003', 1)),
        ('B: INJECT ran', 'b', lambda t: t.replace('rc=1 why=1 gv=00000009', 'rc=3 why=22 gv=00000009')),
        ('B: the inject key still on', 'b', lambda t: t.replace('test=1 inject=0', 'test=1 inject=1')),
        ('B: the R5 procedure failed', 'b', lambda t: t.replace('palette=0 kernel=0 verdict=0', 'palette=2 kernel=0 verdict=1')),
        ('A: the cycle refused BEFORE the inject', 'a', lambda t: (lambda c: t.replace(c, '').replace(
        'mach: RDN-R5 begin boot=aaaa0001 op=9 ', c + 'mach: RDN-R5 begin boot=aaaa0001 op=9 ', 1))(
        'mach: RDN-R2B cycled boot=aaaa0001 live=0\nmach: RDN-R2B cycle n=0 why=15 checked=0 cwhy=0 bad=0 vga=0 palette=0 kernel=0 verdict=0\n')),
    ('A: the engine refused BEFORE the inject', 'a', lambda t: (lambda c: t.replace(c, '').replace(
        'mach: RDN-R5 begin boot=aaaa0001 op=9 ', c + 'mach: RDN-R5 begin boot=aaaa0001 op=9 ', 1))(
        'mach: RDN-R4 bad boot=aaaa0001 n=0 arg=00000000 rc=6 why=0 gv=00000000 us=0 latched=0 win=00000000\n')),
    ('A: the MAP gate saw a mismatch', 'a', lambda t: t.replace('mapgate bad=0000', 'mapgate bad=0010', 1)),
    ('A: the healthy submit read back wrong', 'a', lambda t: t.replace('straddle=1 boundary=1024', 'straddle=1 boundary=1024', 1)
     .replace('got g0=%08x' % cc.marker(0x0badf00d, 0), 'got g0=00000000', 1)),
    ('A: a refusal missing', 'a', lambda t: re.sub(r'mach: RDN-R5 begin boot=aaaa0001 op=4 [^\n]*\nmach: RDN-R5 reset boot=aaaa0001 n=13 [^\n]*\n'
                                                r'(?:mach: RDN-R5 (?:state|io|ptrs|block|wait)[^\n]*\n)+', '', t)),
    ('A: a refusal run twice', 'a', lambda t: t.replace('RDN-R5 begin boot=aaaa0001 op=3 arg=00000000 len=0\nmach: RDN-R5 map boot=aaaa0001 n=12',
                                                     'RDN-R5 begin boot=aaaa0001 op=5 arg=00000000 len=0\nmach: RDN-R5 start boot=aaaa0001 n=12')),
    ('A: the block line is another boot\'s', 'a', lambda t: t.replace('RDN-R5 block boot=aaaa0001', 'RDN-R5 block boot=cccc0003')),
    ('same boot twice', 'n', None),
    ]
    # the machine's order (eae3072b): the INJECT refusal right after the INJECT -- must PASS
    blk = re.search(r'(mach: RDN-R5 begin boot=aaaa0001 op=9 [^\n]*\nmach: RDN-R5 inject boot=aaaa0001 n=16 [^\n]*\n'
                    r'(?:mach: RDN-R5 (?:state|io|ptrs|block|wait)[^\n]*\n)+)', a).group(1)
    first_rec = a.index('mach: RDN-R5 begin boot=aaaa0001 op=1 ', a.index('RDN-R5 inject boot=aaaa0001 n=9 '))
    moved = a.replace(blk, '')
    moved = moved[:first_rec] + blk + moved[first_rec:]
    q = judge(moved, b, 'aaaa0001', 'bbbb0002', '11111111', '22222222')
    print('  %-4s the refusals in another order pass%s' % ('FAIL' if q else 'ok', '' if not q else ': %s' % q[:3]))
    fails += 1 if q else 0
    for label, which, f in BAD:
        if which == 'n':
            q = judge(a, b, 'aaaa0001', 'aaaa0001', '11111111', '22222222')
        else:
            ta, tb = (f(a), b) if which == 'a' else (a, f(b))
            if (ta, tb) == (a, b):
                print('  FAIL %-44s the mutation changed nothing' % label)
                fails += 1
                continue
            q = judge(ta, tb, 'aaaa0001', 'bbbb0002', '11111111', '22222222')
        print('  %-4s %-44s %s' % ('ok' if q else 'FAIL', label, q[:1] if q else 'NOT CAUGHT'))
        fails += 0 if q else 1
    print('check_r5d self-test: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


def main():
    if sys.argv[1:] == ['--self-test']:
        return self_test()
    args = sys.argv[1:]
    try:
        la, lb = args[0], args[1]
        opt = dict(zip(args[2::2], args[3::2]))
        na, nb, ba, bb = opt['--boot-a'], opt['--boot-b'], opt['--build-a'], opt['--build-b']
    except (IndexError, KeyError):
        sys.exit(__doc__)
    notes = []
    p = judge(open(la, errors='replace').read(), open(lb, errors='replace').read(), na, nb, ba, bb, notes)
    for n in notes:
        print('  --   %s' % n)
    for x in p:
        print('  FAIL %s' % x)
    print('check_r5d: %s' % ('PASS' if not p else 'FAIL (%d)' % len(p)))
    return 1 if p else 0


if __name__ == '__main__':
    sys.exit(main())
