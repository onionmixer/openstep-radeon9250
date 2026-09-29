# R6f design check 1: the anchor grid (16 constant-z cells) -- coverage, disjointness
import sys; sys.path.insert(0, '../../tools/r6')
import tri_oracle as to, numpy as np
CELLS = [(2 + 8 * i, 2 + 8 * j) for j in range(4) for i in range(4)]
def cell_tri(x0, y0, leg=3):
    return [(float(x0), float(y0)), (float(x0 + leg), float(y0)), (float(x0), float(y0 + leg))]
tot = np.zeros((32, 32), int)
for x0, y0 in CELLS:
    c = to.cover(cell_tri(x0, y0), to.MEASURED, 32)
    pix = sorted((x, y) for y in range(32) for x in range(32) if c[y][x])
    assert (x0, y0) in pix
    tot += c
    print((x0, y0), len(pix), pix)
    break
for x0, y0 in CELLS[1:]:
    tot += to.cover(cell_tri(x0, y0), to.MEASURED, 32)
print('max overlap', tot.max(), 'covered', int((tot > 0).sum()))
