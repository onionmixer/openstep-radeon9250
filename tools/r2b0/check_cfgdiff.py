#!/usr/bin/env python3
"""Judge instance-table snapshots around a Configure.app activation (docs/R2B0_IMPL_PLAN.md 7-3).

  check_cfgdiff.py precheck <pre> --pcils <file>      one snapshot, before anything changes
  check_cfgdiff.py activate <pre> <post>              VGA -> OSRDNDisplay by Configure
  check_cfgdiff.py same <a> <b>                       nothing changed between a and b
  check_cfgdiff.py restored <pre> <after-restore>     the set restore brought pre back
  check_cfgdiff.py record <a> <b>                     print the differences, no verdict
  check_cfgdiff.py --self-test

A snapshot directory is what tools/r2b0/target-cfgsnap-r2b0.sh wrote (copied
tables, LIST, SNAP).  Every copy is first checked against LIST: BSD sum and
byte count (the NFS stale-size trap), and SNAP must say closed=yes.

Tables are parsed strictly: a line is `"key" = "value";`, a /* */ comment
(may span lines) or blank; anything else, a duplicate key or a non-ASCII
byte refuses the snapshot.  Configure rewrites tables with the keys in
another order (build/r2b0/emu10k1, 2026-09-15), so tables are compared as
key -> value maps; "same" and "restored" also compare bytes, because the
restore writes the snapshot's own bytes back.

On PASS, precheck, activate, same and restored write PRECHECK_PASS,
ACTIVATE_PASS, SAME_PASS and RESTORED_PASS into the later snapshot directory;
tools that act on a snapshot require the marker, and a skipped gate is
visible by its missing marker.
"""

import importlib.util
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
SHIPPED = os.path.join(PROJ, 'OSRDNDisplay', 'Default.table')
DRIVER = 'OSRDNDisplay'
DRIVER_TABLE = 'OSRDNDisplay.config/Instance0.table'
RADEON_LOCATION = 'Dev:11 Func:0 Bus:3'
ALLOWED_DRIVER_DIFF = {'Location', 'Default Table'}
# Configure rewrites a table it touches with root's umask; our bundle's tables
# are 444 because the driverkit postamble chmods them.  That one transition is
# a NOTE, everything else about owner, group or mode is a failure.
ALLOWED_MODE_CHANGE = {('-r--r--r--', '-rw-r--r--')}
# The driverkit bundle postamble appends `"Server Name" = "$(NAME)";` to every
# table in the built bundle (ref/openstep/makefiles/NextDeveloper/Makefiles/
# driverkit/Makefile.bundle_postamble:1-6), so the installed table carries one
# key the repository's source table must NOT hold: a second copy would be a
# duplicate key.  In user space a table is an NXStringTable
# (driverkit/IOConfigTable.h), which is a HashTable whose insertKey:value:
# UPDATES an existing key -- so the last value wins there, while what the
# kernel side does with a duplicate is not established.  An ambiguous table
# is not shipped: every stock i386 driver table has the key exactly once.
# The expected map is the source plus this.
POSTAMBLE = {'Server Name': DRIVER}
# A PCI Location that names a slot holding a different card is normally a
# problem.  The one exception this project carried (Adaptec2940SCSIDriver
# pointing at the Radeon's slot) was CLEANED UP on 2026-09-16: the table now
# says Location "" and PCIBus scans for the card, which is not in this
# machine.  The table is kept empty rather than exempted, so this set is empty
# and any stale Location fails again.
STALE_PCI_LOCATION_OK = {}



def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


pk = _load('pack_r1_for_cfgdiff', os.path.join(PROJ, 'tools', 'r1', 'pack_probe.py'))


class Refused(Exception):
    pass


def parse_table(data, name):
    """{key: value} from table bytes, or Refused."""
    if any(b > 0x7e or (b < 0x20 and b not in (9, 10)) for b in data):
        raise Refused('%s: non-ASCII or control byte' % name)
    text = data.decode('ascii')
    kv = {}
    rest = text
    pos = 0
    line_re = re.compile(r'[ \t]*"([^"\n]*)"[ \t]*=[ \t]*"([^"\n]*)"[ \t]*;[ \t]*')
    while pos < len(rest):
        if rest.startswith('\n', pos):
            pos += 1
            continue
        m = re.compile(r'[ \t]+').match(rest, pos)
        if m and m.end() > pos:
            pos = m.end()
            continue
        if rest.startswith('/*', pos):
            end = rest.find('*/', pos + 2)
            if end < 0:
                raise Refused('%s: unterminated comment' % name)
            pos = end + 2
            continue
        m = line_re.match(rest, pos)
        if not m:
            lineno = rest[:pos].count('\n') + 1
            raise Refused('%s:%d: not a table line: %r' % (name, lineno, rest[pos:rest.find('\n', pos)][:60]))
        k, v = m.group(1), m.group(2)
        if k in kv:
            raise Refused('%s: duplicate key %r' % (name, k))
        kv[k] = v
        pos = m.end()
    return kv


