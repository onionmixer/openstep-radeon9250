/*
 * osrdn_modelog.h - see osrdn_modelog.m.  The class calls this after the mode
 * sequence has finished; nothing inside the sequence may log.
 */

#import "osrdn_mode.h"

void osrdn_mode_lines(const osrdn_mode_state *mode);

/* R3b-2: the extended read-back of the entry that just ran.  From
   -enterLinearMode only -- after a revert these fields are stale
   (docs/R3_MULTIMODE_PLAN.md 23-9 E3). */
void osrdn_verify_line(const osrdn_mode_state *mode);

/* R3b-2b: after a transfer table or a brightness call (24-5) */
void osrdn_xfer_line(const osrdn_mode_state *mode, const unsigned int *table, int count, int result);
void osrdn_bright_line(const osrdn_mode_state *mode, int level, int result);

/* the cycle's verdict: what the revert put back, against the snapshot.  Its
   own arrays, because a re-entry's modeVerify overwrites the entry's. */
void osrdn_revert_lines(const osrdn_mode_state *mode);

/* every bounded wait: evaluations and limit, entry and revert apart */
void osrdn_wait_lines(const osrdn_mode_state *mode);

/* R4 (docs/R4_ENGINE_PLAN.md 12-3): one engine operation's result, printed by
   the class after osrdn_mode_engine released the claim.  rc is what the
   wrapper returned (it may be the wrapper's own BUSY / NOT_LIVE). */
void osrdn_engine_line(const osrdn_engine_state *e, unsigned long nonce, int rc);

/* R5: one CP operation's evidence (docs/R5_PLAN.md 8) */
void osrdn_cp_lines(const osrdn_cp_state *c, unsigned long nonce, int rc);
/* M3c: only the first line of the above -- rc, why, the gate */
void osrdn_cp_head(const osrdn_cp_state *c, unsigned long nonce, int rc);
/* M3i: the CSQ fifo and the ring words a latch took (docs/M3I_PLAN.md 3) -- 40 lines,
   printed on their own so that the record and they never share one 4 KB message buffer */
void osrdn_cp_latch_words(const osrdn_cp_state *c, unsigned long nonce);
