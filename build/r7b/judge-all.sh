#!/bin/bash
# R7b: both judges over one boot, in one command.
#
#   sh build/r7b/judge-all.sh <boot nonce>
#
# The two are deliberately separate and are NOT allowed to share code:
#   judge_r7b.py   the PATH -- the batch page, the window, the latch, and every
#                  refusal that never reaches the verifier
#   indep_r7a.py   the VERDICTS -- the thirteen rules written out a second time,
#                  reading the driver's own allow-list and the CLIENT's generated
#                  tables, so the two can agree only by both being right
#
# It fetches the boot's log first: a judge run against a stale file is a judge
# reporting another boot's evidence.
set -u
N=${1:-}
case "$N" in [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) echo "usage: judge-all.sh <boot nonce>"; exit 2 ;; esac
P=$(cd "$(dirname "$0")/../.." && pwd)
G=$(cd "$P/.." && pwd)
LOG=$P/build/r6/boot-$N.full.log

echo "== fetching this boot's log"
# From the boot's first line to the end, NOT the lines that carry the nonce: several
# lines the judges need do not carry one at all (RDN-R6 zr, the read-back rows), and
# filtering by nonce silently drops them -- which made fifteen refusals look like
# fifteen disagreements when the hardware was right (2026-09-22).  The judges do
# their own boot-slicing.
(cd "$G" && GCDS_CONF=etc/gcds.cnf ./bin/gcds next "sed -n '/boot=$N/,\$p' /usr/adm/messages") \
    | sed 's/.*mach: //' > "$LOG"
echo "   $LOG: $(wc -l < "$LOG") lines"
if [ "$(grep -c "boot=$N" "$LOG")" = "0" ]; then
    echo "   STOP: the log names no such boot"; exit 1
fi

rc=0
echo "== the path (build/r7b/judge_r7b.py)"
python3 "$P/build/r7b/judge_r7b.py" "$N" "$LOG" || rc=1

echo "== the verdicts, recounted (build/r7/indep_r7a.py)"
# the order the runner performs: case 6 through rdnr5cp (not a client stream), then
# the sixteen client streams 0..15 in order
python3 "$P/build/r7/indep_r7a.py" "$N" "$LOG" \
    --tool="$P/tools/r7/rdnr7dev.c" \
    --order=0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15 || rc=1

echo "judge-all: $([ $rc = 0 ] && echo PASS || echo FAIL)"
exit $rc
