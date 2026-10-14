# Апдейт

Ось приауклад аутпут
В ньому НЕ ВИЛНО ЯКІ АРТЕФАУКТИ СВРЕНІ


d7@sdrserver:~/Pub1lic/signals/1otd/azard-sms_2026-10-13$ tetra_demod sms.wav -o sms
Вхід: 7.7 с, 0.55 М відліків @ 72000 Гц
Оцінка піку: 176 МБ, з запасом: 221 МБ  (вузьке місце: matched_filter+пошук)
Доступно: 58499 МБ (/proc/meminfo MemAvailable)
Вистачає: так
[degraded] floor(median)=-68.5 dB  raw=18 -> merged=18 -> filtered=5 -> final=5  | demod ok=5 rejected=0 failed=0
-> sms.txt, sms.bin
СТАТУС: degraded  (ERROR=0 WARN=1 INFO=0)
  [WARN] levels/LOW_LEVEL: RMS=5.22e-04: дуже низький рівень, корисний сигнал займає мало розрядів
Метрики (виміряно з даних):
  mem_required_mb=220.6  mem_available_mb=5.85e+04
  meta_fs_hz=7.2e+04  meta_n_samples=552076  meta_duration_s=7.668
  input_nonfinite_frac=0
  level_rms_dbfs=-65.65  level_clip_frac=0  level_dc_ratio=0.000629  level_circularity=0.01721
  spec_power_swing_db=8.294  spec_active_blocks=69  spec_blocks=539  spec_noise_floor_db=-43.63  spec_coarse_offset_hz=-42.48  spec_bw99_hz=2.138e+04  spec_bw_ratio=0.8796  spec_dc_spike_db=1.302  spec_symline_db=12.15
  act_duty=0.1287  act_n_segments=18  act_n_final=5  act_median_len_sym=4317
  burst_ok=5  burst_rejected=0  burst_failed=0  burst_coherence_median=0.5222  burst_coherence_p10=0.4806  burst_phase_rms_median_deg=16.27  burst_freq_median_hz=130.1  burst_freq_std_hz=13.96  burst_near_limit_share=0  burst_vs_spec_offset_hz=172.5


ДОАЛДТИ
 [ARTEFACTS] 
    abs/path/to/<stem_out>.txt  size
    abs/path/to/<stem_out>.bin  size