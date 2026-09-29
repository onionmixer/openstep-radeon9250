#!/bin/sh
# target-r1c.sh -- R1c on the OPENSTEP target: facts, then two BIOS shadow reads.
#
#   nohup sh target-r1c.sh facts <runid> > /tmp/rdn-r1c-<runid>-facts.out 2>&1 &
#   nohup sh target-r1c.sh read <runid> <length> <sum> <blocks> > /tmp/rdn-r1c-<runid>-<length>.out 2>&1 &
#
# Plan: docs/R1C_R2A_IMPL_PLAN.md section 1-4.  Run as root from gcds, in the
# background: completion is the file /tmp/rdn-r1c-<runid>-<step>.done (R1
# result 1-6: a gcds command returned minutes after its script ended).
#
# Before either step the HOST confirms nxlogd with tools/nx-logcatch.sh status.
# This script does not run ps: on this target `ps ax' started from a detached
# background job never returned (2026-09-15, R1c facts run 789463413, traced
# with sh -x), so the check lives on the host, where it runs over telnet.
#
# facts  (no device access): memory device node, readability, logger and cc
#        paths, Active Drivers.  Copied to the NFS build directory.
# read   1. <runid> decimal, <length> a multiple of 512 from 512 to 65536
#        2. the BSD sum of rdnbios.c equals <sum> <blocks> (the host's)
#        3. /dev/mem readable, Active Drivers names VGA and no Matrox driver
#        4. claim /me/rdn-r1c-ran.d/<runid>-<length> with mkdir (creating the
#           parent first), then sync -- before anything touches the device
#        5. cc -O builds rdnbios in /tmp (fixed command, exit status checked)
#        6. a syslog marker if logger exists, sync, run rdnbios, a second marker
#        7. the capture is exactly <length> bytes; its sum; one cp to the NFS
#           build directory; the copy's sum must equal the original's
# Every outcome writes "R1CREAD DONE ..." or "R1CREAD FAIL ..." to the .done
# file and the log, and copies the log.
#
# ASCII only; no printf, cut, $(...), grep -q, mkdir -p, test -e, dirname, ps;
# no blank inside an unquoted ${NAME:-default} (the target sh says "bad
# substitution" and leaves the variable empty -- measured with a probe script).

TMP=${R1C_TMP:-/tmp}
SRC=${R1C_SRC:-/ndrv/openstep-radeon9250/tools/r1c/rdnbios.c}
OUT=${R1C_OUT:-/ndrv/openstep-radeon9250/build/r1c}
RANDIR=${R1C_RANDIR:-/me/rdn-r1c-ran.d}
SUM=${R1C_SUM:-/usr/bin/sum}
CC=${R1C_CC:-cc}
SYSCFG=${R1C_SYSCFG:-/private/Devices/System.config/Instance0.table}
MEMDEV=${R1C_MEMDEV:-/dev/mem}
LOGGER1=${R1C_LOGGER1:-/usr/ucb/logger}
LOGGER2=${R1C_LOGGER2:-/usr/bin/logger}
LOGGER3=${R1C_LOGGER3:-/bin/logger}

STEP="$1"
RUNID="$2"

case "$RUNID" in
    ""|*[!0-9]*) echo "usage: sh target-r1c.sh facts <runid> | read <runid> <length> <sum> <blocks>"; exit 2 ;;
esac

if [ "$STEP" = "facts" ]; then
    TAG=facts
elif [ "$STEP" = "read" ]; then
    TAG="$3"
else
    echo "usage: sh target-r1c.sh facts <runid> | read <runid> <length> <sum> <blocks>"
    exit 2
fi
case "$TAG" in
    ""|*[!0-9a-z]*) echo "usage: sh target-r1c.sh read <runid> <length> <sum> <blocks>"; exit 2 ;;
esac

LOG=$TMP/rdn-r1c-$RUNID-$TAG.log
DONE=$TMP/rdn-r1c-$RUNID-$TAG.done
rm -f $DONE
echo "R1C $STEP runid=$RUNID tag=$TAG" > $LOG

say() {
    echo "$1"
    echo "$1" >> $LOG
}

copylog() {
    if [ -d $OUT ]; then
        cp $LOG $OUT/rdn-r1c-$RUNID-$TAG.log
    fi
}

finish() {
    verdict="$1"
    say "$verdict"
    echo "$verdict" > $DONE
    copylog
    sync
    case "$verdict" in
        *" DONE"*) exit 0 ;;
    esac
    exit 1
}

if [ "$STEP" = "facts" ]; then
    say "=== facts ==="
    ls -l $MEMDEV >> $LOG 2>&1
    if [ -r $MEMDEV ]; then say "memdev readable yes"; else say "memdev readable no"; fi
    for l in $LOGGER1 $LOGGER2 $LOGGER3; do
        if [ -f $l ]; then say "logger $l"; fi
    done
    ls -l /bin/cc /usr/bin/cc >> $LOG 2>&1
    grep '"Active Drivers"' $SYSCFG >> $LOG 2>&1
    finish "R1CFACTS DONE $LOG"
fi

LENGTH="$3"
WANTSUM="$4"
WANTBLK="$5"

