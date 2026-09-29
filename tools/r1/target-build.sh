#!/bin/sh
# target-build.sh -- build a packed R1 probe ON the OPENSTEP target and gate it.
#
#   sh target-build.sh <tar> <sum> <blocks>
#
# <tar> and the two numbers come from tools/r1/pack_probe.py on the host.
# Nothing here loads anything: target-run.sh does that, separately.
#
# Written for the target's tools (docs: memory of the missing ones): no
# printf, cut, $(...), grep -q, mkdir -p, test -e, dirname; string checks are
# case patterns so that a missing command cannot turn a check into a silent
# pass.  ASCII only.
#
# Gate, in order; any failure stops with a line starting "R1BUILD FAIL":
#   1. the tar's /usr/bin/sum equals what the host printed
#   2. BUILD_STAMP is 8 lower-case hex digits and not 00000000; RUNID is a
#      decimal number; the tar holds no Load_Commands.sect.in
#   3. Load_Commands.sect, comments and blank lines aside, is exactly
#      CALL radeonR1Entry <RUNID> / WIRE / START
#   4. make with OTHER_CFLAGS=-DR1_BUILD=0x<stamp> produces the reloc
#   5. the load commands in the product carry no ADVERTISE and the CALL
#   6. every undefined symbol of the product is exported by /mach_kernel
# On PASS it writes /tmp/RDNR1Probe/R1BUILD_PASS ("<stamp> <runid> <sum> <blocks>"
# of the reloc), which target-run.sh requires and re-checks before loading.
# A MANIFEST marked UNCHECKED (pack_probe.py --skip-hostcheck) is refused.
# Build in /tmp, never on the NFS share (a build scatters objects through
# the tree).  /tmp is cleared at boot.

# Paths are the target's; the R1_* overrides exist only so that
# tools/r1/check_target_scripts.sh can run this file on the host against
# fake tools.  Nothing on the target sets them.
TMP=${R1_TMP:-/tmp}
SUM=${R1_SUM:-/usr/bin/sum}
KERNEL=${R1_KERNEL:-/mach_kernel}

TAR="$1"
WANTSUM="$2"
WANTBLK="$3"
TOP=$TMP/RDNR1Probe
RELOCDIR=$TOP/RDNR1Probe_reloc.tproj
RELOC=$TOP/RDNR1Probe.config/RDNR1Probe_reloc

fail() {
    why="$1"
    echo "R1BUILD FAIL $why"
    exit 1
}

if [ "$TAR" = "" ] || [ "$WANTSUM" = "" ] || [ "$WANTBLK" = "" ]; then
    echo "usage: sh target-build.sh <tar> <sum> <blocks>"
    exit 2
fi
if [ ! -f "$TAR" ]; then fail "no such tar: $TAR"; fi

echo "=== 1. sum ==="
got=`$SUM "$TAR"`
set -- $got
GOTSUM="$1"
GOTBLK="$2"
echo "  tar sum $GOTSUM $GOTBLK, host said $WANTSUM $WANTBLK"
if [ "$GOTSUM" != "$WANTSUM" ] || [ "$GOTBLK" != "$WANTBLK" ]; then
    fail "sum differs: the tar is not the one packed"
fi

cd $TMP || fail "cd $TMP"
rm -rf $TOP
tar xf "$TAR" || fail "tar xf"
if [ ! -d $RELOCDIR ]; then fail "tar has no RDNR1Probe_reloc.tproj"; fi

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
if [ -f $RELOCDIR/Load_Commands.sect.in ]; then fail "template packed with the generated file"; fi
# a tree packed with --skip-hostcheck (for testing the packer) says so first
n=`grep -c '^UNCHECKED' $TOP/MANIFEST`
if [ "$n" != "0" ]; then fail "MANIFEST says UNCHECKED: this tree skipped the host gate"; fi
echo "  stamp $STAMP runid $RUNID"

