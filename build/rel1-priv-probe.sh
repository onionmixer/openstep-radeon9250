#!/bin/sh
# REL1 B7: may an ordinary user reach the driver's parameter interface?
# One harmless CP op (tdump: prints counters, touches no register).
whoami
/ndrv/openstep-radeon9250/build/r2b0/790654423/rdnr5cp 790661944 844b835c tdump
echo "rdnr5cp rc=$?"
