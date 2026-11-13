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

	/* SCH/F: both blocks of a DNB with one logical channel (also the size of a TCH/S full-slot block) */
	DMO_SCH_F_CODED_BITS = 432,
	DMO_SCH_F_TYPE2_BITS = 288,
	DMO_SCH_F_TYPE1_BITS = 268,
	DMO_SCH_F_INTERLEAVE_A = 103,

	/* DNB, table 15: preamble, block 1, training sequence, block 2, tail */
	DMO_PREAMBLE_BITS = 12,
	DMO_NTS_BITS = 22,
	DMO_NTS_OFFSET = 230,
	DMO_DNB_BLK1_OFFSET = 14,
	DMO_DNB_BLK_BITS = 216,
	DMO_DNB_BLK2_OFFSET = 252,
	DMO_TAIL_OFFSET = 468,
	DMO_TAIL_BITS = 2,

	/* Allowed bit errors when recognising a DNB (STS in a DSB is matched with DMO_STS_MAX_BIT_ERRORS_DEFAULT) */
	DMO_PREAMBLE_MAX_BIT_ERRORS = 1,
	DMO_NTS_MAX_BIT_ERRORS = 2,
	DMO_TAIL_MAX_BIT_ERRORS = 0,

	/* Identity fields: 24-bit addresses and MNI (MCC 10 bits + MNC 14 bits) */
	DMO_ADDR_BITS = 24,
	DMO_ADDR_MASK = 0xffffff,
	DMO_MNC_BITS = 14,
	DMO_MNC_MASK = 0x3fff,

	/* Scrambler init: e = (MNI low 6 bits) << 24 | source address; init = e << 2 | DMO_SCRAMB_INIT */
	DMO_SCRAMB_MNI_MASK = 0x3f,
	DMO_SCRAMB_E_SHIFT = 2,

	/* SCH/S type-1 fields: offset, width */
	DMO_SCH_S_SYSTEM_CODE_OFF = 0, DMO_SCH_S_SYSTEM_CODE_BITS = 4,
	DMO_SCH_S_PDU_TYPE_OFF = 4, DMO_SCH_S_PDU_TYPE_BITS = 2,
	DMO_SCH_S_COMM_TYPE_OFF = 6, DMO_SCH_S_COMM_TYPE_BITS = 2,
	DMO_SCH_S_AB_USAGE_OFF = 10, DMO_SCH_S_AB_USAGE_BITS = 2,
	DMO_SCH_S_SLOT_OFF = 12, DMO_SCH_S_SLOT_BITS = 2,
	DMO_SCH_S_FRAME_OFF = 14, DMO_SCH_S_FRAME_BITS = 5,
	DMO_SCH_S_ENC_STATE_OFF = 19, DMO_SCH_S_ENC_STATE_BITS = 2,
	DMO_ENC_STATE_MASK = 3,

	/* SCH/H type-1 fields: absolute offsets of the two flags, then a base from which the rest is relative */
	DMO_SCH_H_FILL_BIT_OFF = 10,
	DMO_SCH_H_FRAG_OFF = 11,
	DMO_SCH_H_BASE_OFF = 12,
	DMO_SCH_H_SLOTS_SCH_F_BITS = 4,		/* present only when the fragmentation flag is set */
	DMO_SCH_H_COUNTDOWN_BITS = 2,
	DMO_SCH_H_ADDR_TYPE_BITS = 2,
	DMO_SCH_H_MSG_TYPE_BITS = 5,
	DMO_SCH_H_DST_TYPE_REL = DMO_SCH_H_COUNTDOWN_BITS,
	DMO_SCH_H_DST_REL = DMO_SCH_H_DST_TYPE_REL + DMO_SCH_H_ADDR_TYPE_BITS,
	DMO_SCH_H_SRC_TYPE_REL = DMO_SCH_H_DST_REL + DMO_ADDR_BITS,
	DMO_SCH_H_SRC_REL = DMO_SCH_H_SRC_TYPE_REL + DMO_SCH_H_ADDR_TYPE_BITS,
	DMO_SCH_H_MNI_REL = DMO_SCH_H_SRC_REL + DMO_ADDR_BITS,
	DMO_SCH_H_MSG_TYPE_REL = DMO_SCH_H_MNI_REL + DMO_ADDR_BITS,
	DMO_COMM_TYPE_MAX_PARSED = 1,		/* SCH/H layout is implemented for communication types 00 and 01 */

	/* DM message types (SCH/H) */
	DMO_MSG_RESERVED = 0x00,
	DMO_MSG_SDS_OCCUPIED = 0x01,
	DMO_MSG_TIMING_REQUEST = 0x02,
	DMO_MSG_TIMING_ACK = 0x03,
	DMO_MSG_SETUP = 0x08,
	DMO_MSG_SETUP_PRES = 0x09,
	DMO_MSG_CONNECT = 0x0a,
	DMO_MSG_DISCONNECT = 0x0b,
	DMO_MSG_CONNECT_ACK = 0x0c,
	DMO_MSG_OCCUPIED = 0x0d,
	DMO_MSG_RELEASE = 0x0e,
	DMO_MSG_TX_CEASED = 0x0f,

	/* TCH record for cdecoder: sync words at multiples of the stride, 432 soft bits between them */
	DMO_TCH_SYNC_WORDS = 6,
	DMO_TCH_SYNC_BASE = 0x6b21,
	DMO_TCH_CHUNK_STRIDE = 115,
	DMO_TCH_FULL_CHUNKS = 3,
	DMO_TCH_FULL_CHUNK_BITS = 114,
	DMO_TCH_LAST_CHUNK_BITS = DMO_SCH_F_CODED_BITS - DMO_TCH_FULL_CHUNKS * DMO_TCH_FULL_CHUNK_BITS,
	DMO_TCH_SOFT_BIT = 127,

	/* Initial capacity of growable arrays; the stream reader grows by a chunk when fewer bytes are free */
	DMO_INITIAL_CAP_ARRAY = 64,
	DMO_INITIAL_CAP_TRAFFIC = 256,
	DMO_READ_MIN_FREE_BYTES = 65536,
	DMO_READ_GROW_BYTES = 1048576,

	/* Largest block of each kind, for stack buffers */
	DMO_MAX_CODED_BITS = DMO_SCH_F_CODED_BITS,
	DMO_MAX_TYPE2_BITS = DMO_SCH_F_TYPE2_BITS,
	DMO_MAX_TYPE1_BITS = DMO_SCH_F_TYPE1_BITS
};

#endif
