/*
 * OSRDNMesaClass.h - M1b: would we draw this state? (docs/M1B_PLAN.md 4)
 *
 * Deliberately a function of PLAIN INTEGERS and nothing else.  The decision is
 * the interesting part of UpdateState, and a decision buried behind Mesa's
 * headers can only be tested on the target; pulled out here it is a table on
 * the host (tools/mesa/sim_class.py).  OSRDNMesaHook.c is the thin part that
 * reads the fields out of GLcontext and calls this.
 *
 * In M1b the answer is only COUNTED.  Nothing is installed, nothing is drawn.
 */

#ifndef OSRDN_MESA_CLASS_H
#define OSRDN_MESA_CLASS_H

#define OSRDN_CLASS_WOULD_TAKE      0   /* a state this card could draw */
#define OSRDN_CLASS_WOULD_DECLINE   1   /* one it could not */
#define OSRDN_CLASS_NO_ACCEL        2   /* we never asked: the probe said software */
#define OSRDN_CLASSES               3

/*
 * Why a state was declined.  Counting only "declined" would hide which of the
 * reasons a scene actually exercises, and a gate that cannot see that cannot
 * tell a narrow test scene from a broad one.
 */
#define OSRDN_WHY_NONE              0
#define OSRDN_WHY_FORMAT            1   /* colour-index: not a four-channel surface */
#define OSRDN_WHY_SMOOTH            2   /* GL_POLYGON_SMOOTH */
#define OSRDN_WHY_STIPPLE           3   /* polygon stipple */
#define OSRDN_WHY_TEXTURE           4   /* texturing, which M1b does not do */
#define OSRDN_WHY_RASTER            5   /* a raster feature outside what we know */
#define OSRDN_WHY_DEPTH_WIDTH       6   /* depth on, but not the 16 bits Mesa uses */
#define OSRDN_WHY_SHADE_MODEL       7   /* Gouraud: M1d draws flat only */
#define OSRDN_WHY_TRI_SETUP         8   /* a setup state Mesa would do for us, or instead of us */
#define OSRDN_WHY_BLEND_MODE        9   /* blending, but not a pair this rung sends */
/*
 * Depth is ENABLED and we do not draw it.  Found by reading, before it drew a
 * wrong picture: RM_DEPTH was in RM_KNOWN and the 16-bit width was accepted, so
 * a program that called glEnable(GL_DEPTH_TEST) was TAKEN -- and the prologue
 * turns R200_Z_ENABLE and R200_Z_WRITE_ENABLE off (docs/M1D_PLAN.md 4d), so the
 * card drew it with no depth test at all while Mesa's own depth buffer sat
 * untouched.  Nothing had exercised it because no test had ever enabled depth.
 *
 * The bit stays in RM_KNOWN -- the mask is not what is wrong -- and this reason
 * says plainly which rung is missing.  M1i is the rung that removes it.
 */
#define OSRDN_WHY_DEPTH            10   /* depth on, and no rung draws it yet */
#define OSRDN_WHY_ALPHA_MODE       11   /* G4-3 K2: the alpha test is on with a compare or ref no code names */
#define OSRDN_WHY_REASONS          12

/*
 * The inputs, named as Mesa names them so the extractor cannot mis-pair them.
 * All of them are what GLcontext already holds; none is computed here.
 */
