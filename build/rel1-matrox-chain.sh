#!/bin/sh
# REL1 Matrox v1.4 chain on the target -- openstep-matrox-remade
# release-packaging/PAYLOAD_MANIFEST.md steps 1-6, in order, stopping at the
# first failure.  Written by docs/REL1_PACKAGING_PLAN.md 11-4.
M=/ndrv/openstep-matrox-remade
step() { echo "=== $1"; shift; "$@"; rc=$?; echo "=== rc=$rc"; if [ $rc != 0 ]; then echo "CHAIN FAIL"; exit $rc; fi; }
cd /tmp
step driver-bundle sh /ndrv/tools/build-matrox-driver.sh
step library csh -f $M/tools/build-matrox-mesa.csh
step driver-pkg sh $M/pkg/build-driver-pkg.sh
step accel-pkg sh $M/pkg/build-accel-pkg.sh $M /tmp/pkgout /ndrv/openstep-mesa342
step demos-overlay sh $M/pkg/build-demos-overlay.sh
step demos-pkg csh -f $M/pkg/build-demos-mga-pkg.csh
step verify-driver sh $M/pkg/verify-driver-pkg.sh
step verify-accel sh $M/pkg/verify-accel-pkg.sh /tmp/pkgout $M /ndrv/openstep-mesa342
step verify-demos sh $M/pkg/verify-demos-mga-pkg.sh
step bom-overlap sh $M/pkg/check-bom-overlap.sh
step collect sh $M/pkg/collect-release-pkgs.sh
echo "CHAIN PASS"
