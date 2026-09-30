#!/bin/sh
# REL2: OSRDNDisplay 1.1 into /me/packages/drivers/OSRDNDisplay; 1.0 to old/OSRDNDisplay-1.0.
P=/me/packages
N=/usr/local/rel1/pkgout-rel2/OSRDNDisplay.pkg
O=$P/old/OSRDNDisplay-1.0
fail() { echo "PLACE FAIL $*"; exit 1; }
[ -d $O ] && fail "$O exists"
grep '^Version 1.1$' $N/OSRDNDisplay.info > /dev/null || fail "new is not 1.1"
grep '^Version 1.0$' $P/drivers/OSRDNDisplay/OSRDNDisplay.pkg/OSRDNDisplay.info > /dev/null || fail "placed is not 1.0"
mkdir $O || fail mkdir
mv $P/drivers/OSRDNDisplay/OSRDNDisplay.pkg $O/ || fail mv
cp -r $N $P/drivers/OSRDNDisplay/ || fail cp
bad=0
for f in `ls $N`; do cmp -s $N/$f $P/drivers/OSRDNDisplay/OSRDNDisplay.pkg/$f || { echo "DIFFERS $f"; bad=1; }; done
grep '^Version' $P/drivers/OSRDNDisplay/OSRDNDisplay.pkg/OSRDNDisplay.info
ls $P/drivers/OSRDNDisplay $O
[ $bad = 0 ] && echo "PLACE PASS" || echo "PLACE FAIL"
