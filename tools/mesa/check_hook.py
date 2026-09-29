#!/usr/bin/env python3
"""M1b gate A: what the hooks are allowed to do, enumerated (docs/M1B_PLAN.md 6-A).

  check_hook.py

The first draft of this gate said only "every rule has a mutation" -- which
names no rules, and a gate that names no rules cannot notice a missing one.  So
the rules are written out below, and each has a mutation; baseline PASS and
every mutation FAIL, in the same run.

What the rules are FOR: M1b claims the accelerated library draws nothing.  A
picture identical to the software one does not show that -- it could have drawn
the same thing, or drawn and been overwritten.  These rules, and the undefined-
symbol allow-list the target build checks, are what actually hold the claim.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
MESA = os.path.join(PROJ, 'mesa')
HOOK = os.path.join(MESA, 'OSRDNMesaHook.c')
STUBS = os.path.join(MESA, 'OSRDNMesaStubs.c')
CLS = os.path.join(MESA, 'OSRDNMesaClass.c')
SURF = os.path.join(MESA, 'OSRDNMesaSurface.c')
TRI = os.path.join(MESA, 'OSRDNMesaTri.c')

# The nine that decline, and the value each must return.  Read from the plan,
# not from the C: that is the point of a rule.
# What M1c still declines.  Six moved into the hook unit and are real now; the
# depth surface, its copy-back and the clear word stay refused, because colour,
# depth and texture are not turned on together.
DECLINE = {
    'OpenStepMesaAccelDepthBuffer': '0',
    'OpenStepMesaAccelCopyDepth': '0',
    'OpenStepMesaAccelClearPixel': None,        # returns nothing
}

# Anything that could put a pixel anywhere.  A hook that drew would have to
# reach one of these, so their absence is the claim's backbone.
# M1c maps one window, so mmap/vm_allocate leave this list and get rules of
# their own (A4/A5).  What may still not appear anywhere is a way to write
# somewhere the rung has not accounted for.
FORBIDDEN = ['write', 'memcpy', 'bcopy', 'memset', 'bzero', 'strcpy', 'sprintf']


def uncomment(t):
    return re.sub(r'//[^\n]*', ' ', re.sub(r'/\*.*?\*/', ' ', t, flags=re.S))


def body(text, name):
    m = re.search(r'\n[\w \*]*\b%s\s*\([^;{]*\)\s*\n?\{' % re.escape(name), text)
    if m is None:
        return ''
    i = text.index('{', m.start())
    d, j = 0, i
    while j < len(text):
        if text[j] == '{':
            d += 1
        elif text[j] == '}':
            d -= 1
            if d == 0:
                return text[i:j + 1]
        j += 1
    return ''



def tripath(text):
    """The triangle path as a whole: the entry, the state it computes and the
    body that does the work.

    M1v split osrdnHookTriangle into osrdnTriStateOf (what cannot change inside
    a render pass) + osrdnTriangleWith (one triangle), so that a whole group can
    share the first.  Every rule below was written against one function body and
    they ALL went blind at once -- seventeen of them -- because the work had
    moved one call deeper.  A rule that greps a function body only ever proves
    something about the text it read (recorded), so the rules follow the calls.
    """
    out = ''
    for n in ('osrdnHookTriangle', 'osrdnTriStateOf', 'osrdnTriangleWith'):
        out += body(text, n)
    return out

def enclosing(text, pos):
    """(name, body) of the function that contains `pos`, or None.

    Naming a function in a rule is a promise the next refactor breaks -- M1k
    moved the submission out of osrdn_tri_send and three rules stopped looking
    without stopping passing.  This lets a rule name the CODE and find the
    function, which is the direction that survives a rename.
    """
    if pos is None or pos < 0:
        return None
    for m in re.finditer(r'\n([\w \*]*?\b(\w+))\s*\([^;{]*\)\s*\n?\{', text):
        i = text.index('{', m.start())
        d, j = 0, i
        while j < len(text):
            if text[j] == '{':
                d += 1
            elif text[j] == '}':
                d -= 1
                if d == 0:
                    break
            j += 1
        if i <= pos <= j:
            return (m.group(2), text[i:j + 1])
    return None


def flatten(text):
    """one space between tokens, so a rule is not defeated by a line wrap"""
    return re.sub(r'\s+', ' ', text)


def rules(hook, stubs, cls, surf=None, tri=None):
    r = {}
    h, s, c = uncomment(hook), uncomment(stubs), uncomment(cls)
    t = uncomment(tri) if tri else ''
    allc = h + '\n' + s + '\n' + c + '\n' + t

    # A1 -- no drawing path anywhere in the accelerated sources
    p = []
    # G4-6: write() is allowed in ONE named function, the submission trace (triTrace), which
    # writes only to the files RDNMesaTrace/RDNMesaTraceLast name -- narrowed by name, not dropped
    tb = body(t, 'triTrace') if t else ''
    allc_nt = allc.replace(tb, ' ') if tb else allc
    allc_nt = re.sub(r'\bextern\b[^;]*;', ' ', allc_nt)      # a declaration is not a call (as the mmap rule)
    for name in FORBIDDEN:
        if re.search(r'\b%s\s*\(' % name, allc_nt):
            p.append('the accel sources call %s()' % name)
    if t and tb:
        if 'getenv(OSRDN_TRI_TRACE_ENV)' not in tb or 'getenv(OSRDN_TRI_TRACE_LAST_ENV)' not in tb:
            p.append('the trace writes to a file the environment did not name')
        if re.search(r'\bwrite\s*\(\s*(?!triTraceFd|triTraceLastFd)', tb):
            p.append('the trace writes to an fd that is not one of its two')
        if flatten(body(t, 'triSubmit')).count('triTrace(n);') != 1:
            p.append('the trace is not taken once per submission, before the ioctl')
    #
    # M1d installs a triangle function, so "nothing writes through ctx->" is no
    # longer true -- but it is still true of everything except two named lines.
    # The rule is narrowed to those two rather than dropped: a dropped rule
    # stops catching what it was written for, and this one was written to catch
    # a unit quietly taking over the drawing.
    #
    # M1j adds a third: our Clear.  Named, like the other two, so that the rule
    # still refuses a fourth -- the point is that every takeover is on this list.
    # M1k adds two.  The exemption is still ONE occurrence each and still only
    # inside osrdnHookInstall, so the rule is unchanged in what it forbids: it
    # now names five writes instead of three, and a sixth anywhere still trips.
    INSTALL_WRITES = ('ctx->Driver.TriangleFunc = 0;',
                      'ctx->Driver.TriangleFunc = osrdnHookTriangle;',
                      'ctx->Driver.Clear = osrdnHookClear;',
                      'ctx->Driver.RenderStart = osrdnHookRenderStart;',
                      'ctx->Driver.RenderFinish = osrdnHookRenderFinish;',
                      # M3g: glFinish's copy back, installed only into an
                      # empty field (docs/M3G_PLAN.md) -- named, not loosened
                      'ctx->Driver.Finish = osrdnHookFinish;',
                      # G4-1b: the three old-style texture notifications, each
                      # chained to what was there (docs/G4_GLQUAKE_PLAN.md 5 T2)
                      'ctx->Driver.TexImage = osrdnHookTexImage;',
                      'ctx->Driver.TexSubImage = osrdnHookTexSubImage;',
                      'ctx->Driver.DeleteTexture = osrdnHookDeleteTexture;',
                      # G4-2 B1 F6/F7: glFlush and the four pixel commands, each
                      # chained to what was there (docs/G4_2_BATCH_PLAN.md 3)
                      'ctx->Driver.Flush = osrdnHookFlush;',
                      'ctx->Driver.ReadPixels = osrdnHookReadPixels;',
                      'ctx->Driver.CopyPixels = osrdnHookCopyPixels;',
                      'ctx->Driver.DrawPixels = osrdnHookDrawPixels;',
                      'ctx->Driver.Bitmap = osrdnHookBitmap;')
    # M1v adds a SECOND installer, and it is named here rather than the rule
    # being loosened: it writes one member, once, and it is the only place that
    # may.  Everything the exemption does not name still trips.
    INSTALLERS = (('osrdnHookInstall', INSTALL_WRITES),
                  ('osrdnInstallGroupTab',
                   ('ctx->Driver.RenderVBRawTab = osrdnRawTab[slot];',)),
                  # G4-2 B1 F3: the point and line wrappers, two members, once
                  # each, from the one function both UpdateState paths call
                  ('osrdnInstallPrims',
                   ('ctx->Driver.PointsFunc = osrdnHookPoints;',
                    'ctx->Driver.LineFunc = osrdnHookLine;')))
    inst0 = body(h, 'osrdnHookInstall')
    rest = allc
    for fname, writes in INSTALLERS:
        fbody = body(h, fname)
        if not fbody:
            p.append('%s is not defined' % fname)
            continue
        stripped = fbody
        for wline in writes:
            k = fbody.count(wline)
            if k == 0:
                p.append('the install line %r is gone' % wline)
            elif k > 1:
                p.append('the install line %r appears %d times' % (wline, k))
            # ONE occurrence is exempt, not every occurrence: replacing them all
            # let a duplicate inside the install through, and a duplicate is how
            # a second, unreviewed write would arrive
            stripped = stripped.replace(wline, '', 1)
        # and only that function's own copy is exempt; one anywhere else trips
        rest = rest.replace(fbody, stripped)
    if re.search(r'ctx\s*->\s*\w+\s*(\[[^\]]*\])?\s*=[^=]', rest):
        p.append('something OTHER than the install assigns through ctx->')
    if re.search(r'Driver\s*\.\s*\w+\s*=[^=]', rest):
        p.append('something OTHER than the install assigns to a ctx->Driver member')
    if not inst0:
        p.append('osrdnHookInstall is not defined')
    r['m1b-no-drawing'] = p
    inst = inst0                    # the rules below read it under its old name

    # ---- M1d --------------------------------------------------------------

    # the fallback is real: every path out of our triangle function either
    # returns after a send or draws it in software
    p = []
    b = tripath(h)
    flat = flatten(b)
    if not b:
        p.append('osrdnHookTriangle is not defined')
    else:
        if b.count('osrdn_tri_send(') != 1:
            p.append('the triangle function sends %d times; one call is the whole shape'
                     % b.count('osrdn_tri_send('))
        if '(*sw)(ctx, v0, v1, v2, pv);' not in b:
            p.append('the triangle function never calls the saved software function')
        if 'osrdnCounts.noSoftware++' not in b:
            p.append('a triangle with no software function to fall back to is not counted')
        if 'osrdnCounts.delegated++' not in b:
            p.append('the delegations are not counted, so nothing can be compared to '
                     'the tri unit\'s refusals')
        if 'osrdn_surf_bound_to' not in b:
            p.append('the triangle function sends without checking that the surface '
                     'is ours')
    r['m1d-never-lose-a-triangle'] = p

    # the install takes Mesa's choice BEFORE putting ours in, or there is
    # nothing to fall back to (src/triangle.c 1532)
    p = []
    if not inst:
        p.append('osrdnHookInstall is not defined')
    else:
        i0 = inst.find('ctx->Driver.TriangleFunc = 0;')
        i1 = inst.find('gl_set_triangle_function(ctx);')
        i2 = inst.find('osrdnSaved[slot].sw = ctx->Driver.TriangleFunc;')
        i3 = inst.find('ctx->Driver.TriangleFunc = osrdnHookTriangle;')
        if min(i0, i1, i2, i3) < 0:
            p.append('the install is not the four steps NULL, choose, save, replace')
        elif not (i0 < i1 < i2 < i3):
            p.append('the install does those four steps out of order (%d %d %d %d)'
                     % (i0, i1, i2, i3))
        if 'if (!take)' not in inst:
            p.append('the install does not leave Mesa alone when we decline')
    r['m1d-save-before-replace'] = p

    # the classifier asks about the shade model and the setup caps, and asks
    # TriangleCaps rather than IndirectTriangles (src/state.c 1130)
    p = []
    for field, guard, why in (
            ('shadeModel', 's->shadeModel != GL_FLAT_', 'OSRDN_WHY_SHADE_MODEL'),
            ('triangleCaps', '(s->triangleCaps & DD_DECLINE_) != 0UL', 'OSRDN_WHY_TRI_SETUP'),
            ('alphaFunc', 'osrdn_class_alpha_code(s->alphaFunc, s->alphaRef) == 0', 'OSRDN_WHY_ALPHA_MODE')):   # G4-3 K2
        if field not in c:
            p.append('the classifier never looks at %s' % field)
        # the name surviving is not the test surviving: `s->shadeModel ==
        # s->shadeModel` keeps the field and always answers no
        if guard not in c:
            p.append('the %s test is not %r any more' % (field, guard))
        if ('w = %s;' % why) not in c:
            p.append('nothing sets %s' % why)
    if 'IndirectTriangles' in c or 'IndirectTriangles' in h:
        p.append('something reads IndirectTriangles, which has had DD_TRI_CULL '
                 'removed from it by the time we could read it')
    if 'ctx->TriangleCaps' not in h:
        p.append('the hook does not read ctx->TriangleCaps')
    if 'ctx->Light.ShadeModel' not in h:
        p.append('the hook does not read ctx->Light.ShadeModel')
    r['m1d-classifier-inputs'] = p

    # the tri unit: no Mesa headers, no card address, one mapping
    p = []
    if tri:
        for bad in ('glheader.h', 'types.h', 'GL/gl.h'):
            if bad in tri:
                p.append('the tri unit includes %s' % bad)
        # Declarations are not calls: `extern char *mmap(...)` counted as one
        # and reported two, which is the trap A4 already records.
        tcalls = re.sub(r'\bextern\b[^;]*;', ' ', t)
        n = len(re.findall(r'\bmmap\s*\(', tcalls))
        if n != 1:
            p.append('the tri unit calls mmap %d times; one window is the invariant' % n)
        if 'caps->winStart' not in t:
            p.append('the surface address does not come from CAPS')
        # an all-ones word is an arithmetic limit, not an address (A5's carve-out)
        for m in re.finditer(r'0x[0-9a-fA-F]{6,}', t):
            if re.match(r'0x[fF]+$', m.group(0)):
                continue
            p.append('a constant address %s is written into the tri unit' % m.group(0))
    r['m1d-tri-pure'] = p

    # a failed ioctl copies nothing back, so its block must not be believed
    #
    # M1k moved the submission out of osrdn_tri_send into triSubmit, so naming
    # the function was the wrong way to write this.  The rule now finds the
    # answer block WHEREVER it is and demands the guard in the same function --
    # which is what it always meant, and which no rename can dodge.
    #
    p = []
    if tri:
        n = t.count('triCounts.lastWhy = sb.why;')
        if n != 1:
            p.append('the answer block is read in %d places; one is the shape' % n)
        else:
            fn = enclosing(t, t.find('triCounts.lastWhy = sb.why;'))
            if fn is None:
                p.append('the answer block is not inside any function')
            else:
                name, sb = fn
                good = sb.find('triCounts.lastWhy = sb.why;')
                guard = sb.find('if (rc != 0)')
                if good < 0 or guard < 0 or guard > good:
                    p.append('the answer block in %s is read without first testing '
                             'the ioctl\'s return' % name)
        #
        # M1p: TWO CALLS NOW, ONE PER BUFFER -- AND BOTH IN ONE FUNCTION.
        #
        # The rule's point was never the number; it was that a batch and a
        # single triangle go the same way.  M1p adds a second way of handing
        # the words over (the client's cached memory instead of the mapped
        # window), so there are two ioctls -- but they must both live in the
        # ONE function that submits, or batch and single could drift apart.
        #
        # G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2-4): the SUBMISSIONS are what must go one way.
        # RETIRE is not a submission -- it hands no words over -- and it has exactly one home.
        every = [(i, ln) for i, ln in enumerate(t.split('\n'))
                 if 'ioctl(' in ln and not ln.lstrip().startswith('extern')]
        lines = [(i, ln) for i, ln in every if 'OSRDN_R7B_IOC_SUBMIT' in ln]
        other = [(i, ln) for i, ln in every if 'OSRDN_R7B_IOC_SUBMIT' not in ln]
        if len(other) != 1 or 'OSRDN_R7B_IOC_RETIRE' not in other[0][1]:
            p.append('the tri unit has %d ioctls that are not submissions; one, RETIRE, is the shape' % len(other))
        else:
            pos = sum(len(x) + 1 for x in t.split('\n')[:other[0][0]])
            fn = enclosing(t, pos)
            if not fn or fn[0] != 'triRetireIoctl':
                p.append('the RETIRE ioctl is not in triRetireIoctl')
        if len(lines) != 2:
            p.append('the tri unit calls ioctl %d times; two (one per buffer) '
                     'is the shape' % len(lines))
        homes = set()
        for i, _ln in lines:
            pos = sum(len(x) + 1 for x in t.split('\n')[:i])
            fn = enclosing(t, pos)
            homes.add(fn[0] if fn else '?')
        if len(homes) != 1:
            p.append('the ioctl calls are spread over %s; one function must own '
                     'them or a batch and a single triangle could go different '
                     'ways' % sorted(homes))
    r['m1d-failed-ioctl-is-not-an-answer'] = p

    # ---- M1e -------------------------------------------------------------

    # Gouraud takes each vertex's own colour; flat takes the provoking one.  ONE
    # place builds the word, because a swap that differed between the two paths
    # would be invisible in the flat picture (which M1d already proved right).
    p = []
    if not b:
        p.append('osrdnHookTriangle is not defined')
    else:
        if 'ctx->Light.ShadeModel' not in b:
            p.append('the triangle function does not ask which shade model this is')
        if 'VB->ColorPtr->data[smooth ? idx[i] : pv]' not in b:
            p.append('the colour is not taken per-vertex when smooth and from pv '
                     'when flat')
        if b.count('osrdnColourWord(') != 1:
            p.append('the colour word is built in %d places; one is the invariant'
                     % b.count('osrdnColourWord('))
        # M1k: there are TWO submission calls now -- alone, and into a batch --
        # and a triangle that took a different set of arguments down one of them
        # would draw a different picture depending on where it arrived.  So both
        # are named, and both must carry the same five.  (Normalised, because
        # the argument list now wraps.)
        for fn, want in (('osrdn_tri_send(', 1), ('osrdn_tri_batch_add(', 1)):
            if flat.count(fn) != want:
                p.append('the triangle function calls %s %d times, want %d'
                         % (fn, flat.count(fn), want))
        if flat.count('vtx, smooth, blend, tex, depth,') != 2:
            p.append('the shade model, the blend mode, the texture and the depth '
                     'are not all passed down BOTH submission paths (found %d of 2)'
                     % flat.count('vtx, smooth, blend, tex, depth,'))
    # and the swap itself exists exactly once in the whole accel source
    if allc.count('(want & 0xff00ff00UL)') != 1:
        p.append('the byte swap appears %d times; it must live in one function'
                 % allc.count('(want & 0xff00ff00UL)'))
    r['m1e-per-vertex-colour'] = p

    # M1f: the blend mode is READ from ctx and CARRIED; the hook does not choose
    # which modes are drawable -- that is the classifier's, and it is tested as
    # a table on the host (tools/mesa/sim_class.py).
    p = []
    if not b:
        p.append('osrdnHookTriangle is not defined')
    else:
        if 'blend = ctx->Color.BlendEnabled ? osrdn_class_blend_code((unsigned long) ctx->Color.BlendSrcRGB, (unsigned long) ctx->Color.BlendDstRGB) : 0;' not in b:
            p.append('the triangle function does not read the blend enable and carry the pair as the classifier codes it (G4-1a)')
        # G4-1a: the depth compare/mask and the env mode travel the same way, and a feature on with no code is not sent
        if 'depth = ctx->Depth.Test ? osrdn_class_depth_code((unsigned long) ctx->Depth.Func, (unsigned long) ctx->Depth.Mask) : 0;' not in b:
            p.append('the depth compare and mask are not carried as the classifier codes them (G4-1a)')
        if 'tex = ctx->Texture.ReallyEnabled ? osrdn_class_env_code((unsigned long) ctx->Texture.Unit[0].EnvMode) : 0;' not in b:
            p.append('the texture env mode is not carried as the classifier codes it (G4-1a)')
        if 'osrdnCounts.codeGap++;\n        return;' not in b:
            p.append('a feature on with a code of 0 is still sent (G4-1a)')
        if flat.count('vtx, smooth, blend, tex, depth,') != 2:
            p.append('the blend mode is not passed down both submission paths')
    for name in ('BlendSrcRGB', 'BlendDstRGB', 'BlendSrcA', 'BlendDstA',
                 'BlendEquation'):
        if ('ctx->Color.%s' % name) not in h:
            p.append('the hook never reads ctx->Color.%s, so the classifier '
                     'cannot refuse on it' % name)
    # and the hook must not decide: no blend factor constant anywhere in it
    for lit in ('0x0302', '0x0303', '0x8006'):
        if lit in h:
            p.append('a GL blend enum %s is written into the hook; deciding '
                     'belongs to the classifier' % lit)
    r['m1f-blend-is-carried'] = p

    # the shade control comes from the generated table, never from a literal
    p = []
    if tri:
        # M1k split triBuild; the slot switch lives in triPrologue now.  Find the
        # function that fills the slot rather than naming one, so the next split
        # does not make this rule stop looking.
        k = t.find('OSRDN_TRI_SLOT_SE_CNTL')
        fn = enclosing(t, k) if k >= 0 else None
        if fn is None:
            p.append('nothing in the tri unit fills the SE_CNTL slot')
        elif ('OSRDN_TRI_SE_CNTL_GOURAUD' not in fn[1] or
              'OSRDN_TRI_SE_CNTL_FLAT' not in fn[1]):
            p.append('the SE_CNTL slot is not filled from the generated values '
                     '(it is filled in %s)' % fn[0])
        for m in re.finditer(r'0x48[0-9a-fA-F]{6}', t):
            p.append('a shade-control value %s is typed into the tri unit; it must '
                     'come from the generated table' % m.group(0))
    r['m1e-shade-value-is-generated'] = p

    # A2 -- the nine decline, and touch nothing
    p = []
    for name, ret in DECLINE.items():
        b = body(s, name)
        if not b:
            p.append('%s is not defined in the stub unit' % name)
            continue
        rets = [x.strip() for x in re.findall(r'return\s*([^;]*);', b)]
        if ret is None:
            if rets:
                p.append('%s returns %r but declares no value' % (name, rets))
        elif rets != [ret]:
            p.append('%s returns %r, the decline value is %r' % (name, rets, ret))
        # writes through a pointer argument, however spelt -- including the ways
        # that use no '=' at all.  The undefined-symbol gate found the compiler
        # emitting memcpy for a struct assignment, which is the same door:
        # memcpy(buffer, ...) writes a caller's buffer without an assignment.
        if re.search(r'\*\s*\w+\s*=[^=]', b) or re.search(r'\w+\s*\[[^\]]*\]\s*=[^=]', b):
            p.append('%s writes through one of its arguments' % name)
        for fn in ('memcpy', 'bcopy', 'memset', 'bzero', 'strcpy', 'sprintf'):
            if re.search(r'\b%s\s*\(' % fn, b):
                p.append('%s calls %s(), which writes without an assignment' % (name, fn))
        # globals: only its own counter
        for m in re.finditer(r'\b(\w+)\s*(=[^=]|\+\+|--|\+=)', b):
            if m.group(1) not in ('osrdn_hook_count',):
                p.append('%s assigns to %s' % (name, m.group(1)))
        if 'osrdn_hook_count' not in b:
            p.append('%s does not count its call' % name)
    r['m1b-stubs-decline'] = p

    # A3 -- UpdateState writes only the recorded stride/orientation and counters
    p = []
    b = body(h, 'OpenStepMesaAccelUpdateState')
    if not b:
        p.append('UpdateState is not defined')
    else:
        allowed = ('osrdnCounts.rowLength', 'osrdnCounts.yUp', 'osrdnCounts.cls',
                   # M3g: a Y_UP-false state is kept off the card here; the
                   # counter and the class it clears are UpdateState's own
                   'osrdnCounts.notUp',
                   'osrdnCounts.why', 'osrdnCounts.rasterSeen', 'osrdnCounts.rasterDeclined',
                   'osrdnCounts.rasterLast',
                   's.rasterMask', 's.rgba', 's.smooth', 's.stipple',
                   's.texture', 's.depthBits', 's.rowLength', 's.yUp', 'cls', 'why',
                   # M1d: two more classifier inputs and the two counters that
                   # record them.  The rule is about UpdateState not reaching
                   # outside itself, and these do not.
                   's.shadeModel', 's.triangleCaps',
                   'osrdnCounts.shade', 'osrdnCounts.caps',
                   # M1f: six more classifier inputs and the counter for them.
                   # UpdateState still only READS ctx and WRITES its own two
                   # structs, which is what this rule is about.
                   's.blendEnabled', 's.blendSrcRGB', 's.blendDstRGB',
                   's.blendSrcA', 's.blendDstA', 's.blendEquation',
                   'osrdnCounts.blend',
                   # M1g: which texture it is, and the local that reads it
                   's.texUnit0', 's.texWidth', 's.texHeight', 's.texBorder',
                   's.texFormat', 's.texMinFilter', 's.texMagFilter',
                   's.texWrapS', 's.texWrapT', 's.texEnvMode', 'osrdnCounts.rmask',
                   's.texMip', 's.texComplete', 's.texLodOk',      # G4-4 K5, G4-5
                   'tv', 'tk', 'osrdnCounts.texWhy', 'osrdnCounts.texWhyVal',   # G4-6: counters only
                   # M1i: which depth, not whether
                   's.depthFunc', 's.depthMask',
                   's.alphaEnabled', 's.alphaFunc', 's.alphaRef',      # G4-3 K2
                   'to', 'osrdnCounts.tex')
        # comparisons first: without this, `cls >= 0` looks like an assignment to
        # ">" and the rule reports a name that is not in the source at all
        nocmp = re.sub(r'[<>!=+\-*/%&|^]=|=[=]', ' ', b)
        for m in re.finditer(r'([\w.\[\]]+(?:->[\w.\[\]]+)*)\s*(?:=|\+\+)', nocmp):
            t = re.sub(r'\[[^\]]*\]', '', m.group(1))
            if t not in allowed:
                p.append('UpdateState assigns to %s, which is not on the list' % m.group(1))
        if 'osrdn_class_of' not in b:
            p.append('UpdateState does not classify')
        if 'osrdnHookInstall' not in b:
            p.append('UpdateState does not install (or decline to install) anything')
        if 'osrdn_hook_count' not in b:
            p.append('UpdateState does not count its call')
    r['m1b-updatestate-writes'] = p

    # the counters must be distinct per hook, or "never called" and "declined"
    # cannot be told apart
    p = []
    used = set(re.findall(r'osrdn_hook_count\(\s*(OSRDN_HOOK_\w+)\s*\)', h + s))
    want = set(re.findall(r'#define\s+(OSRDN_HOOK_\w+)\s+\d+',
                          open(os.path.join(MESA, 'OSRDNMesaHook.h')).read()))
    want.discard('OSRDN_HOOKS')
    if used != want:
        p.append('counted %s, the header declares %s' % (sorted(used), sorted(want)))
    r['m1b-one-counter-each'] = p

    # The classifier stays testable on the host.  M1g made it include the
    # GENERATED table, so the rule is narrowed rather than dropped: its own
    # header, plus generated headers that are nothing but #defines.  A header
    # that includes anything itself could drag Mesa back in through the side
    # door, so that is checked too -- "generated" is not a promise, it is a
    # property this reads.
    p = []
    GENERATED_OK = ('OSRDNMesaTriTable.h',)
    inc = re.findall(r'#\s*include\s*[<"]([^>"]+)[>"]', c)
    extra = [x for x in inc if x != 'OSRDNMesaClass.h' and x not in GENERATED_OK]
    if extra:
        p.append('the classifier includes %s' % extra)
    if 'OSRDNMesaClass.h' not in inc:
        p.append('the classifier does not include its own header')
    for g in inc:
        if g in GENERATED_OK:
            gp = os.path.join(MESA, g)
            if not os.path.exists(gp):
                p.append('%s is included but not present' % g)
            else:
                gi = re.findall(r'#\s*include\s*[<"]([^>"]+)[>"]',
                                open(gp).read())
                if gi:
                    p.append('%s is not self-contained: it includes %s' % (g, gi))
    r['m1b-classifier-pure'] = p

    # ---- M1c ------------------------------------------------------------
    su = uncomment(surf if surf is not None else open(SURF).read())

    # A4: one mmap, and its offset is what CAPS gave us.  Declarations are not
    # calls -- counting `extern char *mmap(...)` as one reported two.
    p = []
    calls = re.sub(r'\bextern\b[^;]*;', ' ', su)
    n = len(re.findall(r'\bmmap\s*\(', calls))
    if n != 1:
        p.append('mmap is called %d times, want exactly one place' % n)
    # balance the parentheses: a non-greedy match stopped at the ')' of a cast
    # inside the argument list and reported the wrong text
    m = re.search(r'\bmmap\s*\(', calls)
    arglist = ''
    if m:
        i, d = m.end() - 1, 0
        while i < len(calls):
            if calls[i] == '(':
                d += 1
            elif calls[i] == ')':
                d -= 1
                if d == 0:
                    arglist = calls[m.start():i + 1]
                    break
            i += 1
    if m and 'caps->winStart' not in arglist:
        p.append('the mmap offset is %r, not the window CAPS gave' % arglist[-48:])
    if re.search(r'\bmmap\s*\(', uncomment(hook) + uncomment(stubs)):
        p.append('mmap appears outside the surface unit')
    r['m1c-one-mapping'] = p

    # A5: no card address written into the source.  An all-ones word is an
    # arithmetic limit, not an address -- the overflow guard uses one, and
    # flagging it reported a bug that was not there.
    p = []
    for m in re.finditer(r'0x[0-9a-fA-F]{6,}', su):
        v = m.group(0)
        if re.match(r'0x[fF]+$', v):
            continue
        p.append('a constant address %s is written in the surface unit' % v)
    r['m1c-no-constant-address'] = p

    # A6: binding and ownership are two fields
    p = []
    if not re.search(r'\bsurfOwner\b', su) or not re.search(r'\bsurfBound\b', su):
        p.append('the surface unit does not have both an owner and a bound field')
    else:
        # a refused take must clear the binding and NOT the ownership
        b = body(su, 'osrdn_surf_take')
        seg = b[b.find('if (w != OSRDN_SURF_OK)'):] if 'if (w != OSRDN_SURF_OK)' in b else ''
        if 'surfBound = 0' not in seg:
            p.append('a refusal does not let the binding go')
        if re.search(r'surfOwner\s*=\s*0', seg):
            p.append('a refusal clears the ownership, which the contract says it must not')
    r['m1c-bound-is-not-owned'] = p

    # A7: Mirror does nothing when nothing is bound
    p = []
    b = body(su, 'osrdn_surf_mirror')
    if not b:
        p.append('the mirror is not there')
    else:
        # It must ask whether there is anything to COPY, and must NOT ask
        # whether this context is still bound: the allocator has already let
        # the binding go by the time the leave path mirrors, so a mirror that
        # tested bound would copy nothing on the one path that saves the
        # drawing (measured, first approval run: mirrors=0 idle=1).
        if not re.search(r'if\s*\(surfBase == 0 \|\| surfApp == 0\)', b):
            p.append('the mirror does not begin by asking whether there is anything to copy')
        if re.search(r'\bsurfBound\b', b):
            p.append('the mirror consults the binding, which is already 0 when it matters')
    r['m1c-mirror-idle-is-ok'] = p

    # ---- M1g: a field the classifier compares against a CONSTANT may not be
    # handed a boolean.
    #
    # This is the bug that reached the card.  The hook wrote
    #     s.texture = ctx->Texture.ReallyEnabled ? 1 : 0;
    # and the classifier asks
    #     s->texture != TEXTURE0_2D_          /* 0x2 */
    # so every textured triangle was declined, in a run whose own log said
    # `tex=1` -- which is what the boolean recorded, and is true, and is not what
    # was passed on.  sim_class drives the classifier with the enum and could not
    # see it; check_hook listed the field as assigned and could not see it either.
    # Neither tool was wrong about what it checked; nothing checked the JOIN.
    #
    # The rule is arithmetic: a `? 1 : 0` can only ever equal 0 or 1, so if the
    # constant it is compared against is anything else the test can never pass.
    p = []
    consts = dict((m.group(1), int(m.group(2), 0)) for m in
                  re.finditer(r'#define\s+(\w+_)\s+(0x[0-9a-fA-F]+|\d+)UL', cls))
    boolean = set(re.findall(r's\.(\w+)\s*=\s*[^;]*\?\s*1\s*:\s*0\s*;', hook))
    for m in re.finditer(r's->(\w+)\s*!=\s*(\w+_)\b', cls):
        f, name = m.group(1), m.group(2)
        if name not in consts or consts[name] in (0, 1):
            continue
        if f in boolean:
            p.append('the classifier compares s->%s against %s (0x%x) but the hook '
                     'assigns it a boolean -- that test can never pass'
                     % (f, name, consts[name]))
    r['m1g-no-boolean-for-a-constant'] = p

    # ---- M1g: the hook does not lay out a vertex.
    #
    # It used to, in two shapes at once, and the five-word writes landed inside
    # the seven-word block (sim_pack.py).  The layout now lives in the tri unit
    # where one stride is chosen once; this keeps it there, because the way it
    # comes back is somebody adding "just one more word" here.
    p = []
    b = tripath(h)
    if not b:
        p.append('osrdnHookTriangle is not there to check')
    else:
        # the DECLARATION is not indexing: `unsigned long vtx[3 * ...]` says
        # how big the buffer is, which this file does have to know
        used = re.sub(r'unsigned long vtx\s*\[[^\]]*\]', '', b)
        if re.search(r'\bvtx\s*\[', used):
            p.append('the triangle function indexes vtx itself; the packing belongs '
                     'to osrdn_tri_vertex')
        # M1t: the inline path writes the slots through the SHARED macro, which
        # is the header's single copy of the layout -- that is allowed.  Writing
        # them out by hand is not, and the `vtx[` rule above still refuses it.
        # What must never happen is neither: a hook that packs some other way.
        if 'osrdn_tri_vertex' not in b:
            p.append('the triangle function does not use osrdn_tri_vertex')
        if 'OSRDN_TRI_VERTEX_PUT' in b and 'OSRDN_TRI_VERTEX_AT' not in b:
            p.append('the inline path writes the slots but computes the vertex '
                     'address some other way')
        if re.search(r'\bq\s*\[\s*[0-9]', b):
            p.append('the triangle function writes numbered slots itself; the '
                     'layout belongs to the header macro')
    r['m1g-hook-does-not-pack'] = p

    # ---- M1i: the vertex z goes out in the CARD's units.
    #
    # VB->Win.data[i][2] is already multiplied by DepthMaxF; the card wants
    # [0,1] and floors z * 2^n itself.  Sending it unscaled submitted two
    # triangles, drew nothing, and every counter said yes -- the picture was the
    # only thing that knew.  Mesa's own code divides in exactly this place
    # (feedback.c 171), so the rule is that ours does too.
    p = []
    b = tripath(h)
    if not b:
        p.append('osrdnHookTriangle is not there to check')
    elif re.search(r'Win\.data\[idx\[i\]\]\[2\]', b) and \
            not re.search(r'Win\.data\[idx\[i\]\]\[2\]\s*/\s*\n?\s*'
                          r'ctx->Visual->DepthMaxF', b):
        p.append('the vertex z is sent without dividing by DepthMaxF, so it is '
                 'in Mesa\'s depth units and not the card\'s')
    r['m1i-z-is-scaled'] = p
    # ---- M3b: we cull, render_triangle's way; and the group path goes to the
    #      card only when the triangle function in force is ours
    #      (docs/M3B_PLAN.md 7-8)
    p = []
    flat = re.sub(r'\s+', ' ', h)
    for want in ('if (ctx->backface_sign != 0.0F) {',
                 'GLfloat ex = win[v1][0] - win[v0][0];',
                 'GLfloat ey = win[v1][1] - win[v0][1];',
                 'GLfloat fx = win[v2][0] - win[v0][0];',
                 'GLfloat fy = win[v2][1] - win[v0][1];',
                 'GLfloat cc = ex*fy-ey*fx;',
                 'if (cc * ctx->backface_sign > 0) { osrdnCounts.culled++; return; }'):
        if want not in flat:
            p.append('M3b: the self-culling is not render_triangle\'s any more: missing %r' % want)
    k = flat.find('osrdnCounts.triangles++;')
    kc = flat.find('if (ctx->backface_sign != 0.0F) {')
    ks = flat.find('osrdn_tri_send(')
    if min(k, kc, ks) >= 0 and not (k < kc < ks):
        p.append('M3b: the culling test is not between the call count and the send')
    r['m3b-we-cull'] = p

    p = []
    if 'if (!st.ok || slot < 0 || ctx->TriangleFunc != osrdnHookTriangle) {' not in flat:
        p.append('M3b: the group path does not check that the triangle function in force '
                 'is ours -- it would skip render_triangle and a declined state')
    r['m3b-group-only-ours'] = p

    # ---- M3g: glFinish copies the surface back; Y_UP false keeps the card
    #      out; the surface refuses an application row that is not the width
    #      (docs/M3G_PLAN.md)
    p = []
    fb = re.sub(r'\s+', ' ', body(h, 'osrdnHookFinish'))
    if not fb:
        p.append('M3g: osrdnHookFinish is not defined')
    else:
        # G3 sharpened it: the flush still comes first, then the present gate (a
        # stand-down that returns WITHOUT copying, docs/G3_PRESENT_PLAN.md 2-2),
        # then the one and only mirror
        want = ('if (!osrdn_surf_bound_to((const void *) ctx->DriverCtx) || osrdn_surf_app_buffer() == 0) return;',
                'osrdnFlushOutside(); if (osrdn_present_active()) { osrdnCounts.finishStoodDown++; return; } '
                'osrdn_surf_mirror();')
        for w in want:
            if w not in fb:
                p.append('M3g: glFinish does not %r' % w)
        if fb.count('osrdn_surf_mirror();') != 1:
            p.append('M3g: glFinish mirrors %d times, want exactly once after the flush' % fb.count('osrdn_surf_mirror();'))
        if fb.count('osrdnFlushOutside();') != 1:
            p.append('M3g: glFinish flushes %d times, want once' % fb.count('osrdnFlushOutside();'))
    ib = re.sub(r'\s+', ' ', body(h, 'osrdnHookInstall'))
    kf = ib.find('if (ctx->Driver.Finish == 0) ctx->Driver.Finish = osrdnHookFinish;')
    kt = ib.find('if (!take) {')
    if kf < 0:
        p.append('M3g: the Finish hook is not installed into an empty field')
    elif kt >= 0 and kf > kt:
        p.append('M3g: the Finish hook is installed only for a taken state -- software '
                 'draws into the surface too')
    ub = re.sub(r'\s+', ' ', body(h, 'OpenStepMesaAccelUpdateState'))
    ky = ub.find('if (!yUp && cls == OSRDN_CLASS_WOULD_TAKE) { osrdnCounts.notUp++; cls = -1; }')
    ki = ub.find('osrdnHookInstall(ctx, cls == OSRDN_CLASS_WOULD_TAKE);')
    if ky < 0 or ki < 0 or ky > ki:
        p.append('M3g: a Y_UP-false state is not kept off the card before the install')
    if surf is not None:
        sb = re.sub(r'\s+', ' ', uncomment(surf))
        if 'appRowPixels != width' not in sb:
            p.append('M3g: the surface takes an application row that is not the width')
    r['m3g-finish-sync'] = p

    # ---- G3b (docs/G3B_CLEAR_PLAN.md 2-3): the card clears; the colour bit leaves
    #      Mesa's mask only when the card did it, the depth bit never does
    p = []
    cb = re.sub(r'\s+', ' ', body(h, 'osrdnHookClear'))
    if not cb:
        p.append('G3b: osrdnHookClear is not defined')
    else:
        ok = cb.find('if (osrdn_card_clear(flags, colour, far, (int) ctx->DrawBuffer->Width, (int) ctx->DrawBuffer->Height, &dwhy)) {')
        drop = cb.find('left &= ~DD_FRONT_LEFT_BIT;')
        els = cb.find('} else {', ok if ok >= 0 else 0)
        if ok < 0:
            p.append('G3b: the clear does not go to the card through osrdn_card_clear')
        if drop < 0 or not (ok < drop < els):
            p.append('G3b: the colour bit is not taken from Mesa inside the success branch only')
        if 'left &= ~DD_DEPTH_BIT' in cb:
            p.append('G3b: the depth bit is taken from Mesa (M1j: Mesa clears its own too)')
        if cb.count('left &= ~DD_FRONT_LEFT_BIT;') != 1:
            p.append('G3b: the colour bit is taken %d times' % cb.count('left &= ~DD_FRONT_LEFT_BIT;'))
        if 'colour = osrdnWantWord(cc, rs, gs, bs, as);' not in cb:
            p.append('G3d: the clear colour is not the pixel packing (osrdnWantWord): the vertex word swaps R and B')
    r['g3b-clear-hook'] = p

    # ---- G4-1b (docs/G4_GLQUAKE_PLAN.md 5 T1, T2): a texture is on the card
    #      only through its residency record, and the record dies with the epoch
    p = []
    res = body(h, 'osrdnTexResident')
    st = body(h, 'osrdnTriStateOf')
    drop = body(h, 'osrdnTexDrop')
    buf = body(h, 'OpenStepMesaAccelBuffer')
    if not res:
        p.append('G4-1b: osrdnTexResident is not defined')
    elif 'r->epoch != osrdnTexEpoch' not in res:
        p.append('G4-1b: a record from an older epoch is believed (its block is gone with the arena)')
    if not st:
        p.append('G4-1b: osrdnTriStateOf is not defined')
    else:
        i0 = st.find('if (!osrdnTexResident(to, &org, &tw, &th, levels))\n            return;')
        i1 = st.find('osrdn_tri_texture_set(')
        if i0 < 0 or i1 < 0 or not (i0 < i1):
            p.append('G4-1b: the Tri unit is told a texture before the image is resident (or without the refusal)')
    if not drop:
        p.append('G4-1b: osrdnTexDrop is not defined')
    else:
        j0 = drop.find('osrdn_texarena_free(r->origin, r->epoch)')
        j1 = drop.find('FREE(r);')
        if j0 < 0 or j1 < 0 or not (j0 < j1):
            p.append('G4-1b: the record is freed before (or without) giving its block back')
        if 'img->DriverData = 0;' not in drop:
            p.append('G4-1b: a dropped record stays in DriverData (a dangling pointer at the next draw)')
    for fn, prev in (('osrdnHookTexImage', 'osrdnPrevTexImage'),
                     ('osrdnHookTexSubImage', 'osrdnPrevTexSubImage'),
                     ('osrdnHookDeleteTexture', 'osrdnPrevDeleteTexture')):
        b = body(h, fn)
        if not b:
            p.append('G4-1b: %s is not defined' % fn)
        elif ('(*%s)(' % prev) not in b:
            p.append('G4-1b: %s does not chain to what was there' % fn)
    if body(h, 'osrdnHookTexSubImage') and '->valid = 0;' not in body(h, 'osrdnHookTexSubImage'):
        p.append('G4-1b: a sub-image leaves the texels on the card marked current')
    if not buf:
        p.append('G4-1b: OpenStepMesaAccelBuffer is not defined')
    else:
        k0 = buf.find('osrdnTexEpoch++;')
        k1 = buf.find('osrdn_texarena_set(OSRDN_TEX_BYTE_OFF,')
        if k0 < 0 or k1 < 0 or not (k0 < k1):
            p.append('G4-1b: a (re)taken surface does not move the epoch before the arena is set')
        if 'osrdn_surf_reserve(OSRDN_TEX_BYTE_OFF + OSRDN_TEX_ARENA_BYTES);' not in buf:
            p.append('G4-1b: the reserve is not the arena (the mapping would end at the 8 x 8 texels)')
    if ('s.rasterMask = ((unsigned long)ctx->RasterMask & ~(unsigned long)TEXTURE_BIT) |\n'
        '                   (ctx->Texture.ReallyEnabled ? (unsigned long)TEXTURE_BIT : 0UL);') not in h:
        p.append('G4-1b: the classifier is given RasterMask\'s texture bit, which Mesa leaves stale (state.c 990 vs 957)')
    if 'unsigned long ww = tex ? osrdnBits(VB->Win.data[idx[i]][3]) : osrdnBits(1.0F);' not in h:
        p.append('G4-1b: a textured vertex does not carry Mesa\'s 1/w (Win[3]); the card would interpolate s, t affinely')
    if 'osrdnUploadTexture' in h:
        p.append('G4-1b: the one-shot 8 x 8 upload is still there (two owners of the texels)')
    r['g4-1b-residency'] = p

    # ---- G4-3 K2 (docs/G4_3_KERNEL_PLAN.md 3): the alpha test reaches the Tri unit as a code, and
    #      only through the classifier's function
    p = []
    st = body(h, 'osrdnTriStateOf')
    for f in ('ctx->Color.AlphaEnabled', 'ctx->Color.AlphaFunc', 'ctx->Color.AlphaRef'):
        if f not in h:
            p.append('K2: the hook does not read %s' % f)
    if not st or 'osrdn_tri_alpha_set(ac);' not in st or 'osrdn_class_alpha_code(' not in st:
        p.append('K2: osrdnTriStateOf does not hand the Tri unit the alpha code from the classifier')
    if st and 'if (ctx->Color.AlphaEnabled && ac == 0UL) {' not in st:
        p.append('K2: an alpha test with no code is sent anyway (codeGap)')
    r['g43-k2-alpha'] = p

    # ---- G4-2 B1: a batch lives across brackets, so every event that must
    #      see the card's triangles first closes it -- the list in
    #      docs/G4_2_BATCH_PLAN.md 3, each line one call in one named function,
    #      BEFORE the thing it protects.  And RenderFinish asks the verifier
    #      instead of flushing, with the promise kept the new way: dead indices
    #      are counted lost, never redrawn.
    p = []
    hh = open(os.path.join(MESA, 'OSRDNMesaHook.h')).read()
    reasons = re.findall(r'^#define\s+(OSRDN_FLUSH_[A-Z]+)\s+(\d+)', hh, re.M)
    names = [n for n, _v in reasons if n != 'OSRDN_FLUSH_REASONS']
    HOME = {                        # reason -> (function, what it must precede)
        'OSRDN_FLUSH_OUTSIDE': ('osrdnFlushOutside', None),
        'OSRDN_FLUSH_BRACKET': ('osrdnBracketEnd', None),
        'OSRDN_FLUSH_STATE': ('osrdnTriangleWith', 'osrdn_tri_batch_add('),
        'OSRDN_FLUSH_CTX': ('osrdnTriangleWith', 'osrdn_tri_batch_add('),
        'OSRDN_FLUSH_REFUSED': ('osrdnBracketEnd', None),
        'OSRDN_FLUSH_POINTS': ('osrdnHookPoints', '(*saved)(ctx, first, last);'),
        'OSRDN_FLUSH_LINES': ('osrdnHookLine', '(*saved)(ctx, v1, v2, pv);'),
        'OSRDN_FLUSH_DELEGATE': ('osrdnTriangleWith', '(*sw)(ctx, v0, v1, v2, pv);'),
        'OSRDN_FLUSH_LEAVE': ('osrdnHookInstall', 'return;'),
        'OSRDN_FLUSH_CLEAR': ('osrdnHookClear', 'osrdn_card_clear('),
        'OSRDN_FLUSH_GLFLUSH': ('osrdnHookFlush', '(*osrdnPrevFlush)(ctx);'),
        'OSRDN_FLUSH_READPIX': ('osrdnHookReadPixels', '(*osrdnPrevReadPixels)('),
        'OSRDN_FLUSH_COPYPIX': ('osrdnHookCopyPixels', '(*osrdnPrevCopyPixels)('),
        'OSRDN_FLUSH_DRAWPIX': ('osrdnHookDrawPixels', '(*osrdnPrevDrawPixels)('),
        'OSRDN_FLUSH_BITMAP': ('osrdnHookBitmap', '(*osrdnPrevBitmap)('),
        'OSRDN_FLUSH_TEXUPLOAD': ('osrdnTexResident', 'osrdn_tex_upload_at('),
        'OSRDN_FLUSH_TEXDROP': ('osrdnTexDrop', 'osrdn_texarena_free('),
        'OSRDN_FLUSH_SURFACE': ('OpenStepMesaAccelBuffer', 'osrdn_surf_take('),
        'OSRDN_FLUSH_RELEASE': ('OpenStepMesaAccelReleaseBuffer', 'osrdn_surf_release('),
        'OSRDN_FLUSH_ALONE': ('osrdnTriangleWith', 'osrdn_tri_send('),
    }
    if sorted(names) != sorted(HOME):
        p.append('the reasons in the header are %s, the rule knows %s'
                 % (sorted(set(names) - set(HOME)), sorted(set(HOME) - set(names))))
    for n in names:
        if n not in HOME:
            continue
        fname, before = HOME[n]
        calls = [m.start() for m in re.finditer(r'osrdnFlushFor\(%s\)' % n, h)]
        if len(calls) != 1:
            p.append('%s is flushed for %d times, want once' % (n, len(calls)))
            continue
        fn = enclosing(h, calls[0])
        if fn is None or fn[0] != fname:
            p.append('%s is flushed for in %s, want %s' % (n, fn[0] if fn else '?', fname))
            continue
        if before is not None:
            fb = fn[1]
            k = fb.find(before)
            if k < 0:
                p.append('%s: %s never reaches %r' % (n, fname, before))
            elif fb.find('osrdnFlushFor(%s)' % n) > k:
                p.append('%s: the flush in %s comes AFTER %r' % (n, fname, before))
    # osrdnFlushOutside (the M1k shape) is called from four places and no more,
    # and in RenderStart and UpdateState only with the span knob off: with it
    # on, a leftover is a batch to keep and a state change is a segment
    fo = [(enclosing(h, m.start()) or ('?', ''))[0] for m in re.finditer(r'osrdnFlushOutside\(\);', h)]
    if sorted(fo) != ['OpenStepMesaAccelMirror', 'OpenStepMesaAccelUpdateState', 'osrdnHookFinish', 'osrdnHookRenderStart']:
        p.append('osrdnFlushOutside is called from %s' % sorted(fo))
    for fn_name in ('OpenStepMesaAccelUpdateState', 'osrdnHookRenderStart'):
        fb2 = flatten(body(h, fn_name))
        if 'if (!osrdn_tri_span_enabled()) { osrdnFlushOutside();' not in fb2 and \
           'if (!osrdn_tri_span_enabled()) osrdnFlushOutside();' not in fb2:
            p.append('%s flushes without asking the span knob' % fn_name)
    # the only callers of the flush itself: the reason wrapper and the bracket's
    # empty case -- anything else closes a batch without saying why
    homes = sorted(set((enclosing(h, m.start()) or ('?',))[0]
                       for m in re.finditer(r'osrdnFlushBatch\(\);', h)))
    if homes != ['osrdnBracketEnd', 'osrdnFlushFor']:
        p.append('osrdnFlushBatch is called from %s; want only osrdnFlushFor and osrdnBracketEnd' % homes)
    # F2: RenderFinish asks; the bracket end verifies before anything is sent,
    # keeps an accepted batch (marks it stale, sends nothing), and on a refusal
    # sends only the verified prefix and redraws only the fresh tail
    rf = flatten(body(h, 'osrdnHookRenderFinish'))
    if 'osrdnBracketEnd();' not in rf or 'osrdnFlushBatch' in rf:
        p.append('RenderFinish does not go through osrdnBracketEnd (or still flushes itself)')
    be = flatten(body(h, 'osrdnBracketEnd'))
    if not be:
        p.append('osrdnBracketEnd is not defined')
    else:
        v = be.find('osrdn_tri_batch_verify(')
        k = be.find('if (!osrdn_tri_span_enabled())')
        acc = be.find('if (why == CP_R7_WHY_OK) { osrdnCounts.prevalidated++; osrdnPend.stale = osrdnPend.n; return; }')
        tr = be.find('osrdn_tri_batch_truncate(keep);')
        fl = be.find('osrdnFlushFor(OSRDN_FLUSH_REFUSED);')
        lp = be.find('for (i = keep; i < n; i++)')
        if min(v, k, acc, tr, fl, lp) < 0:
            p.append('the bracket end lacks one of: span knob, verify, accept-and-mark-stale, truncate, prefix flush, tail replay (%s)'
                     % [v, k, acc, tr, fl, lp])
        elif not (k < v < acc < tr < fl < lp):
            p.append('the bracket end does those out of order (%s)' % [k, v, acc, tr, fl, lp])
        if be.count('osrdn_surf_window(&winBytes)') != 1:
            p.append('the verifier\'s window bound does not come from the surface mapping')
    # the replay never reads a dead index
    fbb = flatten(body(h, 'osrdnFlushBatch'))
    g = fbb.find('if (i < stale) {')
    lost = fbb.find('osrdnCounts.lostAtFlush++; continue; }')
    swc = fbb.find('(*sw)(osrdnPend.ctx')
    if min(g, lost, swc) < 0 or not (g < lost < swc):
        p.append('the replay does not skip (and count) stale entries before calling the software function')
    if 'osrdnPend.stale = 0UL;' not in fbb:
        p.append('the flush does not clear the stale mark')
    # RenderStart flushes only with the knob off; with it on, an unfinished
    # bracket is marked, not redrawn
    rs = flatten(body(h, 'osrdnHookRenderStart'))
    if 'if (!osrdn_tri_span_enabled()) { osrdnFlushOutside(); } else if (osrdnPend.n > osrdnPend.stale) { osrdnCounts.unfinished++; osrdnPend.stale = osrdnPend.n; }' not in rs:
        p.append('RenderStart does not (knob off: flush) / (knob on: mark an unfinished bracket stale)')
    # F10: no batching for a multipass state, read never written
    if '|| osrdnMultipass)' not in flatten(tripath(h)):
        p.append('the triangle path does not stand batching down for a multipass state')
    if 'osrdnMultipass = (ctx->Driver.MultipassFunc != 0) ? 1 : 0;' not in flatten(inst):
        p.append('the install does not read MultipassFunc')
    # F3: the wrappers go in by the four steps, from BOTH UpdateState paths
    pr = body(h, 'osrdnInstallPrims')
    for what, steps in (('points', ('if (ctx->Driver.PointsFunc == 0)', 'gl_set_point_function(ctx);',
                                    'osrdnSaved[slot].points = ctx->Driver.PointsFunc;',
                                    'ctx->Driver.PointsFunc = osrdnHookPoints;')),
                        ('lines', ('if (ctx->Driver.LineFunc == 0)', 'gl_set_line_function(ctx);',
                                   'osrdnSaved[slot].line = ctx->Driver.LineFunc;',
                                   'ctx->Driver.LineFunc = osrdnHookLine;'))):
        idx = [pr.find(x) for x in steps]
        if min(idx) < 0 or idx != sorted(idx):
            p.append('the %s wrapper is not installed by the four steps in order (%s)' % (what, idx))
        # and never over itself: the guard is on OUR pointer (the Clear precedent)
        guard = 'if (ctx->Driver.%s != %s) {' % (('PointsFunc', 'osrdnHookPoints') if what == 'points' else ('LineFunc', 'osrdnHookLine'))
        if guard not in pr:
            p.append('the %s wrapper may save its own pointer (no %r guard)' % (what, guard))
    if flatten(inst).count('osrdnInstallPrims(ctx, slot);') != 2:
        p.append('osrdnInstallPrims is called %d times from the install; want one per path (take, leave)'
                 % flatten(inst).count('osrdnInstallPrims(ctx, slot);'))
    r['g42-flush-points'] = p

    # ---- G4-5 (docs/G4_5_MIP_PLAN.md 2): the chain on the card follows every level Mesa holds,
    #      and a mip filter is admitted only for the lambda GL would compute
    p = []
    ti = flatten(body(h, 'osrdnHookTexImage'))
    if 'if (tObj != 0 && level == 0) osrdnTexDrop(tObj->Image[0]);' not in ti:
        p.append('TexImage on level 0 no longer drops the record')
    if 'else if (tObj != 0 && level > 0 && tObj->Image[0] != 0 && tObj->Image[0]->DriverData != 0) ((osrdnTexRes *) tObj->Image[0]->DriverData)->valid = 0;' not in ti:
        p.append('TexImage on a level above 0 does not invalidate the chain')
    ts = flatten(body(h, 'osrdnHookTexSubImage'))
    if 'if (tObj != 0 && level >= 0 && tObj->Image[0] != 0 && tObj->Image[0]->DriverData != 0) ((osrdnTexRes *) tObj->Image[0]->DriverData)->valid = 0;' not in ts:
        p.append('TexSubImage does not invalidate the chain for every level')
    st2 = flatten(body(h, 'osrdnTriStateOf') + body(h, 'OpenStepMesaAccelUpdateState'))
    want = ('s.texLodOk = (to->BaseLevel == 0 && to->MinLod <= 0.0F && to->MaxLod >= to->M && '
            'ctx->Texture.Unit[0].LodBias == 0.0F && to->M <= 11.0F) ? 1UL : 0UL;')
    if want not in st2:
        p.append('the admission does not ask BaseLevel, MinLod, MaxLod, LodBias and the level count')
    cc = uncomment(cls)
    mcls = re.search(r'\nclassMinOk\(const osrdn_class_state \*s\)\n\{(.*?)\n\}', cc, re.S)
    cb = flatten(mcls.group(1)) if mcls else ''
    for need in ('if (s->texComplete == 0UL || s->texLodOk == 0UL) return 0;',
                 'return (OSRDN_MIP_MEASURED & (1UL << code)) != 0UL ? 1 : 0;'):
        if need not in cb:
            p.append('classMinOk lacks %r' % need)
    # the legacy notifications are the only texture path: a new-style Driver.TexImage2D /
    # TexSubImage2D that returned success would skip them (teximage.c 2156-2174) -- nobody may
    # install one (codex G4-5 review; grep of Mesa core and OSMesa: none)
    osm_path = os.path.join(PROJ, '..', 'openstep-mesa342', 'upstream', 'Mesa-3.4.2', 'src', 'OSmesa', 'osmesa.c')
    osm = uncomment(open(osm_path).read()) if os.path.exists(osm_path) else ''
    if not osm:
        p.append('osmesa.c is not where the rule looks')
    for name, text in (('the accel sources', allc), ('osmesa.c', osm)):
        if re.search(r'Driver\s*\.\s*Tex(Sub)?Image2D\s*=', text):
            p.append('%s install a new-style Driver.TexImage2D/TexSubImage2D, which would skip our invalidation' % name)
    r['g45-mip'] = p
    # G4-10 (docs/G4_10_MIP_SUBSTITUTE_PLAN.md 2): the two level-blending modes reach the card only as
    # the level-selecting mode with the same texel filter, and only the "all" knob sends their own values
    p = []
    ct = uncomment(tri) if tri else ''
    msent = re.search(r'\ntriMinSent\(int code\)\n\{(.*?)\n\}', ct, re.S)
    sb = flatten(msent.group(1)) if msent else ''
    if not msent:
        p.append('no triMinSent in the Tri unit')
    for need in ('if (osrdn_tri_mip_mode() == OSRDN_TRI_MIP_ALL) return code;',
                 'if (code == OSRDN_TRI_MIN_NEAREST_MIPMAP_LINEAR) return OSRDN_TRI_MIN_NEAREST_MIPMAP_NEAREST;',
                 'if (code == OSRDN_TRI_MIN_LINEAR_MIPMAP_LINEAR) return OSRDN_TRI_MIN_LINEAR_MIPMAP_NEAREST;'):
        if need not in sb:
            p.append('triMinSent lacks %r' % need)
    if re.search(r'triMinField\(triTex\.minCode\)', ct):
        p.append('the prologue maps triTex.minCode to a field without triMinSent')
    if len(re.findall(r'triMinField\(triMinSent\(triTex\.minCode\)\)', ct)) != 2:
        p.append('the prologue does not go through triMinSent at both TXFILTER uses')
    for need in ('(1UL << OSRDN_TRI_MIN_NEAREST_MIPMAP_LINEAR)', '(1UL << OSRDN_TRI_MIN_LINEAR_MIPMAP_LINEAR)'):
        if need not in uncomment(cls):
            p.append('OSRDN_MIP_MEASURED does not admit %s' % need)
    r['g410-substitute'] = p

    # G5-1b (docs/G5_1B_PRESENT_ONE_BLIT_PLAN.md 2): in present mode the surface is drawn
    # top-down so the screen takes it in one blit.  The flip is decided by present mode
    # and nothing else, applied to the one y both packing arms share, told to the
    # surface (its mirror reverses rows), and it comes AFTER the cull, which reads
    # Mesa's own y.
    p = []
    tw = body(h, 'osrdnTriangleWith')
    ftw = flatten(tw)
    if 'int flipY = osrdn_present_active();' not in ftw:
        p.append('the flip is not decided by present mode alone (int flipY = osrdn_present_active();)')
    if 'osrdnBits(flipY ? flipH - VB->Win.data[idx[i]][1] : VB->Win.data[idx[i]][1])' not in ftw:
        p.append('the vertex y is not H - y under the flip, on the one wy both arms share')
    if 'osrdn_surf_set_flipped(flipY);' not in ftw:
        p.append('the surface is not told which way up it was drawn')
    if 'flipH = flipY ? (GLfloat) OSRDNMesaSurfaceCounts()->height : 0.0F;' not in ftw:
        p.append('H does not come from the surface (OSRDNMesaSurfaceCounts()->height)')
    kc = ftw.find('ctx->backface_sign')
    kf = ftw.find('flipH - VB->Win.data')
    if kc < 0 or kf < 0 or kc > kf:
        p.append('the cull does not come before the flip')
    r['g51b-flip'] = p

    # ---- G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 1-4, 2-4): with submissions accepted, the CPU may
    # touch the window only after a RETIRE.  The hook's flush reasons each carry a verdict (the table
    # is as long as the reasons, in the reasons' order), the reasons that hand the window to
    # software are 1, the retire runs whether or not the flush had a batch, and the mirror retires
    # before it reads.  (The two uploads and depth_get: sim_texupload runs them.)
    p = []
    hdr = open(os.path.join(MESA, 'OSRDNMesaHook.h')).read()
    mr = re.search(r'#define\s+OSRDN_FLUSH_REASONS\s+(\d+)', hdr)
    names = [m.group(1) for m in re.finditer(r'#define\s+OSRDN_FLUSH_(\w+)\s+\d+', hdr) if m.group(1) != 'REASONS']
    mt = re.search(r'static const unsigned char osrdnFlushTouches\[OSRDN_FLUSH_REASONS\] = \{(.*?)\};', hook, re.S)
    if not mr or not mt:
        p.append('the reason count or the retire table is not where the rule looks')
    else:
        rows = re.findall(r'([01])\s*,?\s*/\*\s*(\w+)', mt.group(1))
        if len(rows) != int(mr.group(1)) or [n for _, n in rows] != names:
            p.append('the retire table has %d rows %s; the reasons are %s' % (len(rows), [n for _, n in rows], names))
        on = dict((n, v) for v, n in rows)
        for must in ('POINTS', 'LINES', 'DELEGATE', 'LEAVE', 'CLEAR', 'READPIX', 'COPYPIX', 'DRAWPIX', 'BITMAP', 'TEXUPLOAD'):
            if on.get(must) != '1':
                p.append('%s hands the window to the CPU and does not retire' % must)
    ff = flatten(uncomment(body(hook, 'osrdnFlushFor') or ''))
    ib, ir = ff.find('osrdnFlushBatch(); }'), ff.find('if (why >= 0 && why < OSRDN_FLUSH_REASONS && osrdnFlushTouches[why]) (void)osrdn_tri_retire_if_inflight();')
    if ib < 0 or ir < 0 or ir < ib:
        p.append('the retire is not after the batch flush and outside it (an empty batch can still have one in flight)')
    if surf is not None:
        mb = flatten(uncomment(body(surf, 'osrdn_surf_mirror') or ''))
        i1, i2 = mb.find('(void)osrdn_tri_retire_if_inflight();'), mb.find('src = (unsigned long *)surfBase;')
        if i1 < 0 or i2 < 0 or i1 > i2:
            p.append('the mirror reads the window before it retires')
    r['g52-retire'] = p

    # ---- G5-4 (docs/G5_4_READPIX_AND_CLEANUP_PLAN.md 1-2): glReadPixels in present mode reads the
    # top-down surface itself -- only there, only for what Mesa's fast path would take (its eight
    # transfer-op switches, word for word), and a decline is counted, never silent
    p = []
    rp = flatten(uncomment(body(hook, 'osrdnHookReadPixels') or ''))
    iflush, igate = rp.find('osrdnFlushFor(OSRDN_FLUSH_READPIX);'), rp.find('if (osrdn_present_active() && osrdn_surf_flipped()) {')
    if iflush < 0 or igate < 0 or iflush > igate:
        p.append('ReadPixels does not flush (and retire) before it decides, or does not gate on a flipped present surface')
    if 'osrdnCounts.readpixFlipped++; return GL_TRUE; }' not in rp or 'osrdnCounts.readpixFlipDeclined++;' not in rp:
        p.append('an answered read does not return GL_TRUE with its count, or a decline is not counted')
    rf = flatten(uncomment(body(hook, 'osrdnReadFlipped') or ''))
    for sw in ('ctx->Pixel.ScaleOrBiasRGBA', 'ctx->Pixel.MapColorFlag', 'ctx->ColorMatrix.type != MATRIX_IDENTITY',
               'ctx->Pixel.ScaleOrBiasRGBApcm', 'ctx->Pixel.ColorTableEnabled', 'ctx->Pixel.PostColorMatrixColorTableEnabled',
               'ctx->Pixel.MinMaxEnabled', 'ctx->Pixel.HistogramEnabled', 'pack->SkipImages != 0',
               'ctx->DrawBuffer->UseSoftwareAlphaBuffers', 'ctx->ReadBuffer->Height != sc->height'):
        if sw not in rf:
            p.append('the flipped reader does not refuse on %s' % sw)
    r['g54-readpix'] = p

    return r


MUTATIONS = [
    # ---- G5-4
    ('G5-4: the flipped reader runs outside present mode', 'hook',
     '    if (osrdn_present_active() && osrdn_surf_flipped()) {', '    if (osrdn_surf_flipped()) {', 'g54-readpix'),
    ('G5-4: a declined read goes uncounted', 'hook',
     '        osrdnCounts.readpixFlipDeclined++;\n', '', 'g54-readpix'),
    ('G5-4: the histogram switch is forgotten', 'hook',
     ' || ctx->Pixel.HistogramEnabled)', ')', 'g54-readpix'),
    ('G5-4: SkipImages is not refused', 'hook',
     ' || pack->SkipImages != 0)', ')', 'g54-readpix'),
    # ---- G5-2
    ('G5-2: a software triangle does not retire', 'hook',
     '    1,  /* DELEGATE  a triangle drawn in software */', '    0,  /* DELEGATE  a triangle drawn in software */', 'g52-retire'),
    ('G5-2: the retire only runs when this flush had a batch', 'hook',
     '        osrdnFlushBatch();\n    }\n    if (why >= 0 && why < OSRDN_FLUSH_REASONS && osrdnFlushTouches[why])\n        (void)osrdn_tri_retire_if_inflight();\n}',
     '        osrdnFlushBatch();\n        if (why >= 0 && why < OSRDN_FLUSH_REASONS && osrdnFlushTouches[why])\n            (void)osrdn_tri_retire_if_inflight();\n    }\n}', 'g52-retire'),
    ('G5-2: a reason loses its row', 'hook',
     '    0,  /* GLFLUSH   no pixel is touched */\n', '', 'g52-retire'),
    ('G5-2: the mirror reads before it retires', 'surf',
     '    (void)osrdn_tri_retire_if_inflight();\n    src = (unsigned long *)surfBase;', '    src = (unsigned long *)surfBase;', 'g52-retire'),
    # ---- G5-1b
    ('G5-1b: the flip is always on', 'hook',
     '    int flipY = osrdn_present_active();', '    int flipY = 1;', 'g51b-flip'),
    ('G5-1b: the flip is off by one row (H - 1 - y)', 'hook',
     'osrdnBits(flipY ? flipH - VB->Win.data[idx[i]][1]', 'osrdnBits(flipY ? flipH - 1.0F - VB->Win.data[idx[i]][1]', 'g51b-flip'),
    ('G5-1b: the surface is not told', 'hook',
     '    osrdn_surf_set_flipped(flipY);\n', '', 'g51b-flip'),
    ('G5-1b: H comes from the draw buffer, not the surface', 'hook',
     'flipH = flipY ? (GLfloat) OSRDNMesaSurfaceCounts()->height : 0.0F;', 'flipH = flipY ? (GLfloat) st->height : 0.0F;', 'g51b-flip'),
    # ---- G4-3 K2
    ('the alpha code never reaches the Tri unit', 'hook', '        osrdn_tri_alpha_set(ac);', '        osrdn_tri_alpha_set(0UL);',
     'g43-k2-alpha'),
    ('an alpha test with no code is sent', 'hook',
     '        if (ctx->Color.AlphaEnabled && ac == 0UL) {\n            osrdnCounts.codeGap++;\n            return;\n        }\n', '',
     'g43-k2-alpha'),
    # ---- G4-1b
    ('a textured vertex goes out with w = 1 (affine texturing)', 'hook',
     '                unsigned long ww = tex ? osrdnBits(VB->Win.data[idx[i]][3]) : osrdnBits(1.0F);',
     '                unsigned long ww = osrdnBits(1.0F);', 'g4-1b-residency'),
    ('the texture bit is read off the stale RasterMask', 'hook',
     '    s.rasterMask = ((unsigned long)ctx->RasterMask & ~(unsigned long)TEXTURE_BIT) |\n'
     '                   (ctx->Texture.ReallyEnabled ? (unsigned long)TEXTURE_BIT : 0UL);',
     '    s.rasterMask = (unsigned long)ctx->RasterMask;', 'g4-1b-residency'),
    ('the epoch stops moving on a retake', 'hook', '            osrdnTexEpoch++;\n', '',
     'g4-1b-residency'),
    ('a texture is sent whether or not it is resident', 'hook',
     '        if (!osrdnTexResident(to, &org, &tw, &th, levels))\n            return;',
     '        (void) osrdnTexResident(to, &org, &tw, &th, levels);', 'g4-1b-residency'),
    ('the TexImage hook stops chaining', 'hook',
     '    if (osrdnPrevTexImage != 0)\n        (*osrdnPrevTexImage)(ctx, target, tObj, level, internalFormat, image);\n', '',
     'g4-1b-residency'),
    ('the record is freed before its block is given back', 'hook',
     '    (void) osrdn_texarena_free(r->origin, r->epoch);\n    FREE(r);',
     '    FREE(r);\n    (void) osrdn_texarena_free(r->origin, r->epoch);', 'g4-1b-residency'),
    ('the reserve shrinks back to the 8 x 8 texels', 'hook',
     '    osrdn_surf_reserve(OSRDN_TEX_BYTE_OFF + OSRDN_TEX_ARENA_BYTES);',
     '    osrdn_surf_reserve(OSRDN_TEX_BYTE_OFF + 256UL);', 'g4-1b-residency'),
    ('an old-epoch record is believed', 'hook',
     'if (r != 0 && (r->epoch != osrdnTexEpoch || r->w', 'if (r != 0 && (r->w', 'g4-1b-residency'),
    ('a sub-image leaves the card current', 'hook',
     '    if (tObj != 0 && level >= 0 && tObj->Image[0] != 0 && tObj->Image[0]->DriverData != 0)\n        ((osrdnTexRes *) tObj->Image[0]->DriverData)->valid = 0;',
     '    if (tObj != 0 && level >= 0 && tObj->Image[0] != 0 && tObj->Image[0]->DriverData != 0)\n        ;', 'g4-1b-residency'),
    # M3g
    ('glFinish copies nothing back', 'hook',
     '    osrdn_surf_mirror();\n    osrdnCounts.finishMirrors++;',
     '    osrdnCounts.finishMirrors++;', 'm3g-finish-sync'),
    ('glFinish copies before the batch goes out', 'hook',
     '    /* whatever is still in a batch is part of the picture */\n    osrdnFlushOutside();\n',
     '    /* whatever is still in a batch is part of the picture */\n    osrdn_surf_mirror();\n    osrdnFlushOutside();\n', 'm3g-finish-sync'),
    ('G4-1a: the depth code is not carried (LESS with write, whatever the state)', 'hook',
     'depth = ctx->Depth.Test ? osrdn_class_depth_code((unsigned long) ctx->Depth.Func, (unsigned long) ctx->Depth.Mask) : 0;',
     'depth = ctx->Depth.Test ? 17 : 0;', 'm1f-blend-is-carried'),
    ('G4-1a: the env code is not carried (REPLACE, whatever the state)', 'hook',
     'tex = ctx->Texture.ReallyEnabled ? osrdn_class_env_code((unsigned long) ctx->Texture.Unit[0].EnvMode) : 0;',
     'tex = ctx->Texture.ReallyEnabled ? 1 : 0;', 'm1f-blend-is-carried'),
    ('G4-1a: a feature on with no code is sent anyway', 'hook',
     '        osrdnCounts.codeGap++;\n        return;', '        osrdnCounts.codeGap++;', 'm1f-blend-is-carried'),
    ('G3b: the colour bit is taken from Mesa even when the card refused', 'hook',
     '            if (flags & OSRDN_CLEAR_COLOUR)\n                osrdnCounts.colourClearBad++;   /* the bit stays in `left`: Mesa clears the array as before */',
     '            if (flags & OSRDN_CLEAR_COLOUR) {\n                osrdnCounts.colourClearBad++;\n                left &= ~DD_FRONT_LEFT_BIT;\n            }', 'g3b-clear-hook'),
    ('G3d: the clear colour goes out as the vertex word', 'hook',
     '            colour = osrdnWantWord(cc, rs, gs, bs, as);', '            colour = osrdnColourWord(cc, rs, gs, bs, as);', 'g3b-clear-hook'),
    ('G3b: the depth bit is taken from Mesa', 'hook',
     '                left &= ~DD_FRONT_LEFT_BIT;     /* the card holds the colour now: Mesa\'s pass is not needed */',
     '                left &= ~DD_FRONT_LEFT_BIT;     /* the card holds the colour now: Mesa\'s pass is not needed */\n                left &= ~DD_DEPTH_BIT;', 'g3b-clear-hook'),
    ('G3: present mode no longer stands the readback down', 'hook',
     '    if (osrdn_present_active()) {\n        osrdnCounts.finishStoodDown++;\n        return;\n    }\n',
     '', 'm3g-finish-sync'),
    ('G3: the stand-down still copies', 'hook',
     '        osrdnCounts.finishStoodDown++;\n        return;\n',
     '        osrdnCounts.finishStoodDown++;\n        osrdn_surf_mirror();\n        return;\n', 'm3g-finish-sync'),
    ('glFinish copies for a context that is not bound', 'hook',
     '    if (!osrdn_surf_bound_to((const void *) ctx->DriverCtx) || osrdn_surf_app_buffer() == 0)\n        return;',
     '    if (osrdn_surf_app_buffer() == 0)\n        return;', 'm3g-finish-sync'),
    ('the Y_UP-false decline is gone', 'hook',
     '    if (!yUp && cls == OSRDN_CLASS_WOULD_TAKE) {', '    if (0 && cls == OSRDN_CLASS_WOULD_TAKE) {', 'm3g-finish-sync'),
    ('the surface takes a longer application row again', 'surf',
     'appRowPixels != width', 'appRowPixels < width', 'm3g-finish-sync'),
    # M3b
    ('the self-culling is gone', 'hook',
     '        if (cc * ctx->backface_sign > 0) {\n            osrdnCounts.culled++;\n            return;\n        }\n',
     '', 'm3b-we-cull'),
    ('the self-culling tests the wrong sign', 'hook',
     'if (cc * ctx->backface_sign > 0) {', 'if (cc * ctx->backface_sign < 0) {', 'm3b-we-cull'),
    ('the group path no longer asks whose triangle function it is', 'hook',
     'if (!st.ok || slot < 0 || ctx->TriangleFunc != osrdnHookTriangle) {',
     'if (!st.ok || slot < 0) {', 'm3b-group-only-ours'),
    # M1t moved this expression into a local `wz`, so the anchor moved with it.
    # It is still the ONLY copy -- that is why the mutation reaches it.
    ('the vertex z goes out in Mesa\'s units', 'hook',
     'VB->Win.data[idx[i]][2] /\n                                             ctx->Visual->DepthMaxF',
     'VB->Win.data[idx[i]][2]', 'm1i-z-is-scaled'),
    # M1t: the inline path must go through the header's macro, not spell the
    # slots out again -- that is how the five-word writes landed in the
    # seven-word block the first time.
    ('the inline path writes numbered slots by hand', 'hook',
     '                    OSRDN_TRI_VERTEX_PUT(q, tex, wx, wy, wz, ww, col, ws, wt);',
     '                    q[0] = wx; q[1] = wy; q[2] = wz; q[3] = ww; q[4] = col;',
     'm1g-hook-does-not-pack'),
    ('the hook lays out a vertex itself again', 'hook',
     '            osrdn_tri_vertex(vtx, i, tex,',
     '            vtx[i * 5 + 0] = 0UL;\n            osrdn_tri_vertex(vtx, i, tex,',
     'm1g-hook-does-not-pack'),
    ('the texture enum is flattened to a boolean', 'hook',
     '    s.texture = (unsigned long)ctx->Texture.ReallyEnabled;',
     '    s.texture = ctx->Texture.ReallyEnabled ? 1 : 0;',
     'm1g-no-boolean-for-a-constant'),
    ('a stub calls memcpy', 'stubs', '    osrdn_hook_count(OSRDN_HOOK_CLEAR_PIXEL);',
     '    memcpy(ctx, &word, 4);\n    osrdn_hook_count(OSRDN_HOOK_CLEAR_PIXEL);',
     'm1b-no-drawing'),
    ('UpdateState assigns to ctx->Driver', 'hook',
     '    cls = osrdn_class_of(&s, osrdnHookAccel(), &why);',
     '    ctx->Driver.TriangleFunc = 0;\n    cls = osrdn_class_of(&s, osrdnHookAccel(), &why);',
     'm1b-no-drawing'),
    ('a stub accepts instead of declining', 'stubs',
     '    osrdn_hook_count(OSRDN_HOOK_DEPTH_BUFFER);\n    return 0;',
     '    osrdn_hook_count(OSRDN_HOOK_DEPTH_BUFFER);\n    return (void *)0x1000;',
     'm1b-stubs-decline'),
    ('a stub writes through a pointer argument', 'stubs',
     '    (void)dst; (void)width; (void)height; (void)bytesPerValue;',
     '    *(int *)dst = 1;\n    (void)width; (void)height; (void)bytesPerValue;',
     'm1b-stubs-decline'),
    ('a stub stops counting', 'stubs',
     '    osrdn_hook_count(OSRDN_HOOK_COPY_DEPTH);\n', '', 'm1b-stubs-decline'),
    ('two hooks share a counter', 'stubs', 'OSRDN_HOOK_COPY_DEPTH', 'OSRDN_HOOK_DEPTH_BUFFER',
     'm1b-one-counter-each'),
    ('UpdateState writes somewhere else', 'hook',
     '    osrdnCounts.rowLength = (unsigned long)rowLength;',
     '    osrdnCounts.verdict = 0UL;\n    osrdnCounts.rowLength = (unsigned long)rowLength;',
     'm1b-updatestate-writes'),
    ('the classifier reaches for a Mesa header', 'cls', '#include "OSRDNMesaClass.h"',
     '#include "types.h"\n#include "OSRDNMesaClass.h"', 'm1b-classifier-pure'),
    # ---- M1c
    ('a second mapping appears', 'surf', '    surfCounts.maps++;',
     '    (void)mmap(0, 0, 0, 0, 0, 0);\n    surfCounts.maps++;', 'm1c-one-mapping'),
    ('the mapping offset stops coming from CAPS', 'surf', '(long)caps->winStart',
     '(long)0x29e000UL', 'm1c-one-mapping'),
    ('a card address is written in', 'surf', '#define PAGE            8192UL',
     '#define PAGE            8192UL\n#define WIN 0x0029e000UL', 'm1c-no-constant-address'),
    ('an all-ones mask is NOT an address (the carve-out still passes)', 'surf',
     '0xffffffffUL - (PAGE - 1UL)', '0xffffffffUL - (PAGE - 2UL)', None),
    ('a refusal throws the ownership away too', 'surf',
     '        if (surfOwner == ctx)\n            surfBound = 0;',
     '        if (surfOwner == ctx) {\n            surfBound = 0;\n            surfOwner = 0;\n        }',
     'm1c-bound-is-not-owned'),
    ('a refusal keeps the binding', 'surf',
     '        if (surfOwner == ctx)\n            surfBound = 0;', '        ;',
     'm1c-bound-is-not-owned'),
    ('the mirror stops checking whether there is anything to copy', 'surf',
     '    if (surfBase == 0 || surfApp == 0) {', '    if (0) {', 'm1c-mirror-idle-is-ok'),
    ('the mirror goes back to consulting the binding', 'surf',
     '    if (surfBase == 0 || surfApp == 0) {',
     '    if (!surfBound || surfBase == 0 || surfApp == 0) {', 'm1c-mirror-idle-is-ok'),
    # ---- M1d.  The first two prove the REFINED A1 still bites.
    ('something else writes through ctx->', 'hook',
     '    osrdnSaved[slot].sw = ctx->Driver.TriangleFunc;',
     '    ctx->Driver.QuadFunc = 0;\n    osrdnSaved[slot].sw = ctx->Driver.TriangleFunc;',
     'm1b-no-drawing'),
    ('the install writes our function from somewhere else', 'hook',
     '    osrdnCounts.installs++;',
     '    ctx->Driver.TriangleFunc = osrdnHookTriangle;\n    osrdnCounts.installs++;',
     'm1b-no-drawing'),
    ('a refused triangle is dropped instead of drawn', 'hook',
     '        (*sw)(ctx, v0, v1, v2, pv);', '        ;',
     'm1d-never-lose-a-triangle'),
    ('the triangle function stops checking the surface is ours', 'hook',
     '    if (!osrdn_surf_bound_to((const void *) ctx))', '    if (0)',
     'm1d-never-lose-a-triangle'),
    ('ours goes in before Mesa has chosen, so there is no fallback', 'hook',
     '    ctx->Driver.TriangleFunc = 0;\n    gl_set_triangle_function(ctx);',
     '    ctx->Driver.TriangleFunc = osrdnHookTriangle;\n    gl_set_triangle_function(ctx);',
     'm1d-save-before-replace'),
    ('the classifier stops asking about the shade model', 'cls',
     's->shadeModel != GL_FLAT_', 's->shadeModel == s->shadeModel',
     'm1d-classifier-inputs'),
    ('the hook reads IndirectTriangles instead of TriangleCaps', 'hook',
     's.triangleCaps = (unsigned long)ctx->TriangleCaps;',
     's.triangleCaps = (unsigned long)ctx->IndirectTriangles;',
     'm1d-classifier-inputs'),
    ('a second batch mapping appears', 'tri', '    triCounts.maps++;',
     '    (void)mmap(0, 0, 0, 0, 0, 0);\n    triCounts.maps++;', 'm1d-tri-pure'),
    ('a card address is written into the tri unit', 'tri',
     '#define NODE_RDWR       2', '#define NODE_RDWR       2\n#define WIN 0x0029e000UL',
     'm1d-tri-pure'),
    # ---- M1e
    ('the smooth path takes the provoking vertex too', 'hook',
     'VB->ColorPtr->data[smooth ? idx[i] : pv]', 'VB->ColorPtr->data[pv]',
     'm1e-per-vertex-colour'),
    ('the shade model is never asked', 'hook',
     'smooth = (ctx->Light.ShadeModel == GL_SMOOTH) ? 1 : 0;', 'smooth = 0;',
     'm1e-per-vertex-colour'),
    # M1k: there are TWO submission paths, so each gets its own mutation -- a
    # single anchor would match both and mutate neither cleanly, and a state
    # that reached the card right down one path and wrong down the other is
    # exactly the bug batching makes possible.
    ('the SINGLE submission is told flat whatever the state', 'hook',
     'vtx, smooth, blend, tex, depth, &why))',
     'vtx, 0, blend, tex, depth, &why))', 'm1e-per-vertex-colour'),
    ('the BATCHED submission is told flat whatever the state', 'hook',
     'vtx, smooth, blend, tex, depth, &why);',
     'vtx, 0, blend, tex, depth, &why);', 'm1e-per-vertex-colour'),
    ('the SINGLE submission is told the blend is off', 'hook',
     'vtx, smooth, blend, tex, depth, &why))',
     'vtx, smooth, 0, tex, depth, &why))', 'm1f-blend-is-carried'),
    ('the BATCHED submission is told the blend is off', 'hook',
     'vtx, smooth, blend, tex, depth, &why);',
     'vtx, smooth, 0, tex, depth, &why);', 'm1f-blend-is-carried'),
    # the anchor carries its neighbour: M1g gave the upload function the same
    # single line, and a two-place anchor is not a mutation, it is a coin toss
    # M1v moved osrdn_surf_shifts into osrdnTriStateOf, so the anchor moved with
    # it.  The mutation still says the same thing: a second place that builds a
    # colour word.
    # M1v: a SECOND write to ctx->Driver from the group installer must still
    # trip -- the exemption is one named line, once, not the function.
    ('the group installer writes a second Driver member', 'hook',
     '    ctx->Driver.RenderVBRawTab = osrdnRawTab[slot];',
     '    ctx->Driver.RenderVBRawTab = osrdnRawTab[slot];\n'
     '    ctx->Driver.RenderVBCulledTab = osrdnRawTab[slot];',
     'm1b-no-drawing'),
    # and a write from somewhere that is not an installer at all
    ('a Driver member is written outside any installer', 'hook',
     '    osrdnCounts.groups++;',
     '    ctx->Driver.RenderVBRawTab = 0;\n    osrdnCounts.groups++;',
     'm1b-no-drawing'),
    ('the byte swap is copied into a second place', 'hook',
     '    else {\n        for (i = 0; i < 3; i++) {',
     '    else {\n        col = (want & 0xff00ff00UL);\n        for (i = 0; i < 3; i++) {',
     'm1e-per-vertex-colour'),
    ('the shade value is typed into the tri unit', 'tri',
     '#define NODE_RDWR       2',
     '#define NODE_RDWR       2\n#define SHADE 0x48005adeUL',
     'm1e-shade-value-is-generated'),
    ('the failed-ioctl block is believed', 'tri',
     '    if (rc != 0) {\n        triCounts.lastWhy = ~0UL;',
     '    triCounts.lastWhy = sb.why;\n    if (rc != 0) {\n        triCounts.lastWhy = ~0UL;',
     'm1d-failed-ioctl-is-not-an-answer'),
    # ---- G4-2 B1
    ('F4: the delegated triangle no longer flushes first', 'hook',
     '    osrdnFlushFor(OSRDN_FLUSH_DELEGATE);    /* F4: the card\'s triangles go under this one */\n', '',
     'g42-flush-points'),
    ('F4: the flush comes after the software triangle', 'hook',
     '    osrdnFlushFor(OSRDN_FLUSH_DELEGATE);    /* F4: the card\'s triangles go under this one */\n'
     '    if (sw != 0)\n        (*sw)(ctx, v0, v1, v2, pv);\n',
     '    if (sw != 0)\n        (*sw)(ctx, v0, v1, v2, pv);\n    osrdnFlushFor(OSRDN_FLUSH_DELEGATE);\n',
     'g42-flush-points'),
    ('F6: the clear no longer flushes', 'hook',
     '    osrdnFlushFor(OSRDN_FLUSH_CLEAR);       /* F6: the clear must land after what was drawn before it */\n', '',
     'g42-flush-points'),
    ('F8: the texel upload no longer flushes', 'hook',
     '        osrdnFlushFor(OSRDN_FLUSH_TEXUPLOAD);   /* F8: an open batch may read these texels */\n', '',
     'g42-flush-points'),
    ('F9: the surface is taken with a batch still aimed at the old one', 'hook',
     '    osrdnFlushFor(OSRDN_FLUSH_SURFACE);     /* G4-2 B1 F9: a batch aimed at the old surface goes first */\n', '',
     'g42-flush-points'),
    ('a hook closes a batch without saying why', 'hook',
     '    osrdnCounts.glFlushes++;\n    osrdnFlushFor(OSRDN_FLUSH_GLFLUSH);',
     '    osrdnCounts.glFlushes++;\n    osrdnFlushBatch();',
     'g42-flush-points'),
    ('the replay reads dead indices', 'hook',
     '        if (i < stale) {', '        if (0) {', 'g42-flush-points'),
    ('RenderFinish flushes instead of asking', 'hook',
     '    osrdnBracketEnd();\n    osrdnInRender = 0;', '    osrdnFlushBatch();\n    osrdnInRender = 0;',
     'g42-flush-points'),
    ('an accepted batch is left open with live-looking indices', 'hook',
     '        osrdnCounts.prevalidated++;\n        osrdnPend.stale = osrdnPend.n;\n',
     '        osrdnCounts.prevalidated++;\n', 'g42-flush-points'),
    ('the refused tail is redrawn from the dead prefix too', 'hook',
     '    for (i = keep; i < n; i++) {', '    for (i = 0UL; i < n; i++) {', 'g42-flush-points'),
    ('the verified prefix is thrown away instead of sent', 'hook',
     '    (void) osrdn_tri_batch_truncate(keep);\n', '    (void) osrdn_tri_batch_truncate(0UL);\n    keep = 0UL;\n',
     'g42-flush-points'),
    ('RenderStart flushes with the knob on', 'hook',
     '    if (!osrdn_tri_span_enabled()) {\n        /* M1k: nothing should be waiting;',
     '    if (1) {\n        /* M1k: nothing should be waiting;', 'g42-flush-points'),
    ('F10: a multipass state is batched', 'hook',
     ' || osrdnMultipass) {', ') {', 'g42-flush-points'),
    ('F3: the wrappers go in only when the state is taken', 'hook',
     '        osrdnFlushFor(OSRDN_FLUSH_LEAVE);\n        osrdnInstallPrims(ctx, slot);\n',
     '        osrdnFlushFor(OSRDN_FLUSH_LEAVE);\n', 'g42-flush-points'),
    ('F3: the point wrapper flushes after the points are drawn', 'hook',
     '    osrdnFlushFor(OSRDN_FLUSH_POINTS);\n    if (saved != 0)\n        (*saved)(ctx, first, last);\n',
     '    if (saved != 0)\n        (*saved)(ctx, first, last);\n    osrdnFlushFor(OSRDN_FLUSH_POINTS);\n',
     'g42-flush-points'),
    ('F3: the point wrapper saves our own pointer', 'hook',
     '    if (ctx->Driver.PointsFunc != osrdnHookPoints) {\n        osrdnSaved[slot].points = ctx->Driver.PointsFunc;\n        ctx->Driver.PointsFunc = osrdnHookPoints;\n    }',
     '    osrdnSaved[slot].points = ctx->Driver.PointsFunc;\n    ctx->Driver.PointsFunc = osrdnHookPoints;',
     'g42-flush-points'),
    ('UpdateState flushes every state change (no segment can ever form)', 'hook',
     '       of GHOST_SEG\'s 150 changes flushed here and no segment was ever made. */\n    if (!osrdn_tri_span_enabled())\n        osrdnFlushOutside();\n',
     '       of GHOST_SEG\'s 150 changes flushed here and no segment was ever made. */\n    osrdnFlushOutside();\n', 'g42-flush-points'),
    ('G4-5: a lower level is changed and the card keeps the old one', 'hook',
     '    else if (tObj != 0 && level > 0 && tObj->Image[0] != 0 && tObj->Image[0]->DriverData != 0)\n        ((osrdnTexRes *) tObj->Image[0]->DriverData)->valid = 0;\n', '',
     'g45-mip'),
    ('G4-5: TexSubImage invalidates only level 0 again', 'hook',
     '    if (tObj != 0 && level >= 0 && tObj->Image[0] != 0', '    if (tObj != 0 && level == 0 && tObj->Image[0] != 0',
     'g45-mip'),
    ('G4-5: a biased lambda is admitted', 'hook',
     ' &&\n                      ctx->Texture.Unit[0].LodBias == 0.0F && to->M <= 11.0F)', ' && to->M <= 11.0F)',
     'g45-mip'),
    ('G4-10: the prologue bypasses triMinSent', 'tri',
     '            if (tex && (triMinField(triMinSent(triTex.minCode)) == ~0UL || triTex.levels < 1 ||',
     '            if (tex && (triMinField(triTex.minCode) == ~0UL || triTex.levels < 1 ||', 'g410-substitute'),
    ('G4-10: the "all" knob is substituted too (no reproducer)', 'tri',
     '    if (osrdn_tri_mip_mode() == OSRDN_TRI_MIP_ALL)\n        return code;                    /* the blend values themselves: the freeze reproducer */\n',
     '', 'g410-substitute'),
    ('G4-10: LINEAR_MIPMAP_LINEAR is sent as itself', 'tri',
     '    if (code == OSRDN_TRI_MIN_LINEAR_MIPMAP_LINEAR)\n        return OSRDN_TRI_MIN_LINEAR_MIPMAP_NEAREST;\n', '', 'g410-substitute'),
    ('G4-10: the mask drops a blending mode again', 'cls',
     ' | \\\n                             (1UL << OSRDN_TRI_MIN_LINEAR_MIPMAP_LINEAR))', ')', 'g410-substitute'),
    ('G4-6: the default knob stops asking the measured mask', 'cls',
     '        return (OSRDN_MIP_MEASURED & (1UL << code)) != 0UL ? 1 : 0;', '        return 1;',
     'g45-mip'),
    ('G4-6: write() is called outside the trace', 'tri',
     '    triTrace(n);                            /* G4-6: on the host before the card sees it */\n',
     '    triTrace(n);                            /* G4-6: on the host before the card sees it */\n    (void) write(1, "x", 1);\n',
     'm1b-no-drawing'),
    ('G4-6: the trace writes to a third fd', 'tri',
     '        (void) write(triTraceFd, line, (unsigned int)k);',
     '        (void) write(2, line, (unsigned int)k);', 'm1b-no-drawing'),
    ('a pixel hook writes a Driver member', 'hook',
     '    osrdnFlushFor(OSRDN_FLUSH_BITMAP);\n',
     '    osrdnFlushFor(OSRDN_FLUSH_BITMAP);\n    ctx->Driver.Bitmap = 0;\n', 'm1b-no-drawing'),
]


def main():
    hook, stubs, cls = open(HOOK).read(), open(STUBS).read(), open(CLS).read()
    surf = open(SURF).read()
    tri = open(TRI).read()
    fails = 0

    r = rules(hook, stubs, cls, surf, tri)
    for name in sorted(r):
        for x in r[name]:
            print('    FAIL %-24s %s' % (name, x))
            fails += 1
        if not r[name]:
            print('    ok   %-24s' % name)

    for label, which, old, new, want in MUTATIONS:
        src = {'hook': hook, 'stubs': stubs, 'cls': cls, 'surf': surf,
               'tri': tri}[which]
        if src.count(old) != 1:
            print('    FAIL mutation %-46s anchor found %d times' % (label, src.count(old)))
            fails += 1
            continue
        m = src.replace(old, new)
        got = rules(m if which == 'hook' else hook,
                    m if which == 'stubs' else stubs,
                    m if which == 'cls' else cls,
                    m if which == 'surf' else surf,
                    m if which == 'tri' else tri)
        caught = [k for k, v in got.items() if v]
        if want is None:
            okk = not caught
            print('    %-4s mutation %-46s %s' % ('ok' if okk else 'FAIL', label,
                                                  'still clean' if okk else caught))
            fails += 0 if okk else 1
            continue
        if want in caught:
            print('    ok   mutation %-46s %s' % (label, caught))
        else:
            print('    FAIL mutation %-46s caught by %s, want %s' % (label, caught, want))
            fails += 1

    print('check_hook: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
