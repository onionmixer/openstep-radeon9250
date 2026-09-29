#!/bin/sh
# target-run-r2b0.sh -- on the activation boot, ask OSRDNDisplay for its
# record once, and capture everything.  Run ON the target, as root, detached:
#
#   nohup sh target-run-r2b0.sh <runid> < /dev/null > /tmp/rdn-r2b0-run.out 2>&1 &
#
# and watch <nfs>/<runid>/run.done from the host.  nxlogd is checked on the
# host (tools/nx-logcatch.sh status) before starting; `ps' is never used.
#
# docs/R2B0_IMPL_PLAN.md sections 2 B, 7 and 9.  The run does not load,
# unload or configure anything; the record runs inside the driver when the
# tool sets "RDNR2b0Record".
#   0. <nfs>/<runid>/BUILD_PASS, R2B0RELOC_PASS and INSTALLED name the same
#      reloc bytes, and the installed reloc is those bytes
#   1. Active Drivers names OSRDNDisplay and not VGA (the activation boot);
#      /me/rdn-r2b0/check.sh says the restore set is whole (Configure.app is
#      not checked: this boot has no screen for it)
#   2. the tool is copied from NFS to /tmp and must sum as BUILD_PASS says
#   3. rdnr2b0 <runid> <stamp> state: it reads RDNR2b0State, the driver logs
#      one line through IOLog, and we wait up to 10 s for that line to reach
#      /usr/adm/messages.  This is the in-boot syslog proof; a logger marker
#      is not used because this machine's syslog.conf routes user.notice
#      nowhere (docs/R1C_RESULT.md fact 5, build/r1c/syslog-check.txt).
#      Nothing has touched hardware at this point.
#   4. the run id is claimed with mkdir /me/rdn-r2b0-ran.d/<runid> (atomic,
#      survives a reboot: the same run id never runs twice).  A claim that
#      fails leaves the earlier run's run.done untouched.
#   5. the facts so far are copied to NFS and synced (a hang in the record
#      must not take the evidence with it), then rdnr2b0 <runid> <stamp>;
#      then wait up to 60 s for the record's end line
#   6. <nfs>/<runid>/: rdn-r2b0-<runid>.log (syslog since the mark),
#      rdnr2b0.out, rdnr2b0-state.out, check.out, kl_util -s, and run.done
#      with the final line -- on every exit after the run id is claimed
#
# Target shell rules: ASCII, no printf, cut, $(...), grep -q, mkdir -p,
# test -e, dirname, ps, set --; arguments read before any function.
# R2B0_* overrides are for tools/r2b0/check_target_r2b0.py only.

RUNID="$1"

TMP=${R2B0_TMP:-/tmp}
SUM=${R2B0_SUM:-/usr/bin/sum}
DRV=${R2B0_DRV:-/private/Drivers/i386}
ME=${R2B0_ME:-/me/rdn-r2b0}
RANDIR=${R2B0_RANDIR:-/me/rdn-r2b0-ran.d}
MSGS=${R2B0_MSGS:-/usr/adm/messages}
KLUTIL=${R2B0_KLUTIL:-/usr/etc/kl_util}
NFSOUT=${R2B0_NFSOUT:-/ndrv/openstep-radeon9250/build/r2b0}
SYSCFG=$DRV/System.config/Instance0.table
DONE=""
LOG=""

finish() {
    line="$1"
    echo "$line"
    if [ "$LOG" != "" ] && [ -f "$LOG" ]; then
        cp $LOG $NFSOUT/$RUNID/rdn-r2b0-$RUNID.log
    fi
    if [ -f $TMP/rdn-r2b0-tool-$RUNID.out ]; then
        cp $TMP/rdn-r2b0-tool-$RUNID.out $NFSOUT/$RUNID/rdnr2b0.out
    fi
    if [ -f $TMP/rdn-r2b0-check-$RUNID.out ]; then
        cp $TMP/rdn-r2b0-check-$RUNID.out $NFSOUT/$RUNID/check.out
    fi
    if [ "$DONE" != "" ]; then
        echo "$line" > $DONE
        sync
    fi
}

fail() {
    finish "R2B0RUN FAIL $1"
    exit 1
}

case "$RUNID" in
    ""|*[!0-9]*) echo "usage: sh target-run-r2b0.sh <runid>"; exit 2 ;;
esac
if [ ! -d $NFSOUT/$RUNID ]; then echo "R2B0RUN FAIL no $NFSOUT/$RUNID (NFS not mounted, or never built)"; exit 1; fi

echo "=== 0. markers ==="
for m in BUILD_PASS R2B0RELOC_PASS INSTALLED; do
    if [ ! -f $NFSOUT/$RUNID/$m ]; then fail "no $NFSOUT/$RUNID/$m"; fi
done
STAMP=`awk '{ print $1 }' $NFSOUT/$RUNID/BUILD_PASS`
BRUN=`awk '{ print $2 }' $NFSOUT/$RUNID/BUILD_PASS`
RSUM=`awk '{ print $3, $4 }' $NFSOUT/$RUNID/BUILD_PASS`
TSUM=`awk '{ print $5, $6 }' $NFSOUT/$RUNID/BUILD_PASS`
case "$STAMP" in
    [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
    *) fail "BUILD_PASS stamp malformed: '$STAMP'" ;;
