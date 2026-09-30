#!/bin/sh
# REL2 judgement: GLQuake as the FIRST card client after the boot, no teapot.
X=/ndrv/_ndrv_scratch/sdl5
grep '^Version' /NextLibrary/Receipts/OSRDNDisplay.pkg/OSRDNDisplay.info
/usr/bin/sum /private/Drivers/i386/OSRDNDisplay.config/OSRDNDisplay_reloc
b=`egrep 'RDN-R2B0 init' /usr/adm/messages | tail -1`; echo "$b"
echo "autostart lines this boot so far:"; egrep 'RDN-R5 autostart' /usr/adm/messages | tail -1
cd /usr/local/quake || exit 1
rm -f /tmp/glq-self.log
RDNMesaTime=1; export RDNMesaTime
sleep 10
echo "FIRST start `date`"
sh /ndrv/openstep-quake/test/run-glquake-self.sh /usr/local/quake/glquake_radeon 300 110 0 +map start
cp /tmp/glq-self.log $X/rel2-first.log; rm -f /tmp/glq-self.log
echo "FIRST end `date`"
egrep 'RDN-R5 autostart' /usr/adm/messages | tail -1
sync
echo "DONE"
