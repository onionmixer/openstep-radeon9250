from conv_space import hyps
Z16 = [0.0212597828, 0.502082825, 0.0248264298, 0.0318303145, 0.478965431, 0.444190949, 0.0248260517, 0.21641545, 0.0222916584, 0.439666271, 0.502075195, 0.497329682]
H = hyps(16)
import random
from conv_space import f32
random.seed(3); probe = [f32(random.random()) for _ in range(3000)]
full = {}
for k, h in H.items(): full.setdefault(tuple(h(z) for z in probe), []).append(k)
reps = {v[0]: v for v in full.values()}
for n in range(1, len(Z16) + 1):
    part = {}
    for k in reps: part.setdefault(tuple(H[k](z) for z in Z16[:n]), []).append(k)
    big = max(part.values(), key=len)
    print(n, 'classes separated', len(part), 'of', len(reps), 'largest group', len(big))
