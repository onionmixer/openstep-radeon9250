exec(open('design2.py').read().split("random.seed(1)")[0])
import random
random.seed(1); probe = [f32(random.random()) for _ in range(4000)]
H = hyps(16); full = {}
for k, h in H.items(): full.setdefault(tuple(h(z) for z in probe + Z), []).append(k)
part = {}
for v in full.values(): part.setdefault(tuple(H[v[0]](z) for z in Z), []).append(v)
for grp in part.values():
    if len(grp) > 1:
        a, b = grp[0][0], grp[1][0]
        diff = [z for z in probe if H[a](z) != H[b](z)]
        print('A', grp[0]); print('B', grp[1]); print('differ on', len(diff), 'of', len(probe), ['%.9g' % z for z in diff[:3]])
