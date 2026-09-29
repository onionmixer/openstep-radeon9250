#!/usr/bin/env python3
"""
kernel_symbols.py -- read the exported symbols out of an OPENSTEP kernel.

Why this exists.  A module that compiles is not a module that loads.  NeXT
cc does not warn about an implicit declaration, so a macro used without
its header becomes a call to a function nobody defines, `make` returns 0,
and the failure appears only after a reboot as "server won't link".  That
has cost this project a boot before.

kext/symcheck.sh answers the same question on the target.  This answers it
here, from the kernel image in the local mirror, so the answer arrives
before the reboot rather than after it.

Linux `nm` does not read NeXT Mach-O, so the symbol table is parsed
directly: LC_SYMTAB gives the nlist array and the string table, and an
external, defined symbol is one with N_EXT set and a type other than
N_UNDF.

    kernel_symbols.py <mach_kernel> [--list]
    kernel_symbols.py <mach_kernel> --check sym [sym ...]
"""

import struct
import sys

MH_MAGIC = 0xFEEDFACE
LC_SYMTAB = 0x02

N_STAB = 0xE0
N_TYPE = 0x0E
N_EXT = 0x01
N_UNDF = 0x00


def load_symbols(path):
    """Every externally visible, defined symbol, as a set of names."""
    d = open(path, "rb").read()
    magic = struct.unpack_from("<I", d, 0)[0]
    if magic != MH_MAGIC:
        raise SystemExit("%s: not a 32-bit little-endian Mach-O (magic %08x)"
                         % (path, magic))
    # mach_header: magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds,
    #              flags
    ncmds = struct.unpack_from("<I", d, 16)[0]
    off = 28
    syms = set()
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", d, off)
        if cmd == LC_SYMTAB:
            symoff, nsyms, stroff, strsize = struct.unpack_from("<IIII",
                                                                d, off + 8)
            strtab = d[stroff:stroff + strsize]
            for i in range(nsyms):
                n_strx, n_type, n_sect, n_desc, n_value = struct.unpack_from(
                    "<IBBhI", d, symoff + i * 12)
                if n_type & N_STAB:
                    continue                    # debug entry, not a symbol
                if not (n_type & N_EXT):
                    continue                    # not visible outside
                if (n_type & N_TYPE) == N_UNDF:
                    continue                    # referenced, not defined
                end = strtab.find(b"\0", n_strx)
                name = strtab[n_strx:end].decode("ascii", "replace")
                if name:
                    syms.add(name)
        off += cmdsize
    if not syms:
        raise SystemExit("%s: no symbol table found" % path)
    return syms


def load_undefined(path):
    """Every symbol the file asks somebody else to provide.

    The mirror of load_symbols, and the half that was missing.  A kernel
    module is checked by asking whether everything it references exists
    in the kernel; that question needs the module's UNDEFINED list, and
    Linux nm cannot read NeXT Mach-O either.  The names come back in
    Mach-O form (a leading underscore on C names, and .objc_class_name_X
    for a class reference), which is the same form load_symbols returns,
    so the two sets compare directly with no fixing up.
    """
    d = open(path, "rb").read()
    magic = struct.unpack_from("<I", d, 0)[0]
    if magic != MH_MAGIC:
        raise SystemExit("%s: not a 32-bit little-endian Mach-O (magic %08x)"
                         % (path, magic))
    ncmds = struct.unpack_from("<I", d, 16)[0]
    off = 28
    syms = set()
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", d, off)
        if cmd == LC_SYMTAB:
            symoff, nsyms, stroff, strsize = struct.unpack_from("<IIII",
                                                                d, off + 8)
            strtab = d[stroff:stroff + strsize]
            for i in range(nsyms):
                n_strx, n_type, n_sect, n_desc, n_value = struct.unpack_from(
                    "<IBBhI", d, symoff + i * 12)
                if n_type & N_STAB:
                    continue
                if not (n_type & N_EXT):
                    continue
                if (n_type & N_TYPE) != N_UNDF:
                    continue                    # defined here, not asked for
                if n_value != 0:
                    continue                    # a COMMON: N_UNDF with a
                    # size is a tentative definition (an uninitialised
                    # global), not a reference.  Counting them made this
                    # reader disagree with the target's own nm -u by 14
                    # names, one of which looked alarmingly like a real
                    # missing symbol.
                end = strtab.find(b"\0", n_strx)
                name = strtab[n_strx:end].decode("ascii", "replace")
                if name:
                    syms.add(name)
        off += cmdsize
    return syms


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    syms = load_symbols(argv[1])
    if "--list" in argv:
        for s in sorted(syms):
            print(s)
        return 0
    if "--check" in argv:
        wanted = argv[argv.index("--check") + 1:]
        missing = [w for w in wanted if w not in syms]
        for w in wanted:
            print("%-40s %s" % (w, "in kernel" if w in syms else "MISSING"))
        return 1 if missing else 0
    print("%d exported symbols" % len(syms))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
