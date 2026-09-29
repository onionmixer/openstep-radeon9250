#!/usr/bin/env python3
"""Pin the R4c character-device invariants in the source text
(docs/R4C_VMAP_PLAN.md 6-2, 11-1 to 11-3, 11-7).

  check_r4c_src.py           run every rule on the real files, then every mutation

Every rule carries at least one mutation, and each mutation must be caught by
the rule it targets in this same run.

  r4c-dmmap-pure     the d_mmap switch function is one call of osrdn_vmap_pfn on
                     the fixed window -- nothing it could read may change (the
                     kernel asks twice and trusts the second answer, plan 1 F3)
  r4c-vmap-pure      osrdn_vmap_pfn and osrdn_vmap_fix call nothing; the unit
                     imports no system header
  r4c-write-once     the window is stored only by osrdn_vmap_fix, which sets
                     `fixed` last; OSRDNDisplay.m never stores into it and fixes
                     it once, in -registerVmap
  r4c-selftest       each self-test case asks osrdn_vmap_pfn twice and compares
  r4c-register-last  -registerVmap is the last thing init does before
                     `return self` (a slot outlives an init that fails after it)
  r4c-gates          in -registerVmap: record key, MMIO, window, bridge, VRAM
                     reach, fix, self-test, then the cdevsw registration, and the
                     state turns ON only after it succeeded; d_open refuses unless ON
  r4c-minor          the minor is (dev & 0xFF), never the whole dev nor dev >> 8
  r4c-tables         both bundle tables turn the key on and fix "Character Major"
                     to 38 -- a slot empty in the kernel's static cdevsw with no
                     /dev node; the automatic major is 1, where /dev/pp0 is 0666
                     (docs/R4C_VMAP_PLAN.md 14)
  r4c-engine-cases   engCases is indexed only in engCaseFor (UBLIT's arg is a seed)
  r4c-seed           the UBLIT seed is refused (bad or reused) before the gate reads
                     anything, and lastSeed is recorded before the preparation
  r4c-unload         the registration log and Unload_Commands.sect say the driver
                     must not be unloaded
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_r4_src import blank, bodies, method  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
TPROJ = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj')
BUNDLE = os.path.join(PROJ, 'OSRDNDisplay')
FILES = {'OSRDNDisplay.m': TPROJ, 'osrdn_vmap.m': TPROJ, 'osrdn_engine.m': TPROJ,
         'Unload_Commands.sect': TPROJ, 'Default.table': BUNDLE, 'Instance0.table': BUNDLE}
KEYWORDS = {'if', 'for', 'while', 'return', 'sizeof', 'switch'}


def ws(s):
    return re.sub(r'\s+', ' ', s).strip()


def calls(body):
    return [m.group(1) for m in re.finditer(r'\b([A-Za-z_]\w*)\s*\(', body) if m.group(1) not in KEYWORDS]


def rules(src):
    r = {}
    b = dict((n, blank(t)) for n, t in src.items())
    disp = b['OSRDNDisplay.m']
    dfn = bodies(disp)
    vm = b['osrdn_vmap.m']
    vfn = bodies(vm)
    eng = b['osrdn_engine.m']
    efn = bodies(eng)
    reg = method(disp, 'registerVmap')
    init = method(disp, 'initFromDeviceDescription')

    p = []
    if ws(dfn.get('rdnDevMmap', '')) != '{ return osrdn_vmap_pfn(&osrdn_vmap_window, dev, offset, prot); }':
        p.append('rdnDevMmap is not exactly one call of osrdn_vmap_pfn on the fixed window: %r'
                 % ws(dfn.get('rdnDevMmap', ''))[:120])
    if 'mmap:(IOSwitchFunc)rdnDevMmap' not in re.sub(r'\s', '', reg):
        p.append('the registration does not hand rdnDevMmap to the mmap slot')
    r['r4c-dmmap-pure'] = p

    p = []
    for fn in ('osrdn_vmap_pfn', 'osrdn_vmap_fix'):
        if fn not in vfn:
            p.append('%s is not defined' % fn)
        elif calls(vfn[fn]):
            p.append('%s calls %s' % (fn, sorted(set(calls(vfn[fn])))))
    if re.search(r'^#(?:import|include)\s*<', src['osrdn_vmap.m'], re.M):
        p.append('osrdn_vmap.m imports a system header')
    r['r4c-vmap-pure'] = p

    p = []
    # R7b: there are now TWO write-once halves -- the VRAM window and the batch
    # window -- and each is written by exactly one function, which sets its own
    # "fixed" flag LAST and touches nothing belonging to the other half.
    HALVES = {'osrdn_vmap_fix': (['start', 'end', 'bar0', 'page', 'shift'], 'fixed'),
              'osrdn_vmap_fix_batch': (['bbase', 'bphys', 'bbytes'], 'bfixed')}
    for fn, body in vfn.items():
        # any store through a pointer member, however the pointer is spelt
        if fn not in HALVES and re.search(r'->\s*\w+\s*=[^=]', body):
            p.append('%s stores into the window' % fn)
    for fn, (fields, flag) in HALVES.items():
        body = vfn.get(fn, '')
        if not body:
            p.append('%s is not defined' % fn)
            continue
        stores = [m.group(1) for m in re.finditer(r'->\s*(\w+)\s*=[^=]', body)]
        if not stores or stores[-1] != flag or stores.count(flag) != 1:
            p.append('%s does not set %s once, last: %s' % (fn, flag, stores))
        for k in stores[:-1]:
            if k not in fields:
                p.append('%s writes %s, which is not its own half' % (fn, k))
        other = HALVES['osrdn_vmap_fix_batch' if fn == 'osrdn_vmap_fix' else 'osrdn_vmap_fix']
        if other[1] in stores:
            p.append("%s writes the other half's flag" % fn)
    if re.search(r'osrdn_vmap_window\.\w+\s*=[^=]', disp):
        p.append('OSRDNDisplay.m stores into osrdn_vmap_window')
    for fn in HALVES:
        if len(re.findall(r'\b%s\s*\(' % fn, disp)) != 1 or fn not in reg:
            p.append('%s is not called exactly once, in -registerVmap' % fn)
    r['r4c-write-once'] = p

    p = []
    ask = vfn.get('vmapAsk', '')
    if len(re.findall(r'\bosrdn_vmap_pfn\s*\(', ask)) != 2 or not re.search(r'\ba != b\b', ask):
        p.append('vmapAsk does not ask twice and compare')
    st = vfn.get('osrdn_vmap_selftest', '')
    if not (re.search(r'got = osrdn_vmap_pfn\(', st) and re.search(r'got2 = osrdn_vmap_pfn\(', st)
            and 'got != got2' in st):
        p.append('the self-test walk does not ask twice and compare')
    r['r4c-selftest'] = p

    p = []
    k = init.find('[self registerVmap:')
    if k < 0:
        p.append('init does not call -registerVmap')
    else:
        tail = ws(init[init.find(';', k) + 1:])
        if tail != 'return self; }':
            p.append('something follows -registerVmap in init: %r' % tail[:80])
    if len(re.findall(r'\[self registerVmap:', disp)) != 1:
        p.append('-registerVmap is called more than once')
    r['r4c-register-last'] = p

    p = []
    order = ['rdnState.recordEnabled', 'mmioMapped', 'osrdn_fb_reach_ok(&rdnState, ceiling)',
             'osrdn_engine_vram_reach(', 'osrdn_vmap_fix(&osrdn_vmap_window, start, ceiling, rdnState.bar0',
             'osrdn_vmap_selftest(', 'addToCdevswFromDescription:', 'rdnVmapState = OSRDN_VMAP_ON']
    pos = [ws(reg).find(ws(o)) for o in order]
    if any(x < 0 for x in pos) or pos != sorted(pos):
        p.append('the gates are missing or out of order: %s' % list(zip(order, pos)))
    if len(re.findall(r'rdnVmapState = OSRDN_VMAP_ON', disp)) != 1:
        p.append('rdnVmapState turns ON other than once')
    if 'rdnVmapState != OSRDN_VMAP_ON' not in dfn.get('rdnDevOpen', ''):
        p.append('d_open does not refuse unless the state is ON')
    r['r4c-gates'] = p

    p = []
    for name, body in (('rdnDevOpen', dfn.get('rdnDevOpen', '')), ('osrdn_vmap_pfn', vfn.get('osrdn_vmap_pfn', ''))):
        if '(dev & 0xFF) != 0' not in body:
            p.append('%s does not take the minor as (dev & 0xFF)' % name)
        if re.search(r'\bdev\s*[!=]=|\bdev\s*>>|\bminor\s*\(', body):
            p.append('%s compares the whole dev or shifts it' % name)
    r['r4c-minor'] = p

    p = []
    for tb in ('Default.table', 'Instance0.table'):
        if '"RDN VRAM Mmap" = "Yes";' not in src[tb]:
            p.append('%s does not turn the key on' % tb)
        if src[tb].count('"Character Major"') != 1 or '"Character Major" = "38";' not in src[tb]:
            p.append('%s does not fix "Character Major" to 38' % tb)
    r['r4c-tables'] = p

    p = []
    case_for = efn.get('engCaseFor', '')
    n_all = len(re.findall(r'\bengCases\s*\[', eng))
    n_def = len(re.findall(r'engCases\s*\[\s*ENG_BLIT_CASES\s*\]', eng))
    n_in = len(re.findall(r'\bengCases\s*\[', case_for))
    if n_all != n_def + n_in or n_in == 0:
        p.append('engCases is indexed outside engCaseFor (%d uses, %d in engCaseFor)' % (n_all - n_def, n_in))
    r['r4c-engine-cases'] = p

    p = []
    run = efn.get('osrdn_engine_run', '')
    g = run.find('engGate(')
    for what in ('!engSeedOk(arg)', 'arg == e->lastSeed'):
        k = run.find(what)
        if k < 0 or k > g:
            p.append('osrdn_engine_run does not refuse %r before the gate' % what)
    draw = efn.get('engDraw', '')
    if not (0 <= draw.find('e->lastSeed = arg;') < draw.find('engPrepare(')):
        p.append('engDraw does not record the seed before the preparation')
    r['r4c-seed'] = p

    p = []
    if 'must NOT be unloaded' not in src['OSRDNDisplay.m']:
        p.append('the registration does not log that the driver must not be unloaded')
    if 'NOT be unloaded' not in src['Unload_Commands.sect']:
        p.append('Unload_Commands.sect does not say the driver must not be unloaded')
    r['r4c-unload'] = p
    return r


D, V, EN = 'OSRDNDisplay.m', 'osrdn_vmap.m', 'osrdn_engine.m'
MUTATIONS = [
    (D, 'd_mmap reads the device state (it can change between the two calls)',
     '    return osrdn_vmap_pfn(&osrdn_vmap_window, dev, offset, prot);\n}',
     '    if (rdnVmapState != OSRDN_VMAP_ON)\n        return -1;\n    return osrdn_vmap_pfn(&osrdn_vmap_window, dev, offset, prot);\n}',
     ['r4c-dmmap-pure']),
    (D, 'the mmap slot gets another function',
     'mmap:(IOSwitchFunc)rdnDevMmap', 'mmap:(IOSwitchFunc)rdnDevNotSupported', ['r4c-dmmap-pure']),
    (V, 'the decision logs',
     '    if (offset < 0)\n        return -1;\n', '    if (offset < 0)\n        return IOLog("neg\\n"), -1;\n', ['r4c-vmap-pure']),
    (V, 'the unit imports a system header',
     '#import "osrdn_vmap.h"', '#import <driverkit/generalFuncs.h>\n#import "osrdn_vmap.h"', ['r4c-vmap-pure']),
    (V, 'fix sets fixed before the values',
     '    v->start = start;\n', '    v->fixed = 1;\n    v->start = start;\n', ['r4c-write-once']),
    (V, 'the decision stores into the window',
     '    off = (unsigned long)offset;\n', '    off = (unsigned long)offset;\n    ((osrdn_vmap *)v)->page = v->page;\n',
     ['r4c-write-once']),
    (D, 'the class widens the window after fixing it',
     '            why = "self";\n', '            why = "self";\n        else if ((osrdn_vmap_window.end = OSRDN_WIN_VRAM) == 0UL)\n            why = "x";\n',
     ['r4c-write-once']),
    (V, 'a self-test case asks once',
     '    b = osrdn_vmap_pfn(v, dev, offset, prot);', '    b = a;', ['r4c-selftest']),
    (V, 'the walk asks once',
     '        got2 = osrdn_vmap_pfn(v, 0, (int)off, rw);', '        got2 = got;', ['r4c-selftest']),
    (D, 'init can still fail after the registration',
     '    [self registerVmap:deviceDescription start:winStart ceiling:winCeiling];\n    return self;',
     '    [self registerVmap:deviceDescription start:winStart ceiling:winCeiling];\n    if (fb == 0)\n        return [self free];\n    return self;',
     ['r4c-register-last']),
    (D, 'the self-test gate is dropped',
     '            if ((bad = osrdn_vmap_selftest(&osrdn_vmap_window, &cases, &allowed)) != 0UL)\n                why = "self";\n            else ',
     '            ', ['r4c-gates']),
    (D, 'the bridge gate is dropped',
     '    else if (!osrdn_fb_reach_ok(&rdnState, ceiling))\n        why = "bridge";\n', '', ['r4c-gates']),
    (D, 'the state turns ON before the registration',
     '    rdnVmapState = OSRDN_VMAP_REFUSED;\n', '    rdnVmapState = OSRDN_VMAP_ON;\n', ['r4c-gates']),
    (D, 'd_open does not look at the state',
     '    if ((dev & 0xFF) != 0 || rdnVmapState != OSRDN_VMAP_ON || rdnR7bHeld) {',
     '    if ((dev & 0xFF) != 0 || rdnR7bHeld) {', ['r4c-gates']),
    (D, 'd_open compares the whole dev',
     '    if ((dev & 0xFF) != 0 || rdnVmapState != OSRDN_VMAP_ON || rdnR7bHeld) {',
     '    if ((dev & 0xFF) != 0 || dev != 0 || rdnVmapState != OSRDN_VMAP_ON || rdnR7bHeld) {',
     ['r4c-minor']),
    (V, 'the decision shifts out a major',
     '    if ((dev & 0xFF) != 0)\n        return -1;', '    if ((dev & 0xFF) != 0 || (dev >> 8) < 0)\n        return -1;',
     ['r4c-minor']),
    ('Default.table', 'the major is left to the kernel (it gives 1, /dev/pp0 is 0666)',
     '"Character Major" = "38";\n', '', ['r4c-tables']),
    ('Instance0.table', 'the major is 1',
     '"Character Major" = "38";', '"Character Major" = "1";', ['r4c-tables']),
    ('Instance0.table', 'a table turns the key off',
     '"RDN VRAM Mmap" = "Yes";', '"RDN VRAM Mmap" = "No";', ['r4c-tables']),
    (EN, 'destStart indexes the cases itself',
     '        return ENG_S0_OFF + E_FILL_Y * ENG_S0_W * 4UL + E_FILL_X * 4UL;\n    c = engCaseFor(op, arg);',
     '        return ENG_S0_OFF + E_FILL_Y * ENG_S0_W * 4UL + E_FILL_X * 4UL;\n    c = &engCases[arg];',
     ['r4c-engine-cases']),
    (EN, 'the seed is recorded after the preparation (a USER refusal leaves it unrecorded)',
     '    if (op == ENG_OP_UBLIT) {\n        e->lastSeed = arg;                  /* from here S1 may hold this seed\'s words */\n'
     '        e->seedUsed = 1;\n    }\n    if (!engPrepare(e, op, arg))\n        return ENG_RC_REFUSED;',
     '    if (!engPrepare(e, op, arg))\n        return ENG_RC_REFUSED;\n    if (op == ENG_OP_UBLIT) {\n'
     '        e->lastSeed = arg;\n        e->seedUsed = 1;\n    }', ['r4c-seed']),
    (EN, 'the seed reuse check is gone',
     '    else if (op == ENG_OP_UBLIT && e->seedUsed && arg == e->lastSeed)\n        (void)engRefuse(e, ENG_WHY_SEED, arg);\n',
     '', ['r4c-seed']),
    (D, 'the registration forgets to say "do not unload"',
     'boot=%08x the driver must NOT be unloaded', 'boot=%08x the driver is registered', ['r4c-unload']),
]


def main():
    src = dict((f, open(os.path.join(d, f), encoding='utf-8').read()) for f, d in FILES.items())
    failures = 0
    print('  == rules on the real files ==')
    base = rules(src)
    for name in sorted(base):
        for why in base[name]:
            print('    FAIL %-18s %s' % (name, why))
        failures += len(base[name])
    if not failures:
        print('    ok   %d rules' % len(base))
    print('  == mutations (each caught by the rule it targets) ==')
    for path, label, old, new, want in MUTATIONS:
        text = src[path]
        if text.count(old) != 1:
            print('    FAIL %-60s anchor found %d times' % (label, text.count(old)))
            failures += 1
            continue
        got = rules(dict(src, **{path: text.replace(old, new)}))
        caught = sorted(n for n in got if got[n])
        ok = all(w in caught for w in want)
        print('    %-4s %-60s %s' % ('ok' if ok else 'FAIL', label,
                                     caught if ok else 'caught by %s, want %s' % (caught, want)))
        failures += 0 if ok else 1
    print('check_r4c_src: %s' % ('PASS' if not failures else 'FAIL (%d)' % failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
