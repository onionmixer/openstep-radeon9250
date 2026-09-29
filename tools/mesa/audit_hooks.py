#!/usr/bin/env python3
"""Audit the OpenStepMesaAccel* hook contract between osmesa.c and an accel library.

  audit_hooks.py [--osmesa FILE] --impl FILE_OR_DIR ... [--nm NM_TEXT] [--members NAME ...]
  audit_hooks.py --self-test

The Mesa 3.4.2 port declares name-neutral hooks inside
`#ifdef OPENSTEP_MESA_ACCEL_HOOK` in src/OSmesa/osmesa.c and calls them from
the rebuilt osmesa.o.  An accelerator library must define every one of them;
a missing one is a link failure at best, and a mismatched signature is a
silent ABI break.  The Matrox build checks four of them by name
(openstep-matrox-remade/tools/build-matrox-mesa.csh); this checks all of them,
from the declarations rather than from a list typed here.

osmesa.c side
  - every `extern ... OpenStepMesaAccel<Name>( ... );` inside the hook #ifdef
  - every call site, and that each one is compiled only when the hook macro is
    defined (a call reachable in the stock build is an error)
  - each hook is called at least once; calls whose return value is cast to
    (void) are listed (CopyDepth's result is discarded by the caller)
implementation side (--impl: C files or directories of them)
  - each declared hook is defined exactly once, with the declared return type
    and parameter types (names ignored)
optional
  --nm      a text `nm` listing of the built object or archive: each hook must
            appear as a defined text symbol (`T _OpenStepMesaAccel...`)
  --members archive member names: `ar` on the target truncates at 15
            characters (build-matrox-mesa.csh); two names that agree in their
            first 15 characters collide and one silently disappears
"""

import argparse
import glob
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
WS = os.path.dirname(PROJ)
DEFAULT_OSMESA = os.path.join(WS, 'openstep-mesa342', 'upstream', 'Mesa-3.4.2', 'src', 'OSmesa', 'osmesa.c')
MACRO = 'OPENSTEP_MESA_ACCEL_HOOK'
PREFIX = 'OpenStepMesaAccel'
AR_NAME_LIMIT = 15


def strip_comments(text):
    """Blank out comments and string literals, keeping newlines."""
    def blank(m):
        return re.sub(r'[^\n]', ' ', m.group(0))
    return re.sub(r'/\*.*?\*/|//[^\n]*|"(\\.|[^"\\\n])*"', blank, text, flags=re.S)


def hook_regions(lines):
    """For each line, True when it is compiled only if MACRO is defined."""
    stack = []          # entries: (is_hook_condition, in_else)
    out = []
    for line in lines:
        s = line.strip()
        m = re.match(r'#\s*(ifdef|ifndef|if|elif|else|endif)\b\s*(.*)', s)
        if m:
            kind, arg = m.group(1), m.group(2).strip()
            if kind in ('ifdef', 'if', 'ifndef'):
                is_hook = (kind == 'ifdef' and arg == MACRO) or (kind == 'if' and arg in ('defined(%s)' % MACRO, 'defined %s' % MACRO))
                stack.append([is_hook, False])
            elif kind in ('else', 'elif') and stack:
                stack[-1][1] = True
            elif kind == 'endif' and stack:
                stack.pop()
            out.append(any(h and not e for h, e in stack))
            continue
        out.append(any(h and not e for h, e in stack))
    return out


def normalise_type(t):
    t = re.sub(r'\bextern\b|\bstatic\b|\binline\b|__inline__', ' ', t)
    t = re.sub(r'\s*\*\s*', ' * ', t)
    return re.sub(r'\s+', ' ', t).strip()


def param_types(params):
    params = params.strip()
    if params in ('', 'void'):
        return ['void']
    out = []
    for p in params.split(','):
        p = normalise_type(p)
        toks = p.split(' ')
        # drop a trailing identifier (the parameter name), keep pointer stars
        if len(toks) > 1 and re.fullmatch(r'[A-Za-z_]\w*', toks[-1]) and toks[-1] not in (
                'int', 'long', 'short', 'char', 'unsigned', 'signed', 'float', 'double', 'void', 'const'):
            toks = toks[:-1]
        out.append(' '.join(toks))
    return out


