#!/bin/sh
# target-run.sh -- run the R2a probe built by target-build.sh, once, and
# capture its log.  Run ON the target, as root, detached:
#
#   nohup sh target-run.sh < /dev/null > /tmp/rdn-r2a-run.out 2>&1 &
#
# and watch <nfs>/<runid>/run.done from the host.  nxlogd is checked on the
# host (tools/nx-logcatch.sh status) before starting: `ps' from a detached
# job never returns on the target (2026-09-15).
#
# What it does:
#   D. shell facts (read-only): uname, the loaded-server list
#   0. refuses unless target-build.sh passed for this tree AND the reloc's
#      sum still equals the one it recorded AND the host's disassembly gate
#      (tools/r2a/check_reloc.py) wrote <nfs>/<runid>/R2ARELOC_PASS for
#      these same bytes
#   1. refuses unless Active Drivers names VGA and no Matrox driver (the
#      generic VGA baseline)
#   2. claims the run id with mkdir /me/rdn-r2a-ran.d/<runid> BEFORE loading
#      -- one atomic check-and-record, not in /tmp (cleared at boot) -- so the
#      same pack can never run twice, even after a hang and reboot
#   4. kl_util -a / -l; the load command CALLs radeonR2aEntry <runid>
#   5. waits up to 60 s for the probe's end line in /usr/adm/messages
#   6. kl_util -u / -d whatever happened in 5, also on SIGHUP/INT/TERM; an
#      unload that fails is a FAIL ("may still be loaded"), never DONE
#   7. writes /tmp/rdn-r2a-<runid>.log: the facts and the new syslog lines,
#      copies it to <nfs>/<runid>/, and writes <nfs>/<runid>/run.done with
#      the final R2ARUN line -- on every exit after the run id is known
#
# The probe writes CLOCK_CNTL_INDEX only, under the PLL group rules
# (docs/R1C_R2A_IMPL_PLAN.md section 2-4; hostcheck.sh, sim_r2a.py).  ASCII
# only; no printf, cut, $(...), grep -q, ps, set --.

# Target paths; R2A_* overrides are for tools/r2a/check_target_r2a.py only.
TMP=${R2A_TMP:-/tmp}
KLUTIL=${R2A_KLUTIL:-/usr/etc/kl_util}
MSGS=${R2A_MSGS:-/usr/adm/messages}
RANDIR=${R2A_RANDIR:-/me/rdn-r2a-ran.d}
SUM=${R2A_SUM:-/usr/bin/sum}
SYSCFG=${R2A_SYSCFG:-/private/Devices/System.config/Instance0.table}
NFSOUT=${R2A_NFSOUT:-/ndrv/openstep-radeon9250/build/r2a}
TOP=$TMP/RDNR2aProbe
RELOC=$TOP/RDNR2aProbe.config/RDNR2aProbe_reloc
SERVER=RDNR2aProbe
DONE=""
LOG=""

finish() {
    line="$1"
    echo "$line"
    if [ "$LOG" != "" ] && [ -f "$LOG" ] && [ -d "$NFSOUT/$RUNID" ]; then
        cp $LOG $NFSOUT/$RUNID/rdn-r2a-$RUNID.log
    fi
    if [ "$DONE" != "" ]; then
        echo "$line" > $DONE
        sync
    fi
}

fail() {
    finish "R2ARUN FAIL $1"
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

if [ ! -f $TOP/R2ABUILD_PASS ]; then fail "no R2ABUILD_PASS in $TOP: run target-build.sh first"; fi
if [ ! -f $RELOC ]; then fail "no product $RELOC"; fi
STAMP=`cat $TOP/BUILD_STAMP`
RUNID=`cat $TOP/RUNID`
case "$RUNID" in
    ""|*[!0-9]*) fail "runid malformed: '$RUNID'" ;;
esac
if [ -d $NFSOUT/$RUNID ]; then DONE=$NFSOUT/$RUNID/run.done; rm -f $DONE; fi
RS1=`$SUM $RELOC | awk '{print $1}'`
RS2=`$SUM $RELOC | awk '{print $2}'`
if [ "`cat $TOP/R2ABUILD_PASS`" != "$STAMP $RUNID $RS1 $RS2" ]; then
    fail "R2ABUILD_PASS does not name this tree and these reloc bytes ($STAMP $RUNID $RS1 $RS2)"
fi
if [ "$DONE" = "" ]; then fail "no $NFSOUT/$RUNID: target-build.sh did not copy the reloc"; fi
if [ ! -f $NFSOUT/$RUNID/R2ARELOC_PASS ]; then
    fail "no R2ARELOC_PASS in $NFSOUT/$RUNID: run tools/r2a/check_reloc.py on the host first"
fi
if [ "`cat $NFSOUT/$RUNID/R2ARELOC_PASS`" != "$RS1 $RS2" ]; then
    fail "R2ARELOC_PASS does not name these reloc bytes ($RS1 $RS2)"
fi
LOG=$TMP/rdn-r2a-$RUNID.log

echo "=== D. shell facts ==="
echo "R2AFACTS stamp=$STAMP runid=$RUNID reloc=$RS1.$RS2" > $LOG
uname -a >> $LOG 2>&1
$KLUTIL -s >> $LOG 2>&1
cat $LOG

echo "=== 1. ready to load ==="
# the baseline boot runs the generic VGA driver, not the G450 one
if [ ! -f $SYSCFG ]; then fail "cannot read $SYSCFG to check the display driver"; fi
grep '"Active Drivers"' $SYSCFG >> $LOG
n=`grep '"Active Drivers"' $SYSCFG | egrep -c 'MGA|Matrox'`
if [ "$n" != "0" ]; then fail "Active Drivers still names a Matrox driver: boot the generic VGA baseline"; fi
n=`grep '"Active Drivers"' $SYSCFG | egrep -c 'VGA'`
if [ "$n" = "0" ]; then fail "Active Drivers names no VGA driver: boot the generic VGA baseline"; fi

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
trap 'unload; finish "R2ARUN FAIL interrupted"; exit 1' 1 2 15
$KLUTIL -l $SERVER
st=$?
echo "kl_util -l exit $st"

echo "=== 5. wait for the end line ==="
waited=0
found=0
while [ "$waited" -lt 60 ]; do
    n=`awk "NR > $MARK" $MSGS | grep -c "RDN-R2A $RUNID end "`
    if [ "$n" != "0" ]; then found=1; break; fi
    sleep 1
    waited=`expr $waited + 1`
done
echo "end line found=$found after ${waited}s"

echo "=== 6. unload ==="
unload
trap 1 2 15

echo "=== 7. log ==="
echo "R2AFACTS load_exit=$st end_found=$found waited=$waited unload_failed=$unloadfail" >> $LOG
awk "NR > $MARK" $MSGS >> $LOG
n=`grep -c "RDN-R2A $RUNID " $LOG`
echo "$n RDN-R2A lines for run $RUNID in $LOG"
sync
if [ "$unloadfail" != "0" ]; then fail "unload failed: $SERVER may still be loaded (log kept in $LOG)"; fi
if [ "$found" != "1" ]; then fail "no end line within 60 s (log kept in $LOG)"; fi
finish "R2ARUN DONE $LOG"
echo "host: python3 tools/r2a/parse_r2a.py build/r2a/$RUNID/rdn-r2a-$RUNID.log $RUNID $STAMP build/r1/rdn-r1-789453017.log 789453017 --out build/r2a/$RUNID"
exit 0
