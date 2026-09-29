#!/bin/bash
# M1l, the timing run (docs/M1L_PLAN.md 8, 9).
#
#   BUILD=<runid> bash build/m1l/run_m1l.sh
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
# THREE ARMS, one binary pair, one scene:
#   t-stock.out    the installed libGL -- software all the way, the baseline
#   t-accel.out    ours, batching ON  (M1k)
#   t-nobatch.out  ours, RDNMesaBatch=0 -- one submission per triangle (M1d..M1j)
#   t-hold.out     ours, batching ON but the device node held open across
#                  submissions -- splits open/close out of the fixed cost
#   t-poison.out   ours, every stream refused at word 0 -- the driver's fixed
#                  path and its 25 log lines WITHOUT any of the work
#   t-qhold.out    M2f, t-quiet with the node HELD: open/close priced without
#                  the submit log in the way (the log-on pair swung 24x)
#   t-quiet.out    ours, batching ON, the driver's 25 lines OFF (M1n) -- the
#                  same submission without the log, so the log has a price
#   t-nosent.out   M1r, t-quiet with RDNMesaSentLog=0 -- the same submission
#                  without the 21-word instrumentation copy a triangle
#   t-nullsend.out M1s, the hook without the send -- it assembles and then lets
#                  Mesa draw, so `submitted` is 0 and the picture is software
#   t-inline.out   M1t, t-quiet with the vertex writer inlined
#   t-nullinl.out  M1t, t-nullsend with the vertex writer inlined -- the pair
#                  that has no card in the loop at all
#   t-group.out    M1v, t-quiet with the whole-group render table installed
#   t-stage.out    M1x, a quiet arm whose stage times the driver accumulates;
#                  the numbers come out in the boot log's RDN-R5 tstage line
#   t-nowb.out     M2a, t-stage with the submission WBINVD skipped: the same
#                  words, the same picture, and a fence= that should collapse
#   t-notime.out   M2c, t-stage with the stage instrument OFF: the fall in the
#                  fixed cost is what the seventeen clock reads a submission cost
#   t-bothoff.out  M2d, t-notime with the WBINVD off too -- the fourth cell, so
#                  that "both off" stops being an addition and becomes a number
#   t-stage2.out   M2d, t-stage repeated as the LAST arm: the QUIET drift bar.
#                  t-accel2 cannot be that bar -- its arms carry the driver log,
#                  whose own cost moves by hundreds of us as syslogd settles
#   t-spin.out     M2b, t-stage with the wait polling before it sleeps: the same
#                  picture, fewer turns, and a wait= that says whether it helped
#   t-grid-L-N.out M1q, one cell a process: leg index L, n index N, two
#                  submissions, the driver's log ON
#   t-grid.drv     the boot's whole driver log, so each grid submission can be
#                  paired with the kernel's own timing of its spin
#
# WHAT CHANGED ABOUT THE CARD'S OWN WAIT (M1q).  This header used to say it was
# already known -- median 0 us over 118 client submissions (docs/M1L_PLAN.md 6)
# -- and that no driver log had to be fetched.  Re-reading those 118: every one
# of them carried 17..57 words, one to three triangles.  Nothing has ever
# measured the wait at n=72, which is 1,082 words, and the M1 ladder's own logs
# carry no `RDN-R5 wait` line at all (checked: zero files).  So the grid arm
# below fetches the log after all, and the claim above now holds only where it
# was measured.
set -u
P=$(cd "$(dirname "$0")/../.." && pwd)
G=$(cd "$P/.." && pwd)
BUILD=${BUILD:?set BUILD to the target build runid, e.g. BUILD=790036553}
B=/ndrv/openstep-radeon9250/build/m1b/$BUILD
CAPS=/ndrv/openstep-radeon9250/build/r2b0/790016206/osrdncaps
OP=$P/build/r7b/r5op.sh
OUT=$P/build/m1l

say() { echo "== $*"; }
mach() { (cd "$G" && GCDS_CONF=etc/gcds.cnf ./bin/gcds next "$1") | sed 's/.*mach: //'; }

