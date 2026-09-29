#!/bin/sh
# target-park-extra-r2b0.sh -- after the operator has made OSRDNDisplay the
# display owner in Configure.app, move every SURPLUS OSRDNDisplay instance
# table out of the bundle, so the next boot configures exactly one device.
#
#   sh target-park-extra-r2b0.sh closed=yes
#
# docs/R2B0_IMPL_PLAN.md section 15-2 B.  Measured on 2026-09-16: Configure
# keeps the installed Instance0.table and ADDS Instance1.table with the real
# slot in "Location", so the activation boot would drive one card from two
# instances.
#
# WHY Instance0 IS THE ONE THAT STAYS.  The machine's /usr/etc/driverLoader
# (sum 62436 48, copied to build/r2b0/driverLoader.bin and disassembled on the
# host) opens Instance0.table, Instance1.table, ... and stops at the first
# number it cannot stat -- but when instance 0 is the missing one it falls back
# to the bundle's Default.table and still configures a device, then goes on to
# instance 1.  So parking Instance0 and keeping Instance1 gives TWO devices on
# the one card; parking Instance1..N and keeping Instance0 gives one.
#
#   1. closed=yes; Active Drivers names OSRDNDisplay and not VGA, as whole
#      tokens; the restore set named by /me/rdn-r2b0/CURRENT is whole and its
#      check.sh reports no EXTRA table outside OSRDNDisplay.config
#   2. the evidence exists on NFS before anything moves: <tag>/pre/PRECHECK_PASS
#      and a <tag>/postraw snapshot of the state Configure left
#   3. our bundle holds Instance0.table, every name is Instance<n>.table, and
#      Instance0.table's keys equal the installed Default.table's (Location and
#      Default Table aside) with the opt-in key "Yes" exactly once
#   4. a census of every *.config/Instance*.table is taken, the surplus tables
#      are copied to /me/rdn-r2b0/parked-activate.<tag>/, compared, then removed
#   5. the census is taken again: only our surplus tables may have gone, our
#      bundle must hold exactly Instance0.table; sync
#
# Nothing outside <drivers>/OSRDNDisplay.config is ever touched.  The parked
# copies stay in /me; restore.sh puts the pre snapshot back whatever happens.
#
# Target shell rules: ASCII, no printf, cut, $(...), grep -q, mkdir -p,
# test -e, dirname, ps, set --; no set -e; arguments read before any function;
# no while-read loop (a redirected loop is a subshell there).  R2B0_* overrides
# exist only for tools/r2b0/check_target_r2b0.py.

CLOSED="$1"

TMP=${R2B0_TMP:-/tmp}
DRV=${R2B0_DRV:-/private/Drivers/i386}
ME=${R2B0_ME:-/me/rdn-r2b0}
SUM=${R2B0_SUM:-/usr/bin/sum}
NFSOUT=${R2B0_NFSOUT:-/ndrv/openstep-radeon9250/build/r2b0}
BUNDLE=$DRV/OSRDNDisplay.config
SYSCFG=$DRV/System.config/Instance0.table
WORK=$TMP/rdn-park

fail() {
    why="$1"
    code="$2"
    echo "PARK FAIL $why"
    exit $code
}

keys() {
    kf="$1"
    ko="$2"
    n=`grep -c . $kf`
    awk -F'"' 'NF == 5 && $1 == "" { print $2 "=" $4 }' $kf | sort > $ko
    m=`grep -c . $ko`
    if [ "$n" != "$m" ]; then fail "$kf has $n lines but $m parse as table lines" 2; fi
    grep -v '^Location=' $ko | grep -v '^Default Table=' > $ko.cmp
}

if [ "$CLOSED" != "closed=yes" ]; then
    echo "usage: sh target-park-extra-r2b0.sh closed=yes   (Configure.app closed)"
    exit 2
fi

rm -rf $WORK
mkdir $WORK || fail "cannot make $WORK" 2

echo "=== 1. the machine is where this script expects ==="
if [ ! -f $SYSCFG ]; then fail "cannot read $SYSCFG" 2; fi
if [ ! -d $BUNDLE ]; then fail "no bundle directory $BUNDLE" 2; fi
n=`grep -c '^"Active Drivers" = "' $SYSCFG`
if [ "$n" != "1" ]; then fail "$SYSCFG has $n \"Active Drivers\" lines, want 1" 2; fi
AD=`sed -n 's/^"Active Drivers" = "\(.*\)";$/\1/p' $SYSCFG`
case "$AD" in
    ""|*[!A-Za-z0-9\ _-]*) fail "Active Drivers holds an odd value: '$AD'" 2 ;;
esac
seen=0
vga=0
for tok in $AD; do
    if [ "$tok" = "OSRDNDisplay" ]; then seen=`expr $seen + 1`; fi
    if [ "$tok" = "VGA" ]; then vga=`expr $vga + 1`; fi
done
echo "  Active Drivers: $AD"
if [ "$seen" != "1" ]; then fail "Active Drivers names OSRDNDisplay $seen times, want 1 (run this after the Configure switch)" 2; fi
if [ "$vga" != "0" ]; then fail "Active Drivers still names VGA: the switch did not happen" 2; fi

TAG=`cat $ME/CURRENT`
case "$TAG" in
    ""|*[!A-Za-z0-9-]*) fail "CURRENT holds no tag: '$TAG'" 2 ;;
