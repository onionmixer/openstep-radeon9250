#!/usr/bin/env python3
"""G4-8 (docs/G4_8_REPLAY_PLAN.md 3): the replay tool's source rules, its allow table against the
oracle's, and the recorded stream (and every prefix the bisection may use) against the tool's walk.
  check_replay.py            the rules on the real files
  check_replay.py --self-test  each rule with a mutation it must catch
"""
import importlib.util
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(HERE, 'rdnreplay.c')
STREAM = os.path.join(PROJ, 'build', 'g46', 'trace-last.bin')
STREAM_WORDS = 4067                     # trace.txt record 0x4c1: words 0xfe3; the file's last word is residue
PREFIXES = [60, 1473, 1565, 1659, 2511, 4067]   # the PACKET3 starts and the end (docs/G4_8_REPLAY_PLAN.md 1 P6)
# G4-8 9: the twin of the frozen stream with the MIN field of every PP_TXFILTER_0 write changed from the
# blend value 6 (hw 0xc) to NEAREST_MIPMAP_NEAREST 2 (hw 0x4); same length, same packets, same surfaces
TWIN = os.path.join(PROJ, 'build', 'g48', 'trace-last-nmn.bin')
# G4-8 13: the second twin, MIN 6 -> 7 (GL LINEAR_MIPMAP_LINEAR: linear texel, linear between mips)
TWINS = [(TWIN, 2), (os.path.join(PROJ, 'build', 'g48', 'trace-last-lml.bin'), 7),
         (os.path.join(PROJ, 'build', 'g48', 'trace-last-full.bin'), 'full')]   # G4-8 13-1: MAX_MIP_LEVEL raised to the full chain
# G4-8 14: twin 4 = twin 2 (MIN 2) with MAG_FILTER_LINEAR (bit 0) -- more texel fetches, no level blend
TWIN4 = os.path.join(PROJ, 'build', 'g48', 'trace-last-nmn-maglin.bin')
PP_TXFILTER_0 = 0x2c00
RB3D_COLOROFFSET = 0x1c40


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def walk(words, n):
    """the tool's walk: (ok, colour offset seen, registers written); ok only when it ends exactly at n"""
    i, colour, regs = 0, None, []
    while i < n:
        h = words[i]
        t = h >> 30
        if t == 0:
            cnt = ((h >> 16) & 0x3fff) + 1
            reg = (h & 0x1fff) << 2
            one = (h >> 15) & 1
            if i + 1 + cnt > n:
                return False, colour, regs
            for k in range(cnt):
                r = reg if one else reg + 4 * k
                regs.append(r)
                if r == RB3D_COLOROFFSET:
                    colour = words[i + 1 + k]
            i += 1 + cnt
        elif t == 3:
            cnt = ((h >> 16) & 0x3fff) + 1
            i += 1 + cnt
        elif t == 2:
            i += 1
        else:
            return False, colour, regs
    return i == n, colour, regs


