#!/bin/sh
# target-build-r2b0.sh -- build the packed OSRDNDisplay R2b-0 bundle and its
# user tool ON the OPENSTEP target, and gate them.
#
#   sh target-build-r2b0.sh <tar> <sum> <blocks>
#
# <tar> and the numbers come from tools/r2b0/pack_r2b0.py.  Nothing here
# installs or loads anything.  Build in /tmp (a build scatters objects), keep
# every marker the later boots need on NFS (/tmp is cleared at boot).
#
# Gate, in order; any failure stops with a line starting "OSRDNBUILD FAIL":
#   1. the tar's sum equals what the host printed
#   2. BUILD_STAMP is 8 lower-case hex digits and not 00000000; RUNID decimal;
#      MANIFEST not UNCHECKED
#   3. Load_Commands.sect, comments and blank lines aside, is exactly WIRE
#   4. make with OTHER_CFLAGS=-DOSRDN_BUILD=0x<stamp> produces the reloc
#   5. the built bundle: Display.modes present (R3b-2); Default.table and
#      Instance0.table present, each with exactly one "Display Mode" line,
#      says "RDN R2B0 Record" = "Yes" once, every "Server Name" line names
#      OSRDNDisplay; the product's load commands are WIRE alone; the
#      inspector (R3d, docs/R3_MULTIMODE_PLAN.md 26-5): the three nib files
#      are non-empty, data.classes declares OSRDNDisplayInspector once, and
#      the bundle executable DEFINES .objc_class_name_OSRDNDisplayInspector
#      (nm type A, as the stock PS2Mouse.config defines its inspector).  The
#      executable's undefined symbols resolve inside Configure.app, so gate 6
#      stays on the reloc alone
#   6. every undefined symbol of the reloc is exported by /mach_kernel, and
#      _basicConsoleMode is among them
#   7. cc -O -Wall -o rdnr2b0 rdnr2b0.m -lDriver exits 0, and so does
#      rdnr4map.m (R4c, docs/R4C_VMAP_PLAN.md 11-4) and rdnr5cp.m (R5, docs/R5_PLAN.md 9-2)
#   8. the reloc and the tools are copied to <nfs>/<runid>/ and the copies'
#      sums must equal the originals' (rdnr4map's in rdnr4map.sum); the make log's cc lines go to
#      <nfs>/<runid>/make-cc.txt (26-3 H4 compares the reloc's with the
#      build before); <nfs>/<runid>/BUILD_PASS holds
#      "<stamp> <runid> <reloc sum> <reloc blocks> <tool sum> <tool blocks>"
#
# Target shell rules: ASCII, no printf, cut, $(...), grep -q, mkdir -p,
# test -e, dirname, ps, set --; arguments read before any function.
# R2B0_* overrides are for tools/r2b0/check_target_r2b0.py only.

TAR="$1"
WANTSUM="$2"
WANTBLK="$3"

TMP=${R2B0_TMP:-/tmp}
SUM=${R2B0_SUM:-/usr/bin/sum}
KERNEL=${R2B0_KERNEL:-/mach_kernel}
CC=${R2B0_CC:-cc}
NFSOUT=${R2B0_NFSOUT:-/ndrv/openstep-radeon9250/build/r2b0}
TOP=$TMP/OSRDNDisplay-r2b0
PROJ=$TOP/OSRDNDisplay
RELOCDIR=$PROJ/OSRDNDisplay_reloc.tproj
BUNDLE=$PROJ/OSRDNDisplay.config
RELOC=$BUNDLE/OSRDNDisplay_reloc
EXE=$BUNDLE/OSRDNDisplay
NIBD=$BUNDLE/English.lproj/DisplayInspector.nib
TOOL=$TOP/rdnr2b0
TOOL4=$TOP/rdnr4map
TOOL5=$TOP/rdnr5cp
TOOL7=$TOP/rdnr7sub
TOOL8=$TOP/rdnr7dev
TOOL9=$TOP/osrdnprobe
TOOLA=$TOP/osrdncaps

fail() {
    why="$1"
    echo "OSRDNBUILD FAIL $why"
    exit 1
}

