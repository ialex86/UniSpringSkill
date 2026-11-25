"""Run: python3 -m unittest discover -s tests -v"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check-localization.py"
CONFIG = {"localization": {"languages": ["en", "ru"], "parityMarkers": ["[hold]"]}}


def project(tables, sources, config=CONFIG):
    root = Path(tempfile.mkdtemp())
    (root / ".claude").mkdir()
    (root / ".claude/unispring-skill.json").write_text(json.dumps(config))
    (root / "Assets/Src/Scripts").mkdir(parents=True)
    (root / "Assets/Src/Resources/Localization").mkdir(parents=True)
    for language, table in tables.items():
        (root / f"Assets/Src/Resources/Localization/{language}.json").write_text(
            json.dumps(table, ensure_ascii=False), encoding="utf-8")
    for rel, text in sources.items():
        path = root / "Assets/Src/Scripts" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def check(root):
    proc = subprocess.run([sys.executable, str(SCRIPT), "--root", str(root)], capture_output=True, text=True)
    return proc.returncode, proc.stdout


class CheckLocalizationTests(unittest.TestCase):
    def test_clean_project_passes(self):
        root = project({"en": {"a.title": "Title {0}"}, "ru": {"a.title": "Заголовок {0}"}},
                       {"A/Presentation/V.cs": 'class V { void F() { label.text = texts.Text("a.title", 1); } }'})
        code, out = check(root)
        self.assertEqual(code, 0, out)

    def test_hardcoded_text_is_reported(self):
        root = project({"en": {}, "ru": {}},
                       {"A/Presentation/V.cs": 'class V { void F() { Hud.SetStatus("Car is ready"); x = "Машина"; } }'})
        code, out = check(root)
        self.assertEqual(code, 1)
        self.assertEqual(out.count("HARDCODED"), 2, out)

    def test_logs_and_editor_code_are_not_text(self):
        root = project({"en": {}, "ru": {}}, {
            "A/Presentation/V.cs": 'class V { void F() { GameLog.Info("Car is ready now"); } }',
            "A/Editor/B.cs": 'class B { string s = "Машина"; }'})
        code, out = check(root)
        self.assertEqual(code, 0, out)

    def test_unused_missing_and_parity(self):
        root = project({"en": {"a.used": "Used", "a.unused": "Unused", "a.args": "{0}"},
                        "ru": {"a.used": "Нужно", "a.args": "без аргумента"}},
                       {"A/Presentation/V.cs": 'class V { void F() { t.Text("a.used"); t.Text("a.args"); t.Text("a.nope"); } }'})
        code, out = check(root)
        self.assertEqual(code, 1)
        self.assertIn('UNUSED: "a.unused"', out)
        self.assertIn('MISSING: "a.nope"', out)
        self.assertIn('PARITY: "a.unused" is missing', out)
        self.assertIn('PARITY: "a.args" placeholders differ', out)

    def test_duplicate_key_breaks_the_table(self):
        root = project({"en": {}, "ru": {}}, {"A/Presentation/V.cs": "class V {}"})
        (root / "Assets/Src/Resources/Localization/en.json").write_text('{"a.b": "x", "a.b": "y"}')
        code, out = check(root)
        self.assertIn('duplicate key "a.b"', out)


    def test_project_ui_sinks_and_parity_markers_come_from_the_config(self):
        config = {"localization": {"languages": ["en", "ru"], "parityMarkers": ["[hold]"],
                                   "extraUiSinks": [r"\bnew\s+KeyHint\s*\("]}}
        root = project({"en": {"a.hint": "[hold] C — rotate"}, "ru": {"a.hint": "C — вращать"}},
                       {"A/Presentation/V.cs": 'class V { void F() { t.Text("a.hint"); h = new KeyHint("Press it now"); } }'},
                       config)
        code, out = check(root)
        self.assertEqual(code, 1)
        self.assertIn("[hold] marker differs", out)
        self.assertEqual(out.count("HARDCODED"), 1, out)
        code, out = check(project({"en": {}}, {"A/Presentation/V.cs": 'class V { void F() { h = new KeyHint("Press it now"); } }'},
                                  {"localization": {"languages": ["en"]}}))
        self.assertEqual(code, 0, out)

    def test_language_without_table_and_disabled_check(self):
        code, out = check(project({"en": {}}, {"A/V.cs": "class V {}"}))
        self.assertIn('no table for configured language "ru"', out)
        code, out = check(project({}, {"A/Presentation/V.cs": 'class V { void F() { x = "Машина"; } }'},
                                  {"localization": {"enabled": False}}))
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
