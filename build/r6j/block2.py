def blend_draw_words(case, seed):
    """R6j: F's state with Gouraud shading, the first draw (the destination), then -- in the same
    submission -- RB3D_BLENDCNTL and RB3D_CNTL, an optional WAIT_UNTIL, and the flat second draw"""
    fw = zo.draw_words('F', seed)
    state, pix, tail = list(fw[:26]), fw[26:34], fw[-10:]
    assert state[14] == zo.p0(zo.V('RADEON_SE_CNTL'))
    state[15] = go.se_cntl_gouraud()
    x1, y1, x2, y2 = to.CLIP
    clip = [zo.p0(zo.V('RADEON_RE_TOP_LEFT')), (y1 << 16) | x1,
            zo.p0(zo.V('RADEON_RE_WIDTH_HEIGHT')), ((y2 - 1) << 16) | (x2 - 1)]

    def draw(colours):
        body = [vf()]
        for (x, y), c in zip(GEOM_Q, colours):
            body += [to.fbits(x), to.fbits(y), to.fbits(0.5), to.fbits(1.0), to.word(c)]
        return [zo.rco.p3(zo.V('R200_3D_DRAW_IMMD_2'), len(body) - 1)] + body

    out = state + list(pix) + clip + draw([BLEND_DST_V[i] for i in range(3)])
    bc = blendcntl(case)
    if bc:
        out += [zo.p0(zo.V('R200_RB3D_BLENDCNTL')), bc,
                zo.p0(zo.V('RADEON_RB3D_CNTL')), rb3d2(case)]
    if blend_wait(case):
        out += [zo.p0(zo.V('RADEON_WAIT_UNTIL')), do.WAIT_3D_IDLECLEAN]
    out += draw([BLEND_SRC] * 3)
    return out + list(tail)


def blend_g_values(case):
    """the twelve values of this case's cpR6G row: no prefill, the second draw's ZSTENCILCNTL, its
    three z values and flat colour, the wait flag, then (R6j) BLENDCNTL and the second RB3D_CNTL"""
    return [0, 0, 0, 0, do.ZCNTL[24], to.fbits(0.5), to.fbits(0.5), to.fbits(0.5),
            to.word(BLEND_SRC), 1 if blend_wait(case) else 0, blendcntl(case), rb3d2(case)]


def blend_case_values(case):
    """the 33 values of a blend case's row"""
    return [0, 0, 64, 64, 0, 0, 0, 0, to.fbits(0.5), RE_SCISSOR,
            0x1000, 0xffffffff, 0x803, 0x10000, header(case), vf(), 0, TRI_J, 0, 0,
            go.se_cntl_gouraud(), 0xf, 0, 0xf, do.ZCNTL[24], 0, 0, 0, do.RB3D_Z_ON,
            len(do.GORDER) + ORDER4.index(case) + 1, 0, 0, 0]
