import re, sys, pickle
sys.path.insert(0, 'tools/r6'); import depth_oracle as do
log = open('build/r6/boot-e4d44687.full.log', errors='replace').read().splitlines()
planes, cur = {}, None
for ln in log:
    m = re.search(r'RDN-R6 plh boot=e4d44687 zc=(\d+) case=(\d+) lane=(\d+) chunk=(\d+) src=(\d+)', ln)
    if m:
        cur = (int(m.group(2)), int(m.group(3))); continue
    m = re.search(r'RDN-R6 pl(\d) (\d+) ((?:[0-9a-f]{8} ?){8})\s*$', ln)
    if m and cur:
        planes.setdefault(cur, {})[int(m.group(2))] = [int(w, 16) for w in m.group(3).split()]
obs = {}
for name in do.ORDER:
    c, bits = do.CASE_NUM[name], do.fmt_bits(name)
    pl = {}
    for l in range(3 if bits == 24 else 2):
        ws = planes[(c, l)]
        assert sorted(ws) == list(range(32)), (name, l)
        pl[l] = [w for k in range(32) for w in ws[k]]
    obs[name] = do.values_from_planes(pl, bits)
pickle.dump(obs, open('build/r6f/observed_e4d44687.pkl', 'wb'))
print('cases', len(obs), 'pixels', len(obs['I1_24']))
