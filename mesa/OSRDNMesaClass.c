/*
 * OSRDNMesaClass.c - see OSRDNMesaClass.h.  Plain C89, no headers at all.
 *
 * The numbers below belong to Mesa, so they are named where they came from and
 * tools/mesa/check_hook.py reads those files and fails if any of them moves.
 * Writing them here rather than including Mesa's headers is what lets this unit
 * compile on the host, where 32-bit system headers do not exist.
 */

#include "OSRDNMesaClass.h"
/* M1g: the texture SIZE the prologue's TXFORMAT log2 fields encode.  Included
   rather than retyped so there is one source of truth -- a generated header of
   plain #defines, which does not cost this unit its header-freedom. */
#include "OSRDNMesaTriTable.h"

/* src/types.h 1449-1462: the RasterMask bits.  Only DEPTH_BIT is a state we
   could draw in M1b; anything else means a feature we have not built. */
#define RM_DEPTH        0x004UL
#define RM_ALPHA        0x001UL         /* G4-3 K2: ALPHATEST_BIT (types.h 1449) */
#define RM_KNOWN        (RM_DEPTH | RM_BLEND | RM_TEXTURE | RM_ALPHA)

/* src/config.h 145 */
#define SOFTWARE_DEPTH_BITS 16

/* include/GL/gl.h 288-289 */
#define GL_FLAT_        0x1D00UL
#define GL_SMOOTH_      0x1D01UL

/* include/GL/gl.h 324-331, 822.  The ONE pair M1f sends; R6j measured it as
   its J4/J7/J9 and it is what Mesa's own default and osrdn-mesa-render.c use.
   Written as a table so the next rung adds rows rather than logic. */
#define GL_SRC_ALPHA_           0x0302UL
#define GL_ONE_MINUS_SRC_ALPHA_ 0x0303UL
#define GL_FUNC_ADD_            0x8006UL

/* src/types.h 1450 */
#define RM_BLEND        0x002UL

/*
 * src/types.h 1462, set at src/state.c 817 from the very same expression that
 * fills `texture` below.  M1g had to admit it: Mesa turns the bit on for ANY
 * texture, so refusing the bit refused the rung -- measured, run 790054955,
 * where the texture clause passed and RASTER declined instead.
 *
 * Admitting a bit is not admitting the feature.  WHICH texture we can draw is
 * decided by the clause above; this only stops the mask itself from being the
 * thing that refuses.
 */
#define RM_TEXTURE      0x1000UL

/* src/types.h 733, include/GL/gl.h 630-631, 457 */
#define TEXTURE0_2D_    0x2UL
#define GL_NEAREST_     0x2600UL
#define GL_REPEAT_      0x2901UL
#define GL_REPLACE_     0x1E01UL
#define GL_LESS_        0x0201UL
#define GL_LEQUAL_      0x0203UL
#define GL_GEQUAL_      0x0206UL
#define GL_ALWAYS_      0x0207UL
#define GL_ZERO_        0x0000UL
#define GL_ONE_         0x0001UL
#define GL_ONE_MINUS_SRC_COLOR_ 0x0301UL
#define GL_MODULATE_    0x2100UL
#define GL_RGB_         0x1907UL
#define GL_LINEAR_      0x2601UL
#define GL_NEAREST_MIPMAP_NEAREST_ 0x2700UL     /* G4-4 K5: GL/gl.h 619-622 */
#define GL_LINEAR_MIPMAP_NEAREST_  0x2701UL
#define GL_NEAREST_MIPMAP_LINEAR_  0x2702UL
#define GL_LINEAR_MIPMAP_LINEAR_   0x2703UL
#define GL_TRUE_        1UL
#define GL_RGBA_        0x1908UL

/* src/types.h 1501-1529: DD_TRI_LIGHT_TWOSIDE | DD_TRI_UNFILLED | DD_TRI_OFFSET
   | DD_TRI_CULL | DD_TRI_CULL_FRONT_BACK.  tools/mesa/sim_trifunc.py computes
   the same number out of types.h and fails if a bit is renumbered. */