esac
if [ ! -f $ME/set.$TAG/manifest ]; then fail "no restore set $ME/set.$TAG" 2; fi
sh $ME/check.sh > $WORK/check.out 2>&1
if [ $? -ne 0 ]; then cat $WORK/check.out; fail "check.sh refused the restore set" 2; fi
n=`grep -c '^CHECK SET OK ' $WORK/check.out`
if [ "$n" != "1" ]; then cat $WORK/check.out; fail "check.sh printed no verdict line" 2; fi
n=`grep -c '^  EXTRA   ' $WORK/check.out`
m=`grep -c '^  EXTRA   OSRDNDisplay.config/' $WORK/check.out`
echo "  restore set $TAG staged, extra tables $n (ours $m)"
if [ "$n" != "$m" ]; then
    grep '^  EXTRA   ' $WORK/check.out
    fail "a table nobody expected is in the bundles: stop and look (restore.sh would refuse it too)" 3
fi

echo "=== 2. the evidence is on NFS before anything moves ==="
if [ ! -f $NFSOUT/cfg/$TAG/pre/PRECHECK_PASS ]; then fail "no $NFSOUT/cfg/$TAG/pre/PRECHECK_PASS" 2; fi
if [ ! -f $NFSOUT/cfg/$TAG/postraw/LIST ]; then fail "no $NFSOUT/cfg/$TAG/postraw/LIST: snapshot the state Configure left first" 2; fi
echo "  pre/PRECHECK_PASS and postraw/LIST are there"

echo "=== 3. our bundle ==="
ours=""
for t in $BUNDLE/Instance*.table; do
    if [ ! -f $t ]; then continue; fi
    nm=`basename $t`
    case "$nm" in
        Instance[0-9].table|Instance[0-9][0-9].table) ;;
        *) fail "unexpected instance table name: $nm" 3 ;;
    esac
    ours="$ours $nm"
done
echo "  instance tables:$ours"
if [ ! -f $BUNDLE/Instance0.table ]; then
    fail "the bundle has no Instance0.table: driverLoader would fall back to Default.table AND still take Instance1 -- a person has to look" 3
fi
if [ ! -f $BUNDLE/Default.table ]; then fail "the bundle has no Default.table" 3; fi
keys $BUNDLE/Instance0.table $WORK/inst
keys $BUNDLE/Default.table $WORK/def
if cmp -s $WORK/inst.cmp $WORK/def.cmp; then :; else
    echo "  Default.table keys:"; cat $WORK/def.cmp
    echo "  Instance0.table keys:"; cat $WORK/inst.cmp
    fail "Instance0.table is not the installed Default.table's keys" 3
fi
n=`grep -c '^"RDN R2B0 Record" = "Yes";$' $BUNDLE/Instance0.table`
if [ "$n" != "1" ]; then fail "Instance0.table does not say \"RDN R2B0 Record\" = \"Yes\" exactly once" 3; fi
echo "  Instance0.table matches Default.table and carries the opt-in key"

echo "=== 4. park the surplus ==="
PARK=$ME/parked-activate.$TAG
if [ -d $PARK ]; then fail "$PARK exists: a park is never overwritten" 3; fi
for t in $DRV/*.config/Instance*.table; do
    if [ -f $t ]; then echo "$t"; fi
done > $WORK/before
parked=0
for nm in $ours; do
    if [ "$nm" = "Instance0.table" ]; then continue; fi
    if [ ! -d $PARK ]; then mkdir $PARK || fail "mkdir $PARK" 4; fi
    if [ ! -d $PARK/OSRDNDisplay.config ]; then mkdir $PARK/OSRDNDisplay.config || fail "mkdir $PARK/OSRDNDisplay.config" 4; fi
    cp $BUNDLE/$nm $PARK/OSRDNDisplay.config/$nm || fail "cannot copy $nm to $PARK" 4
    cmp -s $BUNDLE/$nm $PARK/OSRDNDisplay.config/$nm || fail "the parked copy of $nm differs" 4
    rm -f $BUNDLE/$nm || fail "cannot remove $nm after parking it" 4
    parked=`expr $parked + 1`
    echo "  parked $nm"
done
sync

echo "=== 5. verify ==="
for t in $DRV/*.config/Instance*.table; do
    if [ -f $t ]; then echo "$t"; fi
done > $WORK/after
left=""
for t in $BUNDLE/Instance*.table; do
    if [ -f $t ]; then left="$left `basename $t`"; fi
done
echo "  instance tables now:$left"
if [ "$left" != " Instance0.table" ]; then fail "the bundle holds$left, want Instance0.table alone" 4; fi
bad=0
for t in `cat $WORK/before`; do
    if [ -f $t ]; then continue; fi
    case "$t" in
        $BUNDLE/Instance[0-9].table|$BUNDLE/Instance[0-9][0-9].table) ;;
        *) echo "  GONE $t"; bad=`expr $bad + 1` ;;
    esac
done
for t in `cat $WORK/after`; do
    n=`grep -c "^$t\$" $WORK/before`
    if [ "$n" = "0" ]; then echo "  APPEARED $t"; bad=`expr $bad + 1`; fi
done
if [ "$bad" != "0" ]; then fail "$bad table(s) outside our bundle changed while parking: is Configure.app open?" 4; fi
sync
echo "PARK DONE tag=$TAG parked=$parked left:$left" > $WORK/done
cat $WORK/done
if [ -d $NFSOUT/cfg/$TAG ]; then
    cat $WORK/done > $NFSOUT/cfg/$TAG/PARK.txt || fail "cannot write the NFS record (the park itself is done)" 5
    cmp -s $WORK/done $NFSOUT/cfg/$TAG/PARK.txt || fail "the NFS record differs (the park itself is done)" 5
    sync
fi
exit 0
