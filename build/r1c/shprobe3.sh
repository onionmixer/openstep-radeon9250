D=/tmp/shprobe3.d
rm -rf $D
mkdir $D
echo '"Active Drivers" = "Pro1000 EMU10K1 VGA";' > $D/cfg
n=`grep '"Active Drivers"' $D/cfg | egrep -c 'MGA|Matrox'`
echo "1 egrep -c none: $n"
n=`grep '"Active Drivers"' $D/cfg | grep -c 'VGA'`
echo "2 grep -c VGA: $n"
fin() { echo "fin: $1"; case "$1" in *" DONE"*) echo "  case DONE"; return 0 ;; esac; echo "  case other"; return 1; }
mkdir $D/claim 2> /dev/null || fin "3 first mkdir failed"
mkdir $D/claim 2> /dev/null || fin "3 second mkdir refused (expected)"
fin "4 X DONE y"
sh -c 'exit 3' > $D/line 2>&1
st=$?
echo "5 status: $st"
echo abcdef > $D/w
size=`wc -c < $D/w | sed 's/ //g'`
echo "6 wc: $size"
cs=`echo "123 4 file" | awk '{print $1 " " $2}'`
echo "7 awk: $cs"
if [ "$cs" != "123 4" ]; then echo "8 compare: differ"; else echo "8 compare: same"; fi
ex() { echo "9 exit inside function"; exit 7; }
ex
echo "10 NOT REACHED"
