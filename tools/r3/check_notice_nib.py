#!/usr/bin/env python3
"""H7 of docs/R3_MULTIMODE_PLAN.md 26-3: a derived nib in the tree must be on
the record in NOTICE and docs/R0_4_LICENSES.md (25-10).

  check_notice_nib.py        check the tree, then show the check can fail

The inspector nib is built from Configure.app's own.  NOTICE used to say that
nothing third-party was in the repository; with the nib that sentence would be
false.  So: if OSRDNDisplay/English.lproj/DisplayInspector.nib exists, NOTICE
must carry the "Configure inspector nib" paragraph naming the build script,
must no longer claim that no third-party data is copied, and the licence table
must have its row.  The stock nib itself must not be in the tree outside build/.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
NIB = os.path.join(PROJ, 'OSRDNDisplay', 'English.lproj', 'DisplayInspector.nib')
HEADING = '## Configure inspector nib -- derived from a stock OPENSTEP resource'
OLD_CLAIM = 'No third-party code, microcode or data is copied into this repository yet.'


def check(nib_present, notice, licenses):
    p = []
    if not nib_present:
        return p
    if HEADING not in notice:
        p.append('NOTICE has no "%s" paragraph' % HEADING[3:])
    elif 'tools/r3/build-inspector-nib.py' not in notice.split(HEADING, 1)[1].split('\n## ', 1)[0]:
        p.append('the NOTICE paragraph does not name tools/r3/build-inspector-nib.py')
    if OLD_CLAIM in notice:
        p.append('NOTICE still says no third-party data is copied')
    if 'Configure.app `DisplayInspector.nib`' not in licenses:
        p.append('docs/R0_4_LICENSES.md has no row for the stock nib')
    return p


def stray_stock_nibs():
    """A copy of the stock nib anywhere in the tree but build/."""
    out = []
    for dirpath, dirnames, filenames in os.walk(PROJ):
        rel = os.path.relpath(dirpath, PROJ)
        if rel.split(os.sep)[0] in ('build', '.git'):
            dirnames[:] = []
            continue
        if 'data.classes' in filenames:
            text = open(os.path.join(dirpath, 'data.classes')).read()
            if 'IODisplayInspector = {' in text and 'OSRDNDisplayInspector = {' not in text:
                out.append(rel)
    return out


def main():
    notice = open(os.path.join(PROJ, 'NOTICE')).read()
    licenses = open(os.path.join(PROJ, 'docs', 'R0_4_LICENSES.md')).read()
    fails = 0
    base = check(os.path.isdir(NIB), notice, licenses) + \
        ['a stock nib copy at %s' % d for d in stray_stock_nibs()]
    for x in base:
        print('  FAIL %s' % x)
    print('  %-4s the derived nib is on the record (nib present: %s)'
          % ('FAIL' if base else 'ok', os.path.isdir(NIB)))
    fails += len(base)
    section = notice.split(HEADING, 1)[1].split('\n## ', 1)[0] if HEADING in notice else ''
    negatives = [
        ('the paragraph removed', notice.replace(HEADING, '## Something else'), licenses),
        ('the paragraph without the script', notice.replace(section, section.replace(
            'tools/r3/build-inspector-nib.py', 'a script')), licenses),
        ('the old claim put back', notice + '\n' + OLD_CLAIM + '\n', licenses),
        ('the licence row removed', notice, licenses.replace('Configure.app `DisplayInspector.nib`', 'x')),
    ]
    for label, n, l in negatives:
        caught = bool(check(True, n, l))
        print('  %-4s negative: %s' % ('ok' if caught else 'FAIL', label))
        fails += 0 if caught else 1
    print('check_notice_nib: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
