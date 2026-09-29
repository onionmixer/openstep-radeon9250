#!/bin/sh
# target-cfgsave.sh -- keep a copy of OSRDNDisplay's tables, before and after
# a Configure.app change, so a boot can be judged against what Configure wrote.
#
#   sh target-cfgsave.sh <tag>
#
# docs/R3_MULTIMODE_PLAN.md 23-9 X2.  <tag> is letters, digits and '-' only.
# Writes <out>/<tag>/ with every *.table of the bundle, the listing and the
# sums.  Refuses a tag that already exists.  Reads only.
#
# Target shell rules: ASCII, no printf, cut, $(...), grep -q, mkdir -p,
# test -e; arguments read before any function.  R3_* overrides are for
# tools/r3/check_target_r3.py only.

TAG="$1"

DRV=${R3_DRV:-/private/Drivers/i386}
OUT=${R3_OUT:-/ndrv/openstep-radeon9250/build/r3b2/cfg}
DIR=$DRV/OSRDNDisplay.config

fail() {
    echo "CFGSAVE FAIL $1"
    exit 1
}

if [ "$TAG" = "" ]; then
    echo "usage: sh target-cfgsave.sh <tag>"
    exit 2
fi
# grep, not a case pattern: this machine's sh refused every tag with
# *[!A-Za-z0-9-]* (2026-09-18, boot dfc354ea); this form was checked there
ok=`echo "$TAG" | grep -c '^[a-zA-Z0-9-][a-zA-Z0-9-]*$'`
if [ "$ok" != "1" ]; then fail "tag may hold letters, digits and - only"; fi
if [ ! -d $DIR ]; then fail "no $DIR"; fi

for d in `echo $OUT | tr '/' ' '`; do
    p="$p/$d"
    if [ ! -d $p ]; then mkdir $p || fail "mkdir $p"; fi
done
if [ -d $OUT/$TAG ]; then fail "$OUT/$TAG exists already"; fi
mkdir $OUT/$TAG || fail "mkdir $OUT/$TAG"

ls -l $DIR > $OUT/$TAG/listing
# cat, not cp: cp creates the copy with the table's mode (444) and the NFS
# server then refuses the write (2026-09-18, boot dfc354ea)
for f in $DIR/*.table; do
    if [ -f "$f" ]; then
        b=`basename "$f"`
        cat "$f" > $OUT/$TAG/$b || fail "cannot copy $f"
    fi
done
# one open per file: appending record by record over NFS can keep only the
# last record (the OPENSTEP NFS append trap); the redirected loops run in a
# subshell, so they set nothing the script reads afterwards
for f in $DIR/*.table; do
    if [ -f "$f" ]; then sum "$f"; fi
done > $OUT/$TAG/sums
for f in $OUT/$TAG/*.table; do
    if [ -f "$f" ]; then sum "$f"; fi
done > $OUT/$TAG/sums.copy
n=`ls $OUT/$TAG | grep -c '\.table$'`
echo "  $n tables"
cat $OUT/$TAG/listing
grep '"Display Mode"' $OUT/$TAG/*.table
echo "CFGSAVE DONE $OUT/$TAG"
