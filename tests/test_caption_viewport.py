import tempfile
import unittest
from pathlib import Path

from autoeditor import pipeline


class CaptionViewportContracts(unittest.TestCase):
    def test_tall_source_sizes_caption_band_from_delivery_viewport(self):
        from PIL import Image

        root = Path(pipeline.__file__).resolve().parent.parent
        font_file = root / "desktop/helper/renderer/WorkSans-Variable.ttf"
        words = [
            {"w": "Readable", "s": 0.0, "e": 0.4},
            {"w": "caption.", "s": 0.4, "e": 0.8},
        ]
        with tempfile.TemporaryDirectory() as td:
            band = pipeline.build_caption_band(
                words,
                Path(td),
                str(font_file),
                720,
                1920,
                "30",
                0.8,
                scale=0.062,
                max_words=3,
                safe_width=720.0,
                reference_height=1280.0,
            )
            state = sorted(Path(band["seq"]).glob("state_*.png"))[0]
            with Image.open(state) as frame:
                frame_height = frame.height

        caption_y = pipeline._caption_lane_y(
            320.0, 1280.0, frame_height, "upper"
        )
        subject_top = 320.0 + 1280.0 * 0.26
        self.assertEqual(frame_height, int(int(1280 * 0.062) * 2.2))
        self.assertLessEqual(caption_y + frame_height, subject_top)

    def test_production_caption_paths_use_delivery_view_height(self):
        source = Path(pipeline.__file__).read_text(encoding="utf-8")
        self.assertIn(
            "safe_width=caption_safe_width, reference_height=view_height",
            source,
        )
        self.assertEqual(source.count("reference_height=view_height"), 2)


if __name__ == "__main__":
    unittest.main()
