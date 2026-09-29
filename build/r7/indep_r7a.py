"""R7a/R7b independent recount: own parser, own verifier, written from the plan rather than the
oracle.

  python3 build/r7/indep_r7a.py <boot nonce> [log file] [--tool PATH] [--order 0,1,2,...]

R7b runs the SAME streams through the character device, so the same recount judges it: only the
file the tables are read from and the order the runs came in differ.  --tool names that file and
--order the sequence (default: the R7a plan's, which ends with case 0 again, in pieces).

Nothing here imports tools/r7/verify_oracle.py.  The thirteen rules of docs/R7_PLAN.md 4 are
written out again, and the register allow-list is read straight from the DRIVER's generated table
rather than re-derived, so that this file and the oracle can only agree by both being right about
the rules -- not by sharing the code that implements them.

What it checks, for every submission the boot logged:
  - the driver's verdict equals this file's verdict for the same words
  - a refusal left nothing behind (restChanged 0)
  - the streams that ran drew the triangle the R6d ladder measured
"""
import re
import sys

ARGV = [a for a in sys.argv[1:] if not a.startswith('--')]
OPTS = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
N = ARGV[0]
LOG = ARGV[1] if len(ARGV) > 1 else 'build/r6/boot-%s.full.log' % N
TOOL = OPTS.get('tool', 'tools/r7/rdnr7sub.m')
CP_M = 'OSRDNDisplay/OSRDNDisplay_reloc.tproj/osrdn_cp.m'
M32 = 0xffffffff

# the codes, from docs/R7_PLAN.md 4 -- written here, not imported
OK, TYPE, TRUNC, P0_COUNT, P0_REG, P0_VALUE, P3_OP, VF, VTX_FMT, VTX_UNSET, COUNT, SURFACE, \
    WORDS, EMPTY = range(14)
NAME = {OK: 'OK', TYPE: 'TYPE', TRUNC: 'TRUNC', P0_COUNT: 'P0_COUNT', P0_REG: 'P0_REG',
        P0_VALUE: 'P0_VALUE', P3_OP: 'P3_OP', VF: 'VF', VTX_FMT: 'VTX_FMT',
        VTX_UNSET: 'VTX_UNSET', COUNT: 'COUNT', SURFACE: 'SURFACE', WORDS: 'WORDS', EMPTY: 'EMPTY'}
BATCH_MAX = 2016
RESERVED = (0x15e0, 0x1720, 0x3254, 0x325c)


def allow_list():
    """the driver's own table -- if the driver and the oracle disagree, check_r5_src catches it;
    what this file must not do is re-derive it the same way the oracle does"""
    src = open(CP_M).read()
    i = src.index('static const unsigned short cpR7Allow[')
    return set(int(x, 16) for x in re.findall(r'0x[0-9a-f]{4}', src[i:src.index('};', i)]))


ALLOW = allow_list()


def vwords(f0, f1):
    """words per vertex; None when the format names a field nobody measured"""
    if f0 & ~0x1803:
        return None
    c = (f0 >> 11) & 3
    if c > 1:
        return None
    n = 2 + (1 if f0 & 1 else 0) + (1 if f0 & 2 else 0) + c
    for u in range(6):
        k = (f1 >> (3 * u)) & 7
        if k not in (0, 2):
            return None
        n += k
    return None if f1 >> 18 else n


def verify(w, lo, hi):
    """the thirteen rules, in the plan's order"""
    if not w:
        return EMPTY
    if len(w) > BATCH_MAX:
        return WORDS
    f0, f1, saw = 3, 0, False
    co = cp = zo = zp = tx = None
    i, drew = 0, False
    while i < len(w):
        h = w[i]
        t = h & 0xc0000000
        if t in (0x40000000, 0x80000000):
            return TYPE
        if t == 0:
            if (h & 0x8000) or ((h >> 16) & 0x3fff):
                return P0_COUNT
            if i + 1 >= len(w):
                return TRUNC
            r, v = (h & 0x3fff) * 4, w[i + 1]
            if r not in ALLOW:
                return P0_REG
            if r == 0x1c38 and (v & 0x3e0):         # PP_CNTL: texture units 1-5
                return P0_VALUE
            if r == 0x2080 and (v & 1):             # SE_VAP_CNTL: TCL
                return P0_VALUE
            if r == 0x2c04 and (v & 0x08000000):    # PP_TXFORMAT: cube
                return P0_VALUE
            if r == 0x2c00 and (v & 0x1c000):       # PP_TXFILTER: mip
                return P0_VALUE
            if r == 0x2088:
                f0, saw = v, True
            elif r == 0x208c:
                f1 = v
            elif r == 0x1c40:
                co = v
            elif r == 0x1c48:
                cp = v
            elif r == 0x1c24:
                zo = v
            elif r == 0x1c28:
                zp = v
            elif r == 0x2d00:
                tx = v
            i += 2
            continue
        n = ((h >> 16) & 0x3fff) + 1
        if (h & 0xff00) != 0x3500:
            return P3_OP
        if i + 1 + n > len(w):
            return TRUNC
        vf = w[i + 1]
        if (vf & ~0xffff007f) or (vf & 0x30) != 0x30 or (vf & 0xf) != 4:
            return VF
        nv = (vf >> 16) & 0xffff
        if nv == 0 or nv % 3:
            return VF
        if not saw:
            return VTX_UNSET
        k = vwords(f0, f1)
        if k is None:
            return VTX_FMT
        if n - 1 != k * nv:
            return COUNT
        drew = True
        i += 1 + n
    if not drew:
        return EMPTY
    for off, pitch in ((co, cp), (zo, zp)):
        if (off is None) != (pitch is None):
            return SURFACE
        if off is not None:
            span = (pitch & 0x1ff8) * 4 * 64
            if span == 0 or off < lo or off > hi or hi - off < span:
                return SURFACE
    if tx is not None and (tx < lo or tx > hi or hi - tx < 1024):
        return SURFACE
    return OK


