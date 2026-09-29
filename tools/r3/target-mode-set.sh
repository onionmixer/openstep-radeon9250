#!/bin/sh
# target-mode-set.sh -- set OSRDNDisplay's "Display Mode" for a test boot,
# over telnet, without Configure.app.
#
#   sh target-mode-set.sh closed=yes <code>
#
# <code> is one of the combinations R3b-2b boots (docs/R3_MULTIMODE_PLAN.md
# 24-7, 24-9 Q5): the string written is fixed per code below and
# tools/r3/check_target_r3.py holds each to the oracle's twenty.  Everything
# else is target-mode-reset.sh's (23-7, 23-9 X1-X4).  closed=yes is the operator
# saying Configure.app is closed (it rewrites instance tables); it is not
# checked.  Refuses, changing nothing, when:
#   - there is any Instance table other than Instance0 (driverLoader would
#     still configure the others, so resetting one table proves nothing);
#   - Instance0.table does not hold exactly one "Display Mode" line (the
#     kernel reads the first value and user space the last);
#   - the edited copy is not the original with that one line replaced.
# The table is rewritten with cp onto the existing file, so its inode, owner
# and mode stay; the old one is kept under $SAVE first.
#
# Target shell rules: ASCII, no printf, cut, $(...), grep -q, mkdir -p,
# test -e; arguments read before any function.  R3_* overrides are for
# tools/r3/check_target_r3.py only.

CLOSED="$1"
CODE="$2"

DRV=${R3_DRV:-/private/Drivers/i386}
SAVE=${R3_SAVE:-/me/rdn-mode-reset}
TMP=${R3_TMP:-/tmp}
DIR=$DRV/OSRDNDisplay.config
TABLE=$DIR/Instance0.table
NEWT=$TMP/rdn-mode-set.table
MODE=""
case "$CODE" in
    800x600-888)   MODE='Height: 600 Width: 800 Refresh: 60Hz ColorSpace: RGB:888/32' ;;
    800x600-555)   MODE='Height: 600 Width: 800 Refresh: 60Hz ColorSpace: RGB:555/16' ;;
    800x600-256)   MODE='Height: 600 Width: 800 Refresh: 60Hz ColorSpace: RGB:256/8' ;;
    800x600-bw)    MODE='Height: 600 Width: 800 Refresh: 60Hz ColorSpace: BW:8' ;;
    640x480-888)   MODE='Height: 480 Width: 640 Refresh: 60Hz ColorSpace: RGB:888/32' ;;
    1024x768-888)  MODE='Height: 768 Width: 1024 Refresh: 60Hz ColorSpace: RGB:888/32' ;;
    1280x1024-888) MODE='Height: 1024 Width: 1280 Refresh: 60Hz ColorSpace: RGB:888/32' ;;
    1600x1200-888) MODE='Height: 1200 Width: 1600 Refresh: 60Hz ColorSpace: RGB:888/32' ;;
esac
WANT="\"Display Mode\" = \"$MODE\";"

fail() {
    echo "MODESET FAIL $1 (nothing was changed)"
    exit 1
}

if [ "$CLOSED" != "closed=yes" ] || [ "$MODE" = "" ]; then
    echo "usage: sh target-mode-set.sh closed=yes <code>   (Configure.app must be closed)"
    echo "  codes: 800x600-888 800x600-555 800x600-256 800x600-bw 640x480-888"
    echo "         1024x768-888 1280x1024-888 1600x1200-888"
    exit 2
fi
if [ ! -f $TABLE ]; then fail "no $TABLE"; fi

others=0
for f in $DIR/Instance*.table; do
    if [ "$f" != "$TABLE" ] && [ -f "$f" ]; then
        echo "  found $f"
        others=1
    fi
done
if [ "$others" != "0" ]; then fail "an instance table other than Instance0 exists; a person has to look"; fi

n=`grep -c '^"Display Mode" = ' $TABLE`
echo "  Instance0.table: $n Display Mode line(s)"
if [ "$n" != "1" ]; then fail "Instance0.table must hold exactly one Display Mode line"; fi
grep '^"Display Mode" = ' $TABLE

sed "s|^\"Display Mode\" = .*\$|$WANT|" $TABLE > $NEWT
a=`wc -l < $TABLE`
b=`wc -l < $NEWT`
if [ "$a" != "$b" ]; then fail "the edited copy has $b lines, the table $a"; fi
n=`grep -c "^$WANT\$" $NEWT`
if [ "$n" != "1" ]; then fail "the edited copy does not hold the new line exactly once"; fi
grep -v '^"Display Mode" = ' $TABLE > $NEWT.rest.old
grep -v '^"Display Mode" = ' $NEWT > $NEWT.rest.new
if cmp -s $NEWT.rest.old $NEWT.rest.new; then
    echo "  the edited copy differs only in the Display Mode line"
else
    fail "the edited copy differs outside the Display Mode line"
fi

if [ ! -d $SAVE ]; then mkdir $SAVE || fail "mkdir $SAVE"; fi
k=0
while [ -f $SAVE/Instance0.table.$k ]; do
    k=`expr $k + 1`
done
cp $TABLE $SAVE/Instance0.table.$k || fail "cannot save the old table"
echo "  saved the old table as $SAVE/Instance0.table.$k"

cp $NEWT $TABLE || fail "cp onto the table failed"
n=`grep -c "^$WANT\$" $TABLE`
if [ "$n" != "1" ]; then
    echo "MODESET FAIL the table did not take the new line; the old one is $SAVE/Instance0.table.$k"
    exit 1
fi
ls -l $TABLE
echo "MODESET DONE $WANT"
echo "  reboot to use it"
