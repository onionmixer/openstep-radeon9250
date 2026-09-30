#!/bin/bash
# Turn the collected .pkg tars into the release assets, on the HOST.
#   bash .../pkg/make-release-assets.sh [version] [library-version, default = version]
# The target side is pkg/collect-release-pkgs.sh.  The names follow
# openstep-matrox-remade's: OpenStep-<product>-<version>-i486-<part>.pkg.tar.gz,
# and the Demos variant keeps the MESA port's version with the variant
# suffix, '+' written '-' because a '+' in a filename gets mangled in transit.
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
version="${1:-1.0}"
# the library can stay at an earlier release than the driver (1.1 ships the 1.0 library)
accel_version="${2:-$version}"
src="$root/build/release-pkgs"
dest="$root/release-assets"

declare -A NAMES=(
  [OSRDNDisplay]="OpenStep-Radeon9250-${version}-i486-Display"
  [OSRDNMesaAccel]="OpenStep-Radeon9250-${accel_version}-i486-MesaAccel"
  [OpenStepMesa342DemosRDN]="OpenStep-Mesa-3.4.2-openstep.1-rdn.1-i486-Demos"
)

for n in "${!NAMES[@]}"; do
    [[ -f "$src/$n.pkg.tar" ]] || {
        echo "make-release-assets: missing $src/$n.pkg.tar" >&2
        echo "make-release-assets: run pkg/collect-release-pkgs.sh on the target first" >&2
        exit 1
    }
done

rm -rf "$dest"
mkdir -p "$dest"
for n in "${!NAMES[@]}"; do
    out="$dest/${NAMES[$n]}.pkg.tar.gz"
    gzip -9 -n -c "$src/$n.pkg.tar" > "$out"
    # taken once into a variable: under pipefail a grep that stops at its first
    # match kills tar with SIGPIPE and fails a correct asset
    listing=$(tar tzvf "$out")
    grep "$n.pkg/$n.tar.Z" <<<"$listing" > /dev/null
    # the executable bit on pre_install has to survive, or Installer runs nothing
    grep "$n.pre_install" <<<"$listing" | grep 'r-x' > /dev/null
    echo "  ${NAMES[$n]}.pkg.tar.gz  $(stat -c%s "$out") bytes"
done

( cd "$dest" && sha256sum *.pkg.tar.gz > SHA256SUMS )
echo "make-release-assets: PASS $dest"
