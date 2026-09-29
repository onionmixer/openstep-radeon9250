#!/bin/sh
# target-build.sh -- build a packed R2a probe ON the OPENSTEP target and gate it.
#
#   sh target-build.sh <tar> <sum> <blocks>
#
# <tar> and the two numbers come from tools/r2a/pack_probe.py on the host.
# Nothing here loads anything: target-run.sh does that, separately.
#
# Written for the target's tools (docs: memory of the missing ones): no
# printf, cut, $(...), grep -q, mkdir -p, test -e, dirname, ps, set --; no
# positional parameter after the first function (the target sh does not
# restore them after a call); string checks are case patterns so that a
# missing command cannot turn a check into a silent pass.  ASCII only.
#
# Gate, in order; any failure stops with a line starting "R2ABUILD FAIL":
#   1. the tar's /usr/bin/sum equals what the host printed
#   2. BUILD_STAMP is 8 lower-case hex digits and not 00000000; RUNID is a
#      decimal number; the tar holds no Load_Commands.sect.in
#   3. Load_Commands.sect, comments and blank lines aside, is exactly
#      CALL radeonR2aEntry <RUNID> / WIRE / START
#   4. make with OTHER_CFLAGS=-DR2A_BUILD=0x<stamp> produces the reloc
#   5. the load commands in the product carry no ADVERTISE and the CALL
#   6. every undefined symbol of the product is exported by /mach_kernel
#      (_splhigh and _splx among them)
#   7. the reloc is copied to <nfs>/<runid>/RDNR2aProbe_reloc and the copy's
#      sum must equal the reloc's; the sum goes to <nfs>/<runid>/reloc.sum
#      for tools/r2a/check_reloc.py on the host
# On PASS it writes /tmp/RDNR2aProbe/R2ABUILD_PASS ("<stamp> <runid> <sum> <blocks>"
# of the reloc), which target-run.sh requires and re-checks before loading.
# A MANIFEST marked UNCHECKED (pack_probe.py --skip-hostcheck) is refused.
# Build in /tmp, never on the NFS share (a build scatters objects through
# the tree).  /tmp is cleared at boot.

# Paths are the target's; the R2A_* overrides exist only so that
# tools/r2a/check_target_r2a.py can run this file on the host against
# fake tools.  Nothing on the target sets them.
TMP=${R2A_TMP:-/tmp}
SUM=${R2A_SUM:-/usr/bin/sum}
KERNEL=${R2A_KERNEL:-/mach_kernel}
NFSOUT=${R2A_NFSOUT:-/ndrv/openstep-radeon9250/build/r2a}

TAR="$1"
WANTSUM="$2"
WANTBLK="$3"
TOP=$TMP/RDNR2aProbe
RELOCDIR=$TOP/RDNR2aProbe_reloc.tproj
RELOC=$TOP/RDNR2aProbe.config/RDNR2aProbe_reloc

fail() {
    why="$1"
    echo "R2ABUILD FAIL $why"
    exit 1
}

if [ "$TAR" = "" ] || [ "$WANTSUM" = "" ] || [ "$WANTBLK" = "" ]; then
    echo "usage: sh target-build.sh <tar> <sum> <blocks>"
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
if [ ! -d $RELOCDIR ]; then fail "tar has no RDNR2aProbe_reloc.tproj"; fi

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
sed -e '/^#/d' -e '/^[ 	]*$/d' $RELOCDIR/Load_Commands.sect | awk '{ $1 = $1; print }' > $TMP/rdn-r2a-lc.got
echo "CALL radeonR2aEntry $RUNID" > $TMP/rdn-r2a-lc.want
echo "WIRE" >> $TMP/rdn-r2a-lc.want
echo "START" >> $TMP/rdn-r2a-lc.want
if cmp -s $TMP/rdn-r2a-lc.got $TMP/rdn-r2a-lc.want; then
    echo "  ok"
else
    echo "  got:"; cat $TMP/rdn-r2a-lc.got
    fail "Load_Commands.sect is not CALL radeonR2aEntry $RUNID / WIRE / START"
fi

