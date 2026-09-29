#!/bin/sh
# REL1: before the rehearsal reboot, move what lives only in /tmp to the local
# disk, and back up what an install would change (docs/REL1_PACKAGING_PLAN.md 14).
R=/usr/local/rel1
if [ -d $R ]; then echo "PRESERVE FAIL $R exists -- not overwriting"; exit 1; fi
mkdir $R $R/pkgout $R/build $R/backup || exit 1
cd /tmp/pkgout && tar cf - . | (cd $R/pkgout && tar xf -) || exit 1
# the demos variants' packages exist only as the collected tars on NFS now
(cd $R/pkgout && tar xf /ndrv/openstep-radeon9250/build/release-pkgs/OpenStepMesa342DemosRDN.pkg.tar) || exit 1
(cd $R/pkgout && tar xf /ndrv/openstep-matrox-remade/build/release-pkgs/OpenStepMesa342DemosMGA.pkg.tar) || exit 1
cd /tmp && tar cf - OSRDNDisplay-r2b0 _q13out _rdnteapot _mgateapot | (cd $R/build && tar xf -) || exit 1
# backups: the installed driver bundle (tables included), the file that says
# which drivers load, the installed quake binaries
cd /private/Drivers/i386 && tar cf - OSRDNDisplay.config | (cd $R/backup && tar xf -) || exit 1
cp /private/Drivers/i386/System.config/Instance0.table $R/backup/System.config.Instance0.table || exit 1
mkdir $R/backup/quake && cp /usr/local/quake/squake /usr/local/quake/glquake $R/backup/quake/ || exit 1
ls /LocalDeveloper/Libraries > $R/backup/LocalDeveloper-Libraries.txt
ls /NextLibrary/Receipts > $R/backup/Receipts.txt
echo "PRESERVE PASS"
