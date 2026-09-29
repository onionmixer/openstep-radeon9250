#!/bin/sh
# REL1 B9: both driver packages again (the node, the sixth key); radeon's bundle
# is unchanged (790662775), Matrox's is rebuilt for its new table.
step() { echo "=== $1"; shift; "$@"; rc=$?; echo "=== rc=$rc"; if [ $rc != 0 ]; then echo "CHAIN FAIL"; exit $rc; fi; }
for e in 5980:/ndrv/openstep-radeon9250/pkg/OSRDNDisplay.post_install 4223:/ndrv/openstep-radeon9250/pkg/osrdn-identity-keys.awk 13013:/ndrv/openstep-radeon9250/pkg/verify-driver-pkg.sh 7873:/ndrv/openstep-radeon9250/release-packaging/INSTALL.md 4038:/ndrv/openstep-matrox-remade/OSMGADisplay/Default.table 4110:/ndrv/openstep-matrox-remade/pkg/Instance0.release.table 5915:/ndrv/openstep-matrox-remade/pkg/OSMGADisplay.post_install 4042:/ndrv/openstep-matrox-remade/pkg/osmga-identity-keys.awk 11616:/ndrv/openstep-matrox-remade/pkg/verify-driver-pkg.sh 10973:/ndrv/openstep-matrox-remade/release-packaging/INSTALL.md ; do
    want=`echo $e | sed 's/:.*//'`; f=`echo $e | sed 's/^[0-9]*://'`
    have=`wc -c < $f`
    if [ $have -ne $want ]; then echo "NFS STALE $f host $want target $have"; echo "CHAIN FAIL"; exit 1; fi
done
echo "nfs sizes agree"
cd /tmp
R=/ndrv/openstep-radeon9250; M=/ndrv/openstep-matrox-remade
# /tmp was emptied by the reboot: the preserved (byte-compared) build tree and packages
mkdir -p /tmp/pkgout 2>/dev/null || /bin/mkdirs /tmp/pkgout
cp -r /usr/local/rel1/pkgout-b78/OSRDNMesaAccel.pkg /usr/local/rel1/pkgout-b78/OSRDNMesaAccel.pkg.buildid /tmp/pkgout/
step rdn-driver-pkg sh $R/pkg/build-driver-pkg.sh $R /tmp/pkgout /usr/local/rel1/build-b78/OSRDNDisplay-r2b0
step rdn-verify-driver sh $R/pkg/verify-driver-pkg.sh
step mga-bundle sh /ndrv/tools/build-matrox-driver.sh
step mga-driver-pkg sh $M/pkg/build-driver-pkg.sh
step mga-verify-driver sh $M/pkg/verify-driver-pkg.sh
cp -r /usr/local/rel1/pkgout/OSMGAMesaAccel.pkg /tmp/pkgout/ 2>/dev/null
step bom-overlap sh $R/pkg/check-bom-overlap.sh
step rdn-collect sh $R/pkg/collect-release-pkgs.sh
( cd /tmp/pkgout && tar cf - OSMGADisplay.pkg ) > $M/build/release-pkgs/OSMGADisplay.pkg.tar
echo "  OSMGADisplay.pkg.tar `wc -c < $M/build/release-pkgs/OSMGADisplay.pkg.tar` bytes"
echo "CHAIN PASS"
