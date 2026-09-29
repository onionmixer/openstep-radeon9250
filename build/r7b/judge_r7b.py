#!/usr/bin/env python3
"""R7b boot judge: the things the character-device path must show that R7a's judge cannot see.

  python3 build/r7/judge_r7b.py <boot nonce> [log file]
  python3 build/r7/judge_r7b.py --self-test

The verdicts themselves are judged by build/r7/indep_r7a.py, which reimplements the thirteen
rules; this file judges the PATH -- the page, the window, the latch, and the refusals that never
reach the verifier.  Each check is written so that a missing line fails rather than passes: a
judge that reports nothing when the boot logged nothing is not a judge.
"""
import re
import sys

PAGE = 8192
ALLOC = 12288                                   # R7B_ALLOC_BYTES: the window plus one MMU page
CONV_END = 0xa0000


def judge(text, n):
    """(ok lines, problems) for boot n"""
    ok, bad = [], []

    def one(pat, what):
        m = [x for x in re.finditer(pat % re.escape(n), text)]
        if len(m) != 1:
            bad.append('%s: %d lines, want 1' % (what, len(m)))
            return None
        return m[0]

    # 1. the page: allocated, contiguous, aligned, inside the arena
    m = one(r'RDN-R7B page boot=%s va=([0-9a-f]{8}) phys=([0-9a-f]{8}) len=([0-9a-f]{8}) '
            r'skip=([0-9a-f]{8}) (\w+)', 'the batch page line')
    if m:
        va, phys, ln, skip = (int(m.group(i), 16) for i in (1, 2, 3, 4))
        why = m.group(5)
        if why != 'ok':
            bad.append('the batch page was refused: %s' % why)
        elif phys == 0 or va == 0:
            bad.append('the batch page says ok with a zero address')
        elif phys % PAGE:
            bad.append('the batch page is at %#x, which does not start a page' % phys)
        elif ln != ALLOC:
            bad.append('the allocation is %d bytes, want %d' % (ln, ALLOC))
        elif skip % 4096 or skip + PAGE > ALLOC:
            bad.append('the skipped offset %d is not a usable start' % skip)
        elif phys - skip + ALLOC > CONV_END:
            bad.append('the allocation reaches %#x, past the arena' % (phys - skip + ALLOC))
        else:
            ok.append('the batch page is one aligned run at %#x (%d bytes in)' % (phys, skip))

    # 2. the window went in, and the self-test judged it
    m = one(r'RDN-R4 vmap boot=%s .*? self=(\d+)/(\d+) allowed=(\d+) major=(-?\d+) '
            r'batch=(-?\d+) bphys=([0-9a-f]{8}) (\w+)', 'the vmap line')
    if m:
        cases, wrong, allowed, major, batch = (int(m.group(i)) for i in (1, 2, 3, 4, 5))
        bphys, why = int(m.group(6), 16), m.group(7)
        if why != 'ok':
            bad.append('the device was not registered: %s' % why)
        elif wrong:
            bad.append('the d_mmap self-test found %d wrong answers' % wrong)
        elif batch != 0:
            bad.append('the batch window was refused, code %d' % batch)
        elif bphys == 0:
            bad.append('the batch window is fixed at zero')
        else:
            ok.append('the batch window is at %#x; the self-test asked %d and got none wrong'
                      % (bphys, cases))

    # 3. every submission the client made, and what the driver did with it
    subs = list(re.finditer(r'RDN-R7B submit boot=%s words=(\d+) rc=(-?\d+) why=(\d+) at=(\d+) '
                            r'word=([0-9a-f]{8}) drawn=(\d+) subs=(\d+) denied=(\d+)'
                            % re.escape(n), text))
    stages = list(re.finditer(r'RDN-R7B stage boot=%s words=(\d+) staged=(\d+) dropped=(\d+) ok=(-?\d+)'
                              % re.escape(n), text))
    # M2g: A QUIET SUCCESS PRINTS NO STAGE LINE.  With the submit log off by
    # default the `stage` line survives only for a staging that FAILED; the
    # `submit` line is printed for every submission that ran, quiet or not
    # (OSRDNDisplay.m:1010-1013).  Either is proof a submission got here --
    # requiring stage lines alone would call a working quiet boot dead
    # (docs/M2G_PLAN.md 8, C8).
    if not stages and not subs:
        bad.append('no submission reached the driver at all')
    else:
        drew = [s for s in subs if s.group(6) == '1']
        refused = [s for s in subs if s.group(6) == '0']
        if not drew:
            bad.append('no submission drew: the path never worked')
        if not refused:
            bad.append('no submission was refused: the verifier was never exercised through it')
        # a refusal must leave a reason AND the word it stopped at
        for s in refused:
            if s.group(3) == '0' and s.group(2) == '0':
                bad.append('a submission neither drew nor refused (n=%s)' % s.group(1))
        # the kernel's own limits: a submission that never reached the verifier.
        # Either shape counts -- an argument the driver rejected outright, or a
        # staging it would not take.
        denied = [s for s in stages if s.group(4) == '0'] + \
            list(re.finditer(r'RDN-R7B reject boot=%s words=(\d+) (\w+) denied=(\d+)' % re.escape(n), text))
        if not denied:
            bad.append('no submission was stopped before the verifier (gate E did not run)')
        else:
            ok.append('%d submission(s) stopped at the kernel limit before the verifier' % len(denied))
        ok.append('%d submissions: %d drew, %d refused' % (len(subs), len(drew), len(refused)))

    # 4. the latch: a second open refused while one is held
    if not re.search(r'RDN-R4 open boot=%s .*? refused ' % re.escape(n), text):
        bad.append('no open was ever refused: the latch was not exercised (gate C)')
    else:
        ok.append('a second open was refused while the device was held')

    # 5. an unknown command leaves its number behind
    if not re.search(r'RDN-R7B ioctl boot=%s cmd=[0-9a-f]{8} unknown' % re.escape(n), text):
        bad.append('no unknown ioctl was logged (gate E did not run, or logs nothing)')
    else:
        ok.append('an unknown command was refused and left its number')
    return ok, bad


