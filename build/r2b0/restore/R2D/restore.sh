#!/bin/sh
# restore.sh -- put the instance tables back as the "pre" snapshot had them.
#
# docs/R2B0_IMPL_PLAN.md section 7-2.  Published once by the host
# (tools/r2b0/pack_restore_r2b0.py, staged by target-stage-restore-r2b0.sh)
# to /me/rdn-r2b0/restore.sh; run as root with no argument, over telnet or
# from the config=Default console:
#
#   sh /me/rdn-r2b0/restore.sh
#
# It reads the tag in /me/rdn-r2b0/CURRENT and the set /me/rdn-r2b0/set.<tag>:
# a copy of every <bundle>.config/Instance*.table the snapshot held, and a
# manifest whose lines are
#   <bundle>.config/InstanceN.table <octal mode> <ls mode> <owner> <group> <sum> <blocks> <bytes>
#
#   1. every set file's sum must equal its manifest line; any difference and
#      NOTHING is written (exit 2)
#   2. each manifest table: equal bytes are left alone (owner and mode put
#      right if they differ); otherwise a side file InstanceN.table.rdnnew is
#      written in the same directory, given the manifest's owner and mode,
#      compared, and renamed over the table.  Every table but System's is done
#      first and synced; System.config/Instance0.table (the one that names the
#      display driver in Active Drivers) is written LAST, so a power cut can
#      never leave Active Drivers back on VGA while the VGA instance table is
#      still missing
#   3. an OSRDNDisplay instance table the manifest does not name (the one
#      Configure made) is moved to /me/rdn-r2b0/parked.<tag>/<bundle>.config/.
#      An unexpected instance table of ANY OTHER driver is NOT moved: it is
#      reported and the script stops (exit 3), because a driver in Active
#      Drivers -- Pro1000 carries telnet -- must not lose its table here
#   4. verify: every manifest table equal in bytes, owner, group and mode to
#      the manifest, no table outside it; then sync.  Any difference: exit 3,
#      and do not reboot.
# No NFS.  Output goes to the screen and to /me/rdn-r2b0/restore.log.
#
# Target shell rules: ASCII, no printf, cut, $(...), grep -q, mkdir -p,
# test -e, dirname, ps, set --; no positional parameter after a function;
# no while-read loop (a redirected loop runs in a subshell there, where exit
# does not stop the script).  R2B0_* overrides exist only for
# tools/r2b0/check_target_r2b0.py.

ME=${R2B0_ME:-/me/rdn-r2b0}
DRV=${R2B0_DRV:-/private/Drivers/i386}
SUM=${R2B0_SUM:-/usr/bin/sum}
LS=${R2B0_LS:-/bin/ls}
LOG=$ME/restore.log

say() {
    msg="$1"
    echo "$msg"
    echo "$msg" >> $LOG
}

fail() {
    why="$1"
    code="$2"
    say "RESTORE FAIL $why"
    exit $code
}

field() {
    frel="$1"
    fn="$2"
    awk '$1 == "'"$frel"'" { print $'"$fn"' }' $MAN
}

echo "RESTORE begin `date`" >> $LOG

TAG=`cat $ME/CURRENT`
case "$TAG" in
    ""|*[!A-Za-z0-9-]*) fail "CURRENT holds no tag: '$TAG'" 2 ;;
esac
SET=$ME/set.$TAG
MAN=$SET/manifest
if [ ! -f $MAN ]; then fail "no manifest $MAN" 2; fi
say "restore set $TAG"

