import random, struct
from conv_space2 import hyps, f32
exec(open('design2d.py').read().split("if __name__")[0])
import pick_z3_pool
random.seed(5)
tiny = sorted(set(f32(2 ** random.uniform(-20, -5.6)) for _ in range(4000)))
random.seed(1); probe = [f32(random.random()) for _ in range(3000)] + pick_z3_pool.cands + tiny
add = []
for bits in (16, 24):
    H = hyps(bits); full = {}
    for k, h in H.items(): full.setdefault(tuple(h(z) for z in probe), []).append(k)
    reps = [v[0] for v in full.values()]
    while True:
        part = {}
        for k in reps: part.setdefault(tuple(H[k](z) for z in Z + add), []).append(k)
        if len(part) == len(reps): break
        best = max(tiny, key=lambda z: len({key + (H[k](z),) for key, g in part.items() for k in g}))
        add.append(best)
    print(bits, 'classes', len(reps), 'separated with', len(add), 'tiny additions')
print(['%.6g' % z for z in add], [('%08x' % struct.unpack('<I', struct.pack('<f', z))[0]) for z in add])
