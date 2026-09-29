#!/bin/sh
# REL1 B7+B8: swap the fixed packages into /me/packages; the first candidates
# go to /usr/local/rel1/superseded-rc1 (nothing deleted), then every file is compared.
P=/me/packages
O=/usr/local/rel1/superseded-rc1
fail() { echo "PLACE2 FAIL $*"; exit 1; }
[ -d $O ] && fail "$O exists"
mkdir $O || fail mkdir
mv $P/drivers/OSRDNDisplay/OSRDNDisplay.pkg $O/ || fail mv1
mv $P/mesa/OSRDNMesaAccel.pkg $O/ || fail mv2
mv $P/mesa/OpenStepMesa342DemosRDN.pkg $O/ || fail mv3
mv $P/quake/sdl2quake.pkg $O/ || fail mv4
cp -r /tmp/pkgout/OSRDNDisplay.pkg $P/drivers/OSRDNDisplay/ || fail cp1
cp -r /tmp/pkgout/OSRDNMesaAccel.pkg $P/mesa/ || fail cp2
cp -r /usr/local/mesastage/OpenStepMesa342/dist/OpenStepMesa342DemosRDN.pkg $P/mesa/ || fail cp3
cp -r /usr/local/rel1/pkgout-q3/sdl2quake.pkg $P/quake/ || fail cp4
bad=0
for pair in "/tmp/pkgout/OSRDNDisplay.pkg $P/drivers/OSRDNDisplay/OSRDNDisplay.pkg" \
            "/tmp/pkgout/OSRDNMesaAccel.pkg $P/mesa/OSRDNMesaAccel.pkg" \
            "/usr/local/mesastage/OpenStepMesa342/dist/OpenStepMesa342DemosRDN.pkg $P/mesa/OpenStepMesa342DemosRDN.pkg" \
            "/usr/local/rel1/pkgout-q3/sdl2quake.pkg $P/quake/sdl2quake.pkg"; do
    a=`echo $pair | awk '{print $1}'`; b=`echo $pair | awk '{print $2}'`
    for f in `ls $a`; do cmp -s $a/$f $b/$f || { echo "DIFFERS $b/$f"; bad=1; }; done
    echo "  $b: `grep '^Version' $b/*.info`"
done
# keep the fixed packages beside the preserved build too
rm -rf /usr/local/rel1/pkgout-b78; mkdir /usr/local/rel1/pkgout-b78
cp -r /tmp/pkgout/OSRDNDisplay.pkg /tmp/pkgout/OSRDNMesaAccel.pkg /tmp/pkgout/*.buildid /usr/local/rel1/pkgout-b78/
[ $bad = 0 ] && echo "PLACE2 PASS" || echo "PLACE2 FAIL"
