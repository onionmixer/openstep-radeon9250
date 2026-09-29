#!/bin/sh
# target-build-mesa.sh -- build libGL_radeon.a on the target (docs/M1B_PLAN.md 5, 6).
#
#   sh /ndrv/openstep-radeon9250/tools/mesa/target-build-mesa.sh <runid>
#
# A COMPLETE alternative libGL: the stock archive, plus one macro and the
# replaced osmesa.o, plus one object of ours.  Nothing in openstep-mesa342 is
# modified -- the hook sites are already there, dormant, behind an #ifdef the
# default build never defines.
#
# Written in sh, not csh, because every other target script of this project is
# and its traps are the ones already recorded.
#
# The gates this script itself carries:
#   B1  the ten hooks are DEFINED TEXT symbols in the archive
#   B2  no two archive members collide at the 15 characters ar keeps
#   B3  our accel object's UNDEFINED symbols are within an allow-list with no
#       way to draw in it -- a hook that drew could not link without one
#   G   the finished archive on NFS links through its index
# and it leaves the material for the host to judge F (provenance).

set -u
RUNID=${1:-}
# NOT `case $RUNID in *[!0-9]*)`: that bracket form refuses perfectly good values
# on this shell (recorded trap).  grep decides instead.
ok=`echo "$RUNID" | grep -c '^[0-9][0-9]*$'`
if [ "$ok" != "1" ]; then echo "usage: target-build-mesa.sh <runid>"; exit 2; fi

MOUNT=/ndrv
PROJ=$MOUNT/openstep-radeon9250
MESA=$MOUNT/openstep-mesa342/upstream/Mesa-3.4.2
STOCK=/LocalDeveloper/Libraries/libGL.a
OUT=$PROJ/build/m1b/$RUNID
TMP=/tmp/rdnmesa.$RUNID
CC="cc -m486"

fail() { echo "RDNMESA FAIL $*"; exit 1; }

echo "=== 1. inputs ==="
[ -f "$STOCK" ] || fail "no stock archive at $STOCK"
[ -f "$MESA/src/OSmesa/osmesa.c" ] || fail "no osmesa.c under $MESA"
[ -d "$PROJ/mesa" ] || fail "no $PROJ/mesa"
echo "  stock  $STOCK"
echo "  source $MESA/src/OSmesa/osmesa.c"

# no `mkdir -p` here: this mkdir takes -p for a directory NAME (recorded trap,
# with cut(1) and the bracket case).  Both parents already exist.
rm -rf "$TMP"; mkdir "$TMP" || fail "cannot make $TMP"
if [ -d "$OUT" ]; then fail "$OUT exists: this run id was built before"; fi
if [ ! -d "$PROJ/build/m1b" ]; then mkdir "$PROJ/build/m1b" || fail "cannot make build/m1b"; fi
mkdir "$OUT" || fail "cannot make $OUT"

echo "=== 2. osmesa.o, with the hook macro, FROM OUR TREE ==="
# From the port's own tree and never a staged copy: a change to the hook site
# would otherwise be compiled out of a stale file and nothing would say so.
$CC -O -c -DOPENSTEP_MESA_ACCEL_HOOK -I"$MESA/src" -I"$MESA/include" \
    -o "$TMP/osmesa.o" "$MESA/src/OSmesa/osmesa.c" > "$TMP/cc-osmesa.log" 2>&1
rc=$?
cat "$TMP/cc-osmesa.log"
[ $rc = 0 ] || fail "cc osmesa.c (hooked) exited $rc"

echo "=== 3. osmesa.o WITHOUT the macro, for the host's provenance gate (F3) ==="
$CC -O -c -I"$MESA/src" -I"$MESA/include" \
    -o "$TMP/osmesa-stock.o" "$MESA/src/OSmesa/osmesa.c" > "$TMP/cc-stockosmesa.log" 2>&1
