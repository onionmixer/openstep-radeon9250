#!/bin/sh
# check-all.sh -- every host-side check of this project, one verdict.
#
#   sh tools/check-all.sh
#
# Nothing here touches the target.  Each line is one tool's own verdict; the
# run fails if any tool fails or prints no verdict at all (a tool that crashed
# before printing must not look like a pass).

HERE=$(cd "$(dirname "$0")" && pwd)
PROJ=$(dirname "$HERE")
cd "$PROJ" || exit 2
rc=0
LOG=$(mktemp -d)

# EVERY TOOL'S SCRATCH GOES IN ONE PLACE, AND THAT PLACE IS DELETED.
#
# Measured 2026-09-24: /tmp held 21,427 entries and 61 GB, and 20,658 of those
# directories -- 35.6 GiB -- were ours.  `chkvmapm.*` alone was 2,548 dirs and
# 25.7 GiB.  Twenty-five tools call tempfile.mkdtemp and not one of them
# removes what it made, so every run of this suite left thousands behind and
# the root filesystem finally filled (192 MB free).
#
# The fix is here rather than in twenty-five files because every one of those
# tools honours TMPDIR -- most pass `dir=os.environ.get('TMPDIR')` explicitly
# and the rest reach it through tempfile.gettempdir().  One directory, one
# trap, and the suite leaves nothing behind whatever a tool forgets.
#
# A tool run BY HAND still leaks; the ones that leaked the most are fixed in
# themselves as well.
SCRATCH=$(mktemp -d "${TMPDIR:-/tmp}/rdncheck.XXXXXX") || exit 2
TMPDIR=$SCRATCH
export TMPDIR
trap 'rm -rf "$LOG" "$SCRATCH"' EXIT

run() {
    label=$1; want=$2; shift 2
    if "$@" > "$LOG/out" 2>&1 && grep -q "$want" "$LOG/out"; then
        printf '  ok   %s\n' "$label"
    else
        printf '  FAIL %s\n' "$label"
        tail -15 "$LOG/out" | sed 's/^/       /'
        rc=1
    fi
}

# what /tmp holds before anything runs, so the last check can say whether this
# suite left anything in it (see the SCRATCH note above for why it used to)
ls -1 /tmp > "$LOG/tmp-before" 2>/dev/null

echo "== sources =="
run "no citation of a source this project does not trust" 'no file cites' python3 tools/check_sources.py

echo "== oracles and extractors =="
run 'radeon_modeset.py self-check'      'PASS'  python3 tools/oracle/radeon_modeset.py --self-check
run 'radeon_decode.py self-test'        'PASS'  python3 tools/oracle/radeon_decode.py --self-test
run 'regtable.py (three headers agree)'   'not OK: 0,' python3 tools/oracle/regtable.py
run 'check_microcode.py'                 'microcode copies: IDENTICAL' python3 tools/oracle/check_microcode.py
run 'cmacro.py self-test'               'PASS'  python3 tools/oracle/cmacro.py --self-test
run 'cp_sequence.py self-test'          'PASS'  python3 tools/oracle/cp_sequence.py --self-test
run 'gart_oracle.py self-test'          'PASS'  python3 tools/oracle/gart_oracle.py --self-test
run 'r200_verifier.py self-test'        'PASS'  python3 tools/oracle/r200_verifier.py --self-test
run 'r200_clear_oracle.py self-test'    'PASS'  python3 tools/oracle/r200_clear_oracle.py --self-test
run 'audit_hooks.py self-test'          'PASS'  python3 tools/mesa/audit_hooks.py --self-test
run 'closes.py self-test'               'PASS'  python3 tools/r1/closes.py --self-test
run 'sync_docs.py self-test'            'PASS'  python3 tools/oracle/sync_docs.py --self-test
run 'the citation walker (self-test, G5-6)' 'check_citations self-test: PASS' python3 tools/oracle/check_citations.py --self-test

