from __future__ import annotations

import json
from pathlib import Path

import pikepdf
import pytest
from PIL import Image

from crackedpdfs_audit.cli import main
from crackedpdfs_audit.contracts import contract_satisfied, lexical_oracle_hits
from crackedpdfs_audit.corpus import build_tasks, run_audit, summarize_records, write_outputs
from crackedpdfs_audit.geometry import added_glyphs, extract_glyphs, summarize_glyphs, visibility_reasons
from crackedpdfs_audit.render import pixel_diff, reveal

BASE_STREAM = b"BT /F1 12 Tf 72 700 Td (Benign body text) Tj ET"


def write_pdf(path: Path, extra: bytes = b"", size=(612, 792), cropbox=None) -> Path:
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=size)
    page = pdf.pages[0]
    page.Resources = pikepdf.Dictionary(
        Font=pikepdf.Dictionary(
            F1=pikepdf.Dictionary(
                Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica
            )
        )
    )
    page.Contents = pikepdf.Stream(pdf, BASE_STREAM + b"\n" + extra)
    if cropbox:
        page.CropBox = pikepdf.Array(cropbox)
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.save(path)
    return path


def text_block(x: float, y: float, text: str, size: float = 12, mode: int = 0, rgb=(0, 0, 0)) -> bytes:
    r, g, b = rgb
    return f"q {mode} Tr {r} {g} {b} rg BT /F1 {size} Tf {x} {y} Td ({text}) Tj ET Q".encode()


@pytest.fixture()
def base_pdf(tmp_path: Path) -> Path:
    return write_pdf(tmp_path / "base.pdf")


def added(tmp_path: Path, base_pdf: Path, extra: bytes, **kwargs):
    candidate = write_pdf(tmp_path / "candidate.pdf", extra, **kwargs)
    page = extract_glyphs(candidate)[0]
    reference = extract_glyphs(base_pdf)[0]
    return candidate, page, added_glyphs(page, reference)


def test_reference_diff_isolates_only_added_text(tmp_path, base_pdf):
    _, page, glyphs = added(tmp_path, base_pdf, text_block(100, 400, "HIDDEN", mode=3))
    assert len(page.glyphs) == len("Benign body text") + len("HIDDEN")
    assert "".join(g.text for g in glyphs) == "HIDDEN"


def test_off_page_text_below_the_page_is_measured(tmp_path, base_pdf):
    # The paper v1 failure: regime anchors used as absolute points.
    extra = text_block(0.12, 0.78, "FIRST") + b"\n" + text_block(0.12, -13.62, "SECOND")
    _, page, glyphs = added(tmp_path, base_pdf, extra)
    summary = summarize_glyphs(glyphs, page.page_box)
    assert summary.clipped == len("FIRST")
    assert summary.below_page == len("SECOND")
    assert summary.realized_spatial_class == "straddles_page_edge"
    assert contract_satisfied("inside_page", glyphs, page.page_box) is False


def test_visibility_reasons_cover_each_hiding_mechanism(tmp_path, base_pdf):
    cases = {
        "invisible_render_mode": text_block(100, 400, "A", mode=3),
        "tiny_font": text_block(100, 400, "A", size=1.2),
        "low_contrast_fill": text_block(100, 400, "A", rgb=(0.96, 0.96, 0.96)),
        "off_page": text_block(10000, 10000, "A"),
    }
    for reason, extra in cases.items():
        _, page, glyphs = added(tmp_path, base_pdf, extra)
        assert len(glyphs) == 1
        assert reason in visibility_reasons(glyphs[0], page.page_box), reason

    _, page, glyphs = added(tmp_path, base_pdf, text_block(100, 400, "A"))
    assert visibility_reasons(glyphs[0], page.page_box) == []


def test_label_contracts(tmp_path, base_pdf):
    _, page, inside = added(tmp_path, base_pdf, text_block(200, 400, "INSIDE", mode=3))
    assert contract_satisfied("inside_page", inside, page.page_box)
    assert not contract_satisfied("extreme_off_page", inside, page.page_box)
    assert not contract_satisfied("near_margin", inside, page.page_box)

    _, page, off = added(tmp_path, base_pdf, text_block(-612, -792, "NEGATIVE"))
    assert contract_satisfied("negative_off_page", off, page.page_box)

    _, page, margin = added(tmp_path, base_pdf, text_block(24, 16, "FOOTER", size=1.2))
    assert contract_satisfied("near_margin", margin, page.page_box)
    assert contract_satisfied("unknown_label", margin, page.page_box) is None


