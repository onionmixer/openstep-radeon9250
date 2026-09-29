echo "start"
A=${SHPROBE_UNSET_A:-/tmp}
echo "1 simple default: $A"
B=${SHPROBE_UNSET_B:-/x/a /x/b}
echo "2 default with blank: $B"
C="${SHPROBE_UNSET_C:-/x/a /x/b}"
echo "3 quoted default with blank: $C"
case "abc1" in ""|*[!0-9a-z]*) echo "4 case: bad" ;; *) echo "4 case: ok" ;; esac
if [ "600" -lt 512 ] || [ "600" -gt 65536 ]; then echo "5 test: range"; else echo "5 test: ok"; fi
r=`expr 1024 % 512`
echo "6 expr: $r"
f() { echo "7 function: $1"; }
f arg
echo hello > /tmp/shprobe-wc.txt
n=`wc -c < /tmp/shprobe-wc.txt | sed 's/ //g'`
echo "8 wc: $n"
echo "end"
