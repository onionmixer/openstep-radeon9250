#!/bin/sh
# What would installing the driver package change on THIS machine?  Read-only:
# it unpacks the package and compares it, file by file, with the bundle that
# is installed.  (openstep-matrox-remade's pkg/diff-against-installed.sh.)
#
#   sh .../pkg/diff-against-installed.sh [package-dir]
#
# The instance tables are listed but post_install keeps the machine's own
# (pre_install stashes them, post_install puts them back and rewrites only
# the six identity keys -- pkg/osrdn-identity-keys.awk), so a CHANGES line
# for a switch below is what a FIRST install would bring, not an upgrade.
PKGDIR="${1:-/tmp/pkgout}"
NAME=OSRDNDisplay
PKG="$PKGDIR/$NAME.pkg"
UNPACK=/tmp/_rdndrvdiff
LIVE=/private/Drivers/i386/$NAME.config

if [ ! -d "$PKG" ]; then
    echo "diff-against-installed: no $PKG" >&2
    exit 1
fi
rm -rf "$UNPACK"; /bin/mkdirs "$UNPACK"
( cd "$UNPACK" && /usr/ucb/zcat "$PKG/$NAME.tar.Z" | tar xf - )
NEW="$UNPACK/private/Drivers/i386/$NAME.config"

echo "the driver bundle"
for f in ${NAME}_reloc $NAME Default.table Instance0.table Display.modes \
         English.lproj/Localizable.strings \
         English.lproj/DisplayInspector.nib/data.classes \
         English.lproj/DisplayInspector.nib/data.dependency \
         English.lproj/DisplayInspector.nib/data.nib; do
    if [ ! -r "$LIVE/$f" ]; then
        echo "  ADDED     $f"
    elif cmp -s "$NEW/$f" "$LIVE/$f"; then
        echo "  same      $f"
    else
        echo "  REPLACED  $f"
    fi
done

echo "files the installed bundle has and the package does not"
found=0
for f in `cd "$LIVE" && find . -type f -print`; do
    if [ ! -r "$NEW/$f" ]; then
        echo "  LEFT ALONE (not in the package)  $f"
        found=1
    fi
done
if [ "$found" -eq 0 ]; then echo "  none"; fi

echo "the keys, installed Instance0.table against the package's"
for k in "Title" "Version" "Driver Name" "Server Name" "Class Names" \
         "RDN R2B0 Record" "RDN Engine Test" "RDN VRAM Mmap" "RDN CP Test" \
         "RDN 3D Test" "Display Mode" "Gray Levels" "Location"; do
    # anchored: a comment explaining a key must not be read as its value
    now=`grep "^\"$k\" =" "$LIVE/Instance0.table"`
    new=`grep "^\"$k\" =" "$NEW/Instance0.table"`
    if [ "$now" = "$new" ]; then
        echo "  same      $k"
    else
        echo "  CHANGES   $k"
        echo "      installed: $now"
        echo "      package  : $new"
    fi
done

echo "documentation the package also writes"
for f in LICENSE NOTICE INSTALL.md; do
    d=/usr/local/Documentation/OpenStep-Radeon9250/$f
    if [ -r "$d" ]; then echo "  REPLACED  $d"; else echo "  ADDED     $d"; fi
done