#define DD_SW_SETUP_    0x00400660UL
/*
 * M3b: WHAT WE ACTUALLY DECLINE is DD_SW_SETUP_ WITHOUT DD_TRI_CULL (0x400).
 *
 * Culling is taken now because the hook culls for itself (OSRDNMesaHook.c,
 * osrdnTriangleWith): with the software rasteriser's bits set, Mesa takes
 * DD_TRI_CULL out of IndirectTriangles and leaves culling to the software
 * triangle function (state.c 1127-1130, tritemp.h 150) -- which is the
 * function we replace -- so without our own test NOBODY culls
 * (tools/mesa/sim_trifunc.py D12).
 *
 * Offset and two-sided lighting stay out: both set context state just before
 * the triangle call, and a failed batch is REPLAYED to the software function
 * later, when that state is gone (tools/mesa/gen_tri_prologue.py, which checks
 * the two bits are inside THIS mask).  Unfilled and front-and-back culling stay
 * out as well (docs/M3B_PLAN.md 8-1).
 */
#define DD_DECLINE_     0x00400260UL

/*
 * G4-1a (docs/G4_GLQUAKE_PLAN.md 5 D, B, M): the CODES a drawable state carries down to the
 * triangle unit, decided here where the GL enums live and nowhere else.  0 means "not one we
 * draw" -- the classifier refuses on 0, and the hook treats 0 with the feature enabled as a
 * state it must not send (a defence, not a path).
 *
 * depth: 1 | Z_TEST << 1 | write << 4.  The Z_TEST values are the card's own field (r200_reg.h
 * 107-115, generated into OSRDNMesaTriTable.h); the four GLQuake uses, plus ALWAYS.  GL_NEVER,
 * GREATER, EQUAL and NOTEQUAL are not offered: the reference encodes them, but nothing here
 * has drawn them and the Matrox precedent refused NEVER on evidence (M1_4E8).
 * blend: the pair as a small number; the words are the generated table's.
 * env:   REPLACE (measured) or MODULATE (R0 x DIFFUSE, r200_texstate.c 797-802).
 */
int
osrdn_class_tex_dim_ok(unsigned long d)
{
    return d >= (unsigned long)OSRDN_TEX_MIN_DIM && d <= (unsigned long)OSRDN_TEX_MAX_DIM &&
           (d & (d - 1UL)) == 0UL;
}

int
osrdn_class_alpha_code(unsigned long func, unsigned long ref)
{
    unsigned long op;

    switch (func) {                     /* include/GL/gl.h 243-250; the field values r200_reg.h 35-42 */
    case 0x0200UL: op = 0UL; break;     /* GL_NEVER    -> FAIL */
    case 0x0201UL: op = 1UL; break;     /* GL_LESS */
    case 0x0202UL: op = 3UL; break;     /* GL_EQUAL */
    case 0x0203UL: op = 2UL; break;     /* GL_LEQUAL */
    case 0x0204UL: op = 5UL; break;     /* GL_GREATER */
    case 0x0205UL: op = 6UL; break;     /* GL_NOTEQUAL -> NEQUAL */
    case 0x0206UL: op = 4UL; break;     /* GL_GEQUAL */
    case 0x0207UL: op = 7UL; break;     /* GL_ALWAYS   -> PASS */
    default: return 0;
    }
    if (ref > 0xffUL)
        return 0;
    return (int)(1UL | (op << 1) | (ref << 4));
}

int
osrdn_class_depth_code(unsigned long func, unsigned long mask)
{
    unsigned long zt;

    if (func == GL_LESS_)
        zt = OSRDN_TRI_ZTEST_LESS;
    else if (func == GL_LEQUAL_)
        zt = OSRDN_TRI_ZTEST_LEQUAL;
    else if (func == GL_GEQUAL_)
        zt = OSRDN_TRI_ZTEST_GEQUAL;
    else if (func == GL_ALWAYS_)
        zt = OSRDN_TRI_ZTEST_ALWAYS;
    else
        return 0;                       /* NEVER, GREATER, EQUAL, NOTEQUAL: not drawn */
    return (int)(1UL | (zt << 1) | ((mask != 0UL) ? 16UL : 0UL));
}

int
osrdn_class_blend_code(unsigned long src, unsigned long dst)
{
    if (src == GL_SRC_ALPHA_ && dst == GL_ONE_MINUS_SRC_ALPHA_)
        return OSRDN_TRI_BLEND_SRCA;
    if (src == GL_ZERO_ && dst == GL_ONE_MINUS_SRC_COLOR_)
        return OSRDN_TRI_BLEND_ZERO_OMSC;
    if (src == GL_ONE_ && dst == GL_ONE_)
        return OSRDN_TRI_BLEND_ONE_ONE;
    return 0;
}

