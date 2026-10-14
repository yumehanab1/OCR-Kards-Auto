"""Self-contained pixel tests: no device, file capture, or input dispatch."""
import unittest

import cv2
import numpy as np

import apk_enemy_turn as label


class OpponentTurnLabelTests(unittest.TestCase):
    def sample(self, layout="compact"):
        frame = np.zeros((720, 1280, 3), np.uint8)
        spec = label._LAYOUTS[layout]
        for x0, y0, x1, y1 in spec["edges"]:
            frame[y0:y1, x0:x1] = 137
        x0, y0, x1, y1 = spec["glyph"]
        frame[y0:y1, x0:x1] = cv2.cvtColor(label._template(layout), cv2.COLOR_GRAY2BGR)
        return frame

    def test_embedded_template_decodes_without_resource_paths(self):
        for layout, shape in (("compact", (27, 54)), ("standard", (37, 71))):
            with self.subTest(layout=layout):
                self.assertEqual(label._template(layout).shape, shape)
                result = label.inspect_opponent_turn(self.sample(layout))
                self.assertTrue(result["present"])
                self.assertEqual(result["layout"], layout)

    def test_black_frame_has_no_positive_marker(self):
        self.assertFalse(label.inspect_opponent_turn(np.zeros((720, 1280, 3), np.uint8))["present"])

    def test_wrong_geometry_or_type_is_unknown(self):
        for frame in (None, np.zeros((1080, 1920, 3), np.uint8), np.zeros((720, 1280, 3), np.float32)):
            with self.subTest(shape=getattr(frame, "shape", None)):
                self.assertFalse(label.inspect_opponent_turn(frame)["present"])

    def test_label_at_wrong_location_is_unknown(self):
        for layout in label._LAYOUTS:
            self.assertFalse(label.inspect_opponent_turn(
                np.roll(self.sample(layout), -100, axis=1))["present"])

    def test_each_character_and_each_border_is_required(self):
        for layout, spec in label._LAYOUTS.items():
            x0, y0, x1, y1 = spec["glyph"]
            mid = x0 + spec["split"]
            boxes = ((x0, y0, mid, y1), (mid, y0, x1, y1)) + spec["edges"]
            for box in boxes:
                frame = self.sample(layout)
                x0, y0, x1, y1 = box
                frame[y0:y1, x0:x1] = 0
                with self.subTest(layout=layout, box=box):
                    self.assertFalse(label.inspect_opponent_turn(frame)["present"])

    def test_hud_digits_are_not_part_of_positive_marker(self):
        for layout in label._LAYOUTS:
            frame = self.sample(layout)
            frame[80:160, :100] = (0, 130, 240)
            frame[560:630, :100] = (0, 130, 240)
            self.assertTrue(label.inspect_opponent_turn(frame)["present"])

    def test_plain_bordered_box_is_unknown(self):
        for layout, spec in label._LAYOUTS.items():
            frame = self.sample(layout)
            x0, y0, x1, y1 = spec["glyph"]
            frame[y0:y1, x0:x1] = 30
            self.assertFalse(label.inspect_opponent_turn(frame)["present"])

    def test_conflicting_layout_markers_are_unknown(self):
        frame = np.maximum(self.sample("compact"), self.sample("standard"))
        result = label.inspect_opponent_turn(frame)
        self.assertFalse(result["present"])
        self.assertEqual(result["reason"], "conflicting_opponent_label_layouts")

    def test_standard_glyph_at_compact_position_is_unknown(self):
        frame = self.sample("compact")
        x0, y0, x1, y1 = label._LAYOUTS["compact"]["glyph"]
        wrong = cv2.resize(label._template("standard"), (x1-x0, y1-y0))
        frame[y0:y1, x0:x1] = cv2.cvtColor(wrong, cv2.COLOR_GRAY2BGR)
        self.assertFalse(label.inspect_opponent_turn(frame)["present"])

    def test_mirrored_glyphs_are_unknown(self):
        for layout, spec in label._LAYOUTS.items():
            frame = self.sample(layout)
            x0, y0, x1, y1 = spec["glyph"]
            frame[y0:y1, x0:x1] = frame[y0:y1, x0:x1][:, ::-1]
            self.assertFalse(label.inspect_opponent_turn(frame)["present"])


if __name__ == "__main__":
    unittest.main()