if [ "$TAR" = "" ] || [ "$WANTSUM" = "" ] || [ "$WANTBLK" = "" ]; then
    echo "usage: sh target-build-r2b0.sh <tar> <sum> <blocks>"
    exit 2
fi
if [ ! -f "$TAR" ]; then fail "no such tar: $TAR"; fi

echo "=== 1. sum ==="
GOTSUM=`$SUM "$TAR" | awk '{print $1}'`
GOTBLK=`$SUM "$TAR" | awk '{print $2}'`
echo "  tar sum $GOTSUM $GOTBLK, host said $WANTSUM $WANTBLK"
if [ "$GOTSUM" != "$WANTSUM" ] || [ "$GOTBLK" != "$WANTBLK" ]; then
    fail "sum differs: the tar is not the one packed"
fi

cd $TMP || fail "cd $TMP"
rm -rf $TOP
tar xf "$TAR" || fail "tar xf"
if [ ! -d $RELOCDIR ]; then fail "tar has no OSRDNDisplay_reloc.tproj"; fi

echo "=== 2. stamp and run id ==="
STAMP=`cat $TOP/BUILD_STAMP`
RUNID=`cat $TOP/RUNID`
case "$STAMP" in
    00000000) fail "stamp is the unstamped value" ;;
    [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
    *) fail "stamp malformed: '$STAMP'" ;;
esac
case "$RUNID" in
    ""|*[!0-9]*) fail "runid malformed: '$RUNID'" ;;
esac
n=`grep -c '^UNCHECKED' $TOP/MANIFEST`
if [ "$n" != "0" ]; then fail "MANIFEST says UNCHECKED: this tree skipped the host gate"; fi
echo "  stamp $STAMP runid $RUNID"

echo "=== 3. load commands (source) ==="
sed -e '/^#/d' -e '/^[ 	]*$/d' $RELOCDIR/Load_Commands.sect | awk '{ $1 = $1; print }' > $TMP/rdn-r2b0-lc.got
echo "WIRE" > $TMP/rdn-r2b0-lc.want
if cmp -s $TMP/rdn-r2b0-lc.got $TMP/rdn-r2b0-lc.want; then
    echo "  ok"
else
    echo "  got:"; cat $TMP/rdn-r2b0-lc.got
    fail "Load_Commands.sect is not WIRE alone"
fi

echo "=== 3b. source tables leave \"Server Name\" to the postamble ==="
for t in Default.table Instance0.table; do
    if [ ! -f $PROJ/$t ]; then fail "the tar has no $t"; fi
    n=`grep -c '"Server Name"' $PROJ/$t`
    echo "  source $t: Server Name lines $n (want 0)"
    if [ "$n" != "0" ]; then
        fail "$t names the server itself; the driverkit bundle postamble appends that line, so the built table would hold it twice (2026-09-16)"
    fi
done

echo "=== 4. make ==="
cd $PROJ || fail "cd $PROJ"
make "OTHER_CFLAGS=-DOSRDN_BUILD=0x$STAMP" > $TMP/rdn-r2b0-make.log 2>&1
mst=$?
grep -v "^cc -static" $TMP/rdn-r2b0-make.log
grep "^cc " $TMP/rdn-r2b0-make.log > $TMP/rdn-r2b0-cc-lines.txt
echo "=== MAKE_DONE exit $mst ==="
if [ "$mst" != "0" ]; then fail "make exited $mst"; fi
if [ ! -f $RELOC ]; then fail "no product $RELOC"; fi
ls -l $RELOC