# M2e: AN ARM SAYS ITS OWN KNOBS.
#
# Until M2e the arms inherited whatever the arm before them left.  Counted
# mechanically, the BASELINE arm t-stage inherited BOTH of them, and so did
# t-quiet, t-inline, t-group and five more; only t-accel2 stated both.  Today
# they inherit the right values, but a judge pair's whole claim is "these two
# arms differ in ONE knob", and that claim was resting on the ORDER of the arms.
# Move one arm, or add one, and it breaks with nothing to say so.
#
# So every arm a judge pair uses calls this first.  It is not free -- two CP
# operations, about a second of wall clock each -- but it is paid once an arm,
# outside anything being timed.
knobs() {               # $1 = nowb (0|1)   $2 = time (0|1)
    kn=`bash "$OP" nowb "$1" 2>&1 | sed 's/.*mach: //' \
        | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`
    kt=`bash "$OP" time "$2" 2>&1 | sed 's/.*mach: //' \
        | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`
    echo "   knobs nowb=$1 ($kn) time=$2 ($kt)"
    case "$kn$kt" in
      *"r=0"*"r=0") ;;
      *) say "a knob was refused (nowb: $kn, time: $kt) -- this arm's state is NOT what it says" ;;
    esac
}

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


# ONE SCENE, THREE ARMS.  The sweep is inside the test: it walks n and prints a
# line per block, and the judge fits the line on the host.  Each accelerated arm
# gets its own ZPREP and its own seed -- a repeated seed is refused (CP_WHY_SEED).
M=prof
mkdir -p "$OUT/$R/$M"
N=/ndrv/openstep-radeon9250/build/m1l/$R/$M

say "  stock (software all the way)"
knobs 0 1              # M2e: this arm says its own state
mach "sync; cd /tmp; $B/rdntri-stock ${R}s flat p > $N/t-stock.out 2>&1; sync; echo RC=\$?" | tail -1

# M1r/M1t: THE LEASE IS SPENT, NOT HELD.
#
# `quiet N` swallows N submissions and then the driver speaks again.  One sweep
# arm is 9 reps x 6 points x 5 legs x 8 submissions = 2,160, so a single
# `quiet 5000` before three arms runs out inside the THIRD -- which is exactly
# what happened: t-inline came out with a 1,616 us intercept against t-quiet's
# 529 and a NEGATIVE slope, because most of its blocks were paying for the
# driver's 25 log lines.  Every quiet arm re-arms its own lease.
quiet() {
    qline=`bash "$OP" quiet "$1" 2>&1 | sed 's/.*mach: //' \
           | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`
    echo "   $qline"
    case "$qline" in
      *"r=0") ;;
      *) say "quiet $1 did not return 0 ($qline) -- the driver is older than M1n." ;;
    esac
}

# M2g: THE SUBMIT LOG IS OFF BY DEFAULT.  An arm that needs it asks for it with
# `loud N` and gives it back with `loud 0` -- a lease, so a runner that dies
# cannot leave the machine paying 1.25 ms a submission (docs/M2G_PLAN.md 3).
# Every arm below that pays the log says so HERE, in its own lines; none of
# them relies on a default any more (plan 4-2: five of them used to).
loud() {
    lline=`bash "$OP" loud "$1" 2>&1 | sed 's/.*mach: //' \
           | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`
    echo "   $lline"
    case "$lline" in
      *"r=0") ;;
      *) say "loud $1 did not return 0 ($lline) -- the driver is older than M2g." ;;
    esac
}

zprep() {
    zline=`bash "$OP" zprep 2>&1 | sed 's/.*mach: //' \
           | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`
    echo "   $zline"
    case "$zline" in
      *"r=0") ;;
      *) say "the ZPREP did not return 0 ($zline).  Stopping." ; exit 5 ;;
    esac
}

