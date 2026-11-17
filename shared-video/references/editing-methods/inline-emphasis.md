# V24 行内字幕的可复用实现

[assets/inline-emphasis.mjs](../../assets/inline-emphasis.mjs) 是单行字幕的浏览器组件，不是视频渲染器。它根据绝对成片时间求状态，既可逐帧导出也可随机 seek；不依赖上一帧、计时器或 CSS 反向播放。

接入时等待 `document.fonts.ready`，用本次实际字体、字号和字幕宽度建立根容器，再调用 `createInlineEmphasis(root, config)`。配置如下：

```javascript
const caption = createInlineEmphasis(root, {
  tokens: ['我认为', '认知', '最关键'], // 自然连接的真实文本，不能加占位空格
  keywordIndex: 1,
  captionStart: 12,
  captionEnd: 15,
  anchorTime: 12.8,
  emphasisDuration: 0.3,
  scaleTo: 1.4,
  normalColor: '#efe9dc',
  emphasisColor: '#e6c45c'
});
caption.render(timelineTime);
```

示例数值、颜色不是固定制作规范；按当前母版和语义配置。`scaleYTo` 可独立控制纵向形变，默认等比放大。组件测量真实文本宽度，使用同一进度扩大重点词并平滑推开邻字，使整句中心稳定。完成态保持到 `captionEnd`，边界后隐藏；为下一句重建组件，不能复用上一句的变色结果。更换字体、根宽度或屏幕比例后重新建立；多行字幕按完整词组先断行，每行独立布局，不让组件自动挤断中文词。

根容器须留够放大后的垂直空间，安全区由工程负责。组件不负责自动转写、双语翻译、音频对齐或全片检查；锚点必须来自实际发声。

## 回归检查

运行 `scripts/test_inline_emphasis.mjs --playwright-module /实际/node_modules/playwright --browser /实际/Chrome可执行文件 --output-dir /本次临时验证目录`。浏览器测试实际测量中文字框，覆盖正常初态、锚点前、动画中、终态、句末、退出、下一句及打乱时间顺序的 seek，检查词序、邻字无缝、句中位置、颜色和尺寸保持。测试保存一张状态截图和 JSON 结果；它证明组件在该浏览器行为成立，不代表已经检查用户成片。

工程换用其他引擎时保留同样可观察条件，尤其不能把 `fill: both`、动画结束回调或 `yoyo` 当作随机 seek 的状态来源。仍须看当前实际导出的连续动作和字幕退出边界。
