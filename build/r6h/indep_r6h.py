# independent recount of R6h: own log parser, own interpolation, own texel address, own texel formula
import re, sys, math
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import tex_oracle as te      # only the case table and the covered set
log=open('build/r6/boot-ff9bdf88.full.log',errors='replace').read().splitlines()
planes,cur={},None
for ln in log:
    m=re.search(r'RDN-R6 plh boot=ff9bdf88 zc=(\d+) case=(\d+) lane=(\d+) chunk=(\d+) src=(\d+)', ln)
    if m: cur=(int(m.group(2)), int(m.group(3))); continue
    m=re.search(r'RDN-R6 pl(\d) (\d+) ((?:[0-9a-f]{8} ?){8})\s*$', ln)
    if m and cur: planes.setdefault(cur,{})[int(m.group(2))]=[int(w,16) for w in m.group(3).split()]
def pixel(case, x, y):
    i=y*32+x; v=0
    for l in range(4):
        w=[q for k in range(32) for q in planes[(case,l)][k]][i//4]
        v |= ((w>>(8*(i%4)))&0xff)<<(8*l)
    return v
def texel(u,v): return 0xff000000 | ((u*32)<<16) | ((v*32)<<8) | 0x55
V=[(4,4),(28,4),(4,28)]                         # T1z, written again here
def cover():                                     # the R6d rule, written again here
    out=[]
    for y in range(32):
        for x in range(32):
            sx,sy=Fr(2*x+1,2),Fr(2*y+1,2); ok=True
            for i in range(3):
                (ax,ay),(bx,by)=V[i],V[(i+1)%3]
                e=(bx-ax)*(sy-ay)-(by-ay)*(sx-ax)
                dx,dy=bx-ax,by-ay
                inc=(dy==0 and dx>0) or dy<0
                if e<0 or (e==0 and not inc): ok=False; break
            if ok: out.append((x,y))
    return out
PIX=cover()
def interp(vals, x, y):                          # at the pixel CORNER (the measured position)
    (x0,y0),(x1,y1),(x2,y2)=[(Fr(a),Fr(b)) for a,b in V]
    A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0)
    sx,sy=Fr(x),Fr(y)
    w1=((sx-x0)*(y2-y0)-(x2-x0)*(sy-y0))/A; w2=((x1-x0)*(sy-y0)-(sx-x0)*(y1-y0))/A
    return (1-w1-w2)*Fr(vals[0])+w1*Fr(vals[1])+w2*Fr(vals[2])
def idx(f, n, mode):
    t=math.floor(f)
    return max(0,min(n-1,t)) if mode=='clamp' else t % n
bad=0; tot=0
for c in te.ORDER:
    w,h,stride=te.tex_of(c); st,tt=te.st_of(c); mode=te.case_rule_of(c)
    row=max(w*4,32)//4                           # the measured row stride
    # the texture as the CPU wrote it
    words={}
    for v in range(h):
        for u in range(w):
            words[(v*stride)//4+u]=texel(u,v)
    for (x,y) in PIX:
        u=idx(interp(st,x,y)*w, w, mode); v=idx(interp(tt,x,y)*h, h, mode)
        want=words.get(v*row+u, 0xa5000000 | ((te.TEX_OFF//4 + v*row+u) & 0xffff))
        tot+=1; bad += pixel(te.CASE_NUM[c], x, y) != want
print('pixels', tot, 'mismatches', bad)
print('independent check:', 'PASS' if bad==0 else 'FAIL')
