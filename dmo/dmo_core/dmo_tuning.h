#ifndef DMO_TUNING_H
#define DMO_TUNING_H

/* Tunable values and standard constants. Ref: dmo/docs/dmo-phy-spec.md */

enum {
	/* Default allowed bit errors in the sync training sequence match */
	DMO_STS_MAX_BIT_ERRORS_DEFAULT = 0,

	/* DSB burst length in bits (table 16) */
	DMO_BURST_BITS = 470,

	/* Sync training sequence y1..y38 */
	DMO_STS_OFFSET = 214,
	DMO_STS_BITS = 38,

	/* SCH/S: burst offset, coded bits, type-2 bits, type-1 bits, interleaver a */
	DMO_SCH_S_OFFSET = 94,
	DMO_SCH_S_CODED_BITS = 120,
	DMO_SCH_S_TYPE2_BITS = 80,
	DMO_SCH_S_TYPE1_BITS = 60,
	DMO_SCH_S_INTERLEAVE_A = 11,

	/* SCH/H in block 2 of DSB: same fields as above */
	DMO_SCH_H_OFFSET = 252,
	DMO_SCH_H_CODED_BITS = 216,
	DMO_SCH_H_TYPE2_BITS = 144,
	DMO_SCH_H_TYPE1_BITS = 124,
	DMO_SCH_H_INTERLEAVE_A = 101,

	/* Scrambler init for e(1..30)=0 (colour code 0) */
	DMO_SCRAMB_INIT = 3,

	/* Block code CRC length in bits and its good-residue value */
	DMO_CRC_BITS = 16,
	DMO_CRC_GOOD_RESIDUE = 0x1d0f,

	/* RCPC mother code outputs per type-2 bit */
	DMO_MOTHER_BITS_PER_INPUT = 4,

	/* Largest block of each kind, for stack buffers */
	DMO_MAX_CODED_BITS = DMO_SCH_H_CODED_BITS,
	DMO_MAX_TYPE2_BITS = DMO_SCH_H_TYPE2_BITS,
	DMO_MAX_TYPE1_BITS = DMO_SCH_H_TYPE1_BITS
};

#endif
