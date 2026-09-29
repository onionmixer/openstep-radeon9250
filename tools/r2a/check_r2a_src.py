#!/usr/bin/env python3
"""Source and host-object rules for the R2a probe (docs/R1C_R2A_IMPL_PLAN.md section 2-6 items 4-8).

  check_r2a_src.py <workdir>     compile the host objects into <workdir>, run
                                 every rule on the real files, then every
                                 mutation (each must be caught by the rule it
                                 targets, in this run); exit 1 on any failure

Source rules (comments and string literals blanked first):
  probe-volatile     RDNR2aProbe.m has no `volatile'
  probe-cast         ... no pointer cast `*)'
  probe-longlong     ... no `long long'
  w8-sites           rdnMmioWrite8 called at exactly 2 sites, both in pllGroup,
                     offset REG_CLOCK_CNTL_INDEX, value masked with
                     PLL_INDEX_MASK or LOW_BYTE
  w32-sites          rdnMmioWrite32 called once, in pllGroup, offset
                     REG_CLOCK_CNTL_INDEX, value `p' -- the variable assigned
                     from the group's first index read after splhigh
  spl-pair           splhigh and splx once each, in pllGroup, in that order;
                     between them no call but the three helpers
  constants          REG_CLOCK_CNTL_INDEX 0x0008, REG_CLOCK_CNTL_DATA 0x000c,
                     PLL_WR_EN 0x80, PLL_INDEX_MASK 0x3f, LOW_BYTE 0xff,
                     PCI_CFG_ADDR 0x0CF8, PCI_CFG_DATA 0x0CFC, MMIO_MAP_LENGTH 0x2000
  ports              no inb/inw/outb/outw; outl only in pciRead, port PCI_CFG_ADDR;
                     no VGA port constant 0x3b0-0x3df
  map-length         IOMapPhysicalIntoIOTask/IOUnmapPhysicalFromIOTask only with
                     MMIO_MAP_LENGTH
  long-width         no field width with the long modifier (kernel sprintf)
  cc-names           no identifier id/in/out (cc 2.7.2.1 cast or macro)
  helpers-only       RDNR2aMMIO.m defines exactly the three helpers, no static,
                     no inline, one statement each
  no-lto             no -flto in the tproj makefiles or the target build script
Object rules (gcc-12 -m32 against the target headers):
  helper-width       RDNR2aMMIO.o at -O0 and -O2: rdnMmioWrite8 one 8-bit
                     non-stack store, rdnMmioWrite32 one 32-bit, rdnMmioRead32
                     none (a store is non-stack when its base is not %esp/%ebp)
  obj-out            RDNR2aProbe.o at -O0 -fno-inline: `out' instructions only
                     in outb/outw/outl, outl called only from pciRead after
                     push $0xcf8
  obj-calls          relocations: rdnMmioWrite8 2, rdnMmioWrite32 1, splhigh 1,
                     splx 1, all in pllGroup; between the splhigh and splx
                     calls only helper calls
  obj-stores         every non-stack store outside the helpers has a base
                     derived from a relocated static address or from a
                     parameter the source declares as a pointer.  (The plan's
                     "no store outside the helpers" does not hold: the probe
                     stores into r2aPllRead, r2aBridges and scanPci's
                     out-parameters.  An MMIO store would have to go through
                     the vm_address_t base, which is neither.)
"""

import importlib.util
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
WS = os.path.dirname(PROJ)
TPROJ = os.path.join(PROJ, 'probe', 'RDNR2aProbe', 'RDNR2aProbe_reloc.tproj')
PROBE = os.path.join(TPROJ, 'RDNR2aProbe.m')
MMIO = os.path.join(TPROJ, 'RDNR2aMMIO.m')
R = os.path.join(WS, 'ref', 'openstep', 'headers', 'NextDeveloper', 'Headers')
HOSTSHIM = os.path.join(PROJ, 'tools', 'host', 'hostshim')
TARGET_BUILD = os.path.join(HERE, 'target-build.sh')


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


st = _load('stores', os.path.join(HERE, 'stores.py'))

HELPERS = ('rdnMmioRead32', 'rdnMmioWrite8', 'rdnMmioWrite32')


# ---- source ------------------------------------------------------------------

def blank(src, strings=True):
    def b(m):
        return re.sub(r'[^\n]', ' ', m.group(0))
    pat = r'/\*.*?\*/|//[^\n]*'
    if strings:
        pat += r'|"(\\.|[^"\\\n])*"|\'(\\.|[^\'\\\n])*\''
    return re.sub(pat, b, src, flags=re.S)


def function_bodies(code):
    """{name: (start, end, params text)} for top-level definitions
    `name(params)\\n{ ... \\n}'."""
    out = {}
    for m in re.finditer(r'^([A-Za-z_]\w*)\(([^)]*)\)\s*\n\{', code, re.M):
        end = code.find('\n}', m.end())
        out[m.group(1)] = (m.start(), end if end > 0 else len(code), m.group(2))
    return out


def calls(code, name):
    """[(position, argument text)] for each call of name."""
    res = []
    for m in re.finditer(r'\b%s\s*\(' % re.escape(name), code):
        depth, i = 1, m.end()
        while i < len(code) and depth:
            depth += {'(': 1, ')': -1}.get(code[i], 0)
            i += 1
        res.append((m.start(), code[m.end():i - 1]))
    return res


def args(text):
    return [a.strip() for a in st.split_operands(text)]


def within(pos, body):
    return body is not None and body[0] <= pos < body[1]


def source_rules(probe_src, mmio_src, makefiles, build_script):
    """Return {rule: [problems]} (empty list = pass)."""
    code = blank(probe_src)
    bodies = function_bodies(code)
    pg = bodies.get('pllGroup')
    r = {}

    r['probe-volatile'] = ['volatile at %d' % m.start() for m in re.finditer(r'\bvolatile\b', code)]
    r['probe-cast'] = ['pointer cast at line %d' % (code[:m.start()].count('\n') + 1)
                       for m in re.finditer(r'\*\s*\)', code)]
    r['probe-longlong'] = ['long long at %d' % m.start() for m in re.finditer(r'\blong\s+long\b', code)]

    p = []
    w8 = calls(code, 'rdnMmioWrite8')
    if len(w8) != 2:
        p.append('%d rdnMmioWrite8 call sites, want 2' % len(w8))
    for pos, a in w8:
        a = args(a)
        if not within(pos, pg):
            p.append('rdnMmioWrite8 outside pllGroup')
        if len(a) != 3 or a[1] != 'REG_CLOCK_CNTL_INDEX' or not re.search(r'&\s*(PLL_INDEX_MASK|LOW_BYTE)\s*\)*$', a[2]):
            p.append('rdnMmioWrite8 arguments %s' % a)
    r['w8-sites'] = p

    p = []
    w32 = calls(code, 'rdnMmioWrite32')
    if len(w32) != 1:
        p.append('%d rdnMmioWrite32 call sites, want 1' % len(w32))
    for pos, a in w32:
        a = args(a)
        if not within(pos, pg):
            p.append('rdnMmioWrite32 outside pllGroup')
        if a[1:] != ['REG_CLOCK_CNTL_INDEX', 'p']:
            p.append('rdnMmioWrite32 arguments %s' % a)
    if pg:
        body = code[pg[0]:pg[1]]
        sh = body.find('splhigh(')
        first = re.search(r'\b(\w+)\s*=\s*rdnMmioRead32\s*\(\s*base\s*,\s*REG_CLOCK_CNTL_INDEX\s*\)', body[sh:]) if sh >= 0 else None
        if not first or first.group(1) != 'p':
            p.append('first index read after splhigh is not assigned to p')
        assigns = re.findall(r'(?<![.>\w])p\s*=[^=]', body)
        if len(assigns) != 1:
            p.append('p assigned %d times in pllGroup' % len(assigns))
    r['w32-sites'] = p

    p = []
    sh, sx = calls(code, 'splhigh'), calls(code, 'splx')
    if len(sh) != 1 or len(sx) != 1:
        p.append('splhigh %d, splx %d call sites, want 1 each' % (len(sh), len(sx)))
    elif not (within(sh[0][0], pg) and within(sx[0][0], pg) and sh[0][0] < sx[0][0]):
        p.append('splhigh/splx not a pair in pllGroup')
    else:
        between = code[sh[0][0] + len('splhigh('):sx[0][0]]
        for m in re.finditer(r'\b([A-Za-z_]\w*)\s*\(', between):
            if m.group(1) not in HELPERS + ('if', 'while', 'for'):
                p.append('call of %s between splhigh and splx' % m.group(1))
        for m in re.finditer(r'\b(for|while|goto|return)\b', between):
            p.append('%s between splhigh and splx' % m.group(1))
    r['spl-pair'] = p

    p = []
    want = {'REG_CLOCK_CNTL_INDEX': 0x8, 'REG_CLOCK_CNTL_DATA': 0xc, 'PLL_WR_EN': 0x80, 'PLL_INDEX_MASK': 0x3f,
            'LOW_BYTE': 0xff, 'PCI_CFG_ADDR': 0xcf8, 'PCI_CFG_DATA': 0xcfc, 'MMIO_MAP_LENGTH': 0x2000}
    for n, v in want.items():
        defs = re.findall(r'^#define\s+%s\s+(0x[0-9a-fA-F]+)[uUlL]*\s*$' % n, code, re.M)
        if [int(x, 16) for x in defs] != [v]:
            p.append('%s defined as %s, want one 0x%x' % (n, defs, v))
    r['constants'] = p

    p = []
    for n in ('inb', 'inw', 'outb', 'outw'):
        if calls(code, n):
            p.append('%s called' % n)
    for pos, a in calls(code, 'outl'):
        if not within(pos, bodies.get('pciRead')) or args(a)[0] != '(IOEISAPortAddress)PCI_CFG_ADDR':
            p.append('outl(%s) outside pciRead or not to PCI_CFG_ADDR' % a)
    for m in re.finditer(r'\b0x0*3[bcdBCD][0-9a-fA-F]\b', code):
        p.append('VGA port constant %s' % m.group(0))
    r['ports'] = p

    p = []
    for n in ('IOMapPhysicalIntoIOTask', 'IOUnmapPhysicalFromIOTask'):
        cs = calls(code, n)
        if not cs:
            p.append('%s not called' % n)
        for pos, a in cs:
            if len(args(a)) < 2 or args(a)[1] != 'MMIO_MAP_LENGTH':
                p.append('%s(%s)' % (n, a))
    r['map-length'] = p

    r['long-width'] = re.findall(r'%[-+ #0]*[0-9]+l[a-zA-Z]', blank(probe_src, strings=False))
    r['cc-names'] = ['line %d' % (code[:m.start()].count('\n') + 1)
                     for m in re.finditer(r'(?<![A-Za-z0-9_.])(id|in|out)(?![A-Za-z0-9_])', code)]

    p = []
    mcode = blank(mmio_src)
    mb = function_bodies(mcode)
    if sorted(mb) != sorted(HELPERS):
        p.append('RDNR2aMMIO.m defines %s' % sorted(mb))
    if re.search(r'\b(static|inline|__inline__)\b', mcode):
        p.append('static or inline in RDNR2aMMIO.m')
    for n, (a, b, _) in mb.items():
        stmts = mcode[a:b].split('{', 1)[1].count(';')
        if stmts != 1:
            p.append('%s has %d statements' % (n, stmts))
    r['helpers-only'] = p

    r['no-lto'] = ['-flto in %s' % n for n, t in list(makefiles.items()) + [('target-build.sh', build_script)]
                   if '-flto' in t]
    return r


# ---- objects -----------------------------------------------------------------

