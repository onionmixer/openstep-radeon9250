#!/usr/bin/env python3
"""Port instructions and MMIO helper widths in the target-built OSRDNDisplay reloc (docs/R2B0_IMPL_PLAN.md 6-4).

  check_reloc_r2b0.py <reloc> <sum> <blocks> [--marker DIR]
        check the file's BSD sum, parse the Mach-O and require:
          - R2a's helper store widths (tools/r2a/check_reloc.py check())
          - port instructions (in, out, ins*, outs*, any form) only in
            _osrdn_inb "in (%dx),%al", _osrdn_inl "in (%dx),%eax",
            _osrdn_outb "out %al,(%dx)", _osrdn_outl "out %eax,(%dx)", exactly
            one each, and none in any other range
          - no indirect jump (jmp *) in any range
          - no byte of __text outside every symbol range other than 00 or 90
          - every call to an audited hardware helper (the two MMIO writers,
            the MMIO reader and the four port functions) comes from a range
            on CALL_WANT's list for that helper
        on PASS write DIR/R2B0RELOC_PASS holding "<sum> <blocks>"
  check_reloc_r2b0.py --self-test

Each code-symbol range is disassembled on its own.  A single linear sweep of
the whole __text is not used: on the R2a reloc that ran PASS it decodes two
false `in' instructions where zero padding between two functions throws the
sweep off (Q13 verdict 0-20).

The call rule is one-sided on purpose.  An EXTRA caller is the dangerous
case -- some new code reaching the hardware without going through the audited
helpers' callers -- so an unlisted caller fails.  A listed caller that makes
no call does not fail: cc 2.7.2.1 may fold or drop one, and that the calls
that must happen do happen is proved by the source rules and the simulators
(tools/r2b/check_r2b_src.py, sim_r2b.py), not by a disassembly.

A call whose displacement resolves to 0 is an external call the linker will
patch (IODelay, IOLog, ...) and is counted apart.  __text also starts at 0,
so a call to whatever sits there is indistinguishable from an unpatched one;
an audited helper landing at 0 is therefore refused rather than trusted.

What this cannot see: port access by the kernel itself (the PIT latch in
IOGetTimestamp, the PIC mask in spl), which is not in the reloc.
"""

import importlib.util
import shutil
import atexit
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


cr = _load('check_reloc_r2a_for_r2b0', os.path.join(PROJ, 'tools', 'r2a', 'check_reloc.py'))

PORT_WANT = {'_osrdn_inb': ['in (%dx),%al'], '_osrdn_inl': ['in (%dx),%eax'],
             '_osrdn_outb': ['out %al,(%dx)'], '_osrdn_outl': ['out %eax,(%dx)']}
PORT_RE = re.compile(r'^(rep[a-z]*\s+)?(in|out|ins[bwld]?|outs[bwld]?)\b')
IJMP_RE = re.compile(r'^(jmp|ljmp)[a-z]*\s+\*')
CALL_RE = re.compile(r'^call[a-z]*\s+(?:\*)?(?:0x)?([0-9a-f]+)$')

# Who may reach the hardware.  Read off the source: the mode module writes
# through osrdn_snap.m's accessors and nowhere else, its one direct use of a
# helper is the framebuffer test pattern, and the class file touches neither
# (docs/R2B_IMPL_PLAN.md 12-5, tools/r2b/check_r2b_src.py writes-through-accessors).
# R4 (docs/R4_ENGINE_PLAN.md 12, 13 #1 #4): the engine unit reaches its
# registers directly, and the read-only PLL peek selects and restores the index.
# R4c (docs/R4C_VMAP_PLAN.md 11-2): osrdn_engine_vram_reach reads MEMSIZE and
# APER_SIZE and writes nothing; osrdn_vmap_* reach no hardware at all.
ENGINE_CALLERS = ['_engCond', '_engWait', '_engLatch', '_engGate', '_engRecord', '_engDraw',
                  '_engClip', '_engFillBatch', '_engBlitBatch', '_osrdn_engine_run']
