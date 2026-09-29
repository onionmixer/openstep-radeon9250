"""R6k: pull the observed pictures out of a boot log into a pickle (host analysis).

  python3 build/r6k/extract.py <boot nonce>

Writes build/r6k/observed_<nonce>.pkl: {case name: set of (x, y) written}, plus 'AS8depth' for the
depth case's values and 'dig' for each case's colour digest (changed, ixor, isum).
"""
import pickle
import re
import sys

sys.path.insert(0, 'tools/r6')
import scissor_oracle as sc                     # noqa: E402

do = sc.do
nonce = sys.argv[1]
log = open('build/r6/boot-%s.full.log' % nonce, errors='replace').read().splitlines()

# the driver logs an operation's coverage map BEFORE its "zclear case=" summary and the digest
# after it, so the map is buffered and flushed when the case names itself
cov, dig, planes, case, cur, pend = {}, {}, {}, None, None, {}
for ln in log:
    m = re.search(r'RDN-R6 cov(\d) ((?:[0-9a-f]{8} ?){8})\s*$', ln)
    if m:
        pend[int(m.group(1))] = [int(x, 16) for x in m.group(2).split()]
        continue
    m = re.search(r'RDN-R6 zclear case=(\d+) stage=3', ln)
    if m:
        case = int(m.group(1))
        if pend:
            cov[case] = pend
            pend = {}
        continue
    m = re.search(r'RDN-R6 zc1 xor=\w+ wsum=\w+ changed=(\d+) ixor=(\d+) isum=(\d+)', ln)
    if m and case and case not in dig:
        dig[case] = tuple(int(m.group(k)) for k in (1, 2, 3))
        continue
    m = re.search(r'RDN-R6 plh boot=%s zc=\d+ case=(\d+) lane=(\d) chunk=\d' % nonce, ln)
    if m:
        cur = (int(m.group(1)), int(m.group(2)))
        continue
    m = re.search(r'RDN-R6 pl(\d) (\d+) ((?:[0-9a-f]{8} ?){8})\s*$', ln)
    if m and cur:
        planes.setdefault(cur, {})[int(m.group(2))] = [int(x, 16) for x in m.group(3).split()]

obs = {}
for n in sc.ORDER:
    c = sc.CASE_NUM[n]
    if c not in cov:
        print('%-4s no coverage map' % n)
        continue
    words = [w for k in range(8) for w in cov[c][k]]
    px = set()
    for i in range(1024):
        if (words[i >> 4] >> (2 * (i & 15))) & 3:
            px.add((i % 32, i // 32))
    obs[n] = px
    print('%-4s %4d pixels written, digest %s' % (n, len(px), dig.get(c)))
obs['dig'] = dig
c = sc.CASE_NUM[sc.DEPTH_CASE]
if (c, 0) in planes:
    pl = dict((l, [w for k in range(32) for w in planes[(c, l)][k]]) for l in range(3))
    obs['AS8depth'] = do.values_from_planes(pl, 24)
    print('AS8   depth values %d, distinct %d' % (len(obs['AS8depth']), len(set(obs['AS8depth'].values()))))
pickle.dump(obs, open('build/r6k/observed_%s.pkl' % nonce, 'wb'))
