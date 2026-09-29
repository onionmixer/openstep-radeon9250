#!/bin/sh
# G4-1b: the stock library's pictures of the GHOST_UV scenes (the accelerated ones are ub.*)
N=/ndrv/openstep-radeon9250; O=$N/build/g3c
cd /tmp
head -3 /tmp/cc-gs13.log
cc -O -m486 -D__OPENSTEP__ -DGHOST_STOCK -I/tmp -I/LocalDeveloper/Headers $N/build/g3c/ghostprobe_v14.c -L/LocalDeveloper/Libraries -lGL -lm -o /tmp/ghostprobe_stock14 > /tmp/cc-gs14.log 2>&1
echo CCS=$?
grep error /tmp/cc-gs14.log | head -3
GHOST_UV=1 ./ghostprobe_stock14 0 0 0 $O/uk | egrep 'GHOST uv'
sync
