import importlib.util
from pathlib import Path
import unittest

import pikepdf


def load_inject_policy_module():
    module_path = Path(__file__).with_name("inject_policy.py")
    spec = importlib.util.spec_from_file_location("inject_policy", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INJECT_POLICY = load_inject_policy_module()


def stream_bytes(stream_obj) -> bytes:
    return stream_obj.read_bytes()


class StructuralPlacementTests(unittest.TestCase):
    def create_pdf_with_single_stream(self, content: bytes):
        pdf = pikepdf.new()
        pdf.add_blank_page(page_size=(612, 792))
        page = pdf.pages[0]
        page.Contents = pikepdf.Stream(pdf, content)
        return pdf, page

    def create_pdf_with_stream_array(self, contents: list[bytes]):
        pdf = pikepdf.new()
        pdf.add_blank_page(page_size=(612, 792))
        page = pdf.pages[0]
        streams = [pikepdf.Stream(pdf, chunk) for chunk in contents]
        page.Contents = pikepdf.Array(streams)
        return pdf, page

    def test_append_new_stream_appends_after_isolated_original(self):
        pdf, page = self.create_pdf_with_single_stream(b"OLD")

        INJECT_POLICY._apply_structural_placement(
            page, pdf, b"NEW", "append_new_stream"
        )

        # Original content is bracketed in a balanced q/Q so its graphics state
        # cannot leak into the appended text.
        self.assertIsInstance(page.Contents, pikepdf.Array)
        self.assertEqual(len(page.Contents), 3)
        self.assertEqual(stream_bytes(page.Contents[0]), b"q")
        self.assertEqual(stream_bytes(page.Contents[1]), b"OLD")
        self.assertEqual(stream_bytes(page.Contents[2]), b"Q\nNEW")

    def test_prepend_stream_inserts_at_start(self):
        pdf, page = self.create_pdf_with_single_stream(b"OLD")

        INJECT_POLICY._apply_structural_placement(page, pdf, b"NEW", "prepend_stream")

        self.assertIsInstance(page.Contents, pikepdf.Array)
        self.assertEqual(len(page.Contents), 2)
        self.assertEqual(stream_bytes(page.Contents[0]), b"NEW")
        self.assertEqual(stream_bytes(page.Contents[1]), b"OLD")

    def test_prepend_stream_inserts_at_start_for_stream_array(self):
        pdf, page = self.create_pdf_with_stream_array([b"FIRST", b"SECOND"])

        INJECT_POLICY._apply_structural_placement(page, pdf, b"NEW", "prepend_stream")

        self.assertIsInstance(page.Contents, pikepdf.Array)
        self.assertEqual(len(page.Contents), 3)
        self.assertEqual(stream_bytes(page.Contents[0]), b"NEW")
        self.assertEqual(stream_bytes(page.Contents[1]), b"FIRST")
        self.assertEqual(stream_bytes(page.Contents[2]), b"SECOND")

    def test_inject_into_existing_stream_merges_single_stream(self):
        pdf, page = self.create_pdf_with_single_stream(b"OLD")

        INJECT_POLICY._apply_structural_placement(
            page, pdf, b"NEW", "inject_into_existing_stream"
        )

        # A leading q isolates the original; the injected bytes stay inside the
        # trailing content stream, closed by Q immediately before them.
        self.assertIsInstance(page.Contents, pikepdf.Array)
        self.assertEqual(len(page.Contents), 2)
        self.assertEqual(stream_bytes(page.Contents[0]), b"q")
        merged = stream_bytes(page.Contents[1])
        self.assertEqual(merged, b"OLD\nQ\nNEW")

    def test_inject_into_existing_stream_merges_last_stream_in_array(self):
        pdf, page = self.create_pdf_with_stream_array([b"FIRST", b"SECOND"])

        INJECT_POLICY._apply_structural_placement(
            page, pdf, b"NEW", "inject_into_existing_stream"
        )

        self.assertIsInstance(page.Contents, pikepdf.Array)
        self.assertEqual(len(page.Contents), 3)
        self.assertEqual(stream_bytes(page.Contents[0]), b"q")
        self.assertEqual(stream_bytes(page.Contents[1]), b"FIRST")
        self.assertEqual(stream_bytes(page.Contents[2]), b"SECOND\nQ\nNEW")


if __name__ == "__main__":
    unittest.main()
