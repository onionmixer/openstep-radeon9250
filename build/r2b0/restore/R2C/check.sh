#!/bin/sh
# check.sh -- read-only: is the restore set whole, and how do the live
# instance tables differ from it?
#
# docs/R2B0_IMPL_PLAN.md section 7-2.  Published beside restore.sh; run as
#   sh /me/rdn-r2b0/check.sh
# Exit 0: the set matches its manifest (the line CHECK SET OK says how many
# live tables differ and how many are extra -- a difference is expected on
# the activation boot, none right after staging).  Exit 2: the set is not
# whole; restore.sh would refuse it too.  Writes nothing.
#
# Target shell rules as restore.sh.  R2B0_* overrides are for
# tools/r2b0/check_target_r2b0.py only.

ME=${R2B0_ME:-/me/rdn-r2b0}
DRV=${R2B0_DRV:-/private/Drivers/i386}
SUM=${R2B0_SUM:-/usr/bin/sum}
LS=${R2B0_LS:-/bin/ls}

fail() {
    why="$1"
    echo "CHECK FAIL $why"
    exit 2
}

field() {
    frel="$1"
    fn="$2"
    awk '$1 == "'"$frel"'" { print $'"$fn"' }' $MAN
}

TAG=`cat $ME/CURRENT`
case "$TAG" in
    ""|*[!A-Za-z0-9-]*) fail "CURRENT holds no tag: '$TAG'" ;;
esac
SET=$ME/set.$TAG
MAN=$SET/manifest
if [ ! -f $MAN ]; then fail "no manifest $MAN"; fi

RELS=`awk '{ print $1 }' $MAN`
count=0
differ=0
for rel in $RELS; do
    case "$rel" in
        *..*|/*|*[!A-Za-z0-9._/-]*) fail "manifest path: $rel" ;;
        *.config/Instance[0-9].table|*.config/Instance[0-9][0-9].table) ;;
        *) fail "manifest path is not an instance table: $rel" ;;
    esac
    nf=`awk '$1 == "'"$rel"'" { print NF }' $MAN`
    if [ "$nf" != "8" ]; then fail "manifest line for $rel has $nf fields" ; fi
    if [ ! -f $SET/$rel ]; then fail "set has no $rel"; fi
    want="`field $rel 6` `field $rel 7`"
    got=`$SUM $SET/$rel | awk '{ print $1, $2 }'`
    if [ "$got" != "$want" ]; then fail "set copy of $rel sums $got, manifest $want"; fi
    count=`expr $count + 1`
    dst=$DRV/$rel
    if [ ! -f $dst ]; then
        echo "  MISSING $rel"
        differ=`expr $differ + 1`
    elif cmp -s $SET/$rel $dst; then
        wantp="`field $rel 3` `field $rel 4` `field $rel 5`"
        gotp=`$LS -lg $dst | awk '{ print $1, $3, $4 }'`
        if [ "$gotp" = "$wantp" ]; then
            echo "  same    $rel"
        else
            echo "  PERMS   $rel: $gotp, set $wantp"
            differ=`expr $differ + 1`
        fi
    else
        echo "  DIFFERS $rel"
        differ=`expr $differ + 1`
    fi
done
if [ "$count" = "0" ]; then fail "manifest is empty"; fi
extra=0
for t in $DRV/*.config/Instance*.table; do
    if [ ! -f $t ]; then continue; fi
    rel=`echo $t | sed "s,^$DRV/,,"`
    n=`awk '$1 == "'"$rel"'"' $MAN | wc -l | sed 's/ //g'`
    if [ "$n" = "0" ]; then
        echo "  EXTRA   $rel"
        extra=`expr $extra + 1`
    fi
done
echo "CHECK SET OK set=$TAG tables=$count differ=$differ extra=$extra"
exit 0
