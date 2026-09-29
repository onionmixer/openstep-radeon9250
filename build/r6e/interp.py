"""R6e plan prototype: named colour-interpolation rules (exact rational arithmetic)."""
import importlib.util, math, itertools
from fractions import Fraction as Fr
import numpy as np
s=importlib.util.spec_from_file_location('t','/mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER/openstep-radeon9250/tools/r6/tri_oracle.py'); t=importlib.util.module_from_spec(s); s.loader.exec_module(t)
COV=(16,'trunc',8,'tl','n')                      # R6d, measured
POS=('exact','t16','t8')
OFFS=[(ox,oy) for ox in (0,4,8,12) for oy in (0,4,8,12)]
ANCH=('v0','top','bbox','tile8','row')
QS=(4,6,8,10,12,16); QM=('trunc','round')
ARITH=[('exact',)]+[('q',q,m,a) for q in QS for m in QM for a in ANCH]+[('f32',)]
SCALE=('c','c256'); FS=('floor','round','even','ceil')
def rules():
    for p in POS:
        for o in OFFS:
            for a in ARITH:
                for sc in SCALE:
                    for f in FS:
                        yield (p,o,a,sc,f)
def pos(v,p):
    """setup coordinate: 'exact', or <mode><prec> with mode t(runc) r(ound half up) e(ven)"""
    n=t.fix(v)
    if p!='exact':
        n=t.snap(n,int(p[1:]),{'t':'trunc','r':'round','e':'even'}[p[0]])
    return Fr(n,t.S)
def qz(v,q,m):
    """to 2^-q: trunc = floor (toward -inf), tz = toward zero, round = half up"""
    s=v*(1<<q)
    if m=='trunc': k=math.floor(s)
    elif m=='tz': k=math.floor(s) if s>=0 else math.ceil(s)
    else: k=math.floor(s+Fr(1,2))
    return Fr(k,1<<q)
def conv(v,f):
    if f=='floor': k=math.floor(v)
    elif f=='ceil': k=math.ceil(v)
    elif f=='round': k=math.floor(v+Fr(1,2))
    else:
        k=round(v)                                # python: half to even, exact on Fractions
    return max(0,min(255,k))
_cache={}
def plane(pts,cols,p,o):
    """exact plane coefficients and the covered sample points"""
    key=(tuple(pts),tuple(cols),p,o)
    if key in _cache: return _cache[key]
    P=[(pos(x,p),pos(y,p)) for x,y in pts]
    (x0,y0),(x1,y1),(x2,y2)=P
    A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0)
    c=[Fr(v) for v in cols]
    dx=((c[1]-c[0])*(y2-y0)-(c[2]-c[0])*(y1-y0))/A
    dy=((c[2]-c[0])*(x1-x0)-(c[1]-c[0])*(x2-x0))/A
    cov=t.cover(pts,COV,32)
    pix=[(x,y) for y in range(32) for x in range(32) if cov[y][x]]
    smp={xy:(Fr(16*xy[0]+o[0],16),Fr(16*xy[1]+o[1],16)) for xy in pix}
    r=(P,c,dx,dy,pix,smp); _cache[key]=r; return r
