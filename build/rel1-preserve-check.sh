#!/bin/sh
# compare every preserved file with its original, by sum (REL1 14)
R=/usr/local/rel1
bad=0
chk() {   # $1 original dir, $2 copy dir
    ( cd "$1" && find . -type f -print ) | sort > /tmp/_p_a
    ( cd "$2" && find . -type f -print ) | sort > /tmp/_p_b
    if cmp -s /tmp/_p_a /tmp/_p_b; then :; else echo "LIST DIFFERS $1 $2"; diff /tmp/_p_a /tmp/_p_b | head; bad=1; fi
    for f in `cat /tmp/_p_a`; do
        cmp -s "$1/$f" "$2/$f" || { echo "DIFFERS $1/$f"; bad=1; }
    done
    echo "  checked `wc -l < /tmp/_p_a` files: $1"
}
chk /tmp/pkgout/OSRDNDisplay.pkg $R/pkgout/OSRDNDisplay.pkg
chk /tmp/pkgout/OSRDNMesaAccel.pkg $R/pkgout/OSRDNMesaAccel.pkg
chk /tmp/pkgout/OSMGADisplay.pkg $R/pkgout/OSMGADisplay.pkg
chk /tmp/pkgout/OSMGAMesaAccel.pkg $R/pkgout/OSMGAMesaAccel.pkg
chk /tmp/pkgout/sdl2quake.pkg $R/pkgout/sdl2quake.pkg
chk /tmp/OSRDNDisplay-r2b0 $R/build/OSRDNDisplay-r2b0
chk /tmp/_q13out $R/build/_q13out
chk /tmp/_rdnteapot $R/build/_rdnteapot
chk /tmp/_mgateapot $R/build/_mgateapot
chk /private/Drivers/i386/OSRDNDisplay.config $R/backup/OSRDNDisplay.config
rm -f /tmp/_p_a /tmp/_p_b
if [ $bad = 0 ]; then echo "PRESERVE_CHECK PASS"; else echo "PRESERVE_CHECK FAIL"; fi
