#include <stdlib.h>

#include "dmo_core.h"

/* Sync training sequence y1..y38, EN 300 396-2 (66) */
static const uint8_t sts_y[DMO_STS_BITS] = {
	1,1, 0,0, 0,0, 0,1, 1,0, 0,1, 1,1, 0,0, 1,1, 1,0,
	1,0, 0,1, 1,1, 0,0, 0,0, 0,1, 1,0, 0,1, 1,1
};

/* Returns 1 if the window differs from y in at most max_errors bits. */
static int sts_matches(const uint8_t *win, unsigned max_errors)
{
	unsigned errors = 0;

	for (size_t i = 0; i < DMO_STS_BITS; i++) {
		if (win[i] != sts_y[i] && ++errors > max_errors)
			return 0;
	}
	return 1;
}

int dmo_sync_find(const uint8_t *stream, size_t len, unsigned max_bit_errors,
		  size_t **starts, size_t *count)
{
	size_t cap = 0, n = 0;
	size_t *arr = NULL;

	*starts = NULL;
	*count = 0;
	if (len < DMO_BURST_BITS)
		return 0;

	/* start + DMO_BURST_BITS <= len */
	for (size_t start = 0; start + DMO_BURST_BITS <= len; start++) {
		if (!sts_matches(stream + start + DMO_STS_OFFSET, max_bit_errors))
			continue;
		if (n == cap) {
			size_t ncap = cap ? cap * 2 : 64;
			size_t *tmp = realloc(arr, ncap * sizeof(*arr));
			if (!tmp) {
				free(arr);
				return -1;
			}
			arr = tmp;
			cap = ncap;
		}
		arr[n++] = start;
	}
	*starts = arr;
	*count = n;
	return 0;
}
