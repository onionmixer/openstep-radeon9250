#!/usr/bin/env python3
"""R7b: the character-device path's source rules, and the tables nobody may type.

  check_r7b.py            check
  check_r7b.py --write    regenerate the case tables inside tools/r7/rdnr7dev.c
  check_r7b.py --self-test  prove each rule fires on a source that breaks it

Three things are checked, and each one is a way this rung could quietly rot:

  1. The ioctl command numbers.  They are built out of sizeof, so a field added
     to either block changes them -- and a client built against the old header
     would then send a number the driver does not answer.  The numbers are
     built from the target's own encoding (bsd/sys/ioctl.h: IOC_OUT 0x40000000,
     IOC_IN 0x80000000, IOCPARM_MASK 0x7f), so what can be checked in the text
     is the SHAPE -- the right direction bits, the group, the ordinal, and a
     length taken from the block itself rather than written out.  The number
     each one comes to is printed, and both blocks are held under 128 bytes.
  2. The client is PURE C.  That is the whole reason R7b exists, so it is a
     rule and not a habit: no #import, no driverkit, no IODeviceMaster.
  3. The stream tables in BOTH tools are what tools/r7/verify_oracle.py
     generates -- byte for byte, not "close enough".
"""

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
TPROJ = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj')
HDR = os.path.join(TPROJ, 'osrdn_r7b.h')
DEV = os.path.join(HERE, 'rdnr7dev.c')
SUB = os.path.join(HERE, 'rdnr7sub.m')
ORACLE = os.path.join(HERE, 'verify_oracle.py')
DISP = os.path.join(TPROJ, 'OSRDNDisplay.m')
JUDGE = os.path.join(PROJ, 'build', 'r7b', 'judge_r7b.py')
BEGIN = '/* <<<GENERATED CASES>>> */'
END = '/* <<<END GENERATED CASES>>> */'

IOC_OUT = 0x40000000
IOC_IN = 0x80000000
IOCPARM_MASK = 0x7f
# the only two lines allowed to wear "boot=<nonce> n=" without an rc (see the rule)
LINE_SHAPE_OK = {'RDN-R2B enter', 'RDN-R2B revert'}


def uncomment(t):
    """a rule about code must not be answered by a comment that mentions the word"""
    return re.sub(r'//[^\n]*', ' ', re.sub(r'/\*.*?\*/', ' ', t, flags=re.S))


def macro(text, name):
    """a #define's body, continuation lines included"""
    m = re.search(r'^#define\s+%s\b((?:[^\n]*\\\n)*[^\n]*)' % name, text, re.M)
    return m.group(1) if m else ''


def fields(text, name):
    """the field names of a struct, in order"""
    m = re.search(r'typedef struct \{([^{}]*)\}\s*%s;' % name, text, re.S)
    if m is None:
        return None
    return re.findall(r'^\s*unsigned long (\w+)', m.group(1), re.M)


def ints(text, name, sep=r'0x([0-9a-fA-F]+)UL'):
    """a generated table's numbers, whatever its shape"""
    i = text.find(name)
    if i < 0:
        return None
    j = text.index('};', i)
    return [int(x, 16) for x in re.findall(sep, text[i:j])]


def table_block(text):
    """the three generated tables of a tool, as plain lists"""
    pool = ints(text, 'cpR7Pool[')
    fix = [int(x) for x in re.findall(r'\b[01]\b',
                                      text[text.index('cpR7Fix['):text.index('};', text.index('cpR7Fix['))])] \
        if 'cpR7Fix[' in text else None
    i = text.find('cpR7Cases[')
    cases = None
    if i >= 0:
        cases = [tuple(int(x) for x in m) for m in
                 re.findall(r'\{\s*(\d+),\s*(\d+),\s*(\d+)\s*\}', text[i:text.index('};', i)])]
    return pool, cases, fix


