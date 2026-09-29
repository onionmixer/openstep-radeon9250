#!/bin/sh
# REL1: sdl2quake 1.3 repacked with the Matrox binary installed as glquake_g450,
# from the preserved binaries; checked, then swapped into /me/packages/quake.
O=/usr/local/rel1/pkgout-q
fail() { echo "REPACK FAIL $*"; exit 1; }
for f in /ndrv/openstep-quake/README.md /ndrv/openstep-quake/pkg/sdl2quake.info /ndrv/openstep-quake/pkg/build-sdl2quake-pkg.sh; do
    echo "target `wc -c < $f` $f"
done
rm -rf $O; mkdir $O || fail mkdir
sh /ndrv/openstep-quake/pkg/build-sdl2quake-pkg.sh /ndrv/openstep-quake $O /usr/local/rel1/build/_q13out/bin || fail build
P=$O/sdl2quake.pkg
lsbom -s $P/sdl2quake.bom
grep '^Version' $P/sdl2quake.info
rm -rf /tmp/_qv2; mkdir /tmp/_qv2; cd /tmp/_qv2 || fail cd
/usr/ucb/zcat $P/sdl2quake.tar.Z | tar xf - || fail untar
B=/usr/local/rel1/build/_q13out/bin
cmp squake $B/squake || fail squake
cmp glquake_g450 $B/glquake || fail glquake_g450
cmp glquake_radeon $B/glquake_radeon || fail glquake_radeon
[ -f glquake ] && fail "a file named glquake is in the payload"
cmp docs/README-sdl2quake.md /ndrv/openstep-quake/README.md || fail readme
mv /me/packages/quake/sdl2quake.pkg /usr/local/rel1/sdl2quake.pkg.before-rename || fail mvold
cp -r $P /me/packages/quake/ || fail place
for f in `ls $P`; do cmp -s $P/$f /me/packages/quake/sdl2quake.pkg/$f || fail "placed $f"; done
echo "REPACK PASS"
