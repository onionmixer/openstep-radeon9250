#!/bin/bash
# usage: r5op.sh op [len] -- one CP operation on the target (R6e build)
cd /mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER
R=$(python3 -c "import time;print(int(time.time())-1000000000)")
B=/ndrv/openstep-radeon9250/build/r2b0/789832642
GCDS_CONF=etc/gcds.cnf ./bin/gcds next "sync; $B/rdnr5cp $R fb70d2a2 $* > $B/r5-$R-$1.out 2>&1; echo rc=\$? >> $B/r5-$R-$1.out; sync; sleep 2; cat $B/r5-$R-$1.out"
