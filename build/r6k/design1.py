"""R6k design 1: does the named rule space (docs/R6K_PLAN.md 3) separate over the planned cases?

Every rule is a function (case -> set of written pixels inside the 32x32 map).  Two rules that give
the same pictures on every case are one equivalence class; the design is good when the classes are
as small as the physics allows and, in particular, when 'none' (the registers do nothing) sits alone.
"""
import itertools

MAP = [(x, y) for y in range(32) for x in range(32)]
RECT = {0: ((6, 3), (20, 13)), 1: ((10, 8), (26, 24)), 2: ((2, 18), (14, 29)),
        'inv': ((20, 13), (6, 3)), 'all': ((0, 0), (63, 63)),
        'bias': ((6 + 1440, 3 + 1440), (20 + 1440, 13 + 1440)),
        'high': ((6 + 2048, 3 + 2048), (20 + 2048, 13 + 2048))}
# name: [(rect key, exclusive bit)] for the enabled slots
CASES = {'AS0': [], 'AS1': [(0, 0)], 'AS2': [(0, 1)], 'AS3': [(0, 0), (1, 0)],
         'AS4': [(0, 0), (1, 1)], 'AS5': [(2, 0)], 'AS6': [('inv', 0)], 'AS7': [('all', 0)],
         'AS8': [(0, 0)], 'AS9': [('bias', 0)], 'AS10': [('high', 0)], 'AS12': [(0, 0)]}
RECNTL = dict((c, 2) for c in ('AS0', 'AS1', 'AS2', 'AS3', 'AS4', 'AS5', 'AS6', 'AS7', 'AS8', 'AS9', 'AS10'))
RECNTL['AS12'] = 0                                # the one case without RE_CNTL.SCISSOR_ENABLE
AXES = list(itertools.product(('x_low', 'y_low'), ('br_incl', 'br_excl'),
                              ('keep', 'drop'), ('and', 'or'), ('b0', 'b1440'),
                              ('w16', 'w13', 'w11'), ('free', 'gated')))
RULES = [('none',)] + [tuple(a) for a in AXES]


def inside(p, key, layout, br, bias, width):
    (ax, ay), (bx, by) = RECT[key]
    if layout == 'y_low':                        # the halves read the other way round
        ax, ay, bx, by = ay, ax, by, bx
    m = (1 << int(width[1:])) - 1                 # the field each half really has
    ax, ay, bx, by = ax & m, ay & m, bx & m, by & m
    b = 1440 if bias == 'b1440' else 0
    ax, ay, bx, by = ax - b, ay - b, bx - b, by - b
    hi = 0 if br == 'br_incl' else -1
    return ax <= p[0] <= bx + hi and ay <= p[1] <= by + hi


def picture(case, rule):
    if rule == ('none',):
        return set(MAP)
    layout, br, pol, comb, bias, width, gate = rule
    if gate == 'gated' and RECNTL[case] == 0:    # the aux unit only bites with RE_CNTL bit 1
        return set(MAP)
    out = set()
    for p in MAP:
        keeps = []
        for key, exc in CASES[case]:
            ins = inside(p, key, layout, br, bias, width)
            keep = ins if (pol == 'keep') != bool(exc) else not ins
            keeps.append(keep)
        if not keeps or (all(keeps) if comb == 'and' else any(keeps)):
            out.add(p)
    return out


ORDER = ['AS12', 'AS0', 'AS1', 'AS2', 'AS3', 'AS4', 'AS5', 'AS6', 'AS8', 'AS9', 'AS10']
sig = {}
for r in RULES:
    k = tuple(frozenset(picture(c, r)) for c in ORDER)
    sig.setdefault(k, []).append(r)
print('%d rules -> %d distinguishable classes' % (len(RULES), len(sig)))
for k, v in sorted(sig.items(), key=lambda t: -len(t[1])):
    if len(v) > 1:
        print('  class of %d: %s' % (len(v), v))
alone = [v for v in sig.values() if v == [('none',)]]
print("'none' alone: %s" % bool(alone))
# which single case does the most separating?
for c in ORDER:
    s = set(frozenset(picture(c, r)) for r in RULES)
    print('  %-3s alone gives %2d distinct pictures (%d pixels in AS0)' % (c, len(s), len(picture(c, ('none',)))))
