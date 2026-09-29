#!/usr/bin/env python3
"""judge_g55.py -- G5-5 (docs/G5_5_BATCH_SIZE_PLAN.md 3): the world part of each run, by batch cap.

  judge_g55.py <dir>      reads g55-r<round>-n<cap>.log/.before/.after from run_g55.sh
  judge_g55.py --self-test
"""
import os, re, sys


def block(t, pfx):
    wall = re.search(r'^%s wall us=(\d+) cyc=([0-9a-f]{16}) gtod1000cyc=\d+ frames_present=(\d+)' % pfx, t, re.M)
    if not wall:
        return None
    s, n = {}, {}
    for m in re.finditer(r'^%s site=(\w+) tag=\w+ n=(\d+) cyc=([0-9a-f]{16})' % pfx, t, re.M):
        s[m.group(1)] = s.get(m.group(1), 0) + int(m.group(3), 16)
        n[m.group(1)] = n.get(m.group(1), 0) + int(m.group(2))
    return dict(us=int(wall.group(1)), cyc=int(wall.group(2), 16), fp=int(wall.group(3)), s=s, n=n)


def world(t):
    a, b = block(t, 'RDN-T'), block(t, 'RDN-TS')
    if not a or not b or a['fp'] <= b['fp'] or not a['us']:
        return None
    cpu = a['cyc'] / a['us']
    fr = a['fp'] - b['fp']
    ms = lambda k: (a['s'].get(k, 0) - b['s'].get(k, 0)) / cpu / 1000.0 / fr
    return dict(frame=(a['us'] - b['us']) / 1000.0 / fr, submit=ms('submit'), present=ms('present'),
                subs=(a['n'].get('submit', 0) - b['n'].get('submit', 0)) / fr)


def kernel(before, after):
    k = lambda t: dict((x, int(v)) for x, v in re.findall(r'(\w+)=(\d+)', t.split('RDN-R5 async', 1)[1])) if 'RDN-R5 async' in t else None
    a, b = k(before), k(after)
    if not a or not b:
        return None
    return dict(asub=b['asubmits'] - a['asubmits'], space=b['space'] - a['space'], spaceus=b['spaceus'] - a['spaceus'],
                lost=b['lost'] - a['lost'])


def main(d):
    rows, bad = {}, []
    for f in sorted(os.listdir(d)):
        m = re.match(r'g55-r(\d)-n(\d+)\.log$', f)
        if not m:
            continue
        t = open(os.path.join(d, f)).read()
        w = world(t)
        base = os.path.join(d, f[:-4])
        kd = kernel(open(base + '.before').read(), open(base + '.after').read()) if os.path.exists(base + '.after') else None
        a = re.search(r'^RDN-A .*', t, re.M)
        if w is None:
            bad.append('%s: no split budget' % f); continue
        cap = int(m.group(2))
        if a and cap and ('batchwords=%d ' % cap) not in a.group(0) + ' ':
            bad.append('%s: the knob is not in force (%s)' % (f, a.group(0)))
        if kd and kd['lost']:
            bad.append('%s: %d lost' % (f, kd['lost']))
        rows.setdefault(cap, []).append((int(m.group(1)), w, kd))
    for cap in sorted(rows):
        for rnd, w, kd in sorted(rows[cap], key=lambda x: x[0]):
            print('  cap %-5s round %d: world %.2f ms/frame, submit %.2f, present %.2f, %.1f submissions/frame%s'
                  % (cap or 'drv', rnd, w['frame'], w['submit'], w['present'], w['subs'],
                     '' if not kd else ', kernel: %d space waits (%.0f us each) over %d accepted' %
                     (kd['space'], kd['spaceus'] / kd['space'] if kd['space'] else 0, kd['asub'])))
    if 0 in rows:
        base = [w['frame'] for _, w, _ in rows[0]]
        for cap in sorted(c for c in rows if c):
            fr = [w['frame'] for _, w, _ in rows[cap]]
            wins = sum(1 for x in fr if all(x <= b - 1.0 for b in base))
            print('  cap %d vs the driver\'s own: %s ms vs %s ms -> %s' % (
                cap, '/'.join('%.2f' % x for x in fr), '/'.join('%.2f' % x for x in base),
                'faster by 1 ms or more in every pairing' if wins == len(fr) and fr else 'not faster by 1 ms in every pairing'))
    for b in bad:
        print('  FAIL ' + b)
    print('judge_g55: %s' % ('PASS' if not bad else 'FAIL (%d)' % len(bad)))
    return 1 if bad else 0


def self_test():
    t = ('RDN-TS wall us=1000000 cyc=%016x gtod1000cyc=1 frames_present=150 frames_clear=0\n'
         'RDN-TS site=submit tag=hook n=100 cyc=%016x max=0 huge=0 units=0\n'
         'RDN-T wall us=2500000 cyc=%016x gtod1000cyc=1 frames_present=250 frames_clear=0\n'
         'RDN-T site=submit tag=hook n=600 cyc=%016x max=0 huge=0 units=0\n'
         % (2660000000, 2660 * 100000, 6650000000, 2660 * 600000))
    w = world(t)
    ok = w is not None and abs(w['frame'] - 15.0) < 1e-6 and abs(w['submit'] - 5.0) < 1e-6 and abs(w['subs'] - 5.0) < 1e-6
    print('  %s the world part: %s (want frame 15, submit 5, 5 submissions a frame)' % ('ok  ' if ok else 'FAIL', w))
    k = kernel('RDN-R5 async boot=1 asubmits=10 space=2 spaceus=100 lost=0', 'RDN-R5 async boot=1 asubmits=40 space=12 spaceus=1100 lost=0')
    ok2 = k == dict(asub=30, space=10, spaceus=1000, lost=0)
    print('  %s the kernel difference: %s' % ('ok  ' if ok2 else 'FAIL', k))
    print('judge_g55 self-test: %s' % ('PASS' if ok and ok2 else 'FAIL'))
    return 0 if ok and ok2 else 1


if __name__ == '__main__':
    sys.exit(self_test() if sys.argv[1:2] == ['--self-test'] else main(sys.argv[1]))
