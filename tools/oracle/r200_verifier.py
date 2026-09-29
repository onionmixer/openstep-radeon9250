#!/usr/bin/env python3
"""What the FreeBSD legacy DRM command verifier checks, computed from its source.

  r200_verifier.py --self-test
  r200_verifier.py --markdown          tables for docs/R6_VERIFIER_FACTS.md

Source: ref/upstream/freebsd-stable9/sys/dev/drm/radeon_state.c
  packet[]                          the state-packet table (id -> first register, count)
  radeon_check_and_fixup_packets    which state packets get an address check, on which word
  radeon_check_and_fixup_packet3    which packet-3 opcodes pass, and what is checked
  radeon_check_offset (radeon_drv.h) the address check itself

Everything is parsed, not typed: the table rows, the emit ids from radeon_drm.h,
the case groups of both switches, and the checked data index expressions
(evaluated with cmacro.py).  Register values come from radeon_drv.h.

Address-bearing registers (registers whose value is a card address) are
taken by name from radeon_drv.h: *_COLOROFFSET, *_DEPTHOFFSET, *_ZMASKOFFSET,
*_PP_TXOFFSET_n, *_PP_CUBIC_OFFSET_*.  Two families have no names for every
member; they are derived the way the verifier's own index arithmetic derives
them, and marked as derived:
  R100 PP_TXOFFSET_1/2 = PP_TXFILTER_1/2 + (PP_TXOFFSET_0 - PP_TXFILTER_0)
  R100 PP_CUBIC_OFFSET_Tn_k = PP_CUBIC_OFFSET_Tn_0 + 4k, k = 0..4
The report then says, for every state packet, which address registers its
register range covers and which of those the verifier checks.
"""

import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
DRM = os.path.join(PROJ, 'ref', 'upstream', 'freebsd-stable9', 'sys', 'dev', 'drm')
STATE = os.path.join(DRM, 'radeon_state.c')

_spec = importlib.util.spec_from_file_location('cmacro', os.path.join(HERE, 'cmacro.py'))
cmacro = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cmacro)


def headers():
    return cmacro.Headers([os.path.join(DRM, 'radeon_drv.h'), os.path.join(DRM, 'radeon_drm.h')])


def function_text(src, name):
    m = re.search(r'\n[^\n]*\b%s\s*\([^;{]*\)\s*\{' % re.escape(name), src)
    if not m:
        raise ValueError('function %s not found' % name)
    i = src.index('{', m.start())
    depth = 0
    for j in range(i, len(src)):
        if src[j] == '{':
            depth += 1
        elif src[j] == '}':
            depth -= 1
            if depth == 0:
                return src[i:j + 1], src[:i].count('\n') + 1
    raise ValueError('unbalanced %s' % name)


def packet_table(src):
    m = re.search(r'\} packet\[RADEON_MAX_STATE_PACKETS\] = \{(.*?)\n\};', src, re.S)
    body = re.sub(r'/\*.*?\*/', '', m.group(1), flags=re.S)
    rows = re.findall(r'\{\s*(\w+)\s*,\s*(\d+)\s*,\s*"(\w+)"\s*\}', body)
    return [(start, int(n), name) for start, n, name in rows]


def emit_ids():
    text = open(os.path.join(DRM, 'radeon_drm.h')).read()
    ids = {}
    for name, val in re.findall(r'#define\s+((?:RADEON|R200)_EMIT_\w+)\s+(\d+)', text):
        ids.setdefault(int(val), []).append(name)
    return ids


def case_groups(body):
    """[(labels, block text)] for a switch whose groups end in break/return."""
    out = []
    pos = 0
    labels = []
    for m in re.finditer(r'case\s+(\w+)\s*:', body):
        between = body[pos:m.start()]
        if labels and re.search(r'\b(break|return)\b', between):
            out.append((labels, between))
            labels = []
        labels.append(m.group(1))
        pos = m.end()
    tail = body[pos:]
    cut = tail.find('default:')
    out.append((labels, tail if cut < 0 else tail[:cut]))
    return out


