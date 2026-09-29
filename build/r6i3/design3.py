#!/usr/bin/env python3
"""R6i-3 design 3: with a TRANSPOSED pattern (R follows v, G follows u), does "48 across / 32 down"
follow the axis or the channel?  Count the pixels where the two readings differ."""
import math, sys
from fractions import Fraction as Fr
exec(open("build/r6i3/design2.py").read().split("SH=Fr(1,512)")[0])
SH=Fr(1,512)
def sweep_st(U0, span_x, span_y, V0, w=8, h=8):
    u0=U0+Fr(1,2); v0=V0+Fr(1,2)
    return (Fr(u0,w), Fr(u0+span_x,w), Fr(u0+span_y,w)), (Fr(v0,h),)*3
def sweep_ts(U0, V0, span_x, span_y, w=8, h=8):
    u0=U0+Fr(1,2); v0=V0+Fr(1,2)
    return (Fr(u0,w),)*3, (Fr(v0,h), Fr(v0+span_x,h), Fr(v0+span_y,h))
def pat3(u,v):   # transposed: R follows v, G follows u
    return 0xff000000 | ((255*(v&1))<<16) | ((255*(u&1))<<8) | 0x55
def pat2(u,v):
    return 0xff000000 | ((255*(u&1))<<16) | ((255*(v&1))<<8) | 0x55
def predict(st, tt, pat, r_h, r_v, w=8, h=8):
    out={}
    for (x,y) in COV:
        u=interp(st,x,y)*w-Fr(1,2); v=interp(tt,x,y)*h-Fr(1,2)
        i0,j0=math.floor(u),math.floor(v)
        ku,kv=math.floor((u-i0)*64), math.floor((v-j0)*64)
        word=0
        for lane in range(4):
            t=lambda du,dv: (pat((i0+du)&7,(j0+dv)&7)>>(8*lane))&0xff
            row0=(t(0,0)*(64-ku)+t(1,0)*ku+r_h)>>6
            row1=(t(0,1)*(64-ku)+t(1,1)*ku+r_h)>>6
            val=(row0*(64-kv)+row1*kv+r_v)>>6
            word |= max(0,min(255,val))<<(8*lane)
        out[(x,y)]=word
    return out
S1_st, S1_tt = sweep_st(Fr(0)+SH, Fr(15,16), Fr(1,16), Fr(1))      # u sweeps inside texel 0 (even)
S2_st, S2_tt = sweep_ts(Fr(2), Fr(0)+SH, Fr(15,16), Fr(1,16))      # v sweeps inside texel 0 (even)
for name,(st,tt) in (('S1 (u sweeps, pat3)', (S1_st,S1_tt)), ('S2 (v sweeps, pat3)', (S2_st,S2_tt))):
    axis=predict(st,tt,pat3,48,32)          # the constant follows the AXIS
    chan=predict(st,tt,pat3,32,48)          # ... or the CHANNEL (R keeps 48, G keeps 32)
    d=sum(1 for p in axis if axis[p]!=chan[p])
    mx=max(max(abs(((axis[p]>>(8*l))&0xff)-((chan[p]>>(8*l))&0xff)) for l in range(4)) for p in axis)
    print('%-22s: the two readings differ on %3d of %d pixels (largest %d LSB)' % (name, d, len(axis), mx))
# and the bit-set separation on S3 among the open candidates
st,tt=sweep_st(Fr(2)+SH, Fr(15,16), Fr(1,16), Fr(1))
prof=[(math.floor(interp(st,x,y)*8-Fr(1,2)), math.floor((interp(st,x,y)*8-Fr(1,2))%1*64)) for (x,y) in COV]
cand=(0,8,16,24,32)
print('S3 separations among the open bit-set candidates:')
for i in range(len(cand)):
    for j in range(i+1,len(cand)):
        d=sum(1 for i0,ku in prof if ((255*ku+cand[i])>>6)!=((255*ku+cand[j])>>6))
        print('   r=%2d vs r=%2d: %3d pixels' % (cand[i], cand[j], d))