def compile_obj(src, out, opt, extra=()):
    cmd = ['gcc-12', '-m32', '-nostdinc', '-fno-pic', '-ffreestanding', '-fno-builtin', '-I', TPROJ, '-I', HOSTSHIM,
           '-isystem', R, '-isystem', R + '/ansi', '-isystem', R + '/bsd', '-isystem', R + '/mach',
           '-isystem', R + '/kernserv', '-isystem', R + '/architecture',
           '-DKERNEL', '-DMACH_USER_API', '-DMACH', '-DNeXT=1', '-D__NeXT__', '-D_NEXT_SOURCE', '-Di386',
           '-D__ARCHITECTURE__="i386"', '-x', 'objective-c', '-fnext-runtime', '-w'] + list(opt) + list(extra) + \
          ['-c', src, '-o', out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0, r.stderr


def disasm(obj):
    return subprocess.run(['objdump', '-dr', '--no-show-raw-insn', obj], capture_output=True, text=True).stdout


def helper_widths(dis):
    """{helper: [(width, base)] non-stack stores}, plus all-base counts."""
    f = st.functions(dis)
    res = {}
    for h in HELPERS:
        ins = f.get(h)
        if ins is None:
            res[h] = None
            continue
        allst = [st.classify(i) for _, i, _ in ins]
        allst = [c for c in allst if c]
        res[h] = ([c for c in allst if not st.is_stack(c[1])], allst)
    return res


def helper_rule(dis):
    p = []
    want = {'rdnMmioRead32': [], 'rdnMmioWrite8': [8], 'rdnMmioWrite32': [32]}
    for h, v in helper_widths(dis).items():
        if v is None:
            p.append('%s missing' % h)
            continue
        widths = [w for w, _ in v[0]]
        if widths != want[h]:
            p.append('%s non-stack store widths %s, want %s (all stores %s)' % (h, widths, want[h], v[1]))
    return p


def object_rules(dis, probe_src):
    """Return {rule: [problems]} for RDNR2aProbe.o built -O0 -fno-inline."""
    f = st.functions(dis)
    r = {'obj-out': [], 'obj-calls': [], 'obj-stores': []}
    outcalls = 0
    for fn, ins in f.items():
        prev = ''
        for _, i, rel in ins:
            if re.match(r'out[bwl]?\s', i) and fn not in ('outb', 'outw', 'outl'):
                r['obj-out'].append('out instruction in %s' % fn)
            m = re.match(r'call\s+\S+\s+<(out[bwl])>', i)
            if m:
                outcalls += 1
                if fn != 'pciRead' or m.group(1) != 'outl' or not re.match(r'push\s+\$0xcf8$', prev):
                    r['obj-out'].append('%s called from %s after %r' % (m.group(1), fn, prev))
            prev = i
    if outcalls == 0:
        r['obj-out'].append('no out helper call at all -- the check saw nothing')

    counts = {}
    order = []
    for fn, ins in f.items():
        for addr, i, rel in ins:
            for typ, sym in rel:
                if typ == 'R_386_PC32' and i.startswith('call'):
                    counts[(fn, sym)] = counts.get((fn, sym), 0) + 1
                    if fn == 'pllGroup':
                        order.append(sym)
    want = {'rdnMmioWrite8': 2, 'rdnMmioWrite32': 1, 'splhigh': 1, 'splx': 1}
    for sym, n in want.items():
        tot = sum(v for (fn, s), v in counts.items() if s == sym)
        inpg = counts.get(('pllGroup', sym), 0)
        if tot != n or inpg != n:
            r['obj-calls'].append('%s called %d times (%d in pllGroup), want %d' % (sym, tot, inpg, n))
    if 'splhigh' in order and 'splx' in order:
        between = order[order.index('splhigh') + 1:order.index('splx')]
        for s in between:
            if s not in HELPERS:
                r['obj-calls'].append('call of %s between splhigh and splx' % s)

    # parameters declared as pointers: (function, frame offset)
    pointer_params = set()
    for name, (_, _, params) in function_bodies(blank(probe_src)).items():
        if params.strip() in ('', 'void'):
            continue
        for k, prm in enumerate(params.split(',')):
            if '*' in prm:
                pointer_params.add((name, 8 + 4 * k))
    for fn, ins in f.items():
        if fn in HELPERS or fn in ('inl', 'outl', 'inw', 'outw', 'inb', 'outb'):
            continue
        prov = {}
        slots = {}
        for addr, i, rel in ins:
            has_static = any(t == 'R_386_32' and (s.startswith('.bss') or s.startswith('.data') or
                                                  s.startswith('.rodata') or s in ('r2aPllRead', 'r2aBridges'))
                             for t, s in rel)
            c = st.classify(i)
            if c and not st.is_stack(c[1]):
                ok = (c[1] is None and has_static) or prov.get(c[1], ('?',))[0] in ('static', 'ptrparam')
                if not ok:
                    r['obj-stores'].append('%s+%x %s: base %s from %s' % (fn, addr, i, c[1], prov.get(c[1], ('unknown',))))
            # provenance of register definitions
            parts = i.split(None, 1)
            mn = parts[0]
            ops = st.split_operands(parts[1].split('<')[0]) if len(parts) > 1 else []
            if mn.startswith('call'):
                for reg in ('eax', 'ecx', 'edx'):
                    prov[reg] = ('call',)
                continue
            if c and c[1] == 'ebp' and len(ops) == 2 and ops[0].startswith('%'):
                m = re.match(r'(-?0x[0-9a-f]+)\(%ebp\)$', ops[1])
                if m:
                    slots[int(m.group(1), 16)] = prov.get(ops[0][1:], ('?',))
                continue
            if len(ops) == 2 and ops[1].startswith('%') and ops[1][1:] in st.REG32:
                dst = ops[1][1:]
                src = ops[0]
                if has_static and (mn in ('lea', 'add', 'mov') or mn.startswith('lea')):
                    prov[dst] = ('static',)
                elif mn in ('mov', 'movl') and re.match(r'(-?0x[0-9a-f]+)\(%ebp\)$', src):
                    off = int(re.match(r'(-?0x[0-9a-f]+)', src).group(1), 16)
                    if off > 0:
                        prov[dst] = ('ptrparam',) if (fn, off) in pointer_params else ('param', off)
                    else:
                        prov[dst] = slots.get(off, ('slot?', off))
                elif mn in ('mov', 'movl') and src.startswith('%') and src[1:] in st.REG32:
                    prov[dst] = prov.get(src[1:], ('?',))
                elif mn in ('add', 'sub', 'shl', 'imul', 'lea') and prov.get(dst, ('?',))[0] == 'static' and \
                        (src.startswith('$') or src.startswith('%')) and not has_static:
                    pass    # index arithmetic on a static address keeps it static
                else:
                    prov[dst] = ('other', mn)
            elif len(ops) == 1 and ops[0].startswith('%') and ops[0][1:] in st.REG32 and mn not in ('push', 'pushl'):
                prov[ops[0][1:]] = ('other', mn)
    return r


# ---- mutations ---------------------------------------------------------------

PG_W8 = '        rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX, (unsigned char)(index & PLL_INDEX_MASK));\n'
PG_SPLX = '    splx(s);\n'

# (label, file 'probe'|'mmio', old, new, rules that must fail)
MUTATIONS = [
    ('volatile in the probe', 'probe', '    unsigned long index;\n', '    volatile unsigned long index;\n',
     ['probe-volatile']),
    ('pointer cast store in pllGroup', 'probe', PG_SPLX,
     '    *(unsigned long *)(base + REG_CLOCK_CNTL_DATA) = 0;\n' + PG_SPLX, ['probe-cast', 'obj-stores']),
    ('long long in the probe', 'probe', '    unsigned long index;\n', '    unsigned long index;\n    long long wide;\n',
     ['probe-longlong']),
    ('third rdnMmioWrite8 site', 'probe', PG_W8, PG_W8 + PG_W8, ['w8-sites', 'obj-calls']),
    ('rdnMmioWrite8 value unmasked', 'probe', PG_W8,
     '        rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX, (unsigned char)index);\n', ['w8-sites']),
    ('rdnMmioWrite8 to the data register', 'probe', PG_W8,
     PG_W8.replace('REG_CLOCK_CNTL_INDEX', 'REG_CLOCK_CNTL_DATA'), ['w8-sites']),
    ('rdnMmioWrite32 writes c', 'probe', '            rdnMmioWrite32(base, REG_CLOCK_CNTL_INDEX, p);\n',
     '            rdnMmioWrite32(base, REG_CLOCK_CNTL_INDEX, c);\n', ['w32-sites']),
    ('second rdnMmioWrite32 outside pllGroup', 'probe', '    (void)pllSnapshot(base);\n',
     '    rdnMmioWrite32(base, REG_CLOCK_CNTL_INDEX, 0);\n    (void)pllSnapshot(base);\n', ['w32-sites', 'obj-calls']),
    ('p re-assigned', 'probe', '    splx(s);\n\n    r2aPllRead[k].p = p;\n',
     '    p = c;\n    splx(s);\n\n    r2aPllRead[k].p = p;\n', ['w32-sites']),
    ('IOSleep between splhigh and splx', 'probe', PG_W8, PG_W8 + '        IOSleep(1);\n', ['spl-pair', 'obj-calls']),
    ('IOLog between splhigh and splx', 'probe', PG_W8, PG_W8 + '        IOLog("x");\n', ['spl-pair', 'obj-calls']),
    ('splx before the group', 'probe', '    s = splhigh();\n', '    s = splhigh();\n    splx(s);\n',
     ['spl-pair', 'obj-calls']),
    ('index mask widened', 'probe', '#define PLL_INDEX_MASK      0x3f', '#define PLL_INDEX_MASK      0x7f', ['constants']),
    ('map length grown', 'probe', '#define MMIO_MAP_LENGTH     0x2000', '#define MMIO_MAP_LENGTH     0x4000',
     ['constants']),
    ('VGA sequencer write', 'probe', '    outl((IOEISAPortAddress)PCI_CFG_ADDR, address);\n',
     '    outl((IOEISAPortAddress)PCI_CFG_ADDR, address);\n    outb((IOEISAPortAddress)0x3c4, 1);\n',
     ['ports', 'obj-out']),
    ('outl to the data port', 'probe', '    outl((IOEISAPortAddress)PCI_CFG_ADDR, address);\n',
     '    outl((IOEISAPortAddress)PCI_CFG_DATA, address);\n', ['ports', 'obj-out']),
    ('map with a literal length', 'probe', 'IOMapPhysicalIntoIOTask((unsigned)start, MMIO_MAP_LENGTH, &base)',
     'IOMapPhysicalIntoIOTask((unsigned)start, 0x2000, &base)', ['map-length']),
    ('long hex with a width', 'probe', 'val=%08x", r2aRegs[i].name, r2aRegs[i].offset, U(regVal[i]));',
     'val=%08lx", r2aRegs[i].name, r2aRegs[i].offset, regVal[i]);', ['long-width']),
    ('identifier out', 'probe', '    unsigned long index;\n', '    unsigned long index;\n    int out;\n', ['cc-names']),
    ('fourth helper', 'mmio', '\nvoid\nrdnMmioWrite32(',
     '\nvoid\nrdnMmioPoke(vm_address_t base)\n{\n    *(volatile unsigned char *)base = 0;\n}\n\nvoid\nrdnMmioWrite32(',
     ['helpers-only']),
    ('inline helper', 'mmio', '\nvoid\nrdnMmioWrite8(', '\n__inline__ void\nrdnMmioWrite8(', ['helpers-only']),
    ('Write8 stores 32 bits', 'mmio', '    *(volatile unsigned char *)(base + offset) = value;\n',
     '    *(volatile unsigned long *)(base + offset) = value;\n', ['helper-width-O0', 'helper-width-O2']),
    ('Read32 also stores', 'mmio', '    return *(volatile unsigned long *)(base + offset);\n',
     '    return *(volatile unsigned long *)(base + offset) = 0;\n', ['helper-width-O0', 'helper-width-O2']),
]


def all_rules(work, tag, probe_src, mmio_src, makefiles, build_script):
    pp = os.path.join(work, tag + '.m')
    mp = os.path.join(work, 'RDNR2aMMIO.m')
    open(pp, 'w').write(probe_src)
    mdir = os.path.join(work, tag + '-mmio')
    os.makedirs(mdir, exist_ok=True)
    mp = os.path.join(mdir, 'RDNR2aMMIO.m')
    open(mp, 'w').write(mmio_src)
    res = source_rules(probe_src, mmio_src, makefiles, build_script)
    ok, err = compile_obj(pp, os.path.join(work, tag + '.o'), ['-O0', '-fno-inline'], ['-DR2A_BUILD=0x1234abcd'])
    if ok:
        res.update(object_rules(disasm(os.path.join(work, tag + '.o')), probe_src))
    else:
        res['compile-probe'] = [err.strip()[:300]]
    for opt in ('O0', 'O2'):
        ok, err = compile_obj(mp, os.path.join(work, '%s-mmio-%s.o' % (tag, opt)), ['-' + opt])
        res['helper-width-' + opt] = helper_rule(disasm(os.path.join(work, '%s-mmio-%s.o' % (tag, opt)))) if ok \
            else ['compile: ' + err.strip()[:200]]
    return res


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    work = argv[1]
    os.makedirs(work, exist_ok=True)
    probe_src = open(PROBE).read()
    mmio_src = open(MMIO).read()
    makefiles = dict((n, open(os.path.join(TPROJ, n)).read()) for n in os.listdir(TPROJ) if n.startswith('Makefile'))
    makefiles.update(dict(('../' + n, open(os.path.join(TPROJ, '..', n)).read())
                          for n in os.listdir(os.path.join(TPROJ, '..')) if n.startswith('Makefile')))
    build_script = open(TARGET_BUILD).read() if os.path.exists(TARGET_BUILD) else ''
    failures = 0
    base = all_rules(work, 'base', probe_src, mmio_src, makefiles, build_script)
    print('== rules on the real files ==')
    for rule in sorted(base):
        ok = not base[rule]
        print('  %-4s %-18s %s' % ('ok' if ok else 'FAIL', rule, '' if ok else '; '.join(map(str, base[rule]))[:300]))
        failures += 0 if ok else 1
    if not os.path.exists(TARGET_BUILD):
        print('  FAIL no-lto: target-build.sh not found')
        failures += 1
    print('== mutations (each caught by the rules it targets) ==')
    for label, which, old, new, want in MUTATIONS:
        src = probe_src if which == 'probe' else mmio_src
        if src.count(old) != 1:
            print('  FAIL %-40s anchor found %d times' % (label, src.count(old)))
            failures += 1
            continue
        ms = src.replace(old, new)
        res = all_rules(work, 'mut', ms if which == 'probe' else probe_src, ms if which == 'mmio' else mmio_src,
                        makefiles, build_script)
        caught = [w for w in want if res.get(w)]
        compile_fail = [k for k in res if k.startswith('compile') and res[k]] + \
                       [k for k in ('helper-width-O0', 'helper-width-O2') if any('compile' in x for x in res.get(k, []))]
        ok = len(caught) == len(want) and not compile_fail
        print('  %-4s %-40s caught by %s%s' % ('ok' if ok else 'FAIL', label, caught or 'nothing',
                                              '' if not compile_fail else ' (did not compile: %s)' % compile_fail))
        failures += 0 if ok else 1
    lto = dict(makefiles)
    lto['Makefile.preamble'] = lto.get('Makefile.preamble', '') + '\nOTHER_CFLAGS += -flto\n'
    ok = bool(source_rules(probe_src, mmio_src, lto, build_script)['no-lto'])
    print('  %-4s %-40s caught by %s' % ('ok' if ok else 'FAIL', '-flto in a makefile', ['no-lto'] if ok else 'nothing'))
    failures += 0 if ok else 1
    print('check_r2a_src: %s' % ('PASS' if failures == 0 else 'FAIL (%d)' % failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
