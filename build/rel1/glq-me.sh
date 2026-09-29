#!/bin/sh
# REL1 final: the installed glquake_radeon, 300 frames, no seed, no tools
whoami
cd /usr/local/quake || exit 1
RDNMesaTime=1 RDNMesaTimeSplit=150 sh /ndrv/openstep-quake/test/run-glquake-self.sh /usr/local/quake/glquake_radeon 300 110 0 -nosound +map start > /dev/null 2>&1
echo "rc=$?"
