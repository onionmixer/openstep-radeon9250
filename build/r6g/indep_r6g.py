# independent recount of R6g: own log parser, own prefill, own compare, own pass/write rules
import re, sys, math
sys.path.insert(0,'tools/r6'); import depth_oracle as do          # only for the case table and coverage
log=open('build/r6/boot-04f45b10.full.log',errors='replace').read().splitlines()
planes,covs,cur,curc={},{},None,None
for ln in log:
    m=re.search(r'RDN-R6 plh boot=04f45b10 zc=(\d+) case=(\d+) lane=(\d+) chunk=(\d+) src=(\d+)', ln)
    if m: cur=(int(m.group(2)), int(m.group(3))); continue
    m=re.search(r'RDN-R6 pl(\d) (\d+) ((?:[0-9a-f]{8} ?){8})\s*$', ln)
    if m and cur: planes.setdefault(cur,{})[int(m.group(2))]=[int(w,16) for w in m.group(3).split()]
    m=re.search(r'RDN-R5 zclear boot=04f45b10 n=\d+ arg=[0-9a-f]+ len=(\d+) ', ln)
    if m: curc=int(m.group(1))          # the operation line comes FIRST; the cov lines follow it
    m=re.search(r'RDN-R6 cov(\d) ((?:[0-9a-f]{8} ?){8})\s*$', ln)
    if m and curc: covs.setdefault(curc,{})[int(m.group(1))]=[int(w,16) for w in m.group(2).split()]
def bit(v,b): return (v>>b)&1
def z16(x,y):
    b=(y>>4)*(64>>6)+(x>>6)
    return (bit(x,0)<<1)|(bit(y,0)<<2)|(bit(x,1)<<3)|(bit(y,1)<<4)|(bit(x,2)<<5)|(bit(x,4)<<6)|(bit(x,5)<<7)|(bit(x,3)<<8)|(bit(y,2)<<9)|(bit(y,3)<<10)|((b&1)<<11)|((b>>1)<<12)
def depth_of(case,x,y):
    i=y*32+x; v=0
    for l in (0,1):
        w=[q for k in range(32) for q in planes[(case,l)][k]][i//4]
        v |= ((w>>(8*(i%4)))&0xff)<<(8*l)
    return v
def code_of(case,x,y):
    i=y*32+x
    return (covs[case][i//(16*8)][(i//16)%8] >> (2*(i%16))) & 3
PIX=do.go.covered(do.GEOM['T1z'])
A,B,C = 15360,1024,512
stored=lambda x,y: A+B*x+C*y
Z=lambda z: math.floor(z*65536)
CMP={'NEVER':lambda n,o:False,'LESS':lambda n,o:n<o,'LEQUAL':lambda n,o:n<=o,'EQUAL':lambda n,o:n==o,
     'GEQUAL':lambda n,o:n>=o,'GREATER':lambda n,o:n>o,'NEQUAL':lambda n,o:n!=o,'ALWAYS':lambda n,o:True}
CASES=[('GN','NEVER',1,0.5),('GL','LESS',1,0.5),('GLE','LEQUAL',1,0.5),('GE','EQUAL',1,0.5),('GGE','GEQUAL',1,0.5),
       ('GG','GREATER',1,0.5),('GNE','NEQUAL',1,0.5),('GA','ALWAYS',1,0.5),('GLW','LESS',0,0.5),('GAW','ALWAYS',0,0.5),
       ('GF','EQUAL',1,0.5+2.0**-17),('GFG','GREATER',1,0.5+2.0**-17)]
bad=0
for name,func,write,z in CASES:
    c=do.GCASE_NUM[name]; nw=Z(z)
    pc=dc=0
    for (x,y) in PIX:
        ok=CMP[func](nw,stored(x,y))
        want_code = 1 if ok else 0
        want_depth = nw if (ok and write) else stored(x,y)
        if code_of(c,x,y)!=want_code: pc+=1
        if depth_of(c,x,y)!=want_depth: dc+=1
    npass=sum(1 for (x,y) in PIX if CMP[func](nw,stored(x,y)))
    print('%-4s %-8s write %d: predicted pass %3d | colour mismatches %d, depth mismatches %d' % (name,func,write,npass,pc,dc))
    bad += pc+dc
# the pixels outside the triangle must still hold the prefill
out=[(x,y) for y in range(32) for x in range(32) if (x,y) not in PIX and depth_of(do.GCASE_NUM['GA'],x,y)!=stored(x,y)]
print('GA: uncovered pixels whose depth changed: %d' % len(out)); bad+=len(out)
print('independent check:', 'PASS' if bad==0 else 'FAIL (%d)' % bad)
