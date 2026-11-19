"""Run the paper v1 re-analysis protocols end to end.

Three experiments share one data load and one set of model factories:

frozen      the published base-document split, retrained from the frozen
            feature table and a persisted text cache, with cluster bootstrap
            intervals by base document and by payload;
both_out    five folds over documents and payloads held out independently,
            scored on the C2, C2p, and C3 cells;
family      leave-one-attack-family-out with every detector, including the
            hybrid, under one named protocol.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from crackedpdfs_reanalysis.detector import ARTIFACTS_DIR, TABLES_DIR, frozen_config, package_config
from crackedpdfs_reanalysis.metrics import (
    best_f1_threshold,
    cluster_bootstrap,
    effective_sample_size,
    paired_rank,
    paired_rank_bootstrap,
    point_metrics,
)
from crackedpdfs_reanalysis.models import (
    HybridScorer,
    LogRegScorer,
    TextScorer,
    XgbScorer,
    load_yaml,
    sanitized_text,
)
from crackedpdfs_reanalysis.protocols import (
    DOC_COLUMN,
    PAYLOAD_COLUMN,
    assign_folds,
    both_out_fold,
    carve_validation,
    family_holdout,
)

MODEL_SPECS: dict[str, tuple[str, Path]] = {
    # name: (kind, training config). Text models get a sanitized text column
    # named after the config they use, so sanitizer variants can run side by side.
    "hybrid": ("hybrid", frozen_config("model_hybrid_hard_provenance.yaml")),
    "text_tfidf": ("text", frozen_config("model_text_tfidf_hard_provenance.yaml")),
    "logreg_shortcut_free": ("logreg", frozen_config("model_logreg_hard_provenance_shortcut_free.yaml")),
    "xgb_shortcut_free": ("xgb", frozen_config("model_xgb_hard_provenance_shortcut_free.yaml")),
    "hybrid_symmetric_sanitizer": ("hybrid", package_config("model_hybrid_symmetric_sanitizer.yaml")),
    "text_tfidf_symmetric_sanitizer": ("text", package_config("model_text_tfidf_symmetric_sanitizer.yaml")),
}
MODEL_NAMES = ["hybrid", "text_tfidf", "logreg_shortcut_free", "xgb_shortcut_free"]


def text_column_for(name: str) -> str:
    return f"text::{name}"


FAMILIES = [
    "steganographic_acrostic",
    "microglyph_steganography",
    "semantic_fragmentation",
    "layout_mimicry",
    "margin_microtext",
    "in_page_low_contrast_text",
]


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def load_frame(
    features_path: str,
    labels_path: str,
    text_cache_path: str,
    configs: dict[str, dict[str, Any]],
    models: list[str],
) -> pd.DataFrame:
    features = pd.read_parquet(features_path)
    labels = pd.read_parquet(labels_path)
    text = pd.read_parquet(text_cache_path)[["pdf_id", "raw_text"]]
    frame = labels.merge(features, on="pdf_id", how="inner", validate="one_to_one")
    frame = frame.merge(text, on="pdf_id", how="left", validate="one_to_one")
    if frame["raw_text"].isna().any():
        raise ValueError("Every PDF needs a text cache row.")
    for name in models:
        if MODEL_SPECS[name][0] in ("hybrid", "text"):
            log(f"sanitizing text with the {name} configuration")
            frame[text_column_for(name)] = sanitized_text(frame["raw_text"], configs[name]["text_tfidf"])
    return frame


def fit_model(
    name: str, configs: dict[str, dict[str, Any]], train: pd.DataFrame, val: pd.DataFrame
) -> tuple[Any, float, dict[str, Any]]:
    """Fit on train, pick a threshold (and C for logreg) on val, refit on train+val."""
    y_train = train["label"].astype(int).to_numpy()
    y_val = val["label"].astype(int).to_numpy()
    both = pd.concat([train, val], ignore_index=True)
    y_both = both["label"].astype(int).to_numpy()
    extra: dict[str, Any] = {}
    kind = MODEL_SPECS[name][0]
    if kind == "hybrid":
        model = HybridScorer(configs[name], text_column_for(name)).fit(train, y_train)
    elif kind == "text":
        model = TextScorer(configs[name], text_column_for(name)).fit(train, y_train)
    elif kind == "logreg":
        cfg = configs[name]
        best = None
        for c_value in [float(v) for v in cfg.get("logreg", {}).get("c_values", [1.0])]:
            candidate = LogRegScorer(cfg, c_value).fit(train, y_train)
            val_scores = candidate.score(val)
            chosen_threshold = best_f1_threshold(y_val, val_scores)
            chosen_f1 = point_metrics(y_val, val_scores, chosen_threshold)["f1"]
            if best is None or chosen_f1 > best[1]:
                best = (candidate, chosen_f1, c_value)
        assert best is not None
        model, extra["c_value"] = best[0], best[2]
    elif kind == "xgb":
        model = XgbScorer(configs[name]).warm_fit(train, y_train, val, y_val)
        extra["n_estimators"] = model.n_estimators
    else:
        raise ValueError(name)
    threshold = best_f1_threshold(y_val, model.score(val))
    if kind == "logreg":
        model = LogRegScorer(configs[name], extra["c_value"]).fit(both, y_both)
    else:
        model.fit(both, y_both)
    return model, threshold, extra


def score_cell(
    model: Any, threshold: float, cell: pd.DataFrame, *, bootstrap: int, label: str
) -> dict[str, Any]:
    scores = model.score(cell)
    y = cell["label"].astype(int).to_numpy()
    out: dict[str, Any] = {
        "cell": label,
        "rows": int(len(cell)),
        "threshold": threshold,
        **point_metrics(y, scores, threshold),
    }
    out["paired_rank_vs_confounder"] = paired_rank(cell, scores, "benign_confounder")
    out["paired_rank_vs_original"] = paired_rank(cell, scores, "benign_original")
    if bootstrap:
        out["bootstrap_by_document"] = cluster_bootstrap(
            cell, scores, threshold, DOC_COLUMN, iterations=bootstrap
        )
        injected_payload = (
            cell[PAYLOAD_COLUMN]
            .astype(str)
            .where(cell["label"].astype(int) == 1, "benign:" + cell[DOC_COLUMN].astype(str))
        )
        cell_payload = cell.assign(_payload_group=injected_payload)
        out["bootstrap_by_payload"] = cluster_bootstrap(
            cell_payload, scores, threshold, "_payload_group", iterations=bootstrap
        )
        out["paired_rank_vs_confounder"]["bootstrap_by_document"] = paired_rank_bootstrap(
            cell, scores, "benign_confounder", DOC_COLUMN, iterations=bootstrap
        )
        out["effective_sample_size_by_document"] = effective_sample_size(cell, DOC_COLUMN)
    return out


def run_frozen(
    frame: pd.DataFrame,
    splits: dict[str, Any],
    configs: dict[str, dict[str, Any]],
    models: list[str],
    bootstrap: int,
) -> dict[str, Any]:
    by_id = frame.set_index("pdf_id", drop=False)
    train = by_id.loc[splits["train_ids"]].reset_index(drop=True)
    val = by_id.loc[splits["val_ids"]].reset_index(drop=True)
    test = by_id.loc[splits["test_ids"]].reset_index(drop=True)
    out: dict[str, Any] = {}
    for name in models:
        log(f"frozen: fitting {name}")
        model, threshold, extra = fit_model(name, configs, train, val)
        out[name] = {**score_cell(model, threshold, test, bootstrap=bootstrap, label="frozen_test"), **extra}
        if hasattr(model, "top_weights"):
            out[name]["top_weights"] = model.top_weights()
        log(f"frozen: {name} f1={out[name]['f1']:.4f} roc_auc={out[name].get('roc_auc', float('nan')):.4f}")
    return out


def run_both_out(
    frame: pd.DataFrame, configs: dict[str, dict[str, Any]], models: list[str], n_folds: int, bootstrap: int
) -> dict[str, Any]:
    assignment = assign_folds(frame, n_folds=n_folds)
    out: dict[str, Any] = {
        "n_folds": n_folds,
        "folds": [],
        "assignment": {"documents_per_fold": {}, "payloads_per_fold": {}},
    }
    for fold in range(n_folds):
        out["assignment"]["documents_per_fold"][fold] = sum(
            1 for v in assignment.doc_fold.values() if v == fold
        )
        out["assignment"]["payloads_per_fold"][fold] = sum(
            1 for v in assignment.payload_fold.values() if v == fold
        )
    pooled: dict[str, dict[str, list[pd.DataFrame]]] = {
        name: {"C2": [], "C2p": [], "C3": []} for name in models
    }
    for fold in range(n_folds):
        cells = both_out_fold(frame, assignment, fold)
        train, val = carve_validation(cells["train"], random_state=42 + fold)
        record: dict[str, Any] = {
            "fold": fold,
            "train_rows": int(len(train)),
            "val_rows": int(len(val)),
            "cells": {k: int(len(v)) for k, v in cells.items() if k != "train"},
            "models": {},
        }
        for name in models:
            log(f"both_out fold {fold}: fitting {name}")
            model, threshold, extra = fit_model(name, configs, train, val)
            record["models"][name] = {"threshold": threshold, **extra}
            for cell_name in ("C2", "C2p", "C3"):
                cell = cells[cell_name]
                result = score_cell(model, threshold, cell, bootstrap=0, label=cell_name)
                record["models"][name][cell_name] = result
                pooled[name][cell_name].append(cell.assign(_score=model.score(cell), _threshold=threshold))
                log(
                    f"both_out fold {fold}: {name} {cell_name} f1={result['f1']:.4f} roc_auc={result.get('roc_auc', float('nan')):.4f} pair={result['paired_rank_vs_confounder'].get('accuracy', float('nan')):.3f}"
                )
        out["folds"].append(record)
    out["pooled"] = {}
    for name in models:
        out["pooled"][name] = {}
        for cell_name in ("C2", "C2p", "C3"):
            pooled_frame = pd.concat(pooled[name][cell_name], ignore_index=True)
            scores = pooled_frame["_score"].to_numpy()
            predicted = (scores >= pooled_frame["_threshold"].to_numpy()).astype(int)
            y = pooled_frame["label"].astype(int).to_numpy()
            from sklearn.metrics import average_precision_score, f1_score, roc_auc_score

            entry: dict[str, Any] = {
                "rows": int(len(pooled_frame)),
                "f1": float(f1_score(y, predicted, zero_division=0)),
                "roc_auc": float(roc_auc_score(y, scores)),
                "pr_auc": float(average_precision_score(y, scores)),
                "paired_rank_vs_confounder": paired_rank(pooled_frame, scores, "benign_confounder"),
                "paired_rank_vs_original": paired_rank(pooled_frame, scores, "benign_original"),
            }
            if bootstrap:
                # Per-fold thresholds differ, so bootstrap F1 on the per-row decisions.
                entry["bootstrap_by_document"] = _pooled_bootstrap(
                    pooled_frame, scores, predicted, DOC_COLUMN, bootstrap
                )
                payload_group = (
                    pooled_frame[PAYLOAD_COLUMN]
                    .astype(str)
                    .where(y == 1, "benign:" + pooled_frame[DOC_COLUMN].astype(str))
                )
                entry["bootstrap_by_payload"] = _pooled_bootstrap(
                    pooled_frame.assign(_g=payload_group), scores, predicted, "_g", bootstrap
                )
                entry["paired_rank_vs_confounder"]["bootstrap_by_document"] = paired_rank_bootstrap(
                    pooled_frame, scores, "benign_confounder", DOC_COLUMN, iterations=bootstrap
                )
            out["pooled"][name][cell_name] = entry
    return out


def _pooled_bootstrap(
    frame: pd.DataFrame, scores: np.ndarray, predicted: np.ndarray, group_column: str, iterations: int
) -> dict[str, dict[str, float]]:
    from sklearn.metrics import average_precision_score, f1_score, roc_auc_score

    rng = np.random.default_rng(42)
    y = frame["label"].astype(int).to_numpy()
    groups = frame[group_column].astype(str).to_numpy()
    unique, inverse = np.unique(groups, return_inverse=True)
    members = [np.flatnonzero(inverse == g) for g in range(len(unique))]
    samples: dict[str, list[float]] = {"f1": [], "roc_auc": [], "pr_auc": []}
    for _ in range(iterations):
        chosen = rng.integers(0, len(unique), size=len(unique))
        index = np.concatenate([members[g] for g in chosen])
        yb = y[index]
        if yb.sum() == 0 or yb.sum() == len(yb):
            continue
        samples["f1"].append(float(f1_score(yb, predicted[index], zero_division=0)))
        samples["roc_auc"].append(float(roc_auc_score(yb, scores[index])))
        samples["pr_auc"].append(float(average_precision_score(yb, scores[index])))
    return {
        k: {
            "ci95_low": float(np.percentile(v, 2.5)),
            "ci95_high": float(np.percentile(v, 97.5)),
            "samples": len(v),
        }
        for k, v in samples.items()
        if v
    }


def run_family(
    frame: pd.DataFrame,
    configs: dict[str, dict[str, Any]],
    models: list[str],
    families: list[str],
    bootstrap: int,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for family in families:
        parts = family_holdout(frame, family)
        train, val = carve_validation(parts["train"])
        test = parts["test"]
        family_rows = test[(test["attack_family"].astype(str) == family) | (test["label"].astype(int) == 0)]
        family_pairs = test[
            test["triad_id"].isin(test.loc[test["attack_family"].astype(str) == family, "triad_id"])
        ]
        out[family] = {
            "test_rows": int(len(test)),
            "family_injected": int((test["attack_family"].astype(str) == family).sum()),
            "models": {},
        }
        for name in models:
            log(f"family {family}: fitting {name}")
            model, threshold, extra = fit_model(name, configs, train, val)
            scores_family = model.score(family_rows)
            target = point_metrics(family_rows["label"].astype(int).to_numpy(), scores_family, threshold)
            pair_scores = model.score(family_pairs)
            entry: dict[str, Any] = {
                "threshold": threshold,
                **extra,
                "target_family_vs_all_test_negatives": target,
                "paired_rank_vs_confounder": paired_rank(family_pairs, pair_scores, "benign_confounder"),
                "paired_rank_vs_original": paired_rank(family_pairs, pair_scores, "benign_original"),
            }
            if bootstrap:
                entry["paired_rank_vs_confounder"]["bootstrap_by_document"] = paired_rank_bootstrap(
                    family_pairs, pair_scores, "benign_confounder", DOC_COLUMN, iterations=bootstrap
                )
                entry["target_family_bootstrap_by_document"] = cluster_bootstrap(
                    family_rows, scores_family, threshold, DOC_COLUMN, iterations=bootstrap
                )
            out[family]["models"][name] = entry
            log(
                f"family {family}: {name} target_f1={target['f1']:.3f} pair={entry['paired_rank_vs_confounder'].get('accuracy', float('nan')):.3f}"
            )
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--features", default=str(TABLES_DIR / "features.parquet"))
    parser.add_argument("--labels", default=str(TABLES_DIR / "labels.parquet"))
    parser.add_argument("--splits", default=str(TABLES_DIR / "splits.json"))
    parser.add_argument("--text-cache", default=str(TABLES_DIR / "text_cache.parquet"))
    parser.add_argument("--out", default=str(ARTIFACTS_DIR / "reanalysis"))
    parser.add_argument("--experiments", default="frozen,both_out,family")
    parser.add_argument("--models", default=",".join(MODEL_NAMES))
    parser.add_argument("--families", default=",".join(FAMILIES))
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--bootstrap", type=int, default=1000)
    args = parser.parse_args(argv)

    models = [m for m in args.models.split(",") if m]
    unknown = [m for m in models if m not in MODEL_SPECS]
    if unknown:
        raise SystemExit(f"Unknown models: {unknown}. Known: {sorted(MODEL_SPECS)}")
    configs = {name: load_yaml(MODEL_SPECS[name][1]) for name in models}
    experiments = [e for e in args.experiments.split(",") if e]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    log("loading tables")
    frame = load_frame(args.features, args.labels, args.text_cache, configs, models)
    with open(args.splits, encoding="utf-8") as handle:
        splits = json.load(handle)

    results: dict[str, Any] = {
        "models": models,
        "model_specs": {m: (MODEL_SPECS[m][0], str(MODEL_SPECS[m][1])) for m in models},
        "configs": configs,
    }
    if "frozen" in experiments:
        results["frozen"] = run_frozen(frame, splits, configs, models, args.bootstrap)
        _dump(out_dir / "frozen.json", results["frozen"])
    if "both_out" in experiments:
        results["both_out"] = run_both_out(frame, configs, models, args.folds, args.bootstrap)
        _dump(out_dir / "both_out.json", results["both_out"])
    if "family" in experiments:
        results["family"] = run_family(
            frame, configs, models, [f for f in args.families.split(",") if f], args.bootstrap
        )
        _dump(out_dir / "family.json", results["family"])
    _dump(out_dir / "reanalysis.json", results)
    log(f"wrote {out_dir}")
    return 0


def _dump(path: Path, payload: Any) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=_json_default)


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
