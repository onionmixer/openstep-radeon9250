#!/usr/bin/env python3
"""H3 and H5 of docs/R3_MULTIMODE_PLAN.md 26-3: the SHIPPED inspector nib,
decoded and measured -- not a recomputation of the numbers that built it.

  check_nib_r3d.py        check the shipped nib, then show each check can fail

H3  what Configure will wire up
    - File's Owner is OSRDNDisplayInspector (and no IODisplayInspector owner is left);
    - every stock connector is still there, unchanged (the stock ten include
      displayMode 1 -> 48, without which the mode picker is gone);
    - exactly two new connectors: outlet grayMatrix 1 -> matrix, action
      grayChanged: matrix -> 1;
    - the matrix: one row of four cells, cell 54 x 15, spacing (4, 0), frame
      228 x 15, the selected-cell slot on the tag-0 cell;
    - cell (tag, title) pairs are osrdn_graypanel.h's table, in its order;
    - every new view's superview chain reaches 52 and then 48;
    - outlet and action names agree across the nib, data.classes and
      OSRDNDisplayInspector.h; data.classes is the stock file plus our class;
      data.dependency is the stock file;
    - nibroundtrip accepts the shipped data.nib, and rebuilding it with
      tools/r3/build-inspector-nib.py gives the same bytes (not stale).
H5  where it all sits
    - window, content view 49, box 48 and view 52 are each the stock height + G,
      with one G for all four, and 54/55 are lifted by that same G;
    - the gap between the lowest lifted stock child and the highest new object
      is 23, the stock panel's own;
    - every new frame lies inside view 52;
    - every label's text fits its frame (Helvetica 12 advance widths, URW
      Nimbus Sans -- the metric clone), and each cell title fits beside its
      radio image.
"""

import copy
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
WS = os.path.dirname(PROJ)
NIBMAKER = os.path.join(WS, 'openstep-nibmaker')
sys.path.insert(0, os.path.join(NIBMAKER, 'tools'))
from nibgraft import Nib  # noqa: E402

BUNDLE = os.path.join(PROJ, 'OSRDNDisplay')
SHIPPED = os.path.join(BUNDLE, 'English.lproj', 'DisplayInspector.nib')
STOCK = os.path.join(PROJ, 'build', 'stocknib', 'DisplayInspector.nib')
GRAYPANEL = os.path.join(BUNDLE, 'osrdn_graypanel.h')
INSP_H = os.path.join(BUNDLE, 'OSRDNDisplayInspector.h')
FONT = '/usr/share/fonts/opentype/urw-base35/NimbusSans-Regular.otf'
TEMPLATES = os.path.join(WS, 'openstep-spacesaver2ps2', 'ref', 'nibtemplates')

OWNER = '1'
GAP = 23
RADIO_IMAGE = 20        # the radio image and its gap, as in the Matrox panel


def decode(nib_path, work, name):
    xml = os.path.join(work, name + '.xml')
    with open(xml, 'w') as fh:
        subprocess.check_call([os.path.join(NIBMAKER, 'nib2xml'), nib_path], stdout=fh)
    return Nib(xml)


def superview(n, o):
    first = [c for c in n.groups(o)[0]][0]
    return first.get('oid') if first.tag == 'o' else None


def connectors(n):
    out = []
    for c in n.list_items(n.connectors_list()):
        if c.get('ref') is not None:
            c = n.obj(c.get('oid'))
        g = [k for k in n.group(c, '@@*')]
        out.append((c.get('cls'), g[0].get('oid'), g[1].get('oid'), g[2].get('v')))
    return out


def contains_ref(elem, oid):
    return any(e.tag == 'o' and e.get('oid') == oid for e in elem.iter())


