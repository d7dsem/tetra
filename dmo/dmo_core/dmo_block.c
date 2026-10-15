#include <string.h>

#include <lower_mac/crc_simple.h>
#include <lower_mac/tetra_conv_enc.h>
#include <lower_mac/tetra_interleave.h>
#include <lower_mac/tetra_scramb.h>
#include <lower_mac/viterbi.h>

#include "dmo_core.h"

/* Depuncture marker for "no data" expected by viterbi_dec_sb1_wrapper */
#define DEPUNCT_ERASED 0xff

const struct dmo_block_params dmo_sch_s_params = {
	DMO_SCH_S_CODED_BITS, DMO_SCH_S_TYPE2_BITS, DMO_SCH_S_TYPE1_BITS, DMO_SCH_S_INTERLEAVE_A
};

const struct dmo_block_params dmo_sch_h_params = {
	DMO_SCH_H_CODED_BITS, DMO_SCH_H_TYPE2_BITS, DMO_SCH_H_TYPE1_BITS, DMO_SCH_H_INTERLEAVE_A
};

const struct dmo_block_params dmo_sch_f_params = {
	DMO_SCH_F_CODED_BITS, DMO_SCH_F_TYPE2_BITS, DMO_SCH_F_TYPE1_BITS, DMO_SCH_F_INTERLEAVE_A
};

uint32_t dmo_scramb_init_dcc(uint32_t mni, uint32_t src_addr)
{
	uint32_t e = ((mni & 0x3f) << 24) | (src_addr & 0xffffff);

	return (e << 2) | 3;
}

void dmo_descramble(uint32_t scramb_init, const uint8_t *coded, unsigned n, uint8_t *type4)
{
	memcpy(type4, coded, n);
	tetra_scramb_bits(scramb_init, type4, (int)n);
}

/* Call sequence follows osmo-tetra lower_mac/tetra_lower_mac.c tp_sap_udata_ind. */
int dmo_block_decode(const struct dmo_block_params *p, const uint8_t *coded,
		     struct dmo_block_result *res)
{
	return dmo_block_decode_scr(p, DMO_SCRAMB_INIT, coded, res);
}

int dmo_block_decode_scr(const struct dmo_block_params *p, uint32_t scramb_init, const uint8_t *coded,
			 struct dmo_block_result *res)
{
	uint8_t type4[DMO_MAX_CODED_BITS];
	uint8_t type3[DMO_MAX_CODED_BITS];
	uint8_t type3dp[DMO_MAX_TYPE2_BITS * DMO_MOTHER_BITS_PER_INPUT];
	uint8_t type2[DMO_MAX_TYPE2_BITS];

	if (p->coded_len > DMO_MAX_CODED_BITS || p->type2_len > DMO_MAX_TYPE2_BITS ||
	    p->type1_len + DMO_CRC_BITS > p->type2_len)
		return -1;

	dmo_descramble(scramb_init, coded, p->coded_len, type4);
	block_deinterleave(p->coded_len, p->interleave_a, type4, type3);

	memset(type3dp, DEPUNCT_ERASED, sizeof(type3dp));
	if (tetra_rcpc_depunct(TETRA_RCPC_PUNCT_2_3, type3, (int)p->coded_len, type3dp) < 0)
		return -1;

	viterbi_dec_sb1_wrapper(type3dp, type2, p->type2_len);

	res->crc_ok = crc16_ccitt_bits(type2, p->type1_len + DMO_CRC_BITS) == DMO_CRC_GOOD_RESIDUE;
	memcpy(res->type1, type2, p->type1_len);

	res->tail_zero = 1;
	for (unsigned i = p->type1_len + DMO_CRC_BITS; i < p->type2_len; i++)
		if (type2[i])
			res->tail_zero = 0;
	return 0;
}