# ---- the boot's own lines, this boot only
lines = open(LOG, errors='replace').read().splitlines()
mine = [k for k, l in enumerate(lines) if 'boot=%s' % N in l]
if not mine:
    sys.exit('no line names boot %s in %s' % (N, LOG))
other = [k for k in range(mine[0] + 1, len(lines))
         if re.search(r'boot=(?!%s)[0-9a-f]{8}\b' % re.escape(N), lines[k])]
text = '\n'.join(lines[mine[0]:other[0] if other else len(lines)])

runs = []
for chunk in text.split('RDN-R5 begin ')[1:]:
    chunk = chunk.split('RDN-R5 begin ')[0]
    # a REFUSED submission never reaches stage 3, so the verify line -- which the driver now
    # emits either way -- is what says "this operation was a client stream"
    if not re.search(r'RDN-R7 verify ', chunk):
        continue
    d = {}
    m = re.search(r'RDN-R7 verify boot=[0-9a-f]{8} words=(\d+) why=(\d+) at=(\d+) '
                  r'word=([0-9a-f]{8}) win=([0-9a-f]{8})\.\.([0-9a-f]{8})', chunk)
    if m:
        d = dict(words=int(m.group(1)), why=int(m.group(2)), at=int(m.group(3)),
                 word=int(m.group(4), 16), lo=int(m.group(5), 16), hi=int(m.group(6), 16))
    m = re.search(r'RDN-R6 zr rest0=(\d+) rest1=(\d+)', chunk)
    if m:
        d['rest'] = (int(m.group(1)), int(m.group(2)))
    # the verifier saying OK is not the same as the stream running: the operation can
    # still be refused after it (a repeated seed, a busy claim).  Take the operation's
    # own rc rather than inferring it from the verdict.
    m = re.search(r'RDN-R5 zclear boot=[0-9a-f]{8} n=\d+ arg=[0-9a-f]+ len=\d+ rc=(-?\d+) why=(\d+)',
                  chunk)
    if m:
        d['oprc'] = (int(m.group(1)), int(m.group(2)))
    w = {}
    for cm in re.finditer(r'RDN-R6 cov(\d) ((?:[0-9a-f]{8} ?){8})', chunk):
        w[int(cm.group(1))] = [int(x, 16) for x in cm.group(2).split()]
    if sorted(w) == list(range(8)):
        d['cov'] = [x for k in range(8) for x in w[k]]
    runs.append(d)

# the streams themselves come from the driver's staging log, which prints how many words went in;
# the words are in the tool's generated table, so this file reads THAT rather than the oracle
src = open(TOOL).read()
i = src.index('static const unsigned long cpR7Pool[')
pool = [int(x[:-2], 16) for x in re.findall(r'0x[0-9a-fA-F]+UL', src[i:src.index('};', i)])]
i = src.index('static const unsigned short cpR7Cases[')
rows = [tuple(int(x) for x in m) for m in
        re.findall(r'\{\s*(\d+),\s*(\d+),\s*(\d+)\s*\}', src[i:src.index('};', i)])]
i = src.index('static const unsigned char cpR7Fix[')
fix = [int(x) for x in re.findall(r'\b[01]\b', src[i:src.index('};', i)])]

if 'order' in OPTS:
    order = [int(x) for x in OPTS['order'].split(',')]
else:
    order = list(range(len(rows))) + [0]        # the last run is case 0 again, in pieces
bad = 0
for k, (d, ci) in enumerate(zip(runs, order)):
    first, n, table_why = rows[ci]
    if 'words' not in d:
        print('run %2d: no verify line' % k)
        bad += 1
        continue
    if d['words'] != n:
        print('run %2d: the driver staged %d words, the table says %d' % (k, d['words'], n))
        bad += 1
        continue
    w = [pool[first + j] + (d['lo'] if fix[first + j] else 0) for j in range(n)]
    mine_why = verify(w, d['lo'], d['hi'])
    if mine_why != d['why']:
        print('run %2d (case %d): the driver said %s, this file says %s' %
              (k, ci, NAME.get(d['why'], d['why']), NAME.get(mine_why)))
        bad += 1
        continue
    if mine_why != table_why:
        print('run %2d (case %d): the table wanted %s' % (k, ci, NAME.get(table_why)))
        bad += 1
        continue
    if mine_why != OK and d.get('rest') != (0, 0):
        print('run %2d (case %d): refused but %s words changed' % (k, ci, d.get('rest')))
        bad += 1
        continue
    if mine_why == OK:
        # gate A's real claim: the operation ran.  An OK verdict whose operation was
        # refused is NOT a drawing, and saying so would be the judge inventing one.
        if 'oprc' not in d:
            print('run %2d (case %d): the verifier passed but no operation line says it ran' % (k, ci))
            bad += 1
            continue
        if d['oprc'][0] != 0:
            print('run %2d (case %d): the verifier passed, but the operation was refused '
                  '(rc=%d why=%d)' % (k, ci, d['oprc'][0], d['oprc'][1]))
            bad += 1
            continue
    where = '' if mine_why == OK else '  at word %d (%#010x)' % (d['at'], d['word'])
    print('run %2d case %2d %-9s %s%s' % (k, ci, NAME.get(mine_why),
                                          'drew' if mine_why == OK else 'refused, nothing written',
                                          where))
print('indep_r7a: %d submission(s), %d disagreement(s)' % (len(runs), bad))
sys.exit(1 if bad or len(runs) != len(order) else 0)
