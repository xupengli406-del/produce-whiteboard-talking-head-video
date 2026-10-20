#!/usr/bin/env python3
"""Validate semantic coordination, not visual/audio acceptance. Standard library only."""
import argparse
import json
import math
from pathlib import Path


def validate(plan, base):
    errors = []
    def require(ok, message):
        if not ok:
            errors.append(message)
    def number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    def unique_ids(rows, label):
        ids = [row.get('id') for row in rows if isinstance(row, dict)]
        require(len(ids) == len(rows) and all(isinstance(i, str) and i for i in ids), f'{label}: every object needs an id')
        require(len(set(ids)) == len(ids), f'{label}: duplicate ids')
        return {r['id']: r for r in rows if isinstance(r, dict) and isinstance(r.get('id'), str)}

    require(isinstance(plan, dict), 'plan must be an object')
    if not isinstance(plan, dict):
        return errors
    duration = plan.get('duration')
    require(number(duration) and duration > 0, 'duration must be positive and finite')
    if not number(duration) or duration <= 0:
        return errors
    require(plan.get('kind') in ('schematic', 'production'), 'kind must be schematic or production')
    require(plan.get('format') in ('talking-head', 'voiceover'), 'format must be talking-head or voiceover')
    scope = plan.get('scope', {})
    protected = scope.get('preserve_opening') is True or scope.get('edit_range_excludes_opening') is True
    hook = plan.get('hook', {})
    if not protected:
        clear = hook.get('core_clear_by')
        start = hook.get('start')
        require(number(start) and number(clear) and 0 <= start <= clear <= min(3, duration), 'hook core must be clear in 0–3 seconds')
        for key in ('text', 'basis', 'bridge'):
            require(isinstance(hook.get(key), str) and bool(hook[key].strip()), f'hook.{key} is required')
    elements = unique_ids(plan.get('elements', []), 'elements')
    for key, element in elements.items():
        require(element.get('type') in ('path', 'label', 'card', 'image', 'group'), f'{key}: unsupported element type')
        if element.get('reveal') == 'stroke':
            paths = element.get('paths')
            require(isinstance(paths, list) and bool(paths) and all(isinstance(p, str) and p.strip() for p in paths), f'{key}: stroke reveal requires real paths')
    chapters = unique_ids(plan.get('chapters', []), 'chapters')
    note_ids = {}
    for key, chapter in chapters.items():
        require(bool(chapter.get('title')), f'{key}: chapter title missing')
        note_ids[key] = set(unique_ids(chapter.get('items', []), f'{key}.items'))
    beats_list = plan.get('beats', [])
    beats = unique_ids(beats_list, 'beats')
    require(bool(beats_list), 'at least one beat is required')
    last_end = 0
    visible = set()
    chapter_history = {}
    for beat in beats_list:
        if not isinstance(beat, dict) or beat.get('id') not in beats:
            continue
        key = beat['id']
        start, end = beat.get('start'), beat.get('end')
        if not (number(start) and number(end) and 0 <= start < end <= duration):
            errors.append(f'{key}: invalid time range')
            continue
        require(abs(start-last_end) < 0.001, f'{key}: gap or overlap in semantic beat coverage')
        last_end = end
        speech, anchor = beat.get('speech', ''), beat.get('anchor', '')
        require(isinstance(speech, str) and bool(speech.strip()), f'{key}: speech is required')
        require(isinstance(anchor, str) and bool(anchor) and anchor in speech, f'{key}: anchor must appear in speech')
        require(bool(beat.get('reason')), f'{key}: layout/coordination reason missing')
        board = beat.get('board', {})
        lists = {}
        for field in ('keep', 'add', 'remove'):
            ids = board.get(field)
            if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
                errors.append(f'{key}: board.{field} must be an id list')
                ids = []
            lists[field] = set(ids)
            require(len(ids) == len(lists[field]), f'{key}: duplicate board.{field} ids')
            require(lists[field] <= elements.keys(), f'{key}: unknown board.{field} element')
        keep, add, remove = (lists[f] for f in ('keep', 'add', 'remove'))
        require(keep <= visible, f'{key}: keep references elements never shown or already removed')
        require(remove <= visible, f'{key}: remove references elements not currently present')
        require(not (keep & remove or keep & add or add & remove), f'{key}: conflicting board keep/add/remove')
        require(visible == keep | remove, f'{key}: previously visible elements need explicit keep or remove')
        require(not (add & visible), f'{key}: add duplicates an already visible element')
        visible = keep | add
        camera = board.get('camera', {})
        require(all(number(camera.get(f)) for f in ('x', 'y', 'scale')) and camera.get('scale', 0) > 0, f'{key}: invalid camera')
        mode = beat.get('speaker', {}).get('mode')
        allowed = ('full', 'top-right', 'bottom-right', 'middle-left', 'custom', 'none')
        require(mode in allowed, f'{key}: unsupported speaker mode')
        if plan.get('format') == 'voiceover':
            require(mode == 'none', f'{key}: voiceover format must remove speaker window')
        if mode == 'custom':
            rect = beat.get('speaker', {}).get('rect', {})
            require(all(number(rect.get(f)) for f in ('x', 'y', 'w', 'h')) and rect.get('w', 0) > 0 and rect.get('h', 0) > 0, f'{key}: custom speaker needs a real rectangle')
        note = beat.get('note', {})
        chapter = note.get('chapter')
        require(chapter in chapters, f'{key}: unknown note chapter')
        revealed = note.get('revealed', [])
        if not isinstance(revealed, list) or not all(isinstance(i, str) for i in revealed):
            errors.append(f'{key}: note.revealed must be an id list')
            revealed = []
        revealed_set = set(revealed)
        require(len(revealed) == len(revealed_set), f'{key}: duplicate note ids')
        require(revealed_set <= note_ids.get(chapter, set()), f'{key}: note items do not belong to this chapter')
        require(note.get('active') in revealed_set, f'{key}: active note must already be revealed')
        previous = chapter_history.get(chapter, set())
        if not note.get('scroll_window'):
            require(previous <= revealed_set, f'{key}: note history disappeared without a scroll_window reason')
        else:
            require(isinstance(note['scroll_window'], str), f'{key}: scroll_window must explain retained context')
        chapter_history[chapter] = previous | revealed_set
        for event in beat.get('events', []):
            at, length = event.get('at'), event.get('duration', 0)
            require(number(at) and number(length) and length >= 0 and start <= at and at + length <= end, f'{key}: event outside beat')
            require(event.get('target') in elements, f'{key}: event references unknown target')
            require(isinstance(event.get('anchor'), str) and bool(event['anchor']) and event['anchor'] in speech, f'{key}: event needs a spoken anchor')
    require(abs(last_end-duration) < 0.001, 'beats must cover through the final duration')
    if plan.get('kind') == 'production':
        media = plan.get('media', [])
        roles = {m.get('role') for m in media if isinstance(m, dict)}
        if plan.get('format') == 'talking-head':
            require('speaker' in roles, 'production talking-head needs actual speaker video')
        require('voice' in roles or any(m.get('role') == 'speaker' and m.get('use_audio') is True for m in media), 'production needs one main voice source')
        main_voices = sum(m.get('role') == 'voice' or (m.get('role') == 'speaker' and m.get('use_audio') is True) for m in media)
        require(main_voices == 1, 'production must declare exactly one main voice source')
        for item in media:
            relative = item.get('path')
            require(isinstance(relative, str) and bool(relative), 'production media path missing')
            if isinstance(relative, str) and relative:
                require(not Path(relative).is_absolute(), 'use project-relative media paths')
                require((base / relative).is_file(), f'production media missing: {relative}')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    args = parser.parse_args()
    try:
        plan = json.loads(args.plan.read_text(encoding='utf-8'))
        errors = validate(plan, args.plan.resolve().parent)
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
        errors = [f'invalid plan: {exc}']
    if errors:
        for error in errors:
            print(f'ERROR: {error}')
        return 1
    print('PASS: timing, references, board continuity, note states and declared inputs')
    print('This does not establish visual, audio or exported-video acceptance.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