def expected_driver_kv(data, name):
    """The keys an installed OSRDNDisplay table must have: the source table's,
    plus what the bundle postamble appends at build time."""
    kv = parse_table(data, name)
    both = sorted(set(kv) & set(POSTAMBLE))
    if both:
        raise Refused('%s holds %s, which the bundle postamble appends: the built table would have it twice'
                      % (name, both))
    kv.update(POSTAMBLE)
    return kv


def load_snap(d):
    """{rel: dict(data, kv, ls, owner, group)}; Refused on any inconsistency."""
    snap = os.path.join(d, 'SNAP')
    lst = os.path.join(d, 'LIST')
    if not os.path.exists(snap) or not os.path.exists(lst):
        raise Refused('%s: no SNAP or LIST (snapshot incomplete)' % d)
    s = open(snap).read()
    if 'operator=closed=yes' not in s:
        raise Refused('%s: SNAP does not record closed=yes' % d)
    out = {}
    for n, line in enumerate(open(lst).read().splitlines(), 1):
        f = line.split()
        if len(f) != 7:
            raise Refused('%s LIST:%d: %d fields, want 7' % (d, n, len(f)))
        rel, ls, owner, group, s1, s2, nbytes = f
        if rel in out:
            raise Refused('%s LIST: %s twice' % (d, rel))
        if not re.fullmatch(r'[A-Za-z0-9._-]+\.config/(Instance[0-9]{1,2}|Default)\.table', rel):
            raise Refused('%s LIST: odd path %s' % (d, rel))
        if rel.endswith('/Default.table') and rel != 'System.config/Default.table':
            raise Refused('%s LIST: a Default.table other than System\'s: %s' % (d, rel))
        path = os.path.join(d, rel)
        if not os.path.exists(path):
            raise Refused('%s: LIST names %s but there is no copy' % (d, rel))
        data = open(path, 'rb').read()
        if len(data) != int(nbytes):
            raise Refused('%s: copy of %s has %d bytes, target said %s' % (d, rel, len(data), nbytes))
        if pk.bsdsum(data).split() != [str(int(s1)), str(int(s2))] and \
                [int(x) for x in pk.bsdsum(data).split()] != [int(s1), int(s2)]:
            raise Refused('%s: copy of %s sums %s, target said %s %s' % (d, rel, pk.bsdsum(data), s1, s2))
        if not re.fullmatch(r'-[r-][w-][x-][r-][w-][x-][r-][w-][x-]', ls):
            raise Refused('%s LIST: mode %r of %s' % (d, ls, rel))
        out[rel] = dict(data=data, kv=parse_table(data, rel), ls=ls, owner=owner, group=group)
    m = re.search(r'tables=(\d+)', s)
    if not m or int(m.group(1)) != len(out):
        raise Refused('%s: SNAP says %s tables, LIST has %d' % (d, m.group(1) if m else '?', len(out)))
    # every copied file is in LIST
    for root, _, files in os.walk(d):
        for fn in files:
            rel = os.path.relpath(os.path.join(root, fn), d)
            if rel not in ('LIST', 'SNAP') and not rel.endswith('_PASS') and rel not in out:
                raise Refused('%s: %s is not in LIST' % (d, rel))
    return out


def instances(snap):
    return dict((r, v) for r, v in snap.items() if not r.endswith('/Default.table'))


def perm_problems(snap, label):
    p = []
    for rel, v in sorted(snap.items()):
        if v['owner'] != 'root' or v['group'] != 'wheel':
            p.append('%s %s: owner %s.%s, want root.wheel' % (label, rel, v['owner'], v['group']))
        if v['ls'][5] == 'w' or v['ls'][8] == 'w':
            p.append('%s %s: mode %s is group- or other-writable' % (label, rel, v['ls']))
    return p


def active_drivers(snap):
    t = snap.get('System.config/Instance0.table')
    if t is None or 'Active Drivers' not in t['kv']:
        raise Refused('System.config/Instance0.table or its Active Drivers is missing')
    return t['kv']['Active Drivers'].split()


def kv_diff(a, b):
    """[(key, a value or None, b value or None)]"""
    out = []
    for k in sorted(set(a) | set(b)):
        if a.get(k) != b.get(k):
            out.append((k, a.get(k), b.get(k)))
    return out


def parse_pcils(text):
    """{'bb:dd.f': 'vvvvdddd' id word as Auto Detect IDs writes it (device<<16|vendor)}"""
    out = {}
    for line in text.splitlines():
        m = re.match(r'^([0-9a-f]{2}:[0-9a-f]{2}\.[0-7]) .*\[([0-9a-f]{4}):([0-9a-f]{4})\]', line)
        if m:
            out[m.group(1)] = int(m.group(3), 16) << 16 | int(m.group(2), 16)
    return out


def auto_detect_ids(value):
    """[(id, mask)] from an "Auto Detect IDs" value, or None for a token this
    does not understand.  A token is 0xIIIIIIII, optionally &0xMMMMMMMM (the
    installed Adaptec2940SCSIDriver table writes 0x00789004&0x00ffffff)."""
    out = []
    for tok in value.split():
        m = re.fullmatch(r'0x([0-9a-fA-F]{1,8})(?:&0x([0-9a-fA-F]{1,8}))?', tok)
        if not m:
            return None
        out.append((int(m.group(1), 16), int(m.group(2), 16) if m.group(2) else 0xffffffff))
    return out


