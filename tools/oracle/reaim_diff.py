#!/usr/bin/env python3
"""Re-aim citations by an EXACT old -> new line map, when the pre-edit file is in hand.

  reaim_diff.py --old world5.c=/path/to/world5.c.before [...]           dry run
  reaim_diff.py --old world5.c=/path/to/world5.c.before [...] --write   do it

WHY THIS EXISTS BESIDE reaim.py.  reaim.py finds a citation's new home by
searching for the string EXPECT records, and rightly refuses when that string is
at more than one line -- it cannot know which one was meant.  In a file full of
repeated shapes (`cpWait(base, W_IDLE, ...)` is at ten lines) that is most of
them: one M1y edit left 39 citations for a human.  But when the file as it was
BEFORE the edit is available, the mapping is not a search at all -- difflib says
which old line became which new line, and every citation moves exactly.

WHAT IT STILL LEAVES ALONE, and why:
  * a cited line that no longer exists.  That is not drift: the citation has
    stopped being true, and moving it would erase the finding.
  * the BARE form, `:N`.  It binds to the previously named file, so it is not
    matched by name here.  check_citations.py reports those; write them out in
    full instead (that is what caught six of them on the M1y rung).

Keys are processed from the BOTTOM of the file up.  Going the other way, a key
moved by +d can land on a key not yet processed and the second pass moves both.
"""
import difflib, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.dirname(os.path.dirname(HERE))
CHECKER_PATH = os.path.join(HERE, 'check_citations.py')


def pairs_from_argv():
    """--old NAME=PATH ...  NAME is the citation's file name, as PATHS spells it"""
    import importlib.util
    spec = importlib.util.spec_from_file_location('cc', CHECKER_PATH)
    cc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cc)
    out = {}
    for i, a in enumerate(sys.argv):
        if a != '--old':
            continue
        name, _, old = sys.argv[i + 1].partition('=')
        if name not in cc.PATHS:
            sys.exit('reaim_diff: %s is not a name check_citations knows' % name)
        out[name] = (old, os.path.normpath(os.path.join(cc.UP, cc.PATHS[name])))
    if not out:
        sys.exit(__doc__)
    return out

def linemap(oldp, newp):
    """old 1-based line -> new 1-based line, or None where the line was deleted"""
    o = open(oldp, errors='replace').read().split('\n')
    n = open(newp, errors='replace').read().split('\n')
    m = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, o, n, autojunk=False).get_opcodes():
        if tag == 'equal':
            for k in range(i2 - i1):
                m[i1 + k + 1] = j1 + k + 1
        else:
            for k in range(i1, i2):
                m[k + 1] = None
    return m

def main():
    write = '--write' in sys.argv
    maps = {f: linemap(*p) for f, p in pairs_from_argv().items()}
    checker = CHECKER_PATH
    src = open(checker).read()
    docs = [os.path.join(P, 'docs', f) for f in sorted(os.listdir(os.path.join(P, 'docs')))
            if f.endswith('.md')] + [os.path.join(P, 'ANALYSIS.md')]
    text = {d: open(d).read() for d in docs if os.path.exists(d)}

    moved, gone = 0, []
    for fn, m in sorted(maps.items()):
        for a, b in sorted({(int(x), int(y)) for x, y in
                            re.findall(r"\('%s', (\d+), (\d+)\)" % re.escape(fn), src)},
                           reverse=True):    # bottom up: see the docstring
            na, nb = m.get(a), m.get(b)
            if na is None or nb is None:
                gone.append('%s:%d-%d: a cited line no longer exists -- open it' % (fn, a, b))
                continue
            if (na, nb) == (a, b):
                continue
            okey, nkey = "('%s', %d, %d)" % (fn, a, b), "('%s', %d, %d)" % (fn, na, nb)
            old_named = '`%s:%d-%d`' % (fn, a, b) if a != b else '`%s:%d`' % (fn, a)
            new_named = '`%s:%d-%d`' % (fn, na, nb) if na != nb else '`%s:%d`' % (fn, na)
            hits = sum(t.count(old_named) for t in text.values())
            src = src.replace(okey, nkey)
            for d in list(text):
                text[d] = text[d].replace(old_named, new_named)
            print('  %-12s %d-%d -> %d-%d   (%d in the documents)' % (fn, a, b, na, nb, hits))
            moved += 1
    if write:
        open(checker, 'w').write(src)
        for d, t in text.items():
            open(d, 'w').write(t)
    for g in gone:
        print('  LEFT ALONE  %s' % g)
    print('reaim_diff: %d moved%s, %d left for a human'
          % (moved, '' if write else ' (dry run)', len(gone)))
    return 0

sys.exit(main())