# R5 (docs/R5_PLAN.md 8): the CP unit reaches its registers directly; the MCLK
# pair and RECORD's PLL read use the index byte.
# M2a (docs/M2A_PLAN.md 4): cpSubmitFence is the SUBMISSION path's fence -- the
# same three steps as cpFence with the WBINVD behind a knob -- so it reads the
# same status register.  Naming it here is the point of this list: a new function
# that reaches the hardware has to be declared, not discovered.
CP_READERS = ['_cpCond', '_cpWait', '_cpLatch', '_cpMclkGet', '_cpFence', '_cpSubmitFence',
              '_cpIdleGate', '_cpMapGate', '_cpRecord',
              '_cpUnmap', '_cpMap', '_cpReset', '_cpStart', '_cpPoisonHolds', '_cpPrepare', '_cpReadBack', '_cpSubmit',
              '_cpNegctl', '_cpStopLatched', '_cpStop', '_osrdn_cp_run', '_osrdn_cp_quiesce',
              '_cpRec3d', '_cpZclear', '_cpR6Submit',     # R6a (docs/R6_PLAN.md 7)
              '_cpLatchDump', '_cpFail', '_cpResetPulse', '_cpStartCore',   # M3i/M3j: the latch dump and the reference recovery (docs/M3J_PLAN.md 6)
              # G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2): the space wait reads RPTR (inlined into cpR6Submit
              # when the compiler chooses), the accepted submission reads RPTR/REG5/SURFACE_CNTL, RETIRE waits
              '_cpWaitSpace', '_cpAsubmit', '_cpRetire']
CP_WRITERS = ['_cpMclkPut', '_cpLoad', '_cpUnmap', '_cpMap', '_cpReset', '_cpStart', '_cpPrepare', '_cpSubmit',
              '_cpNegctl', '_cpStopLatched', '_cpStop', '_osrdn_cp_run', '_osrdn_cp_quiesce',
              '_cpZclear', '_cpR6Submit',
              '_cpLatchDump',   # M3i: the CSQ_ADDR selector of the latch dump (docs/M3I_PLAN.md 3), the way r100.c 2977 reads the fifo
              '_cpFail', '_cpResetPulse', '_cpStartCore',   # M3j: CSQ off, the reset pulse, the pointers forced, the restart (docs/M3J_PLAN.md 5)
              '_cpRetire']      # G5-2: the pixel cache flush at the end of RETIRE (radeon_do_pixcache_flush)
CP_BYTE_WRITERS = ['_cpMclkGet', '_cpMclkPut', '_cpRecord', '_cpReset', '_osrdn_cp_run']
CALL_WANT = {
    '_rdnMmioRead32':  ['_pllGroup', '_recordRun', '_osrdn_mmio_get', '_osrdn_pll_get',
                        '_osrdn_snap_take', '_osrdn_peek', '_osrdn_palette_get',
                        '_osrdn_pll_peek', '_osrdn_engine_vram_reach'] + ENGINE_CALLERS + CP_READERS,
    '_rdnMmioWrite8':  ['_pllGroup', '_osrdn_pll_get', '_osrdn_pll_put', '_osrdn_snap_take',
                        '_osrdn_pll_peek'] + CP_BYTE_WRITERS,
    '_rdnMmioWrite32': ['_pllGroup', '_osrdn_mode_pattern', '_osrdn_mmio_put',
                        '_osrdn_palette_put', '_osrdn_pll_put', '_osrdn_snap_take',
                        '_osrdn_palette_get'] + ENGINE_CALLERS + CP_WRITERS,
    '_osrdn_inb':      ['_vgaSnapshot', '_vgaTake', '_osrdn_vga_put'],
    '_osrdn_outb':     ['_vgaSnapshot', '_vgaTake', '_osrdn_vga_put'],
    '_osrdn_inl':      ['_pciRead'],
    '_osrdn_outl':     ['_pciRead'],
}


