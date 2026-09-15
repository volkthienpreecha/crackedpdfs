#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "paper-v1" / "reproducibility" / "download-manifest.json"
DEFAULT_ARTIFACT_DIR = REPO_ROOT / ".cache" / "crackedpdfs-paper-v1"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "reproduced-results"
MODEL_ORDER = ("logreg_shortcut_free", "xgb_shortcut_free", "text_tfidf", "hybrid")
BASELINE_ORDER = ("rule", "promptguard")
METRIC_COLUMNS = ("accuracy", "precision", "recall", "f1", "roc_auc", "pr_auc")


class ReproductionError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_artifact_path(root: Path, relative: str) -> Path:
    normalized = relative.replace("\\", "/")
    parts = Path(normalized).parts
    if not parts or Path(normalized).is_absolute() or ".." in parts:
        raise ReproductionError(f"Unsafe artifact path: {relative}")
    target = (root / Path(*parts)).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        raise ReproductionError(f"Artifact path escaped cache: {relative}")
    return target


RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}


def _is_retryable(error: Exception) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return error.code in RETRYABLE_HTTP_STATUS
    return isinstance(error, (urllib.error.URLError, TimeoutError, ConnectionError))


def download_file(
    url: str,
    destination: Path,
    attempts: int = 4,
    backoff_seconds: float = 2.0,
    sleep=time.sleep,
) -> None:
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in {"http", "https"}:
        raise ReproductionError(
            f"Refusing to download from unsupported scheme: {scheme or 'none'}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "crackedpdfs-reproducer/1.0"})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
            temporary.replace(destination)
            return
        except Exception as error:
            temporary.unlink(missing_ok=True)
            if attempt == attempts or not _is_retryable(error):
                raise
            delay = backoff_seconds * 2 ** (attempt - 1)
            print(
                f"Download attempt {attempt}/{attempts} failed ({error}); retrying in {delay:g}s",
                file=sys.stderr,
            )
            sleep(delay)


def materialize_and_verify_artifacts(
    artifact_dir: Path, manifest: dict[str, Any], base_url_override: str | None
) -> list[dict[str, Any]]:
    base_url = base_url_override or manifest.get("base_url")
    verified: list[dict[str, Any]] = []
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ReproductionError("Download manifest has no files")

    for entry in files:
        relative = str(entry["path"])
        destination = safe_artifact_path(artifact_dir, relative)
        if not destination.is_file():
            if not base_url:
                raise ReproductionError(f"Missing artifact and no base URL configured: {relative}")
            url = f"{str(base_url).rstrip('/')}/{relative.replace('\\', '/')}"
            download_file(url, destination)

        actual_hash = sha256_file(destination)
        expected_hash = str(entry["sha256"]).lower()
        if actual_hash != expected_hash:
            destination.unlink(missing_ok=True)
            raise ReproductionError(
                f"SHA-256 mismatch for {relative}: expected {expected_hash}, got {actual_hash}. "
                "Removed the cached copy; rerun to download it again."
            )
        actual_size = destination.stat().st_size
        expected_size = entry.get("bytes")
        if expected_size is not None and actual_size != int(expected_size):
            raise ReproductionError(
                f"Size mismatch for {relative}: expected {expected_size}, got {actual_size}"
            )
        verified.append({"path": relative, "bytes": actual_size, "sha256": actual_hash})
    return verified


def ordered_names(values: dict[str, Any], preferred: tuple[str, ...]) -> list[str]:
    return [name for name in preferred if name in values] + [
        name for name in values if name not in preferred
    ]


def metric_row(entry_type: str, name: str, setting: str, metrics: dict[str, Any]) -> list[Any]:
    missing = [column for column in METRIC_COLUMNS if column not in metrics]
    if missing:
        raise ReproductionError(f"Missing metrics for {entry_type}/{name}: {', '.join(missing)}")
    return [entry_type, name, setting, *(metrics[column] for column in METRIC_COLUMNS)]


def render_hard_setting_summary(metrics: dict[str, Any], output_path: Path) -> None:
    split_strategy = str(metrics.get("split_strategy", "heldout_provenance"))
    models = metrics.get("models") or {}
    baselines = metrics.get("baselines") or {}
    rows: list[list[Any]] = []

    for name in ordered_names(models, MODEL_ORDER):
        rows.append(metric_row("model", name, split_strategy, models[name]["metrics"]))
    for name in ordered_names(baselines, BASELINE_ORDER):
        rows.append(metric_row("baseline", name, split_strategy, baselines[name]["metrics"]))
    for name in ordered_names(models, MODEL_ORDER):
        label_shuffle = (models[name].get("sanity_checks") or {}).get("label_shuffle")
        if label_shuffle:
            rows.append(metric_row("sanity_check", name, "label_shuffle", label_shuffle))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("entry_type", "name", "setting", *METRIC_COLUMNS))
        writer.writerows(rows)


def reproduce(
    artifact_dir: Path,
    manifest_path: Path,
    output_dir: Path,
    base_url: str | None = None,
) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verified = materialize_and_verify_artifacts(artifact_dir, manifest, base_url)
    metrics_path = safe_artifact_path(artifact_dir, "metrics/metrics.json")
    if not metrics_path.is_file():
        raise ReproductionError("Manifest must include metrics/metrics.json")
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    output_table = output_dir / "hard-setting-summary.csv"
    render_hard_setting_summary(metrics, output_table)
    (output_dir / "verification.json").write_text(
        json.dumps({"verified_artifacts": verified}, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Verified {len(verified)} frozen artifacts")
    print(f"Wrote {output_table}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download and verify frozen CrackedPDFs features, then regenerate paper tables."
    )
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--base-url", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        reproduce(args.artifact_dir, args.manifest, args.output_dir, args.base_url)
    except (OSError, KeyError, ValueError, json.JSONDecodeError, ReproductionError) as exc:
        print(f"reproduction failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
