#!/usr/bin/env python3
"""Re-aim the citations that check_citations.py says have drifted.

  python3 tools/oracle/reaim.py            # say what it WOULD do
  python3 tools/oracle/reaim.py --write    # do it

Every edit to a file we cite moves every citation below it, and each rung has
cost three or four turns of finding the new line by hand.  The checker already
knows where the string went -- it prints "it is now at [N]" -- so this reads its
output and applies the move to both the document and EXPECT.

WHAT IT REFUSES TO TOUCH, and why each one is a real accident that happened:

  * a string that is now at MORE THAN ONE line.  Which one the document meant is
    not recoverable from here.
  * a string that is NOWHERE in the file.  That is not drift, it is a citation
    that has stopped being true, and a tool that "fixed" it would erase the
    finding.
  * the BARE form, `:N`.  It binds to the previously named file, so rewriting it
    by string match once changed `radeon_render.c:884` in another paragraph
    (recorded).  Bare citations are listed for the human instead.

It never invents an EXPECT row: a citation the checker calls "not in EXPECT" is
a line nobody has opened, and opening it is the point.
"""

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
CHECKER = os.path.join(HERE, 'check_citations.py')


def failures():
    docs = [os.path.join(PROJ, 'docs', f)
            for f in sorted(os.listdir(os.path.join(PROJ, 'docs')))
            if f.endswith('.md')]
    docs.append(os.path.join(PROJ, 'ANALYSIS.md'))
    r = subprocess.run([sys.executable, CHECKER] + docs,
                       capture_output=True, text=True)
    out = []
    for ln in r.stdout.split('\n'):
        m = re.match(r"FAIL (\S+):(\d+)-(\d+) does not contain (.+?) -- "
                     r"it is now at \[(\d+)\]$", ln)
        if m:
            out.append(dict(f=m.group(1), a=int(m.group(2)), b=int(m.group(3)),
                            want=m.group(4), to=int(m.group(5))))
        elif 'FAIL' in ln:
            out.append(dict(skip=ln.strip()))
    return out


def main():
    write = '--write' in sys.argv
    moves, skipped = {}, []
    for f in failures():
        if 'skip' in f:
            skipped.append(f['skip'])
            continue
        moves.setdefault((f['f'], f['a'], f['b']), []).append(f['to'])
    if not moves and not skipped:
        print('reaim: nothing has drifted')
        return 0

    # A RANGE MAY REQUIRE SEVERAL STRINGS, AND THE CHECKER ONLY REPORTS THE ONES
    # THAT FAILED.  The first version moved a range to where its one failing
    # string went and broke the one that had still been inside -- code had been
    # inserted BETWEEN them, so the range had to grow, not slide.  So every
    # string of the key is located here, from the checker's own table and the
    # real file, and the range is only re-aimed when all of them fit.
    import importlib.util
    spec = importlib.util.spec_from_file_location('cc', CHECKER)
    cc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cc)

    plan = []
    for (fn, a, b), _tos in sorted(moves.items()):
        want = cc.EXPECT.get((fn, a, b))
        if want is None:
            skipped.append('%s:%d-%d: not in EXPECT' % (fn, a, b))
            continue
        want = (want,) if isinstance(want, str) else tuple(want)
        try:
            lines = open(os.path.join(cc.UP, cc.PATHS[fn]),
                         errors='replace').read().split('\n')
        except (KeyError, IOError) as e:
            skipped.append('%s:%d-%d: cannot open it (%s)' % (fn, a, b, e))
            continue
        at = []
        for w in want:
            hits = [i + 1 for i, ln in enumerate(lines) if w in ln]
            if len(hits) != 1:
                at = None
                skipped.append('%s:%d-%d: %r is at %s -- open it'
                               % (fn, a, b, w,
                                  'no line' if not hits else '%d lines' % len(hits)))
                break
            at.append(hits[0])
        if at is None:
            continue
        na, nb = min(at), max(at)
        if nb - na > (b - a):
            # the strings moved APART: the range would have to grow, and by how
            # much is a judgement about what the citation meant
            skipped.append('%s:%d-%d: its strings are now %d apart but the '
                           'range spans %d -- open it'
                           % (fn, a, b, nb - na, b - a))
            continue
        nb = na + (b - a)
        if (na, nb) == (a, b):
            continue
        plan.append((fn, a, b, na, nb))

    docs = [os.path.join(PROJ, 'docs', f)
            for f in sorted(os.listdir(os.path.join(PROJ, 'docs')))
            if f.endswith('.md')] + [os.path.join(PROJ, 'ANALYSIS.md')]
    src = open(CHECKER).read()
    touched = 0
    for fn, a, b, na, nb in plan:
        old_named = '`%s:%d-%d`' % (fn, a, b) if a != b else '`%s:%d`' % (fn, a)
        new_named = '`%s:%d-%d`' % (fn, na, nb) if na != nb else '`%s:%d`' % (fn, na)
        hits = 0
        for d in docs:
            t = open(d).read()
            if old_named in t:
                hits += t.count(old_named)
                if write:
                    open(d, 'w').write(t.replace(old_named, new_named))
        okey = "('%s', %d, %d)" % (fn, a, b)
        nkey = "('%s', %d, %d)" % (fn, na, nb)
        if okey in src:
            if write:
                src = src.replace(okey, nkey)
        else:
            skipped.append('%s: EXPECT has no %s (a bare `:N` cites it?)'
                           % (fn, okey))
            continue
        print('  %-24s %d-%d -> %d-%d   (%d place%s in the documents)'
              % (fn, a, b, na, nb, hits, '' if hits == 1 else 's'))
        touched += 1
    if write and touched:
        open(CHECKER, 'w').write(src)
    for s in skipped:
        print('  LEFT ALONE  %s' % s)
    print('reaim: %d re-aimed%s, %d left for a human'
          % (touched, '' if write else ' (dry run -- pass --write)', len(skipped)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
