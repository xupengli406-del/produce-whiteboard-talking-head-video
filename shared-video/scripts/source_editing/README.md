# 原素材转录、剪辑与普通字幕模板

来源与原文件SHA见 [ORIGIN.json](ORIGIN.json)。迁入时修正了安装目录输出与导入即执行问题；未把未声明许可的上游代码改称MIT。

在用户工程目录运行，或给每条命令同一个 `--workdir`。相对输入、输出和临时片段均相对该目录；不要把用户媒体和产物放进安装目录。四个脚本的 `--help` 与 `--dry-run` 都不会安装依赖、下载模型或渲染。

- `transcribe.py [目录] --workdir <工程> --model small --language zh`：Whisper生成 `transcripts.json`，保留segments和可用的words时间锚点。实际转录才导入Whisper，首次模型加载可能下载模型。可重复 `--input <源文件>` 明确选择；默认扫描跳过本模板的 `output_final.mp4` 与 `output_subtitled.mp4`，避免把旧成片重新当原片。
- `edit_video.py --workdir <工程> --clips clips.json --width 1280 --height 720 --fps 30`：FFmpeg按清单裁剪，等比缩放补边、统一帧率和音频参数、短音频淡入淡出，再concat；生成 `temp_clips/` 与 `output_final.mp4`。
- `generate_srt.py --workdir <工程> --clips clips.json --corrections corrections.json`：按同一清单映射字幕并纠错，生成 `output.srt`。纠错表可省略。默认沿用原模板短条阈值0.3秒与相邻合并逻辑，必须按真实原声检查被截短/跳过的句子，必要时降低 `--min-duration`；自动合并不替代语义断句。
- `burn_subtitles.py --workdir <工程> --input output_final.mp4 --srt output.srt --style '<项目实际字体及安全区样式>'`：使用FFmpeg/libass烧录已校对的普通SRT，输出 `output_subtitled.mp4`。默认字体只是模板，先确认本次字体可用。

`clips.json` 为 `[["take1.mp4", 1.0, 4.5, "说明"], ["take2.mov", 0.0, 5.0, "说明"]]`。转录、视频和字幕应使用同一源文件名、源时间与成片顺序；不要为了凑时长删掉真实条件或拼造发言。Windows路径作为完整命令参数传递；脚本捕获并按UTF-8容错解码FFmpeg错误。

普通SRT不包含V24动画。需要字幕关键词放大时，按主Skill的行内组件/所选编辑器，用最终原声锚点制作正常初态、放大、邻字让位、句末保持与下一条重建，再检查真实导出。