def id_matches(word, ids):
    for i, mask in ids:
        if word & mask == i & mask:
            return True
    return False


def mode_precheck(pre, pcils_text, pcils_name):
    """[problems], [notes]"""
    p = []
    notes = []
    inst = instances(pre)
    bundles = {}
    for rel in inst:
        bundles.setdefault(rel.split('/')[0], []).append(rel)
    for b, rels in sorted(bundles.items()):
        if len(rels) != 1:
            p.append('%s has %d instance tables %s (the 2026-09-15 duplicate-VGA conflict)' % (b, len(rels), sorted(rels)))
    ad = active_drivers(pre)
    if ad.count('VGA') != 1:
        p.append('Active Drivers names VGA %d times: %s' % (ad.count('VGA'), ad))
    if DRIVER in ad:
        p.append('Active Drivers already names %s: %s' % (DRIVER, ad))
    if DRIVER_TABLE in pre:
        kv = pre[DRIVER_TABLE]['kv']
        if kv.get('RDN R2B0 Record') != 'Yes':
            p.append('%s is installed but says "RDN R2B0 Record" = %r' % (DRIVER_TABLE, kv.get('RDN R2B0 Record')))
        for k, v in sorted(POSTAMBLE.items()):
            if kv.get(k) != v:
                p.append('%s says %r = %r, want %r (the bundle postamble writes it)' % (DRIVER_TABLE, k, kv.get(k), v))
    devs = parse_pcils(pcils_text)
    if not devs:
        p.append('no device in the pcils capture %s' % pcils_name)
    for rel, v in sorted(inst.items()):
        kv = v['kv']
        loc = kv.get('Location', '')
        if kv.get('Bus Type') != 'PCI' or not loc:
            continue
        m = re.fullmatch(r'Dev:(\d+) Func:(\d+) Bus:(\d+)', loc)
        if not m:
            p.append('%s Location %r does not parse' % (rel, loc))
            continue
        bdf = '%02x:%02x.%x' % (int(m.group(3)), int(m.group(1)), int(m.group(2)))
        ids = auto_detect_ids(kv.get('Auto Detect IDs', ''))
        if ids is None:
            p.append('%s Auto Detect IDs %r: a token this does not understand'
                     % (rel, kv.get('Auto Detect IDs')))
            continue
        if bdf not in devs:
            p.append('%s Location %s: no device at %s in %s' % (rel, loc, bdf, pcils_name))
        elif not id_matches(devs[bdf], ids):
            # PCIBus then falls back to its own scan (plan S25), so this is a
            # stale Location rather than a driver bound to the wrong card
            why = STALE_PCI_LOCATION_OK.get((rel, loc, devs[bdf]))
            msg = '%s Location %s: the device at %s is %08x, not one of Auto Detect IDs %s' \
                  % (rel, loc, bdf, devs[bdf], kv.get('Auto Detect IDs'))
            if why:
                notes.append(msg + ' -- known and allowed: ' + why)
            else:
                p.append(msg + ' (stale Location: PCIBus scans instead)')
    p += perm_problems(pre, 'pre')
    return p, notes