# M2c: THE STAGE INSTRUMENT IS OFF AT BOOT NOW, SO ASK FOR IT ONCE, HERE.
#
# Before M2c every client submission carried seventeen IOGetTimestamp calls with
# no way to decline.  It is a knob now, default off.  Every arm in this run wants
# it ON so the arms stay comparable with each other and with the earlier boots --
# every pair below differs in ONE knob, and the instrument must not be a second
# one.  The single arm that turns it off is t-notime, at the very end, and that
# difference is its measurement.
#
# A driver older than M2c has no `time` operation and returns non-zero; the run
# carries on, because on that driver the instrument is on unconditionally, which
# is exactly the state this line is asking for.
tmline=`bash "$OP" time 1 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`
echo "   stage instrument: $tmline"
case "$tmline" in
  *"r=0") ;;
  *) say "time 1 did not return 0 ($tmline) -- a pre-M2c driver times unconditionally, so the arms are still comparable" ;;
esac

say "  accel, batching ON"
zprep
loud 5000
knobs 0 1              # M2e: this arm says its own state
mach "sync; cd /tmp; RDNMesaSeed=$R $B/rdntri-accel ${R}a flat p > $N/t-accel.out 2>&1; sync; echo RC=\$?" | tail -1

say "  accel, batching OFF (one submission per triangle)"
zprep
loud 5000
knobs 0 1              # M2e: this arm says its own state
mach "sync; cd /tmp; RDNMesaSeed=$((R + 7000)) RDNMesaBatch=0 $B/rdntri-accel ${R}b flat p > $N/t-nobatch.out 2>&1; sync; echo RC=\$?" | tail -1

say "  accel, batching ON, and the node HELD across submissions"
zprep
loud 5000
knobs 0 1              # M2e: this arm says its own state
mach "sync; cd /tmp; RDNMesaSeed=$((R + 14000)) RDNMesaHold=1 $B/rdntri-accel ${R}h flat p > $N/t-hold.out 2>&1; sync; echo RC=\$?" | tail -1
loud 0

say "  accel, batching ON, stream POISONED (refused at word 0: the log without the work)"
zprep
knobs 0 1              # M2e: this arm says its own state
mach "sync; cd /tmp; RDNMesaSeed=$((R + 21000)) RDNMesaPoison=1 $B/rdntri-accel ${R}p flat p > $N/t-poison.out 2>&1; sync; echo RC=\$?" | tail -1

say "  accel, batching ON, the driver's submit log OFF (M1n)"
zprep
knobs 0 1              # M2e: this arm says its own state
mach "sync; cd /tmp; RDNMesaSeed=$((R + 28000)) $B/rdntri-accel ${R}q flat p > $N/t-quiet.out 2>&1; sync; echo RC=\$?" | tail -1

# M2f: THE SAME QUIET ARM WITH THE NODE HELD.
#
# The only pair that prices open/close today is t-accel against t-hold, and BOTH
# of those run with the driver's 25-line submit log on.  Across three runs that
# pair said 642.9, 657.2 and 26.9 us -- a factor of 24 -- while the HELD arm was
# stable to within 24 us.  So the swing is in the not-held arm, and the not-held
# arm is the one that pays rdnDevOpen's and rdnDevClose's IOLog ONCE A
# SUBMISSION: those two lines sit outside the quiet gate (OSRDNDisplay.m:160,
# :182 against the gate at :956).
#
# This arm takes the submit log out of the comparison.  What is left in the
# difference is the two syscalls and their own two lines -- which is what a
# client actually pays today, and what M2f-b will then gate.
#
# The lease: t-quiet asked for 5000 and one arm is 2,160 submissions, so ask
# again rather than assume what is left.
say "  the same quiet arm with the node HELD (M2f)"
zprep
knobs 0 1              # M2e: this arm says its own state
mach "sync; cd /tmp; RDNMesaSeed=$((R + 45000)) RDNMesaHold=1 $B/rdntri-accel ${R}k flat p > $N/t-qhold.out 2>&1; sync; echo RC=\$?" | tail -1