# Edges that MUST be in the binary, not merely allowed.  CALL_WANT is one-sided
# (a listed caller that makes no call does not fail), so a new read path would
# otherwise pass even if it never reached the helper.  Only edges that cannot be
# folded away belong here: the caller and the callee are in different units.
CALL_REQUIRED = [
    ('_rdnMmioRead32', '_osrdn_peek'),      # docs/R2_CLOSEOUT.md 11: step 0 reads through it
    ('_rdnMmioRead32', '_osrdn_palette_get'),   # R3b-2: the LUT read-back (docs/R3_MULTIMODE_PLAN.md 23-9 T1)
    ('_rdnMmioRead32', '_osrdn_pll_peek'),  # R4: the clock words RECORD reads
    ('_rdnMmioWrite32', '_engDraw'),        # R4: the dest cache flushes
    ('_rdnMmioRead32', '_osrdn_engine_vram_reach'),  # R4c: MEMSIZE/APER for the gate and the registration
    ('_rdnMmioWrite32', '_cpLoad'),         # R5: the microcode
    ('_rdnMmioWrite8', '_cpMclkPut'),       # R5: the reset's MCLK_CNTL (index byte)
    ('_rdnMmioWrite32', '_cpStopLatched'),  # R5: the one write a latched CP gets
    ('_rdnMmioRead32', '_cpMapGate'),       # R5: every register MAP wrote, read back
    ('_rdnMmioRead32', '_cpRec3d'),         # R6a: REC3D reads the 3D and surface registers
    ('_rdnMmioWrite32', '_cpR6Submit'),     # R6a: the 3D stream's WPTR
    ('_rdnMmioWrite32', '_cpLatchDump'),    # M3i: CSQ_ADDR, 256 times, at a latch
    ('_rdnMmioWrite32', '_cpFail'),         # M3j: CSQ off and the pointers forced before the restart
    ('_rdnMmioWrite32', '_cpResetPulse'),   # M3j: the reset pulse, shared with cpReset
]


def call_check(ranges, decoded):
    """Return (report lines, failures) for calls into the audited helpers."""
    out, fail = [], []
    byaddr = dict((a, n) for n, (a, _) in ranges.items())
    made = {}
    external = 0
    for caller, insns in decoded.items():
        for addr, i in insns:
            m = CALL_RE.match(norm(i))
            if not m:
                continue
            target = int(m.group(1), 16)
            if target == 0:
                external += 1       # the linker patches it; __text starts at 0
                continue
            callee = byaddr.get(target)
            if callee is None:
                external += 1
                continue
            if callee not in CALL_WANT:
                continue
            made.setdefault(callee, {}).setdefault(caller, 0)
            made[callee][caller] += 1
            if caller not in CALL_WANT[callee]:
                fail.append('%s is called from %s at %08x, which is not on its list %s'
                            % (callee, caller, addr, CALL_WANT[callee]))
    for callee in sorted(CALL_WANT):
        if callee in ranges and ranges[callee][0] == 0:
            fail.append('%s sits at __text address 0, where an unpatched call also points:'
                        ' the call rule cannot see its callers' % callee)
        if callee not in ranges:
            fail.append('%s not in the symbol table' % callee)
            continue
        got = made.get(callee, {})
        out.append('  %-16s called %2d time(s) from %s' % (
            callee, sum(got.values()),
            ', '.join('%s x%d' % (c, n) for c, n in sorted(got.items())) or '(nothing)'))
    for callee, caller in CALL_REQUIRED:
        if callee in ranges and caller in ranges and not made.get(callee, {}).get(caller):
            fail.append('%s must call %s and does not' % (caller, callee))
        elif caller not in ranges and callee in CALL_WANT:
            # the R2b-0 reloc predates it; only a build that defines the caller is held to it
            out.append('  (required edge %s -> %s not checked: %s is not in this binary)'
                       % (caller, callee, caller))
    out.insert(0, 'calls into the audited helpers (%d external calls the linker patches):' % external)
    return out, fail


def norm(insn):
    return re.sub(r'\s+', ' ', insn.split('<')[0]).strip()