def mode_activate(pre, post, expected_kv):
    """[problems], [notes]"""
    p = []
    notes = []
    added = sorted(set(post) - set(pre))
    removed = sorted(set(pre) - set(post))
    # the bundle ships an instance table, so the driver's table may be there
    # already (install put it there) or be created by Configure
    if added not in ([], [DRIVER_TABLE]):
        p.append('tables added %s, want none or exactly [%s]' % (added, DRIVER_TABLE))
    # An absolute rule, not a delta: a surplus instance table that was already
    # in pre is in neither set.  driverLoader opens Instance0, Instance1, ...
    # and stops at the first missing number, and when instance 0 is missing it
    # falls back to the bundle's Default.table and still configures a device
    # (driverLoader.bin 0x3bf4-0x3c54 and the loop 0x37d4-0x380f).  So the
    # invariant is one table AND that it is Instance0: parking Instance0 and
    # keeping Instance1 gives two devices on the one card.
    ours = sorted(r for r in post if r.startswith(DRIVER + '.config/'))
    if ours != [DRIVER_TABLE]:
        p.append('%s.config holds %s after the activation, want exactly [%s] (instance 0 missing makes '
                 'driverLoader fall back to Default.table AND still configure Instance1)'
                 % (DRIVER, ours, DRIVER_TABLE))
    elif DRIVER_TABLE not in post:
        p.append('%s does not exist after the activation' % DRIVER_TABLE)
    for rel in removed:
        if not rel.startswith('VGA.config/'):
            p.append('table removed that is not a VGA instance: %s' % rel)
        else:
            # allowed (Configure deletes it), but the VGA rescue driverLoader
            # falls back to then depends on VGA.config/Default.table, which no
            # snapshot can hold: look at the bundle before the reboot
            notes.append('%s was removed: if OSRDNDisplay registers no display, driverLoader loads VGA '
                         'from VGA.config/Default.table -- check that bundle before rebooting' % rel)
    for rel in sorted(set(pre) & set(post)):
        if rel == 'System.config/Default.table':
            if pre[rel]['data'] != post[rel]['data']:
                p.append('System.config/Default.table changed (the config=Default fallback)')
            continue
        if rel in ('System.config/Instance0.table', DRIVER_TABLE) or rel.startswith('VGA.config/'):
            continue
        d = kv_diff(pre[rel]['kv'], post[rel]['kv'])
        if d:
            p.append('%s changed key -> value: %s' % (rel, d[:3]))
    if 'System.config/Instance0.table' in pre and 'System.config/Instance0.table' in post:
        a, b = pre['System.config/Instance0.table']['kv'], post['System.config/Instance0.table']['kv']
        d = [x for x in kv_diff(a, b) if x[0] != 'Active Drivers']
        if d:
            p.append('System.config/Instance0.table changed beyond Active Drivers: %s' % d[:3])
        ad_pre, ad_post = active_drivers(pre), active_drivers(post)
        want = list(ad_pre)
        if 'VGA' in want:
            want[want.index('VGA')] = DRIVER
        if sorted(ad_post) != sorted(want):
            p.append('Active Drivers %s, want %s in any order' % (ad_post, want))
    if DRIVER_TABLE in post:
        kv = post[DRIVER_TABLE]['kv']
        d = [x for x in kv_diff(expected_kv, kv) if x[0] not in ALLOWED_DRIVER_DIFF]
        if d:
            p.append('%s differs from the shipped Default.table (plus the postamble keys) beyond %s: %s'
                     % (DRIVER_TABLE, sorted(ALLOWED_DRIVER_DIFF), d[:4]))
        if kv.get('RDN R2B0 Record') != 'Yes':
            p.append('%s says "RDN R2B0 Record" = %r: the record would be refused' % (DRIVER_TABLE, kv.get('RDN R2B0 Record')))
        if kv.get('Instance') != '0':
            p.append('%s Instance %r, want "0"' % (DRIVER_TABLE, kv.get('Instance')))
        if kv.get('Location', '') not in ('', RADEON_LOCATION):
            p.append('%s Location %r, want "" or %r' % (DRIVER_TABLE, kv.get('Location'), RADEON_LOCATION))
    p += perm_problems(post, 'post')
    # owner, group and mode of every table that survived, compared without
    # condition.  Configure rewrites tables it was not asked about, and on
    # 2026-09-16 it left our own table 444 -> 644; that one transition is
    # recorded, every other one fails.
    for rel in sorted(set(pre) & set(post)):
        a, b = pre[rel], post[rel]
        if (a['owner'], a['group']) != (b['owner'], b['group']):
            p.append('%s owner.group %s.%s -> %s.%s' % (rel, a['owner'], a['group'], b['owner'], b['group']))
        if a['ls'] != b['ls']:
            if (a['ls'], b['ls']) in ALLOWED_MODE_CHANGE:
                notes.append('%s mode %s -> %s (Configure rewrote the table)' % (rel, a['ls'], b['ls']))
            else:
                p.append('%s mode %s -> %s' % (rel, a['ls'], b['ls']))
    return p, notes


def mode_same(a, b):
    p = []
    if sorted(a) != sorted(b):
        p.append('file sets differ: only before %s, only after %s' % (sorted(set(a) - set(b)), sorted(set(b) - set(a))))
    for rel in sorted(set(a) & set(b)):
        if a[rel]['data'] != b[rel]['data']:
            p.append('%s bytes differ (key -> value %s)' % (rel, kv_diff(a[rel]['kv'], b[rel]['kv'])[:3]))
        for k in ('ls', 'owner', 'group'):
            if a[rel][k] != b[rel][k]:
                p.append('%s %s %s, was %s' % (rel, k, b[rel][k], a[rel][k]))
    return p


def mode_record(a, b):
    out = []
    for rel in sorted(set(a) | set(b)):
        if rel not in a:
            out.append('ADDED   %s %s' % (rel, sorted(b[rel]['kv'].items())))
        elif rel not in b:
            out.append('REMOVED %s' % rel)
        else:
            d = kv_diff(a[rel]['kv'], b[rel]['kv'])
            if d:
                out.append('CHANGED %s %s' % (rel, d))
            elif a[rel]['data'] != b[rel]['data']:
                out.append('REORDER %s (same keys and values, other bytes)' % rel)
            if (a[rel]['ls'], a[rel]['owner'], a[rel]['group']) != (b[rel]['ls'], b[rel]['owner'], b[rel]['group']):
                out.append('PERMS   %s %s -> %s' % (rel, (a[rel]['ls'], a[rel]['owner'], a[rel]['group']),
                                                  (b[rel]['ls'], b[rel]['owner'], b[rel]['group'])))
    return out


