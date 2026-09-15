import argparse
import json
import re
import statistics
from typing import Any, Dict, List, Optional, Tuple

import pikepdf

HARNESS_VERSION = "phase5-v2"


def _safe_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
        if parsed != parsed:  # NaN
            return None
        return parsed
    except Exception:
        return None


def _read_stream_bytes(contents_obj) -> List[bytes]:
    streams: List[bytes] = []
    try:
        if isinstance(contents_obj, pikepdf.Array):
            for stream in contents_obj:
                try:
                    streams.append(stream.read_bytes())
                except Exception:
                    continue
        else:
            streams.append(contents_obj.read_bytes())
    except Exception:
        pass
    return streams


def _get_page_dimensions(page) -> Tuple[float, float]:
    try:
        media_box = page.MediaBox
        width = float(media_box[2]) - float(media_box[0])
        height = float(media_box[3]) - float(media_box[1])
        if width > 0 and height > 0:
            return width, height
    except Exception:
        pass
    return 612.0, 792.0


def _snippet_around(raw_text: str, marker: str, context_chars: int = 80) -> Optional[str]:
    idx = raw_text.find(marker)
    if idx < 0:
        return None
    start = max(0, idx - context_chars)
    end = min(len(raw_text), idx + len(marker) + context_chars)
    return raw_text[start:end]


def _normalize_marker_text(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "", value.lower())


def _build_marker_tokens(marker: str) -> List[str]:
    tokens = re.findall(r"[A-Za-z0-9_]+", marker.lower())
    prioritized: List[str] = []

    for token in tokens:
        if (
            token == "dataset_sample_id"
            or token == "message_type"
            or token.startswith("sample_")
            or len(token) >= 8
        ):
            prioritized.append(token)

    if not prioritized:
        prioritized = [token for token in tokens if len(token) >= 5]

    deduped: List[str] = []
    seen = set()
    for token in prioritized:
        if token not in seen:
            deduped.append(token)
            seen.add(token)
    return deduped


