#!/usr/bin/env python3
"""Refuse a citation of a source this project does not trust (operator, 2026-09-16).

  check_sources.py            scan this project; exit 1 on any hit
  check_sources.py --self-test

`openstep-kernel-remade/` is an unfinished reconstruction: its decompilation is
not settled, so nothing here may rest on it.  Driver evidence comes from the
machine's own binaries, the mirror ref/openstep (headers, stock driver bundles
and their relocs, NextDeveloper Makefiles, NeXT documentation), this
workspace's doc/driverkit.md, the openstep-matrox-remade project, and
measurements taken on the machine.

What is refused, in the files this project reasons from:

  * the path `openstep-kernel-remade/`, `full-pass...`, `whole-program.asm`,
    `symbols.tsv` -- citations OF that project
  * a decompiled function file name: eight hex digits and `.c`/`.asm`
    (`001c3cdc.c`), and Ghidra's `FUN_00xxxxxx`

The bare project NAME in prose is allowed, so that a document can say it is
not a source.  docs/review/ is excluded: those files are the transcripts of
cross-reviews as they happened, and rewriting them would falsify the record.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
BAN = re.compile(r'openstep-kernel-remade/|full-pass|whole-program\.asm|symbols\.tsv'
                 r'|\b00[0-9a-f]{6}\.(?:c|asm)\b|\bFUN_00[0-9a-f]{6}\b')
EXTS = ('.md', '.py', '.sh', '.m', '.h', '.c', '.table', '.txt')
SKIP_DIRS = ('build', 'docs/review', '.git', '__pycache__', 'ref')


def hits(root=PROJ):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        rel = '' if rel == '.' else rel
        if any(rel == s or rel.startswith(s + os.sep) for s in SKIP_DIRS):
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames
                       if not any(os.path.join(rel, d).replace(os.sep, '/') == s for s in SKIP_DIRS)]
        for fn in sorted(filenames):
            if not fn.endswith(EXTS):
                continue
            p = os.path.join(dirpath, fn)
            if os.path.abspath(p) == os.path.abspath(__file__):
                continue            # this file must hold the patterns it refuses
            try:
                text = open(p, encoding='utf-8', errors='replace').read()
            except OSError:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if BAN.search(line):
                    out.append((os.path.relpath(p, root), n, line.strip()[:110]))
    return out


def self_test():
    bad = 0
    for probe in ('see openstep-kernel-remade/04_ghidra/x', 'decompiled 001c3cdc.c 12-18',
                  'full-pass5 functions', 'whole-program.asm 4321', 'symbols.tsv line 9',
                  'FUN_001a5220 does it'):
        if not BAN.search(probe):
            print('  FAIL the rule misses %r' % probe)
            bad += 1
    for ok in ('openstep-kernel-remade is not a source', 'the file 001c3cdc is not named here',
               'ref/openstep/drivers/Drivers/i386/PCIBus.config/PCIBus_reloc', 'doc/driverkit.md:155'):
        if BAN.search(ok):
            print('  FAIL the rule fires on %r' % ok)
            bad += 1
    print('  %s source-rule self-test' % ('ok  ' if not bad else 'FAIL'))
    return bad


def main():
    if '--self-test' in sys.argv:
        return 1 if self_test() else 0
    bad = self_test()
    found = hits()
    for rel, n, line in found:
        print('  FAIL %s:%d cites a source this project does not trust: %s' % (rel, n, line))
    if not found:
        print('  ok   no file cites openstep-kernel-remade (docs/review is the archive and is skipped)')
    return 1 if (found or bad) else 0


if __name__ == '__main__':
    sys.exit(main())
