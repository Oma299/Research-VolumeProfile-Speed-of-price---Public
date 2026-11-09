"""Create descriptive VA-quintile summaries and a Kaplan-Meier figure."""

from pathlib import Path
import os
import tempfile

os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "research-volume-profile-matplotlib"),
)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from statsmodels.duration.survfunc import SurvfuncRight


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVENTS_PATH = PROJECT_ROOT / "outputs" / "tables" / "events_analysis.csv"
SUMMARY_PATH = PROJECT_ROOT / "07 Results" / "tables" / "day3_block3_va_quintile_summaries.csv"
FIGURE_PATH = PROJECT_ROOT / "07 Results" / "figures" / "day3_block4_04_km_time_to_target_by_va_quintile.png"
REPORT_PATH = PROJECT_ROOT / "reports" / "day3" / "block3_wide_descriptive" / "DAY3_BLOCK3_DESCRIPTIVE_SUMMARIES.md"

GROUP_LABELS = ("Q1", "Q2", "Q3", "Q4", "Q5")
QUANTILE_LEVELS = (0.20, 0.40, 0.60, 0.80)
EXPECTED_TOTAL = 324
EXPECTED_VA_AVAILABLE = 300
EXPECTED_VA_MISSING = 24
EXPECTED_MISSING_REASON = "reference_region_outside_historical_range"


def _boolean(values: pd.Series) -> pd.Series:
    if values.isna().any():
        raise ValueError(f"Boolean field {values.name} contains missing values")
    if pd.api.types.is_bool_dtype(values):
        return values
    normalized = values.astype(str).str.strip().str.lower()
    if not normalized.isin(("true", "false")).all():
        raise ValueError(f"Boolean field {values.name} has unexpected values")
    return normalized.eq("true")


