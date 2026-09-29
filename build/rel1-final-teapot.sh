#!/bin/sh
# REL1 final check: the first client after a boot, as an ordinary user, no tools.
whoami
u=`whoami`; rm -rf /tmp/_fc2.$u; mkdir /tmp/_fc2.$u; cd /tmp/_fc2.$u || exit 1
/usr/local/rel1/build-b78/_rdnteapot/overlay/Examples/Mesa342/RDNTeapot/rdnteapot_hybrid 64 64 10 card.ppm 2>&1 | grep RDNTEAPOT | egrep 'step=end |end-tri|end-refused'