echo "=== 5. the built bundle ==="
if [ ! -f $BUNDLE/Display.modes ]; then fail "built bundle has no Display.modes"; fi
nm=`grep -c '^"Height:' $BUNDLE/Display.modes`
echo "  Display.modes: $nm mode lines"
if [ "$nm" = "0" ]; then fail "Display.modes lists no mode"; fi
for t in Default.table Instance0.table; do
    if [ ! -f $BUNDLE/$t ]; then fail "built bundle has no $t"; fi
    n=`grep -c '^"Display Mode" = ' $BUNDLE/$t`
    if [ "$n" != "1" ]; then fail "$t must hold exactly one \"Display Mode\" line (the kernel reads the first, user space the last)"; fi
    n=`grep -c '^"RDN R2B0 Record" = "Yes";$' $BUNDLE/$t`
    if [ "$n" != "1" ]; then fail "$t does not say \"RDN R2B0 Record\" = \"Yes\" exactly once"; fi
    all=`grep -c '"Server Name"' $BUNDLE/$t`
    ours=`grep -c '^"Server Name" = "OSRDNDisplay";$' $BUNDLE/$t`
    echo "  $t: Server Name lines $all, naming OSRDNDisplay $ours (want 1 and 1)"
    if [ "$all" != "1" ] || [ "$ours" != "1" ]; then
        fail "$t must hold exactly one \"Server Name\" line naming OSRDNDisplay (the postamble appends one)"
    fi
done
strings $RELOC | egrep '^(CALL|WIRE|START|ADVERTISE|SMAP|DETACH|PORT_DEATH)' > $TMP/rdn-r2b0-lc.bin
cat $TMP/rdn-r2b0-lc.bin
if cmp -s $TMP/rdn-r2b0-lc.bin $TMP/rdn-r2b0-lc.want; then :; else fail "product load commands are not WIRE alone"; fi
for f in data.nib data.classes data.dependency; do
    if [ ! -s $NIBD/$f ]; then fail "built bundle has no (or an empty) DisplayInspector.nib/$f"; fi
done
n=`grep -c '^OSRDNDisplayInspector = {' $NIBD/data.classes`
if [ "$n" != "1" ]; then fail "DisplayInspector.nib/data.classes declares OSRDNDisplayInspector $n times, not once"; fi
if [ ! -s $EXE ]; then fail "built bundle has no executable $EXE"; fi
nm $EXE > $TMP/rdn-r2b0-exe-syms.txt
grep objc_class_name_OSRDNDisplayInspector $TMP/rdn-r2b0-exe-syms.txt
n=`grep -c ' A \.objc_class_name_OSRDNDisplayInspector$' $TMP/rdn-r2b0-exe-syms.txt`
echo "  inspector class defined in the bundle executable: $n (want 1)"
if [ "$n" != "1" ]; then fail "the bundle executable does not define OSRDNDisplayInspector"; fi

echo "=== 6. nm -u against $KERNEL ==="
nm $KERNEL > $TMP/rdn-r2b0-kernsyms.txt
miss=0
seen=0
bcm=0
for s in `nm -u $RELOC | sed 's/^ *//'`; do
    seen=`expr $seen + 1`
    if [ "$s" = "_basicConsoleMode" ]; then bcm=1; fi
    n=`grep -c " $s\$" $TMP/rdn-r2b0-kernsyms.txt`
    if [ "$n" = "0" ]; then
        echo "  MISSING  $s"
        miss=`expr $miss + 1`
    else
        echo "  ok       $s"
    fi
done
if [ "$seen" = "0" ]; then fail "nm -u listed no symbols: the check saw nothing"; fi
if [ "$miss" != "0" ]; then fail "$miss undefined symbol(s) missing from the kernel"; fi
if [ "$bcm" != "1" ]; then fail "_basicConsoleMode is not an undefined symbol of the reloc"; fi

