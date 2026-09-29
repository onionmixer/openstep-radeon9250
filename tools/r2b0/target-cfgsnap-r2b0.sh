#!/bin/sh
# target-cfgsnap-r2b0.sh -- copy every instance table to NFS, with its
# owner, mode and sum, for tools/r2b0/check_cfgdiff.py on the host.
#
#   sh target-cfgsnap-r2b0.sh <pre|postraw|post|post2|post3|postb> <tag> closed=yes
#
# docs/R2B0_IMPL_PLAN.md section 7-1.  Writes only under
# <nfs>/cfg/<tag>/<mode>/, which must not exist yet:
#   <bundle>.config/InstanceN.table   a copy of each table
#   System.config/Default.table       and the config=Default fallback table
#   LIST     one line per copy: <rel> <ls mode> <owner> <group> <sum> <blocks> <bytes>
#            (built in /tmp and copied once: a line-by-line append onto NFS is
#            the pattern this project measured to keep only the last record,
#            memory "OPENSTEP NFS append trap")
#   SNAP     the operator's statement (closed=yes: Configure.app is closed),
#            the date, and "tables=<n>" -- written last
# closed=yes is what the operator said; it is recorded, not checked (ps is
# not used on the target).  Without it nothing is written.
#
# Target shell rules: ASCII, no printf, cut, $(...), grep -q, mkdir -p,
# test -e, dirname, ps, set --; arguments read before any function.
# R2B0_* overrides are for tools/r2b0/check_target_r2b0.py only.

MODE="$1"
TAG="$2"
CLOSED="$3"

DRV=${R2B0_DRV:-/private/Drivers/i386}
SUM=${R2B0_SUM:-/usr/bin/sum}
LS=${R2B0_LS:-/bin/ls}
NFSOUT=${R2B0_NFSOUT:-/ndrv/openstep-radeon9250/build/r2b0}
TMP=${R2B0_TMP:-/tmp}
TMPLIST=$TMP/rdn-r2b0-cfgsnap.list

fail() {
    why="$1"
    echo "CFGSNAP FAIL $why"
    exit 1
}

case "$MODE" in
    pre|postraw|post|post2|post3|postb) ;;
    *) echo "usage: sh target-cfgsnap-r2b0.sh <pre|postraw|post|post2|post3|postb> <tag> closed=yes"; exit 2 ;;
esac
case "$TAG" in
    ""|*[!A-Za-z0-9-]*) fail "tag must be letters, digits and '-': '$TAG'" ;;
esac
if [ "$CLOSED" != "closed=yes" ]; then fail "the operator has not said Configure.app is closed (closed=yes)"; fi
if [ ! -d $NFSOUT ]; then fail "no NFS directory $NFSOUT"; fi
if [ ! -d $DRV/System.config ]; then fail "no $DRV/System.config"; fi

if [ ! -d $NFSOUT/cfg ]; then mkdir $NFSOUT/cfg || fail "mkdir $NFSOUT/cfg"; fi
if [ ! -d $NFSOUT/cfg/$TAG ]; then mkdir $NFSOUT/cfg/$TAG || fail "mkdir $NFSOUT/cfg/$TAG"; fi
DEST=$NFSOUT/cfg/$TAG/$MODE
if [ -d $DEST ]; then fail "$DEST exists: a snapshot is never overwritten"; fi
mkdir $DEST || fail "mkdir $DEST"
rm -f $TMPLIST

n=0
for t in $DRV/*.config/Instance*.table $DRV/System.config/Default.table; do
    if [ ! -f $t ]; then continue; fi
    rel=`echo $t | sed "s,^$DRV/,,"`
    case "$rel" in
        *[!A-Za-z0-9._/-]*) fail "odd character in $rel" ;;
    esac
    dir=`echo $rel | sed 's,/[^/]*$,,'`
    if [ ! -d $DEST/$dir ]; then mkdir $DEST/$dir || fail "mkdir $DEST/$dir"; fi
    # `cat >' and not `cp': cp gives the copy the source's mode, and an
    # installed table is 444 -- on NFS, where root is squashed to an ordinary
    # user, the write into that fresh 444 file is refused (measured on this
    # machine, 2026-09-16).  The mode that matters is recorded from the
    # SOURCE below.
    cat $t > $DEST/$rel || fail "copy $rel"
    cmp -s $t $DEST/$rel || fail "the NFS copy of $rel differs"
    lsl=`$LS -lg $t | awk '{ print $1, $3, $4 }'`
    s=`$SUM $t | awk '{ print $1, $2 }'`
    bytes=`wc -c < $t | sed 's/ //g'`
    echo "$rel $lsl $s $bytes" >> $TMPLIST
    n=`expr $n + 1`
done
if [ "$n" = "0" ]; then fail "no table found under $DRV"; fi
cp $TMPLIST $DEST/LIST || fail "cannot copy the list to $DEST"
sync
if cmp -s $TMPLIST $DEST/LIST; then :; else fail "the LIST copy on NFS differs"; fi
echo "operator=closed=yes date=`date` tables=$n" > $DEST/SNAP
sync
echo "CFGSNAP DONE $MODE $TAG tables=$n"
echo "host: python3 tools/r2b0/check_cfgdiff.py <mode> build/r2b0/cfg/$TAG/..."
exit 0
