#!/usr/bin/env python3
"""G4-8 (docs/G4_8_REPLAY_PLAN.md 4): judge one rdnreplay run from its breadcrumbs.
  judge_replay.py <crumb file> [--reps N]      the file rdnreplay wrote with crumb=<path>
  judge_replay.py --self-test
Each repetition leaves "rep k seed" before the ioctl and "done k status why at drawn" after it.
A "rep" with no "done" is the freeze's fingerprint: the machine never came back from that submission.
  --w0 W --stream FILE --words N   also compute, for every rep, where the client stream sat in the 4096-word
                                   ring (the boot's wptr after CP START is W; each rep is a 32-word prefix
                                   submission and a (N + 12 rounded up to 16)-word client submission), and for
                                   the frozen rep which client word crossed the ring end and which packet it is in
"""
import re
import struct
import sys

RING = 4096
PREFIX_WORDS = 32                       # 30 words (osrdn_cp.m prefix, 15 PACKET0 pairs) padded to 16
TAIL = 12                               # our WAIT_UNTIL pair (2) + our tail (10): osrdn_cp.m "need = subWords + 2 + 10"


def packets(words):
    """[(start, end, kind)] the packets of a client stream"""
    out, i = [], 0
    while i < len(words):
        h = words[i]
        t = h >> 30
        if t == 0:
            n = ((h >> 16) & 0x3fff) + 1
            out.append((i, i + 1 + n, 'P0 %04x' % ((h & 0x1fff) << 2)))
            i += 1 + n
        elif t == 3:
            n = ((h >> 16) & 0x3fff) + 1
            out.append((i, i + 1 + n, 'P3 op %02x' % ((h >> 8) & 0xff)))
            i += 1 + n
        else:
            out.append((i, i + 1, 'P2'))
            i += 1
    return out


def positions(w0, nwords, reps):
    """per rep: (client start index in the ring, the client word that lands on ring index 0, or None)"""
    client = (nwords + TAIL + 15) & ~15
    out = []
    for k in range(reps):
        start = (w0 + PREFIX_WORDS + k * (PREFIX_WORDS + client)) % RING     # the WAIT_UNTIL pair sits here
        first = (start + 2) % RING                                          # client word 0
        cross = (RING - first) % RING                                       # client word that lands on index 0
        out.append((start, cross if 0 < cross < nwords else None))
    return out


def judge(text, reps=None):
    p, notes = [], []
    rep, done = {}, {}
    for line in text.splitlines():
        m = re.match(r'rep (\d+) (\d+)$', line.strip())
        if m:
            rep[int(m.group(1))] = int(m.group(2))
            continue
        m = re.match(r'done (\d+) (\d+) (\d+) (\d+) (\d+)$', line.strip())
        if m:
            done[int(m.group(1))] = tuple(int(x) for x in m.groups()[1:])
    if not rep:
        p.append('no rep crumb at all: the tool never reached a submission')
        return p, notes
    last = max(rep)
    if last not in done:
        p.append('rep %d has no done: the submission never returned (freeze) -- seed %d' % (last, rep[last]))
    for k in sorted(done):
        st, why, at, drawn = done[k]
        if st or why or not drawn:
            p.append('rep %d: status %d why %d at %d drawn %d' % (k, st, why, at, drawn))
    missing = [k for k in range(last) if k not in rep]
    if missing:
        p.append('reps missing before the last: %s' % missing[:5])
    if reps is not None and len(done) != reps:
        p.append('%d done, want %d' % (len(done), reps))
    seeds = list(rep.values())
    if len(set(seeds)) != len(seeds):
        p.append('a seed repeats')
    notes.append('%d rep, %d done, last rep %d' % (len(rep), len(done), last))
    return p, notes


def self_test():
    ok_text = 'rep 0 5001\ndone 0 0 0 0 1\nrep 1 5002\ndone 1 0 0 0 1\n'
    cases = [
        ('clean two reps pass', ok_text, 2, False),
        ('the last rep has no done (freeze)', ok_text + 'rep 2 5003\n', 3, True),
        ('a refusal is reported', ok_text.replace('done 1 0 0 0 1', 'done 1 0 10 5 0'), 2, True),
        ('not drawn is reported', ok_text.replace('done 1 0 0 0 1', 'done 1 0 0 0 0'), 2, True),
        ('fewer done than asked', ok_text, 3, True),
        ('a repeated seed', ok_text.replace('rep 1 5002', 'rep 1 5001'), 2, True),
        ('no crumbs', '', 1, True),
    ]
    bad = 0
    for name, text, reps, want_fail in cases:
        p, _ = judge(text, reps)
        got = bool(p)
        print('  %-4s %s' % ('ok' if got == want_fail else 'FAIL', name))
        bad += 0 if got == want_fail else 1
    print('judge_replay self-test: %s' % ('PASS' if not bad else 'FAIL (%d)' % bad))
    return bad


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        sys.exit(1 if self_test() else 0)
    if not sys.argv[1:]:
        sys.exit(__doc__)
    reps = None
    if '--reps' in sys.argv:
        reps = int(sys.argv[sys.argv.index('--reps') + 1])
    p, notes = judge(open(sys.argv[1], errors='replace').read(), reps)
    if '--w0' in sys.argv and '--stream' in sys.argv and '--words' in sys.argv:
        w0 = int(sys.argv[sys.argv.index('--w0') + 1])
        n = int(sys.argv[sys.argv.index('--words') + 1])
        words = list(struct.unpack('<%dI' % n, open(sys.argv[sys.argv.index('--stream') + 1], 'rb').read()[:4 * n]))
        pk = packets(words)
        text = open(sys.argv[1], errors='replace').read()
        reps_seen = [int(m.group(1)) for m in re.finditer(r'^rep (\d+) ', text, re.M)]
        last = max(reps_seen) if reps_seen else -1
        for k, (start, cross) in enumerate(positions(w0, n, last + 1)):
            if cross is None:
                where = 'no crossing inside the stream'
            else:
                a_, b_, kind = next(((a, b, kd) for a, b, kd in pk if a <= cross < b), (0, 0, '?'))
                where = 'client word %d crosses the ring end, inside %s [%d, %d)' % (cross, kind, a_, b_)
            tag = 'FROZEN' if k == last and not re.search(r'^done %d ' % k, text, re.M) else ''
            if tag or k < 3 or k == last:
                print('  --   rep %d: client at ring %d; %s %s' % (k, start, where, tag))
    for n in notes:
        print('  --   ' + n)
    for x in p:
        print('  FAIL ' + x)
    print('judge_replay: %s' % ('PASS' if not p else 'FAIL (%d)' % len(p)))
    sys.exit(1 if p else 0)
