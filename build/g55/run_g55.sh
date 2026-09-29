#!/bin/bash
# run_g55.sh -- G5-5 (docs/G5_5_BATCH_SIZE_PLAN.md 3): does a smaller batch (two or more in the ring) make
# the world frame faster?  GLQuake +map start, 300 frames, RDNMesaTime=1 RDNMesaTimeSplit=150, the batch
# cap N in {driver's own, 1350, 1000}, alternated twice (A B C A B C) because one scene varies between
# runs.  Before and after each run `r5op tdump` makes the kernel print its sticky async line; the
# judge subtracts.  ON SCREEN: the user's gcdsd.
#   bash build/g55/run_g55.sh
set -u
P=$(cd "$(dirname "$0")/../.." && pwd); G=$(cd "$P/.." && pwd)
N=/ndrv/openstep-radeon9250; T=$N/build/g55; L=$P/build/g55; OP=$P/build/r7b/r5op.sh
mach() { (cd "$G" && GCDS_CONF=etc/gcds.cnf timeout 590 ./bin/gcds next "$1") 2>&1 | sed 's/.*mach: //'; }
seed() { S=$(python3 -c "import time;print(int(time.time())-1000000000)"); echo $(( (S % 40000) * 100000 + $1 )); }
kline() { bash "$OP" tdump >/dev/null 2>&1; mach "grep 'RDN-R5 async' /usr/adm/messages | tail -1"; }
salt=100
for round in 1 2; do
  for cap in 0 1350 1000; do
    name=g55-r$round-n$cap; salt=$((salt + 1))
    envx=""; [ $cap != 0 ] && envx="RDNMesaBatchWords=$cap"
    rm -f "$L/$name.log"
    kline > "$L/$name.before"
    mach "cd /usr/local/quake; $envx RDNMesaTime=1 RDNMesaTimeSplit=150 RDNMesaSeed=$(seed $salt) sh /ndrv/openstep-quake/test/run-glquake-self.sh /usr/local/nxbuild/bin/glquake_radeon 300 110 0 -nosound +map start; cp /tmp/glq-self.log $T/$name.log; sync; egrep '^RDN-A' /tmp/glq-self.log | tail -1" | tail -1
    kline > "$L/$name.after"
    echo "== $name done"
  done
done
python3 "$P/build/g55/judge_g55.py" "$L"