def _build_extractor_result(
    name: str,
    extracted_text: str,
    marker: str,
    available: bool = True,
    ran: bool = True,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    marker_count = extracted_text.count(marker) if extracted_text else 0
    found_marker = marker_count > 0
    return {
        "name": name,
        "available": available,
        "ran": ran,
        "found_marker": found_marker,
        "matched_marker_count": marker_count,
        "snippet": _snippet_around(extracted_text, marker) if found_marker else None,
        "extracted_chars": len(extracted_text),
        "error": error,
    }


def _run_pypdf_text_extractor(input_pdf: str, marker: str) -> Dict[str, Any]:
    reader_cls = None
    engine = None
    import_error: Optional[str] = None

    try:
        from pypdf import PdfReader as PypdfReader  # type: ignore

        reader_cls = PypdfReader
        engine = "pypdf"
    except Exception as pypdf_exc:
        import_error = str(pypdf_exc)
        try:
            from PyPDF2 import PdfReader as PyPdf2Reader  # type: ignore

            reader_cls = PyPdf2Reader
            engine = "PyPDF2"
        except Exception as pypdf2_exc:
            return {
                "name": "pypdf_text",
                "available": False,
                "ran": False,
                "found_marker": False,
                "matched_marker_count": 0,
                "snippet": None,
                "extracted_chars": 0,
                "error": f"pypdf/PyPDF2 import failed: {import_error}; {pypdf2_exc}",
            }

    try:
        reader = reader_cls(input_pdf)  # type: ignore[misc]
        chunks: List[str] = []
        for page in reader.pages:
            try:
                chunks.append(page.extract_text() or "")
            except Exception:
                continue
        result = _build_extractor_result(
            "pypdf_text", "\n".join(chunks), marker, available=True, ran=True
        )
        result["engine"] = engine
        return result
    except Exception as exc:
        return {
            "name": "pypdf_text",
            "available": True,
            "ran": True,
            "found_marker": False,
            "matched_marker_count": 0,
            "snippet": None,
            "extracted_chars": 0,
            "error": f"Extractor execution failed: {exc}",
            "engine": engine,
        }


def _run_pdfplumber_text_extractor(input_pdf: str, marker: str) -> Dict[str, Any]:
    try:
        import pdfplumber  # type: ignore
    except Exception as exc:
        return {
            "name": "pdfplumber_text",
            "available": False,
            "ran": False,
            "found_marker": False,
            "matched_marker_count": 0,
            "snippet": None,
            "extracted_chars": 0,
            "error": f"pdfplumber import failed: {exc}",
        }

    try:
        chunks: List[str] = []
        with pdfplumber.open(input_pdf) as pdf:
            for page in pdf.pages:
                try:
                    chunks.append(page.extract_text() or "")
                except Exception:
                    continue
        return _build_extractor_result(
            "pdfplumber_text", "\n".join(chunks), marker, available=True, ran=True
        )
    except Exception as exc:
        return {
            "name": "pdfplumber_text",
            "available": True,
            "ran": True,
            "found_marker": False,
            "matched_marker_count": 0,
            "snippet": None,
            "extracted_chars": 0,
            "error": f"Extractor execution failed: {exc}",
        }


def _evaluate_extractor_matrix(
    extractor_results: List[Dict[str, Any]], expected_raw: bool
) -> Dict[str, Any]:
    ran_extractors = [entry for entry in extractor_results if entry.get("ran")]
    available_extractors = [entry for entry in extractor_results if entry.get("available")]
    positive_extractors = [
        entry for entry in ran_extractors if bool(entry.get("found_marker"))
    ]
    negative_extractors = [
        entry for entry in ran_extractors if not bool(entry.get("found_marker"))
    ]

    ran_count = len(ran_extractors)
    positive_count = len(positive_extractors)
    min_extractors_required = 2

    if ran_count < min_extractors_required:
        passed = False
        reason = "insufficient_extractors_ran"
    elif expected_raw:
        passed = positive_count >= 1
        reason = "marker_detected_by_matrix" if passed else "marker_not_detected_by_matrix"
    else:
        passed = positive_count == 0
        reason = (
            "marker_absent_in_all_extractors"
            if passed
            else "marker_unexpectedly_detected_by_extractors"
        )

    return {
        "passed": passed,
        "reason": reason,
        "expected_found_marker": expected_raw,
        "min_extractors_required": min_extractors_required,
        "available_extractors": len(available_extractors),
        "ran_extractors": ran_count,
        "positive_extractors": positive_count,
        "negative_extractors": len(negative_extractors),
        "found_by": [entry.get("name") for entry in positive_extractors],
        "missed_by": [entry.get("name") for entry in negative_extractors],
        "extractors": extractor_results,
    }


def _run_renderer_visibility_check(input_pdf: str, marker: str, dpi: int = 200) -> Dict[str, Any]:
    marker_tokens = _build_marker_tokens(marker)
    normalized_marker = _normalize_marker_text(marker)
    token_threshold = 2 if len(marker_tokens) >= 2 else 1

    result: Dict[str, Any] = {
        "ran": False,
        "engine": "pymupdf+pytesseract",
        "dpi": dpi,
        "pages_scanned": 0,
        "marker_visible": False,
        "visible_pages": [],
        "marker_tokens": marker_tokens,
        "token_threshold": token_threshold,
        "page_evidence": [],
        "error": None,
    }

    try:
        import pymupdf as fitz  # type: ignore
        from PIL import Image  # type: ignore
        import pytesseract  # type: ignore
    except Exception as exc:
        result["error"] = f"Renderer dependencies unavailable: {exc}"
        return result

    try:
        scale = max(72, int(dpi)) / 72.0
        matrix = fitz.Matrix(scale, scale)
        with fitz.open(input_pdf) as doc:
            for page_index in range(len(doc)):
                page = doc[page_index]
                pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB, alpha=False)
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

                data = pytesseract.image_to_data(
                    image,
                    config="--psm 6",
                    output_type=pytesseract.Output.DICT,
                )

                words: List[str] = []
                confidences: List[float] = []
                texts = data.get("text", [])
                confs = data.get("conf", [])
                for idx, token in enumerate(texts):
                    value = str(token).strip()
                    if not value:
                        continue
                    words.append(value)
                    if idx < len(confs):
                        conf = _safe_float(confs[idx])
                        if conf is not None and conf >= 0:
                            confidences.append(conf)

                joined_text = " ".join(words)
                normalized_text = _normalize_marker_text(joined_text)

                full_marker_match = bool(normalized_marker) and (
                    normalized_marker in normalized_text
                )
                matched_tokens = [
                    token
                    for token in marker_tokens
                    if _normalize_marker_text(token) in normalized_text
                ]
                visible = full_marker_match or len(matched_tokens) >= token_threshold
                mean_conf = (
                    round(statistics.fmean(confidences), 2) if confidences else None
                )

                if visible:
                    result["visible_pages"].append(page_index + 1)
                    result["marker_visible"] = True

                if full_marker_match or matched_tokens:
                    result["page_evidence"].append(
                        {
                            "page": page_index + 1,
                            "full_marker_match": full_marker_match,
                            "matched_tokens": matched_tokens,
                            "ocr_excerpt": joined_text[:320] if joined_text else None,
                            "ocr_word_count": len(words),
                            "ocr_mean_confidence": mean_conf,
                        }
                    )

                result["pages_scanned"] += 1

        result["ran"] = True
        return result
    except Exception as exc:
        result["error"] = f"Renderer visibility check failed: {exc}"
        return result


