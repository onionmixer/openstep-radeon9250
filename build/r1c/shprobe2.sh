f() { echo "in f: $1"; }
set -- A B
f X
echo "after f: 1=$1 2=$2"
g=`echo "11 22 file" | awk '{print $1 " " $2}'`
echo "awk: $g"
