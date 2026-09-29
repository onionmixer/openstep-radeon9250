def judge_blend(zs, p, notes):
    """R6j across the boot (docs/R6J_PLAN.md 2-3): K1 the controls, K2 the blend arithmetic,
    K3 the combine function, K4 ROUND_ENABLE, K5 whether a wait is needed between the draws"""
    by = dict((CASE_NAME.get(o['len']), o) for o in zs if CASE_NAME.get(o['len']) in pe.CASE_NUM)
    if not by:
        return
    # ---- K1: the two controls
    o = by.get('J0')
    if o is not None and 'texpix' in o:
        want = pe.to.pixel(pe.BLEND_SRC)
        bad = sum(1 for v in o['texpix'].values() if v != want)
        if bad:
            p.append('R6j K1: with blending off the second draw left %d of %d pixels unlike its flat '
                     'colour' % (bad, len(o['texpix'])))
        else:
            notes.append('R6j K1: with blending off the second draw replaces the destination '
                         '(%d pixels)' % len(o['texpix']))
    o = by.get('J2')
    if o is not None and 'texpix' in o:
        dst = pe.blend_dst()
        bad = 0
        for q, d in dst.items():
            w = (d[3] << 24) | (d[0] << 16) | (d[1] << 8) | d[2]      # a r g b, the framebuffer order
            bad += o['texpix'].get(q) != w
        if bad:
            p.append('R6j K1: (ZERO, ONE) changed the destination on %d of %d pixels' % (bad, len(dst)))
        else:
            notes.append('R6j K1: (ZERO, ONE) leaves the Gouraud destination exactly as rule B drew it')
    # ---- K2: the blend arithmetic over the five gated cases
    gated = [n for n in ('J1', 'J3', 'J4', 'J5', 'J6') if 'texpix' in by.get(n, {})]
    named = []
    if gated:
        fits = []
        for r in pe.BLEND_RULES:
            d = 0
            for n2 in gated:
                m2 = pe.blend_map(n2, r)
                d += sum(1 for q, want in m2.items() if by[n2]['texpix'].get(q) != want)
            fits.append((d, r))
        fits.sort(key=lambda t: (t[0], str(t[1])))
        named = [r for d, r in fits if d == 0]
        if named:
            notes.append('R6j K2: the blend is (src*Fs + r) >> 8 + (dst*Fd + r) >> 8 with the factor '
                         'read as %s and r = %s%s' %
                         (named[0][0], named[0][1],
                          '' if len(named) == 1 else ' (%d rules give the same picture: %s)'
                          % (len(named), named[:6])))
        else:
            p.append('R6j K2: no named blend arithmetic explains the five cases (FAIL, measured) -- '
                     'nearest %s' % [(d, r) for d, r in fits[:3]])
    # ---- K3: the combine function of J8
    o = by.get('J8')
    if o is not None and 'texpix' in o and named:
        for comb in ('SUB_CLAMP', 'RSUB_CLAMP', 'SUB_NOCLAMP', 'ADD_CLAMP'):
            bad = sum(1 for q, want in pe.blend_map('J8', named[0], comb).items()
                      if o['texpix'].get(q) != want)
            if bad == 0:
                notes.append('R6j K3: COMB_FCN = SUB_CLAMP computes %s' %
                             ('source minus destination' if comb == 'SUB_CLAMP' else
                              'destination minus source' if comb == 'RSUB_CLAMP' else comb))
                break
        else:
            p.append('R6j K3: the subtract case matches no named reading of the combine function '
                     '(FAIL, measured)')
    # ---- K4: ROUND_ENABLE
    o, o4 = by.get('J7'), by.get('J4')
    if o is not None and o4 is not None and 'texpix' in o and 'texpix' in o4:
        same = sum(1 for q in o4['texpix'] if o['texpix'].get(q) == o4['texpix'][q])
        if same == len(o4['texpix']):
            notes.append('R6j K4: RB3D_CNTL.ROUND_ENABLE changes nothing here (%d pixels equal J4)' % same)
        else:
            fits = sorted(((sum(1 for q, want in pe.blend_map('J7', r).items()
                                if o['texpix'].get(q) != want), r) for r in pe.BLEND_RULES),
                          key=lambda t: (t[0], str(t[1])))
            if fits[0][0] == 0:
                notes.append('R6j K4: with ROUND_ENABLE the arithmetic is %s (J4 agreed on %d of %d)' %
                             (fits[0][1], same, len(o4['texpix'])))
            else:
                p.append('R6j K4: ROUND_ENABLE gives neither J4 nor a named arithmetic (FAIL, measured) '
                         '-- nearest %s' % [(d, r) for d, r in fits[:3]])
    # ---- K5: the wait between the draws
    o, o4 = by.get('J9'), by.get('J4')
    if o is not None and o4 is not None and 'texpix' in o and 'texpix' in o4:
        same = sum(1 for q in o4['texpix'] if o['texpix'].get(q) == o4['texpix'][q])
        notes.append('R6j K5: the same pair with a WAIT_UNTIL between the draws agrees with J4 on '
                     '%d of %d pixels%s' % (same, len(o4['texpix']),
                                            ' -- no wait is needed' if same == len(o4['texpix']) else ''))
