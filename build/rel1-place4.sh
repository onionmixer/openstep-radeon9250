#!/bin/sh
# REL1 six-keys: swap the two driver packages (INSTALL.md, awk comments) into /me/packages.
P=/me/packages
O=/usr/local/rel1/superseded-rc3
fail() { echo "PLACE4 FAIL $*"; exit 1; }
[ -d $O ] && fail "$O exists"
mkdir $O || fail mkdir
mv $P/drivers/OSRDNDisplay/OSRDNDisplay.pkg $O/ || fail mv1
mv $P/drivers/OSMGADisplay/OSMGADisplay.pkg $O/ || fail mv2
cp -r /tmp/pkgout/OSRDNDisplay.pkg $P/drivers/OSRDNDisplay/ || fail cp1
cp -r /tmp/pkgout/OSMGADisplay.pkg $P/drivers/OSMGADisplay/ || fail cp2
bad=0
for n in OSRDNDisplay OSMGADisplay; do
    for f in `ls /tmp/pkgout/$n.pkg`; do cmp -s /tmp/pkgout/$n.pkg/$f $P/drivers/$n/$n.pkg/$f || { echo "DIFFERS $n/$f"; bad=1; }; done
    echo "  $n: `grep '^Version' $P/drivers/$n/$n.pkg/$n.info`"
done
rm -rf /usr/local/rel1/pkgout-6k-placed; mkdir /usr/local/rel1/pkgout-6k-placed
cp -r /tmp/pkgout/OSRDNDisplay.pkg /tmp/pkgout/OSMGADisplay.pkg /tmp/pkgout/OSRDNDisplay.pkg.buildid /usr/local/rel1/pkgout-6k-placed/
[ $bad = 0 ] && echo "PLACE4 PASS" || echo "PLACE4 FAIL"