# M1r: THE SAME ARM WITH THE SENT-TRIANGLE RING OFF.
#
# `triRecord` copies twenty-one words a triangle into a ring nothing reads
# outside a gate run.  M1q left 1.20 us a triangle in userland and priced the
# hook's whole arithmetic at 50 ns of it, so the copies are where the time is.
# This arm is t-quiet with one knob moved and NOTHING else -- same seed spacing,
# same lease, adjacent in time -- so the difference of the two fits is the ring.
say "  accel, quiet, and the sent-triangle ring OFF (M1r)"
zprep
knobs 0 1              # M2e: this arm says its own state
mach "sync; cd /tmp; RDNMesaSeed=$((R + 29000)) RDNMesaSentLog=0 $B/rdntri-accel ${R}n flat p > $N/t-nosent.out 2>&1; sync; echo RC=\$?" | tail -1

# M1s: THE HOOK WITHOUT THE SEND.
#
# Everything the hook does -- classify, read the state, assemble the three
# vertices -- and then Mesa's software function draws it.  So this arm minus
# t-stock is the HOOK's own cost a triangle, and t-poison minus this arm is what
# the tri unit and the ioctl cost, with one software draw on both sides of each
# subtraction cancelling.  `submitted` must come out ZERO here.
say "  the hook WITHOUT the send -- the bisection arm (M1s)"
zprep
knobs 0 1              # M2e: this arm says its own state
mach "sync; cd /tmp; RDNMesaSeed=$((R + 30000)) RDNMesaNullSend=1 $B/rdntri-accel ${R}z0 flat p > $N/t-nullsend.out 2>&1; sync; echo RC=\$?" | tail -1

# M1t: THE SAME TWO ARMS AGAIN, WITH THE VERTEX WRITER INLINED.
#
# `t-inline` against `t-quiet` prices it where the card is in the loop;
# `t-nullinl` against `t-nullsend` prices it where the card is NOT -- if the
# card were the bottleneck the first pair could show nothing while the second
# still does (cross-review #13).  Both pairs differ in ONE knob.
#
# The witness that nothing changed is not a counter: `sent` prints the last
# eight triangles' words, and they must match the arm they are paired with word
# for word.
say "  the vertex writer INLINED -- with the card (M1t)"
zprep
knobs 0 1              # M2e: this arm says its own state
mach "sync; cd /tmp; RDNMesaSeed=$((R + 31000)) RDNMesaInline=1 $B/rdntri-accel ${R}i flat p > $N/t-inline.out 2>&1; sync; echo RC=\$?" | tail -1
say "  the vertex writer INLINED -- without the card"
zprep
knobs 0 1              # M2e: this arm says its own state
mach "sync; cd /tmp; RDNMesaSeed=$((R + 32000)) RDNMesaInline=1 RDNMesaNullSend=1 $B/rdntri-accel ${R}z1 flat p > $N/t-nullinl.out 2>&1; sync; echo RC=\$?" | tail -1

# M1v: THE WHOLE GROUP IN ONE CALL.
#
# `t-group` against `t-quiet` differs in one knob.  The state work -- the
# classifier, the ctx reads, the surface queries, about 260 of the 388
# instructions the disassembly counted -- moves from once a TRIANGLE to once a
# GROUP.  The witness is the sent words, which must not move at all.
say "  the whole group in one call (M1v)"
zprep
knobs 0 1              # M2e: this arm says its own state
mach "sync; cd /tmp; RDNMesaSeed=$((R + 33000)) RDNMesaGroup=1 $B/rdntri-accel ${R}v flat p > $N/t-group.out 2>&1; sync; echo RC=\$?" | tail -1

# the lease would end by itself; saying so out loud is cheaper than trusting it

