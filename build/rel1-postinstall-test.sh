#!/bin/sh
# REL1 19: run the two post_install scripts against a scratch prefix (fresh-install
# path: no stash) and show what they made.  Nothing outside /tmp/_pt is touched.
for d in OSRDNDisplay:/ndrv/openstep-radeon9250/pkg:38 OSMGADisplay:/ndrv/openstep-matrox-remade/pkg:37; do
    n=`echo $d | awk -F: '{print $1}'`; p=`echo $d | awk -F: '{print $2}'`; m=`echo $d | awk -F: '{print $3}'`
    rm -rf /tmp/_pt; mkdir /tmp/_pt /tmp/_pt/private /tmp/_pt/private/dev /tmp/_pt/private/Drivers /tmp/_pt/private/Drivers/i386 /tmp/_pt/private/Drivers/i386/$n.config
    echo "\"Character Major\" = \"$m\";" > /tmp/_pt/private/Drivers/i386/$n.config/Default.table
    csh -f $p/$n.post_install /pkg /tmp/_pt
    echo "$n rc=$?"
    ls -l /tmp/_pt/private/dev
done
rm -rf /tmp/_pt
