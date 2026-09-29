# R6f anchors, final (docs/R6F_PLAN.md 8): separators of the widened conversion space (pick_z3.pkl),
# tiny-z separators (pick_tiny.py), then seeded random (62306) to 64 = four grid cases of 16
import random, pickle, struct
from conv_space2 import f32
P = pickle.load(open('pick_z3.pkl', 'rb'))
TINY = ['377f1dfb', '38d00b9d', '358401b3', '3a11f203', '3584473d', '36ba0076', '36e601b3', '35dffc1a', '36aaff66']
def fromhex(h): return struct.unpack('<f', struct.pack('<I', int(h, 16)))[0]
Z = []
for z in P[16] + P[24] + [fromhex(h) for h in TINY]:
    if z not in Z: Z.append(z)
NSEP = len(Z)
random.seed(62306)
while len(Z) < 64:
    z = f32(random.uniform(0.02, 0.98))
    if z not in Z: Z.append(z)
def hexes(): return ['%08x' % struct.unpack('<I', struct.pack('<f', z))[0] for z in Z]
if __name__ == '__main__':
    from conv_space2 import hyps
    import pick_z3_pool
    random.seed(5); tiny = sorted(set(f32(2 ** random.uniform(-20, -5.6)) for _ in range(4000)))
    random.seed(9); fresh = [f32(random.random()) for _ in range(3000)]           # a probe the pick never saw
    random.seed(1); probe = [f32(random.random()) for _ in range(3000)] + pick_z3_pool.cands + tiny + fresh
    for bits in (16, 24):
        H = hyps(bits); full = {}; part = {}
        for k, h in H.items(): full.setdefault(tuple(h(z) for z in probe), []).append(k)
        for v in full.values(): part.setdefault(tuple(H[v[0]](z) for z in Z), []).append(v)
        print(bits, 'hyps', len(H), 'classes on probe', len(full), 'separated by the 64', len(part))
    print(len(Z), 'anchors,', NSEP, 'separators; range %.3g .. %.3g' % (min(Z), max(Z)))
    print(' '.join(hexes()))
