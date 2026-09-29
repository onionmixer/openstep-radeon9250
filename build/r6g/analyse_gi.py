# are GI's depth values the same ones R6f measured for the same slope (I1_16)?
import re, sys, pickle, math
sys.path.insert(0,'tools/r6'); import depth_oracle as do
log=open('build/r6/boot-04f45b10.full.log',errors='replace').read().splitlines()
planes,cur={},None
for ln in log:
    m=re.search(r'RDN-R6 plh boot=04f45b10 zc=(\d+) case=(\d+) lane=(\d+) chunk=(\d+) src=(\d+)', ln)
    if m: cur=(int(m.group(2)), int(m.group(3))); continue
    m=re.search(r'RDN-R6 pl(\d) (\d+) ((?:[0-9a-f]{8} ?){8})\s*$', ln)
    if m and cur: planes.setdefault(cur,{})[int(m.group(2))]=[int(w,16) for w in m.group(3).split()]
def vals(case, bits=16):
    pl={l: [w for k in range(32) for w in planes[(case,l)][k]] for l in range(2 if bits==16 else 3)}
    return do.values_from_planes(pl, bits)
gi = vals(do.GCASE_NUM['GI'])
r6f = pickle.load(open('build/r6f/observed_e4d44687.pkl','rb'))['I1_16']      # the same slope, measured last boot
pix = do.go.covered(do.GEOM[do.GEOM_G])
exact = do.g_drawn('GI', 1)
pred_c, pred_d = do.g_predict('GI')
passed = [p for p in pix if p in pred_c]
print('GI: pixels %d, passed (colour) %d' % (len(pix), len(passed)))
d_exact = [p for p in passed if gi[p] != exact[p]]
d_meas  = [p for p in passed if gi[p] != r6f[p]]
print('depth differs from exact interpolation: %d pixels (max |diff| %d)'
      % (len(d_exact), max([abs(gi[p]-exact[p]) for p in d_exact], default=0)))
print('depth differs from what R6f measured for the same slope: %d pixels' % len(d_meas))
# and the pixels that did not pass must hold the prefill
pf = do.g_prefill('GI')
kept = [p for p in pix if p not in pred_c and gi[p] != pf[p]]
print('pixels that failed the test but whose depth changed: %d' % len(kept))
