#!/usr/bin/env python3
"""Pin the R4 engine invariants in the source text (docs/R4_ENGINE_PLAN.md 12, 13).

  check_r4_src.py            run every rule on the real files, then every mutation

Every rule carries at least one mutation, and each mutation must be caught by
the rule it targets in this same run (a rule that cannot fail proves nothing).

  r4-class-maps     the class maps exactly two things with IOMapPhysicalIntoIOTask
                    -- the MMIO aperture (OSRDN_MMIO_LENGTH) and the engine alias
                    (ENG_ALIAS_BYTES) -- and unmaps them only in -free
  r4-engine-writes  only osrdn_engine.m writes engine registers, and only the
                    sixteen it is allowed (the batches, the two dest caches, and
                    RB3D_CNTL -- to 0 only, docs 17);
                    no byte writes
  r4-forbidden      nothing writes SURFACE_CNTL, RBBM_SOFT_RESET or
                    HOST_PATH_CNTL (docs 3-2): not by name, not by number
  r4-in-map         every engine register lies inside OSRDN_MMIO_LENGTH (the
                    8 KiB map would have faulted on 0x342c, docs 9-1 E1)
  r4-batches        fill = 12 writes, blit = 13, RB3D_CNTL = 0 first, DST_WIDTH_HEIGHT
                    (the trigger) exactly once and last in each
  r4-gmc            the two DP_GUI_MASTER_CNTL words equal what xf86
                    radeon_reg.h's bit definitions give (AUX_CLIP_DIS included)
  r4-waits          idle means FIFO full AND not active; every wait is bounded by
                    both time and turns; the engine never sleeps or logs
  r4-flush-rmw      each dest cache is flushed by writing back what was read,
                    OR the flush bits (not a bare store)
  r4-latch-first    after a trigger timeout the latch is set before any read
  r4-fence          the prepared block is read back in full before the batch
  r4-wrapper        osrdn_mode_engine claims, sets noSleep, and leaves only
                    through modeFinish -- no return between, no modeRelease
  r4-pll-peek       the read-only PLL table is its own, shares no index with the
                    snapshot table, no write accessor uses it, and the peek puts
                    the saved index byte back
  r4-unique-names   no function name is defined in two units (the reloc gate keys
                    code ranges by name)
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
TPROJ = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj')
XREG = os.path.join(PROJ, 'ref', 'upstream', 'unpacked', 'xf86-video-ati-6.14.6', 'src', 'radeon_reg.h')
FILES = ['OSRDNDisplay.m', 'osrdn_engine.m', 'osrdn_engine.h', 'osrdn_mode.m', 'osrdn_snap.m',
         'osrdn_snap.h', 'osrdn_record.h', 'osrdn_record.m', 'osrdn_pll.m', 'osrdn_modelog.m',
         'osrdn_window.m', 'RDNR2aMMIO.m']
ALLOWED_WRITES = {'E_DEFAULT_OFFSET', 'E_DST_PITCH_OFFSET', 'E_SRC_PITCH_OFFSET', 'E_DEFAULT_SC_BR',
                  'E_SC_TOP_LEFT', 'E_SC_BOTTOM_RIGHT', 'E_DP_GUI_MASTER_CNTL', 'E_DP_WRITE_MASK',
                  'E_DP_BRUSH_FRGD_CLR', 'E_DP_CNTL', 'E_SRC_Y_X', 'E_DST_Y_X', 'E_DST_WIDTH_HEIGHT',
                  'E_RB2D_DSTCACHE_CTLSTAT', 'E_RB3D_DSTCACHE_CTLSTAT', 'E_RB3D_CNTL'}
FORBIDDEN = {0x0b00: 'SURFACE_CNTL', 0x00f0: 'RBBM_SOFT_RESET', 0x0130: 'HOST_PATH_CNTL'}


def blank(code):
    code = re.sub(r'/\*.*?\*/', lambda m: ' ' * len(m.group()), code, flags=re.S)
    return re.sub(r'"(?:[^"\\\n]|\\.)*"', '""', code)


def bodies(code):
    """{function name: body} for C definitions at column 0"""
    out = {}
    for m in re.finditer(r'^(?:static\s+)?[A-Za-z_][\w \t*]*\n([A-Za-z_]\w*)\s*\(', code, re.M):
        start = code.find('{', m.end())
        if start < 0:
            continue
        depth, k = 0, start
        while k < len(code):
            depth += {'{': 1, '}': -1}.get(code[k], 0)
            if depth == 0 and code[k] == '}':
                break
            k += 1
        out[m.group(1)] = code[start:k + 1]
    return out


def method(code, sel):
    """the body of an Objective-C method whose selector starts with sel"""
    m = re.search(r'^[-+]\s*\([^)]*\)\s*%s\b|^[-+]\s*%s\b' % (sel, sel), code, re.M)
    if not m:
        return ''
    start = code.find('{', m.end())
    depth, k = 0, start
    while k < len(code):
        depth += {'{': 1, '}': -1}.get(code[k], 0)
        if depth == 0 and code[k] == '}':
            break
        k += 1
    return code[start:k + 1]


def call_args(code, name):
    """[(position, argument text)] for every call of name, arguments to the matching ')'"""
    out = []
    for m in re.finditer(r'\b%s\s*\(' % name, code):
        depth, k = 1, m.end()
        while k < len(code) and depth:
            depth += {'(': 1, ')': -1}.get(code[k], 0)
            k += 1
        out.append((m.start(), code[m.end():k - 1]))
    return out


def split_args(a):
    parts, depth, cur = [], 0, ''
    for ch in a:
        if ch == ',' and depth == 0:
            parts.append(cur.strip())
            cur = ''
            continue
        depth += {'(': 1, ')': -1}.get(ch, 0)
        cur += ch
    parts.append(cur.strip())
    return parts


def defines(text):
    out = {}
    for m in re.finditer(r'^#define\s+(\w+)\s+(0x[0-9a-fA-F]+|\d+)U?L?\b', text, re.M):
        out[m.group(1)] = int(m.group(2), 0)
    return out


def xf86_gmc():
    t = open(XREG).read()
    def bit(name):
        m = re.search(r'#\s*define\s+RADEON_%s\s+\((\w+)\s*<<\s*(\d+)\)' % name, t)
        if m:
            return int(m.group(1), 0) << int(m.group(2))
        m = re.search(r'#\s*define\s+RADEON_%s\s+(0x[0-9a-fA-F]+)' % name, t)
        return int(m.group(1), 16)
    common = bit('GMC_DST_32BPP') | bit('GMC_SRC_DATATYPE_COLOR') | bit('GMC_CLR_CMP_CNTL_DIS') | \
        bit('GMC_AUX_CLIP_DIS')
    fill = common | bit('GMC_DST_PITCH_OFFSET_CNTL') | bit('GMC_BRUSH_SOLID_COLOR') | bit('ROP3_P')
    blit = common | bit('GMC_DST_PITCH_OFFSET_CNTL') | bit('GMC_SRC_PITCH_OFFSET_CNTL') | \
        bit('GMC_BRUSH_NONE') | bit('ROP3_S') | bit('DP_SRC_SOURCE_MEMORY')
    return fill, blit


def rules(src):
    r = {}
    b = dict((n, blank(t)) for n, t in src.items())
    eng = b['osrdn_engine.m']
    efn = bodies(eng)
    edef = defines(src['osrdn_engine.m'])

    # ---- class maps
    p = []
    cls = b['OSRDNDisplay.m']
    maps = [split_args(a) for _, a in call_args(cls, 'IOMapPhysicalIntoIOTask')]
    lengths = sorted(a[1] for a in maps if len(a) == 3)
    if len(maps) != 2 or lengths != ['(unsigned)ENG_ALIAS_BYTES', 'OSRDN_MMIO_LENGTH']:
        p.append('IOMapPhysicalIntoIOTask lengths %s, want the MMIO map and the alias' % lengths)
    free = method(cls, 'free')
    for pos, a in call_args(cls, 'IOUnmapPhysicalFromIOTask'):
        if a not in free:
            p.append('IOUnmapPhysicalFromIOTask(%s) outside -free' % a.strip())
    unl = sorted(split_args(a)[1] for _, a in call_args(free, 'IOUnmapPhysicalFromIOTask'))
    if unl != ['(unsigned)ENG_ALIAS_BYTES', 'OSRDN_MMIO_LENGTH']:
        p.append('-free unmaps %s' % unl)
    r['r4-class-maps'] = p

    # ---- who writes engine registers, and which
    p = []
    for name, text in b.items():
        if name in ('osrdn_engine.m', 'RDNR2aMMIO.m') or not name.endswith('.m'):
            continue
        for reg in re.findall(r'\bE_[A-Z0-9_]+', text):
            p.append('%s names engine register %s' % (name, reg))
    for pos, a in call_args(eng, 'rdnMmioWrite32'):
        reg = split_args(a)[1]
        if reg not in ALLOWED_WRITES:
            p.append('osrdn_engine.m writes %s' % reg)
        if reg == 'E_RB3D_CNTL' and split_args(a)[2] != '0UL':
            p.append('RB3D_CNTL written with %s, not 0 (docs 17)' % split_args(a)[2])
    if call_args(eng, 'rdnMmioWrite8'):
        p.append('osrdn_engine.m writes a byte')
    r['r4-engine-writes'] = p

    # ---- forbidden registers
    p = []
    for name, text in b.items():
        for fn in ('rdnMmioWrite32', 'rdnMmioWrite8', 'osrdn_mmio_put'):
            for pos, a in call_args(text, fn):
                parts = split_args(a)
                if len(parts) < 2:
                    continue
                reg = parts[1]
                val = edef.get(reg)
                if val is None:
                    try:
                        val = int(reg.rstrip('UL'), 0)
                    except ValueError:
                        continue
                if val in FORBIDDEN:
                    p.append('%s writes %s (%s)' % (name, FORBIDDEN[val], reg))
    r['r4-forbidden'] = p

    # ---- every engine register inside the MMIO map
    p = []
    maplen = defines(src['osrdn_record.h']).get('OSRDN_MMIO_LENGTH', 0)
    for name, val in edef.items():
        if name.startswith('E_') and name not in ('E_FIFO_MASK', 'E_FIFO_DEPTH', 'E_RBBM_ACTIVE',
                                                     'E_CSQ_MODE_MASK', 'E_SURF_SWAP_MASK',
                                                     'E_DC_FLUSH_ALL', 'E_DC_BUSY', 'E_GMC_FILL',
                                                     'E_GMC_BLIT', 'E_DIR_X_LTR', 'E_DIR_Y_TTB',
                                                     'E_SC_MAX', 'E_MARK', 'E_FILL_X', 'E_FILL_Y',
                                                     'E_FILL_W', 'E_FILL_H', 'E_FILL_WRITES',
                                                     'E_BLIT_WRITES', 'E_TICK_US', 'E_FIFO_US',
                                                     'E_IDLE_US', 'E_DC_US', 'E_TURN_FACTOR',
                                                     'E_TURN_SLACK', 'E_REREAD_US'):
            if val + 4 > maplen:
                p.append('%s %#x is outside the %#x MMIO map' % (name, val, maplen))
    if maplen < 0x3430:
        p.append('OSRDN_MMIO_LENGTH %#x does not reach RB2D_DSTCACHE_CTLSTAT' % maplen)
    r['r4-in-map'] = p

    # ---- the batches
    p = []
    clip = len(call_args(efn.get('engClip', ''), 'rdnMmioWrite32'))
    for fn, want, wconst in (('engFillBatch', 12, 'E_FILL_WRITES'), ('engBlitBatch', 13, 'E_BLIT_WRITES')):
        body = efn.get(fn, '')
        w = call_args(body, 'rdnMmioWrite32')
        n = len(w) + (clip if 'engClip' in body else 0)
        if n != want:
            p.append('%s makes %d writes, want %d' % (fn, n, want))
        if edef.get(wconst) != want:
            p.append('%s is %s, want %d' % (wconst, edef.get(wconst), want))
        regs = [split_args(a)[1] for _, a in w]
        if not regs or regs[-1] != 'E_DST_WIDTH_HEIGHT' or regs.count('E_DST_WIDTH_HEIGHT') != 1:
            p.append('%s: the trigger is not written once and last (%s)' % (fn, regs[-3:]))
        if not regs or regs[0] != 'E_RB3D_CNTL':
            p.append('%s: RB3D_CNTL is not cleared first (docs 17)' % fn)
    r['r4-batches'] = p

    # ---- GMC words against xf86's bit definitions
    p = []
    fill, blit = xf86_gmc()
    if edef.get('E_GMC_FILL') != fill:
        p.append('E_GMC_FILL %#x, the header gives %#010x' % (edef.get('E_GMC_FILL', -1), fill))
    if edef.get('E_GMC_BLIT') != blit:
        p.append('E_GMC_BLIT %#x, the header gives %#010x' % (edef.get('E_GMC_BLIT', -1), blit))
    r['r4-gmc'] = p

    # ---- waits
    p = []
    cond = efn.get('engCond', '')
    idle = cond[cond.find('case W_IDLE'):cond.find('case W_DC2')]
    if 'E_FIFO_DEPTH' not in idle or 'E_RBBM_ACTIVE' not in idle:
        p.append('idle does not require both a full FIFO and not-active')
    wait = efn.get('engWait', '')
    # both bounds must be TESTED inside the loop, not merely computed
    if not re.search(r'turns\+\+;\s*if \(turns >= maxTurns\)\s*break;', wait):
        p.append('engWait does not test its turn bound')
    if not re.search(r'if \(w->us >= limitUs\)\s*break;', wait):
        p.append('engWait does not test its time bound')
    if 'IODelay' not in wait:
        p.append('engWait does not spin with IODelay')
    for bad in ('IOSleep', 'IOLog'):
        if re.search(r'\b%s\s*\(' % bad, eng):
            p.append('osrdn_engine.m calls %s' % bad)
    r['r4-waits'] = p

    # ---- flush by read-modify-write
    p = []
    draw = efn.get('engDraw', '')
    for reg, pre in (('E_RB2D_DSTCACHE_CTLSTAT', 'dc2Pre'), ('E_RB3D_DSTCACHE_CTLSTAT', 'dc3Pre')):
        if not re.search(r'e->%s\s*=\s*rdnMmioRead32\(base,\s*%s\)' % (pre, reg), draw):
            p.append('%s is not read before its flush' % reg)
        if not re.search(r'rdnMmioWrite32\(base,\s*%s,\s*e->%s\s*\|\s*E_DC_FLUSH_ALL\)' % (reg, pre), draw):
            p.append('%s is not written back with the flush bits ORed in' % reg)
    r['r4-flush-rmw'] = p

    # ---- latch before any read
    p = []
    latch = efn.get('engLatch', '')
    a, rd = latch.find('e->latched = 1'), latch.find('rdnMmioRead32')
    if a < 0 or (rd >= 0 and rd < a):
        p.append('engLatch reads before it latches')
    r['r4-latch-first'] = p

    # ---- the fence
    p = []
    prep = efn.get('engPrepare', '')
    # the fence is the read-back AGAINST preValue that follows the write loop;
    # UBLIT's check of the user's words (R4c) reads the block too, before any
    # write, and must not stand in for it (docs/R4C_VMAP_PLAN.md 11-2)
    wr = prep.find('a[off / 4UL] = preValue(op, arg, off);')
    fence = re.search(r'for \(off = 0; off < ENG_ALIAS_BYTES; off \+= 4UL\)\s*\n\s*'
                      r'if \(a\[off / 4UL\] != preValue\(op, arg, off\)\)', prep)
    if wr < 0 or not fence or fence.start() < wr:
        p.append('engPrepare does not read the whole block back against preValue after writing it')
    if draw.find('engPrepare') < 0 or draw.find('engPrepare') > draw.find('engFillBatch'):
        p.append('engDraw does not prepare (and fence) before the batch')
    r['r4-fence'] = p

    # ---- the wrapper in osrdn_mode.m
    p = []
    mode = b['osrdn_mode.m']
    wrap = bodies(mode).get('osrdn_mode_engine', '')
    c, f = wrap.find('modeClaim'), wrap.rfind('modeFinish')
    if c < 0 or f < 0:
        p.append('osrdn_mode_engine lacks the claim or modeFinish')
    else:
        mid = wrap[wrap.find(';', c):f]
        if re.search(r'\breturn\b', mid):
            p.append('osrdn_mode_engine returns between the claim and modeFinish')
        if 'noSleep = 1' not in mid or mid.find('noSleep = 1') > mid.find('osrdn_engine_run'):
            p.append('osrdn_mode_engine does not set noSleep before the engine runs')
    if 'modeRelease' in wrap:
        p.append('osrdn_mode_engine uses modeRelease (a kernel revert would be lost)')
    if re.search(r'\bIOLog\s*\(', mode):
        p.append('osrdn_mode.m logs')
    r['r4-wrapper'] = p

    # ---- the read-only PLL table
    p = []
    snap = src['osrdn_snap.m']
    def table(name):
        m = re.search(r'osrdn_snap_reg\s+%s\s*\[[^\]]*\]\s*=\s*\{(.*?)\};' % name, snap, re.S)
        return [] if m is None else [int(x, 16) for x in re.findall(r'0x([0-9a-fA-F]+)\s*\}', m.group(1))]
    peek, snapPll = table('osrdnPllPeek'), table('osrdnSnapPll')
    if sorted(peek) != [0x0d, 0x14, 0x35]:
        p.append('osrdnPllPeek holds %s' % [hex(x) for x in peek])
    if set(peek) & set(snapPll):
        p.append('a read-only PLL register is also in the snapshot table')
    sfn = bodies(b['osrdn_snap.m'])
    for name in ('osrdn_mmio_put', 'osrdn_pll_put', 'osrdn_palette_put', 'osrdn_vga_put'):
        if 'osrdnPllPeek' in sfn.get(name, ''):
            p.append('%s, a write accessor, uses the read-only PLL table' % name)
    pk = sfn.get('osrdn_pll_peek', '')
    w8 = call_args(pk, 'rdnMmioWrite8')
    if len(w8) != 2 or 'saved' not in w8[-1][1]:
        p.append('osrdn_pll_peek does not put the saved index byte back')
    if 'PLL_WR_EN' not in pk:
        p.append('osrdn_pll_peek does not refuse an index with PLL_WR_EN set')
    r['r4-pll-peek'] = p

    # ---- no two units define a function of the same name: the reloc gate keys
    #      code ranges by symbol name, so a second static elapsedUs hid the
    #      first and failed the target build (docs 16)
    p = []
    seen = {}
    for name, text in sorted(b.items()):
        if not name.endswith('.m'):
            continue
        for fn in bodies(text):
            seen.setdefault(fn, []).append(name)
    for fn, where in sorted(seen.items()):
        if len(where) > 1:
            p.append('%s is defined in %s' % (fn, ', '.join(where)))
    r['r4-unique-names'] = p
    return r


E = 'osrdn_engine.m'
MUTATIONS = [
    ('OSRDNDisplay.m', 'a third mapping in the class',
     '    mmioMapped = YES;\n', '    mmioMapped = YES;\n    (void)IOMapPhysicalIntoIOTask(0, 4096, &fbBase);\n',
     ['r4-class-maps']),
    ('OSRDNDisplay.m', 'the alias is not unmapped in free',
     '        (void)IOUnmapPhysicalFromIOTask(rdnEngine.alias, (unsigned)ENG_ALIAS_BYTES);\n', '',
     ['r4-class-maps']),
    (E, 'the engine writes SURFACE_CNTL',
     '    rdnMmioWrite32(base, E_DP_WRITE_MASK, 0xffffffffUL);\n    rdnMmioWrite32(base, E_DP_BRUSH_FRGD_CLR, colour);',
     '    rdnMmioWrite32(base, E_DP_WRITE_MASK, 0xffffffffUL);\n    rdnMmioWrite32(base, E_SURFACE_CNTL, 0x100UL);\n'
     '    rdnMmioWrite32(base, E_DP_BRUSH_FRGD_CLR, colour);', ['r4-engine-writes', 'r4-forbidden', 'r4-batches']),
    (E, 'the engine soft-resets by number',
     '    e->latched = 1;\n', '    rdnMmioWrite32(base, 0x00f0, 0x7fUL);\n    e->latched = 1;\n',
     ['r4-forbidden']),
    ('osrdn_mode.m', 'the mode module writes an engine register',
     '    mode->kernelRevertSeen = 0;\n    mode->noSleep = 1;                  /* setIntValues must not sleep, and a revert',
     '    mode->kernelRevertSeen = 0;\n    (void)E_DP_CNTL;\n    mode->noSleep = 1;                  /* setIntValues must not sleep, and a revert',
     ['r4-engine-writes']),
    ('osrdn_record.h', 'the MMIO map shrinks back to 8 KiB',
     '#define OSRDN_MMIO_LENGTH   0x4000', '#define OSRDN_MMIO_LENGTH   0x2000', ['r4-in-map']),
    (E, 'RB3D_CNTL written with a value other than 0',
     '    rdnMmioWrite32(base, E_RB3D_CNTL, 0UL);                             /* no 3D (docs 17) */\n    rdnMmioWrite32(base, E_DEFAULT_OFFSET, decoy(e));\n    rdnMmioWrite32(base, E_DST_PITCH_OFFSET,',
     '    rdnMmioWrite32(base, E_RB3D_CNTL, 0x1800UL);                        /* no 3D (docs 17) */\n    rdnMmioWrite32(base, E_DEFAULT_OFFSET, decoy(e));\n    rdnMmioWrite32(base, E_DST_PITCH_OFFSET,',
     ['r4-engine-writes']),
    (E, 'the trigger is not last',
     '    rdnMmioWrite32(base, E_DST_Y_X, (E_FILL_Y << 16) | E_FILL_X);\n'
     '    rdnMmioWrite32(base, E_DST_WIDTH_HEIGHT, (E_FILL_W << 16) | E_FILL_H);   /* last */',
     '    rdnMmioWrite32(base, E_DST_WIDTH_HEIGHT, (E_FILL_W << 16) | E_FILL_H);   /* last */\n'
     '    rdnMmioWrite32(base, E_DST_Y_X, (E_FILL_Y << 16) | E_FILL_X);', ['r4-batches']),
    (E, 'a blit batch forgets the source pitch',
     '    rdnMmioWrite32(base, E_SRC_PITCH_OFFSET,\n                   osrdn_engine_pitch_offset(card(e, c->srcOff), c->srcPitch));\n',
     '', ['r4-batches']),
    (E, 'AUX_CLIP_DIS dropped from the fill word',
     '#define E_GMC_FILL              0x30f036d2UL', '#define E_GMC_FILL              0x10f036d2UL', ['r4-gmc']),
    (E, 'the blit word keeps the default pitch register',
     '#define E_GMC_BLIT              0x32cc36f3UL', '#define E_GMC_BLIT              0x32cc36f0UL', ['r4-gmc']),
    (E, 'idle ignores the FIFO',
     '        if ((v & E_FIFO_MASK) != E_FIFO_DEPTH)\n            return 0;\n        return (v & E_RBBM_ACTIVE) == 0UL;',
     '        return (v & E_RBBM_ACTIVE) == 0UL;', ['r4-waits']),
    (E, 'a wait loses its turn bound',
     '        turns++;\n        if (turns >= maxTurns)\n            break;\n', '', ['r4-waits']),
    (E, 'a wait loses its time bound',
     '        if (w->us >= limitUs)\n            break;\n', '', ['r4-waits']),
    (E, 'the engine sleeps',
     '        IODelay((unsigned)E_TICK_US);\n', '        IOSleep(1);\n', ['r4-waits']),
    (E, 'the flush is a bare store',
     '    rdnMmioWrite32(base, E_RB2D_DSTCACHE_CTLSTAT, e->dc2Pre | E_DC_FLUSH_ALL);',
     '    rdnMmioWrite32(base, E_RB2D_DSTCACHE_CTLSTAT, E_DC_FLUSH_ALL);', ['r4-flush-rmw']),
    (E, 'the latch comes after the status read',
     '    e->latched = 1;\n    e->defaultLeft = 1;\n    e->postStatus = rdnMmioRead32(base, E_RBBM_STATUS);',
     '    e->postStatus = rdnMmioRead32(base, E_RBBM_STATUS);\n    e->latched = 1;\n    e->defaultLeft = 1;',
     ['r4-latch-first']),
    (E, 'the fence (full read-back) is removed',
     '    for (off = 0; off < ENG_ALIAS_BYTES; off += 4UL)\n        if (a[off / 4UL] != preValue(op, arg, off))\n'
     '            return engRefuse(e, isBlit(op) ? ENG_WHY_PATTERN : ENG_WHY_MARKER, off);\n',
     '', ['r4-fence']),
    (E, 'the read-back moved before the write loop (it no longer fences anything)',
     "    for (off = 0; off < ENG_ALIAS_BYTES; off += 4UL) {\n        if (op == ENG_OP_UBLIT && inSurface(off, ENG_S1_OFF, S1P, ENG_S1_H, &x, &y))\n            continue;                               /* the user's source stays */\n        a[off / 4UL] = preValue(op, arg, off);\n    }\n    for (off = 0; off < ENG_ALIAS_BYTES; off += 4UL)\n        if (a[off / 4UL] != preValue(op, arg, off))\n            return engRefuse(e, isBlit(op) ? ENG_WHY_PATTERN : ENG_WHY_MARKER, off);\n",
     "    for (off = 0; off < ENG_ALIAS_BYTES; off += 4UL)\n        if (a[off / 4UL] != preValue(op, arg, off))\n            return engRefuse(e, isBlit(op) ? ENG_WHY_PATTERN : ENG_WHY_MARKER, off);\n    for (off = 0; off < ENG_ALIAS_BYTES; off += 4UL) {\n        if (op == ENG_OP_UBLIT && inSurface(off, ENG_S1_OFF, S1P, ENG_S1_H, &x, &y))\n            continue;                               /* the user's source stays */\n        a[off / 4UL] = preValue(op, arg, off);\n    }\n", ['r4-fence']),
    ('osrdn_mode.m', 'the wrapper returns a refusal without modeFinish',
     '    if (!mode->snapshotValid || !mode->modeWritten)\n        rc = ENG_RC_NOT_LIVE;',
     '    if (!mode->snapshotValid || !mode->modeWritten)\n        return ENG_RC_NOT_LIVE;', ['r4-wrapper']),
    ('osrdn_mode.m', 'the wrapper releases instead of finishing',
     '    *copy = *eng;                       /* while the claim is still ours */\n    modeFinish(mode, base);\n    return rc;',
     '    *copy = *eng;                       /* while the claim is still ours */\n    modeRelease(mode);\n    modeFinish(mode, base);\n    return rc;',
     ['r4-wrapper']),
    ('osrdn_mode.m', 'the wrapper forgets noSleep',
     '    mode->noSleep = 1;                  /* setIntValues must not sleep, and a revert',
     '    mode->noSleep = 0;                  /* setIntValues must not sleep, and a revert', ['r4-wrapper']),
    ('osrdn_snap.m', 'a clock register goes into the snapshot table',
     '    { "HTOTAL_CNTL",           0x09 }\n};', '    { "HTOTAL_CNTL",           0x09 },\n    { "SCLK_CNTL",             0x0d }\n};',
     ['r4-pll-peek']),
    (E, 'a second unit defines elapsedUs again',
     'static unsigned long\nengElapsedUs(', 'static unsigned long\nelapsedUs(', ['r4-unique-names']),
    ('osrdn_snap.m', 'the peek leaves the index where it put it',
     '    rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX, (unsigned char)(saved & 0xffUL));\n', '',
     ['r4-pll-peek']),
]


def main():
    src = dict((f, open(os.path.join(TPROJ, f), encoding='utf-8').read()) for f in FILES)
    failures = 0
    print('  == rules on the real files ==')
    base = rules(src)
    for name in sorted(base):
        for why in base[name]:
            print('    FAIL %-18s %s' % (name, why))
        failures += len(base[name])
    if not failures:
        print('    ok   %d rules' % len(base))
    print('  == mutations (each caught by the rule it targets) ==')
    for path, label, old, new, want in MUTATIONS:
        text = src[path]
        if text.count(old) != 1:
            print('    FAIL %-52s anchor found %d times' % (label, text.count(old)))
            failures += 1
            continue
        got = rules(dict(src, **{path: text.replace(old, new)}))
        caught = sorted(n for n in got if got[n])
        ok = all(w in caught for w in want)
        print('    %-4s %-52s %s' % ('ok' if ok else 'FAIL', label,
                                     caught if ok else 'caught by %s, want %s' % (caught, want)))
        failures += 0 if ok else 1
    print('check_r4_src: %s' % ('PASS' if not failures else 'FAIL (%d)' % failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
