"""
Usage:  tetra_demod in.wav -o stem      (-> stem.txt, stem.bin; without -o: <in>.txt, <in>.bin)
        tetra_demod in.cs16 --fs 192000 --set search.on_db=10
        tetra_demod in.wav --diagnose-only --report health.json
        tetra_demod --print-config

Exit codes: 0 ok/degraded, 1 degraded with --strict, 2 failed (has ERROR).
"""
import argparse
import dataclasses
import json
import os

from config import PipelineConfig, apply_overrides
from health import HealthReport, error
from io_stage import (load_iq, probe_input, write_bits_bin, write_bits_bin_aligned,
                      write_bits_bin_phase_aligned, write_bursts)
from pattern_check import SLOT_BITS
from memcheck import available_memory_bytes, estimate_memory, format_report, memory_findings
from pipeline import describe, run


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tetra_demod")
    ap.add_argument("infile", nargs="?")
    ap.add_argument("--fs", type=float, help="sample rate for raw .cs16")
    ap.add_argument("-o", "--out", metavar="STEM",
                    help="output file stem (STEM.txt, STEM.bin); defaults to input name without extension")
    ap.add_argument("--set", action="append", default=[], metavar="group.name=value",
                    help="override a parameter, e.g. search.on_db=10")
    ap.add_argument("--print-config", action="store_true")
    ap.add_argument("--mem-only", action="store_true", help="only estimate memory, no processing")
    ap.add_argument("--diagnose-only", action="store_true",
                    help="full analysis and report, without writing bursts")
    ap.add_argument("--report", metavar="FILE.json", help="save health report as JSON")
    ap.add_argument("--strict", action="store_true", help="exit code 1 if status is degraded")
    ap.add_argument("--plot", action="store_true")
    a = ap.parse_args(argv)

    cfg = apply_overrides(PipelineConfig(), a.set)
    if a.print_config:
        print(json.dumps(dataclasses.asdict(cfg), indent=2))
        return 0
    if not a.infile:
        ap.error("input file required")

    h = HealthReport()
    artefacts = []

    def finish() -> int:
        print(h.format_text())
        if artefacts:
            print("[ARTEFACTS]")
            for p in artefacts:
                print(f"    {os.path.abspath(p)}  {os.path.getsize(p)} B")
        m = h.metrics
        if "pattern_n_bursts" in m:
            print("[SUMMARY]")
            print(f"    bursts:            {m['pattern_n_bursts']}")
            print(f"    symbols (total):   {m['pattern_n_symbols_total']}")
            det = f"{m['pattern_n_any_detected']}/{m['pattern_n_bursts']} ({m['pattern_detect_fraction']:.1%})"
            print(f"    any field found:   {det}")
            thr = m['pattern_threshold']
            print(f"    error threshold:   {thr:.0%}  (tuning: pattern_check.DETECT_THRESHOLD)")
            print("    by field (ETSI EN 300 392-2, section 9.4.4.3):")
            from pattern_check import KNOWN_FIELDS
            NAME_W = 14   # >= longest label "NTS1 (22bit)" (12) + margin
            print(f"      {'name':<{NAME_W}}{'checked':>12}{'exact (0%)':>13}"
                 f"{f'w/ err (<={thr:.0%})':>17}{'median err':>13}")
            for name in ("FCF", "NTS1", "NTS2", "NTS3", "STS", "ETS", "TAIL", "PHASE"):
                status = m.get(f"pattern_{name}_status")
                if status is None:
                    continue
                pattern, _, _ = KNOWN_FIELDS[name]
                label = f"{name} ({len(pattern)}bit)" if pattern is not None else f"{name} (?bit)"
                if status != "ok":
                    print(f"      {label:<{NAME_W}} not a fixed sequence (computed dynamically)")
                    continue
                checked = m.get(f"pattern_{name}_checked", 0)
                exact = m.get(f"pattern_{name}_exact", 0)
                within = m.get(f"pattern_{name}_within_threshold", 0)
                err = m.get(f"pattern_{name}_median_err")
                err_s = f"{err:.1%}" if err is not None else "-"
                print(f"      {label:<{NAME_W}}{checked:>12}{exact:>13}{within:>17}{err_s:>13}")
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
        write_bits_bin_aligned(stem + ".bin2", res.bursts, SLOT_BITS)
        write_bits_bin_phase_aligned(stem + ".bin3", res.bursts, SLOT_BITS,
                                     cfg.front.work_fs_hz, cfg.front.symbol_rate_hz)
        artefacts += [stem + ".txt", stem + ".bin", stem + ".bin2", stem + ".bin3"]
        print(f"-> {stem}.txt, {stem}.bin, {stem}.bin2, {stem}.bin3")
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
    except BrokenPipeError:      # e.g. `... | head`: exit quietly without a traceback
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        code = 0
    raise SystemExit(code)
