#!/usr/bin/env python3
"""Memory stores in i386 AT&T disassembly (docs/R1C_R2A_IMPL_PLAN.md sections 2-6 item 5 and 2-8).

Shared by tools/r2a/check_r2a_src.py (host objects, `objdump -dr`) and
tools/r2a/check_reloc.py (target reloc bytes, `objdump -D -b binary`).

A store is an instruction that writes to a memory operand:
  - two-operand forms whose last (destination) operand is memory: mov,
    or/and/xor/add/sub/adc/sbb, xchg (either operand), shifts and rotates,
    bts/btr/btc, cmpxchg, movs/stos (implicit %es:(%edi))
  - one-operand forms on memory: inc/dec/not/neg, setcc, pop
A memory operand is one with parentheses, a segment prefix, or a bare address.
lea, cmp, test, push, call, jmp never store.

Width is the source register's size (%al.. 8, %ax.. 16, %eax.. 32), else the
mnemonic suffix (b/w/l), else unknown (0).  The base register is the first
register inside the parentheses (None for an absolute address).  A stack
store is one whose base is %esp or %ebp.
"""

import re

REG8 = {'al', 'bl', 'cl', 'dl', 'ah', 'bh', 'ch', 'dh'}
REG16 = {'ax', 'bx', 'cx', 'dx', 'si', 'di', 'sp', 'bp'}
REG32 = {'eax', 'ebx', 'ecx', 'edx', 'esi', 'edi', 'esp', 'ebp'}

TWO = ('mov', 'or', 'and', 'xor', 'add', 'sub', 'adc', 'sbb', 'shl', 'shr', 'sal', 'sar', 'rol', 'ror',
       'rcl', 'rcr', 'bts', 'btr', 'btc', 'cmpxchg')
ONE = ('inc', 'dec', 'not', 'neg', 'pop')
NEVER = ('lea', 'cmp', 'test', 'push', 'call', 'jmp', 'bt', 'nop')
# widening loads (movsbl, movzwl, ...): movsb/movsw/movsl alone are string moves
NEVER_PREFIX = ('movsb', 'movsw', 'movzb', 'movzw', 'movzx', 'movsx', 'cmov', 'lea', 'cmp', 'test', 'push', 'call',
                'jmp', 'j')


def split_operands(ops):
    """Split on commas outside parentheses."""
    out, depth, cur = [], 0, ''
    for ch in ops:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            out.append(cur.strip())
            cur = ''
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def is_memory(op):
    if op.startswith('%') and ':' not in op:
        return False
    if op.startswith('$') or op.startswith('*'):
        return False
    return '(' in op or ':' in op or re.fullmatch(r'-?0x[0-9a-f]+|-?[0-9]+', op) is not None


def base_register(op):
    m = re.search(r'\((%[a-z]+)?', op)
    if m and m.group(1):
        return m.group(1)[1:]
    return None


def reg_width(op):
    if not op.startswith('%'):
        return 0
    r = op[1:]
    if r in REG8:
        return 8
    if r in REG16:
        return 16
    if r in REG32:
        return 32
    return 0


def suffix_width(mn, stem):
    s = mn[len(stem):]
    return {'b': 8, 'w': 16, 'l': 32}.get(s, 0)


def classify(insn):
    """Return None, or (width, base) for a store instruction text such as
    'mov    %al,(%edx)'."""
    insn = insn.strip()
    if not insn or insn.startswith('('):
        return None
    parts = insn.split(None, 1)
    mn = parts[0]
    ops = split_operands(parts[1].split('#')[0].split('<')[0]) if len(parts) > 1 else []
    if mn.startswith(('rep', 'data16', 'addr16', 'lock')) and len(parts) > 1:
        return classify(parts[1])
    if mn in NEVER:
        return None
    if mn in ('movs', 'movsb', 'movsw', 'movsl'):
        return (suffix_width(mn, 'movs') or (reg_width(ops[0]) if ops else 0), 'edi')
    if mn.startswith(NEVER_PREFIX):
        return None
    if mn.startswith('stos'):
        w = reg_width(ops[0]) if ops else suffix_width(mn, 'stos')
        return (w, 'edi')
    if mn.startswith('set') and len(ops) == 1:
        return (8, base_register(ops[0])) if is_memory(ops[0]) else None
    if mn.startswith('xchg') and len(ops) == 2:
        for a, b in ((ops[0], ops[1]), (ops[1], ops[0])):
            if is_memory(b):
                return (reg_width(a) or suffix_width(mn, 'xchg'), base_register(b))
        return None
    for stem in TWO:
        if mn == stem or (mn[:-1] == stem and mn[-1] in 'bwl'):
            if len(ops) == 2 and is_memory(ops[1]):
                return (reg_width(ops[0]) or suffix_width(mn, stem), base_register(ops[1]))
            if len(ops) == 1 and stem in ('shl', 'shr', 'sal', 'sar', 'rol', 'ror', 'rcl', 'rcr') and is_memory(ops[0]):
                return (suffix_width(mn, stem), base_register(ops[0]))
            return None
    for stem in ONE:
        if mn == stem or (mn[:-1] == stem and mn[-1] in 'bwl'):
            if len(ops) == 1 and is_memory(ops[0]):
                return (suffix_width(mn, stem), base_register(ops[0]))
            return None
    return None