def declarations(path):
    raw = open(path, errors='replace').read()
    text = strip_comments(raw)
    lines = text.split('\n')
    region = hook_regions(lines)
    decls = {}
    problems = []
    for m in re.finditer(r'extern\s+([^;(]*?)\b(%s\w+)\s*\(([^)]*)\)\s*;' % PREFIX, text, re.S):
        line = text[:m.start()].count('\n')
        name = m.group(2)
        if not region[line]:
            problems.append('%s declared outside #ifdef %s at %s:%d' % (name, MACRO, os.path.basename(path), line + 1))
        if name in decls:
            problems.append('%s declared twice' % name)
        decls[name] = dict(ret=normalise_type(m.group(1)), params=param_types(m.group(3)), line=line + 1)
    calls = {}
    for m in re.finditer(r'(\(\s*void\s*\)\s*)?\b(%s\w+)\s*\(' % PREFIX, text):
        line = text[:m.start()].count('\n')
        name = m.group(2)
        # skip the declarations themselves
        before = text[max(0, m.start() - 200):m.start()]
        if re.search(r'extern\s+[^;(]*$', before):
            continue
        calls.setdefault(name, []).append(dict(line=line + 1, guarded=region[line], void_cast=bool(m.group(1))))
    for name, cs in calls.items():
        if name not in decls:
            problems.append('%s called but not declared' % name)
        for c in cs:
            if not c['guarded']:
                problems.append('%s called outside #ifdef %s at line %d' % (name, MACRO, c['line']))
    for name in decls:
        if name not in calls:
            problems.append('%s declared but never called' % name)
    return decls, calls, problems


def definitions(paths):
    files = []
    for p in paths:
        files += sorted(glob.glob(os.path.join(p, '*.c'))) if os.path.isdir(p) else [p]
    defs = {}
    for f in files:
        text = strip_comments(open(f, errors='replace').read())
        for m in re.finditer(r'(^|\n)([A-Za-z_][^;{}()#]*?)\b(%s\w+)\s*\(([^)]*)\)\s*\{' % PREFIX, text, re.S):
            name = m.group(3)
            defs.setdefault(name, []).append(dict(file=os.path.relpath(f, WS), ret=normalise_type(m.group(2)),
                                                  params=param_types(m.group(4)),
                                                  line=text[:m.start(3)].count('\n') + 1))
    return defs, files


def audit(osmesa, impl, nm_text=None, members=None):
    decls, calls, problems = declarations(osmesa)
    report = ['%d hooks declared in %s' % (len(decls), os.path.relpath(osmesa, WS))]
    # M3g (docs/M3G_PLAN.md): the surface is offered only to a four-byte pixel.
    # Every back end copies it back a word a pixel; RGB, BGR and COLOR_INDEX
    # would be written past the end of the caller's array.
    flat = re.sub(r'\s+', ' ', open(osmesa).read())
    gate = ('if (ctx->format == OSMESA_RGBA || ctx->format == OSMESA_BGRA '
            '|| ctx->format == OSMESA_ARGB) accelBuf = OpenStepMesaAccelBuffer(')
    if flat.count(gate) != 1:
        problems.append('osmesa.c: OpenStepMesaAccelBuffer is not behind the four-byte format gate '
                        '(found %d)' % flat.count(gate))
    for name in sorted(decls):
        cs = calls.get(name, [])
        report.append('  %-34s calls %d%s' % (name, len(cs), ''.join(
            ' (line %d result discarded)' % c['line'] for c in cs if c['void_cast'])))
    if impl:
        defs, files = definitions(impl)
        report.append('%d implementation files' % len(files))
        for name, d in sorted(decls.items()):
            got = defs.get(name, [])
            if not got:
                problems.append('%s is not defined by the implementation' % name)
                continue
            if len(got) > 1:
                problems.append('%s defined %d times: %s' % (name, len(got), ', '.join('%s:%d' % (g['file'], g['line']) for g in got)))
            g = got[0]
            if g['ret'] != d['ret'] or g['params'] != d['params']:
                problems.append('%s signature differs: declared %s(%s), defined %s(%s) at %s:%d' % (
                    name, d['ret'], ', '.join(d['params']), g['ret'], ', '.join(g['params']), g['file'], g['line']))
        extra = sorted(set(defs) - set(decls))
        if extra:
            report.append('defined but not declared by osmesa.c (not an error): %s' % ', '.join(extra))
    if nm_text is not None:
        have = set(re.findall(r'\b[Tt]\s+_?(%s\w+)' % PREFIX, nm_text))
        for name in sorted(decls):
            if name not in have:
                problems.append('%s is not a defined text symbol in the nm listing' % name)
    if members:
        seen = {}
        for mem in members:
            key = os.path.basename(mem)[:AR_NAME_LIMIT]
            if key in seen and seen[key] != mem:
                problems.append('archive members %s and %s collide at %d characters (%s)' % (seen[key], mem, AR_NAME_LIMIT, key))
            seen.setdefault(key, mem)
    return report, problems


