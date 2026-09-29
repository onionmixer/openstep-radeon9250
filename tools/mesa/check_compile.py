#!/usr/bin/env python3
"""Every C file we send the target compiles HERE first, as C89.

  check_compile.py

The target's cc is two hundred miles away behind a build script, and a missing
#include there costs a whole round trip to learn.  It cost one: M1g added
OSRDNMesaTex and the stock-link stub used OSRDN_TEX_H, which lives in the
GENERATED table and not in the unit header.  Nothing on the host compiled that
file, so nothing said so until the target's step 11.

Compiled with gcc -m32 -std=gnu89 -Wall -Werror, which is not the target's cc
but does catch an undeclared name, a missing include and a C99-ism.  -w is NOT
passed: it would suppress -Werror and the gate would pass by being silent
(recorded).

OSRDNMesaHook.c is the one unit that needs Mesa's INTERNAL headers (src/).  It
was left out while this machine had none; the sibling checkout now carries
upstream/Mesa-3.4.2/src, so since G4-2 B1 it IS compiled here -- at the host's
native width (its includes reach the system headers, and this host has no
32-bit libc headers), with OPENSTEP_MESA_ACCEL_HOOK defined as the target build
defines it.  A Driver hook whose signature drifts from dd.h is then a host
error, not a target one.  The test program needs only Mesa's public include/,
which the sibling checkout has, so it IS compiled here -- it was not, and that
was a hole: M1q edited it and nothing on the host would have seen a C99-ism
until the target's build.
"""

import shutil
import atexit
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
NEEDS_MESA = ('OSRDNMesaHook.c',)
# Mesa's PUBLIC headers -- GL/gl.h and GL/osmesa.h -- from the sibling checkout.
# Named, not searched: a wrong guess here would silently drop the test program
# from the gate, which is the hole this line closes.
MESA_INC = os.path.join(PROJ, '..', 'openstep-mesa342', 'upstream',
                        'Mesa-3.4.2', 'include')
MESA_SRC = os.path.join(PROJ, '..', 'openstep-mesa342', 'upstream',
                        'Mesa-3.4.2', 'src')
# The sweep program is the only source here that includes a SYSTEM header
# (<sys/time.h>), and this host has no 32-bit libc headers, so -m32 cannot
# reach it.  Width is not what this gate is for -- it looks for undeclared
# names, missing includes and C99-isms -- so that one file is compiled at the
# host's native width and the reason is written down rather than the file being
# dropped.
NO_M32 = ('test/osrdn-mesa-tri.c',)
# -Wdeclaration-after-statement is the one the target cares about most: cc
# 2.7.2.1 rejects a declaration after a statement outright (recorded), and
# gnu89 alone does not warn about it -- the mutation below proves it fires.
CC = ['gcc-12', '-m32', '-std=gnu89', '-fsyntax-only', '-Wall', '-Werror',
      '-Wdeclaration-after-statement', '-Wno-unused-function']


def sources():
    out = [os.path.join('mesa', f) for f in sorted(os.listdir(os.path.join(PROJ, 'mesa')))
           if f.endswith('.c') and f not in NEEDS_MESA]
    out.append(os.path.join('test', 'osrdn-mesa-nocount.c'))
    out.append(os.path.join('test', 'osrdn-mesa-tri.c'))
    return out


def compile_one(rel, override=None):
    """None when it compiles, else the first error line"""
    hook = os.path.basename(rel) in NEEDS_MESA
    cc = [a for a in CC if not (a == '-m32' and (rel in NO_M32 or hook))]
    args = cc + ['-I', os.path.join(PROJ, 'mesa'),
                 '-I', os.path.join(PROJ, 'OSRDNDisplay',
                                    'OSRDNDisplay_reloc.tproj'),
                 '-I', MESA_INC]
    if hook:
        args += ['-I', MESA_SRC, '-DOPENSTEP_MESA_ACCEL_HOOK']
    if override is None:
        args.append(os.path.join(PROJ, rel))
    else:
        args.append(override)
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode == 0:
        return None
    for ln in r.stderr.split('\n'):
        if ': error:' in ln or ': fatal error:' in ln:
            return ln.strip()
    return (r.stderr.strip().split('\n') or ['(no message)'])[0]


MUTATIONS = [
    ('the stub loses the generated table', 'test/osrdn-mesa-nocount.c',
     '#include "OSRDNMesaTriTable.h"', '/* removed */'),
    ('a statement before a declaration (C99)', 'mesa/OSRDNMesaTex.c',
     '    unsigned long need;', '    texCounts.uploads += 0; unsigned long need;'),
    # proves the test program is really in the loop, not just listed
    ('the sweep program is not compiled at all', 'test/osrdn-mesa-tri.c',
     '    int li, i, px;', '    int li, i;\n    glFlush();\n    int px;'),
    # G4-2 B1: and the hook unit -- a Driver hook with the wrong signature
    ('a pixel hook drifts from dd.h', 'mesa/OSRDNMesaHook.c',
     'static GLboolean\nosrdnHookBitmap(GLcontext *ctx, GLint x, GLint y, GLsizei width, GLsizei height,',
     'static GLboolean\nosrdnHookBitmap(GLcontext *ctx, GLint x, GLint y, GLsizei width,'),
    ('a statement before a declaration in the hook (C99)', 'mesa/OSRDNMesaHook.c',
     '    int slot;\n\n    /*\n     * M3g:', '    osrdnCounts.installs += 0;\n    int slot;\n\n    /*\n     * M3g:'),
]


def main():
    if subprocess.run(['which', 'gcc-12'], capture_output=True).returncode != 0:
        print('  --   gcc-12 not present, skipped')
        return 0
    fails = 0
    if not os.path.isdir(os.path.join(MESA_INC, 'GL')):
        print('  FAIL Mesa public headers are not at %s' % MESA_INC)
        return 1
    for rel in sources():
        e = compile_one(rel)
        if e:
            print('  FAIL %-34s %s' % (rel, e))
            fails += 1
    if not fails:
        print('  ok   %d sources compile as C89 with -Wall -Werror' % len(sources()))
    # G4-2 B1: the hook unit, against Mesa's internal headers
    if not os.path.isfile(os.path.join(MESA_SRC, 'dd.h')):
        print('  FAIL Mesa internal headers are not at %s' % MESA_SRC)
        fails += 1
    else:
        for name in NEEDS_MESA:
            rel = os.path.join('mesa', name)
            e = compile_one(rel)
            if e:
                print('  FAIL %-34s %s' % (rel, e))
                fails += 1
            else:
                print('  ok   %-34s compiles against Mesa src/ (native width)' % rel)

    work = tempfile.mkdtemp(prefix='chkcomp')
    atexit.register(shutil.rmtree, work, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
    for label, rel, old, new in MUTATIONS:
        src = open(os.path.join(PROJ, rel)).read()
        if src.count(old) != 1:
            print('  FAIL mutation %-38s anchor found %d times' % (label, src.count(old)))
            fails += 1
            continue
        f = os.path.join(work, os.path.basename(rel))
        open(f, 'w').write(src.replace(old, new, 1))
        caught = compile_one(rel, override=f) is not None
        print('  %-4s mutation %-38s %s' % ('ok' if caught else 'FAIL', label,
                                            'caught' if caught else 'NOT CAUGHT'))
        if not caught:
            fails += 1
        os.unlink(f)
    os.rmdir(work)
    print('check_compile: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
