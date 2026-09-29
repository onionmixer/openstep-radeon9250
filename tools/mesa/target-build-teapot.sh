#!/bin/sh
# target-build-teapot.sh -- build the M3a teapot on the target, both links
# (docs/M3A_PLAN.md 4).
#
#   sh target-build-teapot.sh <library runid> <runid>
#
# <library runid> names build/m1b/<library runid>/libGL_radeon.a, which
# target-build-mesa.sh made; this script does not rebuild the library.
#
# The teapot geometry is cut here, at build time, out of Mesa 3.4.2's own
# widgets-mesa/demos/tea.c lines 581-730 -- the patch table, the control points
# and the evaluator loop -- and is never committed.  That region carries SGI's
# and Mark J. Kilgard's notice, which NOTICE reproduces.  No other driver
# project is read.

set -u
LIBRUN=${1:-}
RUNID=${2:-}
# grep decides, not `case $x in *[!0-9]*)` -- that bracket form refuses good
# values on this shell (recorded trap)
ok1=`echo "$LIBRUN" | grep -c '^[0-9][0-9]*$'`
ok2=`echo "$RUNID" | grep -c '^[0-9][0-9]*$'`
if [ "$ok1" != "1" ]; then echo "usage: target-build-teapot.sh <library runid> <runid>"; exit 2; fi
if [ "$ok2" != "1" ]; then echo "usage: target-build-teapot.sh <library runid> <runid>"; exit 2; fi

MOUNT=/ndrv
PROJ=$MOUNT/openstep-radeon9250
MESA=$MOUNT/openstep-mesa342/upstream/Mesa-3.4.2
TEA=$MESA/widgets-mesa/demos/tea.c
LIB=$PROJ/build/m1b/$LIBRUN/libGL_radeon.a
OUT=$PROJ/build/m3a/$RUNID
TMP=/tmp/rdnteapot.$RUNID
HDRS=/LocalDeveloper/Headers
CC="cc -m486"

fail() { echo "RDNTEAPOT BUILD FAIL $*"; exit 1; }

echo "=== 1. inputs ==="
[ -f "$LIB" ] || fail "no $LIB -- run target-build-mesa.sh $LIBRUN first"
[ -f "$TEA" ] || fail "no $TEA"
[ -f /LocalDeveloper/Libraries/libGL.a ] || fail "no stock libGL.a"
echo "  library  $LIB"
echo "  geometry $TEA"

# no `mkdir -p`: this mkdir reads -p as a directory NAME (recorded trap)
rm -rf "$TMP"; mkdir "$TMP" || fail "cannot make $TMP"
if [ -d "$OUT" ]; then fail "$OUT exists: this run id was built before"; fi
if [ ! -d "$PROJ/build/m3a" ]; then mkdir "$PROJ/build/m3a" || fail "cannot make build/m3a"; fi
mkdir "$OUT" || fail "cannot make $OUT"

echo "=== 2. the geometry, cut from Mesa's tea.c ==="
sed -n '581,730p' "$TEA" > "$TMP/teapot-geometry.h" || fail "sed tea.c"
n=`wc -l < "$TMP/teapot-geometry.h"`
n=`echo $n`
[ "$n" = "150" ] || fail "the cut is $n lines, want 150 -- tea.c is not the file this names"
# one pattern a grep: this grep has no alternation (recorded trap)
c1=`grep -c 'cpdata' "$TMP/teapot-geometry.h"`
c2=`grep -c '^teapot(' "$TMP/teapot-geometry.h"`
[ "$c1" != "0" ] || fail "the cut has no cpdata"
[ "$c2" = "1" ] || fail "the cut has $c2 teapot() definitions, want 1"
echo "  $n lines, the control points and teapot() are there"

echo "=== 3. rdnteapot-accel (libGL_radeon.a) ==="
$CC -O -Wall -I"$HDRS" -I"$PROJ/mesa" -I"$TMP" -o "$OUT/rdnteapot-accel" \
    "$PROJ/test/osrdn-mesa-teapot.c" "$LIB" -lm > "$TMP/cc-accel.log" 2>&1
rc=$?
cat "$TMP/cc-accel.log"
[ $rc = 0 ] || fail "cc accel exited $rc"

echo "=== 4. rdnteapot-stock (stock libGL.a, counters read 0) ==="
$CC -O -Wall -I"$HDRS" -I"$PROJ/mesa" -I"$TMP" -o "$OUT/rdnteapot-stock" \
    "$PROJ/test/osrdn-mesa-teapot.c" "$PROJ/test/osrdn-mesa-nocount.c" \
    -L/LocalDeveloper/Libraries -lGL -lm > "$TMP/cc-stock.log" 2>&1
rc=$?
cat "$TMP/cc-stock.log"
[ $rc = 0 ] || fail "cc stock exited $rc"

echo "$LIBRUN" > "$OUT/LIBRARY_RUNID"
rm -rf "$TMP"
echo "RDNTEAPOT BUILD PASS library=$LIBRUN runid=$RUNID"
