#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "dmo_core.h"

static uint8_t *read_bits(const char *path, size_t *len)
{
	FILE *f = fopen(path, "rb");
	uint8_t *buf = NULL;
	size_t cap = 0, n = 0, got;

	if (!f) {
		fprintf(stderr, "dmo_rx: cannot open %s\n", path);
		return NULL;
	}
	do {
		if (cap - n < 65536) {
			uint8_t *tmp = realloc(buf, cap + 1048576);
			if (!tmp) {
				fprintf(stderr, "dmo_rx: out of memory\n");
				free(buf);
				fclose(f);
				return NULL;
			}
			buf = tmp;
			cap += 1048576;
		}
		got = fread(buf + n, 1, cap - n, f);
		n += got;
	} while (got > 0);

	if (ferror(f)) {
		fprintf(stderr, "dmo_rx: read error on %s\n", path);
		free(buf);
		fclose(f);
		return NULL;
	}
	fclose(f);

	for (size_t i = 0; i < n; i++) {
		if (buf[i] > 1) {
			fprintf(stderr, "dmo_rx: byte 0x%02x at offset %zu is not 0 or 1\n", buf[i], i);
			free(buf);
			return NULL;
		}
	}
	*len = n;
	return buf;
}

static void print_bits(const uint8_t *bits, unsigned n)
{
	for (unsigned i = 0; i < n; i++)
		putchar('0' + bits[i]);
}

enum dnb_kind { K_NONE, K_NO_DCC, K_SCH_F, K_TCH, K_STCH_OK, K_STCH_FAIL };

struct rec {
	struct dmo_found f;
	int s_ok, h_ok, h_parsed;
	struct dmo_sync_s s;
	struct dmo_sync_h h;
	uint8_t s_bits[DMO_SCH_S_TYPE1_BITS], h_bits[DMO_SCH_H_TYPE1_BITS];
	enum dnb_kind kind;
	uint8_t f_bits[DMO_SCH_F_TYPE1_BITS];	/* SCH/F type-1 bits, or STCH in the first 124 */
};

/* Colour-code identity taken from a decoded DSB */
struct dcc {
	int valid;
	uint32_t mni, src;
};

static const char *enc_name(unsigned e)
{
	static const char *const n[] = {"DM-1", "DM-2-C", "DM-2-A", "DM-2-B"};

	return n[e & 3];
}

static const char *type_name(enum dmo_burst_type t)
{
	return t == DMO_BURST_DSB ? "DSB" : t == DMO_BURST_DNB1 ? "DNB1" : "DNB2";
}

/* DM-SETUP, DM-CONNECT ACK and DM-OCCUPIED carry the identity the call's colour code is made of */
static int is_call_message(unsigned m)
{
	return m == 0x08 || m == 0x0c || m == 0x0d;
}

static void decode_dsb(struct rec *r, const uint8_t *b, struct dcc *strong, struct dcc *weak)
{
	struct dmo_burst slice;
	struct dmo_block_result rs, rh;

	dmo_burst_slice(b, &slice);
	if (dmo_block_decode(&dmo_sch_s_params, slice.sch_s, &rs) < 0 ||
	    dmo_block_decode(&dmo_sch_h_params, slice.sch_h, &rh) < 0)
		return;
	r->s_ok = rs.crc_ok;
	r->h_ok = rh.crc_ok;
	memcpy(r->s_bits, rs.type1, sizeof(r->s_bits));
	memcpy(r->h_bits, rh.type1, sizeof(r->h_bits));
	if (r->s_ok)
		dmo_parse_sch_s(r->s_bits, &r->s);
	if (r->s_ok && r->h_ok && dmo_parse_sch_h(r->h_bits, r->s.comm_type, &r->h) == 0) {
		r->h_parsed = 1;
		weak->valid = 1;
		weak->mni = r->h.mni;
		weak->src = r->h.src;
		if (is_call_message(r->h.msg_type))
			*strong = *weak;
	}
}

/* Both blocks of a DNB as one 432-bit scrambled block (BKN1 then BKN2) */
static void dnb_blocks(const uint8_t *b, uint8_t *both)
{
	memcpy(both, b + DMO_DNB_BLK1_OFFSET, DMO_DNB_BLK_BITS);
	memcpy(both + DMO_DNB_BLK_BITS, b + DMO_DNB_BLK2_OFFSET, DMO_DNB_BLK_BITS);
}

