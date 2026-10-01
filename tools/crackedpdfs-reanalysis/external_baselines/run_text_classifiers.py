"""Score the frozen paper v1 test split with off-the-shelf prompt-injection text classifiers.

Each PDF in the test split is scored under two text conditions:

* ``raw``: the pypdf-extracted text as stored in the text cache.
* ``sanitized``: the same text after ``apply_text_preprocessing`` with the ``text_tfidf`` block of
  ``configs/model_hybrid_hard_provenance.yaml`` (benchmark wrapper and synthetic phrase marker stripping).

For every (model, condition) pair two document-level scores are recorded:

* ``score_max_chunk``: the text is split into windows of at most ``--chunk-tokens`` model tokens with
  ``--chunk-overlap`` overlapping tokens and the document score is the maximum chunk score.
* ``score_first_512``: the score of the first 512 tokens only, which quantifies what plain truncation loses.

Outputs (per-file scores and a metrics summary) are written under
``data/artifacts/text_baselines/`` by default.

Example::

    cd lightweight-detector
    /path/to/text-venv/bin/python scripts/external_baselines/run_text_classifiers.py \
        --test-split /path/to/test_split.csv

The script requires ``torch``, ``transformers``, ``huggingface_hub``, ``pandas``, ``pyarrow``,
``scikit-learn`` and ``pyyaml``. It runs on CPU and never modifies repository inputs.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

LOGGER = logging.getLogger("external_baselines.text_classifiers")

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_LIGHTWEIGHT_DIR = REPO_ROOT / "lightweight-detector"
WORK_TABLES = REPO_ROOT / ".cache" / "crackedpdfs-reanalysis" / "tables"
DEFAULT_TEXT_CACHE = WORK_TABLES / "text_cache.parquet"
DEFAULT_MODEL_CONFIG = REPO_LIGHTWEIGHT_DIR / "configs" / "model_hybrid_hard_provenance.yaml"
DEFAULT_OUTPUT_DIR = REPO_ROOT / ".cache" / "crackedpdfs-reanalysis" / "artifacts" / "text_baselines"

CONDITIONS = ("raw", "sanitized")
SCORINGS = ("max_chunk", "first_512")
TRUNCATION_TOKENS = 512


@dataclass(frozen=True)
class ModelSpec:
    """Description of an off-the-shelf classifier and how its outputs map to an injection score."""

    key: str
    repo_id: str
    license: str
    positive_label: str
    notes: str = ""
    weights_filename: str | None = None


MODEL_SPECS: tuple[ModelSpec, ...] = (
    ModelSpec(
        key="protectai_deberta_v3_base_pi_v2",
        repo_id="protectai/deberta-v3-base-prompt-injection-v2",
        license="Apache-2.0",
        positive_label="INJECTION",
        notes="score = softmax probability of the INJECTION class (id 1; id 0 is SAFE).",
    ),
    ModelSpec(
        key="horizon_labs_pi_guard_base",
        repo_id="Horizon-Labs/prompt-injection-guard-base",
        license="Apache-2.0",
        positive_label="INJECTION",
        notes=(
            "mmBERT backbone with an 8k token context. Labels per the model card are SAFE (0) and INJECTION (1); "
            "score = softmax probability of INJECTION. The tokenizer applies the model's built-in obfuscation "
            "normalizer. Chunking uses the same window as the other models for comparability."
        ),
    ),
    ModelSpec(
        key="prompt_guard_2_86m",
        repo_id="gravitee-io/Llama-Prompt-Guard-2-86M-onnx",
        license="Llama 4 Community License (ungated mirror of meta-llama/Llama-Prompt-Guard-2-86M)",
        positive_label="MALICIOUS",
        notes=(
            "The mirror ships model.safetensors next to the ONNX export, so the PyTorch weights are loaded with "
            "transformers (DebertaV2ForSequenceClassification). Labels are BENIGN (0) and MALICIOUS (1); "
            "score = softmax probability of MALICIOUS."
        ),
    ),
    ModelSpec(
        key="deepset_deberta_v3_base_injection",
        repo_id="deepset/deberta-v3-base-injection",
        license="MIT",
        positive_label="INJECTION",
        notes="Labels are LEGIT (0) and INJECTION (1); score = softmax probability of INJECTION.",
    ),
)


@dataclass
class ModelRunRecord:
    """Bookkeeping for one model run (status, revision, label mapping, timing)."""

    key: str
    repo_id: str
    license: str
    status: str = "pending"
    revision: str | None = None
    label_mapping: dict[str, Any] = field(default_factory=dict)
    positive_label: str = ""
    positive_index: int | None = None
    max_model_tokens: int | None = None
    error: str | None = None
    wall_clock_seconds: float = 0.0
    load_seconds: float = 0.0
    documents_scored: int = 0
    documents_total: int = 0
    chunks_scored: int = 0
    tokens_scored: int = 0
    chunks_per_second: float = 0.0
    tokens_per_second: float = 0.0
    timed_out: bool = False

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--test-split", type=Path, required=True, help="CSV with pdf_id, label, pdf_role, ..."
    )
    parser.add_argument("--text-cache", type=Path, default=DEFAULT_TEXT_CACHE)
    parser.add_argument("--model-config", type=Path, default=DEFAULT_MODEL_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--models", nargs="*", default=None, help="Subset of model keys to run (default all)."
    )
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--chunk-tokens", type=int, default=400)
    parser.add_argument("--chunk-overlap", type=int, default=50)
    parser.add_argument("--time-limit-minutes", type=float, default=60.0, help="Per-model wall-clock budget.")
    parser.add_argument(
        "--limit", type=int, default=None, help="Score only the first N test rows (smoke tests)."
    )
    parser.add_argument(
        "--threads", type=int, default=None, help="torch intra-op threads (default: torch default)."
    )
    parser.add_argument("--log-every", type=int, default=50, help="Log progress every N batches.")
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Reuse per-model outputs already present in the output directory (per_file_scores_<key>.parquet with "
            "every document scored, plus the matching record in summary.json) instead of re-running those models."
        ),
    )
    return parser.parse_args(argv)


def load_sanitizer(model_config_path: Path) -> tuple[Any, dict[str, Any]]:
    """Import the repository sanitizer without modifying it and build its config from the hybrid model YAML."""
    if str(REPO_LIGHTWEIGHT_DIR) not in sys.path:
        sys.path.insert(0, str(REPO_LIGHTWEIGHT_DIR))
    from src.models.text_preprocessing import apply_text_preprocessing, build_text_preprocessing_config

    with model_config_path.open("r", encoding="utf-8") as handle:
        model_cfg = yaml.safe_load(handle) or {}
    preprocessing = build_text_preprocessing_config(model_cfg.get("text_tfidf"))
    return apply_text_preprocessing, preprocessing


def load_documents(test_split: Path, text_cache: Path, limit: int | None) -> pd.DataFrame:
    split = pd.read_csv(test_split)
    required = {"pdf_id", "label", "pdf_role", "attack_family", "triad_id", "base_pdf_id"}
    missing = required.difference(split.columns)
    if missing:
        raise ValueError(f"test split is missing columns: {sorted(missing)}")
    cache = pd.read_parquet(text_cache, columns=["pdf_id", "raw_text"])
    merged = split.merge(cache, on="pdf_id", how="left", validate="one_to_one")
    absent = merged["raw_text"].isna().sum()
    if absent:
        raise ValueError(f"{absent} test rows have no entry in the text cache")
    if limit is not None:
        merged = merged.head(limit).copy()
    return merged.reset_index(drop=True)


def chunk_token_ids(ids: list[int], chunk_tokens: int, overlap: int) -> list[list[int]]:
    """Split a token id sequence into windows of at most ``chunk_tokens`` with ``overlap`` shared tokens."""
    if chunk_tokens <= overlap:
        raise ValueError("chunk_tokens must exceed chunk_overlap")
    if not ids:
        return [[]]
    step = chunk_tokens - overlap
    chunks: list[list[int]] = []
    start = 0
    while True:
        chunk = ids[start : start + chunk_tokens]
        chunks.append(chunk)
        if start + chunk_tokens >= len(ids):
            break
        start += step
    return chunks


def resolve_positive_index(id2label: dict[int, str], positive_label: str) -> int:
    for idx, name in id2label.items():
        if str(name).strip().upper() == positive_label.upper():
            return int(idx)
    raise ValueError(f"positive label {positive_label!r} not found in id2label {id2label!r}")


def load_model(spec: ModelSpec, record: ModelRunRecord) -> tuple[Any, Any, int]:
    import torch
    from huggingface_hub import HfApi
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    api = HfApi()
    info = api.model_info(spec.repo_id)
    record.revision = info.sha
    tokenizer = AutoTokenizer.from_pretrained(spec.repo_id, revision=info.sha)
    model = AutoModelForSequenceClassification.from_pretrained(
        spec.repo_id, revision=info.sha, torch_dtype=torch.float32
    )
    model.eval()
    id2label = {int(k): str(v) for k, v in model.config.id2label.items()}
    record.label_mapping = {str(k): v for k, v in sorted(id2label.items())}
    record.positive_label = spec.positive_label
    record.positive_index = resolve_positive_index(id2label, spec.positive_label)
    max_len = getattr(model.config, "max_position_embeddings", None) or tokenizer.model_max_length
    if max_len is None or max_len > 1_000_000:
        max_len = 512
    record.max_model_tokens = int(max_len)
    return tokenizer, model, int(max_len)


@dataclass(frozen=True)
class SpecialTokenTemplate:
    """Prefix and suffix special token ids wrapped around a body sequence, plus the pad id."""

    prefix: tuple[int, ...]
    suffix: tuple[int, ...]
    pad_id: int

    @property
    def budget(self) -> int:
        return len(self.prefix) + len(self.suffix)

    def wrap(self, body: list[int]) -> list[int]:
        return [*self.prefix, *body, *self.suffix]


def infer_special_token_template(tokenizer: Any) -> SpecialTokenTemplate:
    """Derive the single-sequence special token template by encoding a probe with and without special tokens."""
    probe = "probe text"
    body = tokenizer(probe, add_special_tokens=False)["input_ids"]
    full = tokenizer(probe, add_special_tokens=True)["input_ids"]
    start = next(i for i in range(len(full) - len(body) + 1) if full[i : i + len(body)] == body)
    pad_id = tokenizer.pad_token_id
    if pad_id is None:
        pad_id = tokenizer.eos_token_id if tokenizer.eos_token_id is not None else 0
    return SpecialTokenTemplate(tuple(full[:start]), tuple(full[start + len(body) :]), int(pad_id))


def collate(batch: list[list[int]], pad_id: int) -> dict[str, Any]:
    """Right-pad a batch of token id lists into input_ids and attention_mask tensors."""
    import torch

    width = max(len(ids) for ids in batch)
    input_ids = torch.full((len(batch), width), pad_id, dtype=torch.long)
    attention = torch.zeros((len(batch), width), dtype=torch.long)
    for row, ids in enumerate(batch):
        input_ids[row, : len(ids)] = torch.tensor(ids, dtype=torch.long)
        attention[row, : len(ids)] = 1
    return {"input_ids": input_ids, "attention_mask": attention}


def build_chunk_table(
    tokenizer: Any,
    docs: pd.DataFrame,
    texts_by_condition: dict[str, list[str]],
    chunk_tokens: int,
    overlap: int,
    max_model_tokens: int,
) -> tuple[list[dict[str, Any]], list[list[int]]]:
    """Tokenize every document under every condition and enumerate the chunks that need scoring.

    Returns a list of chunk descriptors (document row, condition, kind) and the matching token id lists.
    ``kind`` is ``chunk`` for sliding windows and ``first_512`` for the truncation baseline.
    """
    special_budget = infer_special_token_template(tokenizer).budget
    body_chunk = min(chunk_tokens, max_model_tokens - special_budget)
    body_trunc = min(TRUNCATION_TOKENS, max_model_tokens) - special_budget
    descriptors: list[dict[str, Any]] = []
    sequences: list[list[int]] = []
    for condition in CONDITIONS:
        encoded = tokenizer(texts_by_condition[condition], add_special_tokens=False, truncation=False)
        for row_idx, ids in enumerate(encoded["input_ids"]):
            windows = chunk_token_ids(list(ids), body_chunk, overlap)
            for window in windows:
                descriptors.append({"row": row_idx, "condition": condition, "kind": "chunk"})
                sequences.append(window)
            descriptors.append({"row": row_idx, "condition": condition, "kind": "first_512"})
            sequences.append(list(ids[:body_trunc]))
            descriptors.append(
                {
                    "row": row_idx,
                    "condition": condition,
                    "kind": "meta",
                    "n_chunks": len(windows),
                    "n_tokens": len(ids),
                }
            )
            sequences.append([])
    return descriptors, sequences


def score_sequences(
    tokenizer: Any,
    model: Any,
    sequences: list[list[int]],
    positive_index: int,
    batch_size: int,
    deadline: float,
    log_every: int,
    block_size: int = 256,
) -> tuple[np.ndarray, bool, int, int]:
    """Run the classifier over token id sequences and return positive-class probabilities.

    Identical token sequences are scored once (for single-window documents the window and the first-512
    truncation coincide, and the sanitized text frequently equals the raw text). Sequences are processed in
    input order in blocks of ``block_size`` unique sequences, sorted by length within a block to limit padding,
    so that a time limit leaves a contiguous prefix of fully scored documents.

    Returns the score vector (NaN where not scored), a timed-out flag, and the number of unique sequences and
    body tokens scored.
    """
    import torch

    template = infer_special_token_template(tokenizer)
    scores = np.full(len(sequences), np.nan, dtype=np.float64)
    unique_index: dict[tuple[int, ...], int] = {}
    owners: list[list[int]] = []
    for i, ids in enumerate(sequences):
        key = tuple(ids)
        slot = unique_index.get(key)
        if slot is None:
            slot = len(owners)
            unique_index[key] = slot
            owners.append([])
        owners[slot].append(i)
    unique_seqs = [sequences[group[0]] for group in owners]
    LOGGER.info("%d sequences reduce to %d unique sequences", len(sequences), len(unique_seqs))
    timed_out = False
    scored = 0
    scored_tokens = 0
    batch_no = 0
    n_batches = sum(
        (min(block_size, len(unique_seqs) - b) + batch_size - 1) // batch_size
        for b in range(0, len(unique_seqs), block_size)
    )
    t0 = time.monotonic()
    with torch.inference_mode():
        for block_start in range(0, len(unique_seqs), block_size):
            block = list(range(block_start, min(block_start + block_size, len(unique_seqs))))
            block.sort(key=lambda i: -len(unique_seqs[i]))
            for start in range(0, len(block), batch_size):
                if time.monotonic() > deadline:
                    timed_out = True
                    break
                idxs = block[start : start + batch_size]
                batch_ids = [template.wrap(unique_seqs[i]) for i in idxs]
                logits = model(**collate(batch_ids, template.pad_id)).logits
                probs = torch.softmax(logits.float(), dim=-1)[:, positive_index].cpu().numpy()
                for i, prob in zip(idxs, probs, strict=True):
                    scores[owners[i]] = float(prob)
                scored += len(idxs)
                scored_tokens += sum(len(unique_seqs[i]) for i in idxs)
                batch_no += 1
                if log_every and batch_no % log_every == 0:
                    elapsed = time.monotonic() - t0
                    LOGGER.info(
                        "  batch %d/%d, %d unique sequences, %.2f seq/s, eta %.1f min",
                        batch_no,
                        n_batches,
                        scored,
                        scored / elapsed if elapsed else 0.0,
                        (n_batches - batch_no) * elapsed / batch_no / 60.0,
                    )
            if timed_out:
                break
    return scores, timed_out, scored, scored_tokens


def assemble_rows(
    docs: pd.DataFrame,
    descriptors: list[dict[str, Any]],
    scores: np.ndarray,
    model_key: str,
) -> pd.DataFrame:
    """Reduce chunk-level scores to one row per (document, condition)."""
    max_chunk: dict[tuple[int, str], float] = {}
    complete: dict[tuple[int, str], bool] = {}
    first_512: dict[tuple[int, str], float] = {}
    meta: dict[tuple[int, str], dict[str, Any]] = {}
    for desc, score in zip(descriptors, scores, strict=True):
        key = (desc["row"], desc["condition"])
        kind = desc["kind"]
        if kind == "chunk":
            if np.isnan(score):
                complete[key] = False
            else:
                complete.setdefault(key, True)
                max_chunk[key] = max(max_chunk.get(key, -np.inf), float(score))
        elif kind == "first_512":
            first_512[key] = float(score)
        else:
            meta[key] = desc
    rows: list[dict[str, Any]] = []
    for row_idx in range(len(docs)):
        doc = docs.iloc[row_idx]
        for condition in CONDITIONS:
            key = (row_idx, condition)
            is_complete = complete.get(key, False)
            rows.append(
                {
                    "pdf_id": doc["pdf_id"],
                    "label": int(doc["label"]),
                    "pdf_role": doc["pdf_role"],
                    "attack_family": doc["attack_family"],
                    "triad_id": doc["triad_id"],
                    "base_pdf_id": doc["base_pdf_id"],
                    "model": model_key,
                    "condition": condition,
                    "score_max_chunk": max_chunk[key] if is_complete else np.nan,
                    "score_first_512": first_512.get(key, np.nan),
                    "n_chunks": int(meta[key]["n_chunks"]),
                    "n_tokens": int(meta[key]["n_tokens"]),
                }
            )
    return pd.DataFrame(rows)


def run_model(
    spec: ModelSpec,
    docs: pd.DataFrame,
    texts_by_condition: dict[str, list[str]],
    args: argparse.Namespace,
) -> tuple[ModelRunRecord, pd.DataFrame | None]:
    record = ModelRunRecord(
        key=spec.key, repo_id=spec.repo_id, license=spec.license, documents_total=len(docs)
    )
    t0 = time.monotonic()
    try:
        tokenizer, model, max_model_tokens = load_model(spec, record)
    except Exception as exc:  # noqa: BLE001
        record.status = "skipped_download_failed"
        record.error = f"{type(exc).__name__}: {exc}"
        record.wall_clock_seconds = time.monotonic() - t0
        LOGGER.error("Skipping %s: %s", spec.repo_id, record.error)
        return record, None
    record.load_seconds = time.monotonic() - t0
    LOGGER.info(
        "Loaded %s @ %s (labels %s, positive index %d, max tokens %d) in %.1fs",
        spec.repo_id,
        record.revision,
        record.label_mapping,
        record.positive_index,
        max_model_tokens,
        record.load_seconds,
    )
    descriptors, sequences = build_chunk_table(
        tokenizer, docs, texts_by_condition, args.chunk_tokens, args.chunk_overlap, max_model_tokens
    )
    scorable = [i for i, d in enumerate(descriptors) if d["kind"] != "meta"]
    LOGGER.info(
        "%d sequences to score (%d documents x %d conditions)", len(scorable), len(docs), len(CONDITIONS)
    )
    deadline = t0 + args.time_limit_minutes * 60.0
    t_score = time.monotonic()
    sub_scores, timed_out, scored, scored_tokens = score_sequences(
        tokenizer,
        model,
        [sequences[i] for i in scorable],
        int(record.positive_index),
        args.batch_size,
        deadline,
        args.log_every,
    )
    score_seconds = time.monotonic() - t_score
    scores = np.full(len(descriptors), np.nan)
    scores[scorable] = sub_scores
    table = assemble_rows(docs, descriptors, scores, spec.key)
    record.timed_out = timed_out
    record.status = "timed_out_partial" if timed_out else "completed"
    record.chunks_scored = int(scored)
    record.tokens_scored = int(scored_tokens)
    record.documents_scored = int(table.dropna(subset=["score_max_chunk"])["pdf_id"].nunique())
    record.chunks_per_second = scored / score_seconds if score_seconds > 0 else 0.0
    record.tokens_per_second = scored_tokens / score_seconds if score_seconds > 0 else 0.0
    record.wall_clock_seconds = time.monotonic() - t0
    LOGGER.info(
        "%s: %s, %d/%d documents, %.1f sequences/s, %.0f tokens/s, %.1f min total",
        spec.key,
        record.status,
        record.documents_scored,
        record.documents_total,
        record.chunks_per_second,
        record.tokens_per_second,
        record.wall_clock_seconds / 60.0,
    )
    del model
    return record, table


def load_previous_result(
    spec: ModelSpec, output_dir: Path, n_docs: int
) -> tuple[ModelRunRecord, pd.DataFrame] | None:
    """Return a completed earlier run of ``spec`` from the output directory, or None if absent or incomplete."""
    table_path = output_dir / f"per_file_scores_{spec.key}.parquet"
    summary_path = output_dir / "summary.json"
    if not table_path.exists() or not summary_path.exists():
        return None
    table = pd.read_parquet(table_path)
    if table["pdf_id"].nunique() != n_docs or table["score_max_chunk"].isna().any():
        return None
    with summary_path.open("r", encoding="utf-8") as handle:
        previous = json.load(handle)
    for entry in previous.get("models", []):
        if entry.get("key") == spec.key and entry.get("status") == "completed":
            fields = {name for name in ModelRunRecord.__dataclass_fields__}
            record = ModelRunRecord(**{k: v for k, v in entry.items() if k in fields})
            record.status = "completed_reused_from_previous_run"
            return record, table
    return None


def recall_at_fpr(y_true: np.ndarray, scores: np.ndarray, target_fpr: float) -> float:
    from sklearn.metrics import roc_curve

    fpr, tpr, _ = roc_curve(y_true, scores)
    ok = fpr <= target_fpr
    return float(tpr[ok].max()) if ok.any() else 0.0


def best_f1(y_true: np.ndarray, scores: np.ndarray) -> tuple[float, float]:
    from sklearn.metrics import precision_recall_curve

    precision, recall, thresholds = precision_recall_curve(y_true, scores)
    f1 = 2 * precision[:-1] * recall[:-1] / np.clip(precision[:-1] + recall[:-1], 1e-12, None)
    best = int(np.nanargmax(f1))
    return float(f1[best]), float(thresholds[best])


def paired_ranking_accuracy(frame: pd.DataFrame, score_col: str, negative_role: str) -> dict[str, Any]:
    """Fraction of triads where the injected score exceeds the matched negative score (ties count one half)."""
    pos = frame[frame["pdf_role"] == "injected_attack"].set_index("triad_id")[score_col]
    neg = frame[frame["pdf_role"] == negative_role].set_index("triad_id")[score_col]
    joined = pd.concat([pos.rename("pos"), neg.rename("neg")], axis=1, join="inner").dropna()
    if joined.empty:
        return {"accuracy": None, "n_pairs": 0, "n_ties": 0}
    wins = (joined["pos"] > joined["neg"]).sum()
    ties = (joined["pos"] == joined["neg"]).sum()
    return {
        "accuracy": float((wins + 0.5 * ties) / len(joined)),
        "n_pairs": int(len(joined)),
        "n_ties": int(ties),
    }


def compute_metrics(frame: pd.DataFrame, score_col: str) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score, f1_score, roc_auc_score

    sub = frame.dropna(subset=[score_col])
    y = sub["label"].to_numpy(dtype=int)
    s = sub[score_col].to_numpy(dtype=float)
    out: dict[str, Any] = {"n_scored": int(len(sub)), "n_positive": int(y.sum())}
    if len(np.unique(y)) < 2:
        out["note"] = "metrics undefined: a single class is present"
        return out
    pred05 = (s >= 0.5).astype(int)
    f1_best, thr_best = best_f1(y, s)
    out.update(
        {
            "roc_auc": float(roc_auc_score(y, s)),
            "pr_auc": float(average_precision_score(y, s)),
            "f1_at_0_5": float(f1_score(y, pred05)),
            "precision_at_0_5": float(((pred05 == 1) & (y == 1)).sum() / max(pred05.sum(), 1)),
            "recall_at_0_5": float(((pred05 == 1) & (y == 1)).sum() / max(y.sum(), 1)),
            "fpr_at_0_5": float(((pred05 == 1) & (y == 0)).sum() / max((y == 0).sum(), 1)),
            "f1_best_threshold_optimistic": f1_best,
            "best_threshold_optimistic": thr_best,
            "recall_at_1pct_fpr": recall_at_fpr(y, s, 0.01),
            "paired_rank_vs_confounder": paired_ranking_accuracy(sub, score_col, "benign_confounder"),
            "paired_rank_vs_benign_original": paired_ranking_accuracy(sub, score_col, "benign_original"),
        }
    )
    injected = sub[sub["pdf_role"] == "injected_attack"]
    per_family: dict[str, Any] = {}
    for family, group in injected.groupby("attack_family"):
        per_family[str(family)] = {
            "n": int(len(group)),
            "recall_at_0_5": float((group[score_col] >= 0.5).mean()),
        }
    out["per_attack_family_recall_at_0_5"] = dict(sorted(per_family.items()))
    return out


def build_summary(
    per_file: pd.DataFrame,
    records: list[ModelRunRecord],
    args: argparse.Namespace,
    n_docs: int,
    preprocessing: dict[str, Any],
    total_seconds: float,
) -> dict[str, Any]:
    import torch
    import transformers

    results: dict[str, Any] = {}
    for record in records:
        if record.status.startswith("skipped"):
            continue
        model_frame = per_file[per_file["model"] == record.key]
        results[record.key] = {}
        for condition in CONDITIONS:
            cond_frame = model_frame[model_frame["condition"] == condition]
            results[record.key][condition] = {
                scoring: compute_metrics(cond_frame, f"score_{scoring}") for scoring in SCORINGS
            }
    return {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "test_split": str(args.test_split),
        "text_cache": str(args.text_cache),
        "n_documents": int(n_docs),
        "conditions": list(CONDITIONS),
        "scorings": list(SCORINGS),
        "chunking": {
            "chunk_tokens": args.chunk_tokens,
            "chunk_overlap": args.chunk_overlap,
            "truncation_tokens": TRUNCATION_TOKENS,
            "note": (
                "Chunk windows are measured in body tokens of each model's tokenizer; special tokens are added "
                "per window. The document score is the maximum over windows. Windows are clipped to the model's "
                "maximum sequence length."
            ),
        },
        "sanitizer": {
            "module": "src/models/text_preprocessing.py",
            "function": "apply_text_preprocessing",
            "config_source": str(args.model_config),
            "config": preprocessing,
        },
        "runtime": {
            "device": "cpu",
            "batch_size": args.batch_size,
            "torch_threads": torch.get_num_threads(),
            "torch_version": torch.__version__,
            "transformers_version": transformers.__version__,
            "python_version": sys.version.split()[0],
            "time_limit_minutes_per_model": args.time_limit_minutes,
            "total_wall_clock_seconds": total_seconds,
        },
        "models": [record.to_dict() for record in records],
        "results": results,
    }


def fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_markdown(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Off-the-shelf prompt-injection text classifiers on the paper v1 test split")
    lines.append("")
    lines.append(
        f"Generated {summary['generated_at_utc']}. {summary['n_documents']} documents, "
        f"conditions: {', '.join(summary['conditions'])}. Scores are the positive-class softmax probability."
    )
    lines.append("")
    ch = summary["chunking"]
    lines.append(
        f"Chunking: windows of at most {ch['chunk_tokens']} tokens with {ch['chunk_overlap']} overlapping tokens, "
        f"document score = max over windows (`max_chunk`). `first_512` scores only the first "
        f"{ch['truncation_tokens']} tokens."
    )
    lines.append("")
    rt = summary["runtime"]
    lines.append(
        f"Runtime: CPU, batch size {rt['batch_size']}, torch {rt['torch_version']} with {rt['torch_threads']} threads, "
        f"transformers {rt['transformers_version']}, Python {rt['python_version']}. Total wall clock "
        f"{rt['total_wall_clock_seconds'] / 60.0:.1f} min."
    )
    lines.append("")
    lines.append("## Models")
    lines.append("")
    lines.append(
        "| key | repository | revision | license | labels (id: name) | positive | status | docs | seq/s | wall clock |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for rec in summary["models"]:
        labels = ", ".join(f"{k}: {v}" for k, v in rec["label_mapping"].items()) or "n/a"
        status = rec["status"] + (f" ({rec['error']})" if rec.get("error") else "")
        lines.append(
            f"| {rec['key']} | {rec['repo_id']} | {rec['revision'] or 'n/a'} | {rec['license']} | {labels} | "
            f"{rec['positive_label'] or 'n/a'} | {status} | {rec['documents_scored']}/{rec['documents_total']} | "
            f"{rec['chunks_per_second']:.1f} | {rec['wall_clock_seconds'] / 60.0:.1f} min |"
        )
    lines.append("")
    lines.append("## Headline metrics")
    lines.append("")
    lines.append(
        "| model | condition | scoring | ROC-AUC | PR-AUC | F1@0.5 | recall@0.5 | FPR@0.5 | "
        "F1@best (optimistic) | best thr | recall@1% FPR | pair acc vs confounder | pair acc vs benign original |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for model_key, by_condition in summary["results"].items():
        for condition, by_scoring in by_condition.items():
            for scoring, m in by_scoring.items():
                if "roc_auc" not in m:
                    lines.append(
                        f"| {model_key} | {condition} | {scoring} | {m.get('note', 'n/a')} |" + " |" * 9
                    )
                    continue
                lines.append(
                    f"| {model_key} | {condition} | {scoring} | {fmt(m['roc_auc'])} | {fmt(m['pr_auc'])} | "
                    f"{fmt(m['f1_at_0_5'])} | {fmt(m['recall_at_0_5'])} | {fmt(m['fpr_at_0_5'])} | "
                    f"{fmt(m['f1_best_threshold_optimistic'])} | {fmt(m['best_threshold_optimistic'], 4)} | "
                    f"{fmt(m['recall_at_1pct_fpr'])} | "
                    f"{fmt(m['paired_rank_vs_confounder']['accuracy'])} "
                    f"(n={m['paired_rank_vs_confounder']['n_pairs']}) | "
                    f"{fmt(m['paired_rank_vs_benign_original']['accuracy'])} "
                    f"(n={m['paired_rank_vs_benign_original']['n_pairs']}) |"
                )
    lines.append("")
    lines.append(
        "The optimistic F1 selects the threshold on the test set itself and is an upper bound, not a deployable number."
    )
    lines.append("")
    lines.append("## Per-attack-family recall at threshold 0.5 (max_chunk scoring)")
    lines.append("")
    families: list[str] = []
    for by_condition in summary["results"].values():
        for by_scoring in by_condition.values():
            fam = by_scoring.get("max_chunk", {}).get("per_attack_family_recall_at_0_5", {})
            families.extend(k for k in fam if k not in families)
    columns = [
        (model_key, condition)
        for model_key, by_condition in summary["results"].items()
        for condition in by_condition
    ]
    header = "| attack family | n | " + " | ".join(f"{m} / {c}" for m, c in columns) + " |"
    lines.append(header)
    lines.append("|---|---|" + "---|" * len(columns))
    for family in sorted(families):
        n_val = "n/a"
        cells = []
        for model_key, condition in columns:
            fam = (
                summary["results"][model_key][condition]
                .get("max_chunk", {})
                .get("per_attack_family_recall_at_0_5", {})
            )
            entry = fam.get(family)
            if entry:
                n_val = str(entry["n"])
                cells.append(fmt(entry["recall_at_0_5"]))
            else:
                cells.append("n/a")
        lines.append(f"| {family} | {n_val} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## Sanitizer")
    lines.append("")
    san = summary["sanitizer"]
    lines.append(
        f"`{san['function']}` from `{san['module']}` with the `text_tfidf` block of `{Path(san['config_source']).name}`: "
        f"strip_known_benchmark_wrappers={san['config']['strip_known_benchmark_wrappers']}, "
        f"strip_synthetic_phrase_markers={san['config']['strip_synthetic_phrase_markers']}."
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.threads:
        import torch

        torch.set_num_threads(args.threads)
    t_start = time.monotonic()

    sanitize, preprocessing = load_sanitizer(args.model_config)
    docs = load_documents(args.test_split, args.text_cache, args.limit)
    LOGGER.info("Loaded %d test documents", len(docs))
    raw_texts = [str(t) for t in docs["raw_text"].tolist()]
    t_san = time.monotonic()
    sanitized_texts = [sanitize(t, preprocessing) for t in raw_texts]
    LOGGER.info("Sanitized texts in %.1fs", time.monotonic() - t_san)
    texts_by_condition = {"raw": raw_texts, "sanitized": sanitized_texts}

    selected = [spec for spec in MODEL_SPECS if args.models is None or spec.key in set(args.models)]
    if not selected:
        raise SystemExit(f"no models selected; known keys: {[s.key for s in MODEL_SPECS]}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    records: list[ModelRunRecord] = []
    tables: list[pd.DataFrame] = []
    for spec in selected:
        previous = load_previous_result(spec, args.output_dir, len(docs)) if args.resume else None
        if previous is not None:
            record, table = previous
            LOGGER.info("Reusing completed results for %s from %s", spec.key, args.output_dir)
            records.append(record)
            tables.append(table)
            continue
        record, table = run_model(spec, docs, texts_by_condition, args)
        records.append(record)
        if table is not None:
            tables.append(table)
            partial_path = args.output_dir / f"per_file_scores_{spec.key}.parquet"
            table.to_parquet(partial_path, index=False)

    per_file = pd.concat(tables, ignore_index=True) if tables else pd.DataFrame()
    per_file.to_parquet(args.output_dir / "per_file_scores.parquet", index=False)
    per_file.to_csv(args.output_dir / "per_file_scores.csv", index=False)

    total_seconds = time.monotonic() - t_start
    summary = build_summary(per_file, records, args, len(docs), preprocessing, total_seconds)
    with (args.output_dir / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    (args.output_dir / "summary.md").write_text(render_markdown(summary), encoding="utf-8")
    LOGGER.info("Wrote outputs to %s in %.1f min", args.output_dir, total_seconds / 60.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
