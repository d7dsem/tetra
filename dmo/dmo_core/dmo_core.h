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
extern const struct dmo_block_params dmo_sch_f_params;

/* Receive chain for one block with the DSB scrambling (colour code 0); returns 0,
 * or -1 on invalid params or decoder failure. */
int dmo_block_decode(const struct dmo_block_params *p, const uint8_t *coded,
		     struct dmo_block_result *res);

/* Same with an explicit scrambler initial state (see dmo_scramb_init_dcc). */
int dmo_block_decode_scr(const struct dmo_block_params *p, uint32_t scramb_init, const uint8_t *coded,
			 struct dmo_block_result *res);

/* Scrambler initial state from the DM colour code: e(1..6) = low 6 bits of MNI, e(7..30) = source
 * address (EN 300 396-3, 8.2.4); init = (E << 2) | 3 (EN 300 396-2, 8.2.5.2). */
uint32_t dmo_scramb_init_dcc(uint32_t mni, uint32_t src_addr);

/* Descramble n bits (type-5 -> type-4), one bit per byte. */
void dmo_descramble(uint32_t scramb_init, const uint8_t *coded, unsigned n, uint8_t *type4);

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

enum dmo_burst_type {
	DMO_BURST_DSB,		/* DM synchronization burst: STS */
	DMO_BURST_DNB1,		/* DM normal burst, preamble P1 + NTS1: TCH or SCH/F */
	DMO_BURST_DNB2		/* DM normal burst, preamble P2 + NTS2: STCH + TCH or STCH + STCH */
};

struct dmo_found {
	size_t start;
	enum dmo_burst_type type;
};

/* Find all DSB, DNB1 and DNB2 whose whole burst fits in the stream. Returns 0 and a malloc'd array
 * (caller frees; may be NULL when *count is 0), or -1 on allocation failure. */
int dmo_find_bursts(const uint8_t *stream, size_t len, struct dmo_found **found, size_t *count);

/* SCH/S (60 type-1 bits), EN 300 396-3 table 21. */
struct dmo_sync_s {
	unsigned system_code, pdu_type, comm_type, ab_usage;
	unsigned slot;		/* 1..4 */
	unsigned frame;
	unsigned enc_state;
};
void dmo_parse_sch_s(const uint8_t *type1, struct dmo_sync_s *out);

/* SCH/H (124 type-1 bits), table 22, for communication type 00 or 01. */
struct dmo_sync_h {
	unsigned fill_bit, frag, slots_sch_f, countdown;
	unsigned dst_type, src_type, msg_type;
	uint32_t dst, src, mni;
};
/* Returns 0, or -1 for communication types 10 and 11 (layout not implemented). */
int dmo_parse_sch_h(const uint8_t *type1, unsigned comm_type, struct dmo_sync_h *out);
const char *dmo_msg_type_name(unsigned msg_type);

/* One TCH/S full-slot block (432 type-4 bits) as a 690 x int16 record for the ETSI channel decoder
 * (cdecoder): 6 sync words 0x6b21.. and soft bits +-127, same layout as osmo-tetra's traffic dump. */
#define DMO_TRAFFIC_RECORD_WORDS 690
void dmo_traffic_record(const uint8_t *type4, int16_t *record);

#endif
