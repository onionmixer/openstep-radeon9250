import re, sys, pickle
sys.path.insert(0,'tools/r6'); import tex_oracle as te
log=open('build/r6/boot-ff9bdf88.full.log',errors='replace').read().splitlines()
planes,cur={},None
for ln in log:
    m=re.search(r'RDN-R6 plh boot=ff9bdf88 zc=(\d+) case=(\d+) lane=(\d+) chunk=(\d+) src=(\d+)', ln)
    if m: cur=(int(m.group(2)), int(m.group(3))); continue
    m=re.search(r'RDN-R6 pl(\d) (\d+) ((?:[0-9a-f]{8} ?){8})\s*$', ln)
    if m and cur: planes.setdefault(cur,{})[int(m.group(2))]=[int(w,16) for w in m.group(3).split()]
obs={}
for n in te.ORDER:
    c=te.CASE_NUM[n]; pl={}
    for l in range(4):
        ws=planes[(c,l)]; assert sorted(ws)==list(range(32)), (n,l)
        pl[l]=[w for k in range(32) for w in ws[k]]
    px={}
    for (x,y) in te.go.covered(te.GEOM):
        i=y*32+x
        px[(x,y)]=sum(((pl[l][i//4] >> (8*(i%4))) & 0xff) << (8*l) for l in range(4))
    obs[n]=px
pickle.dump(obs, open('build/r6h/observed_ff9bdf88.pkl','wb'))
# which texel did each pixel get?  invert the texel formula
def uv_of(word):
    if (word >> 24) != 0xff or (word & 0xff) != 0x55: return None
    return ((word >> 16) & 0xff) // 32, ((word >> 8) & 0xff) // 32
for n in te.ORDER:
    bad=[p for p,v in obs[n].items() if uv_of(v) is None]
    print('%-3s pixels %3d  texels %2d  not a texel: %d' % (n, len(obs[n]), len(set(obs[n].values())), len(bad)))