def _finite_numeric(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return pd.Series(np.isfinite(numeric.to_numpy(dtype=float)), index=values.index)


def _load_and_group() -> tuple[pd.DataFrame, pd.DataFrame, list[float]]:
    if not EVENTS_PATH.is_file():
        raise FileNotFoundError(f"Analysis event table is missing: {EVENTS_PATH}")
    events = pd.read_csv(EVENTS_PATH, low_memory=False)
    required = {
        "event_id",
        "breakout_direction",
        "VA",
        "log1p_VA",
        "profile_valid",
        "va_missing",
        "va_missing_reason",
        "target_hit",
        "time_to_target_minutes",
        "observed_time_minutes",
        "right_censored",
        "outcome_missing",
        "r_60",
    }
    missing_columns = required.difference(events.columns)
    if missing_columns:
        raise ValueError(f"Event table lacks required fields: {sorted(missing_columns)}")
    if len(events) != EXPECTED_TOTAL or events["event_id"].isna().any() or events["event_id"].duplicated().any():
        raise ValueError("Expected 324 rows with unique, non-missing event_id values")

    va = pd.to_numeric(events["VA"], errors="coerce")
    log_va = pd.to_numeric(events["log1p_VA"], errors="coerce")
    profile_valid = _boolean(events["profile_valid"])
    va_missing = _boolean(events["va_missing"])
    available = profile_valid & ~va_missing & _finite_numeric(va) & _finite_numeric(log_va)
    if int(available.sum()) != EXPECTED_VA_AVAILABLE or int((~available).sum()) != EXPECTED_VA_MISSING:
        raise ValueError("Expected 300 finite valid VA rows and 24 missing VA rows")
    missing_reasons = events.loc[~available, "va_missing_reason"].fillna("<missing>").value_counts()
    if missing_reasons.to_dict() != {EXPECTED_MISSING_REASON: EXPECTED_VA_MISSING}:
        raise ValueError(f"Unexpected missing VA reasons: {missing_reasons.to_dict()}")

    eligible = events.loc[available].copy()
    eligible["VA"] = va.loc[available].astype(float)
    eligible["log1p_VA"] = log_va.loc[available].astype(float)
    cut_points = eligible["VA"].quantile(QUANTILE_LEVELS, interpolation="linear").to_list()
    edges = [-np.inf, *cut_points, np.inf]
    if len(set(cut_points)) != len(QUANTILE_LEVELS):
        raise ValueError(f"VA ties prevent five distinct quintile boundaries: {cut_points}")

    groups = pd.cut(
        eligible["VA"],
        bins=edges,
        labels=GROUP_LABELS,
        right=True,
        include_lowest=True,
    )
    counts = groups.value_counts(sort=False).reindex(GROUP_LABELS, fill_value=0)
    if counts.eq(0).any():
        raise ValueError(f"VA ties prevent five non-empty groups: {counts.to_dict()}")
    eligible["va_quintile"] = groups.astype(str)
    return events, eligible, cut_points


def _summarize(
    eligible: pd.DataFrame,
    cut_points: list[float],
) -> tuple[pd.DataFrame, dict[str, object]]:
    outcome_missing = _boolean(eligible["outcome_missing"])
    target_hit = eligible["target_hit"]
    if target_hit.isna().any():
        complete_outcome = ~outcome_missing & target_hit.notna()
    else:
        complete_outcome = ~outcome_missing
    duration = pd.to_numeric(eligible["observed_time_minutes"], errors="coerce")
    duration_finite = _finite_numeric(duration)
    km_eligible = complete_outcome & duration_finite & duration.between(1, 240)
    if not km_eligible.equals(complete_outcome):
        raise ValueError("Complete outcome rows must have finite observed durations from 1 to 240 minutes")

    right_censored = _boolean(eligible["right_censored"])
    censored = km_eligible & right_censored
    if censored.any():
        valid_censor = (
            ~target_hit.loc[censored].astype(bool)
            & duration.loc[censored].eq(240)
            & pd.to_numeric(eligible.loc[censored, "time_to_target_minutes"], errors="coerce").isna()
        )
        if not valid_censor.all():
            raise ValueError("Right-censored rows must be full 240-minute no-hit observations")
    if (km_eligible & right_censored & target_hit.astype(bool)).any():
        raise ValueError("A right-censored row cannot be marked as a target hit")

    r60 = pd.to_numeric(eligible["r_60"], errors="coerce")
    r60_finite = _finite_numeric(r60)
    rows = []
    medians: dict[str, object] = {}
    lower_edges = [-np.inf, *cut_points]
    upper_edges = [*cut_points, np.inf]
    for index, label in enumerate(GROUP_LABELS):
        group = eligible.loc[eligible["va_quintile"].eq(label)]
        group_complete = km_eligible.loc[group.index]
        group_hits = group_complete & target_hit.loc[group.index].astype(bool)
        group_censored = group_complete & right_censored.loc[group.index]
        group_incomplete = outcome_missing.loc[group.index]
        r60_group = group.loc[r60_finite.loc[group.index], "r_60"].astype(float)
        km_index = group_complete.index[group_complete]

        km = SurvfuncRight(
            time=duration.loc[km_index].to_numpy(dtype=float),
            status=target_hit.loc[km_index].astype(int).to_numpy(),
        )
        median_time = float(km.quantile(0.5))
        median_reached = bool(np.isfinite(median_time))
        medians[label] = median_time if median_reached else "not reached"

        rows.append(
            {
                "va_quintile": label,
                "va_lower_exclusive": lower_edges[index],
                "va_upper_inclusive": upper_edges[index],
                "event_count": int(len(group)),
                "up_count": int(group["breakout_direction"].eq("upward").sum()),
                "down_count": int(group["breakout_direction"].eq("downward").sum()),
                "target_hit_count": int(group_hits.sum()),
                "hit_rate_denominator": int(group_complete.sum()),
                "hit_rate": float(group_hits.sum() / group_complete.sum()) if group_complete.sum() else np.nan,
                "right_censored_count": int(group_censored.sum()),
                "incomplete_followup_count": int(group_incomplete.sum()),
                "km_median_minutes": median_time if median_reached else np.nan,
                "km_median_status": "reached" if median_reached else "not reached",
                "r60_n": int(len(r60_group)),
                "r60_mean": float(r60_group.mean()) if len(r60_group) else np.nan,
                "r60_sd": float(r60_group.std(ddof=1)) if len(r60_group) > 1 else np.nan,
                "r60_median": float(r60_group.median()) if len(r60_group) else np.nan,
                "r60_q25": float(r60_group.quantile(0.25)) if len(r60_group) else np.nan,
                "r60_q75": float(r60_group.quantile(0.75)) if len(r60_group) else np.nan,
            }
        )
    return pd.DataFrame(rows), medians


def _plot_km(eligible: pd.DataFrame, output_path: Path) -> None:
    figure, axes = plt.subplots(figsize=(10.5, 6.5), constrained_layout=True)
    palette = ("#3d6c8e", "#c26a3a", "#40856f", "#8e6e9f", "#ba9b32")
    durations = pd.to_numeric(eligible["observed_time_minutes"], errors="coerce")
    hits = eligible["target_hit"].astype(bool)
    for label, color in zip(GROUP_LABELS, palette):
        group = eligible.loc[eligible["va_quintile"].eq(label)]
        fitter = SurvfuncRight(
            time=durations.loc[group.index].to_numpy(dtype=float),
            status=hits.loc[group.index].astype(int).to_numpy(),
        )
        line_start = len(axes.lines)
        fitter.plot(ax=axes)
        plotted_lines = axes.lines[line_start:]
        if plotted_lines:
            plotted_lines[0].set_color(color)
            plotted_lines[0].set_label(f"{label} (n={len(group)})")
            for line in plotted_lines[1:]:
                line.set_color(color)
                line.set_label("_nolegend_")

    axes.set_xlim(0, 240)
    axes.set_xticks(np.arange(0, 241, 30))
    axes.set_xlabel("Minutes after breakout close")
    axes.set_ylabel("Probability target not yet reached")
    axes.set_title("Kaplan–Meier time-to-target by VA quintile")
    axes.grid(alpha=0.22)
    axes.legend(title="VA quintile", frameon=False)
    figure.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def _render_report(
    events: pd.DataFrame,
    eligible: pd.DataFrame,
    cut_points: list[float],
    summaries: pd.DataFrame,
    medians: dict[str, object],
) -> str:
    missing = events.loc[events["va_missing"].astype(bool)]
    incomplete_count = int(_boolean(eligible["outcome_missing"]).sum())
    lines = [
        "# Day 3 Block 3: описательные сводки по квинтилям VA",
        "",
        "Область: только подтверждённые пользователем описательные сводки по квинтилям. Spearman, R60 regression, bootstrap, тесты значимости и Cox-модель не запускались.",
        "",
        f"Исходные строки: {len(events)}; строк с конечным валидным VA: {len(eligible)}; строк с missing VA: {len(missing)}.",
        "Missing VA оставлен без изменений, импутация не применялась. Пропуски: UP 22, DOWN 2; причина: `reference_region_outside_historical_range`.",
        "",
        "## Границы квинтилей",
        "",
        "Линейно интерполированные пороги VA (20%, 40%, 60%, 80%): " + ", ".join(f"{value:.12g}" for value in cut_points) + ".",
        "Интервалы правозамкнутые; одинаковые значения не разделялись. Сформировано пять непустых групп по 60 событий.",
        "",
        "## Сводки",
        "",
        "| Квинтиль | События | UP | DOWN | Hits / пригодные | Доля hit | Цензурированы | Неполные | KM-медиана (мин) | R60 n | R60 среднее | R60 SD | R60 медиана | R60 Q25 | R60 Q75 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries.itertuples(index=False):
        median = f"{row.km_median_minutes:.1f}" if row.km_median_status == "reached" else "не достигнута"
        lines.append(
            f"| {row.va_quintile} | {row.event_count} | {row.up_count} | {row.down_count} | "
            f"{row.target_hit_count}/{row.hit_rate_denominator} | {row.hit_rate:.1%} | {row.right_censored_count} | "
            f"{row.incomplete_followup_count} | {median} | {row.r60_n} | {row.r60_mean:.6f} | {row.r60_sd:.6f} | "
            f"{row.r60_median:.6f} | {row.r60_q25:.6f} | {row.r60_q75:.6f} |"
        )
    lines.extend(
        [
            "",
            "KM-медиана указывается только если оценённая кривая достигает 0.5; иначе отмечается `не достигнута`. Полный 240-минутный no-hit цензурируется на 240-й минуте и не считается hit. Неполный follow-up исключён из outcome denominators; число таких строк среди VA-пригодных событий — "
            + str(incomplete_count)
            + ".",
            "",
            "KM-график: `07 Results/figures/day3_block4_04_km_time_to_target_by_va_quintile.png`.",
            "",
            "Это только описательные результаты. Они не проверяют статистическую значимость и не устанавливают ассоциацию или причинный эффект.",
            "",
            "## Отложенная работа",
            "",
            "Spearman, R60 regression, bootstrap confidence intervals, тесты значимости и другие исходы (MFE, MAE, дополнительные returns, Return to Box) не рассчитывались.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> dict[str, object]:
    events, eligible, cut_points = _load_and_group()
    summaries, medians = _summarize(eligible, cut_points)
    km_rows = eligible.loc[
        ~_boolean(eligible["outcome_missing"])
        & pd.to_numeric(eligible["observed_time_minutes"], errors="coerce").notna()
        & eligible["target_hit"].notna()
    ]
    if km_rows.empty:
        raise ValueError("No complete outcome rows are available for the Kaplan-Meier summaries")

    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIGURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    summaries.to_csv(SUMMARY_PATH, index=False, float_format="%.12g")
    _plot_km(km_rows, FIGURE_PATH)
    REPORT_PATH.write_text(
        _render_report(events, eligible, cut_points, summaries, medians),
        encoding="utf-8",
    )
    return {
        "total_events": len(events),
        "valid_va_events": len(eligible),
        "missing_va_events": int(events["va_missing"].astype(bool).sum()),
        "cut_points": cut_points,
        "groups": summaries.to_dict(orient="records"),
        "km_medians": medians,
        "summary_path": SUMMARY_PATH,
        "figure_path": FIGURE_PATH,
        "report_path": REPORT_PATH,
    }


def main() -> int:
    result = run()
    print(f"Events={result['total_events']}; VA valid={result['valid_va_events']}; VA missing={result['missing_va_events']}")
    print("VA quintile cut points:", ", ".join(f"{value:.12g}" for value in result["cut_points"]))
    for row in result["groups"]:
        median = row["km_median_minutes"] if row["km_median_status"] == "reached" else "not reached"
        print(
            f"{row['va_quintile']}: n={row['event_count']} UP={row['up_count']} DOWN={row['down_count']} "
            f"hits={row['target_hit_count']}/{row['hit_rate_denominator']} "
            f"censored={row['right_censored_count']} incomplete={row['incomplete_followup_count']} "
            f"KM median={median} R60 n={row['r60_n']} mean={row['r60_mean']:.6g}"
        )
    for key in ("summary_path", "figure_path", "report_path"):
        print(result[key].relative_to(PROJECT_ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
