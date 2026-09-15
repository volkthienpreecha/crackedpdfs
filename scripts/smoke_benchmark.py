#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path

import yaml
from pdf_autogenerator.config import load_config
from pdf_autogenerator.generator import generate_documents
from pypdf import PdfReader

REPO_ROOT = Path(__file__).resolve().parents[1]
INJECTION_DIR = (
    REPO_ROOT
    / "src"
    / "backend"
    / "services"
    / "processing"
    / "layers"
    / "02-watermarking"
    / "volks-pdf-blocker-ada-layer-1"
)


def load_injector():
    script_path = INJECTION_DIR / "inject_policy.py"
    spec = importlib.util.spec_from_file_location("crackedpdfs_smoke_injector", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_pdf_pair(benign_pdf: Path, injected_pdf: Path) -> None:
    if not injected_pdf.is_file() or injected_pdf.stat().st_size == 0:
        raise RuntimeError("Injection did not produce a PDF")

    benign_reader = PdfReader(str(benign_pdf))
    injected_reader = PdfReader(str(injected_pdf))
    if not benign_reader.pages or len(benign_reader.pages) != len(injected_reader.pages):
        raise RuntimeError("Injected PDF did not preserve the benign document page count")


def run_smoke(output_dir: Path) -> dict[str, object]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    benign_dir = output_dir / "benign-dataset"
    generator_config = output_dir / "generator.yaml"
    generator_config.write_text(
        yaml.safe_dump(
            {
                "output_root": str(benign_dir),
                "total_count": 1,
                "seed": 20260525,
                "resume_mode": "overwrite",
                "family_weights": {"academic_handout": 1.0},
                "template_allowlist": [],
                "page_size_weights": {"letter": 1.0},
                "margin_presets": ["0.75in"],
                "density_presets": ["normal"],
                "font_allowlist": ["liberation_sans"],
                "header_probability": 1.0,
                "footer_probability": 1.0,
                "small_text_probability": 0.0,
                "table_region_probability": 1.0,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    rows = generate_documents(load_config(generator_config))
    generated = [row for row in rows if row.get("status") == "generated"]
    if len(generated) != 1:
        raise RuntimeError(f"Expected one generated benign PDF, got {len(generated)}")
    benign_pdf = Path(str(generated[0]["pdf_path"])).resolve()

    injection_config = {
        "spatial_regime": "extreme_off_page",
        "rendering_regime": "invisible_render_mode",
        "structural_regime": "append_new_stream",
        "artifact_wrapper": True,
        "artifact_regime": "artifact_wrapped",
        "attack_family": "plain_single_block",
        "attack_strength": "medium",
        "font_size": 12,
        "coordinates": [10000, 10000],
        "coordinates_mode": "regime",
        "render_mode": 3,
        "color": [0, 0, 0],
        "compatibility_notes": [],
    }
    injected_pdf = output_dir / "injected.pdf"
    injector = load_injector()
    validated_config = injector.validate_resolved_injection_config(injection_config)
    policy_text = (INJECTION_DIR / "instruction_override.txt").read_text(encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        attack_stats = injector.inject_policy_artifact(
            str(benign_pdf), str(injected_pdf), policy_text, validated_config
        )

    validate_pdf_pair(benign_pdf, injected_pdf)

    return {
        "generated_count": 1,
        "injected_count": 1,
        "benign_pdf": str(benign_pdf),
        "injected_pdf": str(injected_pdf),
        "attack_stats": {
            **attack_stats,
            "segment_count": int(attack_stats.get("num_chunks", 0)),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a one-document CrackedPDFs smoke benchmark.")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    report = run_smoke(parse_args().output_dir)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