echo "== documents =="
run 'generated blocks equal their generators' 'sync_docs: PASS' python3 tools/oracle/sync_docs.py
for d in ANALYSIS.md PLAN.md docs/*.md; do
    # check_citations.py fails a document with no citations at all (so a fact
    # document cannot pass empty); a document that has none is reported as such
    if python3 tools/oracle/check_citations.py "$d" 2>&1 | grep -q '^citations: 0 checked, 0 failed$'; then
        printf '  --   %s (no citations)\n' "$d"
        continue
    fi
    run "citations $d" ' 0 failed' python3 tools/oracle/check_citations.py "$d"
done

echo "== R1 probe gate =="
run 'tools/r1/hostcheck.sh' 'hostcheck: PASS' sh tools/r1/hostcheck.sh

echo "== R1c BIOS read gate =="
run 'tools/r1c/hostcheck.sh' 'hostcheck-r1c: PASS' sh tools/r1c/hostcheck.sh

echo "== R2a MMIO and PLL snapshot gate =="
run 'tools/r2a/hostcheck.sh' 'hostcheck-r2a: PASS' sh tools/r2a/hostcheck.sh

echo "== R2b-0 activation-boot record gate =="
run 'tools/r2b0/hostcheck.sh' 'hostcheck-r2b0: PASS' sh tools/r2b0/hostcheck.sh

echo "== R2b first mode set gate =="
run 'tools/r2b/hostcheck.sh' 'hostcheck-r2b: PASS' sh tools/r2b/hostcheck.sh

echo "== R3 modes and formats =="
run 'R3 checks in the header generator can fail' 'mutate_gen_r3: PASS' python3 tools/r3/mutate_gen_r3.py
run 'the mode selection unit equals its oracle' 'test_modesel: PASS' python3 tools/r3/test_modesel.py
run 'Display.modes and the tables' 'check_bundle_modes: PASS' python3 tools/r3/check_bundle_modes.py
run 'R3 target scripts on a fake machine' 'check_target_r3: PASS' python3 tools/r3/check_target_r3.py
run 'the boot judge' 'check_select self-test: PASS' python3 tools/r3/check_select.py --self-test

echo "== R3d Configure inspector =="
run 'H0 inspector sources: C89, #import only' 'hostcheck-inspector: PASS' sh tools/r3/hostcheck_inspector.sh
run 'H1/H2 the panel table equals the driver rule' 'test_inspector_gray: PASS' python3 tools/r3/test_inspector_gray.py
run 'H3/H5 the shipped nib, decoded and measured' 'check_nib_r3d: PASS' python3 tools/r3/check_nib_r3d.py
run 'H4 reloc compile-line comparison (self-test)' 'check_reloc_cclines self-test: PASS' python3 tools/r3/check_reloc_cclines.py --self-test
run 'H7 the derived nib is on the record' 'check_notice_nib: PASS' python3 tools/r3/check_notice_nib.py

echo "== R4 2D engine (docs/R4_ENGINE_PLAN.md 12) =="
run 'engine source rules, each with a mutation' 'check_r4_src: PASS' python3 tools/r4/check_r4_src.py
run 'engine against a fake engine (driver = our model)' 'sim_r4: PASS' python3 tools/r4/sim_r4.py
run 'the offscreen window, 20 modes, three sources' 'check_window: PASS' python3 tools/r4/check_window.py
run 'register table judge (self-test)' 'regtable self-test: PASS' python3 tools/oracle/regtable.py --self-test
run 'the engine log judge (self-test)' 'check_engine self-test: PASS' python3 tools/r4/check_engine.py --self-test

echo "== R4c VRAM mapping (docs/R4C_VMAP_PLAN.md 11) =="
run 'd_mmap decision against the oracle, every page, with mutations' 'check_vmap: PASS' python3 tools/r4/check_vmap.py
run 'character-device source rules, each with a mutation' 'check_r4c_src: PASS' python3 tools/r4/check_r4c_src.py
run 'the mapping tool against the driver, the plan and the fake world' 'check_tool_r4map: PASS' python3 tools/r4/check_tool_r4map.py
run 'the R4c boot judge (self-test)' 'check_vmap_log self-test: PASS' python3 tools/r4/check_vmap_log.py --self-test

echo "== R5 Command Processor (docs/R5_PLAN.md 8, 9) =="
run 'the microcode header equals FreeBSD and linux-firmware' 'gen_ucode: PASS' python3 tools/r5/gen_ucode.py --check
run 'CP source rules, each with a mutation' 'check_r5_src: PASS' python3 tools/r5/check_r5_src.py
run 'the ring space equals the reference over every pointer pair (G5-2)' 'sim_space: PASS' python3 tools/r5/sim_space.py
run 'the G5-2 gate judge (self-test)' 'judge_g52 self-test: PASS' python3 build/g52/judge_g52.py --self-test
run 'the CP against a fake CP behind a PCI GART (driver = our model)' 'sim_r5: PASS' python3 tools/r5/sim_r5.py
run 'the R5 boot judge (self-test)' 'check_cp self-test: PASS' python3 tools/r5/check_cp.py --self-test
run 'the R5d two-boot judge (self-test)' 'check_r5d self-test: PASS' python3 tools/r5/check_r5d.py --self-test

echo "== R6a the first 3D (docs/R6_PLAN.md 7) =="
run 'the depth clear oracle (self-test)' 'zclear_oracle self-test: PASS' python3 tools/r6/zclear_oracle.py --self-test
run 'the triangle coverage oracle, 4032 hypotheses (self-test)' 'tri_oracle self-test: PASS' python3 tools/r6/tri_oracle.py --self-test
run 'the Gouraud interpolation oracle, 34984 named rules (self-test)' 'gouraud_oracle self-test: PASS' python3 tools/r6/gouraud_oracle.py --self-test
run 'the depth value oracle, R6f (self-test)' 'depth_oracle: PASS' python3 tools/r6/depth_oracle.py --self-test
run 'the texture oracle, R6h (self-test)' 'tex_oracle: PASS' python3 tools/r6/tex_oracle.py --self-test
run 'the perspective and bilinear oracle, R6i (self-test)' 'persp_oracle: PASS' python3 tools/r6/persp_oracle.py --self-test
run 'the R6f anchors separate the whole conversion space' 'separation: PASS' python3 tools/r6/depth_oracle.py --separation
run 'the depth clear against a fake 3D, judged by the oracle' 'sim_r6: PASS' python3 tools/r6/sim_r6.py
run 'the R6a boot judge (self-test)' 'check_r6a self-test: PASS' python3 tools/r6/check_r6a.py --self-test
run 'the runner plan files equal the judge procedures' 'check_plan_ops: PASS' python3 tools/r6/check_plan_ops.py
run 'check_plan_ops (self-test)'        'PASS'  python3 tools/r6/check_plan_ops.py --self-test
run 'G4-8 replay tool: allow table, stream boundaries, source rules' 'check_replay: PASS' python3 tools/g48/check_replay.py
run 'check_replay (self-test)'          'PASS'  python3 tools/g48/check_replay.py --self-test
run 'judge_replay (self-test)'          'PASS'  python3 tools/g48/judge_replay.py --self-test

echo "== R7 the client's own CP words (docs/R7_PLAN.md) =="
run 'the submission verifier oracle (self-test)' 'verify_oracle self-test: PASS' python3 tools/r7/verify_oracle.py --self-test
run 'the R7b source rules, each with a mutation' 'check_r7b: PASS' python3 tools/r7/check_r7b.py --self-test
run 'the R7b boot judge (self-test)' 'judge_r7b: PASS' python3 build/r7b/judge_r7b.py --self-test

echo "== M1a the acceleration gate (docs/M1A_PLAN.md) =="
run 'the hook contract, read from osmesa.c' 'design1: PASS' python3 build/m1a/design1.py
run 'the verdicts, derived from the interface' 'design2: PASS' python3 build/m1a/design2.py
run 'the probe against a fake node, input by input' 'sim_probe: PASS' python3 tools/mesa/sim_probe.py
run 'the probe source rules, each with a mutation' 'check_probe: PASS' python3 tools/mesa/check_probe.py
run 'the ten Mesa hooks (self-test)' 'audit_hooks self-test: PASS' python3 tools/mesa/audit_hooks.py --self-test

echo "== M1b the first real hook (docs/M1B_PLAN.md) =="
run 'the triangle chooser, counted' 'design1: PASS' python3 build/m1b/design1.py
run 'the constants borrowed from Mesa' 'design2: PASS' python3 build/m1b/design2.py
run 'the state classifier, state by state' 'sim_class: PASS' python3 tools/mesa/sim_class.py
run 'the hook source rules, each with a mutation' 'check_hook: PASS' python3 tools/mesa/check_hook.py
run 'the texture arena, run block by block (G4-1b)' 'sim_arena: PASS' python3 tools/mesa/sim_arena.py
run 'the client-side verifier is generated from the kernel (self-test)' 'gen_r7verify self-test: PASS' python3 tools/mesa/gen_r7verify.py --self-test
run 'the generated verifier is not stale' 'gen_r7verify --check: PASS' python3 tools/mesa/gen_r7verify.py --check
run 'the generated verifier gives the kernel verdict on every oracle case' 'sim_verify: PASS' python3 tools/mesa/sim_verify.py
run 'the ten hooks match their declarations' 'audit_hooks: PASS' python3 tools/mesa/audit_hooks.py --impl mesa/
run 'every unit in mesa/ is compiled and linked by the build' 'check_units: PASS' python3 tools/mesa/check_units.py
run 'no target script has a glob a quote would disable' 'check_target_sh: PASS' python3 tools/mesa/check_target_sh.py
run 'every C file we send the target compiles here, as C89' 'check_compile: PASS' python3 tools/mesa/check_compile.py
run 'the vertex packing, run slot by slot' 'sim_pack: PASS' python3 tools/mesa/sim_pack.py
run 'the frame-budget instrument, run on the host (G5-0)' 'sim_time: PASS' python3 tools/mesa/sim_time.py
run 'the texture upload read-back, run on the host (G5-1a)' 'sim_texupload: PASS' python3 tools/mesa/sim_texupload.py
run 'the present rows coalesced into one blit, run on the host (G5-1b)' 'sim_present: PASS' python3 tools/mesa/sim_present.py
run 'glReadPixels from the top-down surface against a python oracle (G5-4)' 'sim_readpix: PASS' python3 tools/mesa/sim_readpix.py
run 'the M1b build judge (self-test)' 'judge_m1b self-test: PASS' python3 tools/mesa/judge_m1b.py --self-test
# G4-2: and the judge on the LATEST library build -- the self-test alone let two
# rungs' new symbols (G3, G4-1b) go unjudged (found 2026-09-27)
LATEST_LIB=$(ls build/m1b | grep '^[0-9][0-9]*$' | sort -n | tail -1)
run "the M1b build judge (library $LATEST_LIB)" 'judge_m1b: PASS' python3 tools/mesa/judge_m1b.py "build/m1b/$LATEST_LIB"
run 'the M1c approval-run judge (self-test)' 'judge_m1c self-test: PASS' python3 tools/mesa/judge_m1c.py --self-test

echo "== M1d-M1f the hardware triangle: flat, Gouraud, blended =="
run 'the triangle-function decision, computed' 'sim_trifunc self-test: PASS' python3 tools/mesa/sim_trifunc.py --self-test
run 'the prologue generator (self-test)' 'gen_tri_prologue self-test: PASS' python3 tools/mesa/gen_tri_prologue.py --self-test
run 'the generated table is not stale' 'gen_tri_prologue --check: PASS' python3 tools/mesa/gen_tri_prologue.py --check
run 'the M1d approval-run judge (self-test)' 'judge_m1d self-test: PASS' python3 tools/mesa/judge_m1d.py --self-test
run 'the M1d independent recount (self-test)' 'indep_m1d self-test: PASS' python3 build/m1d/indep_m1d.py --self-test
run 'rule B, two independent implementations' 'indep_m1d cross-check: PASS' python3 build/m1d/indep_m1d.py --cross-check
run 'a whole textured run, built by one tool and judged by the other' 'sim_texrun: PASS' python3 tools/mesa/sim_texrun.py
run 'the M1k batch, built by the real unit and judged by the verifier' 'sim_batch: PASS' python3 tools/mesa/sim_batch.py
run 'the M1l timing judge (self-test)' 'judge_m1l self-test: PASS' python3 tools/mesa/judge_m1l.py --self-test
run 'the M1l runner: every arm states its own knobs' 'check_run_m1l: PASS' python3 tools/mesa/check_run_m1l.py
run 'the M1l runner checker (self-test)' 'check_run_m1l self-test: PASS' python3 tools/mesa/check_run_m1l.py --self-test
run 'the M3a teapot judge (self-test)' 'judge_teapot self-test: PASS' python3 tools/mesa/judge_teapot.py --self-test

echo "== REL1 release packaging (docs/REL1_PACKAGING_PLAN.md) =="
run 'the host release gates (self-test)' 'host_release_gates self-test: PASS' python3 pkg/host_release_gates.py --self-test
# the target's scripts are sh; make-release-assets.sh runs on the host and is bash
run 'the package scripts parse' 'pkg scripts: parse ok' sh -c 'for f in pkg/*.sh; do case "$f" in pkg/make-release-assets.sh) bash -n "$f" || exit 1 ;; *) sh -n "$f" || exit 1 ;; esac; done; echo "pkg scripts: parse ok"'

# ---- and the suite must not have grown /tmp.
#
# This is the check that would have caught it: 20,658 of our directories and
# 35.6 GiB had accumulated there, and the only symptom was the root filesystem
# filling.  Every tool's scratch is redirected into $SCRATCH above, which the
# trap deletes -- so /tmp itself must end where it started.  A tool that writes
# to a hard-coded /tmp path, or a new one that ignores TMPDIR, shows up here.
echo
echo "== scratch =="
# THE NAMES, NOT THE COUNT.  The first version compared entry counts and
# failed on 2026-09-24 because OTHER processes on this host -- another project's
# build, a codex sandbox, a JVM -- made /tmp entries while the suite ran.  So
# the entries that appeared are classified: a name that starts with a prefix
# THIS REPOSITORY's tools use (read from their sources now, not listed by hand)
# is ours and FAILS; anything else is named and left alone.
ls -1 /tmp > "$LOG/tmp-after" 2>/dev/null
python3 - "$LOG/tmp-before" "$LOG/tmp-after" "$PROJ" <<'PYEOF' || rc=1
import glob, os, re, sys
before = set(open(sys.argv[1]).read().split())
after = set(open(sys.argv[2]).read().split())
proj = sys.argv[3]
pre = set()
for p in (glob.glob(os.path.join(proj, 'tools', '**', '*.py'), recursive=True) +
          glob.glob(os.path.join(proj, 'tools', '**', '*.sh'), recursive=True) +
          glob.glob(os.path.join(proj, 'build', '**', '*.py'), recursive=True)):
    t = open(p, errors='replace').read()
    pre.update(re.findall(r"mkdtemp\(\s*prefix='([^']+)'", t))
    pre.update(re.findall(r"/tmp/([A-Za-z][A-Za-z0-9_]*[-.])", t))
new = sorted(after - before)
ours = [n for n in new if any(n.startswith(x) for x in pre)]
foreign = [n for n in new if n not in ours]
if ours:
    print('  FAIL %d new /tmp entr%s from this repository\'s tools: %s'
          % (len(ours), 'y' if len(ours) == 1 else 'ies', ', '.join(ours[:5])))
    sys.exit(1)
print('  ok   no /tmp entry left by this repository\'s tools (%d prefixes read '
      'from their sources)' % len(pre))
if foreign:
    print('       %d entr%s appeared that are not ours: %s'
          % (len(foreign), 'y' if len(foreign) == 1 else 'ies', ', '.join(foreign[:5])))
PYEOF

echo
[ $rc = 0 ] && echo "check-all: PASS" || echo "check-all: FAIL"
exit $rc