GOOD = """
RDN-R7B page boot=aabbccdd va=00090000 phys=00062000 len=00003000 skip=00001000 ok
RDN-R4 vmap boot=aabbccdd start=0029e000 end=07c00000 page=8192 shift=13 bar0=e0000000 pfn0=0007014f pfnN=00073dff mem=08000000 aper=08000000 fix=0 self=15907/0 allowed=15537 major=38 batch=0 bphys=00062000 ok
RDN-R4 open boot=aabbccdd dev=2600 minor=0 ok opens=1 refused=0 closes=0
RDN-R4 open boot=aabbccdd dev=2600 minor=0 refused opens=1 refused=1 closes=0
RDN-R7B stage boot=aabbccdd words=55 staged=55 dropped=0 ok=1
RDN-R7B submit boot=aabbccdd words=55 rc=0 why=0 at=0 word=00000000 drawn=1 subs=1 denied=0
RDN-R7B stage boot=aabbccdd words=57 staged=57 dropped=0 ok=1
RDN-R7B submit boot=aabbccdd words=57 rc=1 why=1 at=112 word=c0012800 drawn=0 subs=2 denied=0
RDN-R7B reject boot=aabbccdd words=2017 count denied=1
RDN-R7B reject2 boot=aabbccdd words=2017 copyin denied=2
RDN-R7B ioctl boot=aabbccdd cmd=deadbeef unknown caps=40205201 submit=c0205202
"""