echo "=== 1. the set against its manifest ==="
RELS=`awk '{ print $1 }' $MAN`
count=0
sysseen=0
for rel in $RELS; do
    case "$rel" in
        *..*|/*) fail "manifest path not relative: $rel" 2 ;;
        *[!A-Za-z0-9._/-]*) fail "manifest path has an odd character: $rel" 2 ;;
        *.config/Instance[0-9].table|*.config/Instance[0-9][0-9].table) ;;
        *) fail "manifest path is not an instance table: $rel" 2 ;;
    esac
    if [ "$rel" = "System.config/Instance0.table" ]; then sysseen=1; fi
    n=`awk '$1 == "'"$rel"'"' $MAN | wc -l | sed 's/ //g'`
    if [ "$n" != "1" ]; then fail "manifest names $rel $n times" 2; fi
    nf=`awk '$1 == "'"$rel"'" { print NF }' $MAN`
    if [ "$nf" != "8" ]; then fail "manifest line for $rel has $nf fields, want 8" 2; fi
    if [ ! -f $SET/$rel ]; then fail "set has no $rel" 2; fi
    want="`field $rel 6` `field $rel 7`"
    got=`$SUM $SET/$rel | awk '{ print $1, $2 }'`
    if [ "$got" != "$want" ]; then fail "set copy of $rel sums $got, manifest $want" 2; fi
    count=`expr $count + 1`
done
if [ "$count" = "0" ]; then fail "manifest is empty" 2; fi
if [ "$sysseen" != "1" ]; then fail "manifest does not hold System.config/Instance0.table" 2; fi
say "  $count tables, every copy matches its manifest line"

echo "=== 2. tables (System last) ==="
wrote=0
for phase in others system; do
for rel in $RELS; do
    if [ "$phase" = "others" ] && [ "$rel" = "System.config/Instance0.table" ]; then continue; fi
    if [ "$phase" = "system" ] && [ "$rel" != "System.config/Instance0.table" ]; then continue; fi
    dst=$DRV/$rel
    dir=`echo $rel | sed 's,/[^/]*$,,'`
    mode=`field $rel 2`
    owner=`field $rel 4`
    group=`field $rel 5`
    if [ ! -d $DRV/$dir ]; then fail "no bundle directory $DRV/$dir: not creating one" 4; fi
    same=0
    if [ -f $dst ]; then
        if cmp -s $SET/$rel $dst; then same=1; fi
    fi
    if [ "$same" = "1" ]; then
        chown $owner.$group $dst || fail "chown $dst" 4
        chmod $mode $dst || fail "chmod $dst" 4
        say "  same  $rel"
    else
        rm -f $dst.rdnnew
        cp $SET/$rel $dst.rdnnew || fail "cp to $dst.rdnnew" 4
        chown $owner.$group $dst.rdnnew || fail "chown $dst.rdnnew" 4
        chmod $mode $dst.rdnnew || fail "chmod $dst.rdnnew" 4
        cmp -s $SET/$rel $dst.rdnnew || fail "$dst.rdnnew differs from the set copy" 4
        mv $dst.rdnnew $dst || fail "rename $dst.rdnnew" 4
        wrote=`expr $wrote + 1`
        say "  wrote $rel"
    fi
done
sync
done

echo "=== 3. tables the snapshot did not have ==="
parked=0
strangers=0
for t in $DRV/*.config/Instance*.table; do
    if [ ! -f $t ]; then continue; fi
    rel=`echo $t | sed "s,^$DRV/,,"`
    n=`awk '$1 == "'"$rel"'"' $MAN | wc -l | sed 's/ //g'`
    if [ "$n" = "0" ]; then
        case "$rel" in
            OSRDNDisplay.config/*) ;;
            *) say "  STRANGER $rel (left in place: only an OSRDNDisplay table is parked)"
               strangers=`expr $strangers + 1`
               continue ;;
        esac
        dir=`echo $rel | sed 's,/[^/]*$,,'`
        if [ ! -d $ME/parked.$TAG ]; then mkdir $ME/parked.$TAG || fail "mkdir $ME/parked.$TAG" 4; fi
        if [ ! -d $ME/parked.$TAG/$dir ]; then mkdir $ME/parked.$TAG/$dir || fail "mkdir parked $dir" 4; fi
        mv $t $ME/parked.$TAG/$dir/ || fail "cannot park $rel" 4
        parked=`expr $parked + 1`
        say "  parked $rel"
    fi
done

if [ "$strangers" != "0" ]; then
    fail "$strangers instance table(s) nobody expected: they were NOT moved; look before rebooting" 3
fi

echo "=== 4. verify ==="
bad=0
for rel in $RELS; do
    dst=$DRV/$rel
    if cmp -s $SET/$rel $dst; then :; else
        say "  DIFFERS $rel"
        bad=`expr $bad + 1`
    fi
    want="`field $rel 3` `field $rel 4` `field $rel 5`"
    got=`$LS -lg $dst | awk '{ print $1, $3, $4 }'`
    if [ "$got" != "$want" ]; then
        say "  PERMISSIONS $rel: $got, manifest $want"
        bad=`expr $bad + 1`
    fi
done
for t in $DRV/*.config/Instance*.table; do
    if [ ! -f $t ]; then continue; fi
    rel=`echo $t | sed "s,^$DRV/,,"`
    n=`awk '$1 == "'"$rel"'"' $MAN | wc -l | sed 's/ //g'`
    if [ "$n" = "0" ]; then
        say "  EXTRA $rel"
        bad=`expr $bad + 1`
    fi
done
sync
if [ "$bad" != "0" ]; then fail "$bad difference(s) after the restore: do not reboot" 3; fi
say "RESTORE DONE set=$TAG tables=$count wrote=$wrote parked=$parked"
exit 0
