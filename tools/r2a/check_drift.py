#!/usr/bin/env python3
"""The R2a target scripts may differ from R1's only by reviewed hunks (docs/R1C_R2A_IMPL_PLAN.md section 2-8).

  check_drift.py            compare, then run the self-mutations; exit 1 on any failure
  check_drift.py --print    print the current hunks in the allowlist format (for review,
                            never copied into the allowlist unread)

R1's tools/r1/target-build.sh and target-run.sh are renamed mechanically
(RENAMES below) and diffed line by line against tools/r2a's.  Every hunk of
that diff must appear, exactly, in tools/r2a/drift-allow.txt, and every hunk
listed there must occur in the diff: a change on either side that nobody
reviewed fails, and so does a stale allowance.

Allowlist format: a header `@@ <script>` opens a hunk; `- ` lines are the
renamed R1 lines it removes, `+ ` lines the R2a lines it adds, in order.
"""

import difflib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
R1 = os.path.join(PROJ, 'tools', 'r1')
ALLOW = os.path.join(HERE, 'drift-allow.txt')
SCRIPTS = ['target-build.sh', 'target-run.sh']

RENAMES = [
    ('RDNR1Probe', 'RDNR2aProbe'), ('radeonR1Entry', 'radeonR2aEntry'), ('RDN-R1', 'RDN-R2A'),
    ('R1_BUILD', 'R2A_BUILD'), ('R1BUILD', 'R2ABUILD'), ('R1RUN', 'R2ARUN'), ('R1FACTS', 'R2AFACTS'),
    ('rdn-r1', 'rdn-r2a'), ('${R1_', '${R2A_'), ('R1_* overrides', 'R2A_* overrides'), ('tools/r1/', 'tools/r2a/'),
    ('parse_r1.py', 'parse_r2a.py'), ('the R1 probe', 'the R2a probe'), ('a packed R1 probe', 'a packed R2a probe'),
]


def renamed(text):
    for a, b in RENAMES:
        text = text.replace(a, b)
    return text


def hunks(script, r1_text, r2a_text):
    a = renamed(r1_text).splitlines()
    b = r2a_text.splitlines()
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != 'equal':
            out.append((script, tuple(a[i1:i2]), tuple(b[j1:j2])))
    return out


def format_hunks(hs):
    lines = []
    for script, rem, add in hs:
        lines.append('@@ ' + script)
        lines += ['- ' + l for l in rem]
        lines += ['+ ' + l for l in add]
    return '\n'.join(lines) + '\n'


def parse_allow(text):
    hs = []
    cur = None
    for n, line in enumerate(text.splitlines(), 1):
        if line.startswith('@@ '):
            cur = [line[3:].strip(), [], []]
            hs.append(cur)
        elif line.startswith('- ') or line == '-':
            cur[1].append(line[2:])
        elif line.startswith('+ ') or line == '+':
            cur[2].append(line[2:])
        elif line.startswith('#') or not line.strip():
            continue
        else:
            raise ValueError('drift-allow.txt:%d: not a hunk line: %r' % (n, line))
    return [(s, tuple(r), tuple(a)) for s, r, a in hs]


def compare(texts, allow):
    """texts: {script: (r1 text, r2a text)}.  Return problems."""
    have = []
    for s in SCRIPTS:
        have += hunks(s, *texts[s])
    problems = []
    remaining = list(allow)
    for h in have:
        if h in remaining:
            remaining.remove(h)
        else:
            problems.append('unreviewed hunk in %s:\n%s' % (h[0], format_hunks([h])))
    for h in remaining:
        problems.append('allowed hunk no longer present in %s:\n%s' % (h[0], format_hunks([h])))
    return problems


def main(argv):
    texts = dict((s, (open(os.path.join(R1, s)).read(), open(os.path.join(HERE, s)).read())) for s in SCRIPTS)
    if argv[1:] == ['--print']:
        hs = []
        for s in SCRIPTS:
            hs += hunks(s, *texts[s])
        sys.stdout.write(format_hunks(hs))
        return 0
    allow = parse_allow(open(ALLOW).read())
    failures = 0
    problems = compare(texts, allow)
    for p in problems:
        print('FAIL ' + p)
    failures += len(problems)
    print('%-4s %d reviewed hunks, the scripts differ from R1 by exactly those' %
          ('ok' if not problems else 'FAIL', len(allow)))
    # self-mutations: each must produce a problem
    muts = [
        ('R2a build loses the sum check', 'target-build.sh', 1,
         'if [ "$GOTSUM" != "$WANTSUM" ] || [ "$GOTBLK" != "$WANTBLK" ]; then', 'if false; then'),
        ('R2a run loses the Matrox check', 'target-run.sh', 1,
         'if [ "$n" != "0" ]; then fail "Active Drivers still names a Matrox driver: boot the generic VGA baseline"; fi',
         ''),
        ('R1 build changes under R2a', 'target-build.sh', 0, 'fail "make exited $mst"', 'fail "make exited"'),
        ('R2a run gains a line', 'target-run.sh', 1, '=== 6. unload ===', '=== 6. unload ===\n"\nrm -rf /'),
    ]
    for label, script, side, old, new in muts:
        t = dict(texts)
        pair = list(t[script])
        if pair[side].count(old) != 1:
            print('FAIL mutation %r: anchor found %d times' % (label, pair[side].count(old)))
            failures += 1
            continue
        pair[side] = pair[side].replace(old, new)
        t[script] = tuple(pair)
        caught = bool(compare(t, allow))
        print('%-4s mutation %r %s' % ('ok' if caught else 'FAIL', label, 'caught' if caught else 'NOT caught'))
        failures += 0 if caught else 1
    stale = allow + [('target-run.sh', ('never there',), ('nor this',))]
    caught = bool(compare(texts, stale))
    print('%-4s mutation %r %s' % ('ok' if caught else 'FAIL', 'stale allowance', 'caught' if caught else 'NOT caught'))
    failures += 0 if caught else 1
    print('check_drift: %s' % ('PASS' if failures == 0 else 'FAIL (%d)' % failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
