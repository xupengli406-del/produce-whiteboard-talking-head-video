"""Whisper transcription adapted from the recorded upstream template; see ORIGIN.json."""
import argparse
import json
from common import project_path, work_directory


def main(argv=None):
    parser = argparse.ArgumentParser(description='转录项目中的视频，保留原始语音时间锚点。')
    parser.add_argument('directory', nargs='?', help='兼容原模板的位置目录参数')
    parser.add_argument('--workdir', help='默认当前工作目录；不向安装目录输出')
    parser.add_argument('--output', default='transcripts.json')
    parser.add_argument('--input', action='append', help='显式选一个原视频，可重复；默认扫描时跳过本模板的两种成片名')
    parser.add_argument('--model', default='small')
    parser.add_argument('--language', default='zh')
    parser.add_argument('--dry-run', action='store_true', help='仅列输入、输出与模型，不导入或下载模型')
    args = parser.parse_args(argv)
    directory = work_directory(args.workdir or args.directory)
    files = [project_path(directory, name) for name in args.input] if args.input else sorted(
        p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in {'.mp4', '.mov', '.avi', '.mkv'}
        and p.name.lower() not in {'output_final.mp4', 'output_subtitled.mp4'})
    if any(not p.is_file() for p in files):
        parser.error('显式原视频不存在')
    if not files:
        parser.error(f'未找到视频：{directory}')
    output = project_path(directory, args.output)
    if args.dry_run:
        print(json.dumps({'files': [str(p) for p in files], 'output': str(output), 'model': args.model, 'language': args.language, 'word_timestamps': True}, ensure_ascii=False))
        return
    import whisper  # Optional runtime dependency; --help/dry-run never installs or loads it.
    model = whisper.load_model(args.model)
    results = {}
    for path in files:
        result = model.transcribe(str(path), language=args.language, word_timestamps=True)
        results[path.name] = {'text': result['text'], 'segments': [
            {**{key: round(segment[key], 2) for key in ('start', 'end')}, 'text': segment['text'],
             **({'words': segment['words']} if 'words' in segment else {})}
            for segment in result['segments']]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Saved {len(results)} transcripts to: {output}')


if __name__ == '__main__':
    main()
