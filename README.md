# 画板手绘风格口播视频 Skill

把一个问题像坐在旁边讲解一样，边说边画明白。默认采用真人口播窗口、手绘黑板、右侧中文笔记和底部字幕，重点编排三者互相配合的时机。

适合知识解释、经验分享、条件选择、流程和避坑类口播。可从已有录像继续后期，也可先写稿与分镜。手绘通过物件隐喻、简笔图和空间关系参与解释。

## 安装

将本仓库克隆到 Codex 的 Skill 目录：

```sh
git clone https://github.com/xupengli406-del/produce-whiteboard-talking-head-video.git ~/.codex/skills/produce-whiteboard-talking-head-video
```

若该目录已存在，先确认是否为同一仓库并保留本地修改，不要覆盖安装。默认支持自动发现，也可明确调用：

```text
用 $produce-whiteboard-talking-head-video，把这段录像做成画板手绘风格口播。
保留我的原声，用简笔图一步步展开，右侧同步整理中文笔记。
```

只需稿件时可说“先写稿和图解分镜，不生成视频”。Skill 安装不包含视频渲染器；完整制作使用当前可用的 HyperFrames 或已有编辑器。真人小窗需要实际录像，纯旁白可按用户选择使用。

## 已整理的内容

- [Skill 入口](SKILL.md)：输入、制作流程、范围与交付。
- [手绘视觉语言](references/visual-language.md)：具体物件、线条、关键词和色彩。
- [三路声画配合](references/choreography.md)：人物模式、黑板累计、局部与总览、章节和要点状态。
- [实现与验收](references/implementation.md)：图层、真实路径显现、媒体时钟及实际导出检查。
- [参考案例](references/source-study.md)：已核对画面与未知细节。
- [构图示意](assets/layout.html)和[计划示例](assets/plan.example.json)：不含真人/音轨，用于检查版式与编排，不能视为完成视频。

## 本地查看与校验

```sh
python3 scripts/validate_plan.py assets/plan.example.json
python3 -m http.server 8765 --bind 127.0.0.1
```

随后打开 `http://127.0.0.1:8765/assets/layout.html`。计划检查关注时间、对象引用、笔记当前状态和真实逐笔前提，不能替代对成片的观看/试听。

本仓库保存可迁移的制作规则和自造示意，不包含参考作者的录像、声音、字体或音乐。已有参考分析未验证作者所用软件、完整逐笔动画或声音细节，也未完成新主题真人视频的端到端验证。

## 当前验证范围

已通过 Skill 格式检查、计划示例检查和本地文档链接检查；检查工具已验证能拒绝超时钩子、未知笔记、丢失画板上下文、缺少路径的逐笔声明及没有真实素材的生产计划。独立新主题试用已产出稿件与分镜，且遵守仅要小窗、不固定八章、不生成音视频的范围。构图示意已检查人物四种布局、笔记推进与总览状态；它没有实现段内精确动效或成片音画验收。
