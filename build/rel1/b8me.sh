#!/bin/sh
# REL1 final: B8 as an ordinary user, built from the installed prefix only
u=`whoami`; echo $u
T=/tmp/_b8.$u; rm -rf $T; mkdir $T; cd $T || exit 1
cc -m486 -O -I/LocalDeveloper/Headers -o b8 /ndrv/openstep-radeon9250/build/rel1/b8probe.c /LocalDeveloper/Libraries/libGL_radeon.a -lm > cc.log 2>&1 || { cat cc.log; exit 1; }
./b8; ./b8; ./b8