def rules(src, stream_words, twin_words=None):
    vo = _load('verify_oracle', os.path.join(PROJ, 'tools', 'r7', 'verify_oracle.py'))
    r = {}
    # 1. the allow table is the oracle's
    p = []
    m = re.search(r'static const unsigned short allow\[(\d+)\] = \{(.*?)\};', src, re.S)
    if not m:
        p.append('no allow table')
    else:
        got = [int(x, 0) for x in re.findall(r'0x[0-9a-fA-F]+', m.group(2))]
        if got != vo.ALLOW or int(m.group(1)) != len(vo.ALLOW):
            p.append('allow table has %d registers, the oracle derives %d' % (len(got), len(vo.ALLOW)))
    r['g48-allow'] = p
    # 2. the stream and its prefixes end on packet boundaries, the oracle accepts the whole, the surfaces are inside
    p = []
    for n in PREFIXES:
        ok, colour, regs = walk(stream_words, n)
        if not ok:
            p.append('prefix %d does not end on a packet boundary' % n)
        if colour != 0x400000:
            p.append('prefix %d: RB3D_COLOROFFSET seen %s, want 0x400000' % (n, colour))
        bad = sorted(set(x for x in regs if x not in vo.ALLOW))
        if bad:
            p.append('prefix %d writes registers outside the allow list: %s' % (n, ['%#06x' % x for x in bad][:4]))
    why, note = vo.verify(stream_words[:STREAM_WORDS], 0x400000, 0x7c00000)
    if why != vo.WHY_OK:
        p.append('the oracle refuses the whole stream: %s %s' % (why, note))
    r['g48-stream'] = p
    # 4. the twins: identical to the recorded stream except the MIN field of the TXFILTER writes (6 -> want)
    p = []
    for twin_path, want_min in ([(TWIN, 2)] if twin_words is not None else TWINS):
        twin = twin_words if twin_words is not None else (
            list(struct.unpack('<%dI' % STREAM_WORDS, open(twin_path, 'rb').read()[:4 * STREAM_WORDS])) if os.path.exists(twin_path) else [])
        if len(twin) != STREAM_WORDS:
            p.append('no twin stream of %d words at %s' % (STREAM_WORDS, os.path.basename(twin_path)))
            continue
        ok, colour, regs = walk(twin, STREAM_WORDS)
        if not ok or colour != 0x400000:
            p.append('the twin does not walk like the original')
        diff = [i for i in range(STREAM_WORDS) if twin[i] != stream_words[i]]
        fields = {}
        i = 0
        while i < STREAM_WORDS:                       # where the TXFILTER_0 values sit
            h = stream_words[i]
            if (h >> 30) == 0:
                cnt = ((h >> 16) & 0x3fff) + 1
                reg = (h & 0x1fff) << 2
                one = (h >> 15) & 1
                for k in range(cnt):
                    if (reg if one else reg + 4 * k) == PP_TXFILTER_0:
                        fields[i + 1 + k] = stream_words[i + 1 + k]
                i += 1 + cnt
            elif (h >> 30) == 3:
                i += 1 + ((h >> 16) & 0x3fff) + 1
            else:
                i += 1
        for d in diff:
            if d not in fields:
                p.append('the twin differs at word %d, which is not a TXFILTER_0 value' % d)
            elif want_min == 'full':
                if (stream_words[d] & ~0xf0000) != (twin[d] & ~0xf0000) or ((twin[d] >> 16) & 0xf) not in (6, 7) or \
                        ((twin[d] >> 16) & 0xf) <= ((stream_words[d] >> 16) & 0xf):
                    p.append('the full-chain twin changes more than MAX_MIP_LEVEL (raised to 6 or 7) at word %d: %08x -> %08x' % (d, stream_words[d], twin[d]))
            elif (stream_words[d] & ~0x1e) != (twin[d] & ~0x1e) or ((stream_words[d] >> 1) & 0xf) != 6 or ((twin[d] >> 1) & 0xf) != want_min:
                p.append('the twin changes more than MIN 6 -> %d at word %d: %08x -> %08x' % (want_min, d, stream_words[d], twin[d]))
        if not diff:
            p.append('the twin is identical to the original')
        why, note = vo.verify(twin, 0x400000, 0x7c00000)
        if why != vo.WHY_OK:
            p.append('the oracle refuses the twin: %s %s' % (why, note))
    if twin_words is None and os.path.exists(TWIN4) and os.path.exists(TWIN):
        t2 = list(struct.unpack('<%dI' % STREAM_WORDS, open(TWIN, 'rb').read()[:4 * STREAM_WORDS]))
        t4 = list(struct.unpack('<%dI' % STREAM_WORDS, open(TWIN4, 'rb').read()[:4 * STREAM_WORDS]))
        diff = [i for i in range(STREAM_WORDS) if t2[i] != t4[i]]
        for d in diff:
            if (t2[d] | 1) != t4[d] or ((t2[d] >> 1) & 0xf) != 2:
                p.append('twin 4 changes more than MAG NEAREST -> LINEAR at word %d: %08x -> %08x' % (d, t2[d], t4[d]))
        if not diff:
            p.append('twin 4 is identical to twin 2')
        why, note = vo.verify(t4, 0x400000, 0x7c00000)
        if why != vo.WHY_OK:
            p.append('the oracle refuses twin 4: %s %s' % (why, note))
    r['g48-twin'] = p
    # 3. source rules
    p = []
    if re.search(r'\bmmap\s*\(', src):
        p.append('the tool maps the window (SUBMIT2 copies from the client buffer; no mmap)')
    if re.search(r'OSRDN_R7B_IOC_SUBMIT\b(?!2)', src):
        p.append('the tool uses the old SUBMIT')
    if re.search(r'^\s*#import', src, re.M):     # the directive, not the word in a comment
        p.append('an #import: the tool must stay pure C')
    for m2 in re.finditer(r'printf\("([^"]*)', src):
        if not m2.group(1).startswith('RDNREPLAY '):
            p.append('a printf that does not start with RDNREPLAY: %r' % m2.group(1)[:30])
    if '% 4000000UL) * 1000UL' not in src:
        p.append('the seed is not (runid mod 4000000) * 1000 + k + 1 (docs/G4_8_REPLAY_PLAN.md 2-3, C3)')
    i_caps = src.find('OSRDN_R7B_IOC_CAPS')
    i_loop = src.find('for (k = 0UL; k < reps; k++)')
    i_close = src.find('(void)close(fd);                /* C2', i_caps)
    if i_caps < 0 or i_loop < 0 or i_close < 0 or not (i_caps < i_close < i_loop):
        p.append('the CAPS fd is not closed before the repetition loop (C2)')
    if not re.search(r'if \(rc != 0\)', src):
        p.append('the ioctl return value is not checked (C4)')
    if 'sub.status != 0UL || sub.why != 0UL' not in src or 'sub.drawn == 0UL' not in src:
        p.append("the library's success test (status, why, drawn) is not copied")
    if 'fsync(crumbFd)' not in src:
        p.append('crumbs are not fsynced')
    r['g48-source'] = p
    return r


