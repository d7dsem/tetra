#ifndef DMO_CORE_H
#define DMO_CORE_H

#include <stddef.h>
#include <stdint.h>

#include "dmo_tuning.h"

/* All bit arrays: one bit per byte, value 0 or 1. */

/* Parameters of one coded block (spec section 5 / osmo tetra_blk_param) */
struct dmo_block_params {
	unsigned coded_len;
	unsigned type2_len;
	unsigned type1_len;
	unsigned interleave_a;
};

struct dmo_block_result {
	uint8_t type1[DMO_MAX_TYPE1_BITS];
	int crc_ok;
	int tail_zero;	/* all type-2 bits after the CRC are 0 */
};

extern const struct dmo_block_params dmo_sch_s_params;
extern const struct dmo_block_params dmo_sch_h_params;

/* Receive chain for one block; returns 0, or -1 on invalid params or decoder failure. */
int dmo_block_decode(const struct dmo_block_params *p, const uint8_t *coded,
		     struct dmo_block_result *res);

struct dmo_burst {
	const uint8_t *sch_s;	/* DMO_SCH_S_CODED_BITS bits */
	const uint8_t *sch_h;	/* DMO_SCH_H_CODED_BITS bits */
};

/* Slice the coded blocks out of a DMO_BURST_BITS-long burst. */
void dmo_burst_slice(const uint8_t *burst, struct dmo_burst *out);

/* Find burst starts whose sync training sequence differs in at most max_bit_errors bits.
 * The whole burst must fit in the stream. Returns 0 and a malloc'd array (caller frees;
 * may be NULL when *count is 0), or -1 on allocation failure. */
int dmo_sync_find(const uint8_t *stream, size_t len, unsigned max_bit_errors,
		  size_t **starts, size_t *count);

#endif
