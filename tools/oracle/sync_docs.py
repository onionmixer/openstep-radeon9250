#!/usr/bin/env python3
"""Keep generated blocks in the documents equal to their generators.

  sync_docs.py            check every block, exit 1 if one differs
  sync_docs.py --write    regenerate every block in place
  sync_docs.py --self-test

A block is

  <!-- BEGIN <script> <args> (generated; do not edit) -->
  ...
  <!-- END <script> -->

and its content must be exactly the output of `python3 tools/oracle/<script> <args>`
(or `python3 tools/<script> <args>` when <script> contains a slash, e.g. r1/closes.py).
Documents searched: *.md in the project root and docs/.  A marker pair with
no matching END, or a script that fails, is a failure; so is finding no
block at all (the check would otherwise pass on nothing).
"""

import glob
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
BLOCK = re.compile(r'(<!-- BEGIN (\S+)((?: [^()\n]+?)?) \(generated; do not edit\) -->\n)(.*?)(<!-- END \2 -->)', re.S)
BEGIN = re.compile(r'<!-- BEGIN (\S+)')


def documents():
    return sorted(glob.glob(os.path.join(PROJ, '*.md')) + glob.glob(os.path.join(PROJ, 'docs', '*.md')))


def generate(script, args):
    # a bare name is in tools/oracle; a name with a slash is relative to tools/
    path = os.path.join(os.path.dirname(HERE), script) if '/' in script else os.path.join(HERE, script)
    r = subprocess.run([sys.executable, path] + args.split(),
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('%s %s failed: %s' % (script, args, r.stderr.strip()[-300:]))
    return r.stdout if r.stdout.endswith('\n') else r.stdout + '\n'


def process(path, write):
    text = open(path).read()
    problems = []
    blocks = list(BLOCK.finditer(text))
    if len(blocks) != len(BEGIN.findall(text)):
        problems.append('%s: a BEGIN marker has no matching END' % path)
    new = text
    for m in reversed(blocks):
        script, args, body = m.group(2), m.group(3).strip(), m.group(4)
        try:
            want = generate(script, args)
        except RuntimeError as e:
            problems.append(str(e))
            continue
        if body != want:
            if write:
                new = new[:m.start(4)] + want + new[m.end(4):]
            else:
                problems.append('%s: block from %s %s is stale' % (os.path.relpath(path, PROJ), script, args))
    changed = write and new != text
    if changed:
        open(path, 'w').write(new)
    return len(blocks), problems, changed


def main(argv):
    if argv[1:] == ['--self-test']:
        return self_test()
    write = argv[1:] == ['--write']
    total = 0
    problems = []
    for d in documents():
        n, p, changed = process(d, write)
        total += n
        problems += p
        if n:
            print('  %-40s %d block(s)%s' % (os.path.relpath(d, PROJ), n, ' rewritten' if changed else ''))
    if total == 0:
        problems.append('no generated block found in any document')
    for p in problems:
        print('FAIL', p)
    print('sync_docs:', 'PASS' if not problems else 'FAIL (%d)' % len(problems))
    return 1 if problems else 0


def self_test():
    bad = 0
    with tempfile.TemporaryDirectory() as t:
        gen = os.path.join(HERE, '_sync_selftest_gen.py')
        open(gen, 'w').write('import sys\nprint("line one")\nprint("args", " ".join(sys.argv[1:]))\n')
        try:
            doc = os.path.join(t, 'd.md')
            good = ('x\n<!-- BEGIN _sync_selftest_gen.py --markdown (generated; do not edit) -->\n'
                    'line one\nargs --markdown\n<!-- END _sync_selftest_gen.py -->\ny\n')
            cases = [
                ('fresh block', good, 0),
                ('edited block', good.replace('line one', 'line 1'), 1),
                ('missing END', good.replace('<!-- END _sync_selftest_gen.py -->', ''), 1),
            ]
            for label, text, want in cases:
                open(doc, 'w').write(text)
                n, p, _ = process(doc, False)
                ok = (len(p) > 0) == bool(want)
                print('%-4s %s (%d problem)' % ('ok' if ok else 'FAIL', label, len(p)))
                bad += 0 if ok else 1
            open(doc, 'w').write(good.replace('line one', 'stale'))
            process(doc, True)
            n, p, _ = process(doc, False)
            ok = not p and 'line one' in open(doc).read()
            print('%-4s --write repairs a stale block' % ('ok' if ok else 'FAIL'))
            bad += 0 if ok else 1
        finally:
            os.unlink(gen)
    print('sync_docs self-test:', 'PASS' if bad == 0 else 'FAIL (%d)' % bad)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
