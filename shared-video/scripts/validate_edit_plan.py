#!/usr/bin/env python3
"""验证剪辑记录的时间/对象/依赖/状态；不渲染，也不代替观看和试听。"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent


def validate(plan, directory, stage):
    rules = json.loads((ROOT / 'references/editing-methods/method-contracts.json').read_text())['methods']
    recipe_text = (ROOT / 'references/editing-methods/recipes.md').read_text()
    recipes = {}
    for ident, text in re.findall(r'^## (R\d{2}) [^\n]+\n(.*?)(?=^## R\d{2} |\Z)', recipe_text, flags=re.M | re.S):
        recipes[ident] = set(re.findall(r'\b[VS]\d{2}\b', text))
    errors = []
    strict = stage in ('implemented', 'delivery')

    def error(message):
        errors.append(message)

    def number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    def file_exists(value):
        return isinstance(value, str) and bool(value) and (directory / value).is_file() and (directory / value).stat().st_size > 0

    def indexed(key):
        result = {}
        for item in plan.get(key, []):
            ident = item.get('id')
            if not ident or ident in result:
                error(f'{key} 存在空或重复 ID：{ident}')
            else:
                result[ident] = item
        return result

    if plan.get('schema_version') != 1:
        error('schema_version 必须为 1')
    output = plan['output']
    duration, fps = output['duration'], output['fps']
    if not number(duration) or not number(fps) or duration <= 0 or fps <= 0:
        return ['成片时长与帧率必须是正数']
    if any(not number(output.get(k)) or output[k] <= 0 for k in ('width', 'height')):
        error('成片宽高必须是正数')
    epsilon = 1 / fps + 1e-6
    sources, clips, objects, assets = [indexed(k) for k in ('sources', 'clips', 'objects', 'assets')]
    if not sources or not clips:
        error('必须有实际来源和片段')
    for ident, source in sources.items():
        if not file_exists(source.get('path')):
            error(f'来源文件缺失：{ident}')
        if not number(source.get('duration')) or source['duration'] <= 0:
            error(f'来源实际时长无效：{ident}')
    primary = []
    for ident, clip in clips.items():
        source = sources.get(clip.get('source_id'))
        if not source:
            error(f'片段来源不存在：{ident}')
            continue
        start, length = clip.get('timeline_start'), clip.get('timeline_duration')
        if not number(start) or not number(length) or start < 0 or length <= 0 or start + length > duration + epsilon:
            error(f'成片区间无效：{ident}')
            continue
        if clip.get('primary'):
            primary.append((start, start + length, ident))
        limit = source['duration']
        if clip.get('mode') == 'freeze':
            point = clip.get('source_time')
            if not number(point) or not 0 <= point < limit:
                error(f'定格源时刻越界：{ident}')
        elif clip.get('mode') == 'play':
            a, b, rate = clip.get('source_in'), clip.get('source_out'), clip.get('playback_rate', 1)
            if not all(number(v) for v in (a, b, rate)) or a < 0 or b <= a or b > limit + epsilon or rate <= 0:
                error(f'源片区间/速度无效：{ident}')
            elif abs((b - a) / rate - length) > epsilon:
                error(f'源时长与成片时长/速度不一致：{ident}')
        else:
            error(f'片段 mode 必须是 play 或 freeze：{ident}')
    cursor = 0
    for start, end, ident in sorted(primary):
        if start > cursor + epsilon:
            error(f'主画面出现未声明空隙：{cursor:.3f}–{start:.3f} 秒')
        cursor = max(cursor, end)
    if cursor < duration - epsilon:
        error('主画面没有覆盖成片末尾')
    for ident, asset in assets.items():
        if strict and not file_exists(asset.get('path')):
            error(f'实现所需素材缺失：{ident}')
    for ident, obj in objects.items():
        if obj.get('clip_id') and obj['clip_id'] not in clips:
            error(f'对象绑定不存在的片段：{ident}')
        if obj.get('asset_id') and obj['asset_id'] not in assets:
            error(f'对象绑定不存在的素材：{ident}')
        if obj.get('kind') == 'foreground' and obj.get('audio_enabled'):
            error(f'人物复制层开启了重复声音：{ident}')
    effect_ids, selected = set(), set()
    if not plan.get('effects'):
        error('没有记录本次使用的技法，不能把空计划当成网感处理完成')
    for effect in plan.get('effects', []):
        ident, method = effect.get('id'), effect.get('method_id')
        if not ident or ident in effect_ids:
            error(f'效果存在空或重复 ID：{ident}')
        effect_ids.add(ident)
        rule, obj = rules.get(method), objects.get(effect.get('object_id'))
        if not rule or not obj:
            error(f'效果方法或对象不存在：{ident}')
            continue
        selected.add(method)
        if obj.get('kind') not in rule['targets']:
            error(f'{method} 作用对象错误：{obj.get("kind")}；应为 {rule["targets"]}')
        start, end, anchor = [effect.get(k) for k in ('start', 'end', 'anchor_time')]
        if not all(number(v) for v in (start, end, anchor)) or not 0 <= start < end <= duration + epsilon or not 0 <= anchor <= duration:
            error(f'效果时间/锚点无效：{ident}')
        elif not start - epsilon <= anchor <= end + epsilon:
            error(f'效果锚点不在动作窗口：{ident}')
        clip = clips.get(obj.get('clip_id'))
        if clip and number(start) and number(end) and (start < clip['timeline_start'] - epsilon or end > clip['timeline_start'] + clip['timeline_duration'] + epsilon):
            error(f'效果越出绑定片段的时间窗：{ident}')
        if rule.get('requires_freeze') and (not clip or clip.get('mode') != 'freeze'):
            error(f'{method} 必须作用于真实定格片段')
        asset = assets.get(obj.get('asset_id'))
        if rule.get('requires_asset') and not asset:
            error(f'{method} 没有登记实际声音素材')
        if rule.get('requires_alpha') and (not asset or asset.get('kind') != 'alpha_video'):
            error(f'{method} 缺少动态 alpha 视频依赖')
        if rule.get('requires_foreground_layers'):
            layers = [objects.get(k, {}) for k in obj.get('layers', [])]
            kinds = [layer.get('kind') for layer in layers]
            if not all(kind in kinds for kind in ('media', 'text', 'foreground')) or not kinds.index('media') < kinds.index('text') < kinds.index('foreground'):
                error('V11 层级应由下到上包含底片、文字、人物前景')
            else:
                base, front = layers[kinds.index('media')], layers[kinds.index('foreground')]
                if not base.get('clip_id') or front.get('clip_id') != base['clip_id']:
                    error('V11 前景与底片没有引用同一源时间映射')
                if not base.get('transform_group') or base.get('transform_group') != front.get('transform_group'):
                    error('V11 前景与底片没有共享变换组')
                front_asset = assets.get(front.get('asset_id'))
                if not front_asset or front_asset.get('kind') != 'alpha_video':
                    error('V11 人物前景未登记动态 alpha 视频')
        params = effect.get('params')
        if not isinstance(params, dict) or not params:
            error(f'未记录具体作用参数：{ident}')
        if isinstance(params, dict):
            for key in ('scale', 'scale_from', 'scale_to'):
                if key in params and (not number(params[key]) or params[key] <= 0):
                    error(f'缩放参数无效：{ident}.{key}')
            if method == 'V24' and params.get('inline_caption') is True:
                # Optional new fields keep existing plans readable. Explicit contradictions fail.
                if 'end_behavior' in params and params['end_behavior'] != rule['inline_caption_end_behavior']:
                    error(f'V24 行内强调必须保持到整句退出：{ident}')
                if any(params.get(k) is True for k in ('restore_to_normal', 'yoyo', 'reset_after_animation')):
                    error(f'V24 行内强调不能恢复普通态：{ident}')
                if 'caption_start' in params or 'caption_end' in params:
                    a, b = params.get('caption_start'), params.get('caption_end')
                    if not all(number(v) for v in (a, b)) or not 0 <= a < b <= duration + epsilon:
                        error(f'V24 字幕窗口无效：{ident}')
                    elif number(anchor) and not a <= anchor < b:
                        error(f'V24 发声锚点不在当前字幕窗口：{ident}')
                    elif number(anchor) and 'emphasis_duration' in params:
                        d = params['emphasis_duration']
                        if not number(d) or d <= 0 or anchor + d >= b:
                            error(f'V24 动效未给强调完成态留下停留：{ident}')
            if method == 'V30' and params.get('has_explicit_steps') is False:
                error(f'V30 没有明确步骤不能强制编号：{ident}')
            if method == 'V31':
                if params.get('focus_mode') in ('fixed-inset', 'invented-click') or params.get('fabricated_clicks') is True:
                    error(f'V31 应按真实坐标同位置聚焦，不另开固定窗或伪造点击：{ident}')
        if effect.get('implementation') not in ('manual', 'manual-equivalent', 'native-preset', 'asset'):
            error(f'实现方式未说明：{ident}')
        if effect.get('status') not in ('planned', 'implemented'):
            error(f'效果状态无效：{ident}')
        if strict and effect.get('status') != 'implemented':
            error(f'效果仍停留在计划：{ident}')
        if strict and effect.get('implementation') == 'native-preset' and rule.get('preset_name') and (effect.get('preset_verified') is not True or not file_exists(effect.get('preset_evidence'))):
            error(f'原版预设没有本次预览证据：{method}')
    required = set(plan.get('requested_methods', []))
    for recipe in plan.get('requested_recipes', []):
        if recipe not in recipes:
            error(f'未知配方：{recipe}')
        else:
            required.update(recipes[recipe])
    for method in sorted(required - selected):
        error(f'承诺的方法/完整配方成员未实现到计划：{method}')
    if stage == 'delivery':
        if not file_exists(output.get('path')):
            error('当前导出文件不存在或为空')
        else:
            inspection = output.get('inspection', {})
            if not number(inspection.get('duration')) or abs(inspection['duration'] - duration) > epsilon:
                error('导出探测时长与计划不一致或未记录')
            if any(inspection.get(key) != output[key] for key in ('width', 'height')):
                error('导出探测画幅与计划不一致或未记录')
            expected_audio = output.get('has_audio', any(s.get('has_audio') for s in sources.values()) or any(s.startswith('S') for s in selected))
            if inspection.get('has_audio') is not expected_audio:
                error('导出音轨状态与计划不一致或未记录')
            digest = hashlib.sha256()
            with (directory / output['path']).open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
            if inspection.get('sha256') != digest.hexdigest():
                error('导出探测记录未绑定当前文件哈希，可能沿用了旧输出')
        for review_type in ('visual', 'audio'):
            if review_type == 'audio' and not any(s.get('has_audio') for s in sources.values()) and not any(s.startswith('S') for s in selected):
                continue
            record = plan.get('review', {}).get(review_type, {})
            if record.get('status') == 'limited' and record.get('reason'):
                continue
            if record.get('status') != 'passed' or not record.get('notes') or not file_exists(record.get('reviewed_file')):
                error(f'{review_type} 缺少真实检查记录；有限制时需明确 limited 和原因')
            elif (directory / record['reviewed_file']).resolve() != (directory / output['path']).resolve():
                error(f'{review_type} 检查对象不是当前导出')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('--stage', choices=['plan', 'implemented', 'delivery'], default='plan')
    args = parser.parse_args()
    try:
        errors = validate(json.loads(args.plan.read_text()), args.plan.resolve().parent, args.stage)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        errors = [f'计划结构或文件无效：{exc}']
    if errors:
        print('\n'.join('错误：' + message for message in errors))
        return 1
    print(f'通过 {args.stage} 记录检查；这不代替真实渲染、观看或试听。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