# THE SAME ARM AGAIN, LAST.  The arms run one after another and the driver's
# log gets cheaper as syslogd gives up, so a difference between two arms can be
# their ORDER rather than their variable.  This repeat of the first accelerated
# arm measures that drift directly: t-accel and t-accel2 differ only in when
# they ran.
#
# THE LOG, MEASURED AS A B B A.
#
# The arms drift: the same arm run first and last differs by about 620 us
# (measured, run 790089625), which is MORE than the effect being looked for.
# So the log is measured adjacent in time and in both orders -- A B B A makes
# a linear drift cancel in the mean of the two differences.  This is the shape
# the Matrox work used for the same reason (tiercost.c: "AB BA AB BA"); it was
# in our own notes and this rung did not use it the first time.
#
abba() {                # $1 = tag   $2 = seed offset   $3 = loud lease (M2g: 0 = log OFF)
    zprep
    bash "$OP" loud "$3" 2>&1 | sed 's/.*mach: //' \
        | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1
    mach "sync; cd /tmp; RDNMesaSeed=$((R + $2)) $B/rdntri-accel ${R}$1 flat p > $N/t-$1.out 2>&1; sync; echo RC=\$?" | tail -1
}
say "  the log, A B B A (on, off, off, on) -- adjacent in time, both orders"
abba ab1 41000 5000
abba ab2 42000 0
abba ab3 43000 0
abba ab4 44000 5000
bash "$OP" loud 0 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1

# M1q: THE GRID -- ONE CELL A PROCESS, THE DRIVER'S LOG ON.
#
# Every arm above reads the wall clock, which cannot see how much of a
# submission the CARD owns.  cpWait times its own spin and the driver prints it
# (`RDN-R5 wait ... idle=evals/limit/us rptr=...`), so this arm asks the kernel
# instead of inferring.
#
# A CELL A PROCESS.  Two submissions each: the driver prints about 2 KB of log a
# submission and the kernel's msgbuf is 4 KB, so a loop inside one process would
# throw its own early lines away.  The log is fetched once at the end, WIDE --
# from the boot's first line to the end, not the lines carrying a nonce, because
# a narrow fetch drops the lines a judge needs (recorded).
#
# The two legs carry the SAME words and differ only in pixels; that is the whole
# experiment (docs/M1Q_PLAN.md 7-2).
say "  the grid: leg x n, the driver's log ON, one cell a process (M1q)"
bash "$OP" loud 5000 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1
gs=50000
for gl in 1 4; do          # index into profLeg[] = {2,4,8,16,32}: leg 4 and leg 32
    for gn in 0 1 2 3; do  # index into profGridN[] = {1,18,36,72}
        gs=$((gs + 100))
        printf '   leg#%s n#%s ' "$gl" "$gn"
        zprep
        mach "sync; cd /tmp; RDNMesaSeed=$((R + gs)) RDNProfGridLeg=$gl RDNProfGridN=$gn $B/rdntri-accel ${R}g$gl$gn flat p > $N/t-grid-$gl-$gn.out 2>&1; sync; echo RC=\$?" | tail -1
    done
done
bash "$OP" loud 0 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1

# M1x: WHERE THE KERNEL'S 366 us GOES.
#
# The arm runs QUIET -- the log costs about 1,085 us a submission and would
# treble what is being measured -- and the driver accumulates eight stage times
# internally.  Then the log goes back on and one `tdump` prints them once.
#
# The zprep comes first because this is a real client arm; the tdump itself
# draws nothing and waits for nothing.
say "  the kernel's stages, accumulated quietly then dumped once (M1x)"
# CLEAR FIRST.  The accumulators are the driver's, not this arm's: every client
# submission since the last tdump is in them.  Without this the first dump
# carried TWELVE arms (25,836 submissions, measured) and its biggest bucket was
# the analysis that only the LOG-ON arms run -- a number about arms, not stages.
bash "$OP" tdump 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1
zprep
knobs 0 1              # M2e: this arm says its own state
mach "sync; cd /tmp; RDNMesaSeed=$((R + 34000)) $B/rdntri-accel ${R}x flat p > $N/t-stage.out 2>&1; sync; echo RC=\$?" | tail -1
tline=`bash "$OP" tdump 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`
echo "   $tline"
case "$tline" in
  *"r=0") ;;
  *) say "tdump did not return 0 ($tline) -- the driver is older than M1x" ;;
