#!/bin/sh
# target-run.sh -- run the R1 probe built by target-build.sh, once, and
# capture its log.  Run ON the target, as root, after the operator has
# installed the Radeon and booted with it.
#
#   sh target-run.sh
#
# What it does:
#   D. shell facts for R1 section 4-D (read-only): uname, the memory device
#      nodes, the loaded-server list
#   0. refuses unless target-build.sh passed for this tree AND the reloc's
#      sum still equals the one it recorded
#   1. refuses unless nxlogd is running and Active Drivers names no Matrox
#      driver (the generic VGA baseline, plan R1 section 2)
#   2. claims the run id with mkdir /me/rdn-r1-ran.d/<runid> BEFORE loading
#      -- one atomic check-and-record, not in /tmp (cleared at boot) -- so the
#      same pack can never run twice, even after a hang and reboot
#   4. kl_util -a / -l; the load command CALLs radeonR1Entry <runid>
#   5. waits up to 60 s for the probe's end line in /usr/adm/messages
#   6. kl_util -u / -d whatever happened in 5, also on SIGHUP/INT/TERM; an
#      unload that fails is a FAIL ("may still be loaded"), never DONE
#   7. writes /tmp/rdn-r1-<runid>.log: the facts and the new syslog lines
#
# The probe itself makes no device writes (hostcheck.sh, sim_r1.py).  ASCII
# only; no printf, cut, $(...), grep -q.

# Target paths; R1_* overrides are for tools/r1/check_target_scripts.sh only.
TMP=${R1_TMP:-/tmp}
KLUTIL=${R1_KLUTIL:-/usr/etc/kl_util}
MSGS=${R1_MSGS:-/usr/adm/messages}
RANDIR=${R1_RANDIR:-/me/rdn-r1-ran.d}
SUM=${R1_SUM:-/usr/bin/sum}
SYSCFG=${R1_SYSCFG:-/private/Devices/System.config/Instance0.table}
TOP=$TMP/RDNR1Probe
RELOC=$TOP/RDNR1Probe.config/RDNR1Probe_reloc
SERVER=RDNR1Probe

fail() {
    why="$1"
    echo "R1RUN FAIL $why"
    exit 1
}

loaded=0
unloadfail=0
unload() {
    if [ "$loaded" = "1" ]; then
        $KLUTIL -u $SERVER
        ust=$?
        echo "kl_util -u exit $ust"
        $KLUTIL -d $SERVER
        dst=$?
        echo "kl_util -d exit $dst"
        loaded=0
        if [ "$ust" != "0" ] || [ "$dst" != "0" ]; then unloadfail=1; fi
    fi
}

if [ ! -f $TOP/R1BUILD_PASS ]; then fail "no R1BUILD_PASS in $TOP: run target-build.sh first"; fi
if [ ! -f $RELOC ]; then fail "no product $RELOC"; fi
STAMP=`cat $TOP/BUILD_STAMP`
RUNID=`cat $TOP/RUNID`
got=`$SUM $RELOC`
set -- $got
if [ "`cat $TOP/R1BUILD_PASS`" != "$STAMP $RUNID $1 $2" ]; then
    fail "R1BUILD_PASS does not name this tree and these reloc bytes ($STAMP $RUNID $1 $2)"
fi
LOG=$TMP/rdn-r1-$RUNID.log

echo "=== D. shell facts ==="
echo "R1FACTS stamp=$STAMP runid=$RUNID" > $LOG
uname -a >> $LOG 2>&1
ls -l /dev/mem /dev/kmem >> $LOG 2>&1
$KLUTIL -s >> $LOG 2>&1
cat $LOG

echo "=== 1. ready to load ==="
# the hang record lives only in nxlogd's copy on the host (plan R1 section 2)
n=`ps ax | grep nxlogd | grep -v grep | wc -l | sed 's/ //g'`
echo "  nxlogd processes: $n"
if [ "$n" = "0" ]; then fail "nxlogd is not running: start tools/nx-logcatch.sh on the host first"; fi
# the baseline boot runs the generic VGA driver, not the G450 one
if [ ! -f $SYSCFG ]; then fail "cannot read $SYSCFG to check the display driver"; fi
grep '"Active Drivers"' $SYSCFG >> $LOG
n=`grep '"Active Drivers"' $SYSCFG | egrep -c 'MGA|Matrox'`
if [ "$n" != "0" ]; then fail "Active Drivers still names a Matrox driver: boot the generic VGA baseline"; fi

echo "=== 2. run id $RUNID not run before (atomic) ==="
if [ ! -d $RANDIR ]; then mkdir $RANDIR || fail "cannot create $RANDIR"; fi
# mkdir is the check and the record in one step: it fails if the id exists
mkdir $RANDIR/$RUNID 2> /dev/null || fail "run id $RUNID was already run (or $RANDIR is not writable): pack again"
sync

MARK=`wc -l < $MSGS | sed 's/ //g'`
case "$MARK" in
    ""|*[!0-9]*) fail "cannot count $MSGS lines: '$MARK'" ;;
esac
echo "syslog was $MARK lines"

echo "=== 4. load ==="
$KLUTIL -a $RELOC
st=$?
echo "kl_util -a exit $st"
if [ "$st" != "0" ]; then fail "kl_util -a failed"; fi
loaded=1
# an interrupt from here on still unloads
trap 'echo "R1RUN FAIL interrupted"; unload; exit 1' 1 2 15
$KLUTIL -l $SERVER
st=$?
echo "kl_util -l exit $st"

echo "=== 5. wait for the end line ==="
waited=0
found=0
while [ "$waited" -lt 60 ]; do
    n=`awk "NR > $MARK" $MSGS | grep -c "RDN-R1 $RUNID end "`
    if [ "$n" != "0" ]; then found=1; break; fi
    sleep 1
    waited=`expr $waited + 1`
done
echo "end line found=$found after ${waited}s"

echo "=== 6. unload ==="
unload
trap 1 2 15

echo "=== 7. log ==="
echo "R1FACTS load_exit=$st end_found=$found waited=$waited unload_failed=$unloadfail" >> $LOG
awk "NR > $MARK" $MSGS >> $LOG
n=`grep -c "RDN-R1 $RUNID " $LOG`
echo "$n RDN-R1 lines for run $RUNID in $LOG"
sync
if [ "$unloadfail" != "0" ]; then fail "unload failed: $SERVER may still be loaded (log kept in $LOG)"; fi
if [ "$found" != "1" ]; then fail "no end line within 60 s (log kept in $LOG)"; fi
echo "R1RUN DONE $LOG"
echo "host: python3 tools/r1/parse_r1.py <fetched copy of $LOG> $RUNID $STAMP"
exit 0
