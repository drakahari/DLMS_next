import unittest
from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms

class RemainingRoadmapFeatureTests(unittest.TestCase):
    def test_printable_chunks_three_cards_per_sheet(self):
        rows = [{"front": str(i), "back": str(i)} for i in range(7)]
        chunks = dlms._chunk_printable_cards(rows, 3)
        self.assertEqual([len(x) for x in chunks], [3, 3, 1])

    def test_printable_long_edge_keeps_order(self):
        cards = [{"front": x} for x in "ABC"]
        self.assertEqual(dlms._printable_back_sheet(cards, "long"), cards)

    def test_printable_short_edge_reverses_back_order(self):
        cards = [{"front": x} for x in "ABC"]
        self.assertEqual([x["front"] for x in dlms._printable_back_sheet(cards, "short")], ["C", "B", "A"])

    def test_matching_script_exposes_drag_and_dropdown_modes(self):
        from pathlib import Path
        text = (Path(dlms.__file__).parent / "static" / "script.js").read_text(encoding="utf-8")
        self.assertIn('setMatchingInteractionMode', text)
        self.assertIn('data-match-answer', text)
        self.assertIn('data-match-target', text)
        self.assertIn('Dropdowns', text)

if __name__ == "__main__":
    unittest.main()
