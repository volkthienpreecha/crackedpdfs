"""Measure what the text sanitizer leaves behind for each member of a triad.

For every confounder and injected PDF, the script computes the characters
added relative to the benign original before and after sanitization, then
reports how well the residual length alone separates the two roles. A large
gap means the sanitizer, not the detector, is doing the discrimination.

Usage:
    crackedpdfs-reanalysis sanitizer-residual
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from sklearn.metrics import roc_auc_score

from crackedpdfs_reanalysis.detector import ARTIFACTS_DIR, TABLES_DIR, frozen_config
from crackedpdfs_reanalysis.sanitizer import build_preprocessing, sanitize

_PRE: dict[str, Any] | None = None


def _init(pre: dict[str, Any]) -> None:
    global _PRE
    _PRE = pre


def _clean_len(text: str) -> int:
    assert _PRE is not None
    return len(sanitize(text, _PRE))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--labels", default=str(TABLES_DIR / "labels.parquet"))
    parser.add_argument("--text-cache", default=str(TABLES_DIR / "text_cache.parquet"))
    parser.add_argument("--config", default=str(frozen_config("model_hybrid_hard_provenance.yaml")))
    parser.add_argument("--out", default=str(ARTIFACTS_DIR / "sanitizer_residual"))
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)

    with open(args.config, encoding="utf-8") as handle:
        text_cfg = yaml.safe_load(handle)["text_tfidf"]
    pre = build_preprocessing(text_cfg)
    labels = pd.read_parquet(args.labels)
    text = pd.read_parquet(args.text_cache)[["pdf_id", "raw_text"]]
    frame = labels.merge(text, on="pdf_id", how="inner", validate="one_to_one")
    with ProcessPoolExecutor(max_workers=args.workers, initializer=_init, initargs=(pre,)) as pool:
        frame["clean_len"] = list(pool.map(_clean_len, frame["raw_text"].astype(str).tolist(), chunksize=256))
    frame["raw_len"] = frame["raw_text"].str.len()
    original = frame[frame["pdf_role"] == "benign_original"].set_index("triad_id")
    members = frame[frame["pdf_role"] != "benign_original"].copy()
    members["added_raw"] = members["raw_len"] - members["triad_id"].map(original["raw_len"])
    members["added_clean"] = members["clean_len"] - members["triad_id"].map(original["clean_len"])
    members["family"] = members["attack_family"].where(
        members["pdf_role"] == "injected_attack", members["benign_confounder_family"]
    )

    y = (members["pdf_role"] == "injected_attack").astype(int).to_numpy()
    rule_accuracy = {}
    for cutoff in (10, 20, 40):
        predicted = (members["added_clean"] > cutoff).astype(int).to_numpy()
        rule_accuracy[f"added_clean_gt_{cutoff}"] = float((predicted == y).mean())
    injected = members[members["pdf_role"] == "injected_attack"].set_index("triad_id")["added_clean"]
    confounder = members[members["pdf_role"] == "benign_confounder"].set_index("triad_id")["added_clean"]
    common = injected.index.intersection(confounder.index)
    diff = injected.loc[common] - confounder.loc[common]
    pair = {
        "pairs": int(len(common)),
        "injected_longer": int((diff > 0).sum()),
        "ties": int((diff == 0).sum()),
        "confounder_longer": int((diff < 0).sum()),
    }
    by_pair_family = (
        members[members["pdf_role"] == "injected_attack"].set_index("triad_id").loc[common, "attack_family"]
    )
    pair_by_family = (
        pd.DataFrame({"family": by_pair_family.to_numpy(), "diff": diff.to_numpy()})
        .groupby("family")["diff"]
        .agg(
            pairs="size",
            injected_longer=lambda d: int((d > 0).sum()),
            ties=lambda d: int((d == 0).sum()),
            confounder_longer=lambda d: int((d < 0).sum()),
        )
    )
    summary = {
        "sanitizer_config": pre,
        "mean_added_by_role": members.groupby("pdf_role")[["added_raw", "added_clean"]]
        .mean()
        .round(1)
        .to_dict(),
        "mean_added_by_family": members.groupby(["pdf_role", "family"])[["added_raw", "added_clean"]]
        .mean()
        .round(1)
        .reset_index()
        .to_dict(orient="records"),
        "residual_length_roc_auc_injected_vs_confounder": float(
            roc_auc_score(y, members["added_clean"].to_numpy())
        ),
        "residual_length_rule_accuracy": rule_accuracy,
        "paired_residual_length": pair,
        "paired_residual_length_by_family": pair_by_family.reset_index().to_dict(orient="records"),
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    members[
        ["pdf_id", "triad_id", "pdf_role", "family", "raw_len", "clean_len", "added_raw", "added_clean"]
    ].to_csv(out / "per_file.csv", index=False)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=float), encoding="utf-8")
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k not in ("sanitizer_config", "mean_added_by_family")},
            indent=2,
            default=float,
        )
    )
    print(pair_by_family.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
