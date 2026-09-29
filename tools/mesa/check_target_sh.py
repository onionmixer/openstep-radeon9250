#!/usr/bin/env python3
"""One measured trap of the target's /bin/sh, enforced over every script we send it.

  check_target_sh.py

MEASURED on the target (globprobe2.sh, five forms in one run):

    for f in $PROJ/mesa/*.c        7 files
    for f in "$PROJ"/mesa/*.c      1 -- the literal string
    for f in $D/*.c                7 files
    for f in /ndrv/.../mesa/*.c    7 files
    for f in "/ndrv/..."/mesa/*.c  1 -- the literal string

So it is not about VARIABLES: this shell does not expand a glob in a word that
carries ANY quoted part, even when the quotes are around a constant.  Host
shells expand all five, which is why the rule cannot be found by running the
script here -- it cost a target round trip to find the first time.

A glob that does not expand does not fail.  It hands the loop one string that
looks like a path, and what happens next depends on what the body does with it.
Ours said "*.c is in mesa/ but was never compiled".

Scanned: every .sh in the project that mentions /ndrv, which is what makes a
script one the target runs.
"""

import shutil
import atexit
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))


def target_scripts():
    out = []
    for root, dirs, files in os.walk(PROJ):
        dirs[:] = [d for d in dirs if d not in ('.git', 'ref', 'build')]
        for f in sorted(files):
            if not f.endswith('.sh'):
                continue
            p = os.path.join(root, f)
            try:
                if '/ndrv' in open(p, errors='replace').read():
                    out.append(p)
            except OSError:
                pass
    return sorted(out)


def offenders(text):
    """[(line number, word)] -- words with a glob OUTSIDE quotes and a quote in them"""
    bad = []
    for n, ln in enumerate(text.split('\n'), 1):
        if ln.lstrip().startswith('#'):
            continue
        # walk the line character by character: only an unquoted * or ? globs,
        # and only a quote in the SAME word disables it
        word, quoted, glob, q = '', False, False, None

        def flush(word, quoted, glob, delim):
            # A word ended by ')' is a CASE PATTERN, and case matching is not
            # filename expansion in any sh: `*" DONE"*)` matches the literal
            # space-D-O-N-E and is meant to.  tools/r1c/target-r1c.sh 95 is that
            # and is correct, so the rule is narrowed rather than dropped -- a
            # rule with one standing exception stops being read.
            if quoted and glob and delim != ')':
                bad.append((n, word))
        for ch in ln + ' ':
            if q:
                word += ch
                if ch == q:
                    q = None
                continue
            if ch in '"\'':
                q = ch
                quoted = True
                word += ch
                continue
            if ch in ' \t;|&()':
                flush(word, quoted, glob, ch)
                word, quoted, glob = '', False, False
                continue
            if ch in '*?':
                glob = True
            word += ch
        flush(word, quoted, glob, ' ')
    return bad


def check(paths):
    p = []
    for path in paths:
        for n, word in offenders(open(path, errors='replace').read()):
            p.append('%s:%d a glob in a word that is partly quoted (%s) -- this '
                     'shell leaves it literal' % (os.path.relpath(path, PROJ), n, word))
    return p


MUTATIONS = [
    ('a quoted variable in front of a glob', 'for f in $PROJ/mesa/*.c; do',
     'for f in "$PROJ"/mesa/*.c; do'),
    ('a quoted constant in front of a glob', 'for f in $PROJ/mesa/*.c; do',
     'for f in "/ndrv/openstep-radeon9250"/mesa/*.c; do'),
]
MUTATED = os.path.join(PROJ, 'tools', 'mesa', 'target-build-mesa.sh')


def main():
    paths = target_scripts()
    bad = check(paths)
    for s in bad:
        print('  FAIL %s' % s)
    fails = 1 if bad else 0
    if not bad:
        print('  ok   %d target scripts, no glob disabled by a quote' % len(paths))

    src = open(MUTATED).read()
    import tempfile
    for label, old, new in MUTATIONS:
        if src.count(old) != 1:
            print('  FAIL mutation %-40s anchor found %d times' % (label, src.count(old)))
            fails += 1
            continue
        d = tempfile.mkdtemp()
        atexit.register(shutil.rmtree, d, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
        f = os.path.join(d, 'm.sh')
        open(f, 'w').write(src.replace(old, new, 1))
        caught = bool(check([f]))
        print('  %-4s mutation %-40s %s' % ('ok' if caught else 'FAIL', label,
                                            'caught' if caught else 'NOT CAUGHT'))
        if not caught:
            fails += 1
        os.unlink(f)
        os.rmdir(d)
    print('check_target_sh: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