def port_check(data):
    """Return (report lines, failures)."""
    out, fail = [], []
    try:
        text, syms = cr.parse_macho(data)
    except (cr.MachOError, Exception) as e:
        return out, ['Mach-O: %s' % e]
    ranges = cr.function_ranges(text, syms)
    # Two code symbols with one name (two units' static functions) make the
    # ranges above -- keyed by name -- hide one of them, whose bytes then look
    # like code outside every symbol.  Say so by name (R4: elapsedUs was in
    # osrdn_record.m and osrdn_engine.m, docs/R4_ENGINE_PLAN.md 16).
    code_names = [n for n, t, sec, v in syms
                  if (t & cr.N_STAB) == 0 and (t & cr.N_TYPE) == cr.N_SECT and sec == text['ordinal']]
    for n in sorted(set(x for x in code_names if code_names.count(x) > 1)):
        fail.append('two code symbols are named %s: rename one (ranges are keyed by name)' % n)
    covered = sorted(ranges.values())
    base = text['addr']
    blob = data[text['offset']:text['offset'] + text['size']]
    # bytes outside every range
    pos = base
    gaps = []
    for a, b in covered:
        if a > pos:
            gaps.append((pos, a))
        pos = max(pos, b)
    if pos < base + text['size']:
        gaps.append((pos, base + text['size']))
    for a, b in gaps:
        bad = [x for x in blob[a - base:b - base] if x not in (0x00, 0x90)]
        if bad:
            fail.append('%d non-padding byte(s) outside every symbol range at %08x-%08x' % (len(bad), a, b))
    seen = dict((n, []) for n in PORT_WANT)
    total = 0
    decoded = {}
    for name, (a, b) in sorted(ranges.items(), key=lambda kv: kv[1]):
        insns = cr.disassemble(blob[a - base:b - base], a)
        decoded[name] = insns
        for addr, i in insns:
            n = norm(i)
            if PORT_RE.match(n):
                total += 1
                if name in PORT_WANT:
                    seen[name].append(n)
                else:
                    fail.append('port instruction %r at %08x in %s' % (n, addr, name))
            if IJMP_RE.match(n):
                fail.append('indirect jump %r at %08x in %s' % (n, addr, name))
    for name, want in PORT_WANT.items():
        if name not in ranges:
            fail.append('%s not in the symbol table' % name)
        elif seen[name] != want:
            fail.append('%s port instructions %s, want %s' % (name, seen[name], want))
    out.append('port instructions: %d in %d ranges; in the four port functions %s' % (
        total, len(ranges), dict((k, v) for k, v in seen.items())))
    o2, f2 = call_check(ranges, decoded)
    return out + o2, fail + f2


def check(data):
    out, fail = cr.check(data)
    o2, f2 = port_check(data)
    return out + o2, fail + f2


# ---- self-test ---------------------------------------------------------------

GOOD = """
.text
inb: push %ebp
 mov %esp,%ebp
 mov 0x8(%ebp),%edx
 in (%dx),%al
 leave
 ret
inl: push %ebp
 mov %esp,%ebp
 mov 0x8(%ebp),%edx
 in (%dx),%eax
 leave
 ret
outb: push %ebp
 mov %esp,%ebp
 mov 0x8(%ebp),%edx
 mov 0xc(%ebp),%eax
 out %al,(%dx)
 lock incl 0x2008
 leave
 ret
outl: push %ebp
 mov %esp,%ebp
 mov 0x8(%ebp),%edx
 mov 0xc(%ebp),%eax
 out %eax,(%dx)
 lock incl 0x2008
 leave
 ret
 .byte 0, 0, 0
other: push %ebp
 mov %esp,%ebp
 mov -0x75(%ebp),%eax
 leave
 ret
""" + cr.GOOD_ASM.replace('.text\n.globl w8\n', '')