static void decode_dnb(struct rec *r, const uint8_t *b, const struct dcc *dcc, int16_t **traffic,
		       size_t *n_traffic, size_t *cap_traffic)
{
	uint32_t init;
	struct dmo_block_result res;
	uint8_t both[DMO_SCH_F_CODED_BITS], type4[DMO_SCH_F_CODED_BITS];

	if (!dcc->valid) {
		r->kind = K_NO_DCC;
		return;
	}
	init = dmo_scramb_init_dcc(dcc->mni, dcc->src);
	if (r->f.type == DMO_BURST_DNB2) {
		if (dmo_block_decode_scr(&dmo_sch_h_params, init, b + DMO_DNB_BLK1_OFFSET, &res) < 0)
			return;
		r->kind = res.crc_ok ? K_STCH_OK : K_STCH_FAIL;
		memcpy(r->f_bits, res.type1, DMO_SCH_H_TYPE1_BITS);
		return;
	}
	dnb_blocks(b, both);
	if (dmo_block_decode_scr(&dmo_sch_f_params, init, both, &res) < 0)
		return;
	if (res.crc_ok) {
		r->kind = K_SCH_F;
		memcpy(r->f_bits, res.type1, DMO_SCH_F_TYPE1_BITS);
		return;
	}
	r->kind = K_TCH;
	dmo_descramble(init, both, DMO_SCH_F_CODED_BITS, type4);
	if (*n_traffic == *cap_traffic) {
		size_t ncap = *cap_traffic ? *cap_traffic * 2 : 256;
		int16_t *tmp = realloc(*traffic, ncap * DMO_TRAFFIC_RECORD_WORDS * sizeof(int16_t));

		if (!tmp)
			return;
		*traffic = tmp;
		*cap_traffic = ncap;
	}
	dmo_traffic_record(type4, *traffic + *n_traffic * DMO_TRAFFIC_RECORD_WORDS);
	(*n_traffic)++;
}

static void print_rec(const struct rec *r, int verbose)
{
	printf("%8zu %-4s ", r->f.start, type_name(r->f.type));
	if (r->f.type == DMO_BURST_DSB) {
		printf("S:%s H:%s", r->s_ok ? "OK  " : "FAIL", r->h_ok ? "OK  " : "FAIL");
		if (r->s_ok)
			printf("  slot %u frame %2u %s", r->s.slot, r->s.frame, enc_name(r->s.enc_state));
		if (r->h_parsed)
			printf("  cd %u  %-14s src %u dst %u mni %u", r->h.countdown,
			       dmo_msg_type_name(r->h.msg_type), r->h.src, r->h.dst, r->h.mni);
		if (verbose) {
			printf("\n         SCH/S ");
			print_bits(r->s_bits, DMO_SCH_S_TYPE1_BITS);
			printf("\n         SCH/H ");
			print_bits(r->h_bits, DMO_SCH_H_TYPE1_BITS);
		}
	} else if (r->kind == K_NO_DCC) {
		printf("no colour code (no decoded DSB before it)");
	} else if (r->kind == K_SCH_F) {
		printf("SCH/F OK");
		if (verbose) {
			printf("\n         ");
			print_bits(r->f_bits, DMO_SCH_F_TYPE1_BITS);
		}
	} else if (r->kind == K_TCH) {
		printf("TCH (CRC does not match SCH/F) -> traffic record");
	} else if (r->kind == K_STCH_OK || r->kind == K_STCH_FAIL) {
		printf("STCH %s (block 1)", r->kind == K_STCH_OK ? "OK" : "FAIL");
		if (verbose && r->kind == K_STCH_OK) {
			printf("\n         ");
			print_bits(r->f_bits, DMO_SCH_H_TYPE1_BITS);
		}
	}
	putchar('\n');
}

static void stem_of(const char *path, char *stem, size_t n)
{
	const char *slash = strrchr(path, '/');
	const char *dot = strrchr(path, '.');
	size_t len = (dot && (!slash || dot > slash)) ? (size_t)(dot - path) : strlen(path);

	if (len >= n)
		len = n - 1;
	memcpy(stem, path, len);
	stem[len] = 0;
}