def _is_white(color: Optional[Tuple[float, float, float]]) -> bool:
    if not color:
        return False
    return all(channel >= 0.99 for channel in color)


def _infer_hidden(
    render_mode: Optional[int],
    color: Optional[Tuple[float, float, float]],
    font_size: Optional[float],
    x: Optional[float],
    y: Optional[float],
    page_w: float,
    page_h: float,
) -> Tuple[bool, List[str]]:
    reasons: List[str] = []

    if render_mode == 3:
        reasons.append("render_mode_3")

    if (
        x is not None
        and y is not None
        and (x < 0 or y < 0 or x > page_w or y > page_h)
    ):
        reasons.append("off_page_coordinates")

    if _is_white(color):
        reasons.append("white_text")

    if font_size is not None and font_size <= 2.0:
        reasons.append("tiny_font")

    return (len(reasons) > 0, reasons)


def _detect_marker_instances(
    page,
    marker: str,
    page_index: int,
) -> Tuple[List[Dict[str, Any]], int]:
    instances: List[Dict[str, Any]] = []
    parse_errors = 0

    page_w, page_h = _get_page_dimensions(page)
    contents_obj = page.Contents
    if contents_obj is None:
        return instances, parse_errors

    for data in _read_stream_bytes(contents_obj):
        decoded = data.decode("latin1", errors="ignore")
        cursor = 0
        while True:
            marker_index = decoded.find(marker, cursor)
            if marker_index < 0:
                break

            prefix = decoded[max(0, marker_index - 1200):marker_index]

            render_mode = _extract_last_render_mode(prefix)
            color = _extract_last_color(prefix)
            font_size = _extract_last_font_size(prefix)
            x, y = _extract_last_coordinates(prefix)

            inferred_hidden, hidden_reasons = _infer_hidden(
                render_mode, color, font_size, x, y, page_w, page_h
            )

            instances.append(
                {
                    "page": page_index + 1,
                    "x": x,
                    "y": y,
                    "page_width": page_w,
                    "page_height": page_h,
                    "render_mode": render_mode,
                    "font_size": font_size,
                    "color": list(color) if color else None,
                    "inferred_hidden": inferred_hidden,
                    "hidden_reasons": hidden_reasons,
                }
            )

            cursor = marker_index + len(marker)

    return instances, parse_errors


def _extract_last_render_mode(prefix: str) -> Optional[int]:
    match = _find_last_match(r"([0-7])\s+Tr\b", prefix)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _extract_last_color(prefix: str) -> Optional[Tuple[float, float, float]]:
    match = _find_last_match(
        r"([+-]?[0-9]*\.?[0-9]+)\s+([+-]?[0-9]*\.?[0-9]+)\s+([+-]?[0-9]*\.?[0-9]+)\s+rg\b",
        prefix,
    )
    if not match:
        return None
    r = _safe_float(match.group(1))
    g = _safe_float(match.group(2))
    b = _safe_float(match.group(3))
    if r is None or g is None or b is None:
        return None
    return (r, g, b)