def is_stack(base):
    return base in ('esp', 'ebp')


def functions(dis_text):
    """objdump -d(r) text -> {function: [(address, insn text, [reloc lines])]}"""
    funcs = {}
    cur = None
    for line in dis_text.splitlines():
        m = re.match(r'^([0-9a-f]+) <([^>]+)>:', line)
        if m:
            cur = funcs.setdefault(m.group(2), [])
            continue
        if cur is None:
            continue
        m = re.match(r'^\s+([0-9a-f]+):\s+(R_386_\S+)\s+(\S+)', line)
        if m and cur:
            cur[-1][2].append((m.group(2), m.group(3)))
            continue
        m = re.match(r'^\s+([0-9a-f]+):\s*(?:(?:[0-9a-f]{2} )+\s*)?(.*)$', line)
        if m and m.group(2).strip():
            cur.append((int(m.group(1), 16), m.group(2).strip(), []))
    return funcs


def self_test():
    cases = [
        ('mov    %al,(%edx)', (8, 'edx')), ('mov    %eax,(%edx)', (32, 'edx')),
        ('mov    %al,-0x4(%ebp)', (8, 'ebp')), ('movb   $0x1,0x8(%eax)', (8, 'eax')),
        ('movl   $0x0,(%esp)', (32, 'esp')), ('movw   $0x1,(%ecx)', (16, 'ecx')),
        ('mov    %dx,(%ecx)', (16, 'ecx')), ('mov    (%eax),%eax', None), ('movzbl -0x4(%ebp),%eax', None),
        ('lea    0x0(%esi,%eiz,1),%esi', None), ('add    %edx,%eax', None), ('add    %dl,(%eax)', (8, 'eax')),
        ('orl    $0x80,0x8(%ebx)', (32, 'ebx')), ('incb   (%eax)', (8, 'eax')), ('push   %ebp', None),
        ('stos   %al,%es:(%edi)', (8, 'edi')), ('rep stos %eax,%es:(%edi)', (32, 'edi')),
        ('mov    %eax,0x0', (32, None)), ('mov    %eax,0x0(,%edx,8)', (32, None)),
        ('xchg   %al,(%ecx)', (8, 'ecx')), ('xchg   %eax,%edx', None), ('sete   (%eax)', (8, 'eax')),
        ('sete   %al', None), ('call   0 <x>', None), ('cmp    %al,(%edx)', None), ('test   %al,(%edx)', None),
        ('mov    %ds:0x1234,%eax', None), ('mov    %eax,%ds:0x1234', (32, None)), ('shll   (%eax)', (32, 'eax')),
        ('pop    (%eax)', (0, 'eax')), ('pop    %ebp', None), ('movsbl (%eax),%eax', None), ('nop', None),
        ('ret', None), ('leave', None), ('movsl  %ds:(%esi),%es:(%edi)', (32, 'edi')),
        ('movsb  %ds:(%esi),%es:(%edi)', (8, 'edi')), ('movswl (%eax),%eax', None), ('jmp    *0x0(,%eax,4)', None),
        ('jne    10 <f>', None), ('sub    $0x4,%esp', None), ('subl   $0x1,-0x8(%ebp)', (32, 'ebp')),
    ]
    bad = 0
    for insn, want in cases:
        got = classify(insn)
        if got != want:
            print('FAIL stores.classify(%r) = %r, want %r' % (insn, got, want))
            bad += 1
    print('stores self-test: %s (%d cases)' % ('PASS' if not bad else 'FAIL (%d)' % bad, len(cases)))
    return bad == 0


if __name__ == '__main__':
    import sys
    sys.exit(0 if self_test() else 1)
