/*
 * OSRDNMesaTexArena.h - where textures live in the window (G4-1b, docs/G4_GLQUAKE_PLAN.md 5 T1).
 *
 * The Matrox library's OpenStepMGAMesaTexArena, in shape: a fixed number of sorted blocks,
 * first fit, and a GENERATION (epoch) that every residency record carries -- when the surface
 * is taken again the epoch moves and every old record is invalid without a scan.  No merging
 * on free is needed: a freed block is the gap between neighbours the next first fit sees.
 *
 * Plain C89, no libc, no Mesa: the host compiles it against a fake world (tools/mesa/sim_arena.py).
 * Offsets are BYTE offsets inside the window (the arena's origin is the texels' start,
 * OSRDN_TEX_BYTE_OFF); the caller adds winStart when it writes TXOFFSET.  Every block is
 * OSRDN_TEXARENA_ALIGN bytes aligned -- the grain R6 measured for a texture offset.
 */
#ifndef OSRDN_MESA_TEX_ARENA_H
#define OSRDN_MESA_TEX_ARENA_H

/* G5-4 (docs/G5_4_READPIX_AND_CLEANUP_PLAN.md 2-2): 512 filled on G4-6's ladder (S13 stopped at exactly
   512).  GLQuake's own ceiling is MAX_GLTEXTURES 1,024 (gl_draw.c) + MAX_LIGHTMAPS 64 (gl_rsurf.c) = 1,088;
   2,048 blocks cost 16 KiB and a worst linear alloc/free ~12 us against a 1.4 ms upload (python) */
#define OSRDN_TEXARENA_BLOCKS   2048
#define OSRDN_TEXARENA_ALIGN    32UL    /* r200-measured-rules: a texture offset needs a 32 B grain */

void osrdn_texarena_set(unsigned long origin, unsigned long bytes, unsigned long epoch);
void osrdn_texarena_drop(void);
unsigned long osrdn_texarena_epoch(void);
/* 1 and *origin on success; 0 when the arena is not live, the epoch is old, the arena is full
   or the block table is */
int osrdn_texarena_alloc(unsigned long bytes, unsigned long epoch, unsigned long *origin);
/* 1 when the block was ours (and is now gone); 0 when it was not, or the epoch is old */
int osrdn_texarena_free(unsigned long origin, unsigned long epoch);
void osrdn_texarena_stat(unsigned long *count, unsigned long *used, unsigned long *bytes);

/*
 * G4-4 K5 (docs/G4_4_KERNEL_PLAN.md 4-2): where the levels of a mip chain lie inside ONE block, the
 * way the R200 reads them (r200_texstate.c 272, 282-285: a level's rows are (w x 4 + 31) & ~31
 * bytes, a level starts 32-byte aligned, the levels are contiguous from the base) -- the same
 * arithmetic as the kernel verifier's cpR7TextureBytes and the oracle's texture_bytes, which
 * tools/mesa/sim_arena.py holds this to.  Fills offs[0..levels) and *bytes (the block to take);
 * 0 when w, h or levels are outside what a chain can be (POT 1..2048, levels <= 16 and no more than
 * the base can halve into).
 */
#define OSRDN_TEXARENA_MAX_LEVELS 16
int osrdn_texarena_chain(unsigned long w, unsigned long h, unsigned long levels,
                         unsigned long *offs, unsigned long *bytes);

#endif /* OSRDN_MESA_TEX_ARENA_H */