esac

#
# M2a: THE SAME ARM WITH THE SUBMISSION WBINVD OFF.
#
# The references do a memory barrier here and no CPU cache operation at all, and
# leave the PCI GART entries snooped (docs/M2A_PLAN.md 1-2).  Whether THIS
# machine's memory really snoops is what this arm asks.  The stage accumulators
# price it: `fence=` should fall to about nothing, and the PICTURE must not move.
#
# The knob is turned OFF again at the end, on the success path and on the failure
# path alike -- a boot that ends with it on would silently colour every later arm.
say "  the same arm with the submission WBINVD OFF (M2a)"
bash "$OP" tdump 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1
nwline=`bash "$OP" nowb 1 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`
echo "   $nwline"
# M2d: THE ARM RUNS ONLY IF THE KNOB TOOK.
#
# It used to run either way -- `say` is an echo (:63), not an exit -- so a
# refused `nowb 1` left an arm that is a COPY of t-stage, and the judge priced
# it as "fixed cost 491 -> 491, 0 us saved".  A wrong number with nobody to
# call it wrong.  Now a refused knob leaves NO file, the judge's pair skips it,
# and the line below is what the transcript keeps in its place.
case "$nwline" in
  *"r=0")
    zprep
    knobs 1 1              # M2e: this arm says its own state
    mach "sync; cd /tmp; RDNMesaSeed=$((R + 36000)) $B/rdntri-accel ${R}w flat p > $N/t-nowb.out 2>&1; sync; echo RC=\$?" | tail -1
    bash "$OP" tdump 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1
    ;;
  *) say "nowb did not return 0 ($nwline) -- NOT running this arm: it would be a copy of t-stage" ;;
esac
# BACK TO THE SHIPPED DEFAULT, unconditionally.
# M2e: that default is now `nowb 1` (skip the WBINVD).  It used to be `nowb 0`,
# and leaving 0 here would leave every later arm on the SLOW path while the
# transcript said nothing.
offline=`bash "$OP" nowb 1 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`
echo "   back to the default (nowb 1): $offline"

#
# M2b: THE SAME ARM AGAIN, POLLING BEFORE IT SLEEPS.
#
# cpWait sleeps IODelay(10) between questions; one question costs 0.83 us
# (measured).  If the card is ready inside that window the sleep is waste.  The
# spin asks up to N more times first.  Both bounds are untouched; what the arm
# measures is whether the card IS ready that soon -- `wait=` and the turn counts
# in the log say it together (docs/M2B_PLAN.md 2).
#
# Turned OFF again at the end on every path: a boot that ended with it on would
# colour every later arm and nothing in the transcript would say so.
say "  the same arm again, polling before it sleeps (M2b)"
bash "$OP" tdump 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1
spline=`bash "$OP" spin 8 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`
echo "   $spline"
case "$spline" in
  *"r=0")
    zprep
    knobs 0 1              # M2e: this arm says its own state
    mach "sync; cd /tmp; RDNMesaSeed=$((R + 37000)) $B/rdntri-accel ${R}p flat p > $N/t-spin.out 2>&1; sync; echo RC=\$?" | tail -1
    bash "$OP" tdump 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1
    ;;
  *) say "spin did not return 0 ($spline) -- NOT running this arm: it would be a copy of t-stage" ;;
esac
offspin=`bash "$OP" spin 0 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`
echo "   back off: $offspin"

