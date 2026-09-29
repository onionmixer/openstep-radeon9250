#!/bin/bash
# usage: r5op.sh op [len] -- one CP operation on the target.
#
# THE BUILD IS NOT PINNED HERE ANY MORE.  It used to be: this script named
# build/r2b0/790003982 and the stamp 4529cb57 in its text.  M1h installed a new
# driver (436c03c0) and the tool of the OLD build refused it -- "RDNR5 exit=4
# state ... build=436c03c0" -- so every CP operation the runner issued did
# nothing, the CP never started, and all six modes declined for "no
# acceleration".  Nothing said "stale script"; the runner printed the op names
# with no results beside them.
#
# So the build comes from the INSTALLED marker: the newest build/r2b0/*/INSTALLED
# is the driver that was put on the machine, and its BUILD_PASS names the stamp.
# The tool still CHECKS the stamp against the driver in memory -- that gate is
# the point, and this only stops the script from feeding it last month's answer.
set -u
ROOT=/mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER
cd "$ROOT"
R=$(python3 -c "import time;print(int(time.time())-1000000000)")
eval "$(python3 - <<'PY'
import glob, os
best = None
for m in glob.glob('openstep-radeon9250/build/r2b0/*/INSTALLED'):
    d = os.path.dirname(m)
    try:
        runid = int(os.path.basename(d))
    except ValueError:
        continue
    if os.path.exists(os.path.join(d, 'rdnr5cp')) and os.path.exists(os.path.join(d, 'BUILD_PASS')):
        if best is None or runid > best[0]:
            best = (runid, d)
if best is None:
    print('echo "r5op: no installed build carries rdnr5cp" >&2; exit 2')
else:
    runid, d = best
    stamp = open(os.path.join(d, 'BUILD_PASS')).read().split()[0]
    print('RUNID=%d' % runid)
    print('STAMP=%s' % stamp)
PY
)"
B=/ndrv/openstep-radeon9250/build/r2b0/$RUNID
GCDS_CONF=etc/gcds.cnf ./bin/gcds next "sync; $B/rdnr5cp $R $STAMP $* > $B/r5-$R-$1.out 2>&1; echo rc=\$? >> $B/r5-$R-$1.out; sync; sleep 2; cat $B/r5-$R-$1.out"
