#!/bin/sh
# target-stage-restore-r2b0.sh -- copy a restore set from NFS to /me and
# make it the current one.
#
#   sh target-stage-restore-r2b0.sh <tag>
#
# docs/R2B0_IMPL_PLAN.md section 7-2.  Source: <nfs>/restore/<tag>/ as
# tools/r2b0/pack_restore_r2b0.py wrote it.  Destination /me/rdn-r2b0:
#   set.<tag>/   manifest and the tables (must not exist yet)
#   restore.sh, check.sh   replaced only through a side file whose sum equals
#                SUMS, then renamed
#   CURRENT      the tag, written last through a side file and a rename
# Every copy's sum is compared with SUMS or the manifest before CURRENT
# moves; /me/rdn-r2b0 is made root-owned and not group/other-writable
# (/me itself is world-writable).  Nothing under /private/Drivers is touched.
#
# Target shell rules: ASCII, no printf, cut, $(...), grep -q, mkdir -p,
# test -e, dirname, ps, set --; arguments read before any function; no
# while-read loop.  R2B0_* overrides are for tools/r2b0/check_target_r2b0.py.

TAG="$1"

ME=${R2B0_ME:-/me/rdn-r2b0}
SUM=${R2B0_SUM:-/usr/bin/sum}
NFSOUT=${R2B0_NFSOUT:-/ndrv/openstep-radeon9250/build/r2b0}

fail() {
    why="$1"
    echo "STAGE FAIL $why"
    exit 1
}

sumof() {
    sf="$1"
    $SUM $sf | awk '{ print $1, $2 }'
}

case "$TAG" in
    ""|*[!A-Za-z0-9-]*) echo "usage: sh target-stage-restore-r2b0.sh <tag>"; exit 2 ;;
esac
SRC=$NFSOUT/restore/$TAG
if [ ! -f $SRC/SUMS ] || [ ! -f $SRC/manifest ]; then fail "no restore set at $SRC"; fi

echo "=== 1. the NFS set against SUMS and its manifest ==="
for name in manifest restore.sh check.sh; do
    want=`awk '$1 == "'"$name"'" { print $2, $3 }' $SRC/SUMS`
    got=`sumof $SRC/$name`
    if [ "$want" = "" ] || [ "$got" != "$want" ]; then fail "$SRC/$name sums '$got', SUMS says '$want'"; fi
done
RELS=`awk '{ print $1 }' $SRC/manifest`
count=0
for rel in $RELS; do
    case "$rel" in
        *..*|/*|*[!A-Za-z0-9._/-]*) fail "manifest path: $rel" ;;
        *.config/Instance[0-9].table|*.config/Instance[0-9][0-9].table) ;;
        *) fail "manifest path is not an instance table: $rel" ;;
    esac
    want=`awk '$1 == "'"$rel"'" { print $6, $7 }' $SRC/manifest`
    got=`sumof $SRC/set/$rel`
    if [ "$got" != "$want" ]; then fail "$SRC/set/$rel sums '$got', manifest '$want'"; fi
    count=`expr $count + 1`
done
if [ "$count" = "0" ]; then fail "the manifest is empty"; fi
echo "  $count tables"

echo "=== 2. copy to $ME ==="
if [ ! -d $ME ]; then mkdir $ME || fail "mkdir $ME"; fi
chown root $ME || fail "chown $ME"
chmod 755 $ME || fail "chmod $ME"
DEST=$ME/set.$TAG
if [ -d $DEST ]; then fail "$DEST exists: a staged set is never overwritten"; fi
mkdir $DEST || fail "mkdir $DEST"
cp $SRC/manifest $DEST/manifest || fail "cp manifest"
for rel in $RELS; do
    dir=`echo $rel | sed 's,/[^/]*$,,'`
    if [ ! -d $DEST/$dir ]; then mkdir $DEST/$dir || fail "mkdir $DEST/$dir"; fi
    cp $SRC/set/$rel $DEST/$rel || fail "cp $rel"
done
for name in restore.sh check.sh; do
    rm -f $ME/$name.new
    cp $SRC/$name $ME/$name.new || fail "cp $name"
done
sync

echo "=== 3. the copies ==="
if [ "`sumof $DEST/manifest`" != "`sumof $SRC/manifest`" ]; then fail "the staged manifest differs"; fi
for rel in $RELS; do
    want=`awk '$1 == "'"$rel"'" { print $6, $7 }' $DEST/manifest`
    got=`sumof $DEST/$rel`
    if [ "$got" != "$want" ]; then fail "staged $rel sums '$got', manifest '$want'"; fi
done
for name in restore.sh check.sh; do
    want=`awk '$1 == "'"$name"'" { print $2, $3 }' $SRC/SUMS`
    got=`sumof $ME/$name.new`
    if [ "$got" != "$want" ]; then fail "staged $name sums '$got', SUMS '$want'"; fi
done
for name in restore.sh check.sh; do
    mv $ME/$name.new $ME/$name || fail "rename $name"
done
echo "$TAG" > $ME/CURRENT.new || fail "write CURRENT.new"
mv $ME/CURRENT.new $ME/CURRENT || fail "rename CURRENT"
sync
if [ "`cat $ME/CURRENT`" != "$TAG" ]; then fail "CURRENT does not read back $TAG"; fi
echo "STAGE DONE $TAG tables=$count"
echo "now: sh $ME/check.sh"
exit 0
