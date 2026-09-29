#!/usr/bin/env python3
"""M1c gate C: the eight-step approval run, judged as one transcript.

  judge_m1c.py <build dir>
  judge_m1c.py --self-test

The review's sharpest point about the first draft was that C, D, E, F and G
could be different runs, and an implementation that behaved differently per run
would pass each of them.  So there is one run, and this reads the whole of it:
the pixels of all three buffers against the stock link, and the counters at
every step of the same process.

The steps, and what each is for:
  bind1                 first bind -- the surface is taken (wasBound was 0)
  bind2                 rebind, same size -- taken again (wasBound was 1)
  bind-second-refused   a SECOND context while the first owns it -> OWNED
  rebind1               the first context takes it back
  bind3-refused         rebind at another size -> SIZE, and osmesa.c's leave
                        path runs: it mirrors WITHOUT testing the binding
  destroy1/2            the surface goes back
"""

import shutil
import atexit
import os
import re
import sys

NAMES = ['taken', 'maps', 'unmaps', 'live', 'livemax', 'mirrors', 'idle']
REASONS = ['-', 'NO_ACCEL', 'OWNED', 'SIZE', 'MAP', 'ARGS']


def pixels(path):
    out = {}
    for line in open(path, errors='replace'):
        m = re.match(r'RDNSURF px (\w+) (\d+)((?: [0-9a-f]{8})+)\s*$', line)
        if m:
            out.setdefault(m.group(1), []).extend(int(x, 16) for x in m.group(3).split())
    return out


def counters(path):
    out = {}
    for line in open(path, errors='replace'):
        m = re.match(r'RDNSURF run=\S+ step=(\S+) taken=(\d+) maps=(\d+) unmaps=(\d+) '
                     r'live=(\d+) livemax=(\d+) mirrors=(\d+) idle=(\d+)', line)
        if m:
            out[m.group(1)] = dict(zip(NAMES, (int(x) for x in m.groups()[1:])))
    return out


def refusals(path):
    """{step: {reason: count}} -- the step name already ends in its own label,
    so the breakdown line for step X is 'step=X-refused'"""
    out = {}
    for line in open(path, errors='replace'):
        # the breakdown line begins with the OK reason, spelt '-='.  Without
        # that anchor the COUNTER line of the same step matched too and
        # overwrote it, and the judge then looked for OWNED among 'taken',
        # 'maps'... -- a parser bug that reported a result that was there.
        m = re.match(r'RDNSURF run=\S+ step=(\S+)-refused (-=\d+(?: \S+=\d+)*)', line)
        if m:
            out[m.group(1)] = dict((kv.split('=')[0], int(kv.split('=')[1]))
                                   for kv in m.group(2).split())
    return out


def hooks(path):
    out = {}
    for line in open(path, errors='replace'):
        m = re.match(r'RDNSURF run=\S+ step=(\S+)-hooks ((?:\S+=\d+ ?)+)', line)
        if m:
            out[m.group(1)] = dict((kv.split('=')[0], int(kv.split('=')[1]))
                                   for kv in m.group(2).split())
    return out