def run(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2, []
    mode = argv[1]
    notes = []
    try:
        if mode == 'precheck' and len(argv) == 5 and argv[3] == '--pcils':
            pre = load_snap(argv[2])
            p, notes = mode_precheck(pre, open(argv[4]).read(), argv[4])
            marker = os.path.join(argv[2], 'PRECHECK_PASS')
        elif mode in ('activate', 'same', 'restored', 'record') and len(argv) == 4:
            a, b = load_snap(argv[2]), load_snap(argv[3])
            if mode == 'record':
                return 0, mode_record(a, b)
            if mode == 'activate':
                p, notes = mode_activate(a, b, expected_driver_kv(open(SHIPPED, 'rb').read(), SHIPPED))
                marker = os.path.join(argv[3], 'ACTIVATE_PASS')
            else:
                p = mode_same(a, b)
                marker = os.path.join(argv[3], 'RESTORED_PASS' if mode == 'restored' else 'SAME_PASS')
        else:
            print(__doc__)
            return 2, []
    except Refused as e:
        return 1, ['REFUSED ' + str(e)]
    out = ['NOTE ' + x for x in notes]
    if p:
        return 1, out + ['FAIL ' + x for x in p]
    if marker:
        open(marker, 'w').write('%s PASS\n' % mode)
    return 0, out + ['%s PASS' % mode]


# ---- self-test -------------------------------------------------------------

EVIDENCE = os.path.join(PROJ, 'build', 'r2b0', 'emu10k1')


def make_snap(d, tables, owner=None, lsmode=None, closed=True, corrupt=None):
    """tables: {rel: bytes}.  Writes a snapshot the way target-cfgsnap does."""
    os.makedirs(d)
    lines = []
    for rel, data in sorted(tables.items()):
        os.makedirs(os.path.join(d, os.path.dirname(rel)), exist_ok=True)
        open(os.path.join(d, rel), 'wb').write(data)
        s = pk.bsdsum(data).split()
        o = (owner or {}).get(rel, 'root wheel')
        m = (lsmode or {}).get(rel, '-rw-r--r--')
        lines.append('%s %s %s %s %s %d' % (rel, m, o, s[0], s[1], len(data)))
    open(os.path.join(d, 'LIST'), 'w').write('\n'.join(lines) + '\n')
    open(os.path.join(d, 'SNAP'), 'w').write('operator=%s date=x tables=%d\n' % ('closed=yes' if closed else 'no', len(tables)))
    if corrupt:
        with open(os.path.join(d, corrupt), 'ab') as f:
            f.write(b'\n')


def self_test():
    failures = 0

    def check(label, ok, detail=''):
        nonlocal failures
        print('%-4s %s%s' % ('ok' if ok else 'FAIL', label, '' if ok else ' -- ' + detail))
        failures += not ok

    emu = open(os.path.join(EVIDENCE, 'EMU10K1.Instance0.after-configure-1456'), 'rb').read()
    emu_before = open(os.path.join(EVIDENCE, 'Instance0.table.expected-17199'), 'rb').read()
    system = open(os.path.join(EVIDENCE, 'System.Instance0.after-configure-1456'), 'rb').read()
    vga = open(os.path.join(EVIDENCE, 'VGA.Instance0.after-configure-1456'), 'rb').read()
    default_sys = b'"Active Drivers" = "PS2Mouse BusMouse SerialPointingDevice ParallelPort VGA";\n"Boot Drivers" = "PS2Keyboard";\n'
    shipped = open(SHIPPED, 'rb').read()

    # parser: the captured tables parse; key order is not a difference
    check('captured EMU10K1 table parses', len(parse_table(emu, 'emu')) == 19)
    check('reordered EMU10K1 tables are the same map',
          parse_table(emu, 'a') == parse_table(emu_before, 'b') and emu != emu_before)
    for label, bad in (('duplicate key', b'"a" = "1";\n"a" = "2";\n'),
                       ('duplicate key with the same value', b'"a" = "1";\n"a" = "1";\n'),
                       ('garbage line', b'"a" = "1";\nhello\n'),
                       ('non-ASCII', b'"a" = "\xc3\xa9";\n'), ('unterminated comment', b'/* x\n"a" = "1";\n'),
                       ('missing semicolon', b'"a" = "1"\n')):
        try:
            parse_table(bad, label)
            check('strict parser refuses ' + label, False, 'accepted')
        except Refused:
            check('strict parser refuses ' + label, True)
    # "Auto Detect IDs": plain words and the masked form the installed
    # Adaptec2940SCSIDriver table uses
    check('Auto Detect IDs: two plain words', auto_detect_ids('0x59601002 0x10198086') ==
          [(0x59601002, 0xffffffff), (0x10198086, 0xffffffff)])
    check('Auto Detect IDs: the masked form', auto_detect_ids('0x00789004&0x00ffffff') == [(0x00789004, 0x00ffffff)])
    check('Auto Detect IDs: a token not understood is None', auto_detect_ids('0x59601002 junk') is None)
    check('the mask decides the match', id_matches(0x50789004, auto_detect_ids('0x00789004&0x00ffffff')) and
          not id_matches(0x59601002, auto_detect_ids('0x00789004&0x00ffffff')) and
          not id_matches(0x50789004, auto_detect_ids('0x00789004')))
    matrox = os.path.join(os.path.dirname(PROJ), 'openstep-matrox-remade', 'OSMGADisplay', 'Default.table')
    if os.path.exists(matrox):
        check('Matrox Default.table with /* */ comments parses', 'Mesa Acceleration' in parse_table(open(matrox, 'rb').read(), 'mga'))

    ad_pre = parse_table(system, 's')['Active Drivers']
    system_post = system.replace(('"Active Drivers" = "%s";' % ad_pre).encode(),
                                 ('"Active Drivers" = "%s";' % ad_pre.replace('VGA', DRIVER)).encode())
    assert system_post != system
    # the build appends the postamble key to every table of the bundle, so what
    # is installed is the source table plus that line, and Configure's instance
    # is made from the installed Default.table
    postamble_lines = ''.join('"%s" = "%s";\n' % (k, v) for k, v in sorted(POSTAMBLE.items())).encode()
    installed = shipped + postamble_lines     # what target-install-r2b0.sh leaves in the bundle
    kv = parse_table(installed, 'installed')
    made = ''.join('"%s" = "%s";\n' % (k, kv[k]) for k in reversed(list(kv))) + '"Default Table" = "Default";\n'
    made = made.encode()
    check('the source table does not hold a postamble key', parse_table(shipped, 'shipped').keys() & POSTAMBLE.keys() == set())
    check('expected_driver_kv adds the postamble key', expected_driver_kv(shipped, 'shipped') == kv)
    try:
        expected_driver_kv(installed, 'source+postamble')
        check('expected_driver_kv refuses a source table that already holds it', False, 'accepted')
    except Refused as e:
        check('expected_driver_kv refuses a source table that already holds it', 'postamble appends' in str(e), str(e))
    pre_tables = {'System.config/Instance0.table': system, 'System.config/Default.table': default_sys,
                  'EMU10K1.config/Instance0.table': emu, 'VGA.config/Instance0.table': vga,
                  DRIVER_TABLE: installed}
    post_tables = {'System.config/Instance0.table': system_post, 'System.config/Default.table': default_sys,
                   'EMU10K1.config/Instance0.table': emu_before, DRIVER_TABLE: made}
    pcils = open(os.path.join(PROJ, 'logs-pcils-20260915.txt')).read()

    work = tempfile.mkdtemp(prefix='cfgdiff.', dir=os.environ.get('TMPDIR'))
    n = [0]

    def snap(tables, **kw):
        n[0] += 1
        d = os.path.join(work, 's%d' % n[0])
        make_snap(d, tables, **kw)
        return d

    def verdict(argv, pcils_text=None):
        if pcils_text is not None:
            pf = os.path.join(work, 'pcils%d.txt' % n[0])
            open(pf, 'w').write(pcils_text)
            argv = argv + ['--pcils', pf]
        return run(['check_cfgdiff.py'] + argv)

    pre = snap(pre_tables)
    rc, out = verdict(['precheck', pre], pcils)
    check('precheck on the captured tables passes (our bundle is installed, not active)',
          rc == 0 and os.path.exists(os.path.join(pre, 'PRECHECK_PASS')), str(out))
    rc, out = verdict(['precheck', snap(dict(pre_tables, **{DRIVER_TABLE: installed.replace(b'"RDN R2B0 Record" = "Yes"', b'"RDN R2B0 Record" = "No"')}))], pcils)
    check('precheck: the installed table without the opt-in key stops', rc == 1 and any('RDN R2B0 Record' in o for o in out), str(out))
    rc, out = verdict(['precheck', snap(dict(pre_tables, **{DRIVER_TABLE: shipped}))], pcils)
    check('precheck: an installed table without the postamble key stops',
          rc == 1 and any("'Server Name'" in o and 'postamble' in o for o in out), str(out))
    rc, out = verdict(['precheck', snap(dict(pre_tables, **{DRIVER_TABLE: shipped + b'"Server Name" = "VGA";\n'}))], pcils)
    check('precheck: an installed table naming another server stops',
          rc == 1 and any("'VGA'" in o for o in out), str(out))
    rc, out = verdict(['precheck', snap(dict(pre_tables, **{DRIVER_TABLE: installed + postamble_lines}))], pcils)
    check('precheck: the postamble key twice (the 2026-09-16 duplicate) is refused',
          rc == 1 and any('duplicate key' in o for o in out), str(out))
    dup = dict(pre_tables, **{'VGA.config/Instance1.table': vga})
    rc, out = verdict(['precheck', snap(dup)], pcils)
    check('precheck: two VGA instances stop', rc == 1 and any('2 instance tables' in o for o in out), str(out))
    stale = dict(pre_tables, **{'EMU10K1.config/Instance0.table': open(os.path.join(EVIDENCE, 'Instance0.table.orig'), 'rb').read()})
    rc, out = verdict(['precheck', snap(stale)], pcils)
    check('precheck: EMU10K1 Location at the Radeon slot stops', rc == 1 and any('not one of Auto Detect IDs' in o for o in out), str(out))
    # 0x99991102 & 0x0000ffff == 0x00021102 & 0x0000ffff (the vendor half)
    masked = emu.replace(b'"Auto Detect IDs" = "0x00021102"', b'"Auto Detect IDs" = "0x99991102&0x0000ffff"')
    assert masked != emu
    rc, out = verdict(['precheck', snap(dict(pre_tables, **{'EMU10K1.config/Instance0.table': masked}))], pcils)
    check('precheck: a masked Auto Detect ID that matches passes', rc == 0, str(out))
    # the allowed stale Location: the machine's own Adaptec table, and three
    # mutations that must bring the FAIL back
    adp = open(os.path.join(EVIDENCE, 'Adaptec2940.Instance0.20260916'), 'rb').read()
    adp_rel = 'Adaptec2940SCSIDriver.config/Instance0.table'
    # the 2026-09-16 cleanup: the machine's table now says Location "", so the
    # old one must fail again (the exception set is empty)
    rc, out = verdict(['precheck', snap(dict(pre_tables, **{adp_rel: adp}))], pcils)
    check('precheck: the old stale Adaptec Location stops (the exception is gone)',
          rc == 1 and any('not one of Auto Detect IDs' in o for o in out), str(out))
    rc, out = verdict(['precheck', snap(dict(pre_tables, **{adp_rel: adp.replace(b'"Location" = "Dev:11 Func:0 Bus:3";', b'"Location" = "";')}))], pcils)
    check('precheck: the cleaned-up Adaptec table passes', rc == 0, str(out))
    rc, out = verdict(['precheck', snap(dict(pre_tables, **{adp_rel: adp.replace(b'Dev:11', b'Dev:13')}))], pcils)
    check('precheck: the same table at another Location stops', rc == 1 and any('FAIL' in o for o in out), str(out))
    other_pcils = pcils.replace('[1002:5960]', '[1002:5961]')
    rc, out = verdict(['precheck', snap(dict(pre_tables, **{adp_rel: adp}))], other_pcils)
    check('precheck: another card in that slot stops', rc == 1 and any('FAIL' in o for o in out), str(out))
    rc, out = verdict(['precheck', snap(dict(pre_tables, **{'Sneak.config/Instance0.table': adp}))], pcils)
    check('precheck: the same stale Location under another bundle stops', rc == 1 and any('FAIL' in o for o in out), str(out))
    odd = emu.replace(b'"Auto Detect IDs" = "0x00021102"', b'"Auto Detect IDs" = "0x00021102|0xff"')
    rc, out = verdict(['precheck', snap(dict(pre_tables, **{'EMU10K1.config/Instance0.table': odd}))], pcils)
    check('precheck: an Auto Detect IDs token not understood stops',
          rc == 1 and any('does not understand' in o for o in out), str(out))
    rc, out = verdict(['precheck', snap(pre_tables, owner={'VGA.config/Instance0.table': 'me wheel'})], pcils)
    check('precheck: a table not owned by root stops', rc == 1 and any('owner me.wheel' in o for o in out), str(out))
    rc, out = verdict(['precheck', snap(pre_tables, closed=False)], pcils)
    check('snapshot without closed=yes is refused', rc == 1 and any('closed=yes' in o for o in out), str(out))
    rc, out = verdict(['precheck', snap(pre_tables, corrupt='EMU10K1.config/Instance0.table')], pcils)
    check('a copy that grew on NFS is refused', rc == 1 and any('bytes' in o for o in out), str(out))

    post = snap(post_tables)
    rc, out = verdict(['activate', pre, post])
    check('activate: Configure-like result passes (reorder, Default Table, VGA instance gone)', rc == 0, str(out))
    cases = [
        ('opt-in key No', dict(post_tables, **{DRIVER_TABLE: made.replace(b'"RDN R2B0 Record" = "Yes"', b'"RDN R2B0 Record" = "No"')}),
         {}, 'would be refused'),
        ('EMU10K1 value changed', dict(post_tables, **{'EMU10K1.config/Instance0.table': emu.replace(b'Dev:13', b'Dev:14')}),
         {}, 'EMU10K1.config/Instance0.table changed'),
        ('extra instance created elsewhere', dict(post_tables, **{'EMU10K1.config/Instance1.table': emu}), {}, 'tables added'),
        ('our table gone after the switch', dict((k, v) for k, v in post_tables.items() if k != DRIVER_TABLE), {},
         'want exactly ['),
        ('System Default.table touched', dict(post_tables, **{'System.config/Default.table': default_sys + b'\n'}), {},
         'Default.table changed'),
        ('Active Drivers lost a driver', dict(post_tables, **{'System.config/Instance0.table': system_post.replace(b'EMU10K1 ', b'')}),
         {}, 'Active Drivers'),
        ('System key changed', dict(post_tables, **{'System.config/Instance0.table': system_post.replace(b'"Boot Graphics" = "Yes"', b'"Boot Graphics" = "No"')}),
         {}, 'beyond Active Drivers'),
        ('driver Location elsewhere', dict(post_tables, **{DRIVER_TABLE: made.replace(b'"Location" = ""', b'"Location" = "Dev:13 Func:0 Bus:3"')}),
         {}, 'Location'),
        ('driver key added', dict(post_tables, **{DRIVER_TABLE: made + b'"IRQ Levels2" = "11";\n'}), {}, 'beyond'),
        ('postamble key lost in Configure\'s table',
         dict(post_tables, **{DRIVER_TABLE: made.replace(b'"Server Name" = "OSRDNDisplay";\n', b'')}), {}, 'Server Name'),
        ('postamble key names another server',
         dict(post_tables, **{DRIVER_TABLE: made.replace(b'"Server Name" = "OSRDNDisplay"', b'"Server Name" = "VGA"')}),
         {}, 'Server Name'),
        ('driver table group-writable', post_tables, {'lsmode': {DRIVER_TABLE: '-rw-rw-r--'}}, 'group- or other-writable'),
        ('a surplus instance that was already in pre', dict(post_tables, **{'OSRDNDisplay.config/Instance1.table': made}),
         {}, 'want exactly ['),
        ('only Instance1 left (the wrong table parked)',
         dict((k, v) for k, v in dict(post_tables, **{'OSRDNDisplay.config/Instance1.table': made}).items()
              if k != DRIVER_TABLE), {}, 'fall back to Default.table'),
        ('a table whose mode changed but whose bytes did not', post_tables,
         {'lsmode': {'EMU10K1.config/Instance0.table': '-r--r--r--'}}, 'mode -rw-r--r-- -> -r--r--r--'),
        ('our table to a mode Configure never writes', post_tables,
         {'lsmode': {DRIVER_TABLE: '-r--r-----'}}, 'mode -rw-r--r-- -> -r--r-----'),
        ('a table that changed owner', post_tables, {'owner': {'EMU10K1.config/Instance0.table': 'me wheel'}},
         'owner.group root.wheel -> me.wheel'),
    ]
    for label, tables, kw, want in cases:
        rc, out = verdict(['activate', pre, snap(tables, **kw)])
        check('activate stops: ' + label, rc == 1 and any(want in o for o in out), str(out))
    # the hole an "added tables" delta cannot see: a surplus table in BOTH snapshots
    pre_surplus = snap(dict(pre_tables, **{'OSRDNDisplay.config/Instance1.table': installed}))
    post_surplus = snap(dict(post_tables, **{'OSRDNDisplay.config/Instance1.table': installed}))
    rc, out = verdict(['activate', pre_surplus, post_surplus])
    check('activate stops: a surplus instance present in pre and post alike',
          rc == 1 and any('want exactly [' in o for o in out), str(out))
    # the bundle's own tables are 444 (the postamble chmods them); Configure
    # rewrote ours to 644 on 2026-09-16 -- that one transition is a NOTE
    pre444 = snap(pre_tables, lsmode={DRIVER_TABLE: '-r--r--r--'})
    rc, out = verdict(['activate', pre444, snap(post_tables)])
    check('activate: the 444 -> 644 Configure rewrite is a NOTE, not a FAIL',
          rc == 0 and any(o.startswith('NOTE ') and 'Configure rewrote' in o for o in out), str(out))
    rc, out = verdict(['same', post, snap(post_tables)])
    check('same: identical snapshots pass', rc == 0, str(out))
    rc, out = verdict(['same', post, snap(dict(post_tables, **{'EMU10K1.config/Instance0.table': emu}))])
    check('same: a reordered table is a difference', rc == 1 and any('bytes differ' in o for o in out), str(out))
    rc, out = verdict(['restored', pre, snap(pre_tables)])
    check('restored: pre back passes', rc == 0, str(out))
    rc, out = verdict(['restored', pre, snap(dict(pre_tables, **{DRIVER_TABLE: made}))])
    check('restored: our table left as Configure wrote it fails', rc == 1 and any('bytes differ' in o for o in out), str(out))
    rc, out = verdict(['restored', pre, snap(dict(pre_tables, **{'EMU10K1.config/Instance1.table': emu}))])
    check('restored: a table nobody parked fails', rc == 1 and any('file sets differ' in o for o in out), str(out))
    rc, out = verdict(['restored', pre, snap(pre_tables, lsmode={'VGA.config/Instance0.table': '-rw-------'})])
    check('restored: a mode difference fails', rc == 1 and any(' ls ' in o for o in out), str(out))
    rc, out = verdict(['record', pre, post])
    check('record lists the Configure changes', rc == 0 and any(o.startswith('CHANGED ' + DRIVER_TABLE) for o in out)
          and any(o.startswith('REMOVED VGA.config') for o in out) and any(o.startswith('REORDER EMU10K1') for o in out), str(out))
    shutil.rmtree(work)
    print('check_cfgdiff self-test: %s' % ('PASS' if failures == 0 else 'FAIL (%d)' % failures))
    return failures == 0


def main(argv):
    if argv[1:] == ['--self-test']:
        return 0 if self_test() else 1
    rc, out = run(argv)
    for o in out:
        print(o)
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv))
