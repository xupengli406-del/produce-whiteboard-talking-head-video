"""FFmpeg/libass plain-SRT burn-in template; animated emphasis is a separate layer."""
import argparse
import json
from common import project_path, run_command, work_directory


STYLE = 'FontSize=20,FontName=Microsoft YaHei,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Shadow=1,MarginV=30'


def subtitle_filter(path, style):
    escaped = str(path).replace('\\', '/').replace(':', '\\:').replace("'", "'\\''")
    return f"subtitles='{escaped}':force_style='{style}'"


def main(argv=None):
    parser = argparse.ArgumentParser(description='烧录已人工校对的普通SRT；不生成V24字幕动画。')
    parser.add_argument('--workdir')
    parser.add_argument('--input', default='output_final.mp4')
    parser.add_argument('--srt', default='output.srt')
    parser.add_argument('--output', default='output_subtitled.mp4')
    parser.add_argument('--style', default=STYLE, help='使用项目实际可用字体和安全区')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    directory = work_directory(args.workdir)
    source, srt, output = [project_path(directory, value) for value in (args.input, args.srt, args.output)]
    if not source.is_file() or not srt.is_file():
        parser.error('无字幕视频或SRT不存在')
    command = ['ffmpeg', '-y', '-i', str(source), '-vf', subtitle_filter(srt, args.style), '-c:v', 'libx264',
               '-preset', 'medium', '-crf', '20', '-c:a', 'copy', '-movflags', '+faststart', str(output)]
    if args.dry_run:
        print(json.dumps({'command': command, 'output': str(output)}, ensure_ascii=False))
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    run_command(command)
    print(f'Done: {output}')


if __name__ == '__main__':
    main()