def test_cropbox_defines_the_visible_page(tmp_path, base_pdf):
    _, page, glyphs = added(tmp_path, base_pdf, text_block(40, 400, "CROPPED"), cropbox=[100, 100, 500, 700])
    assert page.page_box == (100.0, 100.0, 500.0, 700.0)
    assert summarize_glyphs(glyphs, page.page_box).outside == len("CROPPED")


def test_lexical_oracle_tokens():
    assert lexical_oracle_hits("[DATASET_SAMPLE_ID=sample_1][MESSAGE_TYPE=x]") == [
        "DATASET_SAMPLE_ID",
        "MESSAGE_TYPE=",
    ]
    assert lexical_oracle_hits("ordinary text") == []


def test_pixel_diff_separates_rendered_from_unrendered_additions(tmp_path, base_pdf):
    off_page = write_pdf(tmp_path / "off.pdf", text_block(10000, 10000, "HIDDEN TEXT"))
    visible = write_pdf(tmp_path / "visible.pdf", text_block(100, 400, "VISIBLE TEXT"))
    assert pixel_diff(off_page, base_pdf).changed_pixels == 0
    assert pixel_diff(visible, base_pdf).changed_pixels > 50


def test_reveal_draws_off_page_text_on_an_expanded_canvas(tmp_path, base_pdf):
    candidate, page, glyphs = added(tmp_path, base_pdf, text_block(72, -200, "BELOW THE PAGE"))
    output = reveal(candidate, glyphs, page.page_box, tmp_path / "reveal.png", max_side_px=800)
    image = Image.open(output)
    assert image.size[1] > image.size[0]
    # The expanded canvas is taller than the page aspect ratio alone would give.
    assert image.size[1] / image.size[0] > 792 / 612


def test_corpus_audit_end_to_end(tmp_path):
    root = tmp_path / "corpus"
    write_pdf(root / "benign/s1.benign.pdf")
    write_pdf(
        root / "benign/s1.benign-confounder.pdf",
        text_block(0.12, -13.62, "[DATASET_SAMPLE_ID=s1] note", mode=3),
    )
    write_pdf(
        root / "injected/s1.injected.pdf", text_block(0.12, -13.62, "[DATASET_SAMPLE_ID=s1] attack", mode=3)
    )
    write_pdf(root / "benign/s2.benign.pdf")
    write_pdf(root / "benign/s2.benign-confounder.pdf", text_block(10000, 10000, "note"))
    write_pdf(root / "injected/s2.injected.pdf", text_block(10000, 10000, "attack"))
    rows = []
    for sample, label in (("s1", "inside_page"), ("s2", "extreme_off_page")):
        shared = {
            "sample_id": sample,
            "target_attack_family": "in_page_invisible_text",
            "target_physical_attack_strength": "weak",
            "target_physical_spatial_regime": label,
            "target_physical_rendering_regime": "invisible_render_mode",
            "confounder_physical_attack_strength": "weak",
            "confounder_physical_spatial_regime": label,
            "confounder_physical_rendering_regime": "invisible_render_mode",
        }
        rows += [
            {
                **shared,
                "pdf_id": f"{sample}.benign",
                "pdf_role": "benign_original",
                "file_path": f"benign/{sample}.benign.pdf",
            },
            {
                **shared,
                "pdf_id": f"{sample}.benign_confounder",
                "pdf_role": "benign_confounder",
                "file_path": f"benign/{sample}.benign-confounder.pdf",
            },
            {
                **shared,
                "pdf_id": f"{sample}.injected",
                "pdf_role": "injected_attack",
                "file_path": f"injected/{sample}.injected.pdf",
                "spatial_regime": label,
            },
        ]
    metadata = tmp_path / "metadata.jsonl"
    metadata.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    tasks = build_tasks(rows, root, render=True)
    assert len(tasks) == 4
    records = list(run_audit(tasks, workers=1))
    assert all(record["error"] is None for record in records)
    by_id = {record["pdf_id"]: record for record in records}
    assert by_id["s1.injected"]["contract_satisfied"] is False
    assert by_id["s1.injected"]["added_below_page"] == len("[DATASET_SAMPLE_ID=s1] attack")
    assert by_id["s1.injected"]["lexical_oracle_tokens"] == ["DATASET_SAMPLE_ID"]
    assert by_id["s2.injected"]["contract_satisfied"] is True
    assert by_id["s2.injected"]["changed_pixels_72dpi"] == 0

    summary = summarize_records(records)
    assert {(row["role"], row["spatial_label"]) for row in summary} == {
        ("benign_confounder", "extreme_off_page"),
        ("benign_confounder", "inside_page"),
        ("injected_attack", "extreme_off_page"),
        ("injected_attack", "inside_page"),
    }
    outputs = write_outputs(records, tmp_path / "out")
    assert (
        "| injected_attack | in_page_invisible_text | inside_page | 1 |"
        in outputs["summary_markdown"].read_text()
    )

    assert (
        main(
            [
                "corpus",
                "--root",
                str(root),
                "--metadata",
                str(metadata),
                "--out",
                str(tmp_path / "cli"),
                "--workers",
                "1",
            ]
        )
        == 0
    )
    assert (tmp_path / "cli" / "placement-audit-summary.csv").exists()


