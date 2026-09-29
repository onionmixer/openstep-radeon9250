#!/bin/sh
# REL1: place the release packages under /me/packages (user's layout).
# New names go straight in; a package that replaces an older release moves the
# old one to /me/packages/old/<same path> first -- nothing is deleted.
P=/me/packages
S=/usr/local/rel1/pkgout
fail() { echo "PLACE FAIL $*"; exit 1; }
[ -d $P/old ] && fail "$P/old exists -- not merging into it"
mkdir $P/old $P/old/drivers $P/old/drivers/OSMGADisplay $P/old/mesa $P/old/quake || fail mkdir
mv $P/drivers/OSMGADisplay/OSMGADisplay.pkg $P/old/drivers/OSMGADisplay/ || fail mv1
mv $P/mesa/OSMGAMesaAccel.pkg $P/old/mesa/ || fail mv2
mv $P/mesa/OpenStepMesa342DemosMGA.pkg $P/old/mesa/ || fail mv3
mv $P/quake/sdl2quake.pkg $P/old/quake/ || fail mv4
mkdir $P/drivers/OSRDNDisplay || fail mkdir2
put() { cp -r $S/$1 $2/ || fail "cp $1"; }
put OSRDNDisplay.pkg $P/drivers/OSRDNDisplay
put OSRDNMesaAccel.pkg $P/mesa
put OpenStepMesa342DemosRDN.pkg $P/mesa
put OSMGADisplay.pkg $P/drivers/OSMGADisplay
put OSMGAMesaAccel.pkg $P/mesa
put OpenStepMesa342DemosMGA.pkg $P/mesa
put sdl2quake.pkg $P/quake
bad=0
for pair in "OSRDNDisplay.pkg drivers/OSRDNDisplay" "OSRDNMesaAccel.pkg mesa" \
            "OpenStepMesa342DemosRDN.pkg mesa" "OSMGADisplay.pkg drivers/OSMGADisplay" \
            "OSMGAMesaAccel.pkg mesa" "OpenStepMesa342DemosMGA.pkg mesa" "sdl2quake.pkg quake"; do
    n=`echo $pair | awk '{print $1}'`; d=`echo $pair | awk '{print $2}'`
    for f in `ls $S/$n`; do
        cmp -s $S/$n/$f $P/$d/$n/$f || { echo "DIFFERS $d/$n/$f"; bad=1; }
    done
    echo "  $d/$n: `grep '^Version' $P/$d/$n/*.info`"
done
[ $bad = 0 ] && echo "PLACE PASS" || echo "PLACE FAIL"