def values(pts,cols,rule):
    """{(x,y): byte} for one triangle and one channel"""
    p,o,a,sc,f=rule
    cols=[v if sc=='c' else Fr(v*256,255) for v in cols]
    P,c,dx,dy,pix,smp=plane(pts,cols,p,o)
    (x0,y0)=P[0]
    out={}
    if a[0]=='exact':
        for xy in pix:
            sx,sy=smp[xy]; out[xy]=conv(c[0]+dx*(sx-x0)+dy*(sy-y0),f)
    elif a[0]=='f32':
        # float32 plane from v0: 'xy' x term then y term, each op rounded; 'yx' the other order;
        # 'fma' float32 coefficients, one rounding of the exact sum; 'c32' coefficients themselves
        # built in float32 from float32 vertex data, then 'xy'
        f32=np.float32
        var=a[1] if len(a)>1 else 'xy'
        if var=='c32':
            X=[f32(float(v[0])) for v in P]; Y=[f32(float(v[1])) for v in P]; C=[f32(float(v)) for v in c]
            A32=f32(f32(f32(X[1]-X[0])*f32(Y[2]-Y[0]))-f32(f32(X[2]-X[0])*f32(Y[1]-Y[0])))
            dxf=f32(f32(f32(f32(C[1]-C[0])*f32(Y[2]-Y[0]))-f32(f32(C[2]-C[0])*f32(Y[1]-Y[0])))/A32)
            dyf=f32(f32(f32(f32(C[2]-C[0])*f32(X[1]-X[0]))-f32(f32(C[1]-C[0])*f32(X[2]-X[0])))/A32)
        else:
            dxf,dyf=f32(float(dx)),f32(float(dy))
        c0,x0f,y0f=f32(float(c[0])),f32(float(x0)),f32(float(y0))
        for xy in pix:
            sx,sy=smp[xy]
            tx=f32(f32(float(sx))-x0f); ty=f32(f32(float(sy))-y0f)
            if var=='fma':
                v=f32(float(Fr(float(c0))+Fr(float(dxf))*Fr(float(tx))+Fr(float(dyf))*Fr(float(ty))))
            elif var=='yx':
                v=f32(f32(c0+f32(dyf*ty))+f32(dxf*tx))
            else:
                v=f32(f32(c0+f32(dxf*tx))+f32(dyf*ty))
            out[xy]=conv(Fr(float(v)),f)
    else:
        _,q,m,an=a
        qx,qy=qz(dx,q,m),qz(dy,q,m)
        if an=='v0': ax,ay=x0,y0
        elif an=='top': ax,ay=min(P,key=lambda v:(v[1],v[0]))
        elif an=='bbox': ax,ay=min(v[0] for v in P),min(v[1] for v in P)
        elif an=='tile8': ax,ay=Fr(math.floor(min(v[0] for v in P)/8)*8),Fr(math.floor(min(v[1] for v in P)/8)*8)
        if an!='row':
            base=qz(c[0]+dx*(ax-x0)+dy*(ay-y0),q,m)
            for xy in pix:
                sx,sy=smp[xy]; out[xy]=conv(base+qx*(sx-ax)+qy*(sy-ay),f)
        else:
            rows={}
            for xy in pix: rows.setdefault(xy[1],[]).append(xy)
            for y,r in rows.items():
                x_start=min(r)[0]; sx0,sy0=smp[(x_start,y)]
                base=qz(c[0]+dx*(sx0-x0)+dy*(sy0-y0),q,m)
                for xy in r:
                    out[xy]=conv(base+qx*(smp[xy][0]-sx0),f)
    return out

def sig_case(pts,cols):
    """{rule: tuple of bytes over the covered pixels} -- raw values computed once per 4 conversions"""
    out={}
    for p in POS:
        for o in OFFS:
            for a in ARITH:
                for sc in SCALE:
                    raw=values_raw(pts,cols,(p,o,a,sc))
                    keys=sorted(raw)
                    for f in FS:
                        out[(p,o,a,sc,f)]=tuple(conv(raw[k],f) for k in keys)
    return out

def values_raw(pts,cols,r4):
    p,o,a,sc=r4
    global conv
    saved=conv
    try:
        conv=lambda v,f: v
        return values(pts,cols,(p,o,a,sc,'floor'))
    finally:
        conv=saved


def diagnostic_rules():
    """named rules OUTSIDE the gated space (codex 2nd review): missing q widths, toward-zero
    truncation, every 1/16 sample offset, rounded setup coordinates, float32 orders"""
    out=[]
    for p in POS:
        for q in (5,7,9,11,13,14,15):
            for m in ('trunc','round','tz'):
                for a in ANCH:
                    for sc in SCALE:
                        for f in FS: out.append((p,(8,8),('q',q,m,a),sc,f))
        for q in QS:
            for a in ANCH:
                for sc in SCALE:
                    for f in FS: out.append((p,(8,8),('q',q,'tz',a),sc,f))
        for ox in range(16):
            for oy in range(16):
                if (ox,oy) in OFFS: continue
                for sc in SCALE:
                    for f in FS: out.append((p,(ox,oy),('exact',),sc,f))
        for var in ('yx','fma','c32'):
            for o in OFFS:
                for sc in SCALE:
                    for f in FS: out.append((p,o,('f32',var),sc,f))
    for p in ('r16','e16','r8','e8'):
        for o in OFFS:
            for a in (('exact',),('f32',)):
                for sc in SCALE:
                    for f in FS: out.append((p,o,a,sc,f))
    return out