def anatomy(n):
    """The stock objects this check needs, found by structure, not by number:
    decoding numbers objects in stream order, and the graft inserts objects
    ahead of the window (measured: stock 65 becomes 80 in the built nib)."""
    conns = connectors(n)
    box = [c[2] for c in conns if c[0] == 'IBOutletConnector' and c[3] == 'displayMode']
    holder = [c[2] for c in conns if c[0] == 'IBOutletConnector' and c[3] == 'displayAccessoryHolder']
    if len(box) != 1 or len(holder) != 1:
        raise ValueError('displayMode/displayAccessoryHolder outlets: %s %s' % (box, holder))
    box, holder = box[0], holder[0]
    content = superview(n, n.obj(box))
    view = [oid for oid, o in n.objs.items() if n.groups(o) and o.get('cls') == 'View'
            and superview(n, o) == box]
    wins = [o.get('oid') for o in n.find_by_class('WindowTemplate') if contains_ref(o, content)]
    if len(view) != 1 or len(wins) != 1:
        raise ValueError('box content views %s, windows holding %s: %s' % (view, content, wins))
    inner = sorted(oid for oid, o in n.objs.items()
                   if o.get('cls') in ('CustomView', 'Box') and superview(n, o) == view[0])
    return dict(owner=OWNER, window=wins[0], content=content, box=box, view=view[0],
                holder=holder, inner=inner)


def signature(n, o):
    cls = o.get('cls')
    text = None
    if cls in ('TextField', 'Button'):
        text = n.cstring([c for c in n.group(o, 'i@s')][1]).get('v')
    return (cls, tuple(n.frame(o)), text)


def new_views(n, stock):
    """Views of the grafted kinds whose content the stock nib does not have."""
    old = [signature(stock, o) for o in stock.objs.values()
           if o.get('cls') in ('Matrix', 'TextField', 'Button')]
    out = []
    for o in n.objs.values():
        if o.get('cls') in ('Matrix', 'TextField', 'Button'):
            sig = signature(n, o)
            if sig in old:
                old.remove(sig)
            else:
                out.append(o)
    return out


def conn_desc(n, c):
    return (c[0], n.obj(c[1]).get('cls'), n.obj(c[2]).get('cls'), c[3])


def gray_table():
    m = re.search(r'osrdnGrayValues\[OSRDN_GRAY_COUNT\]\s*=\s*\{([^}]*)\}', open(GRAYPANEL).read())
    return re.findall(r'"([^"]*)"', m.group(1))


def classes_block(text, name):
    m = re.search(r'^' + re.escape(name) + r' = \{(.*?)^\};', text, re.S | re.M)
    if not m:
        return None
    body = m.group(1)

    def names(key):
        k = re.search(key + r' = \{(.*?)\};', body, re.S)
        return sorted(re.findall(r'"?([A-Za-z0-9_:]+)"? = "?\1"?;', k.group(1))) if k else None
    sup = re.search(r'SUPERCLASS = (\w+);', body)
    return names('ACTIONS'), names('OUTLETS'), sup.group(1) if sup else None


def header_names(text):
    ivars = re.search(r'@interface OSRDNDisplayInspector : IODisplayInspector\s*\{(.*?)\}', text, re.S)
    outlets = sorted(re.findall(r'\bid\s+(\w+);', ivars.group(1))) if ivars else []
    actions = sorted(a + ':' for a in re.findall(r'^- (\w+):sender;', text, re.M))
    return actions, outlets


_widths = {}


def text_width(s):
    if not _widths:
        from fontTools.ttLib import TTFont
        f = TTFont(FONT)
        _widths['cmap'], _widths['hmtx'], _widths['upem'] = f.getBestCmap(), f['hmtx'], f['head'].unitsPerEm
    return sum(_widths['hmtx'][_widths['cmap'][ord(ch)]][0] for ch in s) * 12.0 / _widths['upem']


