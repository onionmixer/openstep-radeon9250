"""R6e-2 host analysis: barycentric-weight quantization rules against the ff63a8c4 planes."""
import importlib.util, pickle, math
from fractions import Fraction as Fr
s=importlib.util.spec_from_file_location('g','/mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER/openstep-radeon9250/tools/r6/gouraud_oracle.py'); go=importlib.util.module_from_spec(s); s.loader.exec_module(go)
by=pickle.load(open('/mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER/openstep-radeon9250/build/r6e/observed_ff63a8c4.pkl','rb'))
def bary(pts,xy,off=8,pos='t16'):
    P=[(go.pos(x,pos),go.pos(y,pos)) for x,y in pts]
    (x0,y0),(x1,y1),(x2,y2)=P; A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0)
    sx,sy=Fr(16*xy[0]+off,16),Fr(16*xy[1]+off,16)
    l1=((sx-x0)*(y2-y0)-(x2-x0)*(sy-y0))/A; l2=((x1-x0)*(sy-y0)-(sx-x0)*(y1-y0))/A
    return [1-l1-l2,l1,l2]
def q(v,k,m):
    s=v*2**k
    if m=='t': n=math.floor(s)
    elif m=='r': n=math.floor(s+Fr(1,2))
    else: n=round(s)
    return Fr(n,2**k)
def rule(k,m,mode,f='floor'):
    def fn(L,c):
        if mode=='all': w=[q(l,k,m) for l in L]
        else:                                       # 'rest<i>': weight i = 1 - the other two quantized
            i=int(mode[-1]); w=[q(l,k,m) for l in L]; w[i]=1-sum(w[j] for j in range(3) if j!=i)
        v=sum(wi*ci for wi,ci in zip(w,c))
        return max(0,min(255,go.conv(v,f)))
    return fn
def score(fn,off=8,pos='t16'):
    bad=tot=0; worst=[]
    for n in go.ORDER:
        pts=go.GCASES[n][0]; pix=go.covered(pts)
        for lane in go.GCASES[n][2]:
            tr=go.lane_triple(n,lane); obs=go.unpack_plane(by[n][lane],pix)
            b=sum(1 for xy,o in zip(pix,obs) if fn(bary(pts,xy,off,pos),tr)!=o)
            bad+=b; tot+=len(pix)
            if b: worst.append((n,lane,b))
    return bad,tot,worst
