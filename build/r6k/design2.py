"""R6k design 2: the rule space after the cross-review (docs/R6K_PLAN.md 3-4, 8).

codex raised three behaviours the first space could not name; each is checked here rather than
believed.  The axes are now: coordinate layout, BR end, polarity, combination, bias, the width of
the x half, the width of the y half, signedness, and whether RE_CNTL bit 1 gates the unit.
"""
import itertools
import sys

MAP = [(x, y) for y in range(32) for x in range(32)]
R0, R1, R2 = ((6, 3), (20, 13)), ((10, 8), (26, 24)), ((2, 18), (14, 29))
RECT = {0: R0, 1: R1, 2: R2, 'inv': ((20, 13), (6, 3)), 'all': ((0, 0), (63, 63)),
        'bias': ((6 + 1440, 3 + 1440), (20 + 1440, 13 + 1440)),
        'hx': ((6 + 2048, 3), (20 + 2048, 13)),          # AS10: the high bit on x only
        'hy': ((6, 3 + 2048), (20, 13 + 2048)),          # AS13: on y only
        'neg': ((2048 - 16, 2048 - 16), (20, 13))}       # AS14: a top-left that is negative if signed
CASES = {'AS0': [], 'AS1': [(0, 0)], 'AS2': [(0, 1)], 'AS3': [(0, 0), (1, 0)], 'AS4': [(0, 0), (1, 1)],
         'AS5': [(2, 0)], 'AS6': [('inv', 0)], 'AS7': [('all', 0)], 'AS8': [(0, 0)],
         'AS9': [('bias', 0)], 'AS10': [('hx', 0)], 'AS11': [], 'AS12': [(0, 0)],
         'AS13': [('hy', 0)], 'AS14': [('neg', 0)]}
RECNTL = dict((c, 2) for c in CASES)
RECNTL['AS12'] = 0                                        # the one case without RE_CNTL bit 1
AX = list(itertools.product(('x_low', 'y_low'), ('br_incl', 'br_excl'), ('keep', 'drop'),
                            ('and', 'or'), ('b0', 'b1440'), (11, 16), (11, 16),
                            ('unsigned', 'signed'), ('free', 'gated')))
RULES = [('none',)] + [tuple(a) for a in AX]


def coord(v, w, sign):
    v &= (1 << w) - 1
    if sign == 'signed' and (v >> (w - 1)):
        v -= 1 << w
    return v


def inside(p, key, layout, br, bias, wx, wy, sign):
    (ax, ay), (bx, by) = RECT[key]
    if layout == 'y_low':
        ax, ay, bx, by = ay, ax, by, bx
    b = 1440 if bias == 'b1440' else 0
    ax, bx = coord(ax, wx, sign) - b, coord(bx, wx, sign) - b
    ay, by = coord(ay, wy, sign) - b, coord(by, wy, sign) - b
    hi = 0 if br == 'br_incl' else -1
    return ax <= p[0] <= bx + hi and ay <= p[1] <= by + hi


def picture(case, rule):
    if rule == ('none',):
        return frozenset(MAP)
    layout, br, pol, comb, bias, wx, wy, sign, gate = rule
    if gate == 'gated' and RECNTL[case] == 0:
        return frozenset(MAP)
    out = set()
    for p in MAP:
        keeps = []
        for key, exc in CASES[case]:
            ins = inside(p, key, layout, br, bias, wx, wy, sign)
            keeps.append(ins if (pol == 'keep') != bool(exc) else not ins)
        if not keeps or (all(keeps) if comb == 'and' else any(keeps)):
            out.add(p)
    return frozenset(out)


ORDER = sys.argv[1:] or ['AS1', 'AS2', 'AS3', 'AS4', 'AS5', 'AS6', 'AS8', 'AS9', 'AS10', 'AS12', 'AS13', 'AS14']
sig = {}
for r in RULES:
    sig.setdefault(tuple(picture(c, r) for c in ORDER), []).append(r)
print('%d rules -> %d classes over %s' % (len(RULES), len(sig), ' '.join(ORDER)))
big = sorted((v for v in sig.values() if len(v) > 1), key=lambda v: -len(v))
print('  largest class %d, classes > 1: %d' % (len(big[0]) if big else 1, len(big)))
for v in big[:3]:
    ax = [set(r[i] for r in v) for i in range(9)]
    print('   %d rules free in: %s' % (len(v), [sorted(a, key=str) for i, a in enumerate(ax) if len(a) > 1]))
print("  'none' alone: %s" % (sig[tuple(picture(c, ('none',)) for c in ORDER)] == [('none',)]))

# ---- the three cross-review claims, checked rather than believed
OLD = ['AS1', 'AS2', 'AS3', 'AS4', 'AS5', 'AS6', 'AS8', 'AS9', 'AS12']          # the case list before the review
OLDX = OLD + ['AS10']


def cls(order, rule):
    want = tuple(picture(c, rule) for c in order)
    return [r for r in RULES if tuple(picture(c, r) for c in order) == want]


base = ('x_low', 'br_incl', 'keep', 'and', 'b0', 16, 16, 'unsigned', 'free')
print('--- claim 1/2 (a 12-bit or mixed-width field is named as 16/16)')
for w in ((11, 16), (16, 11)):
    r = base[:5] + w + base[7:]
    print('   width %s: with the old cases -> %s; with AS10+AS13 -> %s' %
          (str(w), 'same class as 16/16' if r in cls(OLDX, base) else 'separated',
           'same class as 16/16' if r in cls(ORDER, base) else 'separated'))
print('--- claim 3 (signed 11-bit reads as unsigned 11-bit)')
s11 = ('x_low', 'br_incl', 'keep', 'and', 'b0', 11, 11, 'signed', 'free')
u11 = ('x_low', 'br_incl', 'keep', 'and', 'b0', 11, 11, 'unsigned', 'free')
print('   with the old cases + AS10: %s' % ('same class' if s11 in cls(OLDX, u11) else 'separated'))
print('   with AS14 too:             %s' % ('same class' if s11 in cls(ORDER, u11) else 'separated'))
print('--- the class each plausible answer lands in (new case list)')
for r in (base, base[:2] + ('drop',) + base[3:], base[:3] + ('or',) + base[4:],
          base[:1] + ('br_excl',) + base[2:], ('y_low',) + base[1:], base[:8] + ('gated',),
          ('none',)):
    print('   %-64s class %d' % (str(r), len(cls(ORDER, r))))
