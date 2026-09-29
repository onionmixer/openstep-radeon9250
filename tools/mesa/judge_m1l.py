#!/usr/bin/env python3
"""M1l: what a submission costs, read out of a timing transcript.

  judge_m1l.py <dir>          judge one run (t-accel.out, t-stock.out)
  judge_m1l.py --self-test

WHAT THIS DOES NOT CLAIM.  The fitted slope is not "the cost of a triangle" and
the intercept is not "the cost of an ioctl".  They are the local intercept and
the marginal wall time of THIS command stream on THIS scene: the slope carries
the words copied, the kernel's per-word verification, the rasterisation and the
memory traffic together, and the intercept carries the clock pair, the open,
the ioctl, the fixed prologue and whatever step effect the chosen points happen
to project onto n = 0.  A cross-review made exactly this correction and it is
kept in the wording of every line this file prints.

WHAT IT DOES CLAIM.  Over the points measured, a line fitted below the 4 KiB
user-buffer page boundary predicts the points above it -- or it does not, and
then the deviation names where the model breaks.

The card's own contribution is NOT subtracted here.  It is already known and it
is small: 118 client submissions across M1d..M1k give a median drain wait of
0 us and a maximum of 6 (docs/M1L_PLAN.md 6).  Subtracting a fitted intercept
from an unpaired median would be the statistical mistake the review named.
"""

import shutil
import atexit
import os
import re
import sys

# the user-side stream is 48 + 15n words; it crosses a 4 KiB page after n = 65
PAGE_N = 65
CLOCK_1PCT_US = 400        # gettimeofday resolves 4 us: 1% needs 400 us


def median(v):
    v = sorted(v)
    n = len(v)
    if not n:
        return None
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


# M1q: the leg an older transcript was drawn with.  Every run before M1q used a
# leg of 4 and a tile spacing of 5; M1q fixed the spacing at 2, so a leg=4 row
# from before and one from after are the same geometry but not the same tiling.
# The judge keeps them apart only where it matters (the cover gate); for the fit
# they are the same ten pixels a triangle.
OLD_LEG = 4

# path -> {'legs': [...], 'cover': [...], 'grid': [...]}, filled by read()
READ_EXTRA = {}


def read(path):
    """(clock, rows, pairs) -- rows are (n, kk, subs, rep, us), leg 4 only.

    M1q draws five legs in one transcript.  `rows` carries ONLY the leg-4 blocks
    so every fit and regime split in this judge keeps meaning what it meant
    before; the other legs live in `LEGS` and are read by m1q().
    """
    clock, rows, pairs = {}, [], []
    legs, cover, grid = [], [], []
    for ln in open(path, errors='replace'):
        m = re.match(r'RDNTRI run=\S+ step=prof-clock pair_us=(\d+) batch=(\d+) '
                     r'pts=(\d+) reps=(\d+)', ln)
        if m:
            clock = dict(pair_us=int(m.group(1)), batch=int(m.group(2)),
                         pts=int(m.group(3)), reps=int(m.group(4)))
            continue
        m = re.match(r'RDNTRI run=\S+ step=prof-cover leg=(\d+) px=(\d+) '
                     r'want=(\d+)', ln)
        if m:
            cover.append(tuple(int(m.group(i)) for i in range(1, 4)))
            continue
        m = re.match(r'RDNTRI run=\S+ step=prof-grid leg=(\d+) n=(\d+) '
                     r'subs=(\d+)', ln)
        if m:
            grid.append(tuple(int(m.group(i)) for i in range(1, 4)))
            continue
        # M1q added leg=; M1p added copyin=; both older shapes are still read so
        # earlier transcripts keep judging.
        m = re.match(r'RDNTRI run=\S+ step=prof n=(\d+) k=(\d+) subs=(\d+) '
                     r'rep=(\d+) copyin=(\d+) leg=(\d+) us=(\d+)', ln)
        if m:
            g = [int(m.group(i)) for i in range(1, 8)]
            legs.append((g[0], g[3], g[5], g[6]))
            if g[5] == OLD_LEG:
                rows.append((g[0], g[1], g[2], g[3], g[6]))
                pairs.append((g[0], g[3], g[4], g[6]))
            continue
        m = re.match(r'RDNTRI run=\S+ step=prof n=(\d+) k=(\d+) subs=(\d+) '
                     r'rep=(\d+) copyin=(\d+) us=(\d+)', ln)
        if m:
            g = [int(m.group(i)) for i in range(1, 7)]
            rows.append((g[0], g[1], g[2], g[3], g[5]))
            pairs.append((g[0], g[3], g[4], g[5]))
            legs.append((g[0], g[3], OLD_LEG, g[5]))
            continue
        m = re.match(r'RDNTRI run=\S+ step=prof n=(\d+) k=(\d+) subs=(\d+) '
                     r'rep=(\d+) us=(\d+)', ln)
        if m:
            g = [int(m.group(i)) for i in range(1, 6)]
            rows.append(tuple(g))
            legs.append((g[0], g[3], OLD_LEG, g[4]))
    # NOT function attributes: this judge calls read() again for the software
    # arm, and a second call would overwrite the first call's legs before
    # anything had read them.  The extras go in a dict keyed by PATH.
    READ_EXTRA[path] = dict(legs=legs, cover=cover, grid=grid)
    return clock, rows, pairs


def read_drv(path):
    """[(words, idle_us, rptr_us)] -- each client submission paired with the
    kernel's own timing of its spin.

    The pairing is positional on purpose: `RDN-R7B stage ... words=N` is printed
    when the stream is staged and `RDN-R5 wait ...` when that same submission
    finishes, with nothing of ours in between.  A `wait` with no `stage` before
    it belongs to a driver operation that is not a client submission (a ZPREP, an
    R6 case) and is dropped rather than counted as one.
    """
    out, words = [], None
    for ln in open(path, errors='replace'):
        m = re.search(r'RDN-R7B stage boot=\w+ words=(\d+)', ln)
        if m:
            words = int(m.group(1))
            continue
        # M2b APPENDED A TURN COUNT to every field (`idle=e/l/us/tN`), and this
        # regex was written before it.  It matched nothing in the first real log
        # that carried both a t-grid.drv AND an M2b driver, and the rule read
        # that as "the driver log was off".  The suffix is OPTIONAL here so the
        # transcripts of both eras are read -- a refinement, not a loosening: the
        # three fields the pairing needs are still required exactly where they
        # were, and a line missing them is still dropped.
        m = re.search(r'RDN-R5 wait fifo=\d+/-?\d+(?:/t\d+)? '
                      r'idle=\d+/-?\d+/(\d+)(?:/t\d+)? '
                      r'rptr=\d+/-?\d+/(\d+)(?:/t\d+)?', ln)
        if m and words is not None:
            out.append((words, int(m.group(1)), int(m.group(2))))
            words = None
    return out


def split(v):
    """(low, high, nlow) -- two regimes if the samples fall in two clusters.

    A RUN IS NOT ONE POPULATION.  Measured on the target: the driver logs 25
    lines a submission, and while syslogd is still delivering them a submission
    costs about ten milliseconds more than it does after syslogd starts
    dropping.  Every arm of a fresh-boot run therefore steps DOWN partway
    through -- t-poison went 10.0 ms for four repetitions and 0.73 ms for five.

    A median over that reports whichever regime had more samples, which is how
    the same run showed n=60 at 8352 us and n=66 at 1735 us and called it a
    line.  So the two are separated and BOTH are reported: the low one is what
    a submission costs, the high one is what the logging adds when it lands.
    """
    v = sorted(v)
    if len(v) < 3:
        return (v[0] if v else None), None, len(v)
    # the widest relative gap, if it is wide enough to be a regime and not noise
    gi, gr = None, 1.6
    for i in range(len(v) - 1):
        r = v[i + 1] / max(1e-9, v[i])
        if r > gr:
            gr, gi = r, i
    if gi is None:
        return median(v), None, len(v)
    lo, hi = v[:gi + 1], v[gi + 1:]
    # THREE clusters happen: a steady floor, the logging regime, and the odd
    # 132 ms outlier.  One gap test would then call the middle one "low".
    # Recurse into the low part until it holds no gap, and report the regime
    # nearest above it -- measured at n=72, where a single outlier had made the
    # floor read 6620 us instead of 1739.
    dlo, dhi, dn = split(lo)
    if dhi is not None:
        return dlo, dhi, dn
    return median(lo), median(hi), len(lo)


def per_submission(rows):
    """{n: microseconds for ONE submission carrying n triangles}

    The value is the LOW regime when a run has two (see split()); `regimes`
    below carries what was split off, so nothing is quietly dropped.
    """
    by = {}
    for n, kk, subs, rep, us in rows:
        # a block holds `subs` submissions; with batching each carries n
        # triangles, without it each carries one.  Either way the block is
        # `kk` repetitions of "draw n triangles".
        by.setdefault(n, []).append(us / float(kk))
    return dict((n, split(v)[0]) for n, v in by.items())


def regimes(rows):
    """{n: (low, high, nlow, ntotal)} -- only the n that really split"""
    by = {}
    for n, kk, subs, rep, us in rows:
        by.setdefault(n, []).append(us / float(kk))
    out = {}
    for n, v in by.items():
        lo, hi, nlo = split(v)
        if hi is not None:
            out[n] = (lo, hi, nlo, len(v))
    return out


def fit(points):
    """least squares a + b*n over [(n, t)] -- closed form, no imports"""
    k = len(points)
    if k < 2:
        return None, None
    sx = sum(n for n, _ in points)
    sy = sum(t for _, t in points)
    sxx = sum(n * n for n, _ in points)
    sxy = sum(n * t for n, t in points)
    den = k * sxx - sx * sx
    if den == 0:
        return None, None
    b = (k * sxy - sx * sy) / float(den)
    a = (sy - b * sx) / float(k)
    return a, b


# M1q: what tri_oracle.cover(MEASURED) says each leg covers.  Written here as
# well as in the test program so a transcript cannot agree with itself: the
# target prints `want=` from ITS copy and this judge checks BOTH against this
# one.
LEG_PX = {2: 3, 4: 10, 8: 36, 16: 136, 32: 528}
# the verdict thresholds of docs/M1Q_PLAN.md 8, as numbers
M1Q_FILL_RATIO = 20.0   # L=32 at least this many times L=4 -> the card's fill
M1Q_FLAT_RATIO = 2.0    # within this -> the word side
SUBMITS_PER_BLOCK = 8   # PROF_MIN_SUBMITS in the test program
LOW_CLUSTER = 5         # of PROF_REPS = 9; see m1q()/m1r's note


def lsq3(pts):
    """least squares for us = a + b*L + c*P over [(L, P, us)] -- returns
    (a, b, c) or None.  Solved with Cramer's rule on the 3x3 normal equations:
    no numpy on the target-facing tools, and three unknowns do not need it."""
    n = len(pts)
    if n < 4:
        return None
    S = [[0.0] * 4 for _ in range(3)]
    basis = lambda L, P: (1.0, float(L), float(P))
    for L, P, us in pts:
        b = basis(L, P)
        for i in range(3):
            for j in range(3):
                S[i][j] += b[i] * b[j]
            S[i][3] += b[i] * float(us)

    def det3(m):
        return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))

    A = [[S[i][j] for j in range(3)] for i in range(3)]
    d = det3(A)
    if abs(d) < 1e-9:
        return None
    out = []
    for k in range(3):
        M = [[(S[i][3] if j == k else A[i][j]) for j in range(3)] for i in range(3)]
        out.append(det3(M) / d)
    return tuple(out)


