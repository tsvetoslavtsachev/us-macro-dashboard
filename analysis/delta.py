"""
analysis/delta.py
=================
Week-over-week briefing delta.

Серийно сравнение на две briefing състояния:
  - regime промяна
  - cross-lens pair state flips
  - breadth moves >= threshold (в pp)
  - появили се / изчезнали HIGH non-consensus сигнали
  - появили се / изчезнали NEW-5Y екстремуми в top-N anomalies

Persistence формат: JSON в ``data/state/briefing_YYYY-MM-DD.json``.
Зарежда най-скорошния snapshot, чиято дата е < днешната.

Философия:
  - Snapshot-ът трябва да е достатъчно дребен и stable (без raw series)
  - Всеки delta event е човешки четим
  - BreadthMoveThreshold (10pp) е конфигурируем — ако стане spammy, вдига се

Dependencies:
  - analysis.executive.RegimeSnapshot
  - analysis.breadth.LensBreadthReport
  - analysis.divergence.CrossLensDivergenceReport
  - analysis.anomaly.AnomalyReport
  - analysis.non_consensus.NonConsensusReport
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional


BREADTH_MOVE_THRESHOLD_PP = 0.10   # 10 процентни пункта → notable
STATE_DIR_DEFAULT = "data/state"


# ============================================================
# PERSISTABLE SNAPSHOT
# ============================================================

@dataclass
class BriefingStateSnapshot:
    """Компактно представяне на briefing-а за WoW сравнение.

    Умишлено пропускаме raw series данни; запазваме само output метрики.
    """
    as_of: Optional[str]                                 # max data date от отчетите
    generated_on: str                                    # ISO дата на генериране
    regime_label: str
    regime_label_bg: str
    cross_lens_states: dict[str, str] = field(default_factory=dict)   # pair_id → state
    breadth_by_pg: dict = field(default_factory=dict)   # "lens/peer_group" → float|None
    high_nc_keys: list[str] = field(default_factory=list)
    top_anomaly_keys: list[str] = field(default_factory=list)
    new_extreme_keys: list[str] = field(default_factory=list)   # подмножество на top с is_new_extreme

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "BriefingStateSnapshot":
        return BriefingStateSnapshot(
            as_of=d.get("as_of"),
            generated_on=d.get("generated_on", ""),
            regime_label=d.get("regime_label", "transition"),
            regime_label_bg=d.get("regime_label_bg", ""),
            cross_lens_states=dict(d.get("cross_lens_states", {})),
            breadth_by_pg=dict(d.get("breadth_by_pg", {})),
            high_nc_keys=list(d.get("high_nc_keys", [])),
            top_anomaly_keys=list(d.get("top_anomaly_keys", [])),
            new_extreme_keys=list(d.get("new_extreme_keys", [])),
        )


# ============================================================
# DELTA RECORDS
# ============================================================

@dataclass
class CrossLensStateChange:
    pair_id: str
    from_state: str
    to_state: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BreadthMove:
    lens: str
    peer_group: str
    from_value: Optional[float]
    to_value: Optional[float]
    delta_pp: float   # в процентни пункта (положителни = разширяване)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BriefingDelta:
    prev_generated_on: Optional[str]
    prev_as_of: Optional[str]
    curr_generated_on: str
    curr_as_of: Optional[str]
    regime_change: Optional[tuple]   # (from_label_bg, to_label_bg) или None
    cross_lens_changes: list[CrossLensStateChange] = field(default_factory=list)
    breadth_moves: list[BreadthMove] = field(default_factory=list)
    new_high_nc: list[str] = field(default_factory=list)
    vanished_high_nc: list[str] = field(default_factory=list)
    new_top_anomalies: list[str] = field(default_factory=list)
    vanished_top_anomalies: list[str] = field(default_factory=list)
    new_extremes_surfaced: list[str] = field(default_factory=list)
    new_extremes_resolved: list[str] = field(default_factory=list)

    @property
    def has_content(self) -> bool:
        return bool(
            self.regime_change
            or self.cross_lens_changes
            or self.breadth_moves
            or self.new_high_nc
            or self.vanished_high_nc
            or self.new_extremes_surfaced
            or self.new_extremes_resolved
        )

    def to_dict(self) -> dict:
        return {
            "prev_generated_on": self.prev_generated_on,
            "prev_as_of": self.prev_as_of,
            "curr_generated_on": self.curr_generated_on,
            "curr_as_of": self.curr_as_of,
            "regime_change": list(self.regime_change) if self.regime_change else None,
            "cross_lens_changes": [c.to_dict() for c in self.cross_lens_changes],
            "breadth_moves": [b.to_dict() for b in self.breadth_moves],
            "new_high_nc": list(self.new_high_nc),
            "vanished_high_nc": list(self.vanished_high_nc),
            "new_top_anomalies": list(self.new_top_anomalies),
            "vanished_top_anomalies": list(self.vanished_top_anomalies),
            "new_extremes_surfaced": list(self.new_extremes_surfaced),
            "new_extremes_resolved": list(self.new_extremes_resolved),
        }


# ============================================================
# BUILDER — извлича snapshot от reports
# ============================================================

def build_state_snapshot(
    exec_snapshot,
    cross_report,
    lens_reports: dict,
    anomaly_report,
    nc_report,
    generated_on: Optional[date] = None,
) -> BriefingStateSnapshot:
    """Събира persistable snapshot от всички analysis артефакти."""
    if generated_on is None:
        generated_on = date.today()

    cross_states = {p.pair_id: p.state for p in cross_report.pairs}

    breadth_by_pg: dict[str, Optional[float]] = {}
    for lens, report in lens_reports.items():
        for pg in report.peer_groups:
            key = f"{lens}/{pg.name}"
            bp = pg.breadth_positive
            # NaN → None за JSON safety
            if isinstance(bp, float) and bp != bp:
                breadth_by_pg[key] = None
            else:
                breadth_by_pg[key] = float(bp) if bp is not None else None

    high_nc_keys = sorted({
        r.series_key for r in nc_report.highlights
        if r.signal_strength == "high"
    })

    top_keys = [a.series_key for a in anomaly_report.top]
    ne_keys = sorted({a.series_key for a in anomaly_report.top if a.is_new_extreme})

    return BriefingStateSnapshot(
        as_of=exec_snapshot.as_of,
        generated_on=generated_on.isoformat(),
        regime_label=exec_snapshot.regime_label,
        regime_label_bg=exec_snapshot.regime_label_bg,
        cross_lens_states=cross_states,
        breadth_by_pg=breadth_by_pg,
        high_nc_keys=high_nc_keys,
        top_anomaly_keys=top_keys,
        new_extreme_keys=ne_keys,
    )


# ============================================================
# COMPUTE DELTA
# ============================================================

def compute_delta(
    current: BriefingStateSnapshot,
    previous: Optional[BriefingStateSnapshot],
    breadth_threshold_pp: float = BREADTH_MOVE_THRESHOLD_PP,
) -> BriefingDelta:
    """Диф между текущ и предишен state snapshot.

    Ако previous е None — връща празен BriefingDelta с has_content=False (няма референтна седмица).
    """
    if previous is None:
        return BriefingDelta(
            prev_generated_on=None,
            prev_as_of=None,
            curr_generated_on=current.generated_on,
            curr_as_of=current.as_of,
            regime_change=None,
        )

    # Regime change
    regime_change: Optional[tuple] = None
    if current.regime_label != previous.regime_label:
        regime_change = (previous.regime_label_bg, current.regime_label_bg)

    # Cross-lens state changes
    cross_changes: list[CrossLensStateChange] = []
    all_pair_ids = set(current.cross_lens_states) | set(previous.cross_lens_states)
    for pid in sorted(all_pair_ids):
        from_s = previous.cross_lens_states.get(pid, "—")
        to_s = current.cross_lens_states.get(pid, "—")
        if from_s != to_s:
            cross_changes.append(CrossLensStateChange(pair_id=pid, from_state=from_s, to_state=to_s))

    # Breadth moves
    breadth_moves: list[BreadthMove] = []
    all_pg_keys = set(current.breadth_by_pg) | set(previous.breadth_by_pg)
    for key in sorted(all_pg_keys):
        from_val = previous.breadth_by_pg.get(key)
        to_val = current.breadth_by_pg.get(key)
        if from_val is None or to_val is None:
            continue
        delta = to_val - from_val
        if abs(delta) >= breadth_threshold_pp:
            lens, _, pg = key.partition("/")
            breadth_moves.append(BreadthMove(
                lens=lens,
                peer_group=pg,
                from_value=round(from_val, 3),
                to_value=round(to_val, 3),
                delta_pp=round(delta, 3),
            ))
    # Сортиране по |delta_pp| desc
    breadth_moves.sort(key=lambda b: abs(b.delta_pp), reverse=True)

    # Non-consensus deltas
    curr_nc = set(current.high_nc_keys)
    prev_nc = set(previous.high_nc_keys)
    new_high = sorted(curr_nc - prev_nc)
    vanished_high = sorted(prev_nc - curr_nc)

    # Top anomalies deltas
    curr_top = set(current.top_anomaly_keys)
    prev_top = set(previous.top_anomaly_keys)
    new_top = sorted(curr_top - prev_top)
    vanished_top = sorted(prev_top - curr_top)

    # New-5Y extremes deltas
    curr_ne = set(current.new_extreme_keys)
    prev_ne = set(previous.new_extreme_keys)
    new_ne = sorted(curr_ne - prev_ne)
    resolved_ne = sorted(prev_ne - curr_ne)

    return BriefingDelta(
        prev_generated_on=previous.generated_on,
        prev_as_of=previous.as_of,
        curr_generated_on=current.generated_on,
        curr_as_of=current.as_of,
        regime_change=regime_change,
        cross_lens_changes=cross_changes,
        breadth_moves=breadth_moves,
        new_high_nc=new_high,
        vanished_high_nc=vanished_high,
        new_top_anomalies=new_top,
        vanished_top_anomalies=vanished_top,
        new_extremes_surfaced=new_ne,
        new_extremes_resolved=resolved_ne,
    )


# ============================================================
# PERSISTENCE — save/load JSON
# ============================================================

def save_state(
    snapshot: BriefingStateSnapshot,
    state_dir: str = STATE_DIR_DEFAULT,
) -> str:
    """Записва snapshot-а в ``{state_dir}/briefing_{generated_on}.json``.

    Връща абсолютния path. Създава директорията ако не съществува.
    """
    out_dir = Path(state_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"briefing_{snapshot.generated_on}.json"
    out_path.write_text(
        json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(out_path.resolve())


def load_latest_state(
    state_dir: str = STATE_DIR_DEFAULT,
    before: Optional[date] = None,
) -> Optional[BriefingStateSnapshot]:
    """Зарежда най-скорошния snapshot с generated_on < ``before``.

    Args:
        state_dir: директория с briefing_*.json файлове.
        before: търсим snapshots с generated_on < before. Ако None — търсим всички
                и връщаме последния (удобно за self-test).

    Returns:
        BriefingStateSnapshot или None ако няма кандидат.
    """
    in_dir = Path(state_dir)
    if not in_dir.exists():
        return None

    candidates: list[tuple[date, Path]] = []
    for p in in_dir.glob("briefing_*.json"):
        # Имаме формат briefing_YYYY-MM-DD.json
        stem = p.stem  # "briefing_2026-04-18"
        date_str = stem.replace("briefing_", "", 1)
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if before is not None and d >= before:
            continue
        candidates.append((d, p))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    _, latest_path = candidates[0]
    data = json.loads(latest_path.read_text(encoding="utf-8"))
    return BriefingStateSnapshot.from_dict(data)
