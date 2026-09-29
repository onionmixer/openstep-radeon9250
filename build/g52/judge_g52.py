#!/usr/bin/env python3
"""G5-2 judge (docs/G5_2_ASYNC_SUBMIT_PLAN.md 6).

  judge_g52.py off <dir>     G1-G3 from run_g52_off.sh
  judge_g52.py on  <dir>     G4-G6 from run_g52_on.sh (the GLQuake logs)
  judge_g52.py --self-test
"""
import os, re, sys

FILL = 0x00204060
W, H = 640, 480


def async_line(t):
    m = re.findall(r'RDN-R5 async boot=\w+ (.*)', t)
    return dict((k, int(v)) for k, v in re.findall(r'(\w+)=(-?\d+)', m[-1])) if m else None


def judge_off(d):
    p, notes = [], []
    rd = lambda n: open(os.path.join(d, n), 'rb').read() if os.path.exists(os.path.join(d, n)) else None
    sc, ac, sd, ad = rd('sync-colour.raw'), rd('async-colour.raw'), rd('sync-depth.raw'), rd('async-depth.raw')
    if None in (sc, ac, sd, ad) or len(sc) != W * H * 4 or len(ac) != W * H * 4:
        return ['G1/G2: the dumps are missing or the wrong size'], notes
    fill = FILL.to_bytes(4, 'little')
    drawn = sum(1 for i in range(0, len(sc), 4) if sc[i:i + 4] != fill)
    diff = sum(1 for i in range(0, len(sc), 4) if sc[i:i + 4] != ac[i:i + 4])
    ddiff = sum(1 for i in range(0, len(sd), 2) if sd[i:i + 2] != ad[i:i + 2])
    notes.append('G1: %d of %d colour pixels drawn over the fill' % (drawn, W * H))
    if drawn == 0:
        p.append('G1: the synchronous replay drew nothing over the fill')
    if diff or ddiff:
        p.append('G2: the accepted replay differs from the synchronous one: colour %d, depth %d pixels' % (diff, ddiff))
    else:
        notes.append('G2: colour and depth byte-identical to G1')
    for arm in ('sync', 'async'):
        t = open(os.path.join(d, 'off-%s.log' % arm)).read() if os.path.exists(os.path.join(d, 'off-%s.log' % arm)) else ''
        if 'step=done' not in t or 'RDNDUMP filled' not in t:
            p.append('%s: the replay or the fill did not finish' % arm)
    g3 = open(os.path.join(d, 'off-g3.log')).read() if os.path.exists(os.path.join(d, 'off-g3.log')) else ''
    m = re.search(r'step=retire rc=(-?\d+) status=(\d+) waited=(\d+) us=(\d+) asubmits=(\d+) lost=(\d+)', g3)
    if 'reps=20' not in g3 or not m:
        p.append('G3: the 20 accepted replays or their RETIRE did not finish')
    else:
        rc, st, waited, us, asub, lost = map(int, m.groups())
        notes.append('G3: RETIRE waited=%d us=%d asubmits=%d lost=%d' % (waited, us, asub, lost))
        if rc or st or lost:
            p.append('G3: RETIRE rc=%d status=%d lost=%d' % (rc, st, lost))
    b = async_line(open(os.path.join(d, 'off-before.txt')).read()) if os.path.exists(os.path.join(d, 'off-before.txt')) else None
    a_txt = open(os.path.join(d, 'off-after.txt')).read() if os.path.exists(os.path.join(d, 'off-after.txt')) else ''
    a = async_line(a_txt)
    if not a:
        p.append('G3: no RDN-R5 async line after the run')
    else:
        base = b['asubmits'] if b else 0
        if a['asubmits'] - base != 21:
            p.append('G3: asubmits moved by %d, want 21 (1 in G2 + 20 in G3)' % (a['asubmits'] - base))
        if a['lost'] or a['markbad']:
            p.append('G3: lost=%d markbad=%d' % (a['lost'], a['markbad']))
        notes.append('G3: kernel space waits %d (%d us), retires %d waited %d (%d us), kick skipped %d'
                     % (a['space'], a['spaceus'], a['retires'], a['waited'], a['retireus'], a['kickskip']))
    lt = re.findall(r'^\s*(\d+)\s*$', a_txt, re.M)
    if lt and int(lt[-1]) != 0:
        p.append('G3: %s latch line(s) in the kernel log during this run' % lt[-1])
    return p, notes


def rdn(t, tag):
    m = re.findall(r'%s (.*)' % tag, t)
    return dict((k, int(v)) for k, v in re.findall(r'(\w+)=(-?\d+)', m[-1])) if m else None