def m1q(d, ap):
    """docs/M1Q_PLAN.md 8, as a procedure.  (bad, ok, note)"""
    bad, ok, note = [], [], []
    extra = READ_EXTRA.get(ap, {})
    cover = extra.get('cover') or []
    legs = extra.get('legs') or []

    # ---- gate: the geometry really changed, proved by PIXELS and not by a clock
    if not cover:
        note.append('no prof-cover lines: this transcript predates M1q, so the '
                    'leg sweep is not judged')
        return bad, ok, note
    seen = set()
    for leg, px, want in cover:
        seen.add(leg)
        if leg not in LEG_PX:
            bad.append('prof-cover names leg=%d, which the oracle has no count '
                       'for' % leg)
        elif want != LEG_PX[leg]:
            bad.append('leg=%d: the target says it wants %d pixels, the oracle '
                       'says %d -- the two copies of the table disagree'
                       % (leg, want, LEG_PX[leg]))
        elif px != LEG_PX[leg]:
            bad.append('leg=%d: %d pixels drawn, %d expected -- the geometry is '
                       'NOT what this rung varies, so its times are not read'
                       % (leg, px, LEG_PX[leg]))
        else:
            ok.append('leg=%-2d drew %d pixels, exactly what the raster rule '
                      'predicts' % (leg, px))
    if bad:
        return bad, ok, note

    # ---- the kernel's own timing of its spin, per submission
    # ---- did the grid run at all?  A cell that never ran leaves no line, and a
    #      missing file looks exactly like a quiet PASS unless it is named.
    cells = [(gl, gn) for gl in (1, 4) for gn in (0, 1, 2, 3)]
    missing = []
    for gl, gn in cells:
        f = os.path.join(d, 't-grid-%d-%d.out' % (gl, gn))
        if not os.path.exists(f) or 'step=prof-grid-done' not in open(
                f, errors='replace').read():
            missing.append('%d-%d' % (gl, gn))
    if missing and len(missing) == len(cells):
        note.append('no grid cell ran: this transcript set predates the M1q grid')
    elif missing:
        bad.append('grid cells that did not finish: %s' % ', '.join(missing))
    else:
        ok.append('all %d grid cells ran to their done line' % len(cells))

    drv = os.path.join(d, 't-grid.drv')
    if os.path.exists(drv):
        rows = read_drv(drv)
        if not rows:
            bad.append('t-grid.drv has no (stage, wait) pair: the driver log was '
                       'off, or the collection dropped it')
        else:
            byw = {}
            for words, iu, ru in rows:
                byw.setdefault(words, []).append(iu + ru)
            for w in sorted(byw):
                v = byw[w]
                ok.append('words=%-5d %2d submissions, the card made us wait '
                          '%s us (median %.1f)'
                          % (w, len(v), '/'.join(str(x) for x in v), median(v)))
    else:
        note.append('no t-grid.drv: the kernel side of M1q was not collected, '
                    'so the verdict below rests on the wall clock alone')

    # ---- M2g: THE GRID'S OWN PAIRS, counted by the seed each cell used.
    #
    # t-grid.drv is the whole boot's log, so the (stage, wait) pairs above are
    # every loud arm's, not the grid's: on run 790250798, 8 of 248.  "No pair
    # at all" therefore cannot see a grid that ran QUIET while other arms were
    # loud -- which is exactly what flipping the log's default could produce
    # (docs/M2G_PLAN.md 8, C2b).  Each cell prints the seed of its last
    # submission (`end-tri ... seed=`), and the driver echoes it on that
    # submission's `RDN-R5 begin ... op=12 arg=`; so each cell must own at least
    # one pair.  Fourteen earlier runs all had >= 1 per cell (python).
    if os.path.exists(drv):
        gpairs, gw, gb = [], None, None
        for ln in open(drv, errors='replace'):
            m_ = re.search(r'RDN-R7B stage boot=\w+ words=(\d+)', ln)
            if m_:
                gw, gb = int(m_.group(1)), None
                continue
            m_ = re.search(r'RDN-R5 begin boot=\w+ op=12 arg=([0-9a-f]{8})', ln)
            if m_ and gw is not None:
                gb = int(m_.group(1), 16)
                continue
            if 'RDN-R5 wait fifo=' in ln and gw is not None:
                gpairs.append(gb)
                gw = None
        seeds, orphan = {}, []
        for gl, gn in cells:
            f = os.path.join(d, 't-grid-%d-%d.out' % (gl, gn))
            if not os.path.exists(f):
                continue
            m_ = re.search(r'step=end-tri .*?seed=(\d+)', open(f, errors='replace').read())
            if m_:
                seeds['%d-%d' % (gl, gn)] = int(m_.group(1)) & 0xffffffff
        if seeds:
            for cell, sd in sorted(seeds.items()):
                if not any(b is not None and 0 <= sd - b < 8 for b in gpairs):
                    orphan.append(cell)
            if orphan:
                bad.append('grid cells with no (stage, wait) pair of their OWN in '
                           't-grid.drv: %s.  The pairs that are there belong to other '
                           'loud arms -- this cell ran quiet, or its lines were lost'
                           % ', '.join(orphan))
            else:
                ok.append('every grid cell owns its (stage, wait) pair (%d cells, by '
                          'seed; %d of the %d pairs in the log are the grid\'s)'
                          % (len(seeds), sum(1 for b in gpairs if b is not None and
                             any(0 <= sd - b < 8 for sd in seeds.values())),
                             len(gpairs)))

    # ---- the verdict: leg 32 against leg 4, at the same n
    by = {}
    for n, rep, leg, us in legs:
        by.setdefault((n, leg), []).append(us)
    ns = sorted(set(n for (n, leg) in by if leg == 4 and (n, 32) in by))
    if not ns:
        note.append('no n has both leg=4 and leg=32: nothing to compare')
        return bad, ok, note
    #
    # THE RATIO IS OF SLOPES, NOT OF BLOCKS.
    #
    # A block carries the fixed cost too, and the fixed cost is the same at
    # every leg, so a ratio of block times is diluted by it -- at n=1 almost
    # entirely.  What this rung asks about is the MARGINAL cost, which is the
    # slope of us-per-submission against n (cross-review #17).
    slope = {}
    for leg in sorted(set(l for (_n, l) in by)):
        pts = [(n, median(by[(n, leg)]) / float(SUBMITS_PER_BLOCK))
               for (n, l) in sorted(by) if l == leg]
        a_, b_ = fit(pts)
        if b_ is not None:
            slope[leg] = b_
            ok.append('leg=%-2d us = %.1f + %.3f*n a submission  (%d points)'
                      % (leg, a_, b_, len(pts)))
    ratios = []
    for n in ns:
        a, b = median(by[(n, 4)]), median(by[(n, 32)])
        if a and a > 0:
            ok.append('n=%-3d leg=4 %.0f us, leg=32 %.0f us -- %.2fx a block'
                      % (n, a, b, b / a))
    if 4 in slope and 32 in slope and slope[4] > 0:
        ratios = [slope[32] / slope[4]]
    if ratios:
        r = median(ratios)
        if r >= M1Q_FILL_RATIO:
            ok.append('VERDICT C: the leg-32 SLOPE is %.1fx the leg-4 slope '
                      'with the SAME number of words a triangle -- the marginal cost is the '
                      "card's fill, and the kernel waits for it synchronously"
                      % r)
        elif r <= M1Q_FLAT_RATIO:
            ok.append('VERDICT not-C: %.2fx for 52.8x the pixels -- the marginal '
                      'cost is on the WORD side (which is not yet A or B: the '
                      'next rung narrows the vertex format)' % r)
        else:
            f = lsq3([(leg, n * LEG_PX[leg],
                       median(by[(n, leg)]) / float(SUBMITS_PER_BLOCK))
                      for (n, leg) in sorted(by) if leg in LEG_PX])
            note.append('MIXED: %.2fx, between the two thresholds' % r)
            if f:
                note.append('  us = %.1f + %.3f*L + %.5f*pixels' % f)
            else:
                note.append('  too few distinct cells to fit a + b*L + c*P')
    return bad, ok, note


