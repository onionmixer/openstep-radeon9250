#!/usr/bin/env python3
"""
check_symbols.py -- do the module's undefined symbols exist in the kernel?

Copied from openstep-mdh10/hosttest/check_symbols.py and given a
--prefix option: the original hard-codes `mdfs_` as the name prefix of
the module's own functions, so calling it by path from another project
would check that project's internal calls against the KERNEL and report
every one of them missing -- or, worse, report one present if the kernel
happened to export a name like it.  (codex Q2 on PLAN_STAGE0.)

Two questions:

  - a name that is not the module's own has to come from the kernel, and
    one that is not there is a load that fails after a reboot rather
    than a build that fails now;
  - a name that IS the module's own has to be defined by an object that
    is actually in the build.

Mach-O prefixes C names with an underscore and ELF does not, so the
comparison adds one.  Objective-C class references appear in ELF as
.objc_class_name_X and in the kernel the same way, so they compare
directly.

    check_symbols.py <mach_kernel> <undef.txt> [defined.txt] [--prefix P]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kernel_symbols import load_symbols          # noqa: E402


def main(argv):
    prefix = "emu_"
    if "--prefix" in argv:
        i = argv.index("--prefix")
        prefix = argv[i + 1]
        del argv[i:i + 2]
    if len(argv) < 3:
        sys.stderr.write("usage: check_symbols.py <mach_kernel> <undef.txt> "
                         "[defined.txt] [--prefix P]\n")
        return 2
    kern = load_symbols(argv[1])
    undef = [l.strip() for l in open(argv[2]) if l.strip()]
    have = set()
    if len(argv) >= 4 and os.path.exists(argv[3]):
        have = set(l.strip() for l in open(argv[3]) if l.strip())

    ours = [s for s in undef if s.startswith(prefix)]
    ext = [s for s in undef
           if not s.startswith(prefix) and s != "_GLOBAL_OFFSET_TABLE_"]

    def in_kernel(s):
        if s.startswith(".objc_"):
            return s in kern
        return ("_" + s) in kern

    missing = [s for s in ext if not in_kernel(s)]
    unresolved = [s for s in ours if s not in have] if have else []

    print("  %d symbols resolved inside the module, %d asked of the kernel"
          % (len(ours) - len(unresolved), len(ext)))
    for s in sorted(ext):
        print("  %-8s %s" % ("MISSING" if s in missing else "ok", s))
    for s in unresolved:
        print("  *** %s is the module's own and NOTHING IN THE BUILD "
              "DEFINES IT ***" % s)
    if missing or unresolved:
        if unresolved:
            print("  (a source file is missing from the module's list; the "
                  "module would not link)")
        return 1
    if not have:
        print("  (no defined-symbol list given; the module's own names "
              "were not checked)")
    print("  all %d kernel symbols exist" % len(ext))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
