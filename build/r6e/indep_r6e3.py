# independent recount of R6e-3: own log parser, own rule B; the case table and covered() come from the oracle
import re, sys, math
from fractions import Fraction as Fr
sys.path.insert(0, 'tools/r6'); import gouraud_oracle as go
log = open('build/r6/boot-fecbb2af.full.log', errors='replace').read().splitlines()
planes = {}; cur = None
for ln in log:
    m = re.search(r'RDN-R6 plh boot=(\w+) zc=(\d+) case=(\d+) lane=(\d+) chunk=(\d+)', ln)
    if m:
        assert m.group(1) == 'fecbb2af'; cur = (int(m.group(3)), int(m.group(4))); continue
    m = re.search(r'RDN-R6 pl(\d) (\d+) ((?:[0-9a-f]{8} ?){8})\s*$', ln)
    if m and cur:
        assert int(m.group(1)) == cur[1]
        planes.setdefault(cur, {})[int(m.group(2))] = [int(w, 16) for w in m.group(3).split()]
def t16(v): return Fr(math.floor(Fr(v) * 16), 16)
def ruleb(pts, vals, pix, mode):
    P = [(t16(x), t16(y)) for x, y in pts]
    L = sorted(range(3), key=lambda i: P[i])[0]
    (x0,y0),(x1,y1),(x2,y2) = P
    A = (x1-x0)*(y2-y0)-(x2-x0)*(y1-y0)
    out = []
    for x, y in pix:
        sx, sy = x + Fr(1,2), y + Fr(1,2)
        b1 = ((sx-x0)*(y2-y0)-(x2-x0)*(sy-y0)) / A
        b2 = ((x1-x0)*(sy-y0)-(sx-x0)*(y1-y0)) / A
        w = [1-b1-b2, b1, b2]
        for i in range(3):
            if i == L: continue
            z = w[i]*256; f = math.floor(z); r = z - f
            if r > Fr(1,2) or (r == Fr(1,2) and (mode == 'up' or f % 2 == 1)): f += 1
            w[i] = Fr(f, 256)
        w[L] = 1 - sum(w[i] for i in range(3) if i != L)
        out.append(min(255, max(0, math.floor(sum(a*b for a, b in zip(w, vals))))))
    return out
LANE = {'B': 0, 'G': 1, 'R': 2, 'A': 3}
tot = {'up': 0, 'even': 0}; n = 0; zero_bad = 0
for name in ['G1', 'S3'] + go.ORDER3:
    case = go.CASE_NUM[name]; pts = go.GCASES[name][0]; pix = go.covered(pts); cs = set(pix)
    for lane in go.GCASES[name][2]:
        ls = planes.get((case, LANE[lane]))
        assert ls is not None and sorted(ls) == list(range(32)), (name, lane)
        words = [w for k in range(32) for w in ls[k]]
        byte = lambda x, y: (words[(y*32+x)//4] >> (8*((y*32+x) % 4))) & 0xff
        zero_bad += sum(1 for y in range(32) for x in range(32) if (x, y) not in cs and byte(x, y))
        seen = [byte(x, y) for x, y in pix]; n += len(seen)
        vals = tuple(v['RGBA'.index(lane)] for v in go.GCASES[name][1])
        for m in tot:
            d = sum(a != b for a, b in zip(ruleb(pts, vals, pix, m), seen)); tot[m] += d
            if d: print(name, lane, m, d)
print('bytes', n, 'diff', tot, 'nonzero outside coverage', zero_bad)