typedef struct {
    unsigned long rasterMask;   /* ctx->RasterMask */
    /*
     * NOT the OSMesa format: that lives in osmesa.c's own private struct and a
     * back end cannot see it.  What UpdateState can see is whether the frame
     * buffer is RGBA at all (ctx->Visual->RGBAflag, src/types.h 1338).  Which
     * four-channel PACKING it is arrives later, as the shifts handed to
     * OpenStepMesaAccelBuffer -- so that question belongs to the rung that
     * implements Buffer, not to this one.
     */
    int           rgba;         /* ctx->Visual->RGBAflag */
    int           smooth;       /* ctx->Polygon.SmoothFlag */
    int           stipple;      /* ctx->Polygon.StippleFlag */
    int           texture;      /* ctx->Texture.ReallyEnabled */
    int           depthBits;    /* ctx->Visual->DepthBits */
    int           rowLength;    /* what osmesa.c passes us */
    int           yUp;          /* likewise */
    /*
     * M1d added these two, and the reasons are not symmetrical.
     *
     * shadeModel: Mesa picks flat or smooth at src/triangle.c 1655-1678, which
     * is AFTER the early-out at 1532 that keeps our function.  So installing
     * ours skips that choice entirely: decline anything but GL_FLAT or we draw
     * a Gouraud triangle with a flat function.
     *
     * triangleCaps: with DD_TRI_CULL set, nothing culls before our function --
     * the software rasteriser was the culler (src/tritemp.h 151) and we
     * replaced it, and src/state.c 1130 has already taken the bit out of
     * IndirectTriangles so the VB stage will not do it either.  Read
     * TriangleCaps and NOT IndirectTriangles: 1130 clears it only in the
     * latter, so the latter cannot see the culling at all.
     */
    unsigned long shadeModel;   /* ctx->Light.ShadeModel */
    unsigned long triangleCaps; /* ctx->TriangleCaps -- NOT IndirectTriangles */
    /*
     * M1f.  Five fields, not two, and each earns its place:
     *
     *   blendEnabled          ctx->Color.BlendEnabled
     *   blendSrcRGB/DstRGB    the pair we may be able to send
     *   blendSrcA/DstA        Mesa 3.4.2 can set the ALPHA function separately
     *                         (GL_INGR_blend_func_separate, types.h 363) and
     *                         RB3D_BLENDCNTL has ONE function pair -- so a
     *                         state where they differ is not expressible, and
     *                         drawing it with the RGB pair would be silently
     *                         wrong.
     *   blendEquation         ADD is the only one this rung sends.
     */
    int           blendEnabled;
    unsigned long blendSrcRGB, blendDstRGB;
    unsigned long blendSrcA, blendDstA;
    unsigned long blendEquation;
    /*
     * M1g.  `texture` above is ctx->Texture.ReallyEnabled -- whether ANY unit
     * is on.  These say WHICH texture it is, and the classifier accepts exactly
     * the one shape this rung uploads and R6h measured the sampling of.
     */
    unsigned long texUnit0;         /* ctx->Texture.Unit[0].ReallyEnabled */
    unsigned long texWidth, texHeight, texBorder;
    unsigned long texFormat;        /* the image's Format */
    unsigned long texMinFilter, texMagFilter;
    unsigned long texWrapS, texWrapT;
    /* G4-4 K5 / G4-5: a mip MIN filter is ours only when the knob allows its mode
       (osrdn_tri_mip_mode: OFF 0, MEASURED 1, ALL 2), the object is complete (Mesa's t->Complete:
       every level from the base to P is there), and texLodOk: BaseLevel 0, MinLod <= 0,
       MaxLod >= M, the unit's LodBias 0 and at most 12 levels -- a lambda GL does not clamp or
       bias, so the chain the card holds is the chain GL samples (docs/G4_5_MIP_PLAN.md 2-2) */
    unsigned long texMip, texComplete, texLodOk;
    /* HOW the texel reaches the fragment, which is a separate question from
       WHICH texel.  The prologue's stage 0 is out = R0 (tex_oracle
       blend_texture), a REPLACE; Mesa's default is GL_MODULATE
       (Mesa-3.4.2/src/context.c 602, used at texture.c 2373).  Accepting the
       default would draw the texel where software multiplied it by the vertex
       colour -- and with a white vertex colour the two agree, so the first
       scene to use one would look right. */
    unsigned long texEnvMode;
    /* M1i: the depth comparison.  The prologue carries GL_LESS and nothing
       else, so every other function has to be refused -- the same shape as the
       blend pair.  GL_TRUE/GL_FALSE for the write mask: the card's
       Z_WRITE_ENABLE is one bit and we always set it with the test. */
    unsigned long depthFunc;
    unsigned long depthMask;
    /* G4-3 K2: ctx->Color.AlphaEnabled / AlphaFunc / AlphaRef (the ref is already Mesa's byte) */
    int           alphaEnabled;
    unsigned long alphaFunc;
    unsigned long alphaRef;
} osrdn_class_state;

/*
 * The classification, and (when it declines) the reason.  `why` may be null.
 * `accel` is 0 when the probe did not say HARDWARE, and then the answer is
 * NO_ACCEL without looking at anything else -- asking about a state we could
 * not draw anyway is how a counter starts lying.
 */
/* G4-1a: the codes a drawable state carries (0 = not one we draw); see OSRDNMesaClass.c */
int osrdn_class_tex_dim_ok(unsigned long d);          /* G4-1b: a power of two in [8, 512] */
/* G4-3 K2: 1 | op << 1 | ref << 4 for the eight GL compares (op = the R200 field, r200AlphaFunc),
   0 for a function that is none of them */
int osrdn_class_alpha_code(unsigned long func, unsigned long ref);
int osrdn_class_depth_code(unsigned long func, unsigned long mask);
int osrdn_class_blend_code(unsigned long src, unsigned long dst);
int osrdn_class_env_code(unsigned long env);
/* G4-4 K5: the MIN filter as the Tri unit's code (OSRDN_TRI_MIN_*), or -1 for one it does not have */
int osrdn_class_min_code(unsigned long minFilter);
int osrdn_class_of(const osrdn_class_state *s, int accel, int *why);

/* the name of a class or a reason, for a log line; never null */
const char *osrdn_class_name(int cls);
const char *osrdn_class_why_name(int why);
/*
 * G4-6 diagnosis: which clause of the texture test declined this state, in the order
 * osrdn_class_of tests them -- 0 none (or no texture), 1 not TEXTURE0_2D alone, 2 width,
 * 3 height, 4 border, 5 format, 6 MIN filter, 7 MAG filter, 8 wrap S, 9 wrap T, 10 env mode;
 * *val is the offending field's value.  Pure, like the classifier; it decides nothing.
 */
#define OSRDN_TEXWHY_CLAUSES 11
int osrdn_class_tex_why(const osrdn_class_state *s, unsigned long *val);

#endif /* OSRDN_MESA_CLASS_H */