def _extract_last_font_size(prefix: str) -> Optional[float]:
    match = _find_last_match(
        r"/[A-Za-z0-9_.-]+\s+([+-]?[0-9]*\.?[0-9]+)\s+Tf\b",
        prefix,
    )
    if not match:
        return None
    return _safe_float(match.group(1))


def _extract_last_coordinates(prefix: str) -> Tuple[Optional[float], Optional[float]]:
    td_match = _find_last_match(
        r"([+-]?[0-9]*\.?[0-9]+)\s+([+-]?[0-9]*\.?[0-9]+)\s+Td\b",
        prefix,
    )
    tm_match = _find_last_match(
        r"[+-]?[0-9]*\.?[0-9]+\s+[+-]?[0-9]*\.?[0-9]+\s+[+-]?[0-9]*\.?[0-9]+\s+[+-]?[0-9]*\.?[0-9]+\s+([+-]?[0-9]*\.?[0-9]+)\s+([+-]?[0-9]*\.?[0-9]+)\s+Tm\b",
        prefix,
    )

    td_pos = td_match.start() if td_match else -1
    tm_pos = tm_match.start() if tm_match else -1

    best = td_match if td_pos >= tm_pos else tm_match
    if not best:
        return None, None

    x = _safe_float(best.group(1))
    y = _safe_float(best.group(2))
    return x, y


def _find_last_match(pattern: str, text: str) -> Optional[re.Match]:
    match: Optional[re.Match] = None
    for candidate in re.finditer(pattern, text):
        match = candidate
    return match


def _evaluate_render_visibility(
    *,
    expected_raw: bool,
    found_marker: bool,
    all_instances: List[Dict[str, Any]],
    renderer_evidence: Dict[str, Any],
) -> Tuple[bool, str, str]:
    visible_instances = [entry for entry in all_instances if not entry["inferred_hidden"]]
    renderer_ran = bool(renderer_evidence.get("ran"))
    renderer_visible = bool(renderer_evidence.get("marker_visible"))

    operator_hidden_passed = (
        len(all_instances) > 0 and len(visible_instances) == 0
        if expected_raw
        else not found_marker
    )

    operator_failure_reason = (
        "marker_text_not_detected_in_parsed_operations"
        if expected_raw and len(all_instances) == 0
        else "marker_instances_may_be_visible"
    )

    if renderer_ran:
        if renderer_visible:
            return False, "renderer_detected_visible_marker", "renderer+operator_inference"
        if not operator_hidden_passed:
            return False, operator_failure_reason, "renderer+operator_inference"
        return True, "renderer_and_operator_checks_passed", "renderer+operator_inference"

    if not operator_hidden_passed:
        return False, operator_failure_reason, "operator_inference_only"
    return True, "operator_inference_passed_renderer_unavailable", "operator_inference_only"