int
osrdn_class_env_code(unsigned long env)
{
    if (env == GL_REPLACE_)
        return OSRDN_TRI_TEX_REPLACE;
    if (env == GL_MODULATE_)
        return OSRDN_TRI_TEX_MODULATE;
    return 0;
}

int
osrdn_class_min_code(unsigned long minFilter)
{
    if (minFilter == GL_NEAREST_)                return OSRDN_TRI_MIN_NEAREST;
    if (minFilter == GL_LINEAR_)                 return OSRDN_TRI_MIN_LINEAR;
    if (minFilter == GL_NEAREST_MIPMAP_NEAREST_) return OSRDN_TRI_MIN_NEAREST_MIPMAP_NEAREST;
    if (minFilter == GL_LINEAR_MIPMAP_NEAREST_)  return OSRDN_TRI_MIN_LINEAR_MIPMAP_NEAREST;
    if (minFilter == GL_NEAREST_MIPMAP_LINEAR_)  return OSRDN_TRI_MIN_NEAREST_MIPMAP_LINEAR;
    if (minFilter == GL_LINEAR_MIPMAP_LINEAR_)   return OSRDN_TRI_MIN_LINEAR_MIPMAP_LINEAR;
    return -1;
}

/*
 * G4-5 (docs/G4_5_MIP_PLAN.md 2-3): the mipmap MIN codes measured on this card, as a mask of
 * 1 << OSRDN_TRI_MIN_*.  NEAREST_MIPMAP_NEAREST: boot 9's GHOST_MIP, every level of an 8-level
 * chain fetched from its r200 offset (docs/G4_4_KERNEL_PLAN.md 10).  LINEAR_MIPMAP_NEAREST
 * (GLQuake's default): G4-5 scene C, the same eight levels (docs/G4_5_MIP_PLAN.md 8).  A mode is
 * added here after its probe passes, never before -- the Matrox M12 rule (M12_WARP_MIPMAP_PLAN.md
 * 8, condition 5).  The two *_MIPMAP_LINEAR modes: G4-5 scene D measured the card blending two
 * levels with f = 2^frac(lambda) - 1 -- the mantissa-linear log2 approximation, up to 0.086 off
 * GL's f = frac(lambda); deterministic and monotonic.  Opened as a DOCUMENTED APPROXIMATION
 * (G4-6), as Matrox opened its identical one at up to 1/8 (M12_WARP_MIPMAP_PLAN.md 10-1,
 * decision 2) and as the r200 DRI sends all four modes to the card (r200_tex.c 206-231).  G4-5
 * had held them back on M12-C's pre-measurement 1/16 bar and missed that final decision --
 * and LibreQuake's default.cfg asks for GL_NEAREST_MIPMAP_LINEAR, so every world surface was
 * drawn by Mesa (measured: 2841 of 2845 declines, docs/G4_6_GLQUAKE_PLAN.md).
 */
/* HELD BACK (2026-09-27): the first GLQuake run with the two blending modes on the card froze the
   machine.  UNDERSTOOD (2026-09-28, docs/G4_8_REPLAY_PLAN.md 15): the level-blending path itself
   (hw MIN 6 and 7) hangs this card within a few submissions, whatever else is done.  G4-10
   (docs/G4_10_MIP_SUBSTITUTE_PLAN.md): the two blending modes are ADMITTED again under the same
   chain and lambda conditions, and the Tri unit SENDS them as the level-selecting mode with the
   same texel filter (triMinSent) -- a documented approximation.  Only the "all" knob sends the
   blend values, and that is the freeze reproducer, not a mode. */
#define OSRDN_MIP_MEASURED  ((1UL << OSRDN_TRI_MIN_NEAREST_MIPMAP_NEAREST) | \
                             (1UL << OSRDN_TRI_MIN_LINEAR_MIPMAP_NEAREST) | \
                             (1UL << OSRDN_TRI_MIN_NEAREST_MIPMAP_LINEAR) | \
                             (1UL << OSRDN_TRI_MIN_LINEAR_MIPMAP_LINEAR))

/* G4-4 K5 / G4-5: a MIN filter this state may send -- the two non-mip ones always, a mip one
   when the knob allows its mode, the chain is complete and GL's lambda is not clamped or biased */
