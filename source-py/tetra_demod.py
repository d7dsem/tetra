"""
Запуск:  tetra_demod in.wav -o stem      (-> stem.txt, stem.bin; без -o: <in>.txt, <in>.bin)
         tetra_demod in.cs16 --fs 192000 --set search.on_db=10
         tetra_demod in.wav --diagnose-only --report health.json
         tetra_demod --print-config

Коди виходу: 0 ok/degraded, 1 degraded за --strict, 2 failed (є ERROR).
"""
import argparse
import dataclasses
import json
import os

from config import PipelineConfig, apply_overrides
from health import HealthReport, error
from io_stage import load_iq, probe_input, write_bits_bin, write_bursts
from memcheck import available_memory_bytes, estimate_memory, format_report, memory_findings
from pipeline import describe, run


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tetra_demod")
    ap.add_argument("infile", nargs="?")
    ap.add_argument("--fs", type=float, help="sample rate для raw .cs16")
    ap.add_argument("-o", "--out", metavar="STEM",
                    help="stem вихідних файлів (STEM.txt, STEM.bin); за замовчуванням ім'я входу без розширення")
    ap.add_argument("--set", action="append", default=[], metavar="group.name=value",
                    help="перевизначити параметр, напр. search.on_db=10")
    ap.add_argument("--print-config", action="store_true")
    ap.add_argument("--mem-only", action="store_true", help="лише оцінка пам'яті, без обробки")
    ap.add_argument("--diagnose-only", action="store_true",
                    help="повний аналіз і звіт, без запису burst'ів")
    ap.add_argument("--report", metavar="FILE.json", help="зберегти звіт здоров'я у JSON")
    ap.add_argument("--strict", action="store_true", help="код виходу 1, якщо статус degraded")
    ap.add_argument("--plot", action="store_true")
    a = ap.parse_args(argv)

    cfg = apply_overrides(PipelineConfig(), a.set)
    if a.print_config:
        print(json.dumps(dataclasses.asdict(cfg), indent=2))
        return 0
    if not a.infile:
        ap.error("потрібен вхідний файл")

    h = HealthReport()
    artefacts = []

    def finish() -> int:
        print(h.format_text())
        if artefacts:
            print("[ARTEFACTS]")
            for p in artefacts:
                print(f"    {os.path.abspath(p)}  {os.path.getsize(p)} B")
        if a.report:
            h.to_json(a.report)
        return h.exit_code(a.strict)

    try:
        fs0, n_in = probe_input(a.infile, a.fs)
    except (OSError, ValueError) as ex:
        h.add(error("input", "INPUT_UNREADABLE", f"{type(ex).__name__}: {ex}", fatal=True))
        return finish()

    if cfg.memory.policy != "off" or a.mem_only:
        est = estimate_memory(n_in, fs0, cfg, available_memory_bytes())
        print(format_report(est))
        h.merge(memory_findings(est, cfg, a.mem_only))
        if a.mem_only or h.fatal:
            return finish()

    try:
        fs, x = load_iq(a.infile, a.fs)
    except (OSError, ValueError, MemoryError) as ex:
        h.add(error("input", "INPUT_UNREADABLE", f"{type(ex).__name__}: {ex}", fatal=True))
        return finish()

    res = run(x, fs, cfg, health=h)
    print(describe(res))
    if not h.fatal and not a.diagnose_only:
        stem = a.out or os.path.splitext(a.infile)[0]
        write_bursts(stem + ".txt", res.bursts)
        write_bits_bin(stem + ".bin", res.bursts)
        artefacts += [stem + ".txt", stem + ".bin"]
        print(f"-> {stem}.txt, {stem}.bin")
    if a.plot and res.search is not None:
        import matplotlib.pyplot as plt
        import numpy as np
        from burst_search import plot_search
        plt.rcParams["keymap.quit"] = [*plt.rcParams["keymap.quit"], "escape"]
        plot_search(res.search, cfg.front.work_fs_hz)
        if res.bursts:
            dd = np.concatenate([b.d for b in res.bursts])
            plt.figure(); plt.plot(dd.real, dd.imag, ".", ms=2)
            plt.axis("equal"); plt.title("diff symbols"); plt.show()
    return finish()


if __name__ == "__main__":
    import os
    import sys
    try:
        code = main()
        sys.stdout.flush()
    except BrokenPipeError:      # напр. `... | head`: тихо завершитись без traceback
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        code = 0
    raise SystemExit(code)