int main(int argc, char **argv)
{
	const char *path = NULL, *out_stem = NULL;
	char stem[4096], out_path[4200];
	int verbose = 0, bad_args = 0;
	size_t len = 0, count = 0;
	size_t n_dsb = 0, n_dnb1 = 0, n_dnb2 = 0, s_ok = 0, h_ok = 0, f_ok = 0, tch = 0, stch_ok = 0, stch = 0;
	size_t n_traffic = 0, cap_traffic = 0;
	struct dmo_found *found = NULL;
	struct rec *recs;
	struct dcc strong = {0, 0, 0}, weak = {0, 0, 0};
	int16_t *traffic = NULL;
	uint8_t *stream;

	for (int i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "-v"))
			verbose = 1;
		else if (!strcmp(argv[i], "-o") && i + 1 < argc)
			out_stem = argv[++i];
		else if (!path)
			path = argv[i];
		else
			bad_args = 1;
	}
	if (!path || bad_args) {
		fprintf(stderr, "usage: dmo_rx <bits-file> [-v] [-o STEM]\n");
		return 2;
	}

	stream = read_bits(path, &len);
	if (!stream)
		return 1;
	if (dmo_find_bursts(stream, len, &found, &count) < 0) {
		fprintf(stderr, "dmo_rx: out of memory\n");
		free(stream);
		return 1;
	}
	recs = calloc(count ? count : 1, sizeof(*recs));
	if (!recs) {
		fprintf(stderr, "dmo_rx: out of memory\n");
		free(found);
		free(stream);
		return 1;
	}

	for (size_t i = 0; i < count; i++) {
		struct rec *r = &recs[i];
		const uint8_t *b = stream + found[i].start;

		r->f = found[i];
		if (r->f.type == DMO_BURST_DSB) {
			decode_dsb(r, b, &strong, &weak);
			n_dsb++;
			s_ok += (size_t)r->s_ok;
			h_ok += (size_t)r->h_ok;
		} else {
			decode_dnb(r, b, strong.valid ? &strong : &weak, &traffic, &n_traffic, &cap_traffic);
			if (r->f.type == DMO_BURST_DNB1) {
				n_dnb1++;
				f_ok += r->kind == K_SCH_F;
				tch += r->kind == K_TCH;
			} else {
				n_dnb2++;
				stch += r->kind == K_STCH_OK || r->kind == K_STCH_FAIL;
				stch_ok += r->kind == K_STCH_OK;
			}
		}
	}

	printf("# dmo_rx: %s, %zu bits, bursts: %zu DSB, %zu DNB1, %zu DNB2\n", path, len, n_dsb, n_dnb1, n_dnb2);
	printf("# DSB:  SCH/S crc ok %zu/%zu, SCH/H crc ok %zu/%zu\n", s_ok, n_dsb, h_ok, n_dsb);
	if (strong.valid || weak.valid) {
		const struct dcc *d = strong.valid ? &strong : &weak;

		printf("# colour code from %s DSB: mni %u (mcc %u mnc %u) src %u\n",
		       strong.valid ? "the last call-message" : "the last decoded", d->mni, d->mni >> 14,
		       d->mni & 0x3fff, d->src);
	} else {
		printf("# colour code: none (no DSB with a decoded SCH/H)\n");
	}
	printf("# DNB1: SCH/F crc ok %zu, TCH records %zu of %zu\n", f_ok, tch, n_dnb1);
	printf("# DNB2: STCH crc ok %zu/%zu\n", stch_ok, stch);
	for (size_t i = 0; i < count; i++)
		print_rec(&recs[i], verbose);

	if (n_traffic) {
		FILE *f;

		if (!out_stem) {
			stem_of(path, stem, sizeof(stem));
			out_stem = stem;
		}
		snprintf(out_path, sizeof(out_path), "%s.out", out_stem);
		f = fopen(out_path, "wb");
		if (!f || fwrite(traffic, sizeof(int16_t) * DMO_TRAFFIC_RECORD_WORDS, n_traffic, f) != n_traffic) {
			fprintf(stderr, "dmo_rx: cannot write %s\n", out_path);
			if (f)
				fclose(f);
			free(traffic);
			free(recs);
			free(found);
			free(stream);
			return 1;
		}
		fclose(f);
		printf("-> %s (%zu TCH records for cdecoder)\n", out_path, n_traffic);
	}
	free(traffic);
	free(recs);
	free(found);
	free(stream);
	return 0;
}