static int
classMinOk(const osrdn_class_state *s)
{
    int code = osrdn_class_min_code(s->texMinFilter);

    if (code == OSRDN_TRI_MIN_NEAREST || code == OSRDN_TRI_MIN_LINEAR)
        return 1;
    if (code < OSRDN_TRI_MIN_MIP_FIRST)
        return 0;
    if (s->texComplete == 0UL || s->texLodOk == 0UL)
        return 0;
    if (s->texMip == (unsigned long)OSRDN_TRI_MIP_ALL)
        return 1;
    if (s->texMip == (unsigned long)OSRDN_TRI_MIP_MEASURED)
        return (OSRDN_MIP_MEASURED & (1UL << code)) != 0UL ? 1 : 0;
    return 0;
}

int
osrdn_class_tex_why(const osrdn_class_state *s, unsigned long *val)
{
    int k = 0;
    unsigned long v = 0UL;

    if (!s->texture)
        k = 0;
    else if (s->texture != TEXTURE0_2D_ || s->texUnit0 != TEXTURE0_2D_) {
        k = 1; v = s->texture;
    } else if (!osrdn_class_tex_dim_ok(s->texWidth)) {
        k = 2; v = s->texWidth;
    } else if (!osrdn_class_tex_dim_ok(s->texHeight)) {
        k = 3; v = s->texHeight;
    } else if (s->texBorder != 0UL) {
        k = 4; v = s->texBorder;
    } else if (s->texFormat != GL_RGBA_ && s->texFormat != GL_RGB_) {
        k = 5; v = s->texFormat;
    } else if (!classMinOk(s)) {
        k = 6; v = s->texMinFilter;
    } else if (s->texMagFilter != GL_NEAREST_ && s->texMagFilter != GL_LINEAR_) {
        k = 7; v = s->texMagFilter;
    } else if (s->texWrapS != GL_REPEAT_) {
        k = 8; v = s->texWrapS;
    } else if (s->texWrapT != GL_REPEAT_) {
        k = 9; v = s->texWrapT;
    } else if (osrdn_class_env_code(s->texEnvMode) == 0) {
        k = 10; v = s->texEnvMode;
    }
    if (val != 0)
        *val = v;
    return k;
}

