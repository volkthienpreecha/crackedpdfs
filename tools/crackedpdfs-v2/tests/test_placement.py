import numpy as np

from crackedpdfs_v2.placement import blank_anchors, estimate_lines


def page_with_text_except(blank_rows: tuple[int, int], size=(792, 612)) -> np.ndarray:
    """A 1 px/pt page full of 'text' rows except for one blank band."""
    gray = np.full(size, 255, dtype=np.uint8)
    for row in range(40, size[0] - 40, 14):
        gray[row : row + 8, 60:550] = 0
    gray[blank_rows[0] : blank_rows[1], :] = 255
    return gray


def test_anchor_lands_in_the_only_blank_band():
    gray = page_with_text_except((500, 640))
    anchors = blank_anchors(gray, (612, 792), text_length=200, font_size=10, steps=40)
    best = anchors[0]
    assert best.ink == 0
    # The first baseline sits inside the band (rows 500-640 from the top).
    baseline_from_top = 792 * (1 - best.y)
    assert 500 < baseline_from_top < 640


def test_a_full_page_reports_ink_everywhere():
    gray = page_with_text_except((0, 0))
    anchors = blank_anchors(gray, (612, 792), text_length=300, font_size=10)
    assert all(a.ink > 0 for a in anchors)


def test_estimate_lines_grows_with_text():
    assert estimate_lines(50, 10, 400) < estimate_lines(400, 10, 400)
