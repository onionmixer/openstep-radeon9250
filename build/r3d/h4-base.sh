#!/bin/sh
# H4 baseline (docs/R3_MULTIMODE_PLAN.md 26-3): make the last pre-inspector
# tar in /tmp and keep its compile lines.  Installs nothing.
OUT=/ndrv/openstep-radeon9250/build/r3d
rm -rf /tmp/rdn-h4base
mkdir /tmp/rdn-h4base || exit 1
cd /tmp/rdn-h4base || exit 1
tar xf /ndrv/openstep-radeon9250/build/r2b0/OSRDNDisplay-ae724459-789690148.tar || exit 1
cd OSRDNDisplay-r2b0/OSRDNDisplay || exit 1
make "OTHER_CFLAGS=-DOSRDN_BUILD=0xae724459" > /tmp/rdn-h4base/make.log 2>&1
echo "exit $?" > /tmp/rdn-h4base/make.exit
cat /tmp/rdn-h4base/make.log > $OUT/h4-base-ae724459.log
cat /tmp/rdn-h4base/make.exit > $OUT/h4-base-ae724459.done
