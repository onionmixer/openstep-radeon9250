#!/bin/sh
# target-install-r2b0.sh -- install the OSRDNDisplay bundle that
# target-build-r2b0.sh built, the way tools/install-matrox-driver.sh installs
# the Matrox one.  It does not activate anything: Active Drivers is not
# touched, and the machine's instance tables are kept byte for byte.
#
#   sh target-install-r2b0.sh closed=yes [fresh] [live]
#
# docs/R2B0_IMPL_PLAN.md sections 3 and 7 (S7).  closed=yes is the operator
# saying Configure.app is closed (it writes instance tables); it is recorded,
# not checked.  "fresh" installs the build's own instance tables instead of
# keeping the machine's -- for a table this project itself put there and has
# since corrected (2026-09-16: the shipped table named the server, which the
# bundle postamble appends, so the installed one held "Server Name" twice).
# The old bundle, its tables included, is still left at .prev.
#
# "live" permits the replacement while Active Drivers still names this driver.
# Gate 2 exists because replacing a bundle under a driver that is configured to
# load is how a half-written bundle becomes an unbootable display; without it
# the operator has to switch to VGA in Configure.app, install, and switch back,
# which is three reboots of churn for a driver that is reinstalled often.  What
# makes it acceptable to skip: the running driver is already in memory, so this
# boot is unaffected; the candidate is built whole in .new and moved into place
# in one rename; the old bundle stays at .prev; and if the next boot finds a
# broken bundle, driverLoader falls back to VGA.config/Default.table, which
# this project has checked is intact.  It is NOT the default, it is recorded in
# the INSTALLED marker, and gate 2 still refuses without it.
# (operator decision, 2026-09-16: "just reinstall, I will do the rest".)
#
#   1. the build tree's OSRDNBUILD_PASS equals <nfs>/<runid>/BUILD_PASS and
#      names these reloc bytes, and the host's disassembly gate wrote
#      <nfs>/<runid>/R2B0RELOC_PASS for them
#   2. Active Drivers does not name OSRDNDisplay (never replace a bundle
#      under a driver that is configured to load)
#   3. candidate <drivers>/OSRDNDisplay.config.new: the built bundle; if a
#      bundle is already installed, its Instance*.table files replace the
#      build's, byte for byte (without "fresh")
#   3b. every table of the candidate holds exactly one "Server Name" line and
#      it names OSRDNDisplay: the kernel reads the first value and user space
#      the last, so a duplicate is never installed
#   4. chown -R root.wheel, chmod -R go-w; refuse a symlink, anything not a
#      regular file or directory, a group/other-writable file, a file not
#      root/wheel, an empty member (the members include the Configure
#      inspector's executable and nib, docs/R3_MULTIMODE_PLAN.md 26-5)
#   5. the live instance tables are enumerated and compared again, then
#      rename the old bundle to .prev and the candidate into place
#   6. the installed reloc's sum equals BUILD_PASS; <nfs>/<runid>/INSTALLED
#
# Target shell rules: ASCII, no printf, cut, $(...), grep -q, mkdir -p,
# test -e, dirname, ps, set --; arguments read before any function.
# R2B0_* overrides are for tools/r2b0/check_target_r2b0.py only.

CLOSED="$1"
A2="$2"
A3="$3"
FRESH=""
LIVE=""
if [ "$A2" = "fresh" ]; then FRESH=fresh; fi
if [ "$A3" = "fresh" ]; then FRESH=fresh; fi
if [ "$A2" = "live" ]; then LIVE=live; fi
if [ "$A3" = "live" ]; then LIVE=live; fi

TMP=${R2B0_TMP:-/tmp}
SUM=${R2B0_SUM:-/usr/bin/sum}
DRV=${R2B0_DRV:-/private/Drivers/i386}
NFSOUT=${R2B0_NFSOUT:-/ndrv/openstep-radeon9250/build/r2b0}
TOP=$TMP/OSRDNDisplay-r2b0
SRC=$TOP/OSRDNDisplay/OSRDNDisplay.config
DST=$DRV/OSRDNDisplay.config
C=$DST.new
PREV=$DST.prev
LIST=$DST.find.list
SYSCFG=$DRV/System.config/Instance0.table
MEMBERS="OSRDNDisplay_reloc OSRDNDisplay Default.table Display.modes English.lproj/Localizable.strings English.lproj/DisplayInspector.nib/data.nib English.lproj/DisplayInspector.nib/data.classes English.lproj/DisplayInspector.nib/data.dependency"

