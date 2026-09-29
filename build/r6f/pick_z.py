import random, time, sys
from conv_space import hyps, f32
random.seed(7)
cands = [f32(random.random()) for _ in range(3000)]
for n in range(1, 400):                        # structured: near half-steps of both scales
    for d in (65535, 65536, 0xffffff, 1 << 24):
        cands.append(f32((n * 163 + 0.5) / d)); cands.append(f32((n * 40961 + 0.5) / d))
cands = [z for z in cands if 0.02 < z < 0.98]
t0 = time.time()
for bits in (16, 24):
    H = hyps(bits); keys = list(H)
    probe = cands
    vals = {k: [H[k](z) for z in probe] for k in keys}
    full = {}
    for k in keys: full.setdefault(tuple(vals[k]), []).append(k)
    reps = [v[0] for v in full.values()]
    chosen = []; part = {tuple(): reps}
    while True:
        best = None
        for j in range(len(probe)):
            npart = {}
            for key, grp in part.items():
                for k in grp: npart.setdefault(key + (vals[k][j],), []).append(k)
            s = len(npart)
            if best is None or s > best[0]: best = (s, j, npart)
        if best[0] == len(part): break
        chosen.append(probe[best[1]]); part = best[2]
        if len(part) == len(reps): break
    print(bits, 'classes', len(reps), 'separated', len(part), 'with', len(chosen), 'z:', ['%.9g' % z for z in chosen], '%.0fs' % (time.time() - t0))