def judge_on(d):
    p, notes = [], []
    for name, want_async in (('g52-sync', 0), ('g52-r1', 1), ('g52-r2', 1)):
        f = os.path.join(d, name + '.log')
        if not os.path.exists(f):
            p.append('%s: no log' % name)
            continue
        t = open(f).read()
        c, a = rdn(t, 'RDN-C'), rdn(t, 'RDN-A')
        if not c or not a:
            p.append('%s: RDN-C or RDN-A missing' % name)
            continue
        notes.append('%s: RDN-A %s' % (name, ' '.join('%s=%d' % kv for kv in a.items())))
        if a['async'] != want_async:
            p.append('%s: async=%d, want %d' % (name, a['async'], want_async))
        for k in ('failed', 'latelatch', 'lost'):
            if a.get(k):
                p.append('%s: %s=%d' % (name, k, a[k]))
        for k in ('delegated', 'replayed', 'nosoftware'):
            if c.get(k):
                p.append('%s: RDN-C %s=%d' % (name, k, c[k]))
    # G5-4 8d (docs/G5_4_READPIX_AND_CLEANUP_PLAN.md 2-4): the first card clear after GLQuake.  The kernel
    # prints a clear line once per verdict a boot, so a line with a non-OK verdict here is the event
    f = os.path.join(d, 'on-clear.txt')
    if os.path.exists(f):
        t = open(f).read()
        badc = re.findall(r'RDN-G3 clear boot=\w+ rc=(-?\d+) verdict=(\d+)', t)
        worse = [(rc, v) for rc, v in badc if rc != '0' or v != '0']
        if worse or 'RDN-R5 latch' in t:
            p.append('G8: the first clear after GLQuake: %s%s' % (worse, ' and a latch' if 'RDN-R5 latch' in t else ''))
        else:
            notes.append('G8: no failed clear after GLQuake (%d clear line(s) this window)' % len(badc))
    else:
        notes.append('G8: on-clear.txt missing -- the clear after GLQuake was not tried')
    # G5-3 (docs/G5_3_QUERY_CONSOLE_PLAN.md 3): in the world part, is the window-server query under the
    # card's tail?  With accepted submissions the present ioctl waits for what the card still draws AFTER
    # the query; if it is longer than the synchronous run's (where the card is idle at present), the card
    # was still drawing when the query ended -- the query cost nothing.
    w = {}
    for name in ('g52-sync', 'g52-r1'):
        f = os.path.join(d, name + '.log')
        if os.path.exists(f):
            w[name] = world_sites(open(f).read())
    if len(w) == 2 and None not in w.values():
        (ps, qs), (pa, qa) = w['g52-sync'], w['g52-r1']
        notes.append('G5-3 query: world present ioctl %.2f ms/frame synchronous, %.2f accepted; query %.2f / %.2f -> '
                     'the card drew %.2f ms/frame past the query%s'
                     % (ps, pa, qs, qa, pa - ps, ' (the query is hidden)' if pa - ps >= 0.1 else ' (the query is NOT hidden: plan 3, the every-other-frame option)'))
    return p, notes


def world_sites(t):
    """(present, query) ms/frame over the world part: final RDN-T minus the RDN-TS split"""
    def block(pfx):
        wall = re.search(r'^%s wall us=(\d+) cyc=([0-9a-f]{16}) gtod1000cyc=\d+ frames_present=(\d+)' % pfx, t, re.M)
        if not wall:
            return None
        s = {}
        for m in re.finditer(r'^%s site=(\w+) tag=\w+ n=\d+ cyc=([0-9a-f]{16})' % pfx, t, re.M):
            s[m.group(1)] = s.get(m.group(1), 0) + int(m.group(2), 16)
        return int(wall.group(1)), int(wall.group(2), 16), int(wall.group(3)), s
    a, b = block('RDN-T'), block('RDN-TS')
    if not a or not b or a[2] <= b[2] or not a[0]:
        return None
    cpu = a[1] / a[0]
    fr = a[2] - b[2]
    f = lambda k: (a[3].get(k, 0) - b[3].get(k, 0)) / cpu / 1000.0 / fr
    return f('present'), f('query')


