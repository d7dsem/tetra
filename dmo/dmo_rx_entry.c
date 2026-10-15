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

/* Decodes and prints one block line; returns crc_ok, or -1 on decoder failure. */
static int report_block(const char *name, const struct dmo_block_params *p,
			const uint8_t *coded, int verbose)
{
	struct dmo_block_result r;

	if (dmo_block_decode(p, coded, &r) < 0) {
		fprintf(stderr, "dmo_rx: %s block decode failed\n", name);
		return -1;
	}
	printf(" %s crc=%s type1=", name, r.crc_ok ? "OK" : "FAIL");
	print_bits(r.type1, p->type1_len);
	if (verbose)
		printf(" tail=%s", r.tail_zero ? "OK" : "FAIL");
	return r.crc_ok;
}

int main(int argc, char **argv)
{
	const char *path = NULL;
	int verbose = 0, bad_args = 0;
	size_t len = 0, count = 0, *starts = NULL;
	size_t ok_s = 0, ok_h = 0;
	uint8_t *stream;

	for (int i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "-v"))
			verbose = 1;
		else if (!path)
			path = argv[i];
		else
			bad_args = 1;
	}
	if (!path || bad_args) {
		fprintf(stderr, "usage: dmo_rx <bits-file> [-v]\n");
		return 2;
	}

	stream = read_bits(path, &len);
	if (!stream)
		return 1;
	if (dmo_sync_find(stream, len, DMO_STS_MAX_BIT_ERRORS_DEFAULT, &starts, &count) < 0) {
		fprintf(stderr, "dmo_rx: out of memory\n");
		free(stream);
		return 1;
	}

	for (size_t i = 0; i < count; i++) {
		struct dmo_burst b;
		int s, h;

		dmo_burst_slice(stream + starts[i], &b);
		printf("%zu", starts[i]);
		s = report_block("SCH/S", &dmo_sch_s_params, b.sch_s, verbose);
		h = report_block("SCH/H", &dmo_sch_h_params, b.sch_h, verbose);
		putchar('\n');
		if (s < 0 || h < 0) {
			free(starts);
			free(stream);
			return 1;
		}
		ok_s += (size_t)s;
		ok_h += (size_t)h;
	}

	printf("candidates=%zu SCH/S_crc_ok=%zu SCH/H_crc_ok=%zu\n", count, ok_s, ok_h);
	free(starts);
	free(stream);
	return 0;
}
