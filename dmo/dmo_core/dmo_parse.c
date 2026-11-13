#include <string.h>

#include "dmo_core.h"

static unsigned bits(const uint8_t *b, unsigned off, unsigned n)
{
	unsigned v = 0;

	for (unsigned i = 0; i < n; i++)
		v = (v << 1) | b[off + i];
	return v;
}

void dmo_parse_sch_s(const uint8_t *type1, struct dmo_sync_s *out)
{
	out->system_code = bits(type1, DMO_SCH_S_SYSTEM_CODE_OFF, DMO_SCH_S_SYSTEM_CODE_BITS);
	out->pdu_type = bits(type1, DMO_SCH_S_PDU_TYPE_OFF, DMO_SCH_S_PDU_TYPE_BITS);
	out->comm_type = bits(type1, DMO_SCH_S_COMM_TYPE_OFF, DMO_SCH_S_COMM_TYPE_BITS);
	out->ab_usage = bits(type1, DMO_SCH_S_AB_USAGE_OFF, DMO_SCH_S_AB_USAGE_BITS);
	out->slot = bits(type1, DMO_SCH_S_SLOT_OFF, DMO_SCH_S_SLOT_BITS) + 1;
	out->frame = bits(type1, DMO_SCH_S_FRAME_OFF, DMO_SCH_S_FRAME_BITS);
	out->enc_state = bits(type1, DMO_SCH_S_ENC_STATE_OFF, DMO_SCH_S_ENC_STATE_BITS);
}

int dmo_parse_sch_h(const uint8_t *type1, unsigned comm_type, struct dmo_sync_h *out)
{
	unsigned o;

	if (comm_type > DMO_COMM_TYPE_MAX_PARSED)
		return -1;
	memset(out, 0, sizeof(*out));
	out->fill_bit = type1[DMO_SCH_H_FILL_BIT_OFF];
	out->frag = type1[DMO_SCH_H_FRAG_OFF];
	o = DMO_SCH_H_BASE_OFF;
	if (out->frag) {
		out->slots_sch_f = bits(type1, o, DMO_SCH_H_SLOTS_SCH_F_BITS);
		o += DMO_SCH_H_SLOTS_SCH_F_BITS;
	}
	out->countdown = bits(type1, o, DMO_SCH_H_COUNTDOWN_BITS);
	out->dst_type = bits(type1, o + DMO_SCH_H_DST_TYPE_REL, DMO_SCH_H_ADDR_TYPE_BITS);
	out->dst = bits(type1, o + DMO_SCH_H_DST_REL, DMO_ADDR_BITS);
	out->src_type = bits(type1, o + DMO_SCH_H_SRC_TYPE_REL, DMO_SCH_H_ADDR_TYPE_BITS);
	out->src = bits(type1, o + DMO_SCH_H_SRC_REL, DMO_ADDR_BITS);
	out->mni = bits(type1, o + DMO_SCH_H_MNI_REL, DMO_ADDR_BITS);
	out->msg_type = bits(type1, o + DMO_SCH_H_MSG_TYPE_REL, DMO_SCH_H_MSG_TYPE_BITS);
	return 0;
}

const char *dmo_msg_type_name(unsigned msg_type)
{
	switch (msg_type) {
	case DMO_MSG_RESERVED: return "DM-RESERVED";
	case DMO_MSG_SDS_OCCUPIED: return "DM-SDS OCCUPIED";
	case DMO_MSG_TIMING_REQUEST: return "DM-TIMING REQUEST";
	case DMO_MSG_TIMING_ACK: return "DM-TIMING ACK";
	case DMO_MSG_SETUP: return "DM-SETUP";
	case DMO_MSG_SETUP_PRES: return "DM-SETUP PRES";
	case DMO_MSG_CONNECT: return "DM-CONNECT";
	case DMO_MSG_DISCONNECT: return "DM-DISCONNECT";
	case DMO_MSG_CONNECT_ACK: return "DM-CONNECT ACK";
	case DMO_MSG_OCCUPIED: return "DM-OCCUPIED";
	case DMO_MSG_RELEASE: return "DM-RELEASE";
	case DMO_MSG_TX_CEASED: return "DM-TX CEASED";
	default: return "other";
	}
}

void dmo_traffic_record(const uint8_t *type4, int16_t *record)
{
	memset(record, 0, sizeof(int16_t) * DMO_TRAFFIC_RECORD_WORDS);
	for (unsigned i = 0; i < DMO_TCH_SYNC_WORDS; i++)
		record[DMO_TCH_CHUNK_STRIDE * i] = (int16_t)(DMO_TCH_SYNC_BASE + i);
	for (unsigned c = 0; c <= DMO_TCH_FULL_CHUNKS; c++) {
		unsigned n = c < DMO_TCH_FULL_CHUNKS ? DMO_TCH_FULL_CHUNK_BITS : DMO_TCH_LAST_CHUNK_BITS;

		for (unsigned i = 0; i < n; i++)
			record[DMO_TCH_CHUNK_STRIDE * c + 1 + i] =
				type4[c * DMO_TCH_FULL_CHUNK_BITS + i] ? -DMO_TCH_SOFT_BIT : DMO_TCH_SOFT_BIT;
	}
}
