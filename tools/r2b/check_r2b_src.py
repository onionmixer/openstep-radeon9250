#!/usr/bin/env python3
"""Pin the R2b invariants in the source text (docs/R2B_IMPL_PLAN.md 2, 7-2, 12).

  check_r2b_src.py            run every rule, then every mutation

A rule that no mutation can trip proves nothing, so each rule below carries at
least one mutation and both halves run in this one invocation.

The rules, and why each one exists:

  writes-through-accessors  every mode register write goes through
        osrdn_mmio_put / osrdn_pll_put / osrdn_palette_put / osrdn_vga_put,
        whose argument is an index into osrdn_snap's tables.  The only direct
        rdnMmio* call left is the framebuffer pattern, which writes no
        register.  Without this, "which registers does the entry write" stops
        being answerable by reading a table.
  entry-subset-revert       every register index the entry writes is also
        written by the revert.  This is the invariant the console's return
        rests on (12-5).
  enter-order               the entry calls its steps in the planned order,
        snapshot before any write.
  mode-written              modeWritten is set once, inside modeBlank, before
        that function's first write, and cleared once, at the end of the
        revert.
  revert-runs-through       the revert has no early return after its first
        write: stopping half way loses the console (plan 2-4).
  no-pvg                    no write to PPLL_CNTL carries the PVG field (12-1).
  refdiv-from-boot          PPLL_REF_DIV is only ever written with the value
        read from this boot, or with the atomic-update bit (plan 2-8).
  no-log                    neither file logs: the kernel VGA console owns the
        same I/O ports the snapshot reads (12-9).
  no-float-no-div64         no floating point, no 64-bit division (the kernel
        has neither), and no kilobyte array on the kernel stack.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
TPROJ = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj')
MODE = os.path.join(TPROJ, 'osrdn_mode.m')
SNAP = os.path.join(TPROJ, 'osrdn_snap.m')
MODESEL = os.path.join(TPROJ, 'osrdn_modesel.m')
CLASS = os.path.join(TPROJ, 'OSRDNDisplay.m')

ENTRY_STEPS = ['modeCheck', 'modeSnapshot', 'modeRow', 'modeBlank', 'modeCrtc', 'pllProgram',
               'modeFifo', 'modeDac', 'modePalette', 'osrdn_mode_pattern', 'modeUnblank',
               'modeVerify']


def blank(code):
    """comments and string literals out, so a rule never matches prose"""
    code = re.sub(r'/\*.*?\*/', lambda m: ' ' * len(m.group()), code, flags=re.S)
    code = re.sub(r'"(?:[^"\\\n]|\\.)*"', '""', code)
    return code


def bodies(code):
    """{function name: body text} for definitions at column 0"""
    out = {}
    for m in re.finditer(r'^(?:static\s+)?[A-Za-z_][\w \t*]*\n([A-Za-z_]\w*)\s*\(', code, re.M):
        start = code.find('{', m.end())
        if start < 0:
            continue
        depth, k = 0, start
        while k < len(code):
            if code[k] == '{':
                depth += 1
            elif code[k] == '}':
                depth -= 1
                if depth == 0:
                    break
            k += 1
        out[m.group(1)] = code[start:k + 1]
    return out


def puts(body):
    """the register indexes a body writes, as (kind, index name)"""
    found = []
    for m in re.finditer(r'osrdn_(mmio|pll)_put\s*\(\s*\w+\s*,\s*([A-Za-z_]\w*)', body):
        found.append((m.group(1), m.group(2)))
    if re.search(r'osrdn_palette_put\s*\(', body):
        found.append(('palette', 'PALETTE'))
    if re.search(r'osrdn_vga_put\s*\(', body):
        found.append(('vga', 'VGA'))
    return found


def rules(mode_text, snap_text, sel_text=None, class_text=None):
    r = {}
    if sel_text is None:
        sel_text = open(MODESEL, encoding='utf-8').read()
    if class_text is None:
        class_text = open(CLASS, encoding='utf-8').read()
    mode, snap, sel, cls = blank(mode_text), blank(snap_text), blank(sel_text), blank(class_text)

    # ---- the LIVE class file (tools/r2b0/check_r2b0_src.py reads the R2b-0
    #      archive): no hardware of its own, and every configuration string it
    #      reads is freed (docs/R3_MULTIMODE_PLAN.md 23-9 T1; NeXT's
    #      AMD_x86.m frees what valueForStringKey: returns)
    p = []
    for call in re.findall(r'\b(rdnMmio\w+|osrdn_(?:inb|inl|outb|outl|mmio_\w+|pll_\w+|palette_\w+|vga_\w+|peek|snap_take))\s*\(', cls):
        p.append('OSRDNDisplay.m calls %s' % call)
    reads = re.findall(r'(\w+)\s*=\s*\([^;]*?\)\s*\?\s*0\s*:\s*\[\s*\w+\s+valueForStringKey:', cls)
    frees = re.findall(r'\[\s*\w+\s+freeString:\s*(\w+)\s*\]', cls)
    if len(re.findall(r'valueForStringKey:', cls)) != len(reads):
        p.append('a valueForStringKey: result is not assigned in the checked form')
    if len(reads) != len(frees) or sorted(set(reads)) != sorted(set(frees)):
        p.append('%d configuration strings read (%s), %d freed (%s)' % (len(reads), reads, len(frees), frees))
    r['class-rules'] = p

    # ---- what the class publishes is the chosen row, field by field
    #      (docs/R3_MULTIMODE_PLAN.md 23-3, 23-12): nothing else on the host
    #      compares displayInfo with the oracle, and a wrong rowBytes would
    #      first show as a sheared desktop
    p = []
    flat = re.sub(r'\s+', ' ', cls)
    for stmt in ('info->width = res->width;', 'info->height = res->height;',
                 'info->totalWidth = res->width;', 'info->rowBytes = res->width * fmt->bytes;',
                 'info->refreshRate = 60;', 'info->bitsPerPixel = (IOBitsPerPixel)fmt->ioBpp;',
                 'info->colorSpace = (IOColorSpace)fmt->ioColorSpace;',
                 'info->pixelEncoding[k] = fmt->encoding[k];', 'info->flags = IO_DISPLAY_HAS_TRANSFER_TABLE;',
                 'info->memorySize = res->width * fmt->bytes * res->height;',
                 'info->dotClockRate = (int)res->dotClock;', 'info->screenWidth = res->width;',
                 'info->screenHeight = res->height;',
                 'osrdn_modesel_choose(key, OSRDN_FB_LENGTH, &sel);',
                 'rdnMode.res = sel.res;', 'rdnMode.fmt = sel.fmt;', 'rdnMode.selected = 1;',
                 'res = osrdn_res(sel.res);', 'fmt = osrdn_fmt(sel.fmt);',
                 'if (rdnMode.enterCount != ran && rdnMode.step >= 12) osrdn_verify_line(&rdnMode);',
                 'rdnMode.grayLevels = osrdn_modesel_gray(key, &grayRefused);',
                 'result = osrdn_mode_set_transfer(&rdnMode, [self lutBase], table, count);',
                 'result = osrdn_mode_set_brightness(&rdnMode, [self lutBase], level);',
                 'if (level < EV_SCREEN_MIN_BRIGHTNESS || level > EV_SCREEN_MAX_BRIGHTNESS) {',
                 'if (rdnMode.brightCalls <= OSRDN_BRIGHT_LINES) osrdn_bright_line(&rdnMode, level, result);',
                 'return (mmioMapped && rdnState.recordEnabled) ? mmioBase : 0;'):
        if flat.count(stmt) != 1:
            p.append('OSRDNDisplay.m has %r %d times, want once' % (stmt, flat.count(stmt)))
    fields = set(re.findall(r'\binfo->(\w+)', cls))
    want = {'width', 'height', 'totalWidth', 'rowBytes', 'refreshRate', 'frameBuffer', 'bitsPerPixel',
            'colorSpace', 'pixelEncoding', 'flags', 'memorySize', 'scanRate', 'dotClockRate',
            'screenWidth', 'screenHeight'}
    if fields != want:
        p.append('the class sets displayInfo fields %s, the plan lists %s' % (sorted(fields), sorted(want)))
    if len(re.findall(r'osrdn_verify_line\s*\(', cls)) != 1:
        p.append('osrdn_verify_line is called %d times' % len(re.findall(r'osrdn_verify_line\s*\(', cls)))
    r['class-displayinfo'] = p
    fn = bodies(mode)

    # ---- writes go through the accessors
    p = []
    for name, body in fn.items():
        if name == 'osrdn_mode_pattern':
            continue
        for call in re.findall(r'\b(rdnMmioWrite8|rdnMmioWrite32|osrdn_outb|osrdn_outl)\s*\(', body):
            p.append('%s calls %s directly' % (name, call))
    if len(re.findall(r'\brdnMmioWrite32\s*\(', fn.get('osrdn_mode_pattern', ''))) != 1:
        p.append('osrdn_mode_pattern must write the framebuffer exactly one way')
    r['writes-through-accessors'] = p

    # ---- the entry's write set is inside the revert's
    entry = set()
    for name in ('modeBlank', 'modeCrtc', 'pllProgram', 'modeFifo', 'modeDac', 'modePalette'):
        entry |= set(puts(fn.get(name, '')))
    revert = set(puts(fn.get('modeRevertBody', '')))
    revert |= set(puts(fn.get('pllProgram', '')))         # the revert calls it
    revert |= set(puts(fn.get('modePalette', '')))        # and it, with snapshot values
    missing = sorted(x for x in entry - revert)
    r['entry-subset-revert'] = ['the entry writes %s, the revert does not' % (x,) for x in missing]

    # ---- the order of the entry
    p = []
    body = fn.get('modeEnterBody', '')
    seen = [m for m in re.findall(r'\b([A-Za-z_]\w*)\s*\(', body) if m in ENTRY_STEPS]
    if seen != ENTRY_STEPS:
        p.append('entry calls %s, want %s' % (seen, ENTRY_STEPS))
    r['enter-order'] = p

    # ---- modeWritten
    p = []
    sets = re.findall(r'(\w+)->modeWritten\s*=\s*1', mode)
    clears = re.findall(r'(\w+)->modeWritten\s*=\s*0', mode)
    if len(sets) != 1 or len(clears) != 1:
        p.append('modeWritten set %d times and cleared %d, want 1 and 1' % (len(sets), len(clears)))
    blankBody = fn.get('modeBlank', '')
    if '->modeWritten = 1' not in blankBody:
        p.append('modeWritten is not set in modeBlank')
    else:
        first = min([blankBody.find('osrdn_mmio_put'), blankBody.find('osrdn_pll_put')]
                    if blankBody.find('osrdn_pll_put') >= 0 else [blankBody.find('osrdn_mmio_put')])
        if blankBody.find('->modeWritten = 1') > first:
            p.append('modeWritten is set after the first write in modeBlank')
    revertBody = fn.get('modeRevertBody', '')
    if '->modeWritten = 0' not in revertBody:
        p.append('modeWritten is not cleared in the revert')
    r['mode-written'] = p

    # ---- the revert runs through
    p = []
    body = revertBody
    firstWrite = body.find('osrdn_mmio_put')
    for m in re.finditer(r'\breturn\b', body):
        if firstWrite >= 0 and m.start() > firstWrite:
            p.append('the revert returns after it has begun writing')
            break
    r['revert-runs-through'] = p

    # ---- PVG
    p = []
    for m in re.finditer(r'osrdn_pll_put\s*\(\s*\w+\s*,\s*SNAP_PPLL_CNTL\s*,([^;]*);', mode):
        if '3800' in m.group(1) or 'PVG' in m.group(1):
            p.append('a PPLL_CNTL write carries the PVG field: %s' % m.group(1).strip()[:60])
    r['no-pvg'] = p

    # ---- PPLL_REF_DIV
    p = []
    for m in re.finditer(r'osrdn_pll_put\s*\(\s*\w+\s*,\s*SNAP_PPLL_REF_DIV\s*,([^;]*);', mode):
        val = m.group(1)
        if 'refdiv' not in val and 'ATOMIC_UPDATE' not in val:
            p.append('PPLL_REF_DIV written with %s' % val.strip()[:60])
    r['refdiv-from-boot'] = p

    # ---- logging
    p = []
    for name, text in (('osrdn_mode.m', mode), ('osrdn_snap.m', snap), ('osrdn_modesel.m', sel)):
        if re.search(r'\bIOLog\s*\(', text):
            p.append('%s logs' % name)
    r['no-log'] = p

    # ---- the selection unit is arithmetic on a string: no hardware, no
    #      sleeping, no libc, and none of the names cc 2.7.2.1 trips on
    #      (docs/R3_MULTIMODE_PLAN.md 23-2, 23-9 T1)
    p = []
    for call in re.findall(r'\b(rdnMmio\w+|osrdn_(?:inb|inl|outb|outl|mmio_\w+|pll_\w+|palette_\w+|vga_\w+|peek)'
                           r'|IOSleep|IODelay|IOMalloc|strstr|strcmp|strlen|sscanf|atoi|strtoul)\s*\(', sel):
        p.append('osrdn_modesel.m calls %s' % call)
    for m in re.finditer(r'\b(?:int|long|char|unsigned)\b[^;(){}]*?\b(in|out|id)\b\s*[,;=)\[]', sel):
        p.append('osrdn_modesel.m names a variable %s' % m.group(1))
    if re.search(r'\bswitch\s*\(', sel):
        p.append('osrdn_modesel.m uses switch')
    if re.search(r'\b(float|double)\b', sel):
        p.append('osrdn_modesel.m uses floating point')
    r['modesel-pure'] = p

    # ---- no float, no 64-bit divide, no big stack array
    p = []
    for name, text in (('osrdn_mode.m', mode), ('osrdn_snap.m', snap)):
        if re.search(r'\b(float|double)\b', text):
            p.append('%s uses floating point' % name)
        for m in re.finditer(r'\b(\w+)\s*/\s*', text):
            pass
        if re.search(r'ns_time_t\s+\w+\s*;[^}]*?/[^/=]', text):
            pass
        for m in re.finditer(r'^\s+(?:static\s+)?unsigned long\s+(\w+)\[(\d+)\]', text, re.M):
            if int(m.group(2)) >= 64 and 'static' not in m.group(0):
                p.append('%s puts %s[%s] on the stack' % (name, m.group(1), m.group(2)))
    r['no-float-no-div64'] = p

    # ---- the step-0 registers are read-only and kept apart (R2_CLOSEOUT 11)
    p = []
    sfn = bodies(snap)
    def table(name):
        m = re.search(r'osrdn_snap_reg\s+%s\s*\[[^\]]*\]\s*=\s*\{(.*?)\};' % name, snap_text, re.S)
        return [] if m is None else [int(x, 16) for x in re.findall(r'0x([0-9a-fA-F]+)\s*\}', m.group(1))]
    peekOff, snapOff = table('osrdnPeek'), table('osrdnSnapMmio')
    if not peekOff:
        p.append('no osrdnPeek table')
    for off in sorted(set(peekOff) & set(snapOff)):
        p.append('offset %04x is both a step-0 register and a snapshot register' % off)
    for name in ('osrdn_mmio_put', 'osrdn_pll_put', 'osrdn_palette_put', 'osrdn_vga_put'):
        if 'osrdnPeek' in sfn.get(name, ''):
            p.append('%s, a write accessor, uses the step-0 table' % name)
    body = sfn.get('osrdn_peek', '')
    if len(re.findall(r'\brdnMmioRead32\s*\(', body)) != 1:
        p.append('osrdn_peek must read exactly once')
    if re.search(r'\b(rdnMmioWrite8|rdnMmioWrite32|osrdn_outb|osrdn_outl)\s*\(', body):
        p.append('osrdn_peek writes')
    if 'osrdnPeek[' not in body:
        p.append('osrdn_peek does not read through its own table')
    r['peek-read-only'] = p

    # ---- the mode module reads hardware only through the accessors too
    p = []
    for name, b in fn.items():
        for call in re.findall(r'\b(rdnMmioRead32|osrdn_inb|osrdn_inl)\s*\(', b):
            p.append('%s calls %s directly' % (name, call))
    r['reads-through-accessors'] = p
    return r


MUTATIONS = [
    (SNAP, 'a step-0 register is also put in the snapshot table',
     '    { "DISP_MERGE_CNTL",       0x0d60 }\n};',
     '    { "DISP_MERGE_CNTL",       0x0d60 },\n    { "AIC_CNTL",              0x01d0 }\n};', ['peek-read-only']),
    (SNAP, 'a write accessor indexes the step-0 table',
     '    rdnMmioWrite32(base, osrdnSnapMmio[which].offset, value);',
     '    rdnMmioWrite32(base, osrdnPeek[which].offset, value);', ['peek-read-only']),
    (SNAP, 'the step-0 reader writes',
     '    return rdnMmioRead32(base, osrdnPeek[which].offset);',
     '    rdnMmioWrite32(base, osrdnPeek[which].offset, 0);\n    return rdnMmioRead32(base, osrdnPeek[which].offset);',
     ['peek-read-only']),
    (MODE, 'the mode module reads a register directly',
     '    v = osrdn_peek(base, PEEK_CONFIG_APER_SIZE);',
     '    v = rdnMmioRead32(base, 0x0108);', ['reads-through-accessors']),
    (MODE, 'a register is written without the accessor',
     '    v = osrdn_mmio_get(base, SNAP_CRTC_EXT_CNTL);\n    osrdn_mmio_put(base, SNAP_CRTC_EXT_CNTL, v | CRTC_DIS_ALL);\n}',
     '    rdnMmioWrite32(base, 0x0054, 0);\n}', ['writes-through-accessors']),
    (MODE, 'the revert stops restoring a register the entry writes',
     '    osrdn_mmio_put(base, SNAP_CRTC_PITCH, mode->snap.mmio[SNAP_CRTC_PITCH]);',
     '    /* mutation: the pitch is not restored */',
     ['entry-subset-revert']),
    (MODE, 'the blank happens before the snapshot',
     '    if (!modeSnapshot(mode, base))', '    modeBlank(mode, base);\n    if (!modeSnapshot(mode, base))',
     ['enter-order']),
    (MODE, 'modeWritten is set after the first write',
     '    mode->modeWritten = 1;              /* the first write is the next line */\n'
     '    v = osrdn_mmio_get(base, SNAP_CRTC_GEN_CNTL);\n'
     '    osrdn_mmio_put(base, SNAP_CRTC_GEN_CNTL, (v & ~CRTC_EN) | CRTC_DISP_REQ_EN_B);',
     '    v = osrdn_mmio_get(base, SNAP_CRTC_GEN_CNTL);\n'
     '    osrdn_mmio_put(base, SNAP_CRTC_GEN_CNTL, (v & ~CRTC_EN) | CRTC_DISP_REQ_EN_B);\n'
     '    mode->modeWritten = 1;', ['mode-written']),
    (MODE, 'the revert returns early',
     '    /* 4.5 the PLL, same code as the entry, snapshot values */',
     '    if (mode->why) return;\n    /* 4.5 the PLL, same code as the entry, snapshot values */',
     ['revert-runs-through']),
    (MODE, 'the PLL gain is written',
     'osrdn_pll_put(base, SNAP_PPLL_CNTL, v | PPLL_RESET | PPLL_ATOMIC_UPDATE_EN | PPLL_VGA_ATOMIC_EN);',
     'osrdn_pll_put(base, SNAP_PPLL_CNTL, (v & ~0x3800UL) | (7UL << 11) | PPLL_RESET);', ['no-pvg']),
    (MODE, 'the reference divider is written from the oracle',
     '(v & ~PPLL_REF_DIV_MASK) | (mode->refdiv & PPLL_REF_DIV_MASK));',
     '(v & ~PPLL_REF_DIV_MASK) | 12UL);', ['refdiv-from-boot']),
    (MODE, 'the sequence logs', '    mode->step = 13;', '    IOLog("step 13\\n");\n    mode->step = 13;',
     ['no-log']),
    (SNAP, 'the snapshot logs', '    vgaTake(snap);', '    IOLog("vga\\n");\n    vgaTake(snap);', ['no-log']),
    (MODE, 'the divider row is looked up after the blank',
     '    mode->step = 3;\n    if (!modeRow(mode, base))\n        return 0;\n\n'
     '    /* from here every failure reverts: -enterLinearMode cannot report one */\n'
     '    mode->step = 4;\n    modeBlank(mode, base);\n',
     '\n    mode->step = 4;\n    modeBlank(mode, base);\n'
     '    mode->step = 3;\n    if (!modeRow(mode, base))\n        return 0;\n', ['enter-order']),
    (MODESEL, 'the selection unit touches hardware',
     'osrdn_modesel_choose(const char *displayMode, unsigned long mapped, osrdn_modesel *sel)\n{',
     'osrdn_modesel_choose(const char *displayMode, unsigned long mapped, osrdn_modesel *sel)\n{\n'
     '    (void)rdnMmioRead32(0, 0);', ['modesel-pure']),
    (MODESEL, 'the selection unit logs',
     '    sel->pairDefault = 0;\n',
     '    sel->pairDefault = 0;\n    IOLog("x");\n', ['no-log']),
    (MODESEL, 'the selection unit uses libc',
     '        for (k = 0; k < OSRDN_FMT_COUNT; k++)\n            if (contains(displayMode',
     '        for (k = 0; k < OSRDN_FMT_COUNT; k++)\n            if (strstr(displayMode', ['modesel-pure']),
    (MODESEL, 'the selection unit names a variable out',
     '    unsigned long   width, height;\n    int             k;',
     '    unsigned long   width, height, out;\n    int             k;', ['modesel-pure']),
    (MODESEL, 'the selection unit uses switch',
     '    if (displayMode != 0) {',
     '    switch (0) { default: break; }\n    if (displayMode != 0) {', ['modesel-pure']),
    (CLASS, 'the class forgets to free the Display Mode string',
     '    osrdn_modesel_choose(key, OSRDN_FB_LENGTH, &sel);\n    if (key != 0)\n        [table freeString:key];\n',
     '    osrdn_modesel_choose(key, OSRDN_FB_LENGTH, &sel);\n', ['class-rules']),
    (CLASS, 'the class reads a register itself',
     '    rdnMode.res = sel.res;',
     '    (void)osrdn_peek(mmioBase, 0);\n    rdnMode.res = sel.res;', ['class-rules']),
    (CLASS, 'rowBytes ignores the format', 'info->rowBytes = res->width * fmt->bytes;',
     'info->rowBytes = res->width * 4;', ['class-displayinfo']),
    (CLASS, 'memorySize ignores the format', 'info->memorySize = res->width * fmt->bytes * res->height;',
     'info->memorySize = res->width * 4 * res->height;', ['class-displayinfo']),
    (CLASS, 'bitsPerPixel is always 24', 'info->bitsPerPixel = (IOBitsPerPixel)fmt->ioBpp;',
     'info->bitsPerPixel = IO_24BitsPerPixel;', ['class-displayinfo']),
    (CLASS, 'the class never marks the choice made', '    rdnMode.selected = 1;\n', '', ['class-displayinfo']),
    (CLASS, 'the verify line is printed on the revert path too',
     '    osrdn_mode_revert(&rdnMode, mmioBase);',
     '    osrdn_mode_revert(&rdnMode, mmioBase);\n    osrdn_verify_line(&rdnMode);', ['class-displayinfo']),
    (CLASS, 'a stale verify line is printed after a busy refusal',
     'if (rdnMode.enterCount != ran && rdnMode.step >= 12)', 'if (rdnMode.step >= 12)', ['class-displayinfo']),
    (CLASS, 'the transfer table is not advertised', 'info->flags = IO_DISPLAY_HAS_TRANSFER_TABLE;',
     'info->flags = 0;', ['class-displayinfo']),
    (CLASS, 'a brightness above 64 reaches the module',
     'if (level < EV_SCREEN_MIN_BRIGHTNESS || level > EV_SCREEN_MAX_BRIGHTNESS) {',
     'if (level < EV_SCREEN_MIN_BRIGHTNESS) {', ['class-displayinfo']),
    (CLASS, 'every brightness call is logged',
     'if (rdnMode.brightCalls <= OSRDN_BRIGHT_LINES)', 'if (1)', ['class-displayinfo']),
    (CLASS, 'the table is applied without the opt-in key',
     'return (mmioMapped && rdnState.recordEnabled) ? mmioBase : 0;', 'return mmioBase;', ['class-displayinfo']),
    (CLASS, 'the Gray Levels string is not freed',
     '    rdnMode.grayLevels = osrdn_modesel_gray(key, &grayRefused);\n    if (key != 0)\n        [table freeString:key];\n',
     '    rdnMode.grayLevels = osrdn_modesel_gray(key, &grayRefused);\n', ['class-rules']),
    (MODE, 'a kilobyte array goes back on the stack',
     'modeEnterBody(osrdn_mode_state *mode, vm_address_t base, vm_address_t fb)\n{\n    mode->enterCount++;',
     'modeEnterBody(osrdn_mode_state *mode, vm_address_t base, vm_address_t fb)\n{\n'
     '    unsigned long big[256];\n    mode->enterCount++;', ['no-float-no-div64']),
]


def main():
    modeText = open(MODE, encoding='utf-8').read()
    snapText = open(SNAP, encoding='utf-8').read()
    failures = 0

    print('  == rules on the real files ==')
    base = rules(modeText, snapText, open(MODESEL, encoding='utf-8').read())
    for name in sorted(base):
        if base[name]:
            for why in base[name]:
                print('    FAIL %-24s %s' % (name, why))
            failures += len(base[name])
    if not failures:
        print('    ok   %d rules' % len(base))

    print('  == mutations (each caught by the rule it targets) ==')
    selText = open(MODESEL, encoding='utf-8').read()
    classText = open(CLASS, encoding='utf-8').read()
    for path, label, old, new, want in MUTATIONS:
        text = {MODE: modeText, SNAP: snapText, MODESEL: selText, CLASS: classText}[path]
        if text.count(old) != 1:
            print('    FAIL %-58s anchor found %d times' % (label, text.count(old)))
            failures += 1
            continue
        mutated = text.replace(old, new)
        got = rules(mutated if path == MODE else modeText, mutated if path == SNAP else snapText,
                    mutated if path == MODESEL else selText, mutated if path == CLASS else classText)
        caught = sorted(n for n in got if got[n])
        ok = all(w in caught for w in want)
        print('    %-4s %-58s %s' % ('ok' if ok else 'FAIL', label,
                                     caught if ok else 'caught by %s, want %s' % (caught, want)))
        failures += 0 if ok else 1

    print('check_r2b_src: %s' % ('PASS' if not failures else 'FAIL (%d)' % failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
