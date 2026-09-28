import importlib
import re
import sys
import tempfile
import unittest
import zipfile
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


ROOT = Path(__file__).parents[1]
SKILL_DIR = ROOT / "ashare-fundamentals"
SKILL_SCRIPTS_DIR = SKILL_DIR / "scripts"


def load_script(name: str):
    path = ROOT / "ashare-fundamentals" / "scripts" / name
    spec = spec_from_file_location(name.replace(".py", ""), path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_root_script(name: str):
    path = ROOT / "scripts" / name
    spec = spec_from_file_location(name.replace(".py", ""), path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def declared_version() -> str:
    """Read the version from SKILL.md so bumping it cannot break this suite."""
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r'(?m)^\s*version:\s*"?(\d+\.\d+\.\d+)"?\s*$', text)
    assert match is not None, "SKILL.md is missing a semantic version"
    return match.group(1)


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
            self.assertIn(f"version: {declared_version()}", skill)
            self.assertIn("author: Deng Yishuo", skill)


class SkillIntegrityTests(unittest.TestCase):
    """Keep the packaged skill internally consistent.

    ``python -m compileall`` only checks syntax and never resolves imports, and
    the tests above load scripts one by one by path, so a stale sibling module
    name used to pass CI and only blow up when a user ran the command.
    """

    def test_every_script_imports(self):
        scripts = sorted(SKILL_SCRIPTS_DIR.glob("*.py"))
        self.assertTrue(scripts, f"no scripts found in {SKILL_SCRIPTS_DIR}")

        sys.path.insert(0, str(SKILL_SCRIPTS_DIR))
        try:
            for script in scripts:
                with self.subTest(script=script.name):
                    importlib.import_module(script.stem)
        finally:
            sys.path.remove(str(SKILL_SCRIPTS_DIR))

    def test_skill_md_only_references_existing_scripts(self):
        skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        referenced = sorted(set(re.findall(r"scripts/([A-Za-z0-9_]+\.py)", skill_md)))
        self.assertTrue(referenced, "SKILL.md does not reference any script")
        for name in referenced:
            with self.subTest(script=name):
                self.assertTrue(
                    (SKILL_SCRIPTS_DIR / name).is_file(),
                    f"SKILL.md references a missing script: {name}",
                )

    def test_skill_md_only_references_existing_docs(self):
        skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        referenced = sorted(set(re.findall(r"references/([A-Za-z0-9_.-]+)", skill_md)))
        self.assertTrue(referenced, "SKILL.md does not reference any reference doc")
        for name in referenced:
            with self.subTest(reference=name):
                self.assertTrue(
                    (SKILL_DIR / "references" / name).is_file(),
                    f"SKILL.md references a missing document: {name}",
                )


if __name__ == "__main__":
    unittest.main()
