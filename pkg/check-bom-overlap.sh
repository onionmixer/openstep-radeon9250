#!/bin/sh
# No file may be claimed by two packages -- across THIS project, the Matrox
# project and the Mesa port.
#
#   sh .../pkg/check-bom-overlap.sh [pkg-outdir] [mesa-dist]
#
# openstep-matrox-remade's check compared its own two packages with the Mesa
# port's.  With a second driver project the question widens: two acceleration
# packages and two driver packages can be installed on one machine, and an
# Installer that removes one package may take a file another package still
# claims.  So every package present is compared with every other.  The two
# Demos variants are the exception by design (each carries the plain Demos
# payload; install one of the three) and are never both in one dist, because
# the Mesa builder wipes it per run.
PKGDIR="${1:-/tmp/pkgout}"
MESADIST="${2:-/usr/local/mesastage/OpenStepMesa342/dist}"
W=/tmp/_rdnbomoverlap
rm -rf "$W"; /bin/mkdirs "$W"
: > "$W/all"

add() {
    if [ -r "$1/$2.pkg/$2.bom" ]; then
        # the package name goes on with sed: /bin/awk is the old language and
        # has no -v
        lsbom "$1/$2.pkg/$2.bom" | awk '$2 ~ /^100/ {print $1}' | sed "s|\$| $2|" >> "$W/all"
        echo "  $2: `lsbom $1/$2.pkg/$2.bom | awk '$2 ~ /^100/' | wc -l` files"
    else
        echo "  (skipped, not built: $2)"
    fi
}
# this project's two must be there
for p in OSRDNDisplay OSRDNMesaAccel; do
    if [ ! -r "$PKGDIR/$p.pkg/$p.bom" ]; then
        echo "check-bom-overlap: no $PKGDIR/$p.pkg/$p.bom" >&2
        exit 1
    fi
done
add "$PKGDIR" OSRDNDisplay
add "$PKGDIR" OSRDNMesaAccel
add "$PKGDIR" OSMGADisplay
add "$PKGDIR" OSMGAMesaAccel
add "$MESADIST" OpenStepMesa342Libraries
add "$MESADIST" OpenStepMesa342Headers
add "$MESADIST" OpenStepMesa342DemosRDN
add "$MESADIST" OpenStepMesa342DemosMGA

# a path listed by more than one package
sort "$W/all" | awk '{ n[$1]++; w[$1] = w[$1] " " $2 }
    END { for (f in n) if (n[f] > 1) print f ":" w[f] }' > "$W/both"
n=`wc -l < "$W/both"`
if [ $n -eq 0 ]; then
    echo "CHECK_BOM_OVERLAP=PASS (no file is claimed by two packages)"
else
    echo "CHECK_BOM_OVERLAP=FAIL ($n claimed by two packages)"
    cat "$W/both"
    exit 1
fi
