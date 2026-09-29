# R6f design check 2: 48 anchor z (float32) = the greedy separators of both formats + seeded random
import random, struct
from conv_space import hyps, f32
S16 = [0.0212597828, 0.502082825, 0.0248264298, 0.0318303145, 0.478965431, 0.444190949, 0.0248260517, 0.21641545,
       0.0222916584, 0.439666271, 0.502075195, 0.497329682, 0.0248340573, 0.0318379439, 0.0243148785, 0.0294265747,
       0.0243148804, 0.0294265766, 0.0248260479, 0.0248260498, 0.0248340592, 0.250572234, 0.502075255, 0.502082884]
S24 = [0.0222916622, 0.500660062, 0.0212597828, 0.0234941542, 0.250843465]
Z = []
for z in [f32(v) for v in S16 + S24]:
    if z not in Z: Z.append(z)
random.seed(62306)                               # recorded in the plan before generation
while len(Z) < 47:
    z = f32(random.uniform(0.02, 0.98))
    if z not in Z: Z.append(z)
Z.append(f32(0.119193979))           # separates the from24 ceil pair (design2b.py)
random.seed(1); probe = [f32(random.random()) for _ in range(4000)] + Z
for bits in (16, 24):
    H = hyps(bits); full = {}; part = {}
    for k, h in H.items():
        full.setdefault(tuple(h(z) for z in probe), []).append(k)
    for v in full.values():
        part.setdefault(tuple(H[v[0]](z) for z in Z), []).append(v[0])
    print(bits, 'classes on probe', len(full), 'separated by the 48', len(part))
print(len(Z), 'z; float32 bits:')
print(' '.join('%08x' % struct.unpack('<I', struct.pack('<f', z))[0] for z in Z))