fail() {
    why="$1"
    echo "INSTALL FAIL $why"
    rm -rf $C
    rm -f $LIST
    exit 1
}

refuse_if_any() {
    rmsg=$1
    shift
    rm -f $LIST
    find "$@" -print > $LIST
    if [ $? -ne 0 ]; then fail "find failed while checking: $rmsg"; fi
    if [ -s $LIST ]; then
        cat $LIST
        fail "$rmsg"
    fi
    rm -f $LIST
}

if [ "$CLOSED" != "closed=yes" ]; then
    echo "usage: sh target-install-r2b0.sh closed=yes [fresh] [live]   (Configure.app closed)"
    exit 2
fi
if [ "$A2" != "" ] && [ "$A2" != "fresh" ] && [ "$A2" != "live" ]; then
    echo "usage: sh target-install-r2b0.sh closed=yes [fresh] [live]"
    exit 2
fi
if [ "$A3" != "" ] && [ "$A3" != "fresh" ] && [ "$A3" != "live" ]; then
    echo "usage: sh target-install-r2b0.sh closed=yes [fresh] [live]"
    exit 2
fi

echo "=== 1. build and gate markers ==="
if [ ! -f $TOP/OSRDNBUILD_PASS ]; then fail "no $TOP/OSRDNBUILD_PASS: run target-build-r2b0.sh first (this boot)"; fi
RUNID=`cat $TOP/RUNID`
case "$RUNID" in
    ""|*[!0-9]*) fail "runid malformed: '$RUNID'" ;;
esac
if [ ! -f $NFSOUT/$RUNID/BUILD_PASS ]; then fail "no $NFSOUT/$RUNID/BUILD_PASS"; fi
if [ "`cat $TOP/OSRDNBUILD_PASS`" != "`cat $NFSOUT/$RUNID/BUILD_PASS`" ]; then fail "OSRDNBUILD_PASS and BUILD_PASS differ"; fi
RSUM=`awk '{ print $3, $4 }' $NFSOUT/$RUNID/BUILD_PASS`
if [ "`$SUM $SRC/OSRDNDisplay_reloc | awk '{print $1, $2}'`" != "$RSUM" ]; then fail "the built reloc is not the bytes BUILD_PASS names"; fi
if [ ! -f $NFSOUT/$RUNID/R2B0RELOC_PASS ]; then fail "no R2B0RELOC_PASS: run tools/r2b0/check_reloc_r2b0.py on the host first"; fi
if [ "`cat $NFSOUT/$RUNID/R2B0RELOC_PASS`" != "$RSUM" ]; then fail "R2B0RELOC_PASS does not name these reloc bytes ($RSUM)"; fi
echo "  runid $RUNID reloc $RSUM"

echo "=== 2. not configured to load ==="
if [ ! -f $SYSCFG ]; then fail "cannot read $SYSCFG"; fi
grep '"Active Drivers"' $SYSCFG
n=`grep '"Active Drivers"' $SYSCFG | grep -c 'OSRDNDisplay'`
if [ "$n" != "0" ] && [ "$LIVE" != "live" ]; then
    fail "Active Drivers names OSRDNDisplay: restore VGA before installing, or pass live"
fi
if [ "$n" != "0" ]; then
    echo "  live: replacing the bundle while Active Drivers still names it."
    echo "        this boot keeps the driver already in memory; the next boot gets the new one."
    echo "        the old bundle stays at $DST.prev, and VGA.config/Default.table is the fallback."
fi

echo "=== 3. candidate ==="
if [ ! -d $SRC ]; then fail "no built bundle at $SRC"; fi
rm -rf $C || fail "cannot clear $C"
cp -r $SRC $C || fail "cannot copy the built bundle"
insts=""
kept=""
if [ -d $DST ]; then
    for t in $DST/Instance*.table; do
        if [ -f $t ]; then
            nm=`basename $t`
            case "$nm" in
                Instance[0-9].table|Instance[0-9][0-9].table) ;;
                *) fail "unexpected instance table name: $nm" ;;
            esac
            insts="$insts $nm"
        fi
    done
