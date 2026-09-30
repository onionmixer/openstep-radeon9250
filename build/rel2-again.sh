#!/bin/sh
# REL2 judgement, second look: GLQuake again, still no teapot (no clear) this boot.
X=/ndrv/_ndrv_scratch/sdl5
cd /usr/local/quake || exit 1
rm -f /tmp/glq-self.log
RDNMesaTime=1; export RDNMesaTime
sleep 10
echo "AGAIN start `date`"
sh /ndrv/openstep-quake/test/run-glquake-self.sh /usr/local/quake/glquake_radeon 300 110 0 +map start
cp /tmp/glq-self.log $X/rel2-again.log; rm -f /tmp/glq-self.log
echo "AGAIN end `date`"
sync
echo "DONE"