echo "=== 4. make ==="
cd $TOP || fail "cd $TOP"
# make's own status, not that of a filter after it
make "OTHER_CFLAGS=-DR2A_BUILD=0x$STAMP" > $TMP/rdn-r2a-make.log 2>&1
mst=$?
grep -v "^cc -static" $TMP/rdn-r2a-make.log
echo "=== MAKE_DONE exit $mst ==="
if [ "$mst" != "0" ]; then fail "make exited $mst"; fi
if [ ! -f $RELOC ]; then fail "no product $RELOC"; fi
ls -l $RELOC
# the bundle postamble appends a "Server Name" line to the one in the source
# (driverkit/Makefile.bundle_postamble:4), so count: all must name RDNR2aProbe
all=`grep -c '"Server Name"' $TOP/RDNR2aProbe.config/Default.table`
ours=`grep -c '^"Server Name" = "RDNR2aProbe";$' $TOP/RDNR2aProbe.config/Default.table`
echo "  Server Name lines: $all, naming RDNR2aProbe: $ours"
if [ "$all" = "0" ] || [ "$all" != "$ours" ]; then fail "built Default.table does not name server RDNR2aProbe"; fi

echo "=== 5. load commands (product) ==="
strings $RELOC | egrep '^(CALL|WIRE|START|ADVERTISE|SMAP|DETACH|PORT_DEATH)' > $TMP/rdn-r2a-lc.bin
cat $TMP/rdn-r2a-lc.bin
n=`egrep -c '^(ADVERTISE|SMAP|DETACH|PORT_DEATH)' $TMP/rdn-r2a-lc.bin`
if [ "$n" != "0" ]; then fail "product carries ADVERTISE/SMAP/DETACH/PORT_DEATH"; fi
n=`egrep -c "^CALL radeonR2aEntry $RUNID\$" $TMP/rdn-r2a-lc.bin`
if [ "$n" != "1" ]; then fail "product does not carry exactly one CALL radeonR2aEntry $RUNID"; fi

echo "=== 6. nm -u against $KERNEL ==="
nm $KERNEL > $TMP/rdn-r2a-kernsyms.txt
miss=0
seen=0
for s in `nm -u $RELOC | sed 's/^ *//'`; do
    seen=`expr $seen + 1`
    n=`grep -c " $s\$" $TMP/rdn-r2a-kernsyms.txt`
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
RS1=`$SUM $RELOC | awk '{print $1}'`
RS2=`$SUM $RELOC | awk '{print $2}'`
case "$RS1$RS2" in
    ""|*[!0-9]*) fail "cannot sum the product: '$RS1 $RS2'" ;;
esac
RSUM="$RS1 $RS2"

echo "=== 7. copy the reloc for the host disassembly gate ==="
if [ ! -d $NFSOUT ]; then mkdir $NFSOUT || fail "cannot create $NFSOUT"; fi
if [ ! -d $NFSOUT/$RUNID ]; then mkdir $NFSOUT/$RUNID || fail "cannot create $NFSOUT/$RUNID"; fi
rm -f $NFSOUT/$RUNID/RDNR2aProbe_reloc $NFSOUT/$RUNID/reloc.sum $NFSOUT/$RUNID/R2ARELOC_PASS
cp $RELOC $NFSOUT/$RUNID/RDNR2aProbe_reloc || fail "cannot copy the reloc to $NFSOUT/$RUNID"
sync
CS1=`$SUM $NFSOUT/$RUNID/RDNR2aProbe_reloc | awk '{print $1}'`
CS2=`$SUM $NFSOUT/$RUNID/RDNR2aProbe_reloc | awk '{print $2}'`
echo "  reloc sum $RSUM, copy sum $CS1 $CS2"
if [ "$CS1 $CS2" != "$RSUM" ]; then fail "the copy on $NFSOUT differs from the reloc"; fi
echo "$RSUM" > $NFSOUT/$RUNID/reloc.sum
sync

echo "$STAMP $RUNID $RSUM" > $TOP/R2ABUILD_PASS
echo "R2ABUILD PASS stamp=$STAMP runid=$RUNID reloc=$RELOC symbols=$seen sum=$RSUM"
echo "host: python3 tools/r2a/check_reloc.py build/r2a/$RUNID/RDNR2aProbe_reloc $RSUM --marker build/r2a/$RUNID"
exit 0