BREAKS = [
    ('the page is refused', 'skip=00001000 ok', 'skip=00000000 align'),
    ('the page is not aligned', 'phys=00062000 len', 'phys=00062004 len'),
    # page ALIGNED, so the arena rule is what has to fire -- an unaligned address
    # would have been caught a line earlier and proved nothing about this one
    ('the page runs past the arena', 'phys=00062000 len=00003000', 'phys=000a0000 len=00003000'),
    ('the batch window was refused', 'batch=0 bphys', 'batch=13 bphys'),
    ('the d_mmap self-test found a wrong answer', 'self=15907/0', 'self=15907/2'),
    ('nothing drew', 'drawn=1 subs=1', 'drawn=0 subs=1'),
    ('nothing was refused', 'drawn=0 subs=2', 'drawn=1 subs=2'),
    ('the kernel limit was never reached', 'RDN-R7B reject boot=aabbccdd words=2017 count denied=1', 'x'),
    ('no open was refused', 'refused opens=1 refused=1 closes=0', 'ok opens=2 refused=0 closes=0'),
    ('an unknown command logs nothing', 'RDN-R7B ioctl boot=aabbccdd cmd=deadbeef unknown', 'x'),
    ('the page line is missing', 'RDN-R7B page boot=aabbccdd', 'RDN-R7B page boot=99999999'),
    ('the vmap line is missing', 'RDN-R4 vmap boot=aabbccdd', 'RDN-R4 vmap boot=99999999'),
]


def self_test():
    fails = 0
    ok, bad = judge(GOOD, 'aabbccdd')
    if bad:
        print('  FAIL the good boot is judged bad: %s' % bad)
        fails += 1
    else:
        print('  ok   the good boot passes (%d checks)' % len(ok))
    # M2g: the same boot with every SUCCESSFUL stage line swallowed (the new
    # default) must still pass -- only failed stagings speak now
    quiet_ = '\n'.join(l for l in GOOD.split('\n')
                       if not (l.startswith('RDN-R7B stage') and l.endswith('ok=1')))
    ok2, bad2 = judge(quiet_, 'aabbccdd')
    gone_ = GOOD.count('ok=1\n') + GOOD.endswith('ok=1')
    if bad2 or quiet_ == GOOD:
        print('  FAIL a quiet boot (no successful stage lines) is judged bad: %s'
              % (bad2 or 'the fixture had no ok=1 stage line to remove'))
        fails += 1
    else:
        print('  ok   a quiet boot, with only the failed stagings speaking, still passes')
    # and a boot where NOTHING reached the driver still fails
    dead_ = '\n'.join(l for l in GOOD.split('\n')
                      if not l.startswith('RDN-R7B stage') and not l.startswith('RDN-R7B submit'))
    _o3, bad3 = judge(dead_, 'aabbccdd')
    if not any('no submission reached the driver' in x for x in bad3):
        print('  FAIL a boot with no stage and no submit line is not judged dead')
        fails += 1
    else:
        print('  ok   a boot with no stage and no submit line is still judged dead')
    for label, old, new in BREAKS:
        if GOOD.count(old) != 1:
            print('  FAIL %-46s anchor found %d times' % (label, GOOD.count(old)))
            fails += 1
            continue
        _, b = judge(GOOD.replace(old, new), 'aabbccdd')
        print('  %-4s %-46s %s' % ('ok' if b else 'FAIL', label, b[0] if b else 'NOT CAUGHT'))
        fails += 0 if b else 1
    print('judge_r7b: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


def main():
    if '--self-test' in sys.argv:
        return self_test()
    if len(sys.argv) < 2:
        return print(__doc__) or 2
    n = sys.argv[1]
    log = sys.argv[2] if len(sys.argv) > 2 else 'build/r6/boot-%s.full.log' % n
    ok, bad = judge(open(log, errors='replace').read(), n)
    for line in ok:
        print('  ok   %s' % line)
    for line in bad:
        print('  FAIL %s' % line)
    print('judge_r7b: %s' % ('PASS' if not bad else 'FAIL (%d)' % len(bad)))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
