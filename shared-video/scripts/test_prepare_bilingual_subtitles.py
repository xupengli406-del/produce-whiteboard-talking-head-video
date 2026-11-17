#!/usr/bin/env python3
"""Behavioral CLI checks. Set TMPDIR to an isolated validation directory."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name("prepare_bilingual_subtitles.py")
SPEC = importlib.util.spec_from_file_location("bilingual_subtitles_test_target", SCRIPT)
HELPER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = HELPER
SPEC.loader.exec_module(HELPER)
NAMES = ("字幕_中文.srt", "字幕_英文.srt", "字幕_中英双语.srt")
ZH = "1\n00:00:00,250 --> 00:00:01,400\n我之前是一名AI产品经理，\n现在处于短暂的gap期。\n\n4\n00:00:01,400 --> 00:00:03,125\n这不是实时性文档，是事实性文档。\n"
TRANSLATIONS = [
    {"index": 4, "text": "It is a factual document, not a real-time one."},
    {"index": 1, "text": "I used to be an AI product manager.\nI am taking a short career break."},
]


class BilingualCLI(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bilingual-cli-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.zh = self.root / "checked.srt"
        self.translations = self.root / "translations.json"
        self.output = self.root / "delivery"
        self.recovery = self.root / "task-trash"
        self.zh.write_bytes(("\ufeff" + ZH.replace("\n", "\r\n")).encode("utf-8"))
        self.set_translations(TRANSLATIONS)

    def set_translations(self, items):
        self.translations.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8-sig")

    def run_cli(self, *extra):
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--zh", str(self.zh), "--translations", str(self.translations),
             "--output-dir", str(self.output), "--recovery-dir", str(self.recovery)] + list(extra),
            capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        )

    def assert_rejected(self, message, *extra):
        result = self.run_cli(*extra)
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn(message, result.stderr)
        self.assertFalse(self.output.exists(), "Preflight failure must not create a delivery folder or partial set")

    def test_three_outputs_share_cues_times_and_keep_manual_line_breaks(self):
        source = self.zh.read_bytes()
        result = self.run_cli("--duration", "3.125")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(source, self.zh.read_bytes())
        self.assertEqual(set(NAMES), {path.name for path in self.output.iterdir()})
        chinese, english, bilingual = [(self.output / name).read_text(encoding="utf-8") for name in NAMES]
        self.assertEqual(ZH, chinese)
        expected_english = (
            "1\n00:00:00,250 --> 00:00:01,400\nI used to be an AI product manager.\nI am taking a short career break.\n\n"
            "4\n00:00:01,400 --> 00:00:03,125\nIt is a factual document, not a real-time one.\n"
        )
        self.assertEqual(expected_english, english)
        for zh_block, en_block, both_block in zip(chinese.strip().split("\n\n"), english.strip().split("\n\n"), bilingual.strip().split("\n\n")):
            zh_lines, en_lines, both_lines = zh_block.splitlines(), en_block.splitlines(), both_block.splitlines()
            self.assertEqual(zh_lines[:2], en_lines[:2])
            self.assertEqual(zh_lines[:2], both_lines[:2])
            self.assertEqual(zh_lines[2:] + en_lines[2:], both_lines[2:])

    def test_missing_translation(self):
        self.set_translations(TRANSLATIONS[:1])
        self.assert_rejected("Missing translations")

    def test_duplicate_translation(self):
        self.set_translations(TRANSLATIONS + [TRANSLATIONS[0]])
        self.assert_rejected("Duplicate translation index: 4")

    def test_unknown_translation(self):
        self.set_translations(TRANSLATIONS + [{"index": 99, "text": "Unmatched"}])
        self.assert_rejected("Unknown translation index: 99")

    def test_invalid_translation_shapes(self):
        cases = [({"1": "Translation"}, "must be an array"),
                 ([{"index": True, "text": "Boolean is not a cue number"}], "not bool"),
                 ([{"index": 1.0, "text": "Float is not a cue number"}], "positive integer"),
                 ([{"index": 1, "text": "   "}], "non-empty text"),
                 ([{"index": 1, "text": "One\n\nTwo"}], "blank line"),
                 ([{"index": 1, "text": 123}], "non-empty text"),
                 (["not an object"], "must be an object")]
        for items, error in cases:
            with self.subTest(items=items):
                self.set_translations(items)
                self.assert_rejected(error)

    def test_repeated_json_key_is_not_silently_accepted(self):
        self.translations.write_text('[{"index": 1, "index": 4, "text": "x"}]', encoding="utf-8")
        self.assert_rejected("repeats object key: index")

    def test_overlap(self):
        self.zh.write_text(ZH.replace("00:00:01,400 --> 00:00:03,125", "00:00:01,399 --> 00:00:03,125"), encoding="utf-8")
        self.assert_rejected("overlaps cue 1")

    def test_video_boundary(self):
        self.assert_rejected("beyond video duration", "--duration", "3.124")

    def test_invalid_duration(self):
        for duration in ("NaN", "Infinity", "0", "-1", "invalid"):
            with self.subTest(duration=duration):
                self.assert_rejected("positive finite", "--duration", duration)

    def test_reversed_or_malformed_time(self):
        for text, error in [
            (ZH.replace("00:00:01,400", "00:00:00,100", 1), "end after it starts"),
            (ZH.replace("00:00:00,250", "00:61:00,250"), "invalid timeline"),
            (ZH.replace("00:00:00,250", "00:00:00.250"), "invalid timeline"),
        ]:
            with self.subTest(error=error):
                self.zh.write_text(text, encoding="utf-8")
                self.assert_rejected(error)

    def test_chinese_indexes_must_be_unique_and_increasing(self):
        for index in ("1", "0"):
            with self.subTest(index=index):
                self.zh.write_text(ZH.replace("\n\n4\n", "\n\n" + index + "\n"), encoding="utf-8")
                self.assert_rejected("index")

    def test_preflight_failure_keeps_existing_output_set_unchanged(self):
        self.output.mkdir()
        originals = {}
        for name in NAMES:
            originals[name] = ("existing: " + name).encode("utf-8")
            (self.output / name).write_bytes(originals[name])
        source = self.zh.read_bytes()
        self.set_translations([])
        result = self.run_cli()
        self.assertEqual(2, result.returncode)
        self.assertIn("Missing translations", result.stderr)
        self.assertEqual(source, self.zh.read_bytes())
        self.assertEqual(originals, {path.name: path.read_bytes() for path in self.output.iterdir()})

    def test_chinese_source_may_already_be_canonical_output(self):
        self.output.mkdir()
        canonical_source = self.output / NAMES[0]
        self.zh.replace(canonical_source)
        self.zh = canonical_source
        original_bytes = canonical_source.read_bytes()
        result = self.run_cli()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(original_bytes, canonical_source.read_bytes())
        self.assertEqual(ZH, canonical_source.read_text(encoding="utf-8-sig"))
        self.assertTrue(self.translations.exists())
        self.assertEqual(set(NAMES), {path.name for path in self.output.iterdir()})
        self.assertFalse(self.recovery.exists())

    def test_source_link_alias_keeps_original_bytes_and_link(self):
        self.output.mkdir()
        canonical_source = self.output / NAMES[0]
        canonical_source.symlink_to(self.zh)
        original_bytes = self.zh.read_bytes()
        result = self.run_cli()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(canonical_source.is_symlink())
        self.assertEqual(original_bytes, self.zh.read_bytes())
        self.assertEqual(original_bytes, canonical_source.read_bytes())
        self.assertFalse(self.recovery.exists())

    def test_output_directory_collision_does_not_replace_existing_files(self):
        self.output.mkdir()
        (self.output / NAMES[0]).write_bytes(b"keep")
        (self.output / NAMES[1]).mkdir()
        result = self.run_cli()
        self.assertEqual(2, result.returncode)
        self.assertIn("Output target is not a file", result.stderr)
        self.assertEqual(b"keep", (self.output / NAMES[0]).read_bytes())
        self.assertFalse((self.output / NAMES[2]).exists())

    def test_write_interruption_rolls_back_the_whole_existing_set(self):
        self.output.mkdir()
        originals = {name: ("previous " + name).encode("utf-8") for name in NAMES}
        for name, content in originals.items():
            (self.output / name).write_bytes(content)
        real_replace = os.replace
        interrupted = []

        def fail_during_second_file(source, target):
            if (Path(target) == self.output / NAMES[1] and Path(source).name == "1" and not interrupted):
                interrupted.append(True)
                raise OSError("simulated replacement interruption")
            return real_replace(source, target)

        with mock.patch.object(HELPER.os, "replace", side_effect=fail_during_second_file):
            with self.assertRaisesRegex(OSError, "simulated replacement interruption"):
                HELPER.write_outputs(self.output, ["new Chinese", "new English", "new bilingual"], recovery_dir=self.recovery)
        self.assertEqual(originals, {path.name: path.read_bytes() for path in self.output.iterdir()})
        self.assertFalse((self.recovery / "恢复映射.json").exists())

    def test_replaced_outputs_are_recoverable_and_identical_rerun_adds_nothing(self):
        self.output.mkdir()
        originals = {name: ("previous " + name).encode("utf-8") for name in NAMES}
        for name, content in originals.items():
            (self.output / name).write_bytes(content)
        source_bytes = self.zh.read_bytes()
        result = self.run_cli()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(source_bytes, self.zh.read_bytes())
        mapping_path = self.recovery / "恢复映射.json"
        mapping_bytes = mapping_path.read_bytes()
        mapping = json.loads(mapping_bytes)
        self.assertEqual(3, len(mapping["files"]))
        for entry in mapping["files"]:
            name = Path(entry["from"]).name
            self.assertEqual(originals[name], Path(entry["to"]).read_bytes())
            self.assertNotIn(".bilingual-staging-", entry["to"])
        before_paths = {str(path.relative_to(self.recovery)) for path in self.recovery.rglob("*")}
        result = self.run_cli()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(mapping_bytes, mapping_path.read_bytes())
        self.assertEqual(before_paths, {str(path.relative_to(self.recovery)) for path in self.recovery.rglob("*")})

    def test_no_reliable_trash_refuses_overwrite_before_any_output_changes(self):
        self.output.mkdir()
        original = self.output / NAMES[1]
        original.write_bytes(b"previous English")
        with mock.patch.object(HELPER, "discover_trash", return_value=None):
            with self.assertRaisesRegex(HELPER.SubtitleError, "no reliable system Trash"):
                HELPER.write_outputs(self.output, ["new Chinese", "new English", "new bilingual"])
        self.assertEqual({NAMES[1]: b"previous English"}, {path.name: path.read_bytes() for path in self.output.iterdir()})
        self.assertFalse(self.recovery.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
