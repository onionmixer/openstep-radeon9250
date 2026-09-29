#!/bin/sh
# rebuild-inspector-nib.sh -- rebuild OSRDNDisplay's DisplayInspector.nib on
# the HOST (nibmaker's nib2xml/xml2nib are host binaries).
#
#   sh tools/r3/rebuild-inspector-nib.sh
#
# docs/R3_MULTIMODE_PLAN.md 25-4, 25-11 and 26.  Inputs, only the first of
# which comes from outside this workspace-of-projects:
#
#   stock nib   Configure.app's own DisplayInspector.nib, fetched once into
#               build/stocknib (not committed: it is NeXT's resource).  ON THE
#               TARGET:
#                 cd /NextAdmin/Configure.app/English.lproj && \
#                 tar cf - DisplayInspector.nib > \
#                   /ndrv/openstep-radeon9250/build/stocknib/stock-nib.tar
#               then here: (cd build/stocknib && tar xf stock-nib.tar).
#               A tar, because the files are mode 444 and cp onto NFS refuses
#               them.  Its sha256 must be the one recorded below.
#   templates   ../openstep-spacesaver2ps2/ref/nibtemplates/
#   nibmaker    ../openstep-nibmaker
#
# The bundle ships three files and this rebuilds only data.nib:
#   data.nib         built here
#   data.dependency  the stock one, byte for byte
#   data.classes     MAINTAINED BY HAND next to OSRDNDisplayInspector.h.  The
#                    stock one knows only IODisplayInspector; copying it over
#                    ours would silently disconnect the matrix (an outlet that
#                    fails to connect is nil, and messages to nil say nothing).
#                    tools/r3/check_nib_r3d.py holds the two together.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
PROJ=$(dirname "$(dirname "$HERE")")
WS=$(dirname "$PROJ")
STOCK="$PROJ/build/stocknib/DisplayInspector.nib"
OUT="$PROJ/build/r3d/nibout"
DST="$PROJ/OSRDNDisplay/English.lproj/DisplayInspector.nib"
STOCK_NIB_SHA=380bb6ed636ec9c72ffb667f7f0f0fff02ae444de9944ce12ee561d4636c58d0
STOCK_DEP_SHA=5d7f80764f4d7b9c92880fb5be897cdf808e38e70b112a0684d7f06fb7927733

[ -r "$STOCK/data.nib" ] || { echo "rebuild-inspector-nib: no stock nib at $STOCK (see this script's header)" >&2; exit 1; }
got=$(sha256sum "$STOCK/data.nib" | awk '{print $1}')
[ "$got" = "$STOCK_NIB_SHA" ] || { echo "rebuild-inspector-nib: stock data.nib is $got, not the recorded one" >&2; exit 1; }
got=$(sha256sum "$STOCK/data.dependency" | awk '{print $1}')
[ "$got" = "$STOCK_DEP_SHA" ] || { echo "rebuild-inspector-nib: stock data.dependency is $got, not the recorded one" >&2; exit 1; }

rm -rf "$OUT"; mkdir -p "$OUT"
python3 "$HERE/build-inspector-nib.py" \
    "$WS/openstep-nibmaker" "$STOCK" \
    "$WS/openstep-spacesaver2ps2/ref/nibtemplates/PS2MouseInspector.xml" \
    "$WS/openstep-spacesaver2ps2/ref/nibtemplates/radio-template-BusLogicIntrInspector.xml" \
    "$OUT"

mkdir -p "$DST"
cp "$OUT/data.nib" "$DST/data.nib"
cat "$STOCK/data.dependency" > "$DST/data.dependency"
chmod 644 "$DST/data.nib" "$DST/data.dependency"
[ -s "$DST/data.classes" ] || { echo "rebuild-inspector-nib: $DST/data.classes is missing (it is kept by hand)" >&2; exit 1; }
echo "rebuild-inspector-nib: PASS $(stat -c%s "$DST/data.nib") bytes -> $DST"
