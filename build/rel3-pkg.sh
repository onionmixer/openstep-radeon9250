#!/bin/sh
# REL3 (docs/REL3_DISPLAY_FIX_PLAN.md): the Display 1.2 package from the build
# just made (790772415, /tmp/OSRDNDisplay-r2b0; default 7), verified, beside the unchanged
# Accel package for the overlap check.  Installs nothing.
step() { echo "=== $1"; shift; "$@"; rc=$?; echo "=== rc=$rc"; if [ $rc != 0 ]; then echo "CHAIN FAIL"; exit $rc; fi; }
for e in 1301:/ndrv/openstep-radeon9250/pkg/OSRDNDisplay.info 643:/ndrv/openstep-radeon9250/OSRDNDisplay/Default.table 643:/ndrv/openstep-radeon9250/OSRDNDisplay/Instance0.table 7828:/ndrv/openstep-radeon9250/pkg/build-driver-pkg.sh 13013:/ndrv/openstep-radeon9250/pkg/verify-driver-pkg.sh 7886:/ndrv/openstep-radeon9250/release-packaging/INSTALL.md ; do
    want=`echo $e | sed 's/:.*//'`; f=`echo $e | sed 's/^[0-9]*://'`
    have=`wc -c < $f`
    if [ $have -ne $want ]; then echo "NFS STALE $f host $want target $have"; echo "CHAIN FAIL"; exit 1; fi
done
echo "nfs sizes agree"
cd /tmp
R=/ndrv/openstep-radeon9250
grep '^"Version"' /tmp/OSRDNDisplay-r2b0/OSRDNDisplay/OSRDNDisplay.config/Default.table 2>/dev/null
rm -rf /tmp/pkgout; mkdir /tmp/pkgout
cp -r /usr/local/rel1/pkgout-b78/OSRDNMesaAccel.pkg /usr/local/rel1/pkgout-b78/OSRDNMesaAccel.pkg.buildid /tmp/pkgout/
cp -r /usr/local/rel1/pkgout/OSMGAMesaAccel.pkg /tmp/pkgout/
cp -r /usr/local/rel1/pkgout-6k/OSMGADisplay.pkg /tmp/pkgout/
step driver-pkg sh $R/pkg/build-driver-pkg.sh $R /tmp/pkgout /tmp/OSRDNDisplay-r2b0
step verify-driver sh $R/pkg/verify-driver-pkg.sh
step bom-overlap sh $R/pkg/check-bom-overlap.sh
grep '^Version' /tmp/pkgout/OSRDNDisplay.pkg/OSRDNDisplay.info
cat /tmp/pkgout/OSRDNDisplay.pkg.buildid
( cd /tmp/pkgout && tar cf - OSRDNDisplay.pkg ) > $R/build/release-pkgs/OSRDNDisplay.pkg.tar
cp /tmp/pkgout/OSRDNDisplay.pkg.buildid $R/build/release-pkgs/OSRDNDisplay.buildid
echo "  OSRDNDisplay.pkg.tar `wc -c < $R/build/release-pkgs/OSRDNDisplay.pkg.tar` bytes"
rm -rf /usr/local/rel1/pkgout-rel3 /usr/local/rel1/build-rel3; mkdir /usr/local/rel1/pkgout-rel3
cp -r /tmp/pkgout/OSRDNDisplay.pkg /tmp/pkgout/OSRDNDisplay.pkg.buildid /usr/local/rel1/pkgout-rel3/
cp -r /tmp/OSRDNDisplay-r2b0 /usr/local/rel1/build-rel3
sync
echo "CHAIN PASS"