say "=== 1. arguments ==="
case "$LENGTH" in
    ""|*[!0-9]*|0*) finish "R1CREAD FAIL length '$LENGTH' is not a decimal number" ;;
esac
if [ "$LENGTH" -lt 512 ] || [ "$LENGTH" -gt 65536 ]; then
    finish "R1CREAD FAIL length $LENGTH outside 512..65536"
fi
rem=`expr $LENGTH % 512`
if [ "$rem" != "0" ]; then finish "R1CREAD FAIL length $LENGTH is not a multiple of 512"; fi
case "$WANTSUM" in
    ""|*[!0-9]*) finish "R1CREAD FAIL sum '$WANTSUM' is not a number" ;;
esac
case "$WANTBLK" in
    ""|*[!0-9]*) finish "R1CREAD FAIL blocks '$WANTBLK' is not a number" ;;
esac

say "=== 2. source sum ==="
if [ ! -f $SRC ]; then finish "R1CREAD FAIL no source $SRC"; fi
got=`$SUM $SRC`
set -- $got
say "  rdnbios.c sum $1 $2, host said $WANTSUM $WANTBLK"
if [ "$1" != "$WANTSUM" ] || [ "$2" != "$WANTBLK" ]; then
    finish "R1CREAD FAIL rdnbios.c sum $1 $2 differs from the host's $WANTSUM $WANTBLK"
fi

say "=== 3. ready ==="
if [ ! -r $MEMDEV ]; then finish "R1CREAD FAIL $MEMDEV is not readable (run as root)"; fi
if [ ! -f $SYSCFG ]; then finish "R1CREAD FAIL cannot read $SYSCFG"; fi
grep '"Active Drivers"' $SYSCFG >> $LOG
n=`grep '"Active Drivers"' $SYSCFG | egrep -c 'MGA|Matrox'`
if [ "$n" != "0" ]; then finish "R1CREAD FAIL Active Drivers names a Matrox driver: boot the generic VGA baseline"; fi
n=`grep '"Active Drivers"' $SYSCFG | grep -c 'VGA'`
if [ "$n" = "0" ]; then finish "R1CREAD FAIL Active Drivers does not name VGA: boot the generic VGA baseline"; fi

say "=== 4. claim $RUNID-$LENGTH (atomic) ==="
if [ ! -d $RANDIR ]; then mkdir $RANDIR || finish "R1CREAD FAIL cannot create $RANDIR"; fi
mkdir $RANDIR/$RUNID-$LENGTH 2> /dev/null || finish "R1CREAD FAIL $RUNID-$LENGTH was already run (or $RANDIR is not writable)"
sync

say "=== 5. build ==="
EXE=$TMP/rdnbios-$RUNID-$LENGTH
rm -f $EXE
$CC -O -o $EXE $SRC >> $LOG 2>&1
st=$?
say "  cc exit $st"
if [ "$st" != "0" ]; then finish "R1CREAD FAIL cc exit $st"; fi
if [ ! -f $EXE ]; then finish "R1CREAD FAIL cc produced no $EXE"; fi

say "=== 6. read ==="
LOGGER=""
for l in $LOGGER1 $LOGGER2 $LOGGER3; do
    if [ "$LOGGER" = "" ] && [ -f $l ]; then LOGGER=$l; fi
done
if [ "$LOGGER" != "" ]; then $LOGGER "RDN-R1C $RUNID start length=$LENGTH"; fi
sync
# the exit status is taken from the command itself, not from an assignment
# with a command substitution (whose status old Bourne shells do not agree on)
$EXE $RUNID $LENGTH > $TMP/rdnbios-$RUNID-$LENGTH.line 2>&1
st=$?
line=`cat $TMP/rdnbios-$RUNID-$LENGTH.line`
say "  $line"
if [ "$LOGGER" != "" ]; then $LOGGER "RDN-R1C $RUNID done length=$LENGTH exit=$st"; fi
if [ "$st" != "0" ]; then finish "R1CREAD FAIL rdnbios exit $st"; fi

say "=== 7. capture ==="
# rdnbios builds this name itself, always under /tmp; not an override
CAP=/tmp/rdn-bios-$RUNID-$LENGTH.bin
if [ ! -f $CAP ]; then finish "R1CREAD FAIL no capture $CAP"; fi
size=`wc -c < $CAP | sed 's/ //g'`
if [ "$size" != "$LENGTH" ]; then finish "R1CREAD FAIL capture is $size bytes, not $LENGTH"; fi
got=`$SUM $CAP`
set -- $got
csum="$1 $2"
say "  capture sum $csum"
if [ ! -d $OUT ]; then finish "R1CREAD FAIL no build directory $OUT"; fi
cp $CAP $OUT/rdn-bios-$RUNID-$LENGTH.bin || finish "R1CREAD FAIL cp to $OUT failed"
sync
got=`$SUM $OUT/rdn-bios-$RUNID-$LENGTH.bin`
set -- $got
say "  copy sum $1 $2"
if [ "$1 $2" != "$csum" ]; then finish "R1CREAD FAIL the NFS copy's sum $1 $2 differs from $csum"; fi
finish "R1CREAD DONE $OUT/rdn-bios-$RUNID-$LENGTH.bin $csum"