echo "=== 7. user tool ==="
cd $TOP || fail "cd $TOP"
rm -f $TOOL
$CC -O -Wall -o $TOOL $TOP/rdnr2b0.m -lDriver > $TMP/rdn-r2b0-cc.log 2>&1
cst=$?
cat $TMP/rdn-r2b0-cc.log
echo "=== CC_DONE exit $cst ==="
if [ "$cst" != "0" ]; then fail "cc exited $cst"; fi
if [ ! -f $TOOL ]; then fail "no tool $TOOL"; fi
# R4c: the mapping tool (docs/R4C_VMAP_PLAN.md 11-4), with r4map_want.c beside it
rm -f $TOOL4
$CC -O -Wall -o $TOOL4 $TOP/rdnr4map.m -lDriver > $TMP/rdn-r4map-cc.log 2>&1
cst=$?
cat $TMP/rdn-r4map-cc.log
echo "=== CC4_DONE exit $cst ==="
if [ "$cst" != "0" ]; then fail "cc rdnr4map exited $cst"; fi
if [ ! -f $TOOL4 ]; then fail "no tool $TOOL4"; fi
# R5: the CP tool (docs/R5_PLAN.md 9-2)
rm -f $TOOL5
$CC -O -Wall -o $TOOL5 $TOP/rdnr5cp.m -lDriver > $TMP/rdn-r5cp-cc.log 2>&1
cst=$?
cat $TMP/rdn-r5cp-cc.log
echo "=== CC5_DONE exit $cst ==="
if [ "$cst" != "0" ]; then fail "cc rdnr5cp exited $cst"; fi
if [ ! -f $TOOL5 ]; then fail "no tool $TOOL5"; fi
# R7a: the staging tool (docs/R7_PLAN.md 5)
rm -f $TOOL7
$CC -O -Wall -o $TOOL7 $TOP/rdnr7sub.m -lDriver > $TMP/rdn-r7sub-cc.log 2>&1
cst=$?
cat $TMP/rdn-r7sub-cc.log
echo "=== CC7_DONE exit $cst ==="
if [ "$cst" != "0" ]; then fail "cc rdnr7sub exited $cst"; fi
if [ ! -f $TOOL7 ]; then fail "no tool $TOOL7"; fi
# R7b: the PURE C client (docs/R7_PLAN.md 10).  No -lDriver on purpose: if this
# one ever needs it, the rung has failed and the build should say so.
rm -f $TOOL8
$CC -O -Wall -I$RELOCDIR -o $TOOL8 $TOP/rdnr7dev.c > $TMP/rdn-r7dev-cc.log 2>&1
cst=$?
cat $TMP/rdn-r7dev-cc.log
echo "=== CC8_DONE exit $cst ==="
if [ "$cst" != "0" ]; then fail "cc rdnr7dev exited $cst"; fi
if [ ! -f $TOOL8 ]; then fail "no tool $TOOL8"; fi
# M1a: the acceleration gate and its two C-only clients (docs/M1A_PLAN.md).
# No -lDriver on ANY of them: that is the property the rung exists to prove, and
# a link line that quietly gained it would make the whole ladder pointless.
rm -f $TOOL9
$CC -O -Wall -I$TOP -I$RELOCDIR -o $TOOL9 $TOP/osrdn-mesa-probe-test.c $TOP/OSRDNMesaProbe.c > $TMP/rdn-probe-cc.log 2>&1
cst=$?
cat $TMP/rdn-probe-cc.log
echo "=== CC9_DONE exit $cst ==="
if [ "$cst" != "0" ]; then fail "cc osrdnprobe exited $cst"; fi
if [ ! -f $TOOL9 ]; then fail "no tool $TOOL9"; fi
rm -f $TOOLA
$CC -O -Wall -I$RELOCDIR -o $TOOLA $TOP/osrdn-caps-client.c > $TMP/rdn-caps-cc.log 2>&1
cst=$?
cat $TMP/rdn-caps-cc.log
echo "=== CCA_DONE exit $cst ==="
if [ "$cst" != "0" ]; then fail "cc osrdncaps exited $cst"; fi
if [ ! -f $TOOLA ]; then fail "no tool $TOOLA"; fi

