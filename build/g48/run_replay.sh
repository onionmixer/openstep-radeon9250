#!/bin/bash
# G4-8 (docs/G4_8_REPLAY_PLAN.md 4): replay the frozen stream <reps> times through rdnreplay, crumbs on NFS,
# then the kernel log's tail and the crumb judge.  Offscreen; works under either gcdsd.
#   bash build/g48/run_replay.sh <reps> [words] [file] [w0]   (words: a prefix on a packet boundary, default 4067;
#                                                    file: a target path, default the frozen stream)
REPS=${1:?reps}; WORDS=${2:-4067}; FILE=${3:-/ndrv/openstep-radeon9250/build/g46/trace-last.bin}; W0=${4:-}
HOSTFILE=$(echo "$FILE" | sed "s#^/ndrv/openstep-radeon9250#/mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER/openstep-radeon9250#")
P=/mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER/openstep-radeon9250
G=/mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER
R=$(python3 -c "import time;print(int(time.time())-1000000000)")
C=$P/build/g48/replay-$R.crumbs
echo "runid $R reps $REPS words $WORDS file $FILE crumbs $C $(date +%T)"
(cd $G && GCDS_CONF=etc/gcds.cnf timeout 590 ./bin/gcds next "sync; /ndrv/openstep-radeon9250/build/g48/rdnreplay $R 38 $FILE words=$WORDS reps=$REPS crumb=/ndrv/openstep-radeon9250/build/g48/replay-$R.crumbs; echo rc=\$?; sync") 2>&1 | tee $P/build/g48/replay-$R.log | cut -c1-170
echo "== kernel log (this run's last lines)"
(cd $G && GCDS_CONF=etc/gcds.cnf timeout 120 ./bin/gcds next "grep 'RDN-R5 zclear\|RDN-G3\|rc=[1-9]' /usr/adm/messages | grep -v ' rc=0 ' | tail -4; grep -c 'RDN-R4 open' /usr/adm/messages") 2>&1 | tail -5 | cut -c1-170
if [ -n "$W0" ]; then python3 $P/tools/g48/judge_replay.py $C --reps $REPS --w0 $W0 --stream $HOSTFILE --words $WORDS; else python3 $P/tools/g48/judge_replay.py $C --reps $REPS; fi