def check(n, stock, classes, dependency, insp_h):
    """Problems, one string each."""
    p = []
    try:
        a, sa = anatomy(n), anatomy(stock)
    except ValueError as e:
        return ['cannot find the stock structure: %s' % e]

    # ---- H3: owner
    owners = [o for o in n.find_by_class('CustomObject')
              if n.cstring(o, '*@').get('v') in ('IODisplayInspector', 'OSRDNDisplayInspector')]
    names = [(o.get('oid'), n.cstring(o, '*@').get('v')) for o in owners]
    if names != [(OWNER, 'OSRDNDisplayInspector')]:
        p.append("File's Owner: %s" % names)

    # ---- H3: connectors, compared by (kind, endpoint classes, label)
    got = [conn_desc(n, c) for c in connectors(n)]
    left = list(got)
    for c in [conn_desc(stock, c) for c in connectors(stock)]:
        if c in left:
            left.remove(c)
        else:
            p.append('stock connector %s is gone or changed' % (c,))
    added = new_views(n, stock)
    mats = [o for o in added if o.get('cls') == 'Matrix']
    if len(mats) != 1:
        p.append('%d new matrices, want 1' % len(mats))
        return p
    mat = mats[0]
    m = mat.get('oid')
    want_new = sorted([('IBOutletConnector', 'CustomObject', 'Matrix', 'grayMatrix'),
                       ('IBControlConnector', 'Matrix', 'CustomObject', 'grayChanged:')])
    if sorted(left) != want_new:
        p.append('new connectors %s, want %s' % (sorted(left), want_new))
    new = [c for c in connectors(n) if c[3] in ('grayMatrix', 'grayChanged:')]
    if sorted(new) != sorted([('IBOutletConnector', OWNER, m, 'grayMatrix'),
                              ('IBControlConnector', m, OWNER, 'grayChanged:')]):
        p.append('the gray connectors do not join the owner and the new matrix: %s' % new)

    # ---- H3: the matrix
    cells_group = n.group(mat, '@:@iiii')
    ints = [int(i.get('v')) for i in cells_group if i.tag == 'i']
    if ints != [0, 0, 1, 4]:
        p.append('matrix rows/cols group %s, want [0, 0, 1, 4]' % ints)
    size = [int(i.get('v')) for i in n.group(mat, 'ff', 0) if i.tag == 'i']
    space = [int(i.get('v')) for i in n.group(mat, 'ff', 1) if i.tag == 'i']
    if size != [54, 15] or space != [4, 0]:
        p.append('cell size %s spacing %s, want [54, 15] [4, 0]' % (size, space))
    fx, fy, fw, fh = n.frame(mat)
    if (fw, fh) != (4 * 54 + 3 * 4, 15):
        p.append('matrix frame %dx%d, want 228x15' % (fw, fh))
    cells = [n.obj(c.get('oid')) if c.get('ref') is not None else c
             for c in n.list_items([c for c in cells_group][0])]
    pairs = [(int([i for i in n.group(c, 'i:') if i.tag == 'i'][0].get('v')), n.cstring(c).get('v'))
             for c in cells]
    want_pairs = list(enumerate(gray_table()))
    if pairs != want_pairs:
        p.append('cells (tag, title) %s, want %s' % (pairs, want_pairs))
    sel = [c for c in cells_group][2]
    tag0 = [c for c, (t, _) in zip(cells, pairs) if t == 0]
    if not tag0 or sel.get('oid') != tag0[0].get('oid'):
        p.append('the selected-cell slot is %s, not the tag-0 cell' % sel.get('oid'))

    # ---- H3: every new view hangs under 52 -> 48
    for o in added:
        chain, cur = [], o.get('oid')
        for _ in range(8):
            cur = superview(n, n.obj(cur))
            if cur is None:
                break
            chain.append(cur)
        if chain[:2] != [a['view'], a['box']]:
            p.append('%s %s hangs under %s, not the mode box view' % (o.get('cls'), o.get('oid'), chain[:3]))
    if sorted(o.get('cls') for o in added) != ['Matrix', 'TextField', 'TextField']:
        p.append('new views %s, want one matrix and two labels' % sorted(o.get('cls') for o in added))

    # ---- H3: names agree
    blk = classes_block(classes, 'OSRDNDisplayInspector')
    h_actions, h_outlets = header_names(insp_h)
    nib_actions = sorted(c[3] for c in new if c[0] == 'IBControlConnector')
    nib_outlets = sorted(c[3] for c in new if c[0] == 'IBOutletConnector')
    if blk is None:
        p.append('data.classes has no OSRDNDisplayInspector')
    elif not (blk[0] == h_actions == nib_actions and blk[1] == h_outlets == nib_outlets
              and blk[2] == 'IODisplayInspector'):
        p.append('names differ: data.classes %s, header %s, nib %s'
                 % (blk, (h_actions, h_outlets), (nib_actions, nib_outlets)))
    stock_classes = open(os.path.join(STOCK, 'data.classes')).read()
    if not classes.startswith(stock_classes):
        p.append('data.classes does not start with the stock file')
    if dependency != open(os.path.join(STOCK, 'data.dependency')).read():
        p.append('data.dependency is not the stock file')

    # ---- H5: heights, lift, gap, containment
    grows = []
    for key in ('window', 'content', 'box', 'view'):
        grows.append(n.frame(n.obj(a[key]))[3] - stock.frame(stock.obj(sa[key]))[3])
    if len(set(grows)) != 1 or grows[0] <= 0:
        p.append('window/content/box/view grew by %s, not one positive amount' % grows)
    g = grows[-1]
    if len(a['inner']) != 2 or len(sa['inner']) != 2:
        p.append('the mode box view holds %s, stock %s' % (a['inner'], sa['inner']))
        return p
    inner = [(n.obj(x).get('cls'), n.frame(n.obj(x))) for x in a['inner']]
    stock_inner = [(stock.obj(x).get('cls'), stock.frame(stock.obj(x))) for x in sa['inner']]
    for (c1, f1), (c0, f0) in zip(sorted(inner), sorted(stock_inner)):
        if c1 != c0 or f1[1] - f0[1] != g or [f1[0], f1[2], f1[3]] != [f0[0], f0[2], f0[3]]:
            p.append('%s %s is not the stock %s lifted by %d' % (c1, f1, f0, g))
    vx, vy, vw, vh = n.frame(n.obj(a['view']))
    tops = []
    for o in added:
        x, y, w, h = n.frame(o)
        tops.append(y + h)
        if x < 0 or y < 0 or x + w > vw or y + h > vh:
            p.append('%s %s [%d,%d,%d,%d] is outside the mode box view (%dx%d)'
                     % (o.get('cls'), o.get('oid'), x, y, w, h, vw, vh))
    low = min(f[1] for _, f in inner)
    if tops and low - max(tops) != GAP:
        p.append('gap above the new rows is %d, the stock panel has %d' % (low - max(tops), GAP))

    # ---- H5: text fits
    for o in added:
        if o.get('cls') == 'TextField':
            text = n.cstring([c for c in n.group(o, 'i@s')][1]).get('v') or ''
            if text_width(text) > n.frame(o)[2]:
                p.append('label %r is %.1f px in a %d px frame' % (text, text_width(text), n.frame(o)[2]))
    for _, title in pairs:
        if text_width(title) > size[0] - RADIO_IMAGE:
            p.append('cell title %r does not fit beside its radio image' % title)
    return p


