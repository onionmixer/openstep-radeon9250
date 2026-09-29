#!/bin/sh
# REL1 B8: the same probe linked against the 1.0-rc library (seed counts from 1)
# and against the fixed one, each run twice in a row with RDNMesaSeed unset.
P=/ndrv/openstep-radeon9250
T=/tmp/_b8
rm -rf $T; mkdir $T || exit 1
for v in old:790654424 new:790662776; do
    n=`echo $v | sed 's/:.*//'`; r=`echo $v | sed 's/.*://'`
    cc -m486 -O -I/LocalDeveloper/Headers -I$P/mesa -I$P/OSRDNDisplay/OSRDNDisplay_reloc.tproj \
        -o $T/b8-$n $P/build/rel1/b8probe.c $P/build/m1b/$r/libGL_radeon.a -lm > $T/cc-$n.log 2>&1 || { cat $T/cc-$n.log; exit 1; }
done
unset RDNMesaSeed
for n in old old new new; do
    echo "$n: `cd $T && ./b8-$n`"
done
