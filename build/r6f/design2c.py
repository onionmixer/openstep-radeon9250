import random, time
exec(open('design2.py').read().split("random.seed(1)")[0])
from conv_space2 import hyps, f32
random.seed(1); probe = [f32(random.random()) for _ in range(3000)] + Z
t0 = time.time()
for bits in (16, 24):
    H = hyps(bits); full = {}; part = {}
    for k, h in H.items(): full.setdefault(tuple(h(z) for z in probe), []).append(k)
    for v in full.values(): part.setdefault(tuple(H[v[0]](z) for z in Z), []).append(v[0])
    print(bits, 'hyps', len(H), 'classes on probe', len(full), 'separated by the 48', len(part), '%.0fs' % (time.time() - t0))
