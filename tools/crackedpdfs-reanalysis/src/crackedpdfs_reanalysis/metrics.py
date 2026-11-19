"""Metrics with cluster-aware uncertainty for grouped benchmark data."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, f1_score, roc_auc_score

from crackedpdfs_reanalysis.protocols import DOC_COLUMN, ROLE_COLUMN, TRIAD_COLUMN


def point_metrics(y: np.ndarray, scores: np.ndarray, threshold: float) -> dict[str, float]:
    y = np.asarray(y, dtype=int)
    scores = np.asarray(scores, dtype=float)
    predicted = (scores >= threshold).astype(int)
    out: dict[str, float] = {
        "f1": float(f1_score(y, predicted, zero_division=0)),
        "positives": int(y.sum()),
        "negatives": int((1 - y).sum()),
    }
    if 0 < y.sum() < len(y):
        out["roc_auc"] = float(roc_auc_score(y, scores))
        out["pr_auc"] = float(average_precision_score(y, scores))
    return out


def paired_rank(frame: pd.DataFrame, scores: np.ndarray, negative_role: str) -> dict[str, float]:
    """Share of triads whose injected member outscores its matched negative. Ties count half."""
    table = frame[[TRIAD_COLUMN, ROLE_COLUMN]].copy()
    table["score"] = np.asarray(scores, dtype=float)
    injected = table[table[ROLE_COLUMN] == "injected_attack"].set_index(TRIAD_COLUMN)["score"]
    negative = table[table[ROLE_COLUMN] == negative_role].set_index(TRIAD_COLUMN)["score"]
    common = injected.index.intersection(negative.index)
    if len(common) == 0:
        return {"pairs": 0}
    diff = injected.loc[common].to_numpy() - negative.loc[common].to_numpy()
    wins = float(((diff > 0).sum() + 0.5 * (diff == 0).sum()) / len(common))
    return {
        "pairs": int(len(common)),
        "accuracy": wins,
        "ties": int((diff == 0).sum()),
        "reversed": int((diff < 0).sum()),
    }


def cluster_bootstrap(
    frame: pd.DataFrame,
    scores: np.ndarray,
    threshold: float,
    group_column: str,
    iterations: int = 1000,
    random_state: int = 42,
) -> dict[str, dict[str, float]]:
    """Percentile intervals from resampling whole groups with replacement.

    Rows that share a group (for example every PDF of one base document, or
    every PDF built from one payload) move together, which is what makes the
    interval honest when rows inside a group are correlated.
    """
    rng = np.random.default_rng(random_state)
    y = frame["label"].astype(int).to_numpy()
    scores = np.asarray(scores, dtype=float)
    groups = frame[group_column].astype(str).to_numpy()
    unique, inverse = np.unique(groups, return_inverse=True)
    members = [np.flatnonzero(inverse == g) for g in range(len(unique))]
    samples: dict[str, list[float]] = {"f1": [], "roc_auc": [], "pr_auc": []}
    for _ in range(iterations):
        chosen = rng.integers(0, len(unique), size=len(unique))
        index = np.concatenate([members[g] for g in chosen])
        yb, sb = y[index], scores[index]
        if yb.sum() == 0 or yb.sum() == len(yb):
            continue
        samples["f1"].append(float(f1_score(yb, (sb >= threshold).astype(int), zero_division=0)))
        samples["roc_auc"].append(float(roc_auc_score(yb, sb)))
        samples["pr_auc"].append(float(average_precision_score(yb, sb)))
    out: dict[str, dict[str, float]] = {}
    for name, values in samples.items():
        if values:
            arr = np.asarray(values)
            out[name] = {
                "ci95_low": float(np.percentile(arr, 2.5)),
                "ci95_high": float(np.percentile(arr, 97.5)),
                "samples": len(values),
            }
    return out


def paired_rank_bootstrap(
    frame: pd.DataFrame,
    scores: np.ndarray,
    negative_role: str,
    group_column: str,
    iterations: int = 1000,
    random_state: int = 42,
) -> dict[str, float]:
    """Cluster bootstrap of paired-ranking accuracy, resampling groups of triads."""
    rng = np.random.default_rng(random_state)
    table = frame[[TRIAD_COLUMN, ROLE_COLUMN, group_column]].copy()
    table["score"] = np.asarray(scores, dtype=float)
    injected = table[table[ROLE_COLUMN] == "injected_attack"].set_index(TRIAD_COLUMN)
    negative = table[table[ROLE_COLUMN] == negative_role].set_index(TRIAD_COLUMN)["score"]
    common = injected.index.intersection(negative.index)
    if len(common) == 0:
        return {}
    diff = injected.loc[common, "score"].to_numpy() - negative.loc[common].to_numpy()
    wins = (diff > 0).astype(float) + 0.5 * (diff == 0)
    groups = injected.loc[common, group_column].astype(str).to_numpy()
    unique, inverse = np.unique(groups, return_inverse=True)
    members = [np.flatnonzero(inverse == g) for g in range(len(unique))]
    values = []
    for _ in range(iterations):
        chosen = rng.integers(0, len(unique), size=len(unique))
        index = np.concatenate([members[g] for g in chosen])
        values.append(float(wins[index].mean()))
    arr = np.asarray(values)
    return {
        "ci95_low": float(np.percentile(arr, 2.5)),
        "ci95_high": float(np.percentile(arr, 97.5)),
        "samples": len(values),
    }


def effective_sample_size(frame: pd.DataFrame, group_column: str = DOC_COLUMN) -> dict[str, float]:
    """Design-effect adjusted sample size for a proportion over clustered rows.

    DEFF = 1 + (m - 1) * ICC, with m the mean cluster size; ICC is estimated
    as the share of label variance between clusters. Reported alongside the
    raw count so Wilson intervals can be computed on n / DEFF.
    """
    y = frame["label"].astype(float)
    groups = frame[group_column].astype(str)
    cluster_means = y.groupby(groups).mean()
    sizes = y.groupby(groups).size()
    total_var = float(y.var(ddof=0)) or 1e-12
    between_var = float(((cluster_means - y.mean()) ** 2 * sizes).sum() / len(y))
    icc = max(0.0, min(1.0, between_var / total_var))
    m = float(sizes.mean())
    deff = 1.0 + (m - 1.0) * icc
    return {
        "n": int(len(y)),
        "clusters": int(len(sizes)),
        "mean_cluster_size": m,
        "icc": icc,
        "deff": deff,
        "n_effective": float(len(y) / deff),
    }


def summarize(results: list[dict[str, Any]], key: str) -> dict[str, float]:
    values = [float(r[key]) for r in results if key in r and r[key] is not None]
    if not values:
        return {}
    arr = np.asarray(values)
    return {"mean": float(arr.mean()), "std": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0, "n": len(arr)}


def best_f1_threshold(y: np.ndarray, scores: np.ndarray) -> float:
    """Lowest threshold that maximises F1, over the unique scores plus 0.5.

    Same candidate set and tie rule as ``src.eval.metrics.select_best_threshold``
    (candidates ascending, first maximum wins), computed from cumulative counts
    instead of a full metric recomputation per candidate.
    """
    y = np.asarray(y, dtype=int)
    scores = np.asarray(scores, dtype=float)
    candidates = np.unique(np.concatenate([scores, [0.5]]))
    order = np.argsort(scores, kind="stable")
    sorted_scores = scores[order]
    sorted_y = y[order]
    total_pos = int(y.sum())
    # Number of rows with score < candidate: predictions below threshold are negative.
    below = np.searchsorted(sorted_scores, candidates, side="left")
    pos_below = np.concatenate([[0], np.cumsum(sorted_y)])[below]
    tp = total_pos - pos_below
    predicted_pos = len(scores) - below
    fp = predicted_pos - tp
    fn = total_pos - tp
    denominator = 2 * tp + fp + fn
    f1 = np.where(denominator > 0, 2 * tp / np.maximum(denominator, 1), 0.0)
    return float(candidates[int(np.argmax(f1))])