rc=$?
[ $rc = 0 ] || fail "cc osmesa.c (stock flags) exited $rc"

echo "=== 4. our six units ==="
# M1g added OSRDNMesaTex.  A unit missing from this list does not fail here --
# it fails at the LINK, several steps later, as an undefined symbol with no
# hint of which file was never compiled.
for u in OSRDNMesaClass OSRDNMesaProbe OSRDNMesaStubs OSRDNMesaSurface \
         OSRDNMesaTri OSRDNMesaTex OSRDNMesaTexArena OSRDNMesaVerify OSRDNMesaDepth OSRDNMesaPresent \
         OSRDNMesaTime OSRDNMesaWindow OSRDNMesaReadPix; do
    $CC -O -c -I"$PROJ/mesa" -I"$PROJ/OSRDNDisplay/OSRDNDisplay_reloc.tproj" \
        -o "$TMP/$u.o" "$PROJ/mesa/$u.c" > "$TMP/cc-$u.log" 2>&1
    rc=$?
    cat "$TMP/cc-$u.log"
    [ $rc = 0 ] || fail "cc $u.c exited $rc"
done
# the hook unit is the only one that needs Mesa's headers
$CC -O -c -I"$PROJ/mesa" -I"$PROJ/OSRDNDisplay/OSRDNDisplay_reloc.tproj" \
    -I"$MESA/src" -I"$MESA/include" \
    -o "$TMP/OSRDNMesaHook.o" "$PROJ/mesa/OSRDNMesaHook.c" > "$TMP/cc-hook.log" 2>&1
rc=$?
cat "$TMP/cc-hook.log"
[ $rc = 0 ] || fail "cc OSRDNMesaHook.c exited $rc"

