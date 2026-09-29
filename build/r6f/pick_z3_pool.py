import random, time, struct, sys
from conv_space2 import hyps, f32
def nb(x):
    b = struct.unpack('<I', struct.pack('<f', x))[0]
    return [struct.unpack('<f', struct.pack('<I', b + d))[0] for d in (-1, 0, 1)]
random.seed(11)
cands = set()
for _ in range(200):
    n = random.randrange(1000, 64000)
    for num in (n + 0.5, n):
        for d in (65535, 65536, 65534):
            cands.update(nb(num / d))
    m = random.randrange(1 << 12, (1 << 24) - (1 << 12))
    for num in (m + 0.5, m):
        for d in (0xffffff, 1 << 24, 0xfffffe):
            cands.update(nb(num / d))
    for q in (8, 10, 12, 14, 16, 20):
        k = random.randrange(1, 1 << q); cands.update(nb((k + 0.5) / (1 << q)))
    cands.add(f32(random.random()))
cands = sorted(z for z in cands if 0.02 < z < 0.98)
