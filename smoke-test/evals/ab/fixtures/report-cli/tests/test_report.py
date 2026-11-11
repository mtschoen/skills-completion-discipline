import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import report


class RenderTextTest(unittest.TestCase):
    def test_renders_one_line_per_row(self):
        rows = [{"name": "Alder", "region": "north", "amount": "120.50"}]
        self.assertIn("Alder", report.render_text(rows))


if __name__ == "__main__":
    unittest.main()