def self_test():
    failures = 0

    def expect(label, ok, detail=''):
        nonlocal failures
        print('%-4s %s%s' % ('ok' if ok else 'FAIL', label, '' if ok else ' -- ' + detail))
        failures += 0 if ok else 1

    work = tempfile.mkdtemp(prefix='check_reloc_r2b0.', dir=os.environ.get('TMPDIR'))
    atexit.register(shutil.rmtree, work, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
    addr = 0x1000

    def build(src, extra=(), lead=None):
        code, lab = cr.assemble(src, work)
        names = [('_osrdn_inb', 'inb'), ('_osrdn_inl', 'inl'), ('_osrdn_outb', 'outb'), ('_osrdn_outl', 'outl'),
                 ('_other', 'other'), ('_rdnMmioRead32', 'r32'), ('_rdnMmioWrite8', 'w8'),
                 ('_rdnMmioWrite32', 'w32'), ('_tail', 'tail')]
        s = [(n, 0x0f, 1, lab[l] + addr) for n, l in names if l in lab] + list(extra)
        if lead is not None:
            s = [x for x in s if x[0] != lead]
        return cr.macho(code, s, addr), code, lab

    data, code, lab = build(GOOD)
    out, fail = check(data)
    expect('good reloc passes', not fail, str(fail))
    # the whole-text sweep hazard: padding 00 00 00 before `other', whose
    # `mov -0x75(%ebp)' starts 8b 45 8b: a sweep from the padding decodes an
    # `in' that is not there; the per-range scan must not report it
    sweep = cr.disassemble(code, addr)
    expect('a whole-text sweep of the good code misreads a port instruction (the hazard is real)',
           sum(1 for _, i in sweep if PORT_RE.match(norm(i))) > 4,
           str([i for _, i in sweep if PORT_RE.match(norm(i))]))
    data, _, _ = build(GOOD.replace(' mov -0x75(%ebp),%eax\n', ' mov -0x75(%ebp),%eax\n out %al,$0x80\n'))
    expect('immediate-port out in another function fails', any('in _other' in f for f in check(data)[1]))
    data, _, _ = build(GOOD.replace(' mov -0x75(%ebp),%eax\n', ' mov -0x75(%ebp),%eax\n outsb\n'))
    expect('outsb in another function fails', any("'outsb" in f or 'outsb' in f for f in check(data)[1]))
    data, _, _ = build(GOOD.replace(' mov -0x75(%ebp),%eax\n', ' mov -0x75(%ebp),%eax\n rep insl\n'))
    expect('rep insl in another function fails', any('insl' in f for f in check(data)[1]))
    data, _, _ = build(GOOD.replace(' out %eax,(%dx)\n', ' out %ax,(%dx)\n'))
    expect('66 ef (16-bit out) in _osrdn_outl fails', any('_osrdn_outl port' in f for f in check(data)[1]),
           str(check(data)[1]))
    data, _, _ = build(GOOD.replace(' out %al,(%dx)\n lock', ' out %al,(%dx)\n out %al,(%dx)\n lock'))
    expect('two outs in _osrdn_outb fails', any('_osrdn_outb port' in f for f in check(data)[1]))
    data, _, _ = build(GOOD.replace(' mov -0x75(%ebp),%eax\n', ' mov -0x75(%ebp),%eax\n jmp *%eax\n'))
    expect('indirect jump fails', any('indirect jump' in f for f in check(data)[1]))
    data, _, _ = build(GOOD, lead='_osrdn_inb')
    expect('bytes outside every range (first symbol dropped) fail',
           any('outside every symbol range' in f for f in check(data)[1]) and
           any('_osrdn_inb not in the symbol table' in f for f in check(data)[1]), str(check(data)[1]))
    data, _, _ = build(GOOD.replace(' mov -0x75(%ebp),%eax\n', ' mov -0x75(%ebp),%eax\n in $0x60,%al\n'))
    expect('immediate-port in fails', any('in _other' in f for f in check(data)[1]))

    # the call rule.  GOOD makes no call at all, so the good reloc also shows
    # the one-sided half: a listed caller that calls nothing does not fail.
    CALLS = GOOD.replace(' mov -0x75(%ebp),%eax\n', ' mov -0x75(%ebp),%eax\n call w32\n')
    data, _, _ = build(CALLS)
    expect('a call to _rdnMmioWrite32 from an unlisted range fails',
           any('_rdnMmioWrite32 is called from _other' in f for f in check(data)[1]),
           str(check(data)[1]))
    # the same call, from a range that IS on the list, passes
    _, _, lab = build(CALLS)
    data, _, _ = build(CALLS, extra=[('_osrdn_mmio_put', 0x0f, 1, lab['other'] + addr)],
                       lead='_other')
    expect('the same call from _osrdn_mmio_put passes',
           not [f for f in check(data)[1] if 'is called from' in f], str(check(data)[1]))
    # a required edge: _osrdn_peek is present but makes no call -> fail;
    # present and calling _rdnMmioRead32 -> pass
    _, _, lab = build(GOOD)
    data, _, _ = build(GOOD, extra=[('_osrdn_peek', 0x0f, 1, lab['other'] + addr)], lead='_other')
    expect('a defined _osrdn_peek that never reads fails',
           any('_osrdn_peek must call _rdnMmioRead32' in f for f in check(data)[1]), str(check(data)[1]))
    PEEKS = GOOD.replace(' mov -0x75(%ebp),%eax\n', ' mov -0x75(%ebp),%eax\n call r32\n')
    _, _, lab = build(PEEKS)
    data, _, _ = build(PEEKS, extra=[('_osrdn_peek', 0x0f, 1, lab['other'] + addr)], lead='_other')
    expect('_osrdn_peek calling _rdnMmioRead32 passes',
           not [f for f in check(data)[1] if 'peek' in f], str(check(data)[1]))
    data, _, _ = build(GOOD, extra=[('_other', 0x0e, 1, lab['other'] + addr)])
    expect('two code symbols with one name fail by name',
           any('two code symbols are named _other' in f for f in check(data)[1]), str(check(data)[1]))
    data, _, _ = build(CALLS.replace('call w32', 'call inb'), lead='_osrdn_inb')
    expect('a helper missing from the symbol table fails',
           any('_osrdn_inb not in the symbol table' in f for f in check(data)[1]))
    # __text at 0: _osrdn_inb lands there, so an unpatched call to 0 and a real
    # call to it look the same; the rule must refuse rather than trust
    code0, lab0 = cr.assemble(GOOD, work)
    s0 = [(n, 0x0f, 1, lab0[l]) for n, l in
          (('_osrdn_inb', 'inb'), ('_osrdn_inl', 'inl'), ('_osrdn_outb', 'outb'),
           ('_osrdn_outl', 'outl'), ('_other', 'other'), ('_rdnMmioRead32', 'r32'),
           ('_rdnMmioWrite8', 'w8'), ('_rdnMmioWrite32', 'w32'), ('_tail', 'tail')) if l in lab0]
    expect('an audited helper at __text address 0 fails',
           any('sits at __text address 0' in f for f in check(cr.macho(code0, s0, 0))[1]),
           str(check(cr.macho(code0, s0, 0))[1]))
    # the R2a reloc that ran PASS: its only port code is inline in _pciRead,
    # which this gate refuses (as it must for R2b-0), and the per-range scan
    # finds exactly the two real instructions and not the sweep's two false ones
    real = os.path.join(PROJ, 'build', 'r2a', '789467668', 'RDNR2aProbe_reloc')
    if os.path.exists(real):
        out, fail = port_check(open(real, 'rb').read())
        ports = [f for f in fail if f.startswith('port instruction')]
        expect('R2a reloc: per-range scan finds the 2 real port instructions in _pciRead only',
               len(ports) == 2 and all('_pciRead' in f for f in ports), str(ports))
    print('check_reloc_r2b0 self-test: %s' % ('PASS' if failures == 0 else 'FAIL (%d)' % failures))
    return failures == 0


def main(argv):
    if argv[1:] == ['--self-test']:
        return 0 if self_test() else 1
    a = argv[1:]
    marker = None
    if '--marker' in a:
        i = a.index('--marker')
        marker = a[i + 1]
        a = a[:i] + a[i + 2:]
    if len(a) != 3:
        print(__doc__)
        return 2
    path, want_sum, want_blocks = a
    data = open(path, 'rb').read()
    got = cr.pk.bsdsum(data)
    fail = []
    if not (want_sum.isdigit() and want_blocks.isdigit()) or \
            [int(x) for x in got.split()] != [int(want_sum), int(want_blocks)]:
        fail.append('BSD sum %s, the target reported %s %s' % (got, want_sum, want_blocks))
    out, f2 = check(data)
    fail += f2
    print('reloc %s: %d bytes, sum %s' % (path, len(data), got))
    for o in out:
        print(o)
    for f in fail:
        print('FAIL ' + f)
    ok = not fail
    if ok and marker:
        os.makedirs(marker, exist_ok=True)
        open(os.path.join(marker, 'R2B0RELOC_PASS'), 'w').write('%s %s\n' % tuple(got.split()))
        print('marker %s' % os.path.join(marker, 'R2B0RELOC_PASS'))
    print('check_reloc_r2b0: %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