def self_test():
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as d:
        fill = FILL.to_bytes(4, 'little')
        pic = bytearray(fill * (W * H)); pic[0:4] = b'\x01\x02\x03\x00'
        dep = bytes(W * H * 2)
        for n, b in (('sync-colour.raw', pic), ('async-colour.raw', pic), ('sync-depth.raw', dep), ('async-depth.raw', dep)):
            open(os.path.join(d, n), 'wb').write(b)
        for arm in ('sync', 'async'):
            open(os.path.join(d, 'off-%s.log' % arm), 'w').write('RDNDUMP filled x\nRDNREPLAY run=1 step=done reps=1\n')
        open(os.path.join(d, 'off-g3.log'), 'w').write('RDNREPLAY run=2 step=done reps=20 words=4057\nRDNREPLAY run=2 step=retire rc=0 status=0 waited=1 us=900 asubmits=21 lost=0 cprc=0\n')
        open(os.path.join(d, 'off-before.txt'), 'w').write('RDN-R5 async boot=1 asubmits=0 inflight=0 retires=0 waited=0 retireus=0 last=0 markbad=0 lost=0 space=0 spaceus=0 sres=0 kickskip=0\n')
        open(os.path.join(d, 'off-after.txt'), 'w').write('RDN-R5 async boot=1 asubmits=21 inflight=0 retires=1 waited=1 retireus=900 last=900 markbad=0 lost=0 space=19 spaceus=20000 sres=5 kickskip=0\n0\n')
        good, _ = judge_off(d)
        print('  %s the good sample passes %s' % ('ok  ' if not good else 'FAIL', good)); ok &= not good
        for label, fn, bad in (('the async picture differs', 'async-colour.raw', bytes(pic[:4]) and bytes(b'\x09' * 4) + bytes(pic[4:])),
                               ('nothing drawn', 'sync-colour.raw', fill * (W * H))):
            keep = open(os.path.join(d, fn), 'rb').read()
            open(os.path.join(d, fn), 'wb').write(bad)
            if fn == 'sync-colour.raw':
                open(os.path.join(d, 'async-colour.raw'), 'wb').write(bad)
            caught = bool(judge_off(d)[0])
            print('  %s mutation %-28s %s' % ('ok  ' if caught else 'FAIL', label, 'caught' if caught else 'NOT caught')); ok &= caught
            open(os.path.join(d, fn), 'wb').write(keep); open(os.path.join(d, 'async-colour.raw'), 'wb').write(pic)
        t = open(os.path.join(d, 'off-after.txt')).read()
        open(os.path.join(d, 'off-after.txt'), 'w').write(t.replace('asubmits=21', 'asubmits=20'))
        caught = bool(judge_off(d)[0]); print('  %s mutation %-28s %s' % ('ok  ' if caught else 'FAIL', 'a submission uncounted', 'caught' if caught else 'NOT caught')); ok &= caught
    # G5-3: the world part is the final totals minus the split's, per world frame
    t = ('RDN-TS wall us=1000000 cyc=%016x gtod1000cyc=1 frames_present=150 frames_clear=0\n'
         'RDN-TS site=present tag=out n=150 cyc=%016x max=0 huge=0 units=0\n'
         'RDN-TS site=query tag=out n=150 cyc=%016x max=0 huge=0 units=0\n'
         'RDN-T wall us=2000000 cyc=%016x gtod1000cyc=1 frames_present=250 frames_clear=0\n'
         'RDN-T site=present tag=out n=250 cyc=%016x max=0 huge=0 units=0\n'
         'RDN-T site=query tag=out n=250 cyc=%016x max=0 huge=0 units=0\n'
         % (2660000000, 2660 * 150000, 2660 * 75000, 5320000000, 2660 * 250000, 2660 * 125000))
    got = world_sites(t)
    good = got is not None and abs(got[0] - 1.0) < 1e-6 and abs(got[1] - 0.5) < 1e-6
    print('  %s the world part: present %s query %s ms/frame (want 1.0, 0.5)' % ('ok  ' if good else 'FAIL', got and '%.3f' % got[0], got and '%.3f' % got[1])); ok &= good
    caught = world_sites('\n'.join(l for l in t.split('\n') if not l.startswith('RDN-TS'))) is None
    print('  %s mutation %-28s %s' % ('ok  ' if caught else 'FAIL', 'no split in the log', 'caught' if caught else 'NOT caught')); ok &= caught
    print('judge_g52 self-test: %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


def main():
    if sys.argv[1:2] == ['--self-test']:
        return self_test()
    kind, d = sys.argv[1], sys.argv[2]
    p, notes = (judge_off if kind == 'off' else judge_on)(d)
    for n in notes:
        print('   ' + n)
    for x in p:
        print('  FAIL ' + x)
    print('judge_g52 %s: %s' % (kind, 'PASS' if not p else 'FAIL (%d)' % len(p)))
    return 1 if p else 0


if __name__ == '__main__':
    sys.exit(main())