def generated():
    out = subprocess.run([sys.executable, ORACLE, '--c-cases'], capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit('verify_oracle --c-cases failed:\n' + out.stderr[-500:])
    return out.stdout


def rules(hdr, dev, sub, gen, disp=None):
    """every rule, as (name, [problems]); a rule with no problems passed"""
    r = {}

    # 4. a line that is not a CP operation must not look like one.  The runners
    # select operation lines by "boot=<nonce> n=", and an R7B line wearing that
    # shape was counted as an operation and judged by its rc -- which cost a run
    # (2026-09-22).  The shape belongs to osrdn_cp.m's own line and to nothing else.
    p = []
    if disp is None:
        disp = open(DISP).read()
    seen = set()
    for m in re.finditer(r'IOLog\("(RDN-[^"]*)"', uncomment(disp)):
        fmt = m.group(1)
        if not re.search(r'boot=%08x n=', fmt):
            continue
        tag = ' '.join(fmt.split()[:2])
        seen.add(tag)
        # The operation line belongs to osrdn_modelog.m and to nothing else: a runner
        # SELECTS by this shape and then judges what it selected, so a line here that
        # wears it is counted as an operation whatever else it says.  The two
        # exceptions are named, not waved through: they are parsed by
        # tools/r3/check_select.py, and a mode enter or revert cannot happen inside a
        # runner's CP sequence.
        if tag not in LINE_SHAPE_OK:
            p.append('%s wears the operation line\'s shape' % tag)
    for tag in LINE_SHAPE_OK:
        if tag not in seen:
            p.append('%s is listed as an exception but is not there any more' % tag)
    r['r7b-line-shape'] = p
    # G4-4 K8 (docs/G4_4_KERNEL_PLAN.md 2): the copyin path takes what CAPS advertises.
    # Its count test is the verifier's limit alone; the copy is made INSIDE the
    # staging loop, one APPEND chunk at a time, through the one page; and both
    # paths end in the one shared tail.  Before this the whole stream was copied
    # at once and anything past the page was "count" while CAPS said 4068 -- the
    # mismatch nothing here compared (found on the hardware, 2026-09-27).
    p = []
    dd = uncomment(disp)
    m2 = re.search(r'- \(void\)r7bSubmit2:.*?\n\}\n', dd, re.S)
    m1 = re.search(r'- \(void\)r7bSubmit:.*?\n\}\n', dd, re.S)
    b2 = m2.group(0) if m2 else ''
    b1 = m1.group(0) if m1 else ''
    if not b2 or not b1:
        p.append('r7bSubmit2 or r7bSubmit is not where the rule looks')
    else:
        flat2 = re.sub(r'\s+', ' ', b2)
        if 'else if (n == 0UL || n > OSRDN_R7B_MAX_WORDS) why = "count";' not in flat2:
            p.append('SUBMIT2 does not bound the count by OSRDN_R7B_MAX_WORDS alone')
        if 'OSRDN_R7B_WINDOW_WORDS' in b2:
            p.append('SUBMIT2 still bounds the stream by the page')
        loop = re.search(r'while \(staged && k < n\) \{(.*?)\n        \}', b2, re.S)
        if loop is None:
            p.append('SUBMIT2 has no staging loop')
        else:
            lb = re.sub(r'\s+', ' ', loop.group(1))
            if 'copyin((const void *)(sb->words + k * 4UL), (void *)rdnR7bVirt, (unsigned int)(take * 4UL))' not in lb:
                p.append('the copy is not made inside the loop, one chunk at a time, from the client offset')
            if 'if (take > (unsigned long)CP_R7_APPEND_MAX) take = (unsigned long)CP_R7_APPEND_MAX;' not in lb:
                p.append('the chunk is not bounded by CP_R7_APPEND_MAX')
            if 'osrdn_cp_stage(&rdnCp, (unsigned long)CP_R7_OP_APPEND, token, take, w)' not in lb:
                p.append('the chunk is not appended from the page')
            if 'sb->status = (unsigned long)EFAULT; why = "copyin"; break;' not in lb:
                p.append('a copyin fault does not stop the loop with EFAULT')
        if b2.count('copyin(') != 1:
            p.append('SUBMIT2 copies in %d times; once, in the loop' % b2.count('copyin('))
        if 'CP_R7_OP_RESET' not in b2:
            p.append('SUBMIT2 does not begin with RESET')
        for name, body in (('r7bSubmit2', b2), ('r7bSubmit', b1)):
            if body.count('[self r7bRun:') != 1:
                p.append('%s does not end in the one shared tail (r7bRun called %d times)' % (name, body.count('[self r7bRun:')))
            if 'osrdn_mode_cp(' in body or 'osrdn_cp_quiet_take' in body:
                p.append('%s keeps a copy of the tail' % name)
        if dd.count('- (void)r7bRun:') != 1 or dd.count('osrdn_cp_quiet_take(&rdnCp)') != 1:
            p.append('the tail is not exactly one method with the one quiet decision')
    r['r7b-submit2-chunked'] = p

    # 1. the ioctl encoding, recomputed rather than read
    p = []
    sizes = {}
    hcode = uncomment(hdr)
    for name in ('osrdn_r7b_caps', 'osrdn_r7b_submit'):
        f = fields(hcode, name)
        if f is None:
            p.append('%s is not a struct of unsigned longs' % name)
            continue
        sizes[name] = 4 * len(f)
        if sizes[name] > IOCPARM_MASK:
            p.append('%s is %d bytes; the encoding truncates above %d' % (name, sizes[name], IOCPARM_MASK))
    want = {}
    if len(sizes) == 2:
        want['OSRDN_R7B_IOC_CAPS'] = (IOC_OUT | ((sizes['osrdn_r7b_caps'] & IOCPARM_MASK) << 16) |
                                      (ord('R') << 8) | 1)
        want['OSRDN_R7B_IOC_SUBMIT'] = (IOC_IN | IOC_OUT |
                                        ((sizes['osrdn_r7b_submit'] & IOCPARM_MASK) << 16) |
                                        (ord('R') << 8) | 2)
    for k in ('OSRDN_R7B_IOC_CAPS', 'OSRDN_R7B_IOC_SUBMIT'):
        if re.search(r'#define\s+%s\b' % k, hcode) is None:
            p.append('%s is not defined' % k)
    r['r7b-numbers'] = sorted('%s = %#010x' % (k, v) for k, v in want.items())
    # the header builds the numbers with sizeof, so what is checked is the SHAPE:
    # the right bits, the right group, the right ordinal, and the size it uses
    for k, bits, ordinal, blk in (('OSRDN_R7B_IOC_CAPS', ['OSRDN_R7B_IOC_OUT'], '1UL', 'osrdn_r7b_caps'),
                                  ('OSRDN_R7B_IOC_SUBMIT', ['OSRDN_R7B_IOC_IN', 'OSRDN_R7B_IOC_OUT'],
                                   '2UL', 'osrdn_r7b_submit')):
        body = macro(hcode, k)
        for b in bits:
            if b not in body:
                p.append('%s does not carry %s' % (k, b))
        if 'OSRDN_R7B_IOC_IN' in body and 'IOC_IN' not in ' '.join(bits):
            p.append('%s copies in when it should not' % k)
        if ('sizeof(%s)' % blk) not in body:
            p.append('%s does not take its length from %s' % (k, blk))
        if ordinal not in body:
            p.append('%s does not end in %s' % (k, ordinal))
        if "OSRDN_R7B_IOC_GROUP" not in body:
            p.append('%s does not carry the group' % k)
    if re.search(r'#define\s+OSRDN_R7B_IOC_GROUP\s+\'R\'', hcode) is None:
        p.append("the group is not 'R'")
    if re.search(r'#define\s+OSRDN_R7B_IOC_PARM_MASK\s+0x7fUL', hcode) is None:
        p.append('the parameter mask is not this target\'s 0x7f')
    r['r7b-ioctl'] = p

    # G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2): SUBMIT3 is SUBMIT2's block under a new ordinal, RETIRE
    # its own block, both in and out; the dispatcher gives each the operation its name says; and the
    # last close retires a submission still in flight before it lets the latch go
    p = []
    for k, blk, ordinal in (('OSRDN_R7B_IOC_SUBMIT3', 'osrdn_r7b_submit2', '6UL'), ('OSRDN_R7B_IOC_RETIRE', 'osrdn_r7b_retire', '7UL')):
        body = macro(hcode, k)
        if not body:
            p.append('%s is not defined' % k)
            continue
        for want in ('OSRDN_R7B_IOC_IN', 'OSRDN_R7B_IOC_OUT', 'sizeof(%s)' % blk, ordinal, 'OSRDN_R7B_IOC_GROUP'):
            if want not in body:
                p.append('%s lacks %s' % (k, want))
    fr = fields(hcode, 'osrdn_r7b_retire')
    if fr is None or 4 * len(fr) >= IOCPARM_MASK:
        p.append('osrdn_r7b_retire is not a struct of unsigned longs under the size mask')
    if disp is not None:
        dsp = re.sub(r'\s+', ' ', uncomment(disp))
        for cmd, call in (('OSRDN_R7B_IOC_SUBMIT2', 'r7bSubmit2:(osrdn_r7b_submit2 *)data op:CP_OP_ZCLEAR'),
                          ('OSRDN_R7B_IOC_SUBMIT3', 'r7bSubmit2:(osrdn_r7b_submit2 *)data op:CP_OP_ASUBMIT'),
                          ('OSRDN_R7B_IOC_RETIRE', 'r7bRetire:(osrdn_r7b_retire *)data')):
            m = re.search(r'if \(cmd == \(int\)%s\) \{ \[rdnR7bInstance ([^\]]*)\]; return 0; \}' % cmd, dsp)
            if not m or m.group(1) != call.replace('r7bSubmit2:', 'r7bSubmit2:', 1):
                p.append('%s is not dispatched to %s' % (cmd, call))
        mc = re.search(r'\nrdnDevClose\(.*?\n\}', uncomment(disp), re.S)
        cb = re.sub(r'\s+', ' ', mc.group(0)) if mc else ''
        ir, il = cb.find('[rdnR7bInstance r7bCloseRetire]'), cb.find('rdnR7bHeld = 0')
        if ir < 0 or il < 0 or ir > il:
            p.append('the last close does not retire before it releases the latch')
    r['g52-ioctl'] = p

    # 2. the client is pure C -- the reason the rung exists
    p = []
    code = uncomment(dev)
    for bad, what in ((r'#\s*import\b', '#import'), (r'\bdriverkit/', 'a driverkit header'),
                      (r'\bIODeviceMaster\b', 'IODeviceMaster'), (r'@\s*(interface|implementation)\b',
                                                                  'an Objective-C declaration'),
                      (r'\bobjc_\w+', 'the Objective-C runtime')):
        if re.search(bad, code):
            p.append('the client uses %s' % what)
    if not re.search(r'#include\s+"osrdn_r7b\.h"', code):
        p.append('the client does not include the shared header')
    r['r7b-pure-c'] = p

    # 5. the binary latch: set on the way OUT of d_open (so a refusal cannot set it),
    # cleared in d_close, and a count is never used -- d_close comes on the LAST close
    # only, so opens minus closes is not how many hold the node.
    p = []
    code = uncomment(disp)
    m = re.search(r'\nrdnDevOpen\(.*?\n\}', code, re.S)
    body = m.group(0) if m else ''
    if not body:
        p.append('d_open is not there')
    else:
        refuse = body.find('return ENXIO;')
        latch = body.find('rdnR7bHeld = 1')
        if latch < 0:
            p.append('d_open never takes the latch')
        elif refuse < 0 or latch < refuse:
            p.append('d_open takes the latch before it has finished refusing')
        if 'rdnR7bHeld' not in body.split('return ENXIO;')[0]:
            p.append('d_open does not consult the latch')
    m = re.search(r'\nrdnDevClose\(.*?\n\}', code, re.S)
    if not m or 'rdnR7bHeld = 0' not in m.group(0):
        p.append('d_close does not release the latch')
    if re.search(r'rdnR7bHeld\s*(\+\+|--|\+=|-=)', code):
        p.append('the latch is counted, not latched')
    r['r7b-latch'] = p

    # 6. the judge reads the lines the DRIVER writes.  Renaming a field in one and
    # not the other leaves a judge that quietly sees nothing -- which is how a run
    # was lost (10-10).  So render each R7B format with stand-in values and require
    # the judge's own sample boot to contain the result.
    p = []
    try:
        jtext = open(JUDGE).read()
    except IOError:
        jtext = ''
    if not jtext:
        p.append('the R7b judge is not there')
    else:
        good = re.search(r'GOOD = """(.*?)"""', jtext, re.S)
        good = good.group(1) if good else ''
        for m in re.finditer(r'IOLog\(((?:\s*"[^"]*")+)', uncomment(disp)):
            fmt = ''.join(re.findall(r'"([^"]*)"', m.group(1)))
            if not fmt.startswith('RDN-R7B '):
                continue
            skeleton = re.sub(r'%-?0?\d*[xudsu]', '@', fmt).replace('\\n', '').strip()
            # the same skeleton, taken from the judge's sample: field names and order
            names = re.findall(r'(\w+)=@', skeleton)
            # THE TAG IS A WHOLE WORD.  `startswith('RDN-R7B reject')` also
            # matches `RDN-R7B reject2 ...`, so the day M1p added reject2 the
            # older rule would have quietly checked the NEW line's fields and
            # called it the old one's.  Match the tag exactly.
            tag = skeleton.split()[0] + ' ' + skeleton.split()[1]
            hit = [l for l in good.splitlines()
                   if l.split()[:2] == tag.split()]
            if not hit:
                p.append('the judge\'s sample has no %s line' % ' '.join(skeleton.split()[:2]))
                continue
            got = re.findall(r'(\w+)=', hit[0])
            if names != got:
                p.append('%s: the driver writes %s, the judge\'s sample has %s'
                         % (' '.join(skeleton.split()[:2]), names, got))
    r['r7b-judge-reads-driver'] = p

    # 3. the tables are the oracle's
    p = []
    gp, gc, gf = table_block(gen)
    for label, text in (('rdnr7dev.c', dev), ('rdnr7sub.m', sub)):
        tp, tc, tf = table_block(text)
        if tp != gp:
            p.append('%s: the word pool is not the generated one' % label)
        if tc != gc:
            p.append('%s: the case table is not the generated one' % label)
        if tf != gf:
            p.append('%s: the fixup mask is not the generated one' % label)
    r['r7b-generated'] = p
    return r


SELFTEST = [
    ('a block grows past the length the encoding can carry', 'hdr',
     '    unsigned long winStart;',
     '    unsigned long winStart;\n' + '    unsigned long pad%d;\n' * 25 % tuple(range(25)),
     'r7b-ioctl', None),
    ('SUBMIT stops asking for its own length', 'hdr',
     '((sizeof(osrdn_r7b_submit) & OSRDN_R7B_IOC_PARM_MASK) << 16)', '(32UL << 16)', 'r7b-ioctl', None),
    ('CAPS copies in as well as out', 'hdr',
     '#define OSRDN_R7B_IOC_CAPS      ((unsigned long)(OSRDN_R7B_IOC_OUT |',
     '#define OSRDN_R7B_IOC_CAPS      ((unsigned long)(OSRDN_R7B_IOC_IN | OSRDN_R7B_IOC_OUT |',
     'r7b-ioctl', None),
    ('the client reaches for Objective-C', 'dev',
     '#include <stdio.h>', '#import <driverkit/IODeviceMaster.h>\n#include <stdio.h>',
     'r7b-pure-c', None),
    ('one word of the pool is typed over', 'dev', None, None, 'r7b-generated', 'pool'),
    ('a case row is typed over', 'dev', None, None, 'r7b-generated', 'cases'),
    ('a fixup bit is typed over', 'sub', None, None, 'r7b-generated', 'fix'),
    ('K8: SUBMIT2 bounds the stream by the page again', 'disp',
     '    else if (n == 0UL || n > OSRDN_R7B_MAX_WORDS)\n        why = "count";                  /* G4-4 K8',
     '    else if (n == 0UL || n > OSRDN_R7B_MAX_WORDS || n > OSRDN_R7B_WINDOW_WORDS)\n        why = "count";                  /* G4-4 K8',
     'r7b-submit2-chunked', None),
    ('K8: the stream is copied whole, outside the loop, as well', 'disp',
     '        while (staged && k < n) {\n            take = n - k;\n            if (take > (unsigned long)CP_R7_APPEND_MAX)\n                take = (unsigned long)CP_R7_APPEND_MAX;\n            if (copyin(',
     '        (void)copyin((const void *)sb->words, (void *)rdnR7bVirt, (unsigned int)(n * 4UL));\n        while (staged && k < n) {\n            take = n - k;\n            if (take > (unsigned long)CP_R7_APPEND_MAX)\n                take = (unsigned long)CP_R7_APPEND_MAX;\n            if (copyin(',
     'r7b-submit2-chunked', None),
    ('K8: the copyin path grows its own tail again', 'disp',
     '    [self r7bRun:&old words:n staged:staged op:op];',
     '    quiet = osrdn_cp_quiet_take(&rdnCp);\n    [self r7bRun:&old words:n staged:staged op:op];',
     'r7b-submit2-chunked', None),
    ('G5-2: SUBMIT3 waits like SUBMIT2', 'disp',
     'r7bSubmit2:(osrdn_r7b_submit2 *)data op:CP_OP_ASUBMIT]', 'r7bSubmit2:(osrdn_r7b_submit2 *)data op:CP_OP_ZCLEAR]',
     'g52-ioctl', None),
    ('G5-2: the last close forgets what is in flight', 'disp',
     '    if (rdnR7bInstance != nil && [rdnR7bInstance r7bCloseRetire])\n        rdnCloseRetires++;\n', '',
     'g52-ioctl', None),
    ('G5-2: RETIRE takes SUBMIT3\'s ordinal', 'hdr',
     "((unsigned long)OSRDN_R7B_IOC_GROUP << 8) | 7UL))", "((unsigned long)OSRDN_R7B_IOC_GROUP << 8) | 6UL))",
     'g52-ioctl', None),
    ('the latch is taken before the refusal is done', 'disp',
     '    rdnR7bHeld = 1;                     /* last: a refusal above changes nothing */',
     '    /* moved */', 'r7b-latch', None),
    ('d_close does not release the latch', 'disp',
     '    rdnR7bHeld = 0;\n', '', 'r7b-latch', None),
    ('the latch becomes a count', 'disp',
     '    rdnR7bHeld = 1;', '    rdnR7bHeld++;', 'r7b-latch', None),
    ('a field is renamed in the driver but not in the judge', 'disp',
     'RDN-R7B submit boot=%08x words=%u rc=', 'RDN-R7B submit boot=%08x nwords=%u rc=',
     'r7b-judge-reads-driver', None),
    # M1q: the SECOND reject line is checked too.  It was added by M1p and the
    # judge's sample did not carry it, which check-all reported and nobody read
    # -- and `startswith('RDN-R7B reject')` would have matched `reject2` anyway.
    ('the SECOND reject line is renamed in the driver only', 'disp',
     'RDN-R7B reject2 boot=%08x words=%u', 'RDN-R7B reject2 boot=%08x nwords=%u',
     'r7b-judge-reads-driver', None),
    ('an R7B line wears the operation line\'s shape', 'disp',
     'RDN-R7B submit boot=%08x words=%u rc=', 'RDN-R7B submit boot=%08x n=%u rc=',
     'r7b-line-shape', None),
]


def mutate(kind, dev, sub, which):
    """flip one number in a generated table, whichever file it lives in"""
    text = dev if kind == 'dev' else sub
    if which == 'pool':
        i = text.index('cpR7Pool[')
        j = text.index('0x', i)
        return text[:j] + '0xdeadbee0' + text[j + 10:]
    if which == 'cases':
        i = text.index('cpR7Cases[')
        m = re.search(r'\{\s*(\d+),', text[i:])
        k = i + m.start(1)
        return text[:k] + str(int(m.group(1)) + 1) + text[k + len(m.group(1)):]
    i = text.index('cpR7Fix[')
    m = re.search(r'\b([01])\b', text[i:])
    k = i + m.start(1)
    return text[:k] + ('0' if m.group(1) == '1' else '1') + text[k + 1:]


def main():
    hdr, dev, sub = open(HDR).read(), open(DEV).read(), open(SUB).read()
    disp = open(DISP).read()
    gen = generated()

    if '--write' in sys.argv:
        a, b = dev.index(BEGIN) + len(BEGIN), dev.index(END)
        open(DEV, 'w').write(dev[:a] + '\n' + gen.rstrip('\n') + '\n' + dev[b:])
        print('rdnr7dev.c: case tables regenerated')
        return 0

    fails = 0
    r = rules(hdr, dev, sub, gen, disp)
    for line in r.pop('r7b-numbers', []):
        print('    --   %s' % line)
    for name in sorted(r):
        for problem in r[name]:
            print('    FAIL %-14s %s' % (name, problem))
            fails += 1
        if not r[name]:
            print('    ok   %-14s' % name)

    if '--self-test' in sys.argv:
        for label, kind, old, new, want, which in SELFTEST:
            h, d, s, dd = hdr, dev, sub, disp
            if which is not None:
                if kind == 'dev':
                    d = mutate(kind, dev, sub, which)
                else:
                    s = mutate(kind, dev, sub, which)
            else:
                src = {'hdr': hdr, 'dev': dev, 'sub': sub, 'disp': disp}[kind]
                if src.count(old) != 1:
                    print('    FAIL self-test %-52s anchor found %d times' % (label, src.count(old)))
                    fails += 1
                    continue
                src = src.replace(old, new)
                h, d, s, dd = hdr, dev, sub, disp
                if kind == 'hdr':
                    h = src
                elif kind == 'dev':
                    d = src
                elif kind == 'sub':
                    s = src
                else:
                    dd = src
            got = rules(h, d, s, gen, dd)
            got.pop('r7b-numbers', None)
            caught = [k for k, v in got.items() if v]
            if want in caught:
                print('    ok   mutation %-52s %s' % (label, caught))
            else:
                print('    FAIL mutation %-52s caught by %s, want %s' % (label, caught, want))
                fails += 1

    print('check_r7b: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