def judge(d):
    ok, bad, note = [], [], []
    ap = os.path.join(d, 't-accel.out')
    if not os.path.exists(ap):
        return ['no t-accel.out in %s' % d], [], []
    clock, rows, pairs = read(ap)
    if not rows:
        return ['the transcript has no "prof" lines: this run was not a timing '
                'run, or the judge and it disagree about the shape'], [], []

    # ---- the clock measured itself
    if 'pair_us' not in clock:
        bad.append('the run did not measure its own clock pair')
    else:
        ok.append('the clock pair measured itself at %d us' % clock['pair_us'])

    # ---- every block must be long enough to be worth 1%
    short = sorted(set(n for n, kk, subs, rep, us in rows
                       if us < CLOCK_1PCT_US))
    if short:
        note.append('blocks under %d us at n = %s: those points carry more '
                    'than 1%% clock error' % (CLOCK_1PCT_US, short))
    else:
        ok.append('every block ran at least %d us, so the clock costs under 1%%'
                  % CLOCK_1PCT_US)

    t = per_submission(rows)
    rg = regimes(rows)
    if rg:
        n0 = sorted(rg)[0]
        lo0, hi0, nlo, ntot = rg[n0]
        note.append('this run has TWO regimes: %d of %d repetitions at n=%d ran '
                    'at %.0f us and the rest at %.0f (%.1fx).  The driver logs '
                    '25 lines a submission and syslogd stops delivering them '
                    'partway through; the numbers below are the LOW regime, '
                    'which is the submission without that'
                    % (ntot - nlo, ntot, n0, hi0, lo0, hi0 / max(1.0, lo0)))
        for n in sorted(rg):
            l, h, a_, b_ = rg[n]
            note.append('  n=%-3d low %.0f us, high %.0f us (%d of %d high)'
                        % (n, l, h, b_ - a_, b_))
    lo = sorted(n for n in t if n <= PAGE_N)
    hi = sorted(n for n in t if n > PAGE_N)
    if len(lo) < 2:
        return ['fewer than two points below the page boundary: nothing to fit'], ok, note

    a, b = fit([(n, t[n]) for n in lo])
    if a is None:
        return ['the fit is degenerate'], ok, note
    ok.append('below the page boundary: %d points, marginal %.2f us per '
              'triangle, intercept %.1f us (NOT "the ioctl": see the header)'
              % (len(lo), b, a))

    # ---- how well the line describes the points it was fitted to.
    #
    # The residual is measured against EACH POINT'S OWN value, not against the
    # largest.  A curve through {1,18,36,60} with 0.08n^2 of bend misses the
    # smallest point by 62% of itself and by only 7% of the largest -- scaling
    # by the largest would have called that curve a line.
    resid = [(n, t[n] - (a + b * n)) for n in lo]
    worst_n, worst = max(resid, key=lambda x: abs(x[1]) / max(1.0, t[x[0]]))
    rel = abs(worst) / max(1.0, t[worst_n])
    if rel > 0.15:
        bad.append('the fitted line misses n=%d by %.1f us, which is %.0f%% of '
                   'that point: t(n) is not affine over %s'
                   % (worst_n, worst, rel * 100, lo))
    else:
        ok.append('the line describes every point it was fitted to within '
                  '%.0f%% of that point (worst at n=%d, %.1f us)'
                  % (rel * 100, worst_n, worst))

    # ---- and whether it predicts the points above the boundary
    for n in hi:
        pred = a + b * n
        err = t[n] - pred
        rel = abs(err) / max(1.0, pred)
        msg = ('n=%d: measured %.1f us, the sub-page line predicts %.1f '
               '(%+.1f us, %.0f%%)' % (n, t[n], pred, err, rel * 100))
        if rel > 0.15:
            note.append(msg + ' -- the page boundary shows')
        else:
            ok.append(msg + ' -- the line holds across the boundary')

    # ---- the batch, priced
    sp = os.path.join(d, 't-nobatch.out')
    if os.path.exists(sp):
        _c2, r2, _p2 = read(sp)
        t2 = per_submission(r2)
        both = sorted(set(t) & set(t2))
        for n in both:
            if n < 2:
                continue
            # unbatched draws n triangles as n submissions
            saved = t2[n] - t[n]
            ok.append('n=%d: batched %.1f us, one-at-a-time %.1f us -- the '
                      'batch saves %.1f us (%.1fx)'
                      % (n, t[n], t2[n], saved,
                         t2[n] / max(1e-9, t[n])))
    else:
        note.append('no t-nobatch.out: the batch is not priced in this run')

    # ---- the open/close, priced -- TWICE, because the log-on pair cannot do it
    #
    # M2f: the pair below used to be the only one, and it said 642.9, 657.2 and
    # 26.9 us in three runs -- a factor of 24 -- while the HELD arm was stable to
    # within 24 us across all three.  The swing is in the not-held arm, and the
    # not-held arm is the one that pays rdnDevOpen's and rdnDevClose's IOLog once
    # a submission: those two lines are outside the quiet gate.  With the submit
    # log ALSO on, the difference is two moving costs subtracted from each other.
    #
    # So the quiet pair is priced too, and the two are printed together.  When
    # they disagree by more than the run's own bars, the log-on one is not the
    # open/close cost and this says so.
    ocs = {}
    for base_, arm_, what_ in (('t-accel.out', 't-hold.out', 'the submit log ON'),
                               ('t-quiet.out', 't-qhold.out', 'the submit log OFF')):
        bp_, hp_ = os.path.join(d, base_), os.path.join(d, arm_)
        if not (os.path.exists(bp_) and os.path.exists(hp_)):
            note.append('no %s: open/close is not priced with %s in this run'
                        % (arm_, what_))
            continue
        _cb, rb_, _pb = read(bp_)
        _ch, rh_, _ph = read(hp_)
        tb_, th_ = per_submission(rb_), per_submission(rh_)
        both = sorted(set(tb_) & set(th_))
        if not both:
            note.append('%s and %s share no block size' % (base_, arm_))
            continue
        n0 = both[0]
        diff = tb_[n0] - th_[n0]
        ocs[what_] = diff
        # A HELD ARM THAT IS SLOWER IS NOT A PRICE.
        #
        # Holding the node REMOVES work -- one open and one close a submission,
        # and the two log lines they write.  A negative "cost" means something
        # else moved, and printing it as a price would put a number in the
        # record that says removing work made the machine slower.  Measured on
        # run 790202535: the quiet pair came out -168.7 us, uniformly across all
        # five legs and all six block sizes (133..169), which is a constant per
        # submission that nobody has named.
        if diff < 0.0:
            bad.append('%s: holding the node made it SLOWER by %.1f us a '
                       'submission (%.1f held vs %.1f reopened, n=%d).  Holding '
                       'only removes work, so this is not the open/close cost -- '
                       'it is something else, and it is not priced here'
                       % (what_, -diff, th_[n0], tb_[n0], n0))
            continue
        ok.append('holding the node with %s: n=%d costs %.1f us instead of %.1f '
                  '-- open/close (and its own two log lines) is %.1f us'
                  % (what_, n0, th_[n0], tb_[n0], diff))
        for n in both[1:]:
            ok.append('  %s n=%d: held %.1f us, reopened %.1f us'
                      % (what_, n, th_[n], tb_[n]))
    if len(ocs) == 2:
        a_, b_ = ocs['the submit log ON'], ocs['the submit log OFF']
        ok.append('open/close priced both ways: %.1f us with the submit log on, '
                  '%.1f us with it off (%+.1f).  The knob between them touches no '
                  'open and no close, so a difference here is the LOG moving, not '
                  'the open/close' % (a_, b_, b_ - a_))

    # ---- the driver's fixed path, priced.  Every stream refused at word 0:
    # same ioctl, same log, none of the verification, ring copy or drawing.
    pp = os.path.join(d, 't-poison.out')
    if os.path.exists(pp):
        _c5, r5, _p5 = read(pp)
        t5 = per_submission(r5)
        both = sorted(set(t) & set(t5))
        for n in both:
            share = t5[n] / max(1e-9, t[n])
            ok.append('n=%d: refused-at-word-0 %.1f us of %.1f -- %.0f%% of the '
                      'submission is the driver\'s fixed path and its log, '
                      'before any work' % (n, t5[n], t[n], share * 100))
    else:
        note.append('no t-poison.out: the fixed path is not priced in this run')

    # ---- the driver's own log, priced (M1n).  Same batching, same node
    # handling; the only difference is that the driver swallows its 25 lines.
    qp = os.path.join(d, 't-quiet.out')
    if os.path.exists(qp):
        _c6, r6, _p6 = read(qp)
        t6 = per_submission(r6)
        for n in sorted(set(t) & set(t6)):
            ok.append('n=%d: log on %.1f us, log off %.1f us -- the driver\'s 25 '
                      'lines cost %.1f us (%.0f%% of the submission)'
                      % (n, t[n], t6[n], t[n] - t6[n],
                         100.0 * (t[n] - t6[n]) / max(1e-9, t[n])))
    else:
        note.append('no t-quiet.out: the driver log is not priced in this run')

    # ---- M1p: the two ways of handing the words over, A B B A.
    #
    # The pairs are adjacent in time and the two orders alternate, so a linear
    # drift cancels in the mean of the two differences.  M1n learned that the
    # hard way: a 620 us between-arm drift made a 450 us difference look real
    # and a +730 us one look real in the other direction.
    if pairs:
        by = {}
        for n, rep, use, us in pairs:
            by.setdefault((n, rep), {})[use] = us
        diffs = {}
        # NOT `d`: that is the directory this function was given, and rebinding
        # it here made the judge die three lines later with a type error.
        for (n, rep), both in by.items():
            if 0 in both and 1 in both:
                diffs.setdefault(n, []).append(both[0] - both[1])
        for n in sorted(diffs):
            v = sorted(diffs[n])
            mid = v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] +
                                                     v[len(v) // 2]) / 2.0
            ok.append('n=%d: window minus cached, median of %d adjacent pairs = '
                      '%+.0f us  (%+.2f us a triangle)'
                      % (n, len(v), mid, mid / float(max(1, n))))
    else:
        note.append('no copyin= in this transcript: the two paths were not '
                    'alternated, so nothing prices them')

    # ---- against software
    kp = os.path.join(d, 't-stock.out')
    if os.path.exists(kp):
        _c3, r3, _p3 = read(kp)
        t3 = per_submission(r3)
        for n in sorted(set(t) & set(t3)):
            ok.append('n=%d: card %.1f us, software %.1f us -- %s'
                      % (n, t[n], t3[n],
                         'the card wins' if t[n] < t3[n] else
                         'SOFTWARE WINS by %.2fx' % (t[n] / max(1e-9, t3[n]))))
    else:
        note.append('no t-stock.out: there is no software baseline in this run')

    # ---- M1r: the sent-triangle ring, priced against the arm next to it
    qp = os.path.join(d, 't-quiet.out')
    np_ = os.path.join(d, 't-nosent.out')
    if os.path.exists(qp) and os.path.exists(np_):
        for path, tag in ((qp, 'ring on'), (np_, 'ring off')):
            _c, _r, _p = read(path)
        lg = {}
        for path, tag in ((qp, 'on'), (np_, 'off')):
            rows_ = [(n, rep, leg, us) for (n, rep, leg, us)
                     in (READ_EXTRA.get(path, {}).get('legs') or []) if leg == 4]
            by_ = {}
            for n, rep, leg, us in rows_:
                by_.setdefault(n, []).append(us / float(SUBMITS_PER_BLOCK))
            # THE LOW CLUSTER, not the median.  Every contaminant here pushes a
            # block UP -- syslogd still delivering, an NFS hiccup, another
            # process -- so the plain median of nine carries them and the two
            # arms' medians then differ by whichever arm was unluckier.  Taking
            # the median of the five lowest turned a +0.04 us answer with the
            # WRONG SIGN into a monotone one (recorded in docs/M1R_PLAN.md 8).
            pts = [(n, median(sorted(by_[n])[:LOW_CLUSTER]))
                   for n in sorted(by_)]
            a_, b_ = fit(pts) if len(pts) > 1 else (None, None)
            lg[tag] = b_
            if b_ is not None:
                ok.append('sent ring %-3s: us = %.1f + %.3f*n a submission'
                          % (tag, a_, b_))
        if lg.get('on') is not None and lg.get('off') is not None:
            d_ = lg['on'] - lg['off']
            ok.append('the sent-triangle ring costs %+.3f us a triangle '
                      '(%.0f%% of the %0.2f us marginal cost)'
                      % (d_, 100.0 * d_ / max(1e-9, lg['on']), lg['on']))
        # THE ARM HAS TO SAY WHICH WAY IT RAN.  A `sent n=` check would be
        # vacuous here: the profiling run returns before sent() is ever called,
        # so the only witness in a timing transcript is the knobs line.
        txt = open(np_, errors='replace').read()
        if 'step=knobs sentlog=0' not in txt:
            bad.append('t-nosent.out does not say sentlog=0: the arm ran with '
                       'the ring ON and prices nothing')
        if 'step=knobs sentlog=1' not in open(qp, errors='replace').read():
            bad.append('t-quiet.out does not say sentlog=1: the two arms may '
                       'not differ in the knob at all')
    else:
        note.append('no t-quiet.out/t-nosent.out pair: the sent ring is not '
                    'priced in this run')

    # ---- M1s: the bisection.  stock | hook only | hook+unit+ioctl | all of it
    def leg4slope(path):
        rows_ = [(n, rep, leg, us) for (n, rep, leg, us)
                 in (READ_EXTRA.get(path, {}).get('legs') or []) if leg == 4]
        by_ = {}
        for n, rep, leg, us in rows_:
            by_.setdefault(n, []).append(us / float(SUBMITS_PER_BLOCK))
        pts = [(n, median(sorted(by_[n])[:LOW_CLUSTER])) for n in sorted(by_)]
        return fit(pts) if len(pts) > 1 else (None, None)

    arms = {}
    for tag, name in (('stock', 't-stock.out'), ('hook', 't-nullsend.out'),
                      ('poison', 't-poison.out'), ('all', 't-quiet.out')):
        pth = os.path.join(d, name)
        if os.path.exists(pth):
            read(pth)
            a_, b_ = leg4slope(pth)
            if b_ is not None:
                arms[tag] = b_
    if 'hook' in arms:
        txt = open(os.path.join(d, 't-nullsend.out'), errors='replace').read()
        if 'step=knobs' in txt and 'nullsend=1' not in txt:
            bad.append('t-nullsend.out does not say nullsend=1: the arm sent '
                       'after all and bisects nothing')
        # THE HOOK'S COUNTER, NOT THE UNIT'S.  `step=end-tri entered=` counts
        # calls into the tri unit, which this arm never makes -- so reading it
        # as "did the hook run?" would call a working bisection a failure.  The
        # hook's own line is `step=end ... triangles=N delegated=N`.
        mh = re.search(r'step=end installs=\d+ leaves=\d+ triangles=(\d+) '
                       r'delegated=(\d+)', txt)
        mt = re.search(r'step=end-tri entered=\d+ submitted=(\d+)', txt)
        if mt and int(mt.group(1)) != 0:
            bad.append('t-nullsend.out submitted %s triangles: the send was '
                       'not skipped' % mt.group(1))
        elif mh is None or mt is None:
            bad.append('t-nullsend.out has no end counters, so nothing proves '
                       'the arm ran the hook without sending')
        elif int(mh.group(1)) == 0:
            bad.append('t-nullsend.out never entered the hook, so "submitted=0" '
                       'proves nothing')
        elif int(mh.group(2)) != int(mh.group(1)):
            bad.append('t-nullsend.out entered the hook %s times but delegated '
                       '%s: every one of them had to go to software'
                       % (mh.group(1), mh.group(2)))
        else:
            ok.append('the bisection arm entered the hook %s times, delegated '
                      'all of them and submitted 0' % mh.group(1))
    if 'stock' in arms and 'hook' in arms:
        ok.append('the HOOK itself costs %+.3f us a triangle (%.3f - %.3f)'
                  % (arms['hook'] - arms['stock'], arms['hook'], arms['stock']))
    if 'hook' in arms and 'poison' in arms:
        ok.append('the tri unit and the ioctl cost %+.3f us a triangle '
                  '(%.3f - %.3f)'
                  % (arms['poison'] - arms['hook'], arms['poison'], arms['hook']))
    if 'all' in arms and 'stock' in arms and 'hook' in arms:
        ok.append('the send that really draws costs %+.3f us a triangle '
                  '(%.3f - %.3f + %.3f: the software draw is added back)'
                  % (arms['all'] - arms['hook'] + arms['stock'],
                     arms['all'], arms['hook'], arms['stock']))

    # ---- M1t: the vertex writer inlined, priced in two places and witnessed
    #      by the WORDS, not by a counter
    def sentwords(path):
        """[(k, [words])] from the `tri k w0 w1 ...` rows"""
        out = []
        for ln in open(path, errors='replace'):
            m = re.match(r'RDNTRI run=\S+ tri (\d+)((?: [0-9a-f]{8})+)\s*$', ln)
            if m:
                out.append((int(m.group(1)), m.group(2).split()))
        return out

    for base, arm, what in (('t-quiet.out', 't-inline.out',
                             'inlining the vertex writer, with the card'),
                            ('t-nullsend.out', 't-nullinl.out',
                             'inlining the vertex writer, without the card'),
                            ('t-quiet.out', 't-group.out',
                             'the whole group in one call'),
                            # M2a: the submission WBINVD off.  The knob touches
                            # only when a cache line reaches memory, so the WORDS
                            # must be identical -- if they are not, the card read
                            # something the CPU did not write, which is the whole
                            # question this arm asks.
                            ('t-stage.out', 't-nowb.out',
                             'the submission WBINVD skipped'),
                            # M2b: polling before the sleep.  Same shape of
                            # knob -- it runs once a submission, not once a
                            # triangle -- so the fixed cost is again the result.
                            ('t-stage.out', 't-spin.out',
                             'the wait polling before it sleeps'),
                            # M2c: the stage instrument itself.  t-notime is
                            # t-stage with `time 0`, so the difference is the
                            # seventeen clock reads and nothing else -- the one
                            # number three earlier estimates disagreed about
                            # (2.84, 3.74, 4.57 us a read).  Same shape again:
                            # once a submission, so the intercept is the result.
                            ('t-stage.out', 't-notime.out',
                             'the stage instrument switched off'),
                            # M2d: the fourth cell.  Each of these turns the ONE
                            # knob the other pair already priced, but from the
                            # other starting point -- which is the whole test:
                            # if the knobs are independent the same two numbers
                            # come back, and if they are not, they do not.
                            ('t-notime.out', 't-bothoff.out',
                             'the WBINVD skipped with the instrument already off'),
                            ('t-nowb.out', 't-bothoff.out',
                             'the instrument switched off with the WBINVD already skipped')):
        # M2a: THIS PAIR MOVES THE FIXED COST ON PURPOSE.
        #
        # Every earlier pair turns a knob that touches per-triangle work only, so
        # a differing intercept meant contamination and the guard below refused to
        # price it.  M2a's knob removes an instruction that runs ONCE A
        # SUBMISSION, so its whole effect is in the intercept -- demanding the
        # intercepts match would refuse the very result.  The rule is SPLIT, not
        # dropped: the slope must still match (the knob is not per-triangle), and
        # the intercept must move DOWNWARD (an upward move is contamination).
        fixed_moves = arm in ('t-nowb.out', 't-spin.out', 't-notime.out',
                              't-bothoff.out')
        # NOT `ap`: that is t-accel.out, which m1q() is handed further down.
        # Rebinding it here made every M1q verdict vanish -- the same shadowing
        # the M1p block above already records once, in a different name.
        bpath = os.path.join(d, base)
        apath = os.path.join(d, arm)
        if not (os.path.exists(bpath) and os.path.exists(apath)):
            continue
        atxt = open(apath, errors='replace').read()
        if 'step=knobs' in atxt and 'nullsend=' in atxt and \
                'RDNMesaInline' not in atxt and 'inline=' not in atxt:
            pass                    # the knobs line predates M1t; the words decide
        wb, wa = sentwords(bpath), sentwords(apath)
        # THE NULLSEND PAIR SENDS NOTHING, so it has no words to compare -- and
        # demanding them there would fail an arm that is working exactly as
        # designed.  What must hold is that the two arms AGREE about having
        # nothing: one with rows and one without is a real difference.
        nb_ = re.search(r'step=end-sent n=(\d+)',
                        open(bpath, errors='replace').read())
        na_ = re.search(r'step=end-sent n=(\d+)', atxt)
        empty = (nb_ and na_ and nb_.group(1) == '0' and na_.group(1) == '0'
                 and not wb and not wa)
        if empty:
            note.append('%s vs %s: neither arm sent anything, so the words say '
                        'nothing here -- the price below is the CPU alone'
                        % (base, arm))
        elif not wb or not wa:
            bad.append('%s/%s: one arm logged sent triangles and the other did '
                       'not (%s rows vs %s)'
                       % (base, arm, len(wb), len(wa)))
        elif [w for _k, w in wb] != [w for _k, w in wa]:
            n_ = sum(1 for x, y in zip(wb, wa) if x[1] != y[1])
            bad.append('%s vs %s: %d of %d logged triangles differ WORD FOR '
                       'WORD -- the inlined path is not writing the same thing'
                       % (base, arm, n_, min(len(wb), len(wa))))
        if empty or (wb and wa and [w for _k, w in wb] == [w for _k, w in wa]):
            if not empty:
                ok.append('%s vs %s: all %d logged triangles identical word for '
                          'word' % (base, arm, len(wa)))
            read(bpath)
            read(apath)
            _ab, bb = leg4slope(bpath)
            _aa, ba = leg4slope(apath)
            # TWO ARMS WITH DIFFERENT INTERCEPTS ARE NOT COMPARABLE.
            #
            # The fixed cost a submission is the same for both arms by
            # construction -- they differ in one knob that touches only
            # per-triangle work.  When they do not match, something OUTSIDE the
            # knob moved: the measured case was a `quiet` lease that ran out
            # partway through the second arm, so it paid for the driver's 25 log
            # lines and came back with a 1,616 us intercept against 529 and a
            # NEGATIVE slope.  Pricing that would have reported -2.17 us a
            # triangle as if it were a saving.
            if bb is None or ba is None:
                pass
            # An ABSOLUTE floor as well as a ratio: the no-card pair has
            # intercepts of about 1 us and -0, and a ratio test on two numbers
            # near zero calls every honest pair incomparable -- it did, on the
            # first run of this rule.
            elif fixed_moves:
                # the intercept is the RESULT here; the slope is the guard
                if _aa > _ab + max(20.0, 0.05 * abs(_ab)):
                    bad.append('%s vs %s: the fixed cost went UP (%.0f -> %.0f us a '
                               'submission).  This knob can only remove work, so '
                               'something outside it moved'
                               % (base, arm, _ab, _aa))
                elif abs(ba - bb) > max(0.25, 0.20 * abs(bb)):
                    bad.append('%s vs %s: the MARGINAL cost moved (%.3f -> %.3f us a '
                               'triangle).  This knob runs once a submission, so a '
                               'per-triangle change means something else moved'
                               % (base, arm, bb, ba))
                else:
                    ok.append('%s: the fixed cost %.0f -> %.0f us a submission '
                              '(%+.0f), and the marginal cost did not move '
                              '(%.3f -> %.3f us a triangle)'
                              % (what, _ab, _aa, _aa - _ab, bb, ba))
            elif abs(_ab - _aa) > max(20.0, 0.25 * max(abs(_ab), abs(_aa))):
                bad.append('%s vs %s: the fixed costs differ (%.0f vs %.0f us a '
                           'submission), so the arms are not comparable -- '
                           'something outside the knob moved (a spent quiet '
                           'lease does this).  NOT priced'
                           % (base, arm, _ab, _aa))
            else:
                ok.append('%s: %.3f -> %.3f, %+.3f us a triangle'
                          % (what, bb, ba, ba - bb))

    # ---- ARE THE ARMS THAT SHOULD AGREE ACTUALLY AGREEING?
    #
    # These seven run quiet, with the instrument on and the WBINVD on, and the
    # knobs between them touch either nothing measurable (spin, closed at -3 %)
    # or per-triangle work only.  Their n=1 block must therefore be the same
    # number.  On the M2e driver it was, to 2.5 us across all seven.
    #
    # On the M2f-b driver it split into two clusters 210 us apart, and WHICH arm
    # landed in which cluster changed between two runs of the same boot.  Every
    # pair that straddles the split then reports the gap as its knob's price --
    # that is how "open/close" came out -159.8, then +22.2, then +222.0 in three
    # runs.  Nothing here is worth pricing until this spread is small.
    band = {}
    for nm in ('t-quiet.out', 't-nosent.out', 't-inline.out', 't-group.out',
               't-stage.out', 't-spin.out', 't-stage2.out'):
        pth = os.path.join(d, nm)
        if not os.path.exists(pth):
            continue
        _cb, rb_, _pb = read(pth)
        tb_ = per_submission(rb_)
        if 1 in tb_:
            band[nm] = tb_[1]
    if len(band) >= 4:
        lo_, hi_ = min(band.values()), max(band.values())
        spread = hi_ - lo_
        shape = ', '.join('%s %.0f' % (k[2:-4], v) for k, v in sorted(band.items()))
        if spread > 40.0:
            bad.append('the arms that must agree do not: %.0f us between the '
                       'cheapest and the dearest (%s).  They run quiet with the '
                       'same two knobs and differ only in things measured at or '
                       'near zero, so this spread is contamination -- every pair '
                       'that straddles it reports the spread as its knob\'s price'
                       % (spread, shape))
        else:
            ok.append('the %d arms that must agree do, to %.1f us (%s)'
                      % (len(band), spread, shape))

    # ---- M2g: AN ARM THAT MUST PAY THE LOG, PAYS IT.
    #
    # The log is off by default now, so an arm that forgot its `loud N` runs
    # quiet -- and every price built on it comes out as a quiet arm's: "the log
    # costs 0 us", with no FAIL anywhere (docs/M2G_PLAN.md 4-3).  The runner
    # checker pins the `loud` calls in the script; this pins the EFFECT, from the
    # wall clock, with nothing from syslog: a loud arm is at least 300 us dearer
    # than its quiet partner.  Measured on five runs the smallest such gap was
    # 1,034 us (t-hold) and 1,082 us (ABBA) -- 3.4x and 3.6x the bar -- while
    # the quiet arms agree to 2.6 us.
    def fixed1_(nm):
        pth = os.path.join(d, nm)
        if not os.path.exists(pth):
            return None
        _c, r_, _p = read(pth)
        t_ = per_submission(r_)
        return t_.get(1)
    qbase = fixed1_('t-stage.out')
    pairs_ = [(a_, qbase, 't-stage') for a_ in ('t-accel', 't-nobatch', 't-hold', 't-accel2')]
    ab2_, ab3_ = fixed1_('t-ab2.out'), fixed1_('t-ab3.out')
    if ab2_ is not None and ab3_ is not None:
        for a_ in ('t-ab1', 't-ab4'):
            pairs_.append((a_, (ab2_ + ab3_) / 2.0, 't-ab2/t-ab3'))
    quietly = []
    for a_, q_, qn_ in pairs_:
        v_ = fixed1_(a_ + '.out')
        if v_ is None or q_ is None:
            continue
        if v_ - q_ < 300.0:
            quietly.append('%s %.0f vs %s %.0f' % (a_, v_, qn_, q_))
    if quietly:
        bad.append('M2g: arms that must pay the submit log did not: %s.  Under 300 us '
                   'dearer than the quiet partner means the log was off -- every '
                   'price built on these arms is a quiet arm\'s' % '; '.join(quietly))
    elif qbase is not None:
        ok.append('M2g: every log-on arm is dearer than its quiet partner by more '
                  'than 300 us -- the log was really on where it had to be')

    # ---- M2e: DID THE BOOT REALLY START WITH THE WBINVD SKIPPED?
    #
    # M2e made the skip the driver's default, and the only thing that can say
    # whether the driver ON THE MACHINE has it is the machine's own log.  The
    # driver prints `nowb=` on every state line; the FIRST one in the boot is
    # before any arm has touched a knob, so it is the default.
    #
    # The log window starts at the boot nonce (the runner fetches
    # `sed -n '/boot=<nonce>/,$p'`), so "first in the file" is "first in the
    # boot" even when this is the second run of the same boot.
    drvp_ = os.path.join(d, 't-grid.drv')
    if os.path.exists(drvp_):
        first_nowb = None
        for ln in open(drvp_, errors='replace'):
            m_ = re.search(r'RDN-R5 state .* nowb=(\d)', ln)
            if m_:
                first_nowb = int(m_.group(1))
                break
        if first_nowb is None:
            note.append('no RDN-R5 state line carries nowb=: this driver predates M2a')
        elif first_nowb == 1:
            ok.append('M2e: the boot started with nowb=1 -- the installed driver skips '
                      'the submission WBINVD by default')
        else:
            bad.append('M2e: the boot started with nowb=0 -- the installed driver still '
                       'does the submission WBINVD by default, so every arm in this run '
                       'is measuring the OLD default and the M2d cells do not mean what '
                       'they say')

    # ---- M2d: ARE THE TWO KNOBS ADDITIVE?  and how much of the answer is drift
    #
    # Four cells: t-stage (both on), t-notime (instrument off), t-nowb (WBINVD
    # off), t-bothoff (both off).  If the knobs are independent then
    #
    #     saving(both) == saving(instrument) + saving(WBINVD)
    #
    # and the residual below is zero.  THE SIGN IS NAMED IN WORDS, not left to
    # the reader: this plan's first draft had it backwards (docs/M2D_PLAN.md
    # 2-2), and a bare +/- would have carried that mistake into the report.
    #
    # NEGATIVE means the two OVERLAPPED -- turning both off saves less than the
    # sum, because each was already paying part of the other's cost.  POSITIVE
    # means they AMPLIFIED -- both off saves more than the sum.
    #
    # AND THE RESIDUAL IS REPORTED BESIDE THE DRIFT, never alone.  t-bothoff is
    # the last measured arm, so anything that shifted the fixed cost late in the
    # run lands in the residual and looks exactly like an interaction; the
    # measured counter-example is a true-additive 210 that reads 235 under a
    # 25 us late shift, which BOTH pairs above accept (each only refuses a rise).
    # t-accel/t-accel2 are the same arm at the two ends of the run, so their
    # difference is that shift, measured.  A residual no bigger than the drift
    # is not an interaction.
    cells = {}
    for nm in ('t-stage.out', 't-notime.out', 't-nowb.out', 't-bothoff.out',
               't-stage2.out', 't-spin.out', 't-accel.out', 't-accel2.out'):
        pth = os.path.join(d, nm)
        if os.path.exists(pth):
            read(pth)
            a_, b_ = leg4slope(pth)
            if a_ is not None:
                cells[nm] = a_
    # THE BAR IS A QUIET ARM, NOT t-accel2.
    #
    # The first version of this used t-accel/t-accel2, and on the first real run
    # it reported -354 us -- six times the effect M2c had just measured.  Taking
    # t-stage's quiet 491 out of both shows what it was: the driver's log cost
    # 1,441 us a submission at the start of the run and 1,087 at the end, and
    # 1,085 is the figure the runner's own header gives for it.  That is syslogd
    # settling, and the quiet arms never pay it.  A bar that big would have
    # swallowed every result this rung can produce.
    drift = None
    if 't-stage.out' in cells and 't-stage2.out' in cells:
        drift = cells['t-stage2.out'] - cells['t-stage.out']
        ok.append('the quiet drift across the whole run: t-stage repeated as the '
                  'last arm, %.0f -> %.0f us a submission (%+.0f)'
                  % (cells['t-stage.out'], cells['t-stage2.out'], drift))
    else:
        note.append('the quiet drift was not measured: t-stage and t-stage2 are '
                    'not both here, so nothing bounds a late shift')
    if 't-accel.out' in cells and 't-accel2.out' in cells:
        note.append('the LOG-ON drift, reported but NOT used as the bar: '
                    't-accel %.0f -> t-accel2 %.0f (%+.0f).  These arms carry the '
                    "driver's 25 log lines, whose own cost moves as syslogd "
                    'settles, so this number is about the log and not the machine'
                    % (cells['t-accel.out'], cells['t-accel2.out'],
                       cells['t-accel2.out'] - cells['t-accel.out']))
    # A SECOND BAR: THE KNOB THAT DOES (ALMOST) NOTHING.
    #
    # The drift bar answers "did the machine shift?"  It does not answer "how
    # big a fixed-cost difference does this method produce from a knob with no
    # real effect?"  t-spin is that knob -- M2b measured it and closed it at
    # -3.3 % -- so whatever it appears to move is the floor of what can be
    # resolved here.  On the first M2d run the drift was 2 us and the spin pair
    # moved 6, and the residual was 8: naming it against the drift alone would
    # have called a 1.3x result an interaction.
    spinbar = None
    if 't-stage.out' in cells and 't-spin.out' in cells:
        spinbar = cells['t-spin.out'] - cells['t-stage.out']
    need4 = ('t-stage.out', 't-notime.out', 't-nowb.out', 't-bothoff.out')
    if all(k in cells for k in need4):
        S, N, W, B = (cells[k] for k in need4)
        s_time, s_wb = S - N, S - W
        saving = S - B
        resid = saving - (s_time + s_wb)
        line = ('M2d: both knobs off saves %.0f us a submission; the parts are '
                '%.0f (instrument) + %.0f (WBINVD) = %.0f.  Residual %+.0f us'
                % (saving, s_time, s_wb, s_time + s_wb, resid))
        # A RESIDUAL IS NAMED ONLY WHEN IT BEATS THE DRIFT.
        #
        # An exact zero never happens in a measurement, so "independent" cannot
        # be a test for resid == 0 -- it is what a residual the run cannot
        # resolve MEANS.  The drift is the resolution: the same arm at the two
        # ends of the run.
        bars = [('drift', drift), ('the spin pair', spinbar)]
        have = [(nm, v) for nm, v in bars if v is not None]
        if not have:
            note.append(line + '.  NOT NAMED: neither bar was measured, so '
                        'nothing says whether this is an interaction or noise')
        else:
            bname, bar = max(have, key=lambda kv: abs(kv[1]))
            how = ' and '.join('%s %+.0f' % (nm, v) for nm, v in have)
            ratio = abs(resid) / abs(bar) if bar else float('inf')
            if abs(resid) <= abs(bar):
                ok.append(line + '; the bars are %s us, and the residual does '
                          'not beat the biggest of them (%s) -- so as far as '
                          'this run can resolve, the two knobs are INDEPENDENT '
                          'and the addition was right' % (how, bname))
            else:
                which = ('NEGATIVE -- the two knobs OVERLAPPED, each was already '
                         'paying part of the other' if resid < 0 else
                         'POSITIVE -- the two knobs AMPLIFIED, both off saves '
                         'more than the sum')
                edge = ('.  ONLY JUST: %.1fx the biggest bar (%s), which is the '
                        'edge of what this run resolves -- do not act on the '
                        'sign alone' % (ratio, bname) if ratio <= 2.0 else
                        '.  %.1fx the biggest bar (%s)' % (ratio, bname))
                ok.append(line + '; the bars are %s us.  %s%s'
                          % (how, which, edge))
    elif 't-bothoff.out' in cells:
        note.append('M2d: t-bothoff is here but one of the other three cells is '
                    'not, so the additivity question cannot be asked')

    # ---- M1v: the group path has to say it ran, and lose nothing
    gp = os.path.join(d, 't-group.out')
    if os.path.exists(gp):
        gt = open(gp, errors='replace').read()
        m_ = re.search(r'step=end-group groups=(\d+) declined=(\d+) lost=(\d+) '
                       r'tris=(\d+) installs=(\d+)', gt)
        if m_ is None:
            bad.append('t-group.out has no end-group line: this build predates '
                       'M1v or the arm did not finish')
        else:
            g, dec, lost, tris, inst = (int(m_.group(i)) for i in range(1, 6))
            if lost != 0:
                bad.append('t-group.out lost %d groups -- a group was declined '
                           'with nothing to hand it back to' % lost)
            elif inst == 0 or g == 0:
                bad.append('t-group.out never installed the table or never got '
                           'a group (installs=%d groups=%d): the arm measures '
                           'nothing' % (inst, g))
            elif tris == 0:
                bad.append('t-group.out took %d groups but drew 0 triangles '
                           'through them' % g)
            else:
                ok.append('the group path installed %d times, took %d groups, '
                          'drew %d triangles, declined %d, lost 0'
                          % (inst, g, tris, dec))
        # and the OTHER arms must not have used it
        for other in ('t-quiet.out', 't-accel.out'):
            op_ = os.path.join(d, other)
            if not os.path.exists(op_):
                continue
            mo = re.search(r'step=end-group groups=(\d+)',
                           open(op_, errors='replace').read())
            if mo and int(mo.group(1)) != 0:
                bad.append('%s took %s groups with the knob off: the two arms '
                           'do not differ in the knob' % (other, mo.group(1)))

    # ---- M1x: where the kernel's 366 us goes, if the boot log was fetched
    drvp = os.path.join(d, 't-grid.drv')
    if os.path.exists(drvp):
        mt = None
        for ln in open(drvp, errors='replace'):
            m_ = re.search(r'RDN-R5 tstage boot=\w+ ops=(\d+) gates=(\d+) '
                           r'pre=(\d+) s1ring=(\d+) s1read=(\d+) s2asm=(\d+) '
                           r's2ring=(\d+) flush=(\d+) tail=(\d+)'
                           r'(?: fence=(\d+) wait=(\d+))?(?: put=(\d+))?', ln)
            if m_:
                mt = [int(m_.group(i)) for i in range(1, 10)]
                # M1z appended two totals that are NOT extra stages: they are
                # pieces of s1ring + s2ring, gathered inside cpR6Submit.
                mz = (None if m_.group(10) is None
                      else (int(m_.group(10)), int(m_.group(11))))
                # M2b: the cpPut loops, the half of "the rest" that was a guess
                mp = None if m_.group(12) is None else int(m_.group(12))
        if mt is None:
            note.append('no RDN-R5 tstage line: this driver predates M1x, or the '
                        'tdump was not issued')
        elif mt[0] == 0:
            bad.append('the tstage line says ops=0: nothing accumulated, so the '
                       'stage times are of no operation at all -- either the arm '
                       'never issued `time 1`, or it did and no timed operation '
                       'reached the end.  Zero cannot tell those apart')
        else:
            ops = mt[0]
            names = ('gates', 'preamble', 'stage1 ring', 'stage1 read-backs',
                     'stage2 assemble', 'stage2 ring', 'pixcache flush', 'tail')
            tot = sum(mt[1:])
            ok.append("the kernel op over %d submissions: %.1f us, by stage:"
                      % (ops, tot / float(ops)))
            for nm, v in zip(names, mt[1:]):
                ok.append('    %-18s %7.1f us  %5.1f %%'
                          % (nm, v / float(ops), 100.0 * v / max(1, tot)))
            # ---- M1z: what the two ring stages are made of
            if mz is None:
                note.append('no fence=/wait= on the tstage line: this driver '
                            'predates M1z')
            else:
                fence, wait = mz
                ring = mt[3] + mt[6]            # s1ring + s2ring
                rest = ring - fence - wait
                ok.append('    the two ring submits, %.1f us, split:'
                          % (ring / float(ops)))
                pieces = [('cpFence (WBINVD)', fence), ('the two waits', wait)]
                if mp is None:
                    pieces.append(('puts + doorbell', rest))
                else:
                    pieces.append(('the cpPut loops', mp))
                    pieces.append(('doorbell + posting', rest - mp))
                for nm, v in pieces:
                    ok.append('      %-18s %7.1f us  %5.1f %%'
                              % (nm, v / float(ops), 100.0 * v / max(1, ring)))
                if fence + wait > ring:
                    bad.append('fence (%.1f) + wait (%.1f) is more than the two ring '
                               'stages (%.1f): the instrument measures something '
                               'outside what it claims to be inside'
                               % (fence / float(ops), wait / float(ops), ring / float(ops)))
                elif mp is not None and mp > rest:
                    bad.append('the put loops (%.1f us) are more than what is left of '
                               'the ring stages after the fence and the waits (%.1f us)'
                               % (mp / float(ops), rest / float(ops)))
                elif rest < 0:
                    bad.append('what is left for the puts and the doorbell is %.1f us, '
                               'which cannot be negative' % (rest / float(ops)))

    # ---- M1q: the leg sweep, its geometry gate and its verdict
    qb, qo, qn = m1q(d, ap)
    bad.extend(qb)
    ok.extend(qo)
    note.extend(qn)
    return bad, ok, note


def self_test():
    import tempfile
    fails = 0

    def one(label, cond):
        nonlocal fails
        fails += 0 if cond else 1
        print('  %-4s %s' % ('ok' if cond else 'FAIL', label))

    one('the median of an even list is the mean of the middle two',
        median([1, 2, 3, 4]) == 2.5 and median([5]) == 5)
    # M1m: one population must NOT be split, two must be, and the low one is
    # the answer.  The numbers are the measured t-poison arm of run 790085103.
    lo1, hi1, _n1 = split([100, 101, 99, 102, 100])
    one('a single regime is not split (%s, %s)' % (lo1, hi1), hi1 is None)
    lo2, hi2, nlo2 = split([9992, 10029, 10184, 870, 899, 875, 868, 896, 866])
    one('the measured two-regime arm splits at the gap: low %.0f, high %.0f, '
        '%d low' % (lo2, hi2, nlo2),
        hi2 is not None and 800 < lo2 < 1000 and hi2 > 9000 and nlo2 == 6)
    one('and per_submission reports the LOW one',
        abs(per_submission([(7, 1, 1, r, u) for r, u in enumerate(
            [9992, 10029, 10184, 870, 899, 875, 868, 896, 866])])[7] - lo2) < 1e-9)
    a, b = fit([(1, 110.0), (10, 200.0)])
    one('the fit recovers a line exactly (a=100, b=10): got a=%.3f b=%.3f'
        % (a, b), abs(a - 100) < 1e-9 and abs(b - 10) < 1e-9)
    a, b = fit([(n, 50.0 + 3.0 * n) for n in (1, 18, 36, 60)])
    one('and over the real sweep points too', abs(a - 50) < 1e-9 and abs(b - 3) < 1e-9)
    one('two identical points are degenerate, not a silent zero',
        fit([(5, 1.0), (5, 2.0)]) == (None, None))

    d = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, d, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch

    def write(name, rows, batch=1, pair=4):
        with open(os.path.join(d, name), 'w') as f:
            f.write('RDNTRI run=1 step=prof-clock pair_us=%d batch=%d pts=6 '
                    'reps=3\n' % (pair, batch))
            for n, kk, subs, rep, us in rows:
                f.write('RDNTRI run=1 step=prof n=%d k=%d subs=%d rep=%d us=%d\n'
                        % (n, kk, subs, rep, us))

    # a clean affine world: 50 us fixed + 3 us a triangle, 8 submissions a block
    clean = []
    for rep in range(3):
        for n in (1, 18, 36, 60, 66, 72):
            clean.append((n, 8, 8, rep, int(8 * (50 + 3 * n))))
    write('t-accel.out', clean)
    bad, ok, note = judge(d)
    one('a clean affine transcript passes (%d ok, %d bad)' % (len(ok), len(bad)),
        not bad)
    one('and the line is reported as predicting across the boundary',
        any('the line holds across the boundary' in x for x in ok))

    # the page boundary shows: the two high points cost 40% more
    bent = []
    for n, kk, subs, rep, us in clean:
        bent.append((n, kk, subs, rep, int(us * 1.4) if n > PAGE_N else us))
    write('t-accel.out', bent)
    bad, ok, note = judge(d)
    one('a 40% step above the boundary is REPORTED, not smoothed away',
        any('the page boundary shows' in x for x in note))

    # a curved world must fail the fit, not be averaged into a line
    curved = []
    for rep in range(3):
        for n in (1, 18, 36, 60):
            curved.append((n, 8, 8, rep, int(8 * (50 + 3 * n + 0.08 * n * n))))
    write('t-accel.out', curved)
    bad, ok, note = judge(d)
    one('a quadratic transcript FAILS the affine fit', bool(bad))

    # blocks too short to resolve are named
    tiny = [(n, 8, 8, rep, 40) for rep in range(3) for n in (1, 18, 36, 60)]
    write('t-accel.out', tiny)
    bad, ok, note = judge(d)
    one('blocks under 400 us are named as under-resolved',
        any('more than 1% clock error' in x for x in note))

    # software winning must be said in those words
    write('t-accel.out', clean)
    soft = [(n, 8, 8, rep, int(8 * (10 + 0.5 * n)))
            for rep in range(3) for n in (1, 18, 36, 60, 66, 72)]
    write('t-stock.out', soft)
    bad, ok, note = judge(d)
    one('when software is faster the judge SAYS so',
        any('SOFTWARE WINS' in x for x in ok))

    # ---- M1q: the leg sweep
    def writeq(name, legpx, ratio, badcover=None):
        """a transcript with the M1q shape: five legs, the leg-32 block `ratio`
        times the leg-4 block, and a cover line per leg"""
        with open(os.path.join(d, name), 'w') as f:
            f.write('RDNTRI run=1 step=prof-clock pair_us=4 batch=1 pts=6 '
                    'reps=3\n')
            for leg in sorted(legpx):
                px = legpx[leg] if badcover is None or leg != badcover \
                    else legpx[leg] + 1
                f.write('RDNTRI run=1 step=prof-cover leg=%d px=%d want=%d\n'
                        % (leg, px, LEG_PX[leg]))
            for rep in range(3):
                for n in (1, 18, 36, 60, 66, 72):
                    for leg in sorted(legpx):
                        k = 1.0 + (ratio - 1.0) * (LEG_PX[leg] - LEG_PX[4]) \
                            / float(LEG_PX[32] - LEG_PX[4])
                        # the FIXED cost does not scale with the leg -- only
                        # the per-triangle part does.  Written this way on
                        # purpose: it makes the block ratio smaller than the
                        # slope ratio, which is the dilution the verdict must
                        # not fall for.
                        f.write('RDNTRI run=1 step=prof n=%d k=8 subs=8 rep=%d '
                                'copyin=0 leg=%d us=%d\n'
                                % (n, rep, leg, int(8 * (50 + 3 * n * k))))

    os.path.exists(os.path.join(d, 't-stock.out')) and \
        os.unlink(os.path.join(d, 't-stock.out'))
    writeq('t-accel.out', LEG_PX, 1.0)
    bad, ok, note = judge(d)
    one('M1q: a flat leg sweep passes the cover gate and says WORD side',
        not bad and any('VERDICT not-C' in x for x in ok))
    one('M1q: and the leg-4 rows are what the old fit still uses',
        any('the line holds across the boundary' in x for x in ok))

    writeq('t-accel.out', LEG_PX, 52.8)
    bad, ok, note = judge(d)
    one('M1q: a fill-shaped leg sweep says VERDICT C',
        any('VERDICT C' in x for x in ok))
    one('M1q: and it reads the SLOPE, not the block (the n=1 block is only '
        '1.1x while the slope is 52.8x)',
        any('n=1   leg=4' in x and 'a block' in x and
            float(x.split('--')[1].split('x')[0]) < 5.0 for x in ok)
        and any('VERDICT C: the leg-32 SLOPE is 52' in x for x in ok))

    writeq('t-accel.out', LEG_PX, 52.8, badcover=32)
    bad, ok, note = judge(d)
    one('M1q: one wrong pixel count STOPS the verdict',
        any('the geometry is NOT what this rung varies' in x for x in bad)
        and not any('VERDICT' in x for x in ok))

    # the driver's own spin, paired with the stream it belongs to
    with open(os.path.join(d, 't-grid.drv'), 'w') as f:
        f.write('RDN-R7B stage boot=abcd1234 words=1082 staged=1 dropped=0 ok=1\n')
        f.write('RDN-R5 wait fifo=1/0 idle=2/0/3310 rptr=1/0/0 idle2=1/0 dc=1/0\n')
        f.write('RDN-R5 wait fifo=1/0 idle=1/0/999 rptr=1/0/0 idle2=1/0 dc=1/0\n')
    writeq('t-accel.out', LEG_PX, 52.8)
    bad, ok, note = judge(d)
    one('M1q: the kernel wait is paired with its own stream, and an unpaired '
        'wait is dropped',
        any('words=1082' in x and '3310' in x for x in ok)
        and not any('999' in x for x in ok))

    # THE SAME FIXTURE IN THE SHAPE THE DRIVER ACTUALLY PRINTS TODAY.
    #
    # The two lines above are the PRE-M2b shape, and they are the reason this
    # self-test passed while the real log read as empty: the fixture was written
    # once and never followed the driver.  Both shapes are asserted from here on,
    # so a future field can only be added by making one of them fail.
    with open(os.path.join(d, 't-grid.drv'), 'w') as f:
        f.write('RDN-R7B stage boot=abcd1234 words=1082 staged=1 dropped=0 ok=1\n')
        f.write('RDN-R5 wait fifo=1/0/t0 idle=2/0/3310/t7 rptr=1/0/0/t1 '
                'idle2=1/0/t0 dc=1/0/t0\n')
        f.write('RDN-R5 wait fifo=1/0/t0 idle=1/0/999/t0 rptr=1/0/0/t0 '
                'idle2=1/0/t0 dc=1/0/t0\n')
    bad, ok, note = judge(d)
    one('M1q: the M2b wait line, with its turn counts, is read the same way',
        any('words=1082' in x and '3310' in x for x in ok)
        and not any('999' in x for x in ok))

    # and a wait line that has LOST the microseconds is still dropped, not
    # counted as a zero -- the guard the optional suffix must not have relaxed
    with open(os.path.join(d, 't-grid.drv'), 'w') as f:
        f.write('RDN-R7B stage boot=abcd1234 words=1082 staged=1 dropped=0 ok=1\n')
        f.write('RDN-R5 wait fifo=1/0/t0 idle=2/0/t7 rptr=1/0/t1 '
                'idle2=1/0/t0 dc=1/0/t0\n')
    bad, ok, note = judge(d)
    one('M1q: a wait line without the microseconds is NOT read as zero',
        any('no (stage, wait) pair' in x for x in bad))
    os.unlink(os.path.join(d, 't-grid.drv'))

    # a HALF-RUN grid must be a failure, not a quiet pass
    for gl in (1, 4):
        for gn in (0, 1, 2, 3):
            if (gl, gn) == (4, 3):
                continue
            with open(os.path.join(d, 't-grid-%d-%d.out' % (gl, gn)), 'w') as f:
                f.write('RDNTRI run=1 step=prof-grid leg=4 n=1 subs=2\n')
                f.write('RDNTRI run=1 step=prof-grid-done leg=4 n=1\n')
    bad, ok, note = judge(d)
    one('M1q: a grid cell that never finished is a FAILURE, not a quiet pass',
        any('did not finish: 4-3' in x for x in bad))
    for gl in (1, 4):
        for gn in (0, 1, 2, 3):
            f = os.path.join(d, 't-grid-%d-%d.out' % (gl, gn))
            os.path.exists(f) and os.unlink(f)

    # ---- M1r: the ring is priced, and a run that forgot the knob FAILS
    def writeq2(name, slope, sentlog):
        with open(os.path.join(d, name), 'w') as f:
            f.write('RDNTRI run=1 step=knobs sentlog=%d batch=1\n' % sentlog)
            f.write('RDNTRI run=1 step=prof-clock pair_us=4 batch=1 pts=6 '
                    'reps=3\n')
            for rep in range(3):
                for n in (1, 18, 36, 60, 66, 72):
                    f.write('RDNTRI run=1 step=prof n=%d k=8 subs=8 rep=%d '
                            'copyin=0 leg=4 us=%d\n'
                            % (n, rep, int(8 * (50 + slope * n))))
    writeq('t-accel.out', LEG_PX, 1.0)
    writeq2('t-quiet.out', 2.0, 1)
    writeq2('t-nosent.out', 1.79, 0)
    bad, ok, note = judge(d)
    # NOT a string match on '+0.21': the fit prints three decimals and the
    # literal missed by a digit, which is a self-test failing for its own
    # spelling rather than for the rule.
    priced = [x for x in ok if 'the sent-triangle ring costs' in x]
    one('M1r: the sent ring is priced from the two adjacent arms (%s)'
        % (priced[0].split('costs ')[1].split(' ')[0] if priced else 'nothing'),
        bool(priced) and
        abs(float(priced[0].split('costs ')[1].split(' ')[0]) - 0.209) < 0.01)
    writeq2('t-nosent.out', 1.79, 1)
    bad, ok, note = judge(d)
    one('M1r: an arm that forgot the knob is a FAILURE, not a price',
        any('does not say sentlog=0' in x for x in bad))
    for f_ in ('t-quiet.out', 't-nosent.out'):
        os.unlink(os.path.join(d, f_))

    # ---- M1s: the bisection arm has to prove it skipped the send
    def writes(name, slope, nullsend, submitted, entered=500):
        with open(os.path.join(d, name), 'w') as f:
            f.write('RDNTRI run=1 step=knobs sentlog=1 batch=1 nullsend=%d\n'
                    % nullsend)
            f.write('RDNTRI run=1 step=prof-clock pair_us=4 batch=1 pts=6 '
                    'reps=3\n')
            for rep in range(3):
                for n in (1, 18, 36, 60, 66, 72):
                    f.write('RDNTRI run=1 step=prof n=%d k=8 subs=8 rep=%d '
                            'copyin=0 leg=4 us=%d\n'
                            % (n, rep, int(8 * (50 + slope * n))))
            f.write('RDNTRI run=1 step=end installs=1 leaves=0 triangles=%d '
                    'delegated=%d nosw=0\n'
                    % (entered, entered if submitted == 0 else 0))
            f.write('RDNTRI run=1 step=end-tri entered=%d submitted=%d maps=0 '
                    'opens=0\n' % (entered, submitted))
    writeq('t-accel.out', LEG_PX, 1.0)
    writes('t-stock.out', 1.30, 0, 500)
    writes('t-nullsend.out', 1.75, 1, 0)
    writes('t-poison.out', 2.40, 0, 500)
    bad, ok, note = judge(d)
    one('M1s: the arm proves it ran the hook and sent nothing',
        any('delegated all of them and submitted 0' in x for x in ok))
    one('M1s: the hook alone is priced at 0.45 us',
        any('the HOOK itself costs +0.450' in x for x in ok))
    one('M1s: the unit and the ioctl are priced at 0.65 us',
        any('the tri unit and the ioctl cost +0.650' in x for x in ok))
    writes('t-nullsend.out', 1.75, 1, 12)
    bad, ok, note = judge(d)
    one('M1s: an arm that still submitted is a FAILURE',
        any('submitted 12 triangles' in x for x in bad))
    writes('t-nullsend.out', 1.75, 0, 0)
    bad, ok, note = judge(d)
    one('M1s: and an arm that forgot the knob is a FAILURE',
        any('does not say nullsend=1' in x for x in bad))
    for f_ in ('t-stock.out', 't-nullsend.out', 't-poison.out'):
        p_ = os.path.join(d, f_)
        os.path.exists(p_) and os.unlink(p_)

    # ---- M1t: the words witness it, and a changed word is a FAILURE
    def writet(name, slope, words, fixed=50.0):
        with open(os.path.join(d, name), 'w') as f:
            f.write('RDNTRI run=1 step=knobs sentlog=1 batch=1 nullsend=0\n')
            f.write('RDNTRI run=1 step=prof-clock pair_us=4 batch=1 pts=6 '
                    'reps=3\n')
            for rep in range(3):
                for n in (1, 18, 36, 60, 66, 72):
                    f.write('RDNTRI run=1 step=prof n=%d k=8 subs=8 rep=%d '
                            'copyin=0 leg=4 us=%d\n'
                            % (n, rep, int(8 * (fixed + slope * n))))
            f.write('RDNTRI run=1 step=end-sent n=8 kept=2 words=15\n')
            for k, w in enumerate(words):
                f.write('RDNTRI run=1 tri %d %s\n' % (k, ' '.join(w)))
    same = [['%08x' % (0x1000 + i) for i in range(15)],
            ['%08x' % (0x2000 + i) for i in range(15)]]
    writeq('t-accel.out', LEG_PX, 1.0)
    writet('t-quiet.out', 2.00, same)
    writet('t-inline.out', 1.55, same)
    bad, ok, note = judge(d)
    one('M1t: identical words let the price through',
        any('all 2 logged triangles identical word for word' in x for x in ok)
        and any(x.startswith('inlining the vertex writer, with the card: '
                             '2.000 -> 1.5') for x in ok))
    changed = [same[0], same[1][:7] + ['deadbeef'] + same[1][8:]]
    writet('t-inline.out', 1.55, changed)
    bad, ok, note = judge(d)
    one('M1t: ONE changed word is a FAILURE and no price is printed',
        any('differ WORD FOR WORD' in x for x in bad)
        and not any('inlining the vertex writer' in x for x in ok))

    writet('t-inline.out', 1.55, same)
    with open(os.path.join(d, 't-inline.out')) as f_:
        t_ = f_.read()
    # same slope, ten times the fixed cost: the arms are not comparable
    t_ = re.sub(r'us=(\d+)', lambda m_: 'us=%d' % (int(m_.group(1)) + 8000), t_)
    with open(os.path.join(d, 't-inline.out'), 'w') as f_:
        f_.write(t_)
    bad, ok, note = judge(d)
    one('M1t: arms with different fixed costs are NOT priced',
        any('the arms are not comparable' in x for x in bad)
        and not any('inlining the vertex writer' in x for x in ok))

    for f_ in ('t-quiet.out', 't-inline.out'):
        p_ = os.path.join(d, f_)
        os.path.exists(p_) and os.unlink(p_)

    # ---- M1v: the group arm must prove it ran, and a lost group is fatal
    def writeg(name, groups, declined, lost, tris, installs, slope=1.70):
        with open(os.path.join(d, name), 'w') as f:
            f.write('RDNTRI run=1 step=knobs sentlog=1 batch=1 nullsend=0\n')
            f.write('RDNTRI run=1 step=prof-clock pair_us=4 batch=1 pts=6 '
                    'reps=3\n')
            for rep in range(3):
                for n in (1, 18, 36, 60, 66, 72):
                    f.write('RDNTRI run=1 step=prof n=%d k=8 subs=8 rep=%d '
                            'copyin=0 leg=4 us=%d\n'
                            % (n, rep, int(8 * (50 + slope * n))))
            f.write('RDNTRI run=1 step=end-sent n=8 kept=2 words=15\n')
            for k, w in enumerate(same):
                f.write('RDNTRI run=1 tri %d %s\n' % (k, ' '.join(w)))
            f.write('RDNTRI run=1 step=end-group groups=%d declined=%d lost=%d '
                    'tris=%d installs=%d\n'
                    % (groups, declined, lost, tris, installs))
    writeq('t-accel.out', LEG_PX, 1.0)
    writet('t-quiet.out', 2.00, same)
    writeg('t-group.out', 40, 0, 0, 480, 3)
    bad, ok, note = judge(d)
    one('M1v: a group arm that ran is priced',
        any('drew 480 triangles' in x for x in ok)
        # NOT the literal '1.700': the fit prints three decimals and lands on
        # 1.701, and a self-test that fails for its own spelling teaches nothing
        and any(x.startswith('the whole group in one call: 2.000 -> 1.7')
                for x in ok))
    writeg('t-group.out', 40, 2, 1, 480, 3)
    bad, ok, note = judge(d)
    one('M1v: ONE lost group is a FAILURE',
        any('lost 1 groups' in x for x in bad))

    # ---- M2a: the pair whose knob moves the FIXED cost, both directions
    #
    # Written because the real arm FAILED the old guard: M2a removes an
    # instruction that runs once a submission, so the intercept MUST move and the
    # rule that demanded it stay put refused the result.  The rule was split, and
    # both halves are exercised here.
    writet('t-stage.out', 2.00, same, fixed=470.0)
    writet('t-nowb.out', 2.03, same, fixed=250.0)
    bad, ok, note = judge(d)
    one('M2a: a fixed cost that falls is the RESULT, and is priced',
        any('the submission WBINVD skipped: the fixed cost 470 -> 250' in x for x in ok)
        and not any('not comparable' in x for x in bad))
    writet('t-nowb.out', 2.03, same, fixed=700.0)
    bad, ok, note = judge(d)
    one('M2a: a fixed cost that RISES is a FAILURE',
        any('the fixed cost went UP' in x for x in bad))
    writet('t-nowb.out', 3.10, same, fixed=250.0)
    bad, ok, note = judge(d)
    one('M2a: a MARGINAL cost that moves is a FAILURE',
        any('the MARGINAL cost moved' in x for x in bad))
    # ---- M2c: the instrument's own price, both directions
    #
    # The arm that turns the instrument OFF cannot be judged by the tstage line
    # -- it does not produce one -- so it is judged by the client's wall clock
    # exactly like M2a's, and the same two guards apply.
    writet('t-stage.out', 2.00, same, fixed=250.0)
    writet('t-notime.out', 2.02, same, fixed=190.0)
    bad, ok, note = judge(d)
    one('M2c: the instrument\'s price is the fall in the fixed cost',
        any('the stage instrument switched off: the fixed cost 250 -> 190' in x
            for x in ok)
        and not any('not comparable' in x for x in bad))
    writet('t-notime.out', 2.02, same, fixed=400.0)
    bad, ok, note = judge(d)
    one('M2c: taking the instrument off cannot cost MORE',
        any('the fixed cost went UP' in x for x in bad))
    writet('t-notime.out', 2.60, same, fixed=190.0)
    bad, ok, note = judge(d)
    one('M2c: a per-triangle change means something else moved',
        any('the MARGINAL cost moved' in x for x in bad))
    # ---- M2g: a log-on arm that did not pay the log is a FAILURE, not a price
    #
    # These five files are shared with the tests after this one, so they are
    # put BACK afterwards, not deleted: deleting t-accel.out made every later
    # judge stop at "no t-accel.out" (the first draft of this block did).
    keep_ = {}
    for a_ in ('t-stage.out', 't-accel.out', 't-nobatch.out', 't-hold.out', 't-accel2.out'):
        p_ = os.path.join(d, a_)
        keep_[a_] = open(p_).read() if os.path.exists(p_) else None
    writet('t-stage.out', 2.00, same, fixed=490.0)
    for a_ in ('t-accel.out', 't-nobatch.out', 't-hold.out', 't-accel2.out'):
        writet(a_, 2.00, same, fixed=1570.0)
    bad, ok, note = judge(d)
    one('M2g: log-on arms 1,080 us dearer than t-stage pass',
        any('every log-on arm is dearer' in x for x in ok)
        and not any('must pay the submit log' in x for x in bad))
    writet('t-hold.out', 2.00, same, fixed=500.0)          # the lease was forgotten
    bad, ok, note = judge(d)
    one('M2g: a log-on arm that ran quiet (500 vs 490) is a FAILURE',
        any('must pay the submit log did not' in x and 't-hold' in x for x in bad))
    for a_, txt_ in keep_.items():
        p_ = os.path.join(d, a_)
        if txt_ is None:
            os.path.exists(p_) and os.unlink(p_)
        else:
            with open(p_, 'w') as f:
                f.write(txt_)

    # ---- M2g: each grid cell must own a pair, found by its seed
    gseed = 790300901
    with open(os.path.join(d, 't-grid.drv'), 'w') as f:
        for k_ in range(8):
            f.write('RDN-R7B stage boot=abcd1234 words=63 staged=1 dropped=0 ok=1\n')
            f.write('RDN-R5 begin boot=abcd1234 op=12 arg=%08x len=137\n' % (gseed + 100 * k_))
            f.write('RDN-R5 wait fifo=1/0/t0 idle=2/0/40/t7 rptr=1/0/0/t1 '
                    'idle2=1/0/t0 dc=1/0/t0\n')
        # a loud OTHER arm's pair, which must not stand in for a cell
        f.write('RDN-R7B stage boot=abcd1234 words=63 staged=1 dropped=0 ok=1\n')
        f.write('RDN-R5 begin boot=abcd1234 op=12 arg=%08x len=137\n' % 12345)
        f.write('RDN-R5 wait fifo=1/0/t0 idle=2/0/41/t7 rptr=1/0/0/t1 '
                'idle2=1/0/t0 dc=1/0/t0\n')
    k_ = 0
    for gl in (1, 4):
        for gn in (0, 1, 2, 3):
            with open(os.path.join(d, 't-grid-%d-%d.out' % (gl, gn)), 'w') as f:
                f.write('RDNTRI run=1 step=prof-grid leg=4 n=1 subs=2\n')
                f.write('RDNTRI run=1 step=prof-grid-done leg=4 n=1\n')
                f.write('RDNTRI run=1 step=end-tri entered=3 submitted=3 seed=%d\n'
                        % (gseed + 100 * k_))
            k_ += 1
    bad, ok, note = judge(d)
    one('M2g: every grid cell owning its pair by seed passes',
        any('every grid cell owns its' in x for x in ok))
    # the grid ran QUIET: its own pairs are gone, another arm's is still there
    with open(os.path.join(d, 't-grid.drv'), 'w') as f:
        f.write('RDN-R7B stage boot=abcd1234 words=63 staged=1 dropped=0 ok=1\n')
        f.write('RDN-R5 begin boot=abcd1234 op=12 arg=%08x len=137\n' % 12345)
        f.write('RDN-R5 wait fifo=1/0/t0 idle=2/0/41/t7 rptr=1/0/0/t1 '
                'idle2=1/0/t0 dc=1/0/t0\n')
    bad, ok, note = judge(d)
    one('M2g: a quiet grid is a FAILURE even when another arm left pairs in the log',
        any('no (stage, wait) pair of their OWN' in x and '1-0' in x and '4-3' in x
            for x in bad)
        and not any('no (stage, wait) pair:' in x for x in bad))
    os.unlink(os.path.join(d, 't-grid.drv'))
    for gl in (1, 4):
        for gn in (0, 1, 2, 3):
            p_ = os.path.join(d, 't-grid-%d-%d.out' % (gl, gn))
            os.path.exists(p_) and os.unlink(p_)

    # ---- the spread gate: the arms that must agree, and what happens when they do not
    #
    # This is the gate that would have stopped three wrong numbers going into the
    # record (docs/M2F_PLAN.md 8-2), so it gets the same treatment as the rules
    # it protects: a run that agrees passes, a run that splits FAILS, and the
    # split is named rather than priced.
    for f_ in ('t-quiet.out', 't-nosent.out', 't-inline.out', 't-group.out',
               't-stage.out', 't-spin.out', 't-stage2.out'):
        writet(f_, 2.00, same, fixed=490.0)
    bad, ok, note = judge(d)
    one('the spread gate: seven arms that agree are reported as agreeing',
        any('arms that must agree do, to' in x for x in ok))
    writet('t-spin.out', 2.00, same, fixed=700.0)        # one arm 210 us away
    bad, ok, note = judge(d)
    one('the spread gate: ONE arm 210 us away is a FAILURE',
        any('arms that must agree do not' in x and '210' in x for x in bad))
    writet('t-spin.out', 2.00, same, fixed=520.0)        # 30 us: inside the band
    bad, ok, note = judge(d)
    one('the spread gate: 30 us is inside the band and still passes',
        any('arms that must agree do, to' in x for x in ok))
    for f_ in ('t-quiet.out', 't-nosent.out', 't-inline.out', 't-group.out',
               't-stage.out', 't-spin.out', 't-stage2.out'):
        p_ = os.path.join(d, f_)
        os.path.exists(p_) and os.unlink(p_)

    # ---- M2f: open/close priced BOTH ways, and the comparison named
    #
    # The numbers are the measured ones: the log-on pair said 26.9 us on the run
    # that found this, and the point of the quiet pair is that it can disagree.
    writet('t-accel.out', 2.00, same, fixed=1600.0)
    writet('t-hold.out', 2.00, same, fixed=1573.0)      # log on: 27 apart
    writet('t-quiet.out', 2.00, same, fixed=500.0)
    writet('t-qhold.out', 2.00, same, fixed=490.0)      # log off: 10 apart
    bad, ok, note = judge(d)
    one('M2f: open/close is priced with the submit log on AND off',
        any('holding the node with the submit log ON' in x for x in ok)
        and any('holding the node with the submit log OFF' in x for x in ok))
    one('M2f: the two prices are compared, and the difference is named as the LOG',
        any('open/close priced both ways' in x and 'the LOG moving' in x
            for x in ok))
    # and a held arm that is SLOWER is a failure, not a negative price
    writet('t-qhold.out', 2.00, same, fixed=660.0)      # slower than t-quiet's 500
    bad, ok, note = judge(d)
    one('M2f: a held arm that is SLOWER is a FAILURE, not a negative price',
        any('holding the node made it SLOWER' in x for x in bad)
        and not any('with the submit log OFF' in x and 'open/close' in x
                    for x in ok))
    writet('t-qhold.out', 2.00, same, fixed=490.0)
    for f_ in ('t-qhold.out', 't-hold.out'):
        p_ = os.path.join(d, f_)
        os.path.exists(p_) and os.unlink(p_)
    bad, ok, note = judge(d)
    one('M2f: a missing quiet-hold arm is NOTED, not silently skipped',
        any('no t-qhold.out' in x for x in note))
    writeq('t-accel.out', LEG_PX, 1.0)      # back to the shape the rest expects

    # ---- M2d: the fourth cell, its three signs, and the drift that can fake one
    #
    # The three t-bothoff values are the ones docs/M2D_PLAN.md 2-2 tabulates,
    # and they are here because the plan's first draft named their signs
    # BACKWARDS.  A self-test that only checked "there is a residual" would have
    # let that through, so each one is matched on its WORD.
    #
    # The drift arms are written far apart so the drift is small; the last case
    # makes the drift big enough to swallow the residual and asserts the verdict
    # refuses to name it.
    writet('t-stage.out', 2.00, same, fixed=491.0)
    writet('t-notime.out', 2.01, same, fixed=431.0)
    writet('t-nowb.out', 2.01, same, fixed=270.0)
    # t-accel is written in the SAME shape as the other cells here: the drift is
    # a difference of two intercepts, and writeq's transcript has no leg-4 sweep
    # for leg4slope to fit -- with it the drift silently came out unmeasured and
    # three of these cases failed for that and not for what they test.
    writet('t-stage2.out', 2.00, same, fixed=493.0)      # quiet drift +2
    writet('t-spin.out', 2.00, same, fixed=492.0)        # spin bar +1
    for bf, want in ((210.0, 'INDEPENDENT'),
                     (150.0, 'AMPLIFIED'),
                     (290.0, 'OVERLAPPED')):
        writet('t-bothoff.out', 2.01, same, fixed=bf)
        bad, ok, note = judge(d)
        one('M2d: t-bothoff %.0f is read as %s' % (bf, want),
            any('M2d: both knobs off saves' in x and want in x
                for x in ok + note))
    # THE BAND WHERE THE SIGN IS NOT ENOUGH.
    #
    # The first real M2d run landed here: residual -8 against a 2 us drift and a
    # 6 us spin pair.  Against the drift alone it read as a clean interaction;
    # 1.3x the bigger bar is not one.
    writet('t-spin.out', 2.00, same, fixed=486.0)        # spin bar -6
    writet('t-bothoff.out', 2.01, same, fixed=218.0)     # residual about -8
    bad, ok, note = judge(d)
    one('M2d: a residual barely over the bar is marked ONLY JUST',
        any('ONLY JUST' in x and 'the spin pair' in x for x in ok))
    # and the bigger of the two bars is the one that decides
    writet('t-bothoff.out', 2.01, same, fixed=214.0)     # residual about -4
    bad, ok, note = judge(d)
    one('M2d: the SPIN bar decides when it is bigger than the drift',
        any('INDEPENDENT' in x and 'the spin pair' in x for x in ok))
    writet('t-spin.out', 2.00, same, fixed=492.0)
    # and the drift is priced in its own line
    bad, ok, note = judge(d)
    one('M2d: the quiet drift is reported as its own number',
        any('the quiet drift across the whole run' in x and '+2' in x
            for x in ok))
    # a residual no bigger than the drift is read as INDEPENDENT, not as an
    # interaction -- the same numbers that said OVERLAPPED above
    writet('t-stage2.out', 2.00, same, fixed=591.0)      # quiet drift +100
    writet('t-bothoff.out', 2.01, same, fixed=250.0)     # residual -40
    bad, ok, note = judge(d)
    one('M2d: the SAME residual is INDEPENDENT once the drift is bigger',
        any('INDEPENDENT' in x and 'does not beat the biggest of them' in x
            for x in ok)
        and not any('OVERLAPPED' in x for x in ok))
    # ---- M2e: the boot's default, read from the machine's own log, both ways
    STATE = ('RDN-R5 state state=0 latched=0 reset=0 failed=0 wptr=0 phys=00040000 '
             'post=00000000 csqstat=02000603 csq2stat=04010080 csqread=1 '
             'nowb=%d spin=0 time=0\n')
    for val, want, where in ((1, 'the boot started with nowb=1', 'ok'),
                             (0, 'the boot started with nowb=0', 'bad')):
        with open(os.path.join(d, 't-grid.drv'), 'w') as f_:
            f_.write(STATE % val)
            f_.write(STATE % (1 - val))     # a LATER line must not decide it
        bad, ok, note = judge(d)
        one('M2e: nowb=%d on the first state line is read as %s' % (val, where),
            any(want in x for x in (ok if where == 'ok' else bad)))
    os.unlink(os.path.join(d, 't-grid.drv'))
    bad, ok, note = judge(d)
    one('M2e: with no driver log the default is NOT claimed either way',
        not any('M2e: the boot started' in x for x in ok + bad))

    # and with NEITHER bar the question is not answered quietly
    os.unlink(os.path.join(d, 't-stage2.out'))
    sp_ = os.path.join(d, 't-spin.out')
    spsave = open(sp_).read()
    os.unlink(sp_)
    bad, ok, note = judge(d)
    one('M2d: without either bar the residual is NOT named',
        any('the quiet drift was not measured' in x for x in note)
        and any('NOT NAMED: neither bar was measured' in x for x in note))
    # and ONE bar is enough to ask the question
    with open(sp_, 'w') as f_:
        f_.write(spsave)
    bad, ok, note = judge(d)
    one('M2d: the spin bar ALONE can still answer it',
        any('M2d: both knobs off saves' in x and 'the spin pair' in x
            for x in ok))
    for f_ in ('t-bothoff.out', 't-stage2.out'):
        p_ = os.path.join(d, f_)
        os.path.exists(p_) and os.unlink(p_)

    for f_ in ('t-stage.out', 't-nowb.out', 't-notime.out'):
        p_ = os.path.join(d, f_)
        os.path.exists(p_) and os.unlink(p_)

    writeg('t-group.out', 0, 0, 0, 0, 0)
    bad, ok, note = judge(d)
    one('M1v: an arm that never installed the table measures nothing',
        any('never installed the table' in x for x in bad))
    for f_ in ('t-quiet.out', 't-group.out'):
        p_ = os.path.join(d, f_)
        os.path.exists(p_) and os.unlink(p_)

    # ---- M1x: the stage line, and ops=0 is a failure not a report
    with open(os.path.join(d, 't-grid.drv'), 'w') as f:
        f.write('RDN-R5 tstage boot=aabbccdd ops=100 gates=1000 pre=2000 '
                's1ring=3000 s1read=10000 s2asm=4000 s2ring=5000 flush=6000 '
                'tail=5600\n')
    writeq('t-accel.out', LEG_PX, 1.0)
    bad, ok, note = judge(d)
    one('M1x: the stage times are reported per submission',
        any('the kernel op over 100 submissions: 366.0 us' in x for x in ok)
        and any('stage1 read-backs    100.0 us   27.3 %' in x for x in ok))
    with open(os.path.join(d, 't-grid.drv'), 'w') as f:
        f.write('RDN-R5 tstage boot=aabbccdd ops=0 gates=0 pre=0 s1ring=0 '
                's1read=0 s2asm=0 s2ring=0 flush=0 tail=0\n')
    bad, ok, note = judge(d)
    one('M1x: ops=0 is a FAILURE, not a report of zero',
        any('says ops=0' in x for x in bad))
    # ---- M1z: the two ring-submit totals, and the two ways they can be wrong
    #  s1ring 3000 + s2ring 5000 = 8000; fence 4000 + wait 3000 leaves 1000
    with open(os.path.join(d, 't-grid.drv'), 'w') as f:
        f.write('RDN-R5 tstage boot=aabbccdd ops=100 gates=1000 pre=2000 '
                's1ring=3000 s1read=10000 s2asm=4000 s2ring=5000 flush=6000 '
                'tail=5600 fence=4000 wait=3000\n')
    bad, ok, note = judge(d)
    one('M1z: the ring submits are split into fence, waits and the rest',
        any('cpFence (WBINVD)      40.0 us' in x for x in ok)
        and any('the two waits         30.0 us' in x for x in ok)
        and any('puts + doorbell       10.0 us' in x for x in ok))
    one('M1z: no complaint when the parts fit inside the whole',
        not any('more than the two ring' in x or 'cannot be negative' in x for x in bad))
    with open(os.path.join(d, 't-grid.drv'), 'w') as f:
        f.write('RDN-R5 tstage boot=aabbccdd ops=100 gates=1000 pre=2000 '
                's1ring=3000 s1read=10000 s2asm=4000 s2ring=5000 flush=6000 '
                'tail=5600 fence=6000 wait=3000\n')
    bad, ok, note = judge(d)
    one('M1z: parts bigger than the whole is a FAILURE',
        any('more than the two ring' in x for x in bad))
    with open(os.path.join(d, 't-grid.drv'), 'w') as f:
        f.write('RDN-R5 tstage boot=aabbccdd ops=100 gates=1000 pre=2000 '
                's1ring=3000 s1read=10000 s2asm=4000 s2ring=5000 flush=6000 '
                'tail=5600\n')
    bad, ok, note = judge(d)
    one('M1z: a driver without the two fields is NOTED, not failed',
        any('predates M1z' in x for x in note)
        and not any('more than the two ring' in x for x in bad))

    # ---- M2b: the put loops split "the rest" in two, and cannot exceed it
    with open(os.path.join(d, 't-grid.drv'), 'w') as f:
        f.write('RDN-R5 tstage boot=aabbccdd ops=100 gates=1000 pre=2000 '
                's1ring=3000 s1read=10000 s2asm=4000 s2ring=5000 flush=6000 '
                'tail=5600 fence=4000 wait=3000 put=600\n')
    bad, ok, note = judge(d)
    one('M2b: the put loops are named and the doorbell is what is left',
        any('the cpPut loops        6.0 us' in x for x in ok)
        and any('doorbell + posting     4.0 us' in x for x in ok))
    with open(os.path.join(d, 't-grid.drv'), 'w') as f:
        f.write('RDN-R5 tstage boot=aabbccdd ops=100 gates=1000 pre=2000 '
                's1ring=3000 s1read=10000 s2asm=4000 s2ring=5000 flush=6000 '
                'tail=5600 fence=4000 wait=3000 put=2000\n')
    bad, ok, note = judge(d)
    one('M2b: a put bigger than what is left is a FAILURE',
        any('are more than what is left' in x for x in bad))
    os.unlink(os.path.join(d, 't-grid.drv'))

    one('M1q: lsq3 recovers a + b*L + c*P exactly',
        (lambda f: f is not None and abs(f[0] - 7) < 1e-6
         and abs(f[1] - 2) < 1e-6 and abs(f[2] - 0.5) < 1e-6)(
            lsq3([(L, P, 7 + 2 * L + 0.5 * P)
                  for L in (2, 4, 8, 16) for P in (10, 100, 500)])))

    print('judge_m1l self-test: %s'
          % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return fails


def main():
    if '--self-test' in sys.argv:
        return 1 if self_test() else 0
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    bad, ok, note = judge(sys.argv[1])
    for x in ok:
        print('  ok   %s' % x)
    for x in note:
        print('  --   %s' % x)
    for x in bad:
        print('  FAIL %s' % x)
    print('judge_m1l: %s' % ('PASS' if not bad else 'FAIL (%d)' % len(bad)))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
