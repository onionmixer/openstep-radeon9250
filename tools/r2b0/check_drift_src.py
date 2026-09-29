#!/usr/bin/env python3
"""osrdn_pll.m's PLL groups may differ from R2a's by reviewed hunks only (docs/R2B0_IMPL_PLAN.md 4-2).

  check_drift_src.py            compare, then run the self-mutations; exit 1 on any failure
  check_drift_src.py --print    print the current hunks in the allowlist format (for review,
                                never copied into the allowlist unread)

pllGroup, whyName and pllSnapshot are cut out of R2a's RDNR2aProbe.m (which
ran PASS on the card) and out of OSRDNDisplay's osrdn_pll.m, and diffed line
by line.  Every hunk must appear, exactly, in tools/r2b0/drift-src-allow.txt,
and every hunk listed there must occur: an unreviewed change on either side
fails, and so does a stale allowance.  The table (r2aPll) is not compared
here -- check_r2b0_src.py holds it to the parser's.
"""

import difflib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
R2A = os.path.join(PROJ, 'probe', 'RDNR2aProbe', 'RDNR2aProbe_reloc.tproj', 'RDNR2aProbe.m')
R2B0 = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_pll.m')
ALLOW = os.path.join(HERE, 'drift-src-allow.txt')
FUNCS = [('pllGroup', 'pllGroup'), ('whyName', 'whyName'), ('pllSnapshot', 'osrdn_pll_snapshot')]


def cut(text, name):
    """The definition of name: from the comment block or return type above
    `name(` at column 0 to the closing brace at column 0."""
    m = re.search(r'^%s\(' % re.escape(name), text, re.M)
    if not m:
        raise ValueError('%s not found' % name)
    start = text.rfind('\n\n', 0, m.start()) + 2
    end = text.find('\n}\n', m.end())
    if end < 0:
        raise ValueError('%s has no closing brace' % name)
    return text[start:end + 3]


def hunks(r2a_text, r2b0_text):
    out = []
    for a_name, b_name in FUNCS:
        a = cut(r2a_text, a_name).splitlines()
        b = cut(r2b0_text, b_name).splitlines()
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag != 'equal':
                out.append((b_name, tuple(a[i1:i2]), tuple(b[j1:j2])))
    return out


def format_hunks(hs):
    lines = []
    for fn, rem, add in hs:
        lines.append('@@ ' + fn)
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
            raise ValueError('drift-src-allow.txt:%d: not a hunk line: %r' % (n, line))
    return [(f, tuple(r), tuple(a)) for f, r, a in hs]


def compare(r2a_text, r2b0_text, allow):
    try:
        have = hunks(r2a_text, r2b0_text)
    except ValueError as e:
        return [str(e)]
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
    a_text, b_text = open(R2A).read(), open(R2B0).read()
    if argv[1:] == ['--print']:
        sys.stdout.write(format_hunks(hunks(a_text, b_text)))
        return 0
    allow = parse_allow(open(ALLOW).read())
    failures = 0
    problems = compare(a_text, b_text, allow)
    for p in problems:
        print('FAIL ' + p)
    failures += len(problems)
    print('%-4s %d reviewed hunks, osrdn_pll.m differs from R2a by exactly those' %
          ('ok' if not problems else 'FAIL', len(allow)))
    muts = [
        ('R2b-0 loses the upper-bits check', 1, '        if ((c & ~LOW_BYTE) != (p & ~LOW_BYTE))\n            why = WHY_UPPER;\n', ''),
        ('R2b-0 abort writes c', 1, '            rdnMmioWrite32(base, REG_CLOCK_CNTL_INDEX, p);\n',
         '            rdnMmioWrite32(base, REG_CLOCK_CNTL_INDEX, c);\n'),
        ('R2b-0 sleeps in the group', 1, '    s = splhigh();\n', '    s = splhigh();\n    IOSleep(1);\n'),
        ('R2a source changes under R2b-0', 0, '                why = WHY_LOW;\n', '                why = WHY_UPPER;\n'),
        ('R2b-0 snapshot keeps going after a stop', 1, '        if (why != WHY_NONE)\n            break;\n', ''),
    ]
    for label, side, old, new in muts:
        texts = [a_text, b_text]
        if texts[side].count(old) != 1:
            print('FAIL mutation %r: anchor found %d times' % (label, texts[side].count(old)))
            failures += 1
            continue
        texts[side] = texts[side].replace(old, new)
        caught = bool(compare(texts[0], texts[1], allow))
        print('%-4s mutation %r %s' % ('ok' if caught else 'FAIL', label, 'caught' if caught else 'NOT caught'))
        failures += 0 if caught else 1
    stale = allow + [('pllGroup', ('never there',), ('nor this',))]
    caught = bool(compare(a_text, b_text, stale))
    print('%-4s mutation %r %s' % ('ok' if caught else 'FAIL', 'stale allowance', 'caught' if caught else 'NOT caught'))
    failures += 0 if caught else 1
    print('check_drift_src: %s' % ('PASS' if failures == 0 else 'FAIL (%d)' % failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
