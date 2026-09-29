"""R6i: pull the observed planes out of a boot log into a pickle (host analysis).

  python3 build/r6i2/extract.py <boot nonce>

Writes build/r6i2/observed_<nonce>.pkl: {case name: {(x, y): pixel word}} for the colour cases,
{'PZ': {(x, y): depth value}} for the depth one, and the two control cases under their own names.
"""
import pickle
import re
import sys

sys.path.insert(0, 'tools/r6')
import persp_oracle as pe
import depth_oracle as do                        # noqa: E402
import gouraud_oracle as go                      # noqa: E402

nonce = sys.argv[1]
log = open('build/r6/boot-%s.full.log' % nonce, errors='replace').read().splitlines()
planes, cur = {}, None
for ln in log:
    m = re.search(r'RDN-R6 plh boot=%s zc=(\d+) case=(\d+) lane=(\d+) chunk=(\d+) src=(\d+)' % nonce, ln)
    if m:
        cur = (int(m.group(2)), int(m.group(3)))
        continue
    m = re.search(r'RDN-R6 pl(\d) (\d+) ((?:[0-9a-f]{8} ?){8})\s*$', ln)
    if m and cur:
        planes.setdefault(cur, {})[int(m.group(2))] = [int(w, 16) for w in m.group(3).split()]


def lanes_of(case, lanes):
    c = pe.CASE_NUM[case] if case in pe.CASE_NUM else (go.CASE_NUM.get(case) or do.CASE_NUM[case])
    out = {}
    for l in lanes:
        ws = planes[(c, l)]
        assert sorted(ws) == list(range(32)), (case, l, sorted(ws))
        out[l] = [w for k in range(32) for w in ws[k]]
    return out


obs = {}
for n in pe.ORDER2 + ['LD']:
    if pe.kind(n) == 'depth':
        pl = lanes_of(n, range(3))
        obs[n] = do.values_from_planes(pl, 24)
        continue
    pts = pe.geom_of(n)
    pl = lanes_of(n, range(4))
    px = {}
    for (x, y) in go.covered(pts):
        i = y * 32 + x
        px[(x, y)] = sum(((pl[l][i // 4] >> (8 * (i % 4))) & 0xff) << (8 * l) for l in range(4))
    obs[n] = px

pickle.dump(obs, open('build/r6i2/observed_%s.pkl' % nonce, 'wb'))
for n in pe.ORDER2 + ['LD']:
    v = obs[n]
    print('%-6s pixels %3d  distinct %3d' % (n, len(v), len(set(v.values()))))
