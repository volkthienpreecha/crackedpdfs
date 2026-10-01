"""Aggregate the external-baseline per-file CSVs into ``summary.json`` and ``summary.md``.

For each ``<name>_per_file.csv`` in the artifact directory the script reports, on the full test
split and on the paired subset (injected versus benign_confounder only): accuracy, precision,
recall and F1 with ``flagged`` as the positive prediction, and ROC-AUC using ``score`` as a
continuous ranking (ties contribute one half). It also reports paired ranking accuracy (the
injected member of each triad scores strictly above its matched confounder, with ties counting one
half), flag rates per ``pdf_role`` and per ``attack_family``, error and timeout counts, and the run
metadata recorded by each driver (commit, version, command line, wall-clock time).

The script depends only on the standard library.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict
from pathlib import Path

WORK_ROOT = Path(os.environ.get("CRACKEDPDFS_WORK", Path.home() / "crackedpdfs-work")).resolve()
ARTIFACT_DIR = (
    Path(__file__).resolve().parents[3]
    / ".cache"
    / "crackedpdfs-reanalysis"
    / "artifacts"
    / "external_baselines"
)
SPLIT_PATH = WORK_ROOT / "v1" / "test_split.csv"
DETECTOR_ORDER = [
    "phantomlint",
    "phantomlint_passthrough",
    "hidden_text_detector",
    "pdf_injection_scanner",
    "hiddencontent_structural",
    "hiddencontent_vision",
]


def load_rows(path: Path) -> list[dict]:
    """Read a CSV into dictionaries with numeric fields converted."""
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["label"] = int(row["label"])
        if "flagged" in row:
            row["flagged"] = int(row["flagged"])
            row["score"] = float(row["score"])
            row["seconds"] = float(row["seconds"])
    return rows


def classification_metrics(rows: list[dict]) -> dict:
    """Accuracy, precision, recall, F1 with ``flagged`` as the positive prediction."""
    tp = sum(1 for r in rows if r["label"] == 1 and r["flagged"] == 1)
    fp = sum(1 for r in rows if r["label"] == 0 and r["flagged"] == 1)
    tn = sum(1 for r in rows if r["label"] == 0 and r["flagged"] == 0)
    fn = sum(1 for r in rows if r["label"] == 1 and r["flagged"] == 0)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "n": len(rows),
        "positives": tp + fn,
        "negatives": fp + tn,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "accuracy": (tp + tn) / len(rows) if rows else 0.0,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "roc_auc": roc_auc(rows),
    }


def roc_auc(rows: list[dict]) -> float | None:
    """ROC-AUC via the rank-sum (Mann-Whitney) formulation; ties count one half."""
    positives = [r["score"] for r in rows if r["label"] == 1]
    negatives = [r["score"] for r in rows if r["label"] == 0]
    if not positives or not negatives:
        return None
    scored = sorted(positives + negatives)
    ranks: dict[float, float] = {}
    idx = 0
    while idx < len(scored):
        end = idx
        while end + 1 < len(scored) and scored[end + 1] == scored[idx]:
            end += 1
        ranks[scored[idx]] = (idx + end) / 2 + 1  # average rank, 1-based
        idx = end + 1
    rank_sum = sum(ranks[s] for s in positives)
    n_pos, n_neg = len(positives), len(negatives)
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def paired_ranking_accuracy(rows: list[dict], split: dict[str, dict]) -> dict:
    """Fraction of triads where the injected score exceeds the matched confounder score (ties count one half)."""
    by_triad: dict[str, dict[str, float]] = defaultdict(dict)
    for row in rows:
        meta = split[row["pdf_id"]]
        by_triad[meta["triad_id"]][meta["pdf_role"]] = row["score"]
    wins = ties = total = 0
    for roles in by_triad.values():
        if "injected_attack" not in roles or "benign_confounder" not in roles:
            continue
        total += 1
        if roles["injected_attack"] > roles["benign_confounder"]:
            wins += 1
        elif roles["injected_attack"] == roles["benign_confounder"]:
            ties += 1
    return {
        "pairs": total,
        "wins": wins,
        "ties": ties,
        "accuracy": (wins + 0.5 * ties) / total if total else None,
    }


def flag_rates(rows: list[dict], key: str) -> dict[str, dict]:
    """Flag rate grouped by ``key``."""
    groups: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row["flagged"])
    return {
        name: {"n": len(flags), "flagged": sum(flags), "rate": sum(flags) / len(flags)}
        for name, flags in sorted(groups.items())
    }


def technique_counts(rows: list[dict]) -> dict[str, int]:
    """Count how often each technique string component appears among flagged files."""
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        if row["flagged"] and row["techniques"]:
            for part in row["techniques"].split("|"):
                counts[part] += 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def summarise_detector(name: str, rows: list[dict], split: dict[str, dict], run_meta: dict) -> dict:
    """Build the full summary block for one detector."""
    paired_rows = [r for r in rows if r["pdf_role"] in ("injected_attack", "benign_confounder")]
    timeouts = sum(1 for r in rows if r["error"] == "timeout")
    errors = sum(1 for r in rows if r["error"] and r["error"] != "timeout")
    seconds = [r["seconds"] for r in rows]
    return {
        "detector": name,
        "run": run_meta,
        "full_split": classification_metrics(rows),
        "paired_subset": classification_metrics(paired_rows),
        "paired_ranking": paired_ranking_accuracy(rows, split),
        "flag_rate_by_pdf_role": flag_rates(rows, "pdf_role"),
        "flag_rate_by_attack_family": flag_rates(
            [r for r in rows if r["pdf_role"] == "injected_attack"], "attack_family"
        ),
        "techniques_among_flagged": technique_counts(rows),
        "errors": errors,
        "timeouts": timeouts,
        "seconds_per_file_mean": sum(seconds) / len(seconds) if seconds else None,
        "seconds_per_file_max": max(seconds) if seconds else None,
    }


def fmt(value: float | None, digits: int = 3) -> str:
    """Format a metric for Markdown."""
    return "n/a" if value is None else f"{value:.{digits}f}"


def render_markdown(summary: dict) -> str:
    """Render the summary as Markdown."""
    lines = ["# External hidden-text detector baselines", ""]
    split = summary["split"]
    lines.append(
        "Independently written open-source detectors run unmodified over the paper v1 frozen test split "
        f"({split['n']} PDFs, {split['injected']} injected, {split['benign_confounder']} benign confounders, "
        f"{split['benign_original']} benign originals). `flagged` is the positive prediction; ROC-AUC uses each "
        "detector's numeric `score` (ties count one half). Scoring rules are documented in each driver's docstring "
        "and in the `run` block of `summary.json`. Rows whose coverage is a triad subsample (see Run details) report "
        "metrics on that subsample only; paired metrics remain valid because sampling is by triad."
    )
    lines.append("")
    lines.append("## Headline metrics")
    lines.append("")
    lines.append("| Detector | Subset | n | Acc | Prec | Rec | F1 | ROC-AUC |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for det in summary["detectors"]:
        for subset_key, subset_name in (
            ("full_split", "full test split"),
            ("paired_subset", "injected vs confounder"),
        ):
            m = det[subset_key]
            cells = [det["detector"], subset_name, str(m["n"]), fmt(m["accuracy"]), fmt(m["precision"])]
            cells += [fmt(m["recall"]), fmt(m["f1"]), fmt(m["roc_auc"])]
            lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## Paired ranking accuracy")
    lines.append("")
    lines.append(
        "Score of the injected PDF strictly above its matched benign confounder within the same triad; "
        "ties count one half."
    )
    lines.append("")
    lines.append("| Detector | Pairs | Wins | Ties | Accuracy |")
    lines.append("|---|---|---|---|---|")
    for det in summary["detectors"]:
        p = det["paired_ranking"]
        lines.append(
            f"| {det['detector']} | {p['pairs']} | {p['wins']} | {p['ties']} | {fmt(p['accuracy'])} |"
        )
    lines.append("")
    lines.append("## Flag rate by PDF role")
    lines.append("")
    roles = sorted({role for det in summary["detectors"] for role in det["flag_rate_by_pdf_role"]})
    lines.append("| Detector | " + " | ".join(roles) + " |")
    lines.append("|---|" + "---|" * len(roles))
    for det in summary["detectors"]:
        rates = det["flag_rate_by_pdf_role"]
        cells = [
            f"{rates[r]['rate']:.3f} ({rates[r]['flagged']}/{rates[r]['n']})" if r in rates else "n/a"
            for r in roles
        ]
        lines.append(f"| {det['detector']} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## Flag rate by attack family (injected PDFs only)")
    lines.append("")
    families = sorted({f for det in summary["detectors"] for f in det["flag_rate_by_attack_family"]})
    lines.append(
        "| Attack family | n | " + " | ".join(det["detector"] for det in summary["detectors"]) + " |"
    )
    lines.append("|---|---|" + "---|" * len(summary["detectors"]))
    for family in families:
        n = next(
            (
                det["flag_rate_by_attack_family"][family]["n"]
                for det in summary["detectors"]
                if family in det["flag_rate_by_attack_family"]
            ),
            0,
        )
        cells = [
            fmt(det["flag_rate_by_attack_family"].get(family, {}).get("rate")) for det in summary["detectors"]
        ]
        lines.append(f"| {family} | {n} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## Techniques reported among flagged files")
    lines.append("")
    for det in summary["detectors"]:
        lines.append(
            f"- {det['detector']}: "
            + (", ".join(f"{k} ({v})" for k, v in det["techniques_among_flagged"].items()) or "none")
        )
    lines.append("")
    lines.append("## Run details")
    lines.append("")
    lines.append(
        "| Detector | Files | Coverage | Commit | Version | Python | Workers | Wall clock (s) | Mean s/file "
        "| Max s/file | Errors | Timeouts |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for det in summary["detectors"]:
        run = det["run"]
        cells = [
            det["detector"],
            str(det["full_split"]["n"]),
            run.get("subsample", "full test split"),
            f"`{run.get('commit', 'unknown')[:12]}`",
            run.get("version", "unknown"),
            run.get("python", "unknown"),
            str(run.get("workers", "n/a")),
            str(run.get("wall_clock_seconds", "n/a")),
            fmt(det["seconds_per_file_mean"], 2),
            fmt(det["seconds_per_file_max"], 1),
            str(det["errors"]),
            str(det["timeouts"]),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("Command lines:")
    lines.append("")
    for det in summary["detectors"]:
        lines.append(f"- {det['detector']}: `{det['run'].get('command_template', 'unknown')}`")
        lines.append(f"  - flag rule: {det['run'].get('flag_rule', 'unknown')}")
        lines.append(f"  - score rule: {det['run'].get('score_rule', 'unknown')}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--artifact-dir", type=Path, default=ARTIFACT_DIR)
    parser.add_argument("--split", type=Path, default=SPLIT_PATH)
    args = parser.parse_args()

    split_rows = load_rows(args.split)
    split = {r["pdf_id"]: r for r in split_rows}
    detectors = []
    available = {p.name[: -len("_per_file.csv")]: p for p in args.artifact_dir.glob("*_per_file.csv")}
    # Only the detectors produced by the drivers in this directory are summarised; other per-file
    # tables that may share the artifact directory use different column layouts.
    for name in [n for n in DETECTOR_ORDER if n in available]:
        rows = load_rows(available[name])
        run_path = args.artifact_dir / f"{name}_run.json"
        run_meta = json.loads(run_path.read_text(encoding="utf-8")) if run_path.exists() else {}
        detectors.append(summarise_detector(name, rows, split, run_meta))

    summary = {
        "split": {
            "path": str(args.split),
            "n": len(split_rows),
            "injected": sum(1 for r in split_rows if r["pdf_role"] == "injected_attack"),
            "benign_confounder": sum(1 for r in split_rows if r["pdf_role"] == "benign_confounder"),
            "benign_original": sum(1 for r in split_rows if r["pdf_role"] == "benign_original"),
        },
        "detectors": detectors,
    }
    (args.artifact_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (args.artifact_dir / "summary.md").write_text(render_markdown(summary), encoding="utf-8")
    print(render_markdown(summary))


if __name__ == "__main__":
    main()
