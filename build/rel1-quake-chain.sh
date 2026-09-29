#!/bin/sh
# REL1 sdl2quake 1.3 on the target (docs/REL1_PACKAGING_PLAN.md 11-5).
# glquake against Matrox 1.4's libGL_mga.a, glquake_radeon against the
# judged release libGL_radeon.a, squake the 1.2 bytes; then the package.
step() { echo "=== $1"; shift; "$@"; rc=$?; echo "=== rc=$rc"; if [ $rc != 0 ]; then echo "CHAIN FAIL"; exit $rc; fi; }
P=/tmp/_q13pfx
O=/tmp/_q13out
RLIB=/ndrv/openstep-radeon9250/build/m1b/790654424/libGL_radeon.a
cd /tmp
rm -rf $P $O
mkdir $P $P/Libraries $O $O/bin
cp /LocalDeveloper/Libraries/libSDL2.a /LocalDeveloper/Libraries/libGL.a $P/Libraries/
cp /ndrv/openstep-matrox-remade/build/mesa/libGL_mga.a $P/Libraries/
ranlib $P/Libraries/libSDL2.a $P/Libraries/libGL.a $P/Libraries/libGL_mga.a
ln -s /LocalDeveloper/Headers $P/Headers
step glquake-matrox sh /ndrv/openstep-quake/build/build-glquake.sh /ndrv/openstep-quake $P /ndrv/openstep-matrox-remade $O
ACCEL=radeon; RDN_LIB=$RLIB; export ACCEL RDN_LIB
step glquake-radeon sh /ndrv/openstep-quake/build/build-glquake.sh /ndrv/openstep-quake $P /ndrv/openstep-matrox-remade $O
ACCEL=; export ACCEL
cp /usr/local/nxbuild/bin/squake $O/bin/squake
/usr/bin/sum $O/bin/squake $O/bin/glquake $O/bin/glquake_radeon $O/bin/glquake_sw
step pkg sh /ndrv/openstep-quake/pkg/build-sdl2quake-pkg.sh /ndrv/openstep-quake /tmp/pkgout $O/bin
echo "CHAIN PASS"