def judge(d):
    ok, bad = [], []
    sp = os.path.join(d, 's-stock.out')
    ap = os.path.join(d, 's-accel.out')
    if not (os.path.exists(sp) and os.path.exists(ap)):
        return [], ['the two transcripts are not both in the build']

    a, b = pixels(sp), pixels(ap)
    c, r, h = counters(ap), refusals(ap), hooks(ap)

    # 1. the pixels, all three buffers
    for tag, n in (('A', 4096), ('B', 4096), ('C', 1024)):
        if len(a.get(tag, [])) != n or len(b.get(tag, [])) != n:
            bad.append('%s: stock %d and accel %d pixels, want %d'
                       % (tag, len(a.get(tag, [])), len(b.get(tag, [])), n))
        elif a[tag] != b[tag]:
            k = next(i for i in range(n) if a[tag][i] != b[tag][i])
            bad.append('%s: %d pixels differ, first at %d (%08x vs %08x)'
                       % (tag, sum(1 for i in range(n) if a[tag][i] != b[tag][i]),
                          k, a[tag][k], b[tag][k]))
        elif sum(1 for v in a[tag] if v) < 100 or len(set(a[tag])) < 3:
            bad.append('%s: too little drawn (%d non-black, %d colours) for identity to mean '
                       'anything' % (tag, sum(1 for v in a[tag] if v), len(set(a[tag]))))
        else:
            ok.append('%s: %d pixels identical, %d non-black, %d colours'
                      % (tag, n, sum(1 for v in a[tag] if v), len(set(a[tag]))))

    # 2. the steps, as CHANGES between one step and the next.
    #
    # The first draft pinned absolute counts, and adding two steps to the test
    # broke four of them while every property they stood for still held.  A
    # delta says the property directly and survives the test growing.
    order = [l.split('step=')[1].split()[0]
             for l in open(ap, errors='replace')
             if re.match(r'RDNSURF run=\S+ step=\S+ taken=', l)]
    want = [('bind1', 'taken', '+', 'the first bind took the surface'),
            ('bind2', 'taken', '+', 'a rebind at the same size took it again'),
            ('bind-second-refused', 'taken', '0', 'a second context did NOT get it'),
            ('rebind1', 'taken', '+', 'the first context took it back'),
            ('bind3-refused', 'mirrors', '+', 'the leave path mirrored'),
            ('bind3-refused', 'unmaps', '+', 'and released')]
    for step, field, how, what in want:
        if step not in c:
            bad.append('step %s is missing from the transcript' % step)
            continue
        i = order.index(step)
        prev = c[order[i - 1]][field] if i > 0 else 0
        d = c[step][field] - prev
        if (how == '+' and d < 1) or (how == '0' and d != 0):
            bad.append('%s: %s changed by %d, want %s (%s)' % (step, field, d, how, what))
        else:
            ok.append('%-20s %s %+d -- %s' % (step, field, d, what))
    if 'destroy1' in c and c['destroy1']['livemax'] != 1:
        bad.append('livemax is %d: a second window was live at once' % c['destroy1']['livemax'])
    elif 'destroy1' in c:
        ok.append('%-20s livemax=1 -- never more than one mapping was live' % 'destroy1')

    # 3. the refusals were for the RIGHT reason
    # the step names already end in their own label, so these are the keys
    for step, reason in (('bind-second-refused', 'OWNED'), ('bind3-refused', 'SIZE')):
        got = r.get(step)
        if got is None:
            bad.append('no refusal breakdown for %s' % step)
        elif got.get(reason, 0) < 1:
            bad.append('%s was not refused for %s (%s)' % (step, reason, got))
        else:
            ok.append('%s refused for %s' % (step, reason))

    # 4. all six hooks actually ran
    last = h.get('destroy1')
    if last is None:
        bad.append('no hook counts at the end of the run')
    else:
        for name in ('Buffer', 'BoundTo', 'Stride', 'AppBuffer', 'Mirror', 'ReleaseBuffer'):
            if last.get(name, 0) < 1:
                bad.append('%s was never called (%d)' % (name, last.get(name, 0)))
        if not [x for x in bad if 'never called' in x]:
            ok.append('all six hooks ran: ' + ', '.join(
                '%s=%d' % (n, last[n]) for n in
                ('Buffer', 'BoundTo', 'Stride', 'AppBuffer', 'Mirror', 'ReleaseBuffer')))

    # 5. ALPHABUF_BIT is gone once the surface was taken (M1b measured it set)
    seen = None
    for line in open(ap, errors='replace'):
        # the LAST state's mask, not the running OR: an OR can only grow, so
        # "0x100 is gone" is unanswerable from it (that is how this judge first
        # reported a failure that was its own question's fault)
        m = re.search(r'step=destroy1-raster seen=[0-9a-f]{8} declined=[0-9a-f]{8} '
                      r'last=([0-9a-f]{8})', line)
        if m:
            seen = int(m.group(1), 16)
    # the running OR says states WERE recorded; the last one says what is set now
    runningOr = None
    for line in open(ap, errors='replace'):
        m = re.search(r'step=destroy1-raster seen=([0-9a-f]{8})', line)
        if m:
            runningOr = int(m.group(1), 16)
    if seen is None or runningOr is None:
        bad.append('the raster mask was not reported')
    elif runningOr == 0:
        bad.append('no raster mask was ever recorded, so "0x100 is absent" says nothing')
    elif not (runningOr & 0x100):
        bad.append('ALPHABUF_BIT was never set at all, so its absence proves nothing '
                   '(M1b measured it set)')
    elif seen & 0x100:
        bad.append('ALPHABUF_BIT is still set in the last state (%#x) -- the substitution '
                   'did not clear it' % seen)
    else:
        ok.append('ALPHABUF_BIT was set (running OR %#06x) and is GONE from the last '
                  'state (%#06x)' % (runningOr, seen))
    return ok, bad


def self_test():
    fails = 0

    def one(label, cond):
        nonlocal fails
        fails += 0 if cond else 1
        print('  %-4s %s' % ('ok' if cond else 'FAIL', label))

    line = ('RDNSURF run=1 step=bind-second-refused-refused -=0 NO_ACCEL=0 OWNED=1 '
            'SIZE=0 MAP=0 ARGS=0\n')
    import tempfile
    t = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, t, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
    p = os.path.join(t, 'x')
    open(p, 'w').write(line)
    r = refusals(p)
    one('the breakdown line is read for its own step',
        r.get('bind-second-refused', {}).get('OWNED') == 1)
    open(p, 'w').write('RDNSURF run=1 step=bind1-refused taken=2 maps=1 unmaps=0 '
                       'live=1 livemax=1 mirrors=0 idle=0\n')
    one('and a counter line of the same step is NOT mistaken for one',
        refusals(p) == {})

    open(p, 'w').write('RDNSURF px A 00000 00000001 00000002\n')
    one('pixels are read by tag', pixels(p).get('A') == [1, 2])
    print('judge_m1c self-test: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return fails


def main():
    if '--self-test' in sys.argv:
        return 1 if self_test() else 0
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    ok, bad = judge(sys.argv[1])
    for x in ok:
        print('  ok   %s' % x)
    for x in bad:
        print('  FAIL %s' % x)
    print('judge_m1c: %s' % ('PASS' if not bad else 'FAIL (%d)' % len(bad)))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
