# R6f anchors v2 (after codex Q3): separators of the widened space (pick_z3) + seeded random to 48
import random, pickle, struct, time
from conv_space2 import hyps, f32
P = pickle.load(open('pick_z3.pkl', 'rb'))
Z = []
for z in P[16] + P[24]:
    if z not in Z: Z.append(z)
random.seed(62306)
while len(Z) < 48:
    z = f32(random.uniform(0.02, 0.98))
    if z not in Z: Z.append(z)
if __name__ == '__main__':
    import pick_z3_pool
    random.seed(1); probe = [f32(random.random()) for _ in range(3000)] + pick_z3_pool.cands
    for bits in (16, 24):
        H = hyps(bits); full = {}; part = {}
        for k, h in H.items(): full.setdefault(tuple(h(z) for z in probe), []).append(k)
        for v in full.values(): part.setdefault(tuple(H[v[0]](z) for z in Z), []).append(v)
        print(bits, 'hyps', len(H), 'classes on probe', len(full), 'separated by the 48', len(part))
        for g in part.values():
            if len(g) > 1: print('   merged:', [x[0] for x in g])
    print(len(Z), 'separators', len(P[16]) + len(P[24]), 'distinct', len(set(P[16] + P[24])))
    print(' '.join('%08x' % struct.unpack('<I', struct.pack('<f', z))[0] for z in Z))
