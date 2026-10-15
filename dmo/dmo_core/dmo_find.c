#include <stdlib.h>

#include "dmo_core.h"

/* EN 300 396-2: preambles (61), (62), (65); training sequences (63), (64), (66) */
static const uint8_t pre_p1[DMO_PREAMBLE_BITS] = {0,0, 1,1, 0,0, 1,0, 0,0, 1,1};
static const uint8_t pre_p2[DMO_PREAMBLE_BITS] = {1,0, 0,1, 1,0, 1,0, 1,0, 0,1};
static const uint8_t nts_1[DMO_NTS_BITS] = {1,1, 0,1, 0,0, 0,0, 1,1, 1,0, 1,0, 0,1, 1,1, 0,1, 0,0};
static const uint8_t nts_2[DMO_NTS_BITS] = {0,1, 1,1, 1,0, 1,0, 0,1, 0,0, 0,0, 1,1, 0,1, 1,1, 1,0};
static const uint8_t sts_y[DMO_STS_BITS] = {
	1,1, 0,0, 0,0, 0,1, 1,0, 0,1, 1,1, 0,0, 1,1, 1,0,
	1,0, 0,1, 1,1, 0,0, 0,0, 0,1, 1,0, 0,1, 1,1
};

/* Number of differing bits, stopping as soon as it exceeds max_errors. */
static unsigned bit_errors(const uint8_t *win, const uint8_t *pat, unsigned n, unsigned max_errors)
{
	unsigned errors = 0;

	for (unsigned i = 0; i < n; i++)
		if (win[i] != pat[i] && ++errors > max_errors)
			break;
	return errors;
}

static int matches(const uint8_t *win, const uint8_t *pat, unsigned n, unsigned max_errors)
{
	return bit_errors(win, pat, n, max_errors) <= max_errors;
}

static int is_dnb(const uint8_t *b, const uint8_t *pre, const uint8_t *nts)
{
	static const uint8_t tail[DMO_TAIL_BITS] = {0, 0};

	return matches(b, pre, DMO_PREAMBLE_BITS, DMO_PREAMBLE_MAX_BIT_ERRORS) &&
	       matches(b + DMO_NTS_OFFSET, nts, DMO_NTS_BITS, DMO_NTS_MAX_BIT_ERRORS) &&
	       matches(b + DMO_TAIL_OFFSET, tail, DMO_TAIL_BITS, DMO_TAIL_MAX_BIT_ERRORS);
}

int dmo_find_bursts(const uint8_t *stream, size_t len, struct dmo_found **found, size_t *count)
{
	size_t cap = 0, n = 0;
	struct dmo_found *arr = NULL;

	*found = NULL;
	*count = 0;
	for (size_t start = 0; start + DMO_BURST_BITS <= len; start++) {
		const uint8_t *b = stream + start;
		enum dmo_burst_type type;

		if (matches(b + DMO_STS_OFFSET, sts_y, DMO_STS_BITS, DMO_STS_MAX_BIT_ERRORS_DEFAULT))
			type = DMO_BURST_DSB;
		else if (is_dnb(b, pre_p1, nts_1))
			type = DMO_BURST_DNB1;
		else if (is_dnb(b, pre_p2, nts_2))
			type = DMO_BURST_DNB2;
		else
			continue;

		if (n == cap) {
			size_t ncap = cap ? cap * 2 : 64;
			struct dmo_found *tmp = realloc(arr, ncap * sizeof(*arr));

			if (!tmp) {
				free(arr);
				return -1;
			}
			arr = tmp;
			cap = ncap;
		}
		arr[n].start = start;
		arr[n].type = type;
		n++;
	}
	*found = arr;
	*count = n;
	return 0;
}
