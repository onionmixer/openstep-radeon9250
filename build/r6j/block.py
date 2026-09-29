# ---- R6j: the blend unit (docs/R6J_PLAN.md 2) ----------------------------------------------------

BLEND_DST_V = ((0x10, 0x20, 0xf0, 0x40), (0xe0, 0x90, 0x30, 0xc0), (0x70, 0xf0, 0x80, 0x20))
BLEND_SRC = (0xc1, 0x2a, 0x9b, 0x37)            # (r, g, b, a) of the flat second draw
TRI_J = 58                                      # the cpR6Tris row the first draw uses
RB3D_BLEND = do.RB3D_Z_ON | 1                   # ALPHA_BLEND_ENABLE on top of our usual value
RB3D_BLEND_ROUND = RB3D_BLEND | 8               # + ROUND_ENABLE (plan J3)
GLF = {'ZERO': 32, 'ONE': 33, 'SRC_COLOR': 34, 'ONE_MINUS_SRC_COLOR': 35, 'DST_COLOR': 36,
       'ONE_MINUS_DST_COLOR': 37, 'SRC_ALPHA': 38, 'ONE_MINUS_SRC_ALPHA': 39, 'DST_ALPHA': 40,
       'ONE_MINUS_DST_ALPHA': 41}
COMB = {'ADD_CLAMP': 0 << 12, 'ADD_NOCLAMP': 1 << 12, 'SUB_CLAMP': 2 << 12, 'SUB_NOCLAMP': 3 << 12,
        'MIN': 4 << 12, 'MAX': 5 << 12, 'RSUB_CLAMP': 6 << 12, 'RSUB_NOCLAMP': 7 << 12}
# name: (source factor, destination factor, combine, RB3D_CNTL of the second draw, a wait between)
BCASES = {
    'J1': ('ONE', 'ZERO', 'ADD_CLAMP', RB3D_BLEND, False),
    'J2': ('ZERO', 'ONE', 'ADD_CLAMP', RB3D_BLEND, False),
    'J3': ('ONE', 'ONE', 'ADD_CLAMP', RB3D_BLEND, False),
    'J4': ('SRC_ALPHA', 'ONE_MINUS_SRC_ALPHA', 'ADD_CLAMP', RB3D_BLEND, False),
    'J5': ('DST_COLOR', 'ZERO', 'ADD_CLAMP', RB3D_BLEND, False),
    'J6': ('SRC_ALPHA', 'ONE', 'ADD_CLAMP', RB3D_BLEND, False),
    'J7': ('SRC_ALPHA', 'ONE_MINUS_SRC_ALPHA', 'ADD_CLAMP', RB3D_BLEND_ROUND, False),
    'J8': ('ONE', 'ONE', 'SUB_CLAMP', RB3D_BLEND, False),
    'J9': ('SRC_ALPHA', 'ONE_MINUS_SRC_ALPHA', 'ADD_CLAMP', RB3D_BLEND, True),
    'J0': (None, None, None, 0, False),         # the control: the second draw with blending off
}


def blendcntl(case):
    fs, fd, comb, _, _ = BCASES[case]
    if fs is None:
        return 0
    return COMB[comb] | (GLF[fs] << 16) | (GLF[fd] << 24)


def rb3d2(case):
    return BCASES[case][3]


def blend_wait(case):
    return BCASES[case][4]


_bd = {}


def blend_dst():
    """the first draw's Gouraud destination by the measured rule B: {(x, y): (r, g, b, a)}"""
    if _bd:
        return _bd['v']
    pts = GEOM_Q
    out = dict((p, []) for p in go.covered(pts))
    for c in range(4):
        vals = [BLEND_DST_V[v][c] for v in range(3)]
        for p, b in zip(go.covered(pts), go.rule_b(pts, vals, 'even')):
            out[p].append(b)
    _bd['v'] = dict((p, tuple(v)) for p, v in out.items())
    return _bd['v']


def factor_value(name, src, dst, lane):
    """the 0..255 factor this GL name gives for one channel (lane order b, g, r, a)"""
    if name == 'ZERO':
        return 0
    if name == 'ONE':
        return 255
    if name == 'SRC_COLOR':
        return src[lane]
    if name == 'ONE_MINUS_SRC_COLOR':
        return 255 - src[lane]
    if name == 'DST_COLOR':
        return dst[lane]
    if name == 'ONE_MINUS_DST_COLOR':
        return 255 - dst[lane]
    if name == 'SRC_ALPHA':
        return src[3]
    if name == 'ONE_MINUS_SRC_ALPHA':
        return 255 - src[3]
    if name == 'DST_ALPHA':
        return dst[3]
    return 255 - dst[3]                          # ONE_MINUS_DST_ALPHA


FMAPS = {'id': lambda x: x, 'sat256': lambda x: 256 if x == 255 else x,
         'expand': lambda x: x + (x >> 7)}
BLEND_RULES = [(fm, r) for fm in sorted(FMAPS) for r in range(256)]


def blend_map(case, rule):
    """{(x, y): pixel word} one R6j case under a named blend arithmetic"""
    fm, r = rule
    fs, fd, comb, _, _ = BCASES[case]
    out = {}
    for p, d in blend_dst().items():
        dl = (d[2], d[1], d[0], d[3])            # rule B gives (r, g, b, a); the word's lanes are b, g, r, a
        sl = (BLEND_SRC[2], BLEND_SRC[1], BLEND_SRC[0], BLEND_SRC[3])
        word = 0
        for lane in range(4):
            if fs is None:                       # blending off: the second draw replaces the destination
                v = sl[lane]
            else:
                a = FMAPS[fm](factor_value(fs, sl, dl, lane))
                b = FMAPS[fm](factor_value(fd, sl, dl, lane))
                t = (sl[lane] * a + r) >> 8
                u = (dl[lane] * b + r) >> 8
                v = t + u if comb.startswith('ADD') else t - u
                v = max(0, min(255, v)) if comb.endswith('CLAMP') else v & 0xff
            word |= (v & 0xff) << (8 * lane)
        out[p] = word
    return out


