#include "dmo_core.h"

void dmo_burst_slice(const uint8_t *burst, struct dmo_burst *out)
{
	out->sch_s = burst + DMO_SCH_S_OFFSET;
	out->sch_h = burst + DMO_SCH_H_OFFSET;
}