#
# M2c: THE SAME ARM WITH THE STAGE INSTRUMENT OFF.
#
# Seventeen IOGetTimestamp calls a client submission (docs/M2C_PLAN.md 2).  What
# one costs has been estimated three times from three arms and come out 2.84,
# 3.74 and 4.57 us -- so it has never been measured.  This arm measures it: the
# fall in the FIXED cost against t-stage is the instrument, whole.
#
# It issues NO tdump.  With the instrument off nothing accumulates, so a dump
# here would print `ops=0` as the LAST tstage line of the boot and the judge
# would rightly fail the whole run on it (judge_m1l.py, the ops=0 rule).
#
# M2d MOVED t-accel2 BEHIND THIS ARM.  This comment used to say the opposite --
# that this arm comes after the drift arm on purpose -- which left the two arms
# M2d cares about outside the bracket t-accel/t-accel2 form.  The drift arm is
# last now, so the bracket closes around every arm including this one.
#
# The knob is left OFF at the end -- which is also the boot default, so a later
# arm that forgets to ask gets the plain driver and not a silently timed one.
say "  the same arm with the stage instrument OFF (M2c)"
ntline=`bash "$OP" time 0 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`
echo "   $ntline"
case "$ntline" in
  *"r=0")
    zprep
    knobs 0 0              # M2e: this arm says its own state
    mach "sync; cd /tmp; RDNMesaSeed=$((R + 38000)) $B/rdntri-accel ${R}t flat p > $N/t-notime.out 2>&1; sync; echo RC=\$?" | tail -1
    ;;
  *) say "time 0 did not return 0 ($ntline) -- the driver is older than M2c, so this arm cannot be run" ;;
esac

#
# M2d: BOTH KNOBS OFF AT ONCE -- IS THE SAVING THE SUM?
#
# M2a measured -221 us for the WBINVD and M2c measured -60 us for the stage
# instrument, each with the OTHER knob left alone.  "Both off costs 210" is then
# an ADDITION, not a measurement, and addition assumes the two are independent.
# They might not be: the WBINVD throws the whole cache away and the instrument's
# seventeen clock reads touch kernel memory, so one could have been paying the
# other's misses already.  M2a itself showed that shape once -- the kernel saved
# 181 us and end-to-end fell 221.
#
# `time` is ALREADY 0 here: the arm above set it and deliberately left it off
# (see its comment).  So this arm turns exactly one more knob.
#
# It issues no tdump, for the same reason t-notime does not: with the instrument
# off nothing accumulates and an `ops=0` line would become the last tstage line
# of the boot, which the judge rightly fails the whole run on.
say "  the same arm with BOTH knobs off (M2d)"
bfline=`bash "$OP" nowb 1 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`
echo "   $bfline"
case "$bfline" in
  *"r=0")
    zprep
    knobs 1 0              # M2e: this arm says its own state
    mach "sync; cd /tmp; RDNMesaSeed=$((R + 39000)) $B/rdntri-accel ${R}o flat p > $N/t-bothoff.out 2>&1; sync; echo RC=\$?" | tail -1
    ;;
  *) say "nowb 1 did not return 0 ($bfline) -- NOT running this arm: it would be a copy of t-notime" ;;
esac
# BACK TO THE SHIPPED DEFAULT, unconditionally -- the same discipline as the M2a arm
offboth=`bash "$OP" nowb 1 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`
echo "   back to the default (nowb 1): $offboth"

#
# THE DRIFT ARM, AND IT IS LAST ON PURPOSE (M2d).
#
# It used to sit before t-notime, which meant the two arms that matter most to
# M2d -- t-notime and t-bothoff -- were OUTSIDE the bracket it forms with
# t-accel.  A fixed-cost shift confined to the end of the run would then land
# wholly in M2d's residual and be read as an interaction.  It now closes the
# bracket around every arm.
#
# Its knobs must match t-accel's, which ran with the instrument ON and the
# WBINVD ON: `nowb` is already back to 0 just above, so only `time` is restored.
say "  accel again, LAST -- the same arm as the first, to price the drift across the WHOLE run"
tmback=`bash "$OP" time 1 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`
echo "   instrument back on for the drift arm: $tmback"
case "$tmback" in
  *"r=0")
    zprep
    loud 5000
    knobs 0 1              # M2e: this arm says its own state
    mach "sync; cd /tmp; RDNMesaSeed=$((R + 35000)) $B/rdntri-accel ${R}z flat p > $N/t-accel2.out 2>&1; sync; echo RC=\$?" | tail -1
    loud 0
    ;;
  *) say "time 1 did not return 0 ($tmback) -- NOT running the drift arm: it would not match t-accel" ;;