echo "=== 3. load commands (source) ==="
# one command per line, comments and blank lines dropped, fields re-joined by
# single spaces; then compared with the expected three lines byte for byte
sed -e '/^#/d' -e '/^[ 	]*$/d' $RELOCDIR/Load_Commands.sect | awk '{ $1 = $1; print }' > $TMP/rdn-r1-lc.got
echo "CALL radeonR1Entry $RUNID" > $TMP/rdn-r1-lc.want
echo "WIRE" >> $TMP/rdn-r1-lc.want
echo "START" >> $TMP/rdn-r1-lc.want
if cmp -s $TMP/rdn-r1-lc.got $TMP/rdn-r1-lc.want; then
    echo "  ok"
else
    echo "  got:"; cat $TMP/rdn-r1-lc.got
    fail "Load_Commands.sect is not CALL radeonR1Entry $RUNID / WIRE / START"
fi

echo "=== 4. make ==="
cd $TOP || fail "cd $TOP"
# make's own status, not that of a filter after it
make "OTHER_CFLAGS=-DR1_BUILD=0x$STAMP" > $TMP/rdn-r1-make.log 2>&1
mst=$?
grep -v "^cc -static" $TMP/rdn-r1-make.log
echo "=== MAKE_DONE exit $mst ==="
if [ "$mst" != "0" ]; then fail "make exited $mst"; fi
if [ ! -f $RELOC ]; then fail "no product $RELOC"; fi
ls -l $RELOC
# the bundle postamble appends a "Server Name" line to the one in the source
# (driverkit/Makefile.bundle_postamble:4), so count: all must name RDNR1Probe
all=`grep -c '"Server Name"' $TOP/RDNR1Probe.config/Default.table`
ours=`grep -c '^"Server Name" = "RDNR1Probe";$' $TOP/RDNR1Probe.config/Default.table`
echo "  Server Name lines: $all, naming RDNR1Probe: $ours"
if [ "$all" = "0" ] || [ "$all" != "$ours" ]; then fail "built Default.table does not name server RDNR1Probe"; fi

echo "=== 5. load commands (product) ==="
strings $RELOC | egrep '^(CALL|WIRE|START|ADVERTISE|SMAP|DETACH|PORT_DEATH)' > $TMP/rdn-r1-lc.bin
cat $TMP/rdn-r1-lc.bin
n=`egrep -c '^(ADVERTISE|SMAP|DETACH|PORT_DEATH)' $TMP/rdn-r1-lc.bin`
if [ "$n" != "0" ]; then fail "product carries ADVERTISE/SMAP/DETACH/PORT_DEATH"; fi
n=`egrep -c "^CALL radeonR1Entry $RUNID\$" $TMP/rdn-r1-lc.bin`
if [ "$n" != "1" ]; then fail "product does not carry exactly one CALL radeonR1Entry $RUNID"; fi

echo "=== 6. nm -u against $KERNEL ==="
nm $KERNEL > $TMP/rdn-r1-kernsyms.txt
miss=0
seen=0
for s in `nm -u $RELOC | sed 's/^ *//'`; do
    seen=`expr $seen + 1`
    n=`grep -c " $s\$" $TMP/rdn-r1-kernsyms.txt`
    if [ "$n" = "0" ]; then
        echo "  MISSING  $s"
        miss=`expr $miss + 1`
    else
        echo "  ok       $s"
    fi
done
# the probe calls IOLog at least: zero undefined symbols means nm saw nothing
if [ "$seen" = "0" ]; then fail "nm -u listed no symbols: the check saw nothing"; fi
if [ "$miss" != "0" ]; then fail "$miss undefined symbol(s) missing from the kernel"; fi

# the reloc's sum goes into the marker: target-run.sh loads only these bytes
got=`$SUM $RELOC`
set -- $got
RSUM="$1 $2"
case "$1" in
    ""|*[!0-9]*) fail "cannot sum the product: '$got'" ;;
esac
echo "$STAMP $RUNID $RSUM" > $TOP/R1BUILD_PASS
echo "R1BUILD PASS stamp=$STAMP runid=$RUNID reloc=$RELOC symbols=$seen sum=$RSUM"
exit 0