def self_test():
    bad = 0
    matrox = os.path.join(WS, 'openstep-matrox-remade', 'mesa')

    def expect(label, cond, detail=''):
        nonlocal bad
        print('%-4s %s%s' % ('ok' if cond else 'FAIL', label, '' if cond else ' -- ' + detail))
        bad += 0 if cond else 1

    decls, calls, probs = declarations(DEFAULT_OSMESA)
    expect('osmesa.c declares 10 hooks under the macro', len(decls) == 10 and not probs, '%d %s' % (len(decls), probs))
    expect('CopyDepth result is discarded at every call',
           all(c['void_cast'] for c in calls.get('OpenStepMesaAccelCopyDepth', [])) and calls.get('OpenStepMesaAccelCopyDepth'))
    report, probs = audit(DEFAULT_OSMESA, [matrox])
    expect('Matrox accel sources satisfy all 10 hooks', not probs, '; '.join(probs))
    with tempfile.TemporaryDirectory() as t:
        # control 1: an implementation missing one hook and with one wrong signature
        src = ''.join(open(f, errors='replace').read() for f in sorted(glob.glob(os.path.join(matrox, '*.c'))))
        mutated = re.sub(r'\bOpenStepMesaAccelStride\s*\(', 'OpenStepMesaAccelStrideRenamed(', src)
        mutated = re.sub(r'(\n[^\n;{}]*)\bint\s+(OpenStepMesaAccelBoundTo\s*\()', r'\1long \2', mutated, count=1)
        f1 = os.path.join(t, 'impl.c')
        open(f1, 'w').write(mutated)
        _, probs = audit(DEFAULT_OSMESA, [f1])
        expect('control: a missing hook is caught', any('Stride is not defined' in p for p in probs), '; '.join(probs))
        expect('control: a changed return type is caught', any('BoundTo signature differs' in p for p in probs), '; '.join(probs))
        # control 2: a call reachable without the macro
        os_src = open(DEFAULT_OSMESA, errors='replace').read()
        f2 = os.path.join(t, 'osmesa.c')
        open(f2, 'w').write(os_src + '\nstatic void stray(void) { OpenStepMesaAccelMirror(); }\n')
        _, _, probs = declarations(f2)
        expect('control: an unguarded call is caught', any('called outside' in p for p in probs), '; '.join(probs))
        # control 3: nm listing missing a symbol, and colliding archive members
        nm = '\n'.join('00001000 T _%s' % n for n in decls if n != 'OpenStepMesaAccelClearPixel')
        _, probs = audit(DEFAULT_OSMESA, None, nm_text=nm)
        expect('control: nm listing without ClearPixel is caught', any('ClearPixel is not a defined' in p for p in probs))
        _, probs = audit(DEFAULT_OSMESA, None, members=['OpenStepMGAMesaHook.o', 'OpenStepMGAMesaProbe.o'])
        expect('control: members agreeing in 15 characters collide', any('collide' in p for p in probs), '; '.join(probs))
        _, probs = audit(DEFAULT_OSMESA, None, members=['osmesa.o', 'osmgaccel.o'])
        expect('distinct short member names pass', not probs, '; '.join(probs))
    print('audit_hooks self-test:', 'PASS' if bad == 0 else 'FAIL (%d)' % bad)
    return 1 if bad else 0


def main(argv):
    if argv[1:] == ['--self-test']:
        return self_test()
    ap = argparse.ArgumentParser()
    ap.add_argument('--osmesa', default=DEFAULT_OSMESA)
    ap.add_argument('--impl', nargs='*')
    ap.add_argument('--nm')
    ap.add_argument('--members', nargs='*')
    a = ap.parse_args(argv[1:])
    nm_text = open(a.nm).read() if a.nm else None
    report, problems = audit(a.osmesa, a.impl, nm_text, a.members)
    print('\n'.join(report))
    for p in problems:
        print('FAIL', p)
    print('audit_hooks:', 'PASS' if not problems else 'FAIL (%d)' % len(problems))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
