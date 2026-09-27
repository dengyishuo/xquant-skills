from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


def load_script(name: str):
    path = ROOT / "ashare-fundamentals" / "scripts" / name
    spec = spec_from_file_location(name.replace(".py", ""), path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class HelperTests(unittest.TestCase):
    def test_normalize_listing_date(self):
        module = load_script("fetch_universe.py")
        self.assertEqual(module.normalize_date(19910403), "1991-04-03")
        self.assertEqual(module.normalize_date(None), "")

    def test_frequency_from_report_date(self):
        module = load_script("import_mysql.py")
        self.assertEqual(module.frequency({"REPORT_DATE": "2025-12-31"}), "annual")
        self.assertEqual(module.frequency({"REPORT_DATE": "2026-06-30"}), "q2")

    def test_inventory_classification(self):
        module = load_script("inventory.py")
        self.assertEqual(
            module.classify(Path("annual/balance_sheet/2025.parquet")),
            "balance_sheet",
        )
        self.assertEqual(
            module.classify(Path("indicators/annual/2025.parquet")),
            "main_financial_indicator",
        )


if __name__ == "__main__":
    unittest.main()
