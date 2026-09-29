#!/bin/sh
# REL1 14: after the Installer.app install, before the reboot.  Read-only.
R=/usr/local/rel1
P=/me/packages
D=/private/Drivers/i386/OSRDNDisplay.config
bad=0
ok()  { echo "  ok   $1"; }
no()  { echo "  FAIL $1"; bad=1; }
echo "receipts"
for r in OSRDNDisplay OSRDNMesaAccel sdl2quake; do
    if [ -d /NextLibrary/Receipts/$r.pkg ]; then ok "$r: `grep '^Version' /NextLibrary/Receipts/$r.pkg/$r.info`"; else no "no receipt for $r"; fi
done
echo "the driver bundle against the package payload"
rm -rf /tmp/_ic; mkdir /tmp/_ic; cd /tmp/_ic
/usr/ucb/zcat $P/drivers/OSRDNDisplay/OSRDNDisplay.pkg/OSRDNDisplay.tar.Z | tar xf -
N=/tmp/_ic/private/Drivers/i386/OSRDNDisplay.config
for f in OSRDNDisplay_reloc OSRDNDisplay Default.table Display.modes English.lproj/Localizable.strings \
         English.lproj/DisplayInspector.nib/data.classes English.lproj/DisplayInspector.nib/data.nib; do
    cmp -s $N/$f $D/$f && ok "$f as packaged" || no "$f differs from the package"
done
# data.dependency: the old tar drops that path; the package's own copy is read with cp from the pkg extraction dir
cmp -s "$N/English.lproj/DisplayInspector.nib/data.dependency" "$D/English.lproj/DisplayInspector.nib/data.dependency" && ok "nib data.dependency as packaged" || no "nib data.dependency differs"
cmp -s /tmp/_ic/private/Drivers/i386/osrdn-identity-keys.awk /private/Drivers/i386/osrdn-identity-keys.awk && ok "identity-key transform installed" || no "identity-key transform missing"
[ -d /private/Drivers/i386/OSRDNDisplay.instances ] && no "the stash is still there (post_install did not finish)" || ok "no stash left"
if [ -n "${DRVRUN:-}" ]; then
    want=`cat /ndrv/openstep-radeon9250/build/r2b0/$DRVRUN/R2B0RELOC_PASS`
    have=`/usr/bin/sum $D/OSRDNDisplay_reloc | awk '{print $1, $2}'`
    [ "$want" = "$have" ] && ok "installed reloc is the judged build $DRVRUN ($have)" || no "installed reloc $have is not build $DRVRUN's $want"
fi
echo "the machine's Instance0.table: kept, identity keys rewritten"
B=$R/backup/OSRDNDisplay.config/Instance0.table
egrep -v '^"(Driver Name|Server Name|Class Names|Family|Version)"' $B > /tmp/_ic/a
egrep -v '^"(Driver Name|Server Name|Class Names|Family|Version)"' $D/Instance0.table > /tmp/_ic/b
cmp -s /tmp/_ic/a /tmp/_ic/b && ok "every other line is the machine's, byte for byte" || { no "lines outside the five keys changed"; diff /tmp/_ic/a /tmp/_ic/b; }
# one grep per line into a file: nested quotes inside backquotes break this sh
egrep '^"(Driver Name|Server Name|Class Names|Family|Version)"' $B > /tmp/_ic/kb
egrep '^"(Driver Name|Server Name|Class Names|Family|Version)"' $D/Instance0.table > /tmp/_ic/ka
echo "      before:"; sed 's/^/        /' /tmp/_ic/kb
echo "      after:";  sed 's/^/        /' /tmp/_ic/ka
n=`grep '"Server Name"' $D/Instance0.table | wc -l`; [ $n -eq 1 ] && ok "one Server Name line" || no "$n Server Name lines"
cmp -s $R/backup/System.config.Instance0.table /private/Drivers/i386/System.config/Instance0.table && ok "System.config Instance0.table untouched" || no "System.config Instance0.table changed"
for f in LICENSE NOTICE INSTALL.md; do [ -s /usr/local/Documentation/OpenStep-Radeon9250/$f ] && ok "doc $f" || no "doc $f missing"; done
echo "the library"
L=/LocalDeveloper/Libraries/libGL_radeon.a
J=/ndrv/openstep-radeon9250/build/m1b/${LIBRUN:-790654424}/libGL_radeon.a
rm -rf /tmp/_ic/l1 /tmp/_ic/l2; mkdir /tmp/_ic/l1 /tmp/_ic/l2
(cd /tmp/_ic/l1 && ar x $L); (cd /tmp/_ic/l2 && ar x $J)
# object members only: the symbol table's name holds a space and is rebuilt by
# ranlib at the installed path, so it is not compared
ar t $J | grep '\.o$' > /tmp/_ic/objs
# a for loop, not `while read ... < file`: this sh runs that loop in a
# subshell, and the count and the failures would be lost (it reported 0)
m=0
for f in `cat /tmp/_ic/objs`; do
    m=`expr $m + 1`
    cmp -s "/tmp/_ic/l1/$f" "/tmp/_ic/l2/$f" || no "member $f differs"
done
if [ $m -eq 83 ]; then ok "all $m object members identical to the judged library's"; else no "compared $m object members, want 83"; fi
for h in OSRDNMesaHook.h OSRDNMesaPresent.h OSRDNMesaTriTable.h; do [ -s /LocalDeveloper/Headers/$h ] && ok "header $h" || no "header $h missing"; done
echo 'int main(){extern int OSMesaCreateContext();OSMesaCreateContext();return 0;}' > /tmp/_ic/t.c
cc -m486 -o /tmp/_ic/t /tmp/_ic/t.c $L -lm > /tmp/_ic/t.log 2>&1 && ok "links through its index at the installed path" || no "does not link (ranlib?)"
echo "quake"
cd /tmp/_ic && rm -rf q && mkdir q && cd q && /usr/ucb/zcat $P/quake/sdl2quake.pkg/sdl2quake.tar.Z | tar xf -
for f in squake glquake_g450 glquake_radeon; do cmp -s $f /usr/local/quake/$f && ok "$f as packaged" || no "$f differs or missing"; done
# a glquake left in the directory is only the package's business if a receipt
# owns it; a development copy is reported, not failed
if lsbom -s /NextLibrary/Receipts/sdl2quake.pkg/sdl2quake.bom | grep '^\./glquake$' > /dev/null; then
    no "the 1.3 receipt owns a file named glquake"
else
    ok "the 1.3 receipt owns no glquake"
fi
[ -f /usr/local/quake/glquake ] && echo "  note a glquake no receipt owns is in /usr/local/quake (`/usr/bin/sum /usr/local/quake/glquake`)"
[ -d /usr/local/quake/id1 ] && ok "game data still there (id1)" || no "id1 missing"
rm -rf /tmp/_ic
[ $bad = 0 ] && echo "INSTALLED_CHECK PASS" || echo "INSTALLED_CHECK FAIL"
