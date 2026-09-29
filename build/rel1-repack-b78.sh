#!/bin/sh
# REL1 B7+B8: rebuild the radeon packages and sdl2quake with the fixed driver
# (790662775) and library (790662776).  Stops at the first failure.
step() { echo "=== $1"; shift; "$@"; rc=$?; echo "=== rc=$rc"; if [ $rc != 0 ]; then echo "CHAIN FAIL"; exit $rc; fi; }
R=/ndrv/openstep-radeon9250
LIB=790662776
# the target must see the host's edits whole (recorded NFS trap)
for e in 7037:/ndrv/openstep-radeon9250/release-packaging/INSTALL.md 5800:/ndrv/openstep-radeon9250/release-packaging/PORT-NOTES.md 29559:/ndrv/openstep-radeon9250/mesa/OSRDNMesaTri.h 6809:/ndrv/openstep-quake/README.md ; do
    want=`echo $e | sed 's/:.*//'`; f=`echo $e | sed 's/^[0-9]*://'`
    have=`wc -c < $f`
    if [ $have -ne $want ]; then echo "NFS STALE $f host $want target $have"; echo "CHAIN FAIL"; exit 1; fi
done
echo "nfs sizes agree"
cd /tmp
step driver-pkg sh $R/pkg/build-driver-pkg.sh
step accel-pkg sh $R/pkg/build-accel-pkg.sh $LIB
step verify-driver sh $R/pkg/verify-driver-pkg.sh
step verify-accel sh $R/pkg/verify-accel-pkg.sh
step demos-overlay sh $R/pkg/build-demos-overlay.sh $LIB
step demos-pkg csh -f $R/pkg/build-demos-rdn-pkg.csh
step verify-demos sh $R/pkg/verify-demos-rdn-pkg.sh
cp -r /usr/local/rel1/pkgout/OSMGADisplay.pkg /usr/local/rel1/pkgout/OSMGAMesaAccel.pkg /tmp/pkgout/
step bom-overlap sh $R/pkg/check-bom-overlap.sh
step diff-installed sh $R/pkg/diff-against-installed.sh
step collect sh $R/pkg/collect-release-pkgs.sh
# sdl2quake: glquake_radeon relinked against the fixed library
rm -rf /tmp/_q13out /tmp/_q13pfx; mkdir /tmp/_q13out /tmp/_q13out/bin /tmp/_q13pfx /tmp/_q13pfx/Libraries
cp /LocalDeveloper/Libraries/libSDL2.a /LocalDeveloper/Libraries/libGL.a /tmp/_q13pfx/Libraries/
cp /ndrv/openstep-matrox-remade/build/mesa/libGL_mga.a /tmp/_q13pfx/Libraries/
ranlib /tmp/_q13pfx/Libraries/libSDL2.a /tmp/_q13pfx/Libraries/libGL.a /tmp/_q13pfx/Libraries/libGL_mga.a
ln -s /LocalDeveloper/Headers /tmp/_q13pfx/Headers
ACCEL=radeon; RDN_LIB=$R/build/m1b/$LIB/libGL_radeon.a; export ACCEL RDN_LIB
step glquake-radeon sh /ndrv/openstep-quake/build/build-glquake.sh /ndrv/openstep-quake /tmp/_q13pfx /ndrv/openstep-matrox-remade /tmp/_q13out
ACCEL=; export ACCEL
cp /usr/local/rel1/build/_q13out/bin/squake /usr/local/rel1/build/_q13out/bin/glquake /tmp/_q13out/bin/
rm -rf /usr/local/rel1/pkgout-q3; mkdir /usr/local/rel1/pkgout-q3
step quake-pkg sh /ndrv/openstep-quake/pkg/build-sdl2quake-pkg.sh /ndrv/openstep-quake /usr/local/rel1/pkgout-q3 /tmp/_q13out/bin
/usr/bin/sum /tmp/_q13out/bin/*
cd /usr/local/rel1/pkgout-q3 && tar cf - sdl2quake.pkg > /ndrv/openstep-quake/build/release-pkgs/sdl2quake.pkg.tar
echo "CHAIN PASS"