def main():
    fails = 0
    work = tempfile.mkdtemp(prefix='check_nib_r3d.')
    try:
        n = decode(os.path.join(SHIPPED, 'data.nib'), work, 'shipped')
        stock = decode(os.path.join(STOCK, 'data.nib'), work, 'stock')
        classes = open(os.path.join(SHIPPED, 'data.classes')).read()
        dependency = open(os.path.join(SHIPPED, 'data.dependency')).read()
        insp_h = open(INSP_H).read()

        base = check(n, stock, classes, dependency, insp_h)
        for x in base:
            print('  FAIL %s' % x)
        print('  %-4s H3/H5 the shipped nib (%d connectors, %d objects)'
              % ('FAIL' if base else 'ok', len(connectors(n)), len(n.objs)))
        fails += len(base)

        r = subprocess.run([os.path.join(NIBMAKER, 'nibroundtrip'), os.path.join(SHIPPED, 'data.nib')],
                           capture_output=True, text=True)
        ok = r.returncode == 0
        print('  %-4s nibroundtrip accepts the shipped data.nib' % ('ok' if ok else 'FAIL'))
        fails += 0 if ok else 1

        out = os.path.join(work, 'rebuild')
        os.makedirs(out)
        r = subprocess.run(['python3', os.path.join(HERE, 'build-inspector-nib.py'), NIBMAKER, STOCK,
                            os.path.join(TEMPLATES, 'PS2MouseInspector.xml'),
                            os.path.join(TEMPLATES, 'radio-template-BusLogicIntrInspector.xml'), out],
                           capture_output=True, text=True)
        same = r.returncode == 0 and open(os.path.join(out, 'data.nib'), 'rb').read() == \
            open(os.path.join(SHIPPED, 'data.nib'), 'rb').read()
        print('  %-4s the shipped data.nib is what the script builds now' % ('ok' if same else 'FAIL'))
        fails += 0 if same else 1

        # ---- each check can fail: mutate a copy of the decoded nib
        def mutant(fn):
            m = copy.deepcopy(n)
            m.tree = copy.deepcopy(n.tree)
            m.root = m.tree.getroot()
            m.reindex()
            fn(m)
            m.reindex()
            return m

        def the_matrix(m):
            return [o for o in new_views(m, stock) if o.get('cls') == 'Matrix'][0]

        def cells_of(m):
            g = m.group(the_matrix(m), '@:@iiii')
            return [m.obj(c.get('oid')) if c.get('ref') is not None else c
                    for c in m.list_items([c for c in g][0])]

        def set_int(group, idx, v):
            [i for i in group if i.tag == 'i'][idx].set('v', str(v))

        def drop_stock_connector(m):
            lst = m.list_items(m.connectors_list())
            # okButton: one the structure lookup does not use, so it is the
            # "stock connector gone" rule that has to catch it
            victim = [c for c in lst if c.get('cls') == 'IBOutletConnector'
                      and [k for k in m.group(c, '@@*')][2].get('v') == 'okButton'][0]
            lst.remove(victim)

        def relabel_outlet(m):
            for c in m.list_items(m.connectors_list()):
                g = [k for k in m.group(c, '@@*')] if c.get('ref') is None else []
                if g and g[2].get('v') == 'grayMatrix':
                    g[2].set('v', 'grayMatrx')

        def reparent_label(m):
            lb = [o for o in new_views(m, stock) if o.get('cls') == 'TextField'][0]
            [c for c in m.groups(lb)[0]][0].set('oid', anatomy(m)['content'])

        negatives = [
            ('a cell title changed', mutant(lambda m: m.set_cstring(cells_of(m)[2], '8')), classes),
            ('two cell tags swapped', mutant(lambda m: (set_int(m.group(cells_of(m)[1], 'i:'), 0, 2),
                                                        set_int(m.group(cells_of(m)[2], 'i:'), 0, 1))), classes),
            ('the matrix laid out 2 x 2', mutant(lambda m: (set_int(m.group(the_matrix(m), '@:@iiii'), 2, 2),
                                                            set_int(m.group(the_matrix(m), '@:@iiii'), 3, 2))),
             classes),
            ('the cell spacing left at the template (0, 3)',
             mutant(lambda m: (set_int(m.group(the_matrix(m), 'ff', 1), 0, 0),
                               set_int(m.group(the_matrix(m), 'ff', 1), 1, 3))), classes),
            ('the selected cell is the "2" cell', mutant(
                lambda m: [c for c in m.group(the_matrix(m), '@:@iiii')][2].set('oid', cells_of(m)[3].get('oid'))),
             classes),
            ('the stock okButton outlet deleted', mutant(drop_stock_connector), classes),
            ('the outlet misspelt in the nib', mutant(relabel_outlet), classes),
            ('the outlet misspelt in data.classes', n, classes.replace('grayMatrix = grayMatrix',
                                                                       'grayMatrx = grayMatrx')),
            ('data.classes rebuilt from the stock file', n, open(os.path.join(STOCK, 'data.classes')).read()),
            ('a label hung on view 49', mutant(reparent_label), classes),
            ('the mode box not lifted as far', mutant(lambda m: m.set_frame(m.obj(anatomy(m)['inner'][1]), *[
                v - 5 if k == 1 else v for k, v in enumerate(m.frame(m.obj(anatomy(m)['inner'][1])))])), classes),
            ('the window not grown', mutant(lambda m: set_int(m.group(m.obj(anatomy(m)['window']), 'ffff', 0), 3,
                                                              stock.frame(stock.obj(anatomy(stock)['window']))[3])),
             classes),
            ('the caption too long for its frame', mutant(lambda m: m.set_cstring(
                [c for c in m.group([o for o in new_views(m, stock) if o.get('cls') == 'TextField'
                                     and 'reboot' in signature(m, o)[2]][0], 'i@s')][1],
                'Applies to BW:8 modes only; it takes effect after the next reboot.')), classes),
        ]
        for label, m, cls in negatives:
            try:
                caught = bool(check(m, stock, cls, dependency, insp_h))
            except Exception as e:           # a mutation that breaks the reader is caught too,
                caught = True                # but say so, so it is not mistaken for a rule
                label += ' (reader raised %s)' % type(e).__name__
            print('  %-4s negative: %s' % ('ok' if caught else 'FAIL', label))
            fails += 0 if caught else 1
    finally:
        shutil.rmtree(work)
    print('check_nib_r3d: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