fi
if [ -d $DST ] && [ "$FRESH" != "fresh" ]; then
    rm -f $C/Instance*.table || fail "cannot clear the build's instance tables"
    for nm in $insts; do
        cp $DST/$nm $C/$nm || fail "cannot preserve $nm"
    done
    kept="$insts"
    echo "  kept the machine's instance tables:$insts"
elif [ -d $DST ]; then
    if [ ! -f $C/Instance0.table ]; then fail "fresh install and the build has no Instance0.table"; fi
    echo "  fresh: the build's instance tables replace the machine's ($insts stay in .prev)"
else
    if [ ! -f $C/Instance0.table ]; then fail "first install and the build has no Instance0.table"; fi
    echo "  first install: the build's Instance0.table"
fi
rm -f $C/.lastBuildTime

echo "=== 3b. one \"Server Name\" per candidate table ==="
for t in $C/Default.table $C/Instance*.table; do
    if [ -f $t ]; then
        nm=`basename $t`
        all=`grep -c '"Server Name"' $t`
        ours=`grep -c '^"Server Name" = "OSRDNDisplay";$' $t`
        echo "  $nm: Server Name lines $all, naming OSRDNDisplay $ours (want 1 and 1)"
        if [ "$all" != "1" ] || [ "$ours" != "1" ]; then
            fail "candidate $nm holds $all \"Server Name\" line(s): the kernel reads the first and user space the last.  An old installed table needs 'fresh' (2026-09-16)"
        fi
    fi
done

echo "=== 4. ownership, modes, structure ==="
chown -R root.wheel $C || fail "chown failed"
chmod -R go-w $C || fail "chmod failed"
for m in $MEMBERS; do
    if [ ! -s $C/$m ]; then fail "missing or empty member: $m"; fi
done
refuse_if_any "a symlink in the bundle" $C -type l
refuse_if_any "not a regular file or directory" $C ! -type f ! -type d
refuse_if_any "group-writable in the bundle" $C -perm -020
refuse_if_any "other-writable in the bundle" $C -perm -002
refuse_if_any "not owned by root" $C ! -user root
refuse_if_any "not in group wheel" $C ! -group wheel
refuse_if_any "an empty file" $C -type f -size 0
for nm in $kept; do
    cmp -s $DST/$nm $C/$nm || fail "$nm did not survive the copy"
done

echo "=== 5. switch over ==="
rm -rf $PREV || fail "cannot clear $PREV"
now=""
if [ -d $DST ]; then
    for t in $DST/Instance*.table; do
        if [ -f $t ]; then now="$now `basename $t`"; fi
    done
fi
if [ "$now" != "$insts" ]; then fail "instance tables changed while installing ($insts ->$now): is Configure.app open?"; fi
for nm in $kept; do
    cmp -s $DST/$nm $C/$nm || fail "$nm changed while installing: is Configure.app open?"
done
sync
if [ -d $DST ]; then
    mv $DST $PREV || fail "cannot move the old bundle aside"
fi
mv $C $DST
if [ $? -ne 0 ]; then
    echo "INSTALL FAIL cannot move the new bundle into place"
    if [ -d $PREV ]; then
        mv $PREV $DST && echo "INSTALL FAIL the previous bundle was put back"
    fi
    exit 1
fi
sync

echo "=== 6. verify ==="
got=`$SUM $DST/OSRDNDisplay_reloc | awk '{print $1, $2}'`
if [ "$got" != "$RSUM" ]; then fail "installed reloc sums $got, BUILD_PASS $RSUM"; fi
for t in $DST/Default.table $DST/Instance*.table; do
    if [ -f $t ]; then
        n=`grep -c '^"Server Name" = "OSRDNDisplay";$' $t`
        a=`grep -c '"Server Name"' $t`
        if [ "$n" != "1" ] || [ "$a" != "1" ]; then fail "installed `basename $t` holds $a \"Server Name\" line(s)"; fi
    fi
done
echo "$RUNID $RSUM closed=yes live=$LIVE fresh=$FRESH `date`" > $NFSOUT/$RUNID/INSTALLED
sync
echo "INSTALL DONE runid=$RUNID reloc=$RSUM tables:$insts kept:$kept"
exit 0