def checked_indices(block, start_name, h):
    """Data indices passed to radeon_check_and_fixup_offset in a case block."""
    idx = []
    for m in re.finditer(r'radeon_check_and_fixup_offset\s*\([^;]*?&data\[([^\]]+)\]', block, re.S):
        expr = m.group(1).strip()
        if expr == 'i':
            loop = re.search(r'for \(i = 0; i < (\d+); i\+\+\)', block)
            idx.extend(range(int(loop.group(1))))
        elif re.fullmatch(r'\d+', expr):
            idx.append(int(expr))
        else:
            mm = re.fullmatch(r'\((\w+)\s*-\s*(\w+)\)\s*/\s*4', expr)
            if not mm:
                raise ValueError('cannot evaluate data index %r' % expr)
            idx.append((h.value(mm.group(1)) - h.value(mm.group(2))) // 4)
    return idx


def address_registers(h):
    names = [n for n in h.body if re.fullmatch(
        r'(RADEON|R200)_(RB3D_COLOROFFSET|RB3D_DEPTHOFFSET|RB3D_ZMASKOFFSET|PP_TXOFFSET_\d|PP_CUBIC_OFFSET_\w+)', n)]
    reg = {}
    for n in names:
        reg[h.value(n)] = n
    d = h.value('RADEON_PP_TXOFFSET_0') - h.value('RADEON_PP_TXFILTER_0')
    for k in (1, 2):
        reg.setdefault(h.value('RADEON_PP_TXFILTER_%d' % k) + d, 'RADEON_PP_TXOFFSET_%d (derived)' % k)
    for t in (0, 1, 2):
        base = h.value('RADEON_PP_CUBIC_OFFSET_T%d_0' % t)
        for k in range(5):
            reg.setdefault(base + 4 * k, 'RADEON_PP_CUBIC_OFFSET_T%d_%d (derived)' % (t, k))
    return reg


def analyse():
    src = open(STATE).read()
    h = headers()
    table = packet_table(src)
    ids = emit_ids()
    body, body_line = function_text(src, 'radeon_check_and_fixup_packets')
    groups = case_groups(body[body.index('switch'):])
    addr = address_registers(h)
    problems = []

    if len(table) != h.value('RADEON_MAX_STATE_PACKETS'):
        problems.append('packet[] has %d rows, RADEON_MAX_STATE_PACKETS is %d' % (len(table), h.value('RADEON_MAX_STATE_PACKETS')))
    label_class = {}
    label_idx = {}
    for labels, block in groups:
        if 'radeon_check_and_fixup_offset' in block:
            cls = 'checked'
        elif "don't contain memory offsets" in block:
            cls = 'no-offsets'
        elif 'RADEON_SE_TCL_STATE_FLUSH' in block:
            cls = 'flush-then-emit'
        else:
            cls = 'other'
        for lab in labels:
            if lab in label_class:
                problems.append('%s appears in two case groups' % lab)
            label_class[lab] = cls
            label_idx[lab] = checked_indices(block, None, h) if cls == 'checked' else []

    rows = []
    for i, (start, n, name) in enumerate(table):
        id_names = ids.get(i, [])
        if not id_names:
            problems.append('packet[%d] (%s) has no emit id' % (i, name))
            continue
        labs = [x for x in id_names if x in label_class]
        if len(labs) != 1:
            problems.append('emit id %d (%s) is named in %d case labels' % (i, id_names, len(labs)))
            continue
        lab = labs[0]
        first = h.value(start)
        covered = [first + 4 * k for k in range(n)]
        in_range = [(r, addr[r]) for r in covered if r in addr]
        checked = [first + 4 * k for k in label_idx[lab]]
        for r in checked:
            if r not in covered:
                problems.append('%s checks word at %04x outside its range' % (lab, r))
        unchecked = [(r, nm) for r, nm in in_range if r not in checked]
        rows.append(dict(id=i, label=lab, table_name=name, start=start, first=first, count=n,
                         cls=label_class[lab], checked=[(r, addr.get(r, '?')) for r in checked],
                         unchecked=unchecked))
    unused = [lab for lab in label_class if lab not in [r['label'] for r in rows]]
    if unused:
        problems.append('case labels with no packet row: %s' % unused)

    # overlaps between packet ranges (two ids writing the same register)
    overlaps = []
    for a in rows:
        for b in rows:
            if a['id'] < b['id']:
                ra = set(a['first'] + 4 * k for k in range(a['count']))
                rb = set(b['first'] + 4 * k for k in range(b['count']))
                both = ra & rb
                if both:
                    overlaps.append((a['label'], b['label'], sorted(both)))

    # packet 3
    body3, line3 = function_text(src, 'radeon_check_and_fixup_packet3')
    sw = body3[body3.index('switch(cmd[0] & 0xff00)'):]
    sw = re.sub(r'/\*.*?\*/', '', sw, flags=re.S)
    p3 = []
    for labels, block in case_groups(sw):
        if 'r100-class' in block:
            what = 'R200 microcode only'
        elif 'r200-class' in block:
            what = 'R100 microcode only (refused on RV280)'
        elif 'these packets are safe' in block:
            what = 'accepted, contents unchecked'
        else:
            what = 'accepted'
        if 'radeon_check_and_fixup_offset' in block:
            what += '; address words checked'
        if 'count > 18' in block:
            what += '; count <= 18'
        if '0x80000810' in block:
            what += '; register word must be 0x80000810'
        for lab in labels:
            p3.append((lab, h.value(lab), what))
    return dict(rows=rows, overlaps=overlaps, p3=p3, problems=problems, addr=addr,
                table_line=src[:src.index('} packet[RADEON_MAX_STATE_PACKETS]')].count('\n') + 1)


def markdown():
    a = analyse()
    out = ['### 생성표 A — 상태 패킷 (RV280 이 받는 R200 microcode 경로)', '',
           '범위 = 첫 레지스터부터 `count` 워드.  **검사** = `radeon_check_and_fixup_offset` 을 거치는 워드, '
           '**미검사 주소** = 범위 안에 주소 레지스터가 있는데 검사하지 않는 것.', '',
           '| id | case | 범위 | 분류 | 검사하는 주소 | 미검사 주소 |', '|---|---|---|---|---|---|']
    for r in a['rows']:
        out.append('| %d | `%s` | `%04x`–`%04x` (%d) | %s | %s | %s |' % (
            r['id'], r['label'], r['first'], r['first'] + 4 * (r['count'] - 1), r['count'], r['cls'],
            ', '.join('`%04x` %s' % x for x in r['checked']) or '—',
            ', '.join('`%04x` %s' % x for x in r['unchecked']) or '—'))
    out += ['', '### 생성표 B — 같은 레지스터를 쓰는 패킷 쌍', '', '| 패킷 | 패킷 | 겹치는 레지스터 |', '|---|---|---|']
    for x, y, regs in a['overlaps']:
        out.append('| `%s` | `%s` | %s |' % (x, y, ' '.join('`%04x`' % r for r in regs)))
    out += ['', '### 생성표 C — 패킷 3 허용 목록 (`radeon_check_and_fixup_packet3`)', '',
            '| opcode | 값 | 처리 |', '|---|---|---|']
    for lab, val, what in a['p3']:
        out.append('| `%s` | `0x%08x` | %s |' % (lab, val, what))
    return '\n'.join(out)


def self_test():
    a = analyse()
    bad = 0

    def expect(label, got, want):
        nonlocal bad
        ok = got == want
        print('%-4s %-62s %s' % ('ok' if ok else 'FAIL', label, '' if ok else 'got %r want %r' % (got, want)))
        bad += 0 if ok else 1

    expect('no structural problem in table/switch/ids', a['problems'], [])
    expect('95 state packets classified', len(a['rows']), 95)
    by = dict((r['label'], r) for r in a['rows'])
    # spot checks against lines read by hand (radeon_state.c:100-160)
    expect('PP_MISC checks RB3D_DEPTHOFFSET', [x[1] for x in by['RADEON_EMIT_PP_MISC']['checked']], ['RADEON_RB3D_DEPTHOFFSET'])
    expect('PP_CNTL checks RB3D_COLOROFFSET', [x[1] for x in by['RADEON_EMIT_PP_CNTL']['checked']], ['RADEON_RB3D_COLOROFFSET'])
    expect('R200 cubic offsets: five words checked', len(by['R200_EMIT_PP_CUBIC_OFFSETS_0']['checked']), 5)
    expect('R200_EMIT_VAP_CTL emits a TCL flush first', by['R200_EMIT_VAP_CTL']['cls'], 'flush-then-emit')
    # every address register some packet can write: is any left unchecked?
    unchecked = [(r['label'], x) for r in a['rows'] for x in r['unchecked']]
    covering = [r for r in a['rows'] if r['checked'] or r['unchecked']]
    # 3 buffer offsets (colour, depth, zmask) + 3 R100 texture + 6 R200 texture
    # + 30 R200 cubic (5 faces x 6 units) + 15 R100 cubic (5 x 3 units)
    expect('address registers found by name or derivation', len(a['addr']), 3 + 3 + 6 + 30 + 15)
    expect('packets whose range covers an address register: %d' % len(covering), len(covering) >= 20, True)
    expect('no state packet writes an address register unchecked', unchecked, [])
    # packet 3 on RV280
    p3 = dict((lab, what) for lab, _, what in a['p3'])
    expect('3D_DRAW_IMMD_2 is R200-only', p3.get('RADEON_CP_3D_DRAW_IMMD_2', '').startswith('R200 microcode only'), True)
    expect('RNDR_GEN_INDX_PRIM refused for R200 microcode', p3.get('RADEON_3D_RNDR_GEN_INDX_PRIM', '').startswith('R100'), True)
    # negative controls: the parser must notice a changed source
    src = open(STATE).read()
    global STATE_TEXT_OVERRIDE
    for label, mutate, want in (
        ('a table row removed', lambda s: s.replace('\t{RADEON_RE_MISC, 1, "RADEON_RE_MISC"},\n', '', 1), 'packet[] has'),
        ('a case label removed', lambda s: s.replace('\tcase RADEON_EMIT_RE_MISC:\n', '', 1), 'named in 0 case labels'),
        ('PP_MISC checks the wrong word', lambda s: s.replace('(RADEON_RB3D_DEPTHOFFSET - RADEON_PP_MISC) / 4',
                                                             '(RADEON_PP_MISC - RADEON_PP_MISC) / 4', 1), 'UNCHECKED RADEON_RB3D_DEPTHOFFSET'),
    ):
        tmp = STATE + '.selftest'
        open(tmp, 'w').write(mutate(src))
        saved = globals()['STATE']
        globals()['STATE'] = tmp
        try:
            res = analyse()
            got = res['problems'] + ['UNCHECKED %s' % x[1] for r in res['rows'] for x in r['unchecked']]
        finally:
            globals()['STATE'] = saved
            os.unlink(tmp)
        expect('control: %s' % label, any(want in p for p in got), True)
    print('r200_verifier self-test:', 'PASS' if bad == 0 else 'FAIL (%d)' % bad)
    return 1 if bad else 0


def main(argv):
    if argv[1:] == ['--self-test']:
        return self_test()
    if argv[1:] == ['--markdown']:
        a = analyse()
        if a['problems']:
            sys.stderr.write('\n'.join(a['problems']) + '\n')
            return 1
        print(markdown())
        return 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
