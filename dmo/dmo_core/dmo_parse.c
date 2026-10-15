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
	out->system_code = bits(type1, 0, 4);
	out->pdu_type = bits(type1, 4, 2);
	out->comm_type = bits(type1, 6, 2);
	out->ab_usage = bits(type1, 10, 2);
	out->slot = bits(type1, 12, 2) + 1;
	out->frame = bits(type1, 14, 5);
	out->enc_state = bits(type1, 19, 2);
}

int dmo_parse_sch_h(const uint8_t *type1, unsigned comm_type, struct dmo_sync_h *out)
{
	unsigned o;

	if (comm_type > 1)
		return -1;
	memset(out, 0, sizeof(*out));
	out->fill_bit = type1[10];
	out->frag = type1[11];
	o = 12;
	if (out->frag) {
		out->slots_sch_f = bits(type1, o, 4);
		o += 4;
	}
	out->countdown = bits(type1, o, 2);
	out->dst_type = bits(type1, o + 2, 2);
	out->dst = bits(type1, o + 4, 24);
	out->src_type = bits(type1, o + 28, 2);
	out->src = bits(type1, o + 30, 24);
	out->mni = bits(type1, o + 54, 24);
	out->msg_type = bits(type1, o + 78, 5);
	return 0;
}

const char *dmo_msg_type_name(unsigned msg_type)
{
	switch (msg_type) {
	case 0x00: return "DM-RESERVED";
	case 0x01: return "DM-SDS OCCUPIED";
	case 0x02: return "DM-TIMING REQUEST";
	case 0x03: return "DM-TIMING ACK";
	case 0x08: return "DM-SETUP";
	case 0x09: return "DM-SETUP PRES";
	case 0x0a: return "DM-CONNECT";
	case 0x0b: return "DM-DISCONNECT";
	case 0x0c: return "DM-CONNECT ACK";
	case 0x0d: return "DM-OCCUPIED";
	case 0x0e: return "DM-RELEASE";
	case 0x0f: return "DM-TX CEASED";
	default: return "other";
	}
}

void dmo_traffic_record(const uint8_t *type4, int16_t *record)
{
	memset(record, 0, sizeof(int16_t) * DMO_TRAFFIC_RECORD_WORDS);
	for (unsigned i = 0; i < 6; i++)
		record[115 * i] = (int16_t)(0x6b21 + i);
	for (unsigned i = 0; i < 114; i++)
		record[1 + i] = type4[i] ? -127 : 127;
	for (unsigned i = 0; i < 114; i++)
		record[116 + i] = type4[114 + i] ? -127 : 127;
	for (unsigned i = 0; i < 114; i++)
		record[231 + i] = type4[228 + i] ? -127 : 127;
	for (unsigned i = 0; i < 90; i++)
		record[346 + i] = type4[342 + i] ? -127 : 127;
}