esac
if [ "$BRUN" != "$RUNID" ]; then fail "BUILD_PASS names run $BRUN"; fi
if [ "`cat $NFSOUT/$RUNID/R2B0RELOC_PASS`" != "$RSUM" ]; then fail "R2B0RELOC_PASS does not name $RSUM"; fi
if [ "`awk '{ print $2, $3 }' $NFSOUT/$RUNID/INSTALLED`" != "$RSUM" ]; then fail "INSTALLED does not name $RSUM"; fi
got=`$SUM $DRV/OSRDNDisplay.config/OSRDNDisplay_reloc | awk '{print $1, $2}'`
if [ "$got" != "$RSUM" ]; then fail "installed reloc sums '$got', BUILD_PASS $RSUM"; fi
echo "  stamp $STAMP reloc $RSUM tool $TSUM"

echo "=== 1. the activation boot ==="
if [ ! -f $SYSCFG ]; then fail "cannot read $SYSCFG"; fi
AD=`grep '"Active Drivers"' $SYSCFG`
echo "  $AD"
n=`echo "$AD" | grep -c 'OSRDNDisplay'`
if [ "$n" = "0" ]; then fail "Active Drivers does not name OSRDNDisplay: not the activation boot"; fi
n=`echo "$AD" | egrep -c '[" ]VGA[" ]'`
if [ "$n" != "0" ]; then fail "Active Drivers still names VGA"; fi
if [ ! -f $ME/check.sh ]; then fail "no $ME/check.sh: the restore set was never staged"; fi
sh $ME/check.sh > $TMP/rdn-r2b0-check-$RUNID.out 2>&1
cst=$?
cat $TMP/rdn-r2b0-check-$RUNID.out
if [ "$cst" != "0" ]; then fail "check.sh exit $cst: the restore set is not whole"; fi

echo "=== 2. tool ==="
TOOL=$TMP/rdnr2b0-$RUNID
rm -f $TOOL
cp $NFSOUT/$RUNID/rdnr2b0 $TOOL || fail "cannot copy the tool"
chmod 755 $TOOL || fail "chmod the tool"
if [ "`$SUM $TOOL | awk '{print $1, $2}'`" != "$TSUM" ]; then fail "the tool copy is not the bytes BUILD_PASS names"; fi

LOG=$TMP/rdn-r2b0-$RUNID.log
MARK=`wc -l < $MSGS | sed 's/ //g'`
case "$MARK" in
    ""|*[!0-9]*) fail "cannot count $MSGS lines: '$MARK'" ;;
esac
echo "R2B0FACTS stamp=$STAMP runid=$RUNID reloc=$RSUM syslog_was=$MARK" > $LOG
uname -a >> $LOG 2>&1
$KLUTIL -s >> $LOG 2>&1

echo "=== 3. syslog proof: a State read, which the driver logs (no hardware) ==="
$TOOL $RUNID $STAMP state > $TMP/rdn-r2b0-state-$RUNID.out 2>&1
sst=$?
cat $TMP/rdn-r2b0-state-$RUNID.out
cat $TMP/rdn-r2b0-state-$RUNID.out >> $LOG
echo "state-only exit $sst"
if [ "$sst" != "0" ]; then fail "the State read failed (exit $sst): the driver is not the one we built"; fi
waited=0
seen=0
while [ "$waited" -lt 10 ]; do
    n=`awk "NR > $MARK" $MSGS | grep -c "RDN-R2B0 state boot="`
    if [ "$n" != "0" ]; then seen=1; break; fi
    sleep 1
    waited=`expr $waited + 1`
done
if [ "$seen" != "1" ]; then fail "the driver's state line did not reach $MSGS in 10 s: is syslogd running?"; fi

echo "=== 4. run id $RUNID not run before (atomic) ==="
if [ ! -d $RANDIR ]; then mkdir $RANDIR || fail "cannot create $RANDIR"; fi
if mkdir $RANDIR/$RUNID 2> /dev/null; then
    :
else
    echo "R2B0RUN FAIL run id $RUNID was already run (or $RANDIR is not writable)"
    echo "  (run.done of the earlier run is left untouched)"
    exit 1
fi
sync
DONE=$NFSOUT/$RUNID/run.done
rm -f $DONE

echo "=== 5. the evidence so far, on NFS before the record ==="
cp $LOG $NFSOUT/$RUNID/rdn-r2b0-$RUNID.log || fail "cannot copy the log to NFS"
cp $TMP/rdn-r2b0-state-$RUNID.out $NFSOUT/$RUNID/rdnr2b0-state.out || fail "cannot copy the state output"
sync

echo "=== 6. record ==="
$TOOL $RUNID $STAMP > $TMP/rdn-r2b0-tool-$RUNID.out 2>&1
tst=$?
cat $TMP/rdn-r2b0-tool-$RUNID.out
echo "tool exit $tst"
found=0
waited=0
if [ "$tst" = "0" ]; then
    while [ "$waited" -lt 60 ]; do
        n=`awk "NR > $MARK" $MSGS | grep -c "RDN-R2B0 $RUNID end "`
        if [ "$n" != "0" ]; then found=1; break; fi
        sleep 1
        waited=`expr $waited + 1`
    done
fi

echo "=== 7. log ==="
echo "R2B0FACTS tool_exit=$tst end_found=$found waited=$waited" >> $LOG
awk "NR > $MARK" $MSGS >> $LOG
n=`grep -c "RDN-R2B0 $RUNID " $LOG`
echo "$n RDN-R2B0 lines for run $RUNID"
sync
if [ "$tst" != "0" ]; then fail "rdnr2b0 exit $tst (docs/R2B0_IMPL_PLAN.md 9: restore, no re-run)"; fi
if [ "$found" != "1" ]; then fail "no end line within 60 s"; fi
finish "R2B0RUN DONE $LOG"
echo "host: python3 tools/r2b0/parse_r2b0.py build/r2b0/$RUNID/rdn-r2b0-$RUNID.log $RUNID $STAMP --tool build/r2b0/$RUNID/rdnr2b0.out --out build/r2b0/$RUNID"
exit 0