def test_file_command_json(tmp_path, base_pdf, capsys):
    candidate = write_pdf(tmp_path / "candidate.pdf", text_block(10000, 10000, "OFF"))
    assert (
        main(["file", str(candidate), "--reference", str(base_pdf), "--label", "extreme_off_page", "--json"])
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report[0]["outside"] == 3
    assert report[0]["contract_satisfied"] is True


def write_pdf_raw(path: Path, content: bytes, mediabox=None, rotate=None, pages=1) -> Path:
    pdf = pikepdf.new()
    for _ in range(pages):
        pdf.add_blank_page(page_size=(612, 792))
    for page in pdf.pages:
        page.Resources = pikepdf.Dictionary(
            Font=pikepdf.Dictionary(
                F1=pikepdf.Dictionary(
                    Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica
                )
            )
        )
        if mediabox:
            page.MediaBox = pikepdf.Array(mediabox)
        if rotate is not None:
            page.Rotate = rotate
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.save(path)
    return path


def test_rotated_page_uses_the_glyph_coordinate_frame(tmp_path):
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    page = pdf.pages[0]
    page.Resources = pikepdf.Dictionary(
        Font=pikepdf.Dictionary(
            F1=pikepdf.Dictionary(
                Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica
            )
        )
    )
    page.Rotate = 90
    page.Contents = pikepdf.Stream(pdf, b"BT /F1 12 Tf 100 700 Td (INSIDE) Tj ET")
    path = tmp_path / "rot.pdf"
    pdf.save(path)
    glyphs_page = extract_glyphs(path)[0]
    assert glyphs_page.page_box == (0.0, 0.0, 792.0, 612.0)
    assert summarize_glyphs(glyphs_page.glyphs, glyphs_page.page_box).realized_spatial_class == "inside_page"


def test_nonzero_mediabox_origin_is_normalized(tmp_path):
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    page = pdf.pages[0]
    page.Resources = pikepdf.Dictionary(
        Font=pikepdf.Dictionary(
            F1=pikepdf.Dictionary(
                Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica
            )
        )
    )
    page.MediaBox = pikepdf.Array([100, 100, 712, 892])
    page.Contents = pikepdf.Stream(pdf, b"BT /F1 12 Tf 120 120 Td (INSIDE) Tj ET")
    path = tmp_path / "shift.pdf"
    pdf.save(path)
    glyphs_page = extract_glyphs(path)[0]
    assert glyphs_page.page_box == (0.0, 0.0, 612.0, 792.0)
    assert summarize_glyphs(glyphs_page.glyphs, glyphs_page.page_box).realized_spatial_class == "inside_page"


def test_multi_page_marker_on_second_page_is_counted(tmp_path):
    base = write_pdf_raw(tmp_path / "base.pdf", b"", pages=2)
    pdf = pikepdf.open(base, allow_overwriting_input=True)
    pdf.pages[1].Contents = pikepdf.Stream(
        pdf, b"q 3 Tr BT /F1 12 Tf 100 400 Td ([DATASET_SAMPLE_ID=s2] hidden) Tj ET Q"
    )
    cand = tmp_path / "cand.pdf"
    pdf.save(cand)
    from crackedpdfs_audit.corpus import AuditTask, audit_task

    task = AuditTask(
        pdf_id="p",
        sample_id="s",
        role="injected_attack",
        family="f",
        strength="weak",
        spatial_label="inside_page",
        rendering_label="invisible_render_mode",
        path=str(cand),
        reference_path=str(base),
        reference_expected=True,
        render=False,
    )
    record = audit_task(task)
    assert record["status"] == "audited"
    assert record["pages"] == 2
    assert record["added_glyphs"] == len("[DATASET_SAMPLE_ID=s2] hidden")
    assert record["lexical_oracle_tokens"] == ["DATASET_SAMPLE_ID"]


def test_missing_pdf_and_reference_are_reported_not_skipped(tmp_path):
    from crackedpdfs_audit.corpus import AuditTask, audit_task, coverage, coverage_complete

    missing = AuditTask(
        pdf_id="p1",
        sample_id="s1",
        role="injected_attack",
        family="f",
        strength="weak",
        spatial_label="inside_page",
        rendering_label="x",
        path=str(tmp_path / "gone.pdf"),
        reference_path=None,
        reference_expected=True,
        render=False,
    )
    present = write_pdf_raw(tmp_path / "there.pdf", b"BT /F1 12 Tf 100 400 Td (hi) Tj ET")
    ref_gone = AuditTask(
        pdf_id="p2",
        sample_id="s2",
        role="injected_attack",
        family="f",
        strength="weak",
        spatial_label="inside_page",
        rendering_label="x",
        path=str(present),
        reference_path=None,
        reference_expected=True,
        render=False,
    )
    records = [audit_task(missing), audit_task(ref_gone)]
    assert records[0]["status"] == "missing"
    assert records[1]["status"] == "reference_missing"
    cov = coverage(records)
    assert cov["missing"] == 1 and cov["reference_missing"] == 1
    assert coverage_complete(cov) is False


def test_strict_mode_exits_nonzero_on_missing_pdf(tmp_path, capsys):
    root = tmp_path / "corpus"
    write_pdf(root / "benign/s1.benign.pdf")
    write_pdf(root / "benign/s1.benign-confounder.pdf", text_block(100, 400, "note", mode=3))
    # injected PDF referenced by metadata but absent on disk
    rows = []
    shared = {
        "sample_id": "s1",
        "target_attack_family": "in_page_invisible_text",
        "target_physical_attack_strength": "weak",
        "target_physical_spatial_regime": "inside_page",
        "target_physical_rendering_regime": "invisible_render_mode",
        "confounder_physical_attack_strength": "weak",
        "confounder_physical_spatial_regime": "inside_page",
        "confounder_physical_rendering_regime": "invisible_render_mode",
    }
    rows += [
        {**shared, "pdf_id": "s1.benign", "pdf_role": "benign_original", "file_path": "benign/s1.benign.pdf"},
        {
            **shared,
            "pdf_id": "s1.benign_confounder",
            "pdf_role": "benign_confounder",
            "file_path": "benign/s1.benign-confounder.pdf",
        },
        {
            **shared,
            "pdf_id": "s1.injected",
            "pdf_role": "injected_attack",
            "file_path": "injected/s1.injected.pdf",
        },
    ]
    metadata = tmp_path / "metadata.jsonl"
    metadata.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    code = main(
        [
            "corpus",
            "--root",
            str(root),
            "--metadata",
            str(metadata),
            "--out",
            str(tmp_path / "out"),
            "--workers",
            "1",
            "--strict",
        ]
    )
    assert code == 2
    assert (tmp_path / "out" / "placement-audit-coverage.json").exists()


def two_page_pdf(path: Path, page2_extra: bytes = b"") -> Path:
    pdf = pikepdf.new()
    for _ in range(2):
        pdf.add_blank_page(page_size=(612, 792))
    for index, page in enumerate(pdf.pages):
        page.Resources = pikepdf.Dictionary(
            Font=pikepdf.Dictionary(
                F1=pikepdf.Dictionary(
                    Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica
                )
            )
        )
        body = b"BT /F1 12 Tf 72 700 Td (Body) Tj ET"
        page.Contents = pikepdf.Stream(
            pdf, body + (b"\n" + page2_extra if index == 1 and page2_extra else b"")
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.save(path)
    return path


def audit_pair(
    candidate: Path,
    reference: Path | None,
    label: str = "inside_page",
    render: bool = False,
    require_reference: bool = True,
):
    from crackedpdfs_audit.corpus import AuditTask, audit_task

    task = AuditTask(
        pdf_id="p",
        sample_id="s",
        role="injected_attack",
        family="f",
        strength="weak",
        spatial_label=label,
        rendering_label="invisible_render_mode",
        path=str(candidate),
        reference_path=str(reference) if reference else None,
        reference_expected=reference is not None,
        render=render,
        require_reference=require_reference,
    )
    return audit_task(task)


def test_unchanged_pages_do_not_count_as_placement_failures(tmp_path):
    base = two_page_pdf(tmp_path / "base.pdf")
    cand = two_page_pdf(tmp_path / "cand.pdf", b"q 3 Tr BT /F1 12 Tf 100 400 Td (hidden inside) Tj ET Q")
    record = audit_pair(cand, base)
    assert record["status"] == "audited"
    assert record["payload_pages"] == [2]
    assert record["contract_satisfied"] is True
    assert record["added_realized_spatial_class"] == "inside_page"


def test_contract_fails_when_any_payload_page_violates(tmp_path):
    base = two_page_pdf(tmp_path / "base.pdf")
    cand = two_page_pdf(tmp_path / "cand.pdf", b"q 3 Tr BT /F1 12 Tf 10000 10000 Td (off page) Tj ET Q")
    record = audit_pair(cand, base)
    assert record["contract_satisfied"] is False


def test_no_added_glyphs_is_an_explicit_absent_payload_result(tmp_path):
    base = two_page_pdf(tmp_path / "base.pdf")
    same = two_page_pdf(tmp_path / "same.pdf")
    record = audit_pair(same, base)
    assert record["status"] == "no_payload_detected"
    assert record["contract_satisfied"] is None
    assert record["payload_pages"] == []


def test_missing_original_metadata_row_is_a_reference_error(tmp_path):
    from crackedpdfs_audit.corpus import build_tasks, coverage, coverage_complete, run_audit

    root = tmp_path / "corpus"
    two_page_pdf(root / "injected/s1.injected.pdf", b"q 3 Tr BT /F1 12 Tf 100 400 Td (x) Tj ET Q")
    rows = [
        {
            "sample_id": "s1",
            "pdf_id": "s1.injected",
            "pdf_role": "injected_attack",
            "file_path": "injected/s1.injected.pdf",
            "target_attack_family": "f",
            "target_physical_attack_strength": "weak",
            "target_physical_spatial_regime": "inside_page",
            "target_physical_rendering_regime": "invisible_render_mode",
        }
    ]
    records = list(run_audit(build_tasks(rows, root), workers=1))
    assert records[0]["status"] == "reference_missing"
    assert "no benign_original metadata row" in records[0]["error"]
    assert records[0].get("added_glyphs") is None
    assert coverage_complete(coverage(records)) is False


def test_unpaired_mode_is_explicit(tmp_path):
    from crackedpdfs_audit.corpus import build_tasks, run_audit

    root = tmp_path / "corpus"
    two_page_pdf(root / "injected/s1.injected.pdf", b"q 3 Tr BT /F1 12 Tf 100 400 Td (x) Tj ET Q")
    rows = [
        {
            "sample_id": "s1",
            "pdf_id": "s1.injected",
            "pdf_role": "injected_attack",
            "file_path": "injected/s1.injected.pdf",
            "target_attack_family": "f",
            "target_physical_attack_strength": "weak",
            "target_physical_spatial_regime": "inside_page",
            "target_physical_rendering_regime": "invisible_render_mode",
        }
    ]
    records = list(run_audit(build_tasks(rows, root, paired=False), workers=1))
    assert records[0]["status"] == "audited"
    assert records[0]["paired"] is False
    # Without a reference, existing document text counts as added text, so the
    # unpaired count exceeds the single injected glyph.
    assert records[0]["added_glyphs"] == len("Body") * 2 + len("x")


def test_pixel_diff_covers_every_page(tmp_path):
    base = two_page_pdf(tmp_path / "base.pdf")
    visible = two_page_pdf(
        tmp_path / "vis.pdf", b"q 0 Tr BT /F1 24 Tf 100 400 Td (VISIBLE ON PAGE TWO) Tj ET Q"
    )
    diff = pixel_diff(visible, base)
    assert diff is not None
    assert diff.compared_pages == 2
    assert diff.changed_pixels_by_page[0] == 0
    assert diff.changed_pixels_by_page[1] > 0
    assert diff.changed_pixels == sum(diff.changed_pixels_by_page)
    assert diff.page_count_mismatch is False


def test_pixel_diff_reports_page_count_mismatch(tmp_path):
    base = two_page_pdf(tmp_path / "base.pdf")
    one = write_pdf(tmp_path / "one.pdf")
    diff = pixel_diff(one, base)
    assert diff is not None
    assert diff.page_count_mismatch is True
    assert diff.compared_pages == 1