echo "=== 4b. every unit in mesa/ was compiled ==="
# The list above is written by hand and the directory is not.  Comparing them
# turns "a unit was forgotten" from a link error three steps later into a
# sentence naming the file.
# UNQUOTED, and measured: this shell does not expand a glob in a word that
# carries ANY quoted part.  "$PROJ"/mesa/*.c yielded the literal string and the
# loop ran once, complaining that "*.c" was never compiled -- a check that had
# to be believed to be understood.  $PROJ/mesa/*.c yields the seven files.
for f in $PROJ/mesa/*.c; do
    b=`basename "$f" .c`
    if [ "$b" = "OSRDNMesaHook" ]; then continue; fi
    if [ ! -f "$TMP/$b.o" ]; then fail "$b.c is in mesa/ but was never compiled"; fi
done
echo "  every .c in mesa/ has an object"

echo "=== 5. one object, not four ==="
# ar here truncates member names at 15 characters and ours agree well past that,
# so four members would become one and three would silently vanish.
ld -r -o "$TMP/osrdnaccel.o" "$TMP/OSRDNMesaHook.o" "$TMP/OSRDNMesaStubs.o" \
    "$TMP/OSRDNMesaClass.o" "$TMP/OSRDNMesaProbe.o" "$TMP/OSRDNMesaSurface.o" \
    "$TMP/OSRDNMesaTri.o" "$TMP/OSRDNMesaTex.o" "$TMP/OSRDNMesaTexArena.o" "$TMP/OSRDNMesaVerify.o" "$TMP/OSRDNMesaDepth.o" "$TMP/OSRDNMesaPresent.o" \
    "$TMP/OSRDNMesaTime.o" "$TMP/OSRDNMesaWindow.o" "$TMP/OSRDNMesaReadPix.o" \
    > "$TMP/ld.log" 2>&1
rc=$?
cat "$TMP/ld.log"
[ $rc = 0 ] || fail "ld -r exited $rc"

echo "=== 6. the archive ==="
cp "$STOCK" "$OUT/libGL_radeon.a" || fail "cannot copy the stock archive"
ar r "$OUT/libGL_radeon.a" "$TMP/osmesa.o" "$TMP/osrdnaccel.o" > "$TMP/ar.log" 2>&1
rc=$?
cat "$TMP/ar.log"
[ $rc = 0 ] || fail "ar exited $rc"
# likewise: ranlib warns about stock members that carry no symbols
ranlib "$OUT/libGL_radeon.a" 2>&1 | grep -v 'has no symbols'
if [ ! -s "$OUT/libGL_radeon.a" ]; then fail "the archive vanished"; fi

echo "=== 7. B1: the ten hooks are defined TEXT symbols ==="
# nm exits non-zero merely because some stock member carries no symbols, so the
# OUTPUT decides, not the exit code -- an exit code here would fail a good build
nm "$OUT/libGL_radeon.a" > "$OUT/nm-archive.txt" 2>&1
if [ ! -s "$OUT/nm-archive.txt" ]; then fail "nm produced nothing for the archive"; fi
miss=
for h in UpdateState Buffer DepthBuffer ReleaseBuffer BoundTo AppBuffer \
         CopyDepth Mirror Stride ClearPixel; do
    n=`grep -c "^[0-9a-f]* T _OpenStepMesaAccel$h\$" "$OUT/nm-archive.txt"`
    if [ "$n" = "0" ]; then miss="$miss $h"; fi
done
[ -z "$miss" ] || fail "not defined as text symbols:$miss"
echo "  all ten present"

echo "=== 8. B2: no two members collide at 15 characters ==="
ar t "$OUT/libGL_radeon.a" > "$OUT/members.txt" 2>&1
if [ ! -s "$OUT/members.txt" ]; then fail "ar t listed nothing"; fi
# no cut(1) on this system -- awk does the truncation
dup=`awk '{print substr($0,1,15)}' "$OUT/members.txt" | sort | uniq -d`
[ -z "$dup" ] || fail "members collide at 15 characters: $dup"
echo "  `wc -l < "$OUT/members.txt"` members, none colliding"

echo "=== 9. B3: what our object may leave undefined ==="
nm -u "$TMP/osrdnaccel.o" > "$OUT/nm-undef.txt" 2>&1
if [ ! -s "$OUT/nm-undef.txt" ]; then echo "  (no undefined symbols at all)"; fi
cat "$OUT/nm-undef.txt"
echo "  (the host judges this against the allow-list)"

echo "=== 10. G: the finished archive links through its index ==="
cat > "$TMP/link.c" <<'EOF'
extern int OSMesaCreateContext();
extern void OpenStepMesaAccelMirror();
int main() { OSMesaCreateContext(); OpenStepMesaAccelMirror(); return 0; }
EOF
$CC -o "$TMP/link" "$TMP/link.c" "$OUT/libGL_radeon.a" -lm > "$TMP/link.log" 2>&1
rc=$?
cat "$TMP/link.log"
[ $rc = 0 ] || fail "the archive does not link through its index (rc=$rc)"
echo "  links"

echo "=== 11. the render test, linked BOTH ways (gate C) ==="
# One source, two links.  The stock one must have no idea the hooks exist, so it
# is compiled without RDN_ACCEL and against the installed libGL; the accelerated
# one gets the macro and our archive.  Nothing else differs between them.
HDRS=/LocalDeveloper/Headers
$CC -O -Wall -I"$HDRS" -o "$OUT/rdnrender-stock" "$PROJ/test/osrdn-mesa-render.c" \
    -L/LocalDeveloper/Libraries -lGL -lm > "$TMP/cc-rstock.log" 2>&1
rc=$?
cat "$TMP/cc-rstock.log"
[ $rc = 0 ] || fail "cc the stock render test exited $rc"
$CC -O -Wall -DRDN_ACCEL -I"$HDRS" -I"$PROJ/mesa" -o "$OUT/rdnrender-accel" \
    "$PROJ/test/osrdn-mesa-render.c" "$OUT/libGL_radeon.a" -lm > "$TMP/cc-raccel.log" 2>&1
rc=$?
cat "$TMP/cc-raccel.log"
[ $rc = 0 ] || fail "cc the accelerated render test exited $rc"
# M1c: the eight-step approval run, and the same steps against stock libGL so
# the pixels have something to be compared with.
$CC -O -Wall -DRDN_ACCEL -I"$HDRS" -I"$PROJ/mesa" -o "$OUT/rdnsurface-accel" \
    "$PROJ/test/osrdn-mesa-surface.c" "$OUT/libGL_radeon.a" -lm > "$TMP/cc-saccel.log" 2>&1
rc=$?
cat "$TMP/cc-saccel.log"
[ $rc = 0 ] || fail "cc the accelerated surface test exited $rc"
# the stock one needs the same source; the counter calls are behind RDN_ACCEL,
# and a stub file supplies the two printers so the steps still print
$CC -O -Wall -I"$HDRS" -I"$PROJ/mesa" -o "$OUT/rdnsurface-stock" \
    "$PROJ/test/osrdn-mesa-surface.c" "$PROJ/test/osrdn-mesa-nocount.c" \
    -L/LocalDeveloper/Libraries -lGL -lm > "$TMP/cc-sstock.log" 2>&1
rc=$?
cat "$TMP/cc-sstock.log"
[ $rc = 0 ] || fail "cc the stock surface test exited $rc"
# M1d: the four-state approval run, both ways, for the same reason
$CC -O -Wall -DRDN_ACCEL -I"$HDRS" -I"$PROJ/mesa" -o "$OUT/rdntri-accel" \
    "$PROJ/test/osrdn-mesa-tri.c" "$OUT/libGL_radeon.a" -lm > "$TMP/cc-taccel.log" 2>&1
rc=$?
cat "$TMP/cc-taccel.log"
[ $rc = 0 ] || fail "cc the accelerated triangle test exited $rc"
$CC -O -Wall -I"$HDRS" -I"$PROJ/mesa" -o "$OUT/rdntri-stock" \
    "$PROJ/test/osrdn-mesa-tri.c" "$PROJ/test/osrdn-mesa-nocount.c" \
    -L/LocalDeveloper/Libraries -lGL -lm > "$TMP/cc-tstock.log" 2>&1
rc=$?
cat "$TMP/cc-tstock.log"
[ $rc = 0 ] || fail "cc the stock triangle test exited $rc"
echo "  all six linked (render, surface and triangle, each way)"

echo "=== 12. material for the host's F gate ==="
cp "$TMP/osmesa-stock.o" "$OUT/osmesa-stock.o" || fail "cannot copy the stock-flags object"
cp "$TMP/osmesa.o" "$OUT/osmesa-hooked.o" || fail "cannot copy the hooked object"
cp "$STOCK" "$OUT/libGL-stock.a" || fail "cannot copy the stock archive for comparison"
nm "$OUT/osmesa-stock.o" > "$OUT/nm-osmesa-stock.txt" 2>&1
ar t "$OUT/libGL-stock.a" > "$OUT/members-stock.txt" 2>&1
# F3 needs the INSTALLED archive's own osmesa.o to compare against, so extract
# it here: the host has no nm for this architecture, and a provenance gate that
# cannot read the thing it is about is not a gate.
# into a directory of its own: $TMP/osmesa.o is OUR hooked object and ar x
# would silently replace it with the stock one
mkdir "$TMP/x" || fail "cannot make $TMP/x"
( cd "$TMP/x" && ar x "$STOCK" osmesa.o ) > "$TMP/arx.log" 2>&1
if [ -f "$TMP/x/osmesa.o" ]; then
    nm "$TMP/x/osmesa.o" > "$OUT/nm-osmesa-installed.txt" 2>&1
    echo "  extracted the installed osmesa.o for the provenance gate"
else
    echo "  (could not extract osmesa.o from the installed archive)"
fi
sync

echo "RDNMESA PASS runid=$RUNID out=$OUT"
