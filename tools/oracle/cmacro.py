#!/usr/bin/env python3
"""Evaluate object-like C #define constants from reference headers.

  cmacro.py --self-test
  cmacro.py <header> ... -- NAME ...      print the values

Only object-like macros whose bodies are integer expressions: numbers
(decimal, hex, with u/U/l/L suffixes), other such macros, parentheses and
the operators << >> | & ^ ~ + - * /.  Casts such as (u32) are removed.
Anything else (function-like macros, strings, statements) raises, so a value
that cannot be computed is never guessed.  Results are 32-bit unsigned.
"""

import os
import re
import sys

DEFINE = re.compile(r'^\s*#\s*define\s+([A-Za-z_]\w*)(\(?)\s*(.*)$')


class Headers:
    def __init__(self, paths):
        self.body = {}
        self.where = {}
        for p in paths:
            lines = open(p, errors='replace').read().split('\n')
            i = 0
            while i < len(lines):
                line = lines[i]
                n = i + 1
                while line.endswith('\\') and i + 1 < len(lines):
                    i += 1
                    line = line[:-1] + ' ' + lines[i]
                m = DEFINE.match(line)
                if m and m.group(2) == '':
                    body = re.sub(r'/\*.*?\*/', ' ', m.group(3))
                    body = re.sub(r'//.*$', '', body).strip()
                    # first definition wins, as the preprocessor would warn on a
                    # different redefinition; record duplicates to report them
                    if m.group(1) not in self.body:
                        self.body[m.group(1)] = body
                        self.where[m.group(1)] = '%s:%d' % (os.path.basename(p), n)
                i += 1

    def value(self, name, _depth=0):
        if _depth > 50:
            raise ValueError('macro recursion through %s' % name)
        if name not in self.body:
            raise KeyError('no object-like #define %s' % name)
        expr = self.body[name]
        expr = re.sub(r'\(\s*(u8|u16|u32|u64|int|unsigned|unsigned int|uint32_t)\s*\)', '', expr)

        def num(m):
            return str(int(m.group(1), 0))
        expr = re.sub(r'\b(0[xX][0-9a-fA-F]+|\d+)[uUlL]*\b', num, expr)

        def ident(m):
            return '(%d)' % self.value(m.group(0), _depth + 1)
        expr = re.sub(r'\b[A-Za-z_]\w*\b', ident, expr)
        if not re.fullmatch(r'[\d\s()<>|&^~+\-*/]*', expr) or not expr.strip():
            raise ValueError('%s is not an integer expression: %r' % (name, self.body[name]))
        expr = expr.replace('/', '//')
        return eval(expr, {'__builtins__': {}}) & 0xffffffff


def self_test():
    import tempfile
    t = tempfile.NamedTemporaryFile('w', suffix='.h', delete=False)
    t.write('#define A 0x10\n#\tdefine B (A << 2) /* c */\n#define C (B | 1UL)\n'
            '#define F(x) (x)\n#define S "str"\n#define N (~0)\n#define M \\\n  (C + 1)\n'
            '#define A 0x99\n')
    t.close()
    h = Headers([t.name])
    ok = (h.value('A') == 0x10 and h.value('B') == 0x40 and h.value('C') == 0x41 and
          h.value('N') == 0xffffffff and h.value('M') == 0x42)
    for bad in ('F', 'S', 'Z'):
        try:
            h.value(bad)
            ok = False
        except (KeyError, ValueError):
            pass
    os.unlink(t.name)
    print('cmacro self-test:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


def main(argv):
    if argv[1:] == ['--self-test']:
        return self_test()
    if '--' not in argv:
        sys.stderr.write(__doc__)
        return 2
    k = argv.index('--')
    h = Headers(argv[1:k])
    for n in argv[k + 1:]:
        print('%-40s 0x%08x  %s' % (n, h.value(n), h.where[n]))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
