#!/usr/bin/env python3
"""Export aligned Chinese, English and bilingual SRT from a checked Chinese SRT.

No translation, network access, rendering or automatic cue splitting is performed.
English input is a JSON array of {"index": <Chinese cue number>, "text": "..."}.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional


class SubtitleError(ValueError):
    """An actionable input or output validation error."""


@dataclass(frozen=True)
class Cue:
    index: int
    start_ms: int
    end_ms: int
    text: str


STAMP = r"(\d{2,}):([0-5]\d):([0-5]\d),(\d{3})"
TIMELINE = re.compile(r"^" + STAMP + r"[ \t]+-->[ \t]+" + STAMP + r"[ \t]*$")
OUTPUT_NAMES = ("字幕_中文.srt", "字幕_英文.srt", "字幕_中英双语.srt")


def duration_seconds(value: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise argparse.ArgumentTypeError("duration must be a positive finite number of seconds")
    if not result.is_finite() or result <= 0:
        raise argparse.ArgumentTypeError("duration must be a positive finite number of seconds")
    return result


def _milliseconds(parts: List[str]) -> int:
    hours, minutes, seconds, millis = map(int, parts)
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def read_chinese(path: Path, duration: Optional[Decimal]) -> List[Cue]:
    try:
        content = path.read_text(encoding="utf-8-sig")
    except UnicodeError as exc:
        raise SubtitleError("Chinese SRT must use UTF-8: {}".format(path)) from exc
    content = content.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if not content.strip():
        raise SubtitleError("Chinese SRT contains no cues")
    cues = []
    for position, block in enumerate(re.split(r"\n[ \t]*\n", content), 1):
        lines = block.split("\n")
        if len(lines) < 3 or not re.fullmatch(r"[0-9]+", lines[0].strip()):
            raise SubtitleError("Chinese SRT block {} needs a numeric index, timeline and text".format(position))
        index = int(lines[0].strip())
        if index < 1:
            raise SubtitleError("Chinese cue index must be positive: {}".format(index))
        if cues and index <= cues[-1].index:
            raise SubtitleError("Chinese cue indexes must be unique and increasing: {} after {}".format(index, cues[-1].index))
        match = TIMELINE.fullmatch(lines[1].strip())
        if not match:
            raise SubtitleError("Chinese cue {} has an invalid timeline; use HH:MM:SS,mmm --> HH:MM:SS,mmm".format(index))
        start_ms = _milliseconds(list(match.groups()[:4]))
        end_ms = _milliseconds(list(match.groups()[4:]))
        if end_ms <= start_ms:
            raise SubtitleError("Chinese cue {} must end after it starts".format(index))
        if cues and start_ms < cues[-1].end_ms:
            raise SubtitleError("Chinese cue {} overlaps cue {}".format(index, cues[-1].index))
        if duration is not None and Decimal(end_ms) > duration * 1000:
            raise SubtitleError("Chinese cue {} ends beyond video duration {} seconds".format(index, duration))
        text = "\n".join(lines[2:])
        if not text.strip():
            raise SubtitleError("Chinese cue {} has empty text".format(index))
        cues.append(Cue(index, start_ms, end_ms, text))
    return cues


def _unique_json_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SubtitleError("Translation JSON repeats object key: {}".format(key))
        result[key] = value
    return result


def read_translations(path: Path, cues: List[Cue]) -> Dict[int, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_json_keys)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SubtitleError("Translations must be valid UTF-8 JSON: {}".format(exc)) from exc
    if not isinstance(data, list):
        raise SubtitleError("Translations JSON must be an array of {index, text} objects")
    expected = {cue.index for cue in cues}
    translations = {}
    for position, item in enumerate(data, 1):
        if not isinstance(item, dict):
            raise SubtitleError("Translation entry {} must be an object".format(position))
        index = item.get("index")
        if type(index) is not int or index < 1:
            raise SubtitleError("Translation entry {} index must be a positive integer, not bool or text".format(position))
        if index in translations:
            raise SubtitleError("Duplicate translation index: {}".format(index))
        if index not in expected:
            raise SubtitleError("Unknown translation index: {} (not present in Chinese SRT)".format(index))
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise SubtitleError("Translation cue {} must contain non-empty text".format(index))
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if any(not line.strip() for line in text.split("\n")):
            raise SubtitleError("Translation cue {} contains a blank line; SRT uses blank lines to separate cues".format(index))
        translations[index] = text
    missing = expected.difference(translations)
    if missing:
        raise SubtitleError("Missing translations for Chinese cue indexes: {}".format(", ".join(map(str, sorted(missing)))))
    return translations


def stamp(milliseconds: int) -> str:
    seconds, millis = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return "{:02d}:{:02d}:{:02d},{:03d}".format(hours, minutes, seconds, millis)


def render(cues: List[Cue], translations: Optional[Dict[int, str]] = None, bilingual: bool = False) -> str:
    blocks = []
    for cue in cues:
        text = cue.text
        if translations is not None:
            text = cue.text + "\n" + translations[cue.index] if bilingual else translations[cue.index]
        blocks.append("{}\n{} --> {}\n{}".format(cue.index, stamp(cue.start_ms), stamp(cue.end_ms), text))
    return "\n\n".join(blocks) + "\n"


def discover_trash() -> Optional[Path]:
    """Only use a known existing system Trash; do not invent a fallback."""
    candidate = Path.home() / ".Trash"
    if sys.platform == "darwin" and candidate.is_dir():
        return candidate
    return None


def _atomic_bytes(path: Path, content: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".recovery-map-", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
        os.replace(temporary, str(path))
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def write_outputs(output_dir: Path, contents: List[str], source_zh: Optional[Path] = None,
                  recovery_dir: Optional[Path] = None) -> List[Path]:
    """Preserve source bytes and move replaced outputs to recoverable Trash.

    An explicit recovery_dir is the caller-selected task folder in system Trash.
    The staging directory only ever contains newly generated disposable files.
    """
    targets = [output_dir / name for name in OUTPUT_NAMES]
    changes = []
    for target in targets:
        if target.exists() and not target.is_file():
            raise SubtitleError("Output target is not a file: {}".format(target))
    for position, (target, content) in enumerate(zip(targets, contents)):
        if position == 0 and source_zh is not None and target.resolve() == source_zh.resolve():
            continue
        generated = content.encode("utf-8")
        if target.is_file() and target.read_bytes() == generated:
            continue
        changes.append({"target": target, "bytes": generated, "position": position,
                        "backup": None, "moved": False, "installed": False})
    if not changes:
        return targets

    replacing = [change for change in changes if os.path.lexists(str(change["target"]))]
    recovery = None
    operation_dir = None
    mapping_path = None
    previous_mapping = None
    mapping = None
    if replacing:
        if recovery_dir is None:
            trash = discover_trash()
            if trash is None:
                raise SubtitleError("Cannot safely overwrite existing outputs: no reliable system Trash; provide --recovery-dir pointing to a task folder in Trash")
            recovery = trash / ("bilingual-subtitles-" + uuid.uuid4().hex[:12])
        else:
            recovery = recovery_dir
        resolved_recovery = recovery.resolve()
        resolved_output = output_dir.resolve()
        if (resolved_recovery == resolved_output or resolved_output in resolved_recovery.parents
                or resolved_recovery in resolved_output.parents):
            raise SubtitleError("Recovery directory must be separate from the output directory")
        if recovery.exists() and not recovery.is_dir():
            raise SubtitleError("Recovery directory is not a folder: {}".format(recovery))
        mapping_path = recovery / "恢复映射.json"
        entries = []
        if mapping_path.exists():
            previous_mapping = mapping_path.read_bytes()
            try:
                previous = json.loads(previous_mapping.decode("utf-8-sig"))
                if not isinstance(previous, dict) or previous.get("version") != 1 or not isinstance(previous.get("files"), list):
                    raise ValueError("expected version 1 and files array")
                entries = previous["files"]
            except (UnicodeError, ValueError) as exc:
                raise SubtitleError("Existing recovery map is invalid; outputs were not changed: {}".format(mapping_path)) from exc
        operation_dir = recovery / ("replaced-" + uuid.uuid4().hex[:12])
        for change in replacing:
            target = change["target"]
            change["backup"] = operation_dir / target.name
            entries.append({"from": str(target.absolute()), "to": str(change["backup"].absolute()),
                            "sha256": hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None})
        mapping = (json.dumps({"version": 1, "files": entries}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    output_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".bilingual-staging-", dir=str(output_dir)))
    mapping_written = False
    try:
        for change in changes:
            (staging / str(change["position"])).write_bytes(change["bytes"])
        if recovery is not None:
            operation_dir.mkdir(parents=True)
            _atomic_bytes(mapping_path, mapping)
            mapping_written = True
        for change in changes:
            if change["backup"] is not None:
                shutil.move(str(change["target"]), str(change["backup"]))
                change["moved"] = True
            os.replace(str(staging / str(change["position"])), str(change["target"]))
            change["installed"] = True
    except OSError as exc:
        recovery_errors = []
        for change in reversed(changes):
            try:
                if change["moved"]:
                    if change["installed"]:
                        change["target"].unlink()  # Only the new disposable output.
                    shutil.move(str(change["backup"]), str(change["target"]))
                elif change["installed"]:
                    change["target"].unlink()
            except OSError as recovery_error:
                recovery_errors.append(str(recovery_error))
        # A failed cross-filesystem move can leave a partial copy. Retain it and
        # its mapping instead of deleting an uncertain recovery artifact.
        if any(change["backup"] is not None and os.path.lexists(str(change["backup"])) for change in replacing):
            recovery_errors.append("Recovery folder still contains files")
        if mapping_written and not recovery_errors:
            try:
                if previous_mapping is None:
                    mapping_path.unlink()  # This invocation's generated map.
                else:
                    _atomic_bytes(mapping_path, previous_mapping)
            except OSError as recovery_error:
                recovery_errors.append(str(recovery_error))
        if recovery_errors:
            raise SubtitleError("Output write failed; recovery files/map retained at {}: {}".format(recovery, "; ".join(recovery_errors))) from exc
        raise
    finally:
        shutil.rmtree(str(staging))  # Never contains a previous delivery.
        if operation_dir is not None:
            try:
                operation_dir.rmdir()  # Only succeeds for an empty folder.
            except OSError:
                pass
    return targets


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zh", type=Path, required=True, help="Final checked Chinese SRT (UTF-8)")
    parser.add_argument("--translations", type=Path, required=True, help="JSON array of index/text translations")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--duration", type=duration_seconds, help="Actual final video duration in seconds")
    parser.add_argument("--recovery-dir", type=Path, help="Task recovery folder in system Trash for replaced outputs; auto-detect existing macOS Trash if omitted")
    args = parser.parse_args(argv)
    try:
        cues = read_chinese(args.zh, args.duration)
        translations = read_translations(args.translations, cues)
        contents = [render(cues), render(cues, translations), render(cues, translations, bilingual=True)]
        targets = [args.output_dir / name for name in OUTPUT_NAMES]
        for position, target in enumerate(targets):
            if position != 0 and target.resolve() == args.zh.resolve():
                raise SubtitleError("Chinese source cannot also be an English/bilingual output path")
            if target.resolve() == args.translations.resolve():
                raise SubtitleError("Translation input cannot also be an output path")
        targets = write_outputs(args.output_dir, contents, source_zh=args.zh, recovery_dir=args.recovery_dir)
    except (SubtitleError, OSError) as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 2
    print("Exported {} aligned cues:".format(len(cues)))
    for target in targets:
        print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
