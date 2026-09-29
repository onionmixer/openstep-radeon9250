#!/bin/bash
# M1d, the hardware half (docs/M1D_PLAN.md 5).
#
#   BUILD=<runid> bash build/m1d/run_m1d.sh
#
# THE CP IS ONE LOAD..STOP CYCLE PER BOOT.  This script therefore ASKS before it
# starts anything: if CAPS already says cprunning=1 -- as it does when M1a's
# preamble ran earlier in the same boot and did not stop -- the preamble is
# skipped.  Running `load` on a started ring is refused (r=-714) and the boot is
# spent for nothing, which is exactly the accident the R6m note records.
#
# It does NOT stop the CP either.  A gate that fails here is worth another
# attempt in the same boot, and a stop would make that impossible.
#
# Two links of one source, so that a difference in the pixels has one cause:
#   rdntri-stock   the installed libGL, software all the way
#   rdntri-accel   ours, which sends the flat triangles to the card
set -u
P=$(cd "$(dirname "$0")/../.." && pwd)
G=$(cd "$P/.." && pwd)
BUILD=${BUILD:?set BUILD to the target build runid, e.g. BUILD=790036553}
B=/ndrv/openstep-radeon9250/build/m1b/$BUILD
CAPS=/ndrv/openstep-radeon9250/build/r2b0/790016206/osrdncaps
OP=$P/build/r7b/r5op.sh
OUT=$P/build/m1d

say() { echo "== $*"; }
mach() { (cd "$G" && GCDS_CONF=etc/gcds.cnf ./bin/gcds next "$1") | sed 's/.*mach: //'; }

R=$(python3 -c "import time;print(int(time.time())-1000000000)")
say "run $R, build $BUILD"

say "is the CP already up?  (asking, not assuming)"
CAPLINE=$(mach "sync; $CAPS ${R}q 2>&1 | head -1")
echo "   $CAPLINE"
case "$CAPLINE" in
  *cprunning=1*) say "the CP is already running -- the preamble is SKIPPED" ;;
  *cprunning=0*)
      say "bringing the CP up (this spends the boot's one cycle)"
      # EVERY OP IS CHECKED.  They used to be printed and forgotten: when the op
      # tool was built for the previous driver it refused every one, printed
      # nothing the grep matched, and the loop walked on.  The CP never started
      # and all six modes then declined for "no acceleration" -- six transcripts
      # that looked like a library bug (docs/M1H_PLAN.md 13).
      for op in record rec3d load map reset start; do
          printf '   %-8s ' "$op"
          line=`bash "$OP" "$op" 2>&1 | sed 's/.*mach: //' \
                | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`
          echo "$line"
          case "$line" in
            *"r=0") ;;
            "")  say "the op tool said nothing for $op -- it is probably built for"
                 say "another driver.  Stopping: a run without the CP judges nothing."
                 exit 4 ;;
            *)   say "$op did not return 0 ($line).  Stopping."
                 exit 4 ;;
          esac
      done ;;
  *)  say "CAPS did not answer; stopping rather than guessing"; exit 3 ;;
esac

# The transcripts are ~1600 lines each.  They are written STRAIGHT TO NFS
# rather than catted back through gcds: a cat that size is slow enough to meet
# the 180 s remote timeout, and a truncated transcript would be judged as a
# short one rather than as a failure to fetch it.
#
# TWO MODES, TWO RUNS.  One process submits once, because the driver carries a
# client stream as a CP_OP_ZCLEAR and refuses one with no ZPREP since the last
# (docs/M1D_PLAN.md 4e).  So flat and Gouraud each get their own ZPREP and their
# own seed -- a repeated seed is refused too (CP_WHY_SEED), and the seed base is
# the run id plus an offset per mode.
mode_run() {            # $1 = tag   $2 = seed base   $3.. = the test's arguments
    M=$1
    SEED=$2
    shift 2
    A="$*"
    mkdir -p "$OUT/$R/$M"
    N=/ndrv/openstep-radeon9250/build/m1d/$R/$M
    say "  $M ($A): the STOCK link (software all the way)"
    mach "sync; cd /tmp; $B/rdntri-stock ${R}s $A > $N/t-stock.out 2>&1; sync; echo RC=\$?" | tail -1
    say "  $M: one ZPREP, then ours"
    zline=`bash "$OP" zprep 2>&1 | sed 's/.*mach: //' \
           | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`
    echo "$zline"
    case "$zline" in
      *"r=0") ;;
      *) say "the ZPREP did not return 0 ($zline).  Stopping." ; exit 5 ;;
    esac
    mach "sync; cd /tmp; RDNMesaSeed=$SEED $B/rdntri-accel ${R}a $A > $N/t-accel.out 2>&1; sync; echo RC=\$?" | tail -1
    wc -l "$OUT/$R/$M/t-stock.out" "$OUT/$R/$M/t-accel.out"
}

# five combinations, each its own submission, its own ZPREP and its own seed.
#
# TEXTURE IS FLAT AND UNBLENDED, on purpose.  Under GL_REPLACE the vertex colour
# never reaches the buffer, so pairing it with Gouraud would test nothing the
# smooth run does not; and every texel has alpha 0xff, at which the measured
# blend factors make the result the source exactly (docs/M1F_PLAN.md 5c), so
# pairing it with blending would look like blending that worked whether or not
# it did.
mode_run flat         "$R"              flat
mode_run smooth       "$((R + 1000))"   smooth
mode_run flat-blend   "$((R + 2000))"   flat   blend
mode_run smooth-blend "$((R + 3000))"   smooth blend
mode_run tex          "$((R + 4000))"   flat   tex
# M1h: three triangles in ONE frame.  Until the driver stopped demanding a ZPREP
# per client submission this was one triangle and two software fallbacks, and
# the picture still looked right -- which is why the three overlap in a known
# order (docs/M1H_PLAN.md 12).
mode_run multi        "$((R + 5000))"   flat   multi
# M1i: two overlapping triangles at different depths, the FAR one drawn second.
# If depth survives across submissions the near colour stays in the overlap; if
# it does not, the far one wins there (docs/M1I_PLAN.md 8).
mode_run depth        "$((R + 6000))"   flat   depth

say "the driver's own view of the run"
mach "dmesg | grep RDN | tail -20"

echo "M1D-RUN-DONE $R"
for m in flat smooth flat-blend smooth-blend tex multi depth; do
    echo "   judge: python3 tools/mesa/judge_m1d.py build/m1d/$R/$m"
done