int
osrdn_class_of(const osrdn_class_state *s, int accel, int *why)
{
    int w = OSRDN_WHY_NONE;
    int cls;

    if (!accel) {
        /* Not "declined": we never asked.  A counter that folded this into
           WOULD_DECLINE would report a card that is not there as a card that
           refused, and the two need different answers. */
        if (why != 0)
            *why = OSRDN_WHY_NONE;
        return OSRDN_CLASS_NO_ACCEL;
    }

    /* Colour-index is a different surface, not a different state.  Which
       four-channel packing it is cannot be asked here -- see the header. */
    if (!s->rgba)
        w = OSRDN_WHY_FORMAT;
    else if (s->smooth)
        w = OSRDN_WHY_SMOOTH;
    else if (s->stipple)
        w = OSRDN_WHY_STIPPLE;
    /*
     * M1g opened this from "any texture is refused" to "the one texture this
     * rung uploads".  Every clause is a thing the prologue fixes and cannot
     * vary at run time: the size is in TXFORMAT's log2 fields, the filter and
     * the wrap are in TXFILTER, the format is ARGB8888.  Drawing a different
     * texture with that prologue would sample the right pixels out of the wrong
     * image -- a picture that looks plausible and is wrong.
     */
    else if (s->texture &&
             (s->texture != TEXTURE0_2D_ ||
              s->texUnit0 != TEXTURE0_2D_ ||
              /* G4-1b: any power of two from 8 to 512 (R6h measured 8; the log2 fields carry the
                 rest, and 512 is GLQuake's largest), RGB or RGBA (Mesa's 3 or 4 bytes), the two
                 non-mip filters, REPEAT (measured XC; CLAMP is measured as CLAMP_LAST only) */
              !osrdn_class_tex_dim_ok(s->texWidth) ||
              !osrdn_class_tex_dim_ok(s->texHeight) ||
              s->texBorder != 0UL ||
              (s->texFormat != GL_RGBA_ && s->texFormat != GL_RGB_) ||
              !classMinOk(s) ||                                   /* G4-4 K5 */
              (s->texMagFilter != GL_NEAREST_ && s->texMagFilter != GL_LINEAR_) ||
              s->texWrapS != GL_REPEAT_ ||
              s->texWrapT != GL_REPEAT_ ||
              osrdn_class_env_code(s->texEnvMode) == 0))    /* G4-1a: REPLACE or MODULATE */
        w = OSRDN_WHY_TEXTURE;
    /*
     * The bit and the field come from one expression in Mesa (state.c 817), so
     * they cannot disagree -- and if they ever do, this state was not built by
     * the Mesa we read.  Checking it costs nothing and keeps RM_TEXTURE from
     * becoming a bit that means "accepted" on its own.
     */
    else if (((s->rasterMask & RM_TEXTURE) != 0UL) != (s->texture != 0UL))
        w = OSRDN_WHY_TEXTURE;
    else if ((s->rasterMask & ~RM_KNOWN) != 0UL)
        w = OSRDN_WHY_RASTER;
    /* G4-3 K2: the alpha bit and the state come from one expression too (update_rasterflags), and
       the test is drawn only with a compare the code names -- all eight GL functions have one
       (r200AlphaFunc maps NEVER to FAIL and ALWAYS to PASS rather than turning the test off) */
    else if (((s->rasterMask & RM_ALPHA) != 0UL) != (s->alphaEnabled != 0))
        w = OSRDN_WHY_RASTER;
    else if ((s->rasterMask & RM_ALPHA) != 0UL && osrdn_class_alpha_code(s->alphaFunc, s->alphaRef) == 0)
        w = OSRDN_WHY_ALPHA_MODE;
    else if ((s->rasterMask & RM_DEPTH) != 0UL && s->depthBits != SOFTWARE_DEPTH_BITS)
        w = OSRDN_WHY_DEPTH_WIDTH;
    /*
     * M1i draws depth now, so the blanket refusal is gone -- but WHICH depth is
     * the question the reason keeps asking.  The prologue carries GL_LESS and
     * Z_WRITE_ENABLE together; a program that asked for another compare, or for
     * the test without the write, would be drawn with ours.
     */
    else if ((s->rasterMask & RM_DEPTH) != 0UL &&
             osrdn_class_depth_code(s->depthFunc, s->depthMask) == 0)   /* G4-1a: four compares, either mask */
        w = OSRDN_WHY_DEPTH;
    /*
     * M1e widened this from "flat only" to "flat or smooth", and did NOT delete
     * the reason.  Both are states we draw: the card's shade control has a
     * setting for each, and R6d and R6e measured the rule for each.  Anything
     * else is still refused -- a reason with no cases left is a reason waiting
     * to be needed again, and deleting it would leave the next one unnamed.
     */
    else if (s->shadeModel != GL_FLAT_ && s->shadeModel != GL_SMOOTH_)
        w = OSRDN_WHY_SHADE_MODEL;
    else if ((s->triangleCaps & DD_DECLINE_) != 0UL)
        w = OSRDN_WHY_TRI_SETUP;
    /*
     * M1f.  RM_KNOWN now admits the blend bit, so the blend STATE has to be
     * looked at -- admitting the bit without checking the mode would accept
     * every blend function and draw them all with one.
     */
    else if (s->blendEnabled &&
             (s->blendEquation != GL_FUNC_ADD_ ||
              osrdn_class_blend_code(s->blendSrcRGB, s->blendDstRGB) == 0 ||   /* G4-1a: three pairs */
              /* RB3D_BLENDCNTL has one function pair; a separate alpha
                 function cannot be expressed and must not be approximated */
              s->blendSrcA != s->blendSrcRGB ||
              s->blendDstA != s->blendDstRGB))
        w = OSRDN_WHY_BLEND_MODE;

    cls = (w == OSRDN_WHY_NONE) ? OSRDN_CLASS_WOULD_TAKE : OSRDN_CLASS_WOULD_DECLINE;
    if (why != 0)
        *why = w;
    return cls;
}

const char *
osrdn_class_name(int cls)
{
    static const char *names[OSRDN_CLASSES] = { "WOULD_TAKE", "WOULD_DECLINE", "NO_ACCEL" };

    if (cls < 0 || cls >= OSRDN_CLASSES)
        return "?";
    return names[cls];
}

const char *
osrdn_class_why_name(int why)
{
    static const char *names[OSRDN_WHY_REASONS] = {
        "-", "FORMAT", "SMOOTH", "STIPPLE", "TEXTURE", "RASTER", "DEPTH_WIDTH",
        "SHADE_MODEL", "TRI_SETUP", "BLEND_MODE", "DEPTH", "ALPHA_MODE"
    };

    if (why < 0 || why >= OSRDN_WHY_REASONS)
        return "?";
    return names[why];
}
