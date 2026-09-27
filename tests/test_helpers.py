from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import tempfile
import unittest
import zipfile


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

    def test_portable_package_has_skill_at_root(self):
        module = load_root_script("build_skill_package.py")
        with tempfile.TemporaryDirectory() as temp_dir:
            package = module.build(ROOT / "ashare-fundamentals", Path(temp_dir))
            with zipfile.ZipFile(package) as archive:
                names = archive.namelist()
            self.assertIn("SKILL.md", names)
            self.assertIn("scripts/download_statements.py", names)
            self.assertIn("references/platforms.md", names)
            self.assertNotIn(".DS_Store", names)

    def test_workbuddy_package_has_required_metadata(self):
        module = load_root_script("build_skill_package.py")
        with tempfile.TemporaryDirectory() as temp_dir:
            package = module.build(
                ROOT / "ashare-fundamentals", Path(temp_dir), "workbuddy"
            )
            with zipfile.ZipFile(package) as archive:
                skill = archive.read("SKILL.md").decode("utf-8")
            self.assertIn("description_zh:", skill)
            self.assertIn("description_en:", skill)
            self.assertIn("version: 0.2.0", skill)
            self.assertIn("author: Deng Yishuo", skill)


def load_root_script(name: str):
    path = ROOT / "scripts" / name
    spec = spec_from_file_location(name.replace(".py", ""), path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
