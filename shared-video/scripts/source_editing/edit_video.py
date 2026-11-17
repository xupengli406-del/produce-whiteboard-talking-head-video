"""FFmpeg trim/normalize/concatenate template; see ORIGIN.json for provenance."""
import argparse
import json
from common import normalized_clips, project_path, read_json, run_command, work_directory


def trim_command(source, start, end, output, width, height, fps):
    duration = end - start
    fade = min(0.05, duration / 2)
    return ['ffmpeg', '-y', '-ss', f'{start:.3f}', '-i', str(source), '-t', f'{duration:.3f}',
            '-vf', f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-c:a', 'aac', '-b:a', '128k',
            '-ar', '44100', '-ac', '2', '-af', f'afade=t=in:st=0:d={fade:.3f},afade=t=out:st={duration-fade:.3f}:d={fade:.3f}',
            '-avoid_negative_ts', 'make_zero', '-r', str(fps), str(output)]


def main(argv=None):
    parser = argparse.ArgumentParser(description='按同一真实剪辑清单裁剪、统一画幅并拼接。')
    parser.add_argument('--workdir')
    parser.add_argument('--clips', default='clips.json', help='项目内 [[源文件,开始秒,结束秒,说明], ...]')
    parser.add_argument('--output', default='output_final.mp4')
    parser.add_argument('--temp-dir', default='temp_clips')
    parser.add_argument('--width', type=int, default=1280)
    parser.add_argument('--height', type=int, default=720)
    parser.add_argument('--fps', type=float, default=30)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    directory = work_directory(args.workdir)
    clips = normalized_clips(read_json(directory, args.clips))
    if min(args.width, args.height, args.fps) <= 0:
        parser.error('画幅与帧率必须大于0')
    temporary = project_path(directory, args.temp_dir)
    output = project_path(directory, args.output)
    commands, paths = [], []
    for index, (name, start, end, _) in enumerate(clips):
        source = project_path(directory, name)
        if not source.is_file():
            parser.error(f'源文件不存在：{source}')
        part = temporary / f'clip_{index:02d}.mp4'
        paths.append(part)
        commands.append(trim_command(source, start, end, part, args.width, args.height, args.fps))
    list_file = temporary / 'filelist.txt'
    commands.append(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(list_file), '-c:v', 'libx264',
                     '-preset', 'medium', '-crf', '20', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', str(output)])
    if args.dry_run:
        print(json.dumps({'commands': commands, 'concat_inputs': [str(p) for p in paths], 'output': str(output)}, ensure_ascii=False))
        return
    temporary.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    for command in commands[:-1]:
        run_command(command)
    list_file.write_text(''.join("file '" + str(p).replace("'", "'\\''") + "'\n" for p in paths), encoding='utf-8')
    run_command(commands[-1])
    duration = run_command(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(output)])
    print(f'Done: {float(duration.strip()):.3f}s | {output}')


if __name__ == '__main__':
    main()