def real():
    src = open(SRC).read()
    b = open(STREAM, 'rb').read()
    words = list(struct.unpack('<%dI' % (len(b) // 4), b))
    r = rules(src, words)
    bad = 0
    for k in sorted(r):
        for x in r[k]:
            print('  FAIL %-12s %s' % (k, x))
            bad += 1
        if not r[k]:
            print('  ok   %s' % k)
    return bad


def self_test():
    src = open(SRC).read()
    b = open(STREAM, 'rb').read()
    words = list(struct.unpack('<%dI' % (len(b) // 4), b))
    twin = list(struct.unpack('<%dI' % STREAM_WORDS, open(TWIN, 'rb').read()[:4 * STREAM_WORDS]))
    base = rules(src, words)
    bad = sum(len(v) for v in base.values())
    print('  %-4s the real files pass (%d findings)' % ('ok' if not bad else 'FAIL', bad))
    muts = [
        ('g48-allow', 'the allow table loses a register', src.replace('0x1c14, ', '', 1), words),
        ('g48-stream', 'a prefix cut inside a packet', src, words, [61]),
        ('g48-stream', 'a stream whose colour surface is elsewhere', src,
         [w if w != 0x400000 else 0x500000 for w in words]),
        ('g48-source', 'the tool maps the window', src + '\n/* */ mmap(0, 0, 0, 0, 0, 0);', words),
        ('g48-source', 'an #import directive', src + '\n#import <foo.h>\n', words),
        ('g48-source', 'the old SUBMIT', src.replace('OSRDN_R7B_IOC_SUBMIT2', 'OSRDN_R7B_IOC_SUBMIT', 1), words),
        ('g48-source', 'a printf without the prefix', src + '\nprintf("hello");', words),
        ('g48-source', 'the seed is runid + k', src.replace('% 4000000UL) * 1000UL', '+ 0UL) * 1UL', 1), words),
        ('g48-source', 'the CAPS fd stays open', src.replace('(void)close(fd);                /* C2', '/* kept */', 1), words),
        ('g48-source', 'the ioctl return value is ignored', src.replace('if (rc != 0)', 'if (0)', 1), words),
        ('g48-source', 'drawn is not tested', src.replace('sub.drawn == 0UL', 'sub.drawn == 99UL', 1), words),
        ('g48-source', 'crumbs without fsync', src.replace('fsync(crumbFd)', 'fsync(-1)'), words),
        ('g48-twin', 'the twin changes a word that is not a filter', src, words, None, twin[:100] + [twin[100] ^ 1] + twin[101:]),
        ('g48-twin', 'the twin changes MAX_MIP_LEVEL too', src, words, None, [v ^ 0x10000 if v == 0x00040004 else v for v in twin]),
        ('g48-twin', 'the twin is the original', src, words, None, list(words[:STREAM_WORDS])),
    ]
    for m in muts:
        rule, name, s, w = m[0], m[1], m[2], m[3]
        global PREFIXES
        saved = PREFIXES
        if len(m) > 4 and m[4] is not None:
            PREFIXES = m[4]
        r = rules(s, w, m[5] if len(m) > 5 else None)
        PREFIXES = saved
        caught = bool(r[rule])
        print('  %-4s mutation %-45s %s' % ('ok' if caught else 'FAIL', name, 'caught' if caught else 'MISSED'))
        bad += 0 if caught else 1
    print('check_replay self-test: %s' % ('PASS' if not bad else 'FAIL (%d)' % bad))
    return bad


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        sys.exit(1 if self_test() else 0)
    bad = real()
    print('check_replay: %s' % ('PASS' if not bad else 'FAIL (%d)' % bad))
    sys.exit(1 if bad else 0)
