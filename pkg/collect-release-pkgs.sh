#!/bin/sh
# Collect the three release packages into the repository, one plain tar each.
#
#   sh .../pkg/collect-release-pkgs.sh [source-root] [driver-outdir] [mesa-dist]
#
# The shape is openstep-matrox-remade's pkg/collect-release-pkgs.sh.  Each
# package crosses as ONE tar because the NFS export refuses to create a
# mode-444 file and then write into it, which is what `package` leaves; inside
# a tar the modes are data and the executable bit on pre_install survives.
#
# The Mesa builder wipes its dist directory on every run, so this has to run
# right after the RDN variant was built -- before the Matrox one.
set -e
SRC="${1:-/ndrv/openstep-radeon9250}"
DRVOUT="${2:-/tmp/pkgout}"
MESADIST="${3:-/usr/local/mesastage/OpenStepMesa342/dist}"
DEST="$SRC/build/release-pkgs"

DRV=OSRDNDisplay
ACC=OSRDNMesaAccel
DEM=OpenStepMesa342DemosRDN

for p in "$DRVOUT/$DRV.pkg" "$DRVOUT/$ACC.pkg" "$MESADIST/$DEM.pkg"; do
    if [ ! -d "$p" ]; then
        echo "collect-release-pkgs: missing $p" >&2
        exit 1
    fi
done

rm -rf "$DEST"
/bin/mkdirs "$DEST"
copy_pkg() {
    ( cd "$1" && tar cf - "$2.pkg" ) > "$DEST/$2.pkg.tar"
    if [ ! -s "$DEST/$2.pkg.tar" ]; then
        echo "collect-release-pkgs: $2.pkg.tar is empty" >&2
        exit 1
    fi
}
copy_pkg "$DRVOUT" "$DRV"
copy_pkg "$DRVOUT" "$ACC"
copy_pkg "$MESADIST" "$DEM"
# which builds these are, beside them
cp "$DRVOUT/$DRV.pkg.buildid" "$DEST/$DRV.buildid"
cp "$DRVOUT/$ACC.pkg.buildid" "$DEST/$ACC.buildid"

for n in "$DRV" "$ACC" "$DEM"; do
    if tar tf "$DEST/$n.pkg.tar" | grep "$n.tar.Z" > /dev/null; then
        :
    else
        echo "collect-release-pkgs: $n.tar.Z is not in $n.pkg.tar" >&2
        exit 1
    fi
    echo "  $n.pkg.tar  `wc -c < $DEST/$n.pkg.tar` bytes"
done
echo "collect-release-pkgs: PASS $DEST"