RS1=`$SUM $RELOC | awk '{print $1}'`
RS2=`$SUM $RELOC | awk '{print $2}'`
TS1=`$SUM $TOOL | awk '{print $1}'`
TS2=`$SUM $TOOL | awk '{print $2}'`
US1=`$SUM $TOOL4 | awk '{print $1}'`
US2=`$SUM $TOOL4 | awk '{print $2}'`
VS1=`$SUM $TOOL5 | awk '{print $1}'`
VS2=`$SUM $TOOL5 | awk '{print $2}'`
WS1=`$SUM $TOOL7 | awk '{print $1}'`
WS2=`$SUM $TOOL7 | awk '{print $2}'`
XS1=`$SUM $TOOL8 | awk '{print $1}'`
XS2=`$SUM $TOOL8 | awk '{print $2}'`
YS1=`$SUM $TOOL9 | awk '{print $1}'`
ZS1=`$SUM $TOOLA | awk '{print $1}'`
case "$RS1$RS2$TS1$TS2$US1$US2$VS1$VS2$WS1$WS2$XS1$XS2$YS1$ZS1" in
    ""|*[!0-9]*) fail "cannot sum the products: '$RS1 $RS2 $TS1 $TS2 $US1 $US2 $VS1 $VS2 $WS1 $WS2 $XS1 $XS2 $YS1 $ZS1'" ;;
esac

echo "=== 8. copies for the host gate and the activation boot ==="
if [ ! -d $NFSOUT ]; then mkdir $NFSOUT || fail "cannot create $NFSOUT"; fi
if [ -d $NFSOUT/$RUNID ]; then fail "$NFSOUT/$RUNID exists: this run id was built before, pack again"; fi
mkdir $NFSOUT/$RUNID || fail "cannot create $NFSOUT/$RUNID"
cp $RELOC $NFSOUT/$RUNID/OSRDNDisplay_reloc || fail "cannot copy the reloc"
cp $TOOL $NFSOUT/$RUNID/rdnr2b0 || fail "cannot copy the tool"
cp $TOOL4 $NFSOUT/$RUNID/rdnr4map || fail "cannot copy the mapping tool"
cp $TOOL5 $NFSOUT/$RUNID/rdnr5cp || fail "cannot copy the CP tool"
cp $TOOL7 $NFSOUT/$RUNID/rdnr7sub || fail "cannot copy the staging tool"
cp $TOOL8 $NFSOUT/$RUNID/rdnr7dev || fail "cannot copy the device tool"
cp $TOOL9 $NFSOUT/$RUNID/osrdnprobe || fail "cannot copy the probe test"
cp $TOOLA $NFSOUT/$RUNID/osrdncaps || fail "cannot copy the caps client"
cat $TMP/rdn-r2b0-cc-lines.txt > $NFSOUT/$RUNID/make-cc.txt || fail "cannot copy the compile lines"
sync
if [ "`$SUM $NFSOUT/$RUNID/OSRDNDisplay_reloc | awk '{print $1, $2}'`" != "$RS1 $RS2" ]; then
    fail "the reloc copy on $NFSOUT differs"
fi
if [ "`$SUM $NFSOUT/$RUNID/rdnr2b0 | awk '{print $1, $2}'`" != "$TS1 $TS2" ]; then
    fail "the tool copy on $NFSOUT differs"
fi
if [ "`$SUM $NFSOUT/$RUNID/rdnr4map | awk '{print $1, $2}'`" != "$US1 $US2" ]; then
    fail "the mapping tool copy on $NFSOUT differs"
fi
echo "$US1 $US2" > $NFSOUT/$RUNID/rdnr4map.sum
if [ "`$SUM $NFSOUT/$RUNID/rdnr5cp | awk '{print $1, $2}'`" != "$VS1 $VS2" ]; then
    fail "the CP tool copy on $NFSOUT differs"
fi
echo "$VS1 $VS2" > $NFSOUT/$RUNID/rdnr5cp.sum
echo "$RS1 $RS2" > $NFSOUT/$RUNID/reloc.sum
echo "$STAMP $RUNID $RS1 $RS2 $TS1 $TS2" > $NFSOUT/$RUNID/BUILD_PASS
sync
echo "$STAMP $RUNID $RS1 $RS2 $TS1 $TS2" > $TOP/OSRDNBUILD_PASS
echo "OSRDNBUILD PASS stamp=$STAMP runid=$RUNID reloc=$RS1.$RS2 tool=$TS1.$TS2 symbols=$seen"
echo "host: python3 tools/r2b0/check_reloc_r2b0.py build/r2b0/$RUNID/OSRDNDisplay_reloc $RS1 $RS2 --marker build/r2b0/$RUNID"
exit 0