def run_validation(
    input_pdf: str, marker: str, expected_raw: bool, skip_renderer: bool = False
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "success": False,
        "harness_version": HARNESS_VERSION,
        "pdf_path": input_pdf,
        "expected_marker": marker,
        "expected_raw_extraction": expected_raw,
        "raw_extraction_check": {
            "passed": False,
            "found_marker": False,
            "expected_found_marker": expected_raw,
            "matched_marker_count": 0,
            "snippet": None,
        },
        "extractor_matrix_check": {
            "passed": False,
            "reason": "not_run",
            "expected_found_marker": expected_raw,
            "min_extractors_required": 2,
            "available_extractors": 0,
            "ran_extractors": 0,
            "positive_extractors": 0,
            "negative_extractors": 0,
            "found_by": [],
            "missed_by": [],
            "extractors": [],
        },
        "render_visibility_check": {
            "passed": False,
            "reason": "not_run",
            "mode": "renderer+operator_inference",
            "marker_instances": 0,
            "inferred_hidden_instances": 0,
            "inferred_visible_instances": 0,
            "evidence": [],
            "renderer_evidence": {
                "ran": False,
                "engine": "pymupdf+pytesseract",
                "dpi": 200,
                "pages_scanned": 0,
                "marker_visible": False,
                "visible_pages": [],
                "marker_tokens": [],
                "token_threshold": 2,
                "page_evidence": [],
                "error": "not_run",
            },
        },
        "parse_errors": 0,
    }

    try:
        pdf = pikepdf.open(input_pdf)
    except Exception as exc:
        result["error"] = f"Failed to open PDF: {exc}"
        return result

    raw_chunks: List[str] = []
    marker_count = 0
    all_instances: List[Dict[str, Any]] = []
    parse_errors = 0

    for page_index, page in enumerate(pdf.pages):
        contents_obj = page.Contents if "/Contents" in page else None
        if contents_obj is not None:
            for data in _read_stream_bytes(contents_obj):
                decoded = data.decode("latin1", errors="ignore")
                raw_chunks.append(decoded)
                marker_count += decoded.count(marker)

        instances, local_errors = _detect_marker_instances(page, marker, page_index)
        all_instances.extend(instances)
        parse_errors += local_errors

    raw_text = "\n".join(raw_chunks)
    found_marker = marker_count > 0
    snippet = _snippet_around(raw_text, marker)

    raw_result = {
        "passed": found_marker == expected_raw,
        "found_marker": found_marker,
        "expected_found_marker": expected_raw,
        "matched_marker_count": marker_count,
        "snippet": snippet,
    }
    result["raw_extraction_check"] = raw_result

    extractor_results: List[Dict[str, Any]] = [
        _build_extractor_result("raw_stream", raw_text, marker, available=True, ran=True),
        _run_pypdf_text_extractor(input_pdf, marker),
        _run_pdfplumber_text_extractor(input_pdf, marker),
    ]
    extractor_matrix = _evaluate_extractor_matrix(extractor_results, expected_raw)
    result["extractor_matrix_check"] = extractor_matrix

    hidden_instances = [entry for entry in all_instances if entry["inferred_hidden"]]
    visible_instances = [entry for entry in all_instances if not entry["inferred_hidden"]]
    if skip_renderer:
        renderer_evidence = {
            "ran": False,
            "engine": "pymupdf+pytesseract",
            "dpi": 200,
            "pages_scanned": 0,
            "marker_visible": False,
            "visible_pages": [],
            "marker_tokens": _build_marker_tokens(marker),
            "token_threshold": 2,
            "page_evidence": [],
            "error": "renderer_check_skipped",
        }
        render_passed = True
        render_reason = "renderer_check_skipped"
        render_mode = "skipped"
    else:
        renderer_evidence = _run_renderer_visibility_check(input_pdf, marker)
        render_passed, render_reason, render_mode = _evaluate_render_visibility(
            expected_raw=expected_raw,
            found_marker=found_marker,
            all_instances=all_instances,
            renderer_evidence=renderer_evidence,
        )

    result["render_visibility_check"] = {
        "passed": render_passed,
        "reason": render_reason,
        "mode": render_mode,
        "marker_instances": len(all_instances),
        "inferred_hidden_instances": len(hidden_instances),
        "inferred_visible_instances": len(visible_instances),
        "evidence": all_instances[:10],
        "renderer_evidence": renderer_evidence,
    }

    result["parse_errors"] = parse_errors
    result["success"] = True
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate injection survivability and visibility.")
    parser.add_argument("--input", required=True, help="Path to PDF to validate")
    parser.add_argument("--marker", required=True, help="Expected marker text")
    parser.add_argument(
        "--expected-raw",
        required=True,
        choices=["true", "false"],
        help="Whether raw extraction is expected to contain marker",
    )
    parser.add_argument(
        "--skip-renderer",
        action="store_true",
        help="Skip OCR-based renderer visibility checks",
    )
    args = parser.parse_args()

    payload = run_validation(
        input_pdf=args.input,
        marker=args.marker,
        expected_raw=args.expected_raw == "true",
        skip_renderer=args.skip_renderer,
    )
    print(json.dumps(payload))
