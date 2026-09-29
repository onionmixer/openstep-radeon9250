import random, time, struct
from conv_space import hyps, f32
def nb(x):  # float32 neighbours of x
    b = struct.unpack('<I', struct.pack('<f', x))[0]
    return [struct.unpack('<f', struct.pack('<I', b + d))[0] for d in (-1, 0, 1)]
random.seed(11)
cands = set()
for _ in range(250):
    n = random.randrange(1000, 64000)
    for num in (n + 0.5, n):
        for d in (65535, 65536):
            cands.update(nb(num / d))
    m = random.randrange(1 << 12, (1 << 24) - (1 << 12))
    for num in (m + 0.5, m):
        for d in (0xffffff, 1 << 24):
            cands.update(nb(num / d))
    for q in (16, 20):
        k = random.randrange(1, 1 << q); cands.update(nb((k + 0.5) / (1 << q)))
cands = sorted(z for z in cands if 0.02 < z < 0.98)
print('candidates', len(cands))
t0 = time.time()
for bits in (16, 24):
    H = hyps(bits); keys = list(H)
    vals = {k: [H[k](z) for z in cands] for k in keys}
    full = {}
    for k in keys: full.setdefault(tuple(vals[k]), []).append(k)
    reps = [v[0] for v in full.values()]
    chosen = []; part = {(): reps}
    while len(part) < len(reps):
        best = None
        for j in range(len(cands)):
            npart = {}
            for key, grp in part.items():
                for k in grp: npart.setdefault(key + (vals[k][j],), []).append(k)
            if best is None or len(npart) > best[0]: best = (len(npart), j, npart)
        if best[0] == len(part): break
        chosen.append(cands[best[1]]); part = best[2]
    print(bits, 'classes', len(reps), 'separated', len(part), 'with', len(chosen), '%.0fs' % (time.time() - t0))
    print('   ', ['%.9g' % z for z in chosen])
