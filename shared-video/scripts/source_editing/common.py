"""Project-path helpers for the source-editing templates; no import-time writes."""
from pathlib import Path
import json
import math
import subprocess


def work_directory(value=None):
    directory = Path(value).expanduser().resolve() if value else Path.cwd().resolve()
    if not directory.is_dir():
        raise ValueError(f'工作目录不存在：{directory}')
    return directory


def project_path(directory, value):
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (directory / path).resolve()


def read_json(directory, value):
    return json.loads(project_path(directory, value).read_text(encoding='utf-8'))


def run_command(command):
    result = subprocess.run([str(x) for x in command], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout = result.stdout.decode('utf-8', errors='replace')
    stderr = result.stderr.decode('utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(f'{command[0]} 执行失败：{stderr[-1000:]}')
    return stdout


def normalized_clips(clips):
    result = []
    for row in clips:
        if len(row) not in (3, 4):
            raise ValueError('每个片段须为 [源文件,开始秒,结束秒,可选说明]')
        source, start, end = row[:3]
        start, end = float(start), float(end)
        if not all(math.isfinite(x) for x in (start, end)) or start < 0 or end <= start:
            raise ValueError(f'片段区间无效：{row}')
        result.append((source, start, end, str(row[3]) if len(row) == 4 else ''))
    if not result:
        raise ValueError('没有片段；通过项目内的 --clips JSON 提供真实剪辑时间线')
    return result
