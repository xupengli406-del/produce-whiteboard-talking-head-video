"""Map Whisper segments through the same clips used by edit_video.py; see ORIGIN.json."""
import argparse
from common import normalized_clips, project_path, read_json, work_directory


def format_time(seconds):
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}'


def subtitles(transcripts, clips, corrections, min_duration=0.3):
    result, offset = [], 0.0
    for name, start, end, _ in clips:
        for segment in transcripts[name]['segments']:
            a, b = max(float(segment['start']), start), min(float(segment['end']), end)
            if b - a < min_duration or b <= a:
                continue
            text = segment['text'].strip()
            for wrong, correct in corrections.items():
                text = text.replace(wrong, correct)
            if text:
                result.append((offset+a-start, offset+b-start, text))
        offset += end-start
    merged = []
    for start, end, text in result:
        if merged and 0 <= start-merged[-1][1] < 0.3 and len(merged[-1][2])+len(text) < 30:
            merged[-1] = (merged[-1][0], end, merged[-1][2]+text)
        else:
            merged.append((start, end, text))
    return ''.join(f'{i}\n{format_time(a)} --> {format_time(b)}\n{text}\n\n' for i, (a, b, text) in enumerate(merged, 1))


def main(argv=None):
    parser = argparse.ArgumentParser(description='按源片到成片映射生成可校对的SRT，不伪造发声时间。')
    parser.add_argument('--workdir')
    parser.add_argument('--clips', default='clips.json')
    parser.add_argument('--transcripts', default='transcripts.json')
    parser.add_argument('--corrections', help='可选项目内JSON纠错表')
    parser.add_argument('--output', default='output.srt')
    parser.add_argument('--min-duration', type=float, default=0.3, help='沿用模板阈值；短条被跳过，须结合原声校对或调低')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    directory = work_directory(args.workdir)
    clips = normalized_clips(read_json(directory, args.clips))
    corrections = read_json(directory, args.corrections) if args.corrections else {}
    rendered = subtitles(read_json(directory, args.transcripts), clips, corrections, args.min_duration)
    if args.dry_run:
        print(rendered, end='')
        return
    output = project_path(directory, args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding='utf-8')
    print(f'Saved: {output}')


if __name__ == '__main__':
    main()
