#!/usr/bin/env python3
"""Read-only method/provenance check. Optional evidence input verifies original bytes."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parent.parent
REFS = ROOT / 'references/editing-methods'


def check(evidence_root=None):
    errors, techniques, recipes = [], {}, {}
    for path in REFS.glob('*.md'):
        body = path.read_text(encoding='utf-8')
        for ident, name in re.findall(r'^## ((?:V|S|R)\d{2}) (.+)$', body, re.M):
            target = recipes if ident.startswith('R') else techniques
            if ident in target:
                errors.append(f'重复ID：{ident}')
            target[ident] = (path, name)
            if f'id="{ident}"' not in body:
                errors.append(f'缺少锚点：{ident}')
    contracts = json.loads((REFS / 'method-contracts.json').read_text())['methods']
    if set(contracts) != set(techniques):
        errors.append('方法说明与执行约束集合不同')
    authorization = json.loads((REFS / 'user-authorized-methods.json').read_text())
    authorized = set()
    if authorization.get('source_type') != 'user_authorized_method':
        errors.append('用户授权来源类型不正确')
    for item in authorization['methods']:
        ident = item['id']
        if ident in authorized or ident not in techniques or not item.get('request'):
            errors.append(f'授权记录无效：{ident}')
        authorized.add(ident)
        if contracts.get(ident, {}).get('origin') != 'user_authorized_method':
            errors.append(f'授权方法来源混淆：{ident}')
    covered, media_count, verified = set(), 0, 0
    for path in sorted((REFS / 'cases').glob('*/coverage.json')):
        coverage = json.loads(path.read_text())
        registered = {m['path']: m for m in coverage['media_files']}
        media_count += len(registered)
        for group in ('annotations', 'observations'):
            for item in coverage[group]:
                if not item.get('label') or not item.get('technique_ids') or not 0 <= item['time_seconds'] < coverage['duration_ms']/1000:
                    errors.append('来源覆盖条目无效')
                if item['snapshot'] not in registered:
                    errors.append(f'来源截图未登记：{item["snapshot"]}')
                for ident in item['technique_ids']:
                    if ident not in techniques:
                        errors.append(f'来源指向不存在的方法：{ident}')
                    covered.add(ident)
        if evidence_root is not None:
            folder = (Path(evidence_root) / coverage['case_id']).resolve()
            for name, metadata in registered.items():
                file = (folder / name).resolve()
                if not file.is_relative_to(folder) or not file.is_file():
                    errors.append(f'证据缺失或越界：{name}')
                elif hashlib.sha256(file.read_bytes()).hexdigest() != metadata['sha256']:
                    errors.append(f'证据哈希不符：{name}')
                else:
                    verified += 1
    if set(techniques) != covered | authorized or covered & authorized:
        errors.append('方法证据与用户授权覆盖不完整或重复')
    all_ids = set(techniques) | set(recipes)
    for path in REFS.rglob('*.md'):
        body = path.read_text(encoding='utf-8')
        for ident in set(re.findall(r'\b(?:V|S|R)\d{2}\b', body)) - all_ids:
            errors.append(f'引用不存在的ID：{ident}')
        for target in re.findall(r'\]\(([^)]+)\)', body):
            if target.startswith(('https://', 'http://')):
                continue
            name, _, fragment = target.partition('#')
            resolved = (path.parent / unquote(name)).resolve() if name else path
            if not resolved.is_file():
                errors.append(f'引用文件不存在：{path.name} → {target}')
            elif fragment and resolved.suffix == '.md' and f'id="{fragment}"' not in resolved.read_text():
                errors.append(f'引用锚点不存在：{target}')
    return {'passed': not errors, 'methods': len(techniques), 'recipes': len(recipes),
            'reference_covered': len(covered), 'user_authorized': len(authorized),
            'evidence_files_registered': media_count, 'evidence_files_verified': verified,
            'evidence_bytes_checked': evidence_root is not None, 'errors': errors,
            'scope': '方法、来源映射与可选证据文件；不证明用户成片实际观看/试听或已被接受'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-root', type=Path, help='包含lc-vol12目录的项目证据根目录')
    args = parser.parse_args()
    report = check(args.evidence_root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
