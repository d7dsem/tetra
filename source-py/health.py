"""
Модель діагностики: Finding (знахідка), CheckResult (результат одного етапу),
HealthReport (зведення по запуску).

Рівні деградації запуску:
  ok        нічого, окрім INFO
  degraded  є WARN: результат отримано, але його треба інтерпретувати обережно
  failed    є ERROR: результат ненадійний або обробку зупинено (fatal)
Коди виходу CLI: 0 ok/degraded, 1 degraded за --strict, 2 failed.
"""
import json
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional


class Severity(IntEnum):
    INFO = 0
    WARN = 1
    ERROR = 2


@dataclass(frozen=True)
class Finding:
    stage: str
    code: str
    severity: Severity
    message: str
    value: Optional[float] = None
    threshold: Optional[float] = None
    fatal: bool = False        # обробку далі продовжувати безглуздо


def info(stage, code, message, value=None, threshold=None):
    return Finding(stage, code, Severity.INFO, message, value, threshold)


def warn(stage, code, message, value=None, threshold=None):
    return Finding(stage, code, Severity.WARN, message, value, threshold)


def error(stage, code, message, value=None, threshold=None, fatal=False):
    return Finding(stage, code, Severity.ERROR, message, value, threshold, fatal)


@dataclass
class CheckResult:
    findings: List[Finding] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)

    def add(self, f: Finding) -> None:
        self.findings.append(f)


@dataclass
class HealthReport:
    findings: List[Finding] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)

    def add(self, f: Finding) -> None:
        self.findings.append(f)

    def merge(self, r: CheckResult) -> "HealthReport":
        self.findings.extend(r.findings)
        self.metrics.update(r.metrics)
        return self

    def has(self, code: str) -> bool:
        return any(f.code == code for f in self.findings)

    @property
    def fatal(self) -> bool:
        return any(f.fatal for f in self.findings)

    @property
    def status(self) -> str:
        sev = max((f.severity for f in self.findings), default=Severity.INFO)
        return {Severity.ERROR: "failed", Severity.WARN: "degraded"}.get(sev, "ok")

    def exit_code(self, strict: bool = False) -> int:
        if self.status == "failed":
            return 2
        return 1 if (strict and self.status == "degraded") else 0

    def counts(self) -> Dict[str, int]:
        c = {s.name: 0 for s in Severity}
        for f in self.findings:
            c[f.severity.name] += 1
        return c

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "counts": self.counts(),
            "metrics": self.metrics,
            "findings": [{"stage": f.stage, "code": f.code, "severity": f.severity.name,
                          "message": f.message, "value": f.value, "threshold": f.threshold,
                          "fatal": f.fatal} for f in self.findings],
        }

    def to_json(self, path: str) -> None:
        with open(path, "w") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2, default=float)

    def format_text(self, with_metrics: bool = True) -> str:
        c = self.counts()
        L = [f"СТАТУС: {self.status}  (ERROR={c['ERROR']} WARN={c['WARN']} INFO={c['INFO']})"]
        for f in sorted(self.findings, key=lambda f: -f.severity):
            L.append(f"  [{f.severity.name}] {f.stage}/{f.code}: {f.message}")
        if with_metrics and self.metrics:
            L.append("Метрики (виміряно з даних):")
            groups: Dict[str, List[str]] = {}
            for k, v in self.metrics.items():
                g = k.split("_", 1)[0]
                groups.setdefault(g, []).append(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}")
            for g, items in groups.items():
                L.append("  " + "  ".join(items))
        return "\n".join(L)
