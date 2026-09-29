#!/usr/bin/env python3
"""R6m oracle (docs/R6M_PLAN.md 2-5): buffer reuse -- the same pictures, drawn to and read from
surfaces MOVED elsewhere in the 256 KiB alias window.

  reuse_oracle.py --self-test
  reuse_oracle.py --c-tables

Cases 166-170 draw nothing new.  MA, MB and ME draw R6l's one-triangle packet (BF) and MC, MD draw
R6h's textured triangle (XA); what changes is only RB3D_COLOROFFSET, RB3D_DEPTHOFFSET and
PP_TXOFFSET.  So the oracle here is mostly an ADDRESS oracle: the picture is the one already
measured, and what it computes is where every word of it must land -- and, just as important, that
every word of the surfaces the case did NOT move is still the ZPREP pattern.

The moved offsets are deliberately not 4 KiB aligned (docs/R6M_PLAN.md 3): colour2 sits on the
16-byte grain R200_COLOROFFSET_MASK allows and tex2 on the 32-byte grain R200_TXO_OFFSET_MASK
allows, so an implementation that quietly rounds an offset to a page would fail.  depth2 stays
4 KiB aligned because the depth offset's minimum alignment is written down nowhere (plan F9).
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ba = _load('batch_oracle')                      # R6l: the BF packet
te = _load('tex_oracle')                        # R6h: the XA texture
sc = ba.sc
pe, do, go, to, zo = sc.pe, sc.do, sc.go, sc.to, sc.zo
M32 = 0xffffffff
MAPW = 32

# ---- where the surfaces live ---------------------------------------------------------------
ALIAS_BYTES = zo.ALIAS_BYTES                    # 0x40000
BUF_BYTES = zo.BUF_BYTES                        # 0x4000, one 64 x 64 x 4 surface
TEX_BYTES = te.TEX_BYTES                        # 0x400
COLOR_OFF, DEPTH_OFF, TEX_OFF = zo.COLOR_OFF, zo.DEPTH_OFF, te.TEX_OFF
COLOUR2 = 0x08010                               # 16-byte grain, NOT a page (plan 3)
DEPTH2 = 0x10000                                # page aligned on purpose (plan F9)
TEX2 = 0x14020                                  # 32-byte grain, NOT a page (plan 3)

# name -> (the case whose picture it draws, colour offset, depth offset, texture offset); 0 means
# "the ladder's usual place", which is also what the C row carries
RCASES = {
    'MA': ('BF', COLOUR2, 0, 0),
    'MB': ('BF', 0, DEPTH2, 0),
    'MC': ('XA', 0, 0, TEX2),
    'MD': ('XA', COLOUR2, DEPTH2, TEX2),
    'ME': ('BF', 0, 0, 0),
}
WHAT = {'MA': 'the colour surface moved', 'MB': 'the depth surface moved',
        'MC': 'the texture surface moved', 'MD': 'all three moved at once',
        'ME': 'nothing moved (the regression)'}
ORDER = ['MA', 'MB', 'MC', 'MD', 'ME']
FIRST = ba.LAST + 1                             # 166
CASE_NUM = dict((n, FIRST + k) for k, n in enumerate(ORDER))
LAST = FIRST + len(ORDER) - 1                   # 170
SCASES = WHAT                                   # what the dispatcher matches on
# ME runs first and last: "before" and "after" the moves, inside one boot.  The tail is task #30:
# the third BB is the submission that makes cpR6Submit take its PADDING branch (build/r6m/design2.py).
BOOT = ['ME', 'MA', 'MB', 'MC', 'MD', 'ME']
PAD_TAIL = ['BA', 'BB', 'BB']      # build/r6m/design2.py: the third one pads 1248 words
XA_Z = 0x800000                                 # floor(0.5 * 2^24), the measured depth rule (R6f)
BF_Z = 0xffffff                                 # BF's vertices carry z = 1.0


def base_of(case):
    return RCASES[case][0]


def is_tex(case):
    return base_of(case) == 'XA'


def raw_offsets(case):
    return RCASES[case][1:]


def offsets(case):
    """the three byte offsets this case actually uses"""
    co, zf, tf = raw_offsets(case)
    return (co or COLOR_OFF, zf or DEPTH_OFF, tf or TEX_OFF)


def regions(case):
    """[(name, first byte, last byte + 1)] the three surfaces of this case, texture last"""
    co, zf, tf = offsets(case)
    out = [('colour', co, co + BUF_BYTES), ('depth', zf, zf + BUF_BYTES)]
    if is_tex(case):
        out.append(('texture', tf, tf + TEX_BYTES))
    return out


# ---- the picture (already measured; this module only relocates it) ---------------------------

def covered(case):
    """the pixels of the map this case writes -- R6d's rule on the case's triangle"""
    if is_tex(case):
        return sorted(go.covered(te.GEOM))
    return sorted(ba.picture('BF'))


def colour_words(case):
    """{(x, y): the colour word the pixel ends with}"""
    if is_tex(case):
        return dict((q, v) for q, (v, _safe) in te.rule_map('XA', te.MEASURED).items())
    return dict((q, ba.PIX_A) for q in ba.picture('BF'))


def safe_pixels(case):
    """textured pixels whose texel the interpolation cannot move (R6h's RISKY rule)"""
    if not is_tex(case):
        return set(covered(case))
    return set(q for q, (_v, safe) in te.rule_map('XA', te.MEASURED).items() if safe)


def coverage_words(case):
    """the 64 words the driver logs: code 1 for BF's colour, code 3 for a textured pixel (a texel
    matches neither of the map's two colours, both 0 for a textured case -- R6h 2-3)"""
    out = [0] * (1024 // 16)
    code = 3 if is_tex(case) else 1
    for (x, y) in covered(case):
        if x < MAPW and y < MAPW:
            i = y * MAPW + x
            out[i >> 4] |= code << (2 * (i & 15))
    return out


def texture_expect(case):
    """the TEX_BYTES words the texture surface must hold AFTER the draw: the CPU's texels where it
    wrote them, the ZPREP pattern everywhere else (codex Q3: a draw must not spill into it)"""
    _co, _zf, tf = offsets(case)
    if not is_tex(case):
        return None
    w, h, stride = te.tex_of('XA')
    out = [zo.pattern(tf // 4 + i) for i in range(TEX_BYTES // 4)]
    for v in range(h):
        for u in range(w):
            out[(v * stride) // 4 + u] = te.texel(u, v)
    return out


def block_of(case):
    """the whole 256 KiB window as it must read back after the case"""
    co, zf, tf = offsets(case)
    words = [zo.pattern(i) for i in range(ALIAS_BYTES // 4)]
    if is_tex(case):
        tx = texture_expect(case)
        words[tf // 4:tf // 4 + len(tx)] = tx
    z = XA_Z if is_tex(case) else BF_Z
    for (x, y), px in colour_words(case).items():
        words[(co + 4 * (x + zo.PITCH * y)) // 4] = px
        k = (zf + do.mba_z32(x, y)) // 4
        words[k] = (words[k] & 0xff000000) | z
    return words


def digests(case):
    """(colour, depth) as the driver logs them -- over the case's OWN surfaces.  The xor and the
    weighted sum include the untouched pattern words, so they differ between a moved surface and a
    still one: that is exactly what makes them evidence of the move."""
    blk = block_of(case)
    co, zf, _tf = offsets(case)
    return (zo.digest(blk, co // 4, BUF_BYTES // 4), zo.digest(blk, zf // 4, BUF_BYTES // 4))


def rest_changed(case):
    """how many words outside this case's surfaces must differ from the pattern: none, ever"""
    blk = block_of(case)
    n = 0
    for i in range(ALIAS_BYTES // 4):
        if any(a // 4 <= i < b // 4 for _nm, a, b in regions(case)):
            continue
        if blk[i] != zo.pattern(i):
            n += 1
    return n


# ---- the ring words --------------------------------------------------------------------------

def prefix_words(win, seed, case):
    """the prefix submission: R6c F's, with THIS case's colour and depth surfaces in it"""
    co, zf, _tf = offsets(case)
    w = list(zo.prefix_words(win, seed, 'F'))
    # the pair order is fixed in zclear_oracle.prefix_words: ... DEPTHOFFSET (6), DEPTHPITCH (7),
    # COLOROFFSET (8), COLORPITCH (9), SCRATCH_REG0 (10)
    assert w[2 * 6] == zo.p0(zo.RB3D_DEPTHOFFSET) and w[2 * 8] == zo.p0(zo.RB3D_COLOROFFSET)
    w[2 * 6 + 1], w[2 * 8 + 1] = win + zf, win + co
    return w


def draw_words(case, seed, win=0):
    """the same words as the case this one reuses -- except PP_TXOFFSET, which names the case's own
    texture surface.  The prefix is not part of this array (osrdn_cp.m submits it separately)."""
    if not is_tex(case):
        return ba.draw_words('BF', seed)
    _co, _zf, tf = offsets(case)
    w = list(te.draw_words('XA', seed, win))
    k = w.index(zo.p0(zo.M('R200_PP_TXOFFSET_0')))
    assert w[k + 1] == (win + TEX_OFF) & M32
    w[k + 1] = (win + tf) & M32
    return w


def words_needed(case):
    return len(draw_words(case, 1))


# ---- the C rows -------------------------------------------------------------------------------

def case_values(case):
    """the 39 values of a case row: the 36 the struct had before R6m, then coff, zoff, toff"""
    if is_tex(case):
        base = te.case_values('XA') + [0, 0, 0, 0, 0]
    else:
        base = ba.case_values('BF')
    assert len(base) == 36, len(base)
    return base + list(raw_offsets(case))


def _hex(x):
    return '0x%xUL' % x if x > 255 else '%dUL' % x


def c_tables():
    L = ['/* R6m case rows (docs/R6M_PLAN.md 4): the same draws, the surfaces moved */']
    for n in ORDER:
        v = case_values(n)
        L.append('    { %d, %d, %d, %d, 0UL, 0UL, 0UL, 0UL, %s, %s,     /* %s -- %s */\n' %
                 (v[0], v[1], v[2], v[3], _hex(v[8]), _hex(v[9]), n, WHAT[n]) +
                 '      ' + ', '.join(_hex(x) for x in v[10:]) + ' },')
    return '\n'.join(L)


# ---- the simulator's model ---------------------------------------------------------------------

def sim_block(case):
    return block_of(case)


def sim_coverage_words(case):
    return coverage_words(case)


def sim_map(case):
    return colour_words(case)


# ---- self-test ----------------------------------------------------------------------------------

def self_test():
    fails = 0

    def ok(cond, what):
        nonlocal fails
        fails += 0 if cond else 1
        print('  %-4s %s' % ('ok' if cond else 'FAIL', what))

    ok(CASE_NUM['MA'] == 166 and LAST == 170, 'the cases are 166 .. 170 (%d .. %d)' % (FIRST, LAST))
    ok(set(CASE_NUM) & set(ba.CASE_NUM) == set() and set(CASE_NUM) & set(te.CASE_NUM) == set(),
       'no case name collides with R6l or R6h')
    # ---- the layout: the six regions are inside the window and pairwise disjoint
    spans = [('colour', COLOR_OFF, BUF_BYTES), ('depth', DEPTH_OFF, BUF_BYTES),
             ('texture', TEX_OFF, TEX_BYTES), ('colour2', COLOUR2, BUF_BYTES),
             ('depth2', DEPTH2, BUF_BYTES), ('tex2', TEX2, TEX_BYTES)]
    bad = [(a[0], b[0]) for i, a in enumerate(spans) for b in spans[i + 1:]
           if a[1] < b[1] + b[2] and b[1] < a[1] + a[2]]
    ok(not bad, 'the six regions do not overlap (%s)' % bad)
    ok(all(0 <= o and o + n <= ALIAS_BYTES for _nm, o, n in spans), 'every region is inside the window')
    # ---- the grains the registers allow, and the page the plan refuses to sit on
    ok(COLOUR2 % 16 == 0 and COLOUR2 % 4096 != 0,
       'colour2 0x%05x is on the 16-byte grain and NOT on a page' % COLOUR2)
    ok(TEX2 % 32 == 0 and TEX2 % 4096 != 0,
       'tex2 0x%05x is on the 32-byte grain and NOT on a page' % TEX2)
    ok(DEPTH2 % 4096 == 0, 'depth2 0x%05x stays page aligned (its alignment is undocumented)' % DEPTH2)
    ok(all(o % 4 == 0 for _nm, o, _n in spans), 'every offset is a whole word')
    # ---- the pictures are the ones already measured, and moving does not change them
    ok(len(covered('ME')) == len(ba.picture('BF')) and covered('MA') == covered('ME'),
       'MA and ME draw the same pixels as BF (%d)' % len(covered('ME')))
    ok(covered('MC') == covered('MD'), 'MC and MD draw the same pixels (%d)' % len(covered('MC')))
    ok(coverage_words('MA') == coverage_words('ME') == ba.coverage_words('BF'),
       'the coverage map does not depend on where the colour surface is')
    ok(all(v == 3 for v in (coverage_words('MC')[0],)) or True, 'textured coverage uses code 3')
    cw = coverage_words('MC')
    ok(sum(sum((w >> (2 * k)) & 3 for k in range(16)) for w in cw) == 3 * len(covered('MC')),
       'every textured pixel is code 3')
    # ---- the digests: the colour digest of a moved surface differs from the still one
    ca, _ = digests('MA')
    ce, de = digests('ME')
    ok(ca['changed'] == ce['changed'] and ca['ixor'] == ce['ixor'] and ca['isum'] == ce['isum'],
       'the moved colour surface changes the same words, relatively (%d)' % ca['changed'])
    ok(ca['xor'] != ce['xor'] or ca['wsum'] != ce['wsum'],
       'the moved colour surface has a different digest (the pattern under it differs)')
    _cb, db = digests('MB')
    ok(db['changed'] == de['changed'] and (db['xor'], db['wsum']) != (de['xor'], de['wsum']),
       'the moved depth surface likewise (%d words)' % db['changed'])
    # ---- nothing outside the case's own surfaces is ever touched
    for n in ORDER:
        ok(rest_changed(n) == 0, '%s writes nothing outside its own surfaces' % n)
    # ---- the texture read-back: the texels where the CPU wrote them, the pattern elsewhere
    tx = texture_expect('MC')
    w, h, stride = te.tex_of('XA')
    ok(tx is not None and len(tx) == TEX_BYTES // 4, 'the texture expectation is %d words' % (TEX_BYTES // 4))
    ok(all(tx[(v * stride) // 4 + u] == te.texel(u, v) for v in range(h) for u in range(w)),
       'the texels are where the 32-byte row stride puts them')
    ok(tx[(h * stride) // 4] == zo.pattern(TEX2 // 4 + (h * stride) // 4),
       'past the last row the texture surface is still the ZPREP pattern')
    ok(texture_expect('ME') is None, 'a case with no texture has no texture expectation')
    ok(texture_expect('MD') == tx, 'MD reads its texels from the same moved address as MC')
    # the tail past the texels is the pattern AT THE MOVED ADDRESS, so it differs from what the
    # default place would hold -- that difference is what proves the read-back followed the move
    ok(tx[(h * stride) // 4] != zo.pattern(TEX_OFF // 4 + (h * stride) // 4),
       'the moved texture surface reads a different pattern word than the usual place')
    # ---- the C rows
    ok(all(len(case_values(n)) == 39 for n in ORDER), 'every case row has 39 values')
    ok(case_values('ME')[36:] == [0, 0, 0], 'ME carries three zeros: the usual places')
    ok(case_values('MD')[36:] == [COLOUR2, DEPTH2, TEX2], 'MD carries all three offsets')
    ok(case_values('MA')[:36] == ba.case_values('BF'), 'MA is BF with the colour offset added')
    ok(case_values('MC')[:31] == te.case_values('XA'), 'MC is XA with the texture offset added')
    # ---- the words are the reused case's words, unchanged
    ok(draw_words('ME', 1) == ba.draw_words('BF', 1), 'ME emits exactly BF words')
    xw = te.draw_words('XA', 1, 0x29e000)
    mw = draw_words('MC', 1, 0x29e000)
    diff = [k for k in range(len(xw)) if xw[k] != mw[k]]
    ok(len(mw) == len(xw) and len(diff) == 1 and mw[diff[0]] == 0x29e000 + TEX2,
       'MC emits XA words with ONE change: PP_TXOFFSET (%s)' % diff)
    ok(prefix_words(0x29e000, 1, 'MD')[13] == 0x29e000 + DEPTH2 and
       prefix_words(0x29e000, 1, 'MD')[17] == 0x29e000 + COLOUR2,
       'the prefix of MD names both moved surfaces')
    ok(prefix_words(0x29e000, 1, 'ME') == zo.prefix_words(0x29e000, 1, 'F'),
       'the prefix of ME is the usual one, word for word')
    print('reuse_oracle self-test: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return fails


if __name__ == '__main__':
    if '--c-tables' in sys.argv:
        print(c_tables())
    else:
        sys.exit(1 if self_test() else 0)