esac
#
# AND THE DRIFT THAT M2d ACTUALLY NEEDS: A QUIET ARM REPEATED.
#
# t-accel/t-accel2 run with the driver's log ON, and that log is not a constant:
# it costs about 1,085 us a submission once syslogd saturates and MORE before
# that (docs/.. log-cost-depends-on-syslogd).  Measured on run 790188919 their
# difference was -354 us, and taking t-stage's quiet 491 out of both shows why:
# the log was 1,441 us at the start of the run and 1,087 at the end.  That is
# the log settling, not the machine drifting -- and the quiet arms never pay it.
# Using it as M2d's bar would swallow the whole 60 us instrument result.
#
# So the bar is a QUIET arm repeated: t-stage2 is t-stage again, same knobs
# (instrument on, WBINVD on, log off), at the other end of the run.
#
# It issues NO tdump: a dump here would replace the stage table the M2b arm
# left, which is the one every earlier rung's numbers are quoted from.
say "  t-stage again, the LAST arm -- the quiet drift bar for M2d"
case "$tmback" in
  *"r=0")
    zprep
    knobs 0 1              # M2e: this arm says its own state
    mach "sync; cd /tmp; RDNMesaSeed=$((R + 40000)) $B/rdntri-accel ${R}s flat p > $N/t-stage2.out 2>&1; sync; echo RC=\$?" | tail -1
    ;;
  *) say "the instrument is off ($tmback) -- NOT running the quiet drift bar: it would not match t-stage" ;;
esac

# AND BACK TO THE SHIPPED DEFAULTS, so the boot ends where a fresh one starts:
# instrument off, WBINVD skipped.  Every arm above stated its own state, so this
# is not needed by them -- it is here so that anything run AFTER this script,
# by hand, gets the driver as it ships.
knobs 1 0

wc -l "$OUT/$R/$M/t-stock.out" "$OUT/$R/$M/t-accel.out" "$OUT/$R/$M/t-nobatch.out" "$OUT/$R/$M/t-hold.out" "$OUT/$R/$M/t-poison.out" "$OUT/$R/$M/t-quiet.out" "$OUT/$R/$M/t-qhold.out" "$OUT/$R/$M/t-nosent.out" "$OUT/$R/$M/t-nullsend.out" "$OUT/$R/$M/t-inline.out" "$OUT/$R/$M/t-nullinl.out" "$OUT/$R/$M/t-group.out" "$OUT/$R/$M/t-stage.out" "$OUT/$R/$M/t-nowb.out" "$OUT/$R/$M/t-spin.out" "$OUT/$R/$M/t-notime.out" "$OUT/$R/$M/t-bothoff.out" "$OUT/$R/$M/t-accel2.out" "$OUT/$R/$M/t-stage2.out" "$OUT/$R/$M/t-ab1.out" "$OUT/$R/$M/t-ab2.out" "$OUT/$R/$M/t-ab3.out" "$OUT/$R/$M/t-ab4.out"

# the boot's whole log, so the (stage, wait) pairs the grid produced are here
# next to the transcripts that name them
if [ -n "${BOOT:-}" ]; then
    say "  fetching this boot's driver log for the grid"
    (cd "$G" && GCDS_CONF=etc/gcds.cnf ./bin/gcds next "sed -n '/boot=$BOOT/,\$p' /usr/adm/messages") \
        | sed 's/.*mach: //' > "$OUT/$R/$M/t-grid.drv"
    echo "   t-grid.drv: $(wc -l < "$OUT/$R/$M/t-grid.drv") lines"
else
    say "  BOOT=<nonce> was not given, so t-grid.drv was not fetched --"
    say "  the M1q verdict will rest on the wall clock alone"
fi

echo "M1L-RUN-DONE $R"
echo "   judge: python3 tools/mesa/judge_m1l.py build/m1l/$R/$M"
