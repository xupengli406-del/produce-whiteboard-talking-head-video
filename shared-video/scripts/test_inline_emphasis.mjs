#!/usr/bin/env node
/** Real-browser regression for the reusable V24 component; no user media. */
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';

const args = process.argv.slice(2);
const option = name => { const i = args.indexOf(name); return i < 0 ? undefined : args[i + 1]; };
if (args.includes('--help')) {
  console.log('test_inline_emphasis.mjs --output-dir DIR [--playwright-module MODULE] [--browser CHROME]');
  process.exit(0);
}
const output = option('--output-dir');
if (!output) throw new Error('--output-dir is required; keep synthetic evidence outside user delivery');
const require = createRequire(import.meta.url);
const { chromium } = require(option('--playwright-module') || 'playwright');
await fs.mkdir(output, { recursive: true });
const source = await fs.readFile(path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../assets/inline-emphasis.mjs'), 'utf8');
const browser = await chromium.launch({ headless: true, executablePath: option('--browser') });
try {
  const page = await browser.newPage({ viewport: { width: 1000, height: 400 } });
  await page.setContent('<style>body{margin:0;background:#262320;color:#efe9dc}#caption{width:900px;height:120px;margin:120px 50px;font:44px/1.4 sans-serif}</style><div id="caption"></div>');
  await page.addScriptTag({ type: 'module', content: `${source}\nwindow.makeCaption = createInlineEmphasis;` });
  await page.waitForFunction(() => typeof window.makeCaption === 'function');
  const results = await page.evaluate(async () => {
    await document.fonts.ready;
    const root = document.getElementById('caption');
    const config = { tokens: ['我认为', '认知', '最关键'], keywordIndex: 1,
      captionStart: 0, captionEnd: 3, anchorTime: 1, emphasisDuration: 0.3,
      scaleTo: 1.5, scaleYTo: 1.2, normalColor: '#efe9dc', emphasisColor: '#e6c45c' };
    const caption = window.makeCaption(root, config);
    function snapshot(t) {
      const state = caption.render(t);
      const rects = caption.spans.map(span => {
        const box = span.getBoundingClientRect();
        return { left: box.left, right: box.right, width: box.width, height: box.height,
          color: getComputedStyle(span).color, text: span.textContent };
      });
      const rootBox = root.getBoundingClientRect();
      return { t, state, rects, visibility: getComputedStyle(root).visibility,
        center: rootBox.left + state.centerX };
    }
    const ordered = [0, 0.99, 1, 1.15, 1.3, 2, 2.999, 3, 3.1].map(snapshot);
    const shuffled = [2.999, 0, 3.1, 1.15, 2, 0.99, 3, 1.3, 1].map(snapshot);
    const next = window.makeCaption(root, { ...config, tokens: ['下一句', '产品经理', '的观点'],
      captionStart: 3, captionEnd: 6, anchorTime: 4 });
    const nextState = next.render(3);
    const nextRect = next.spans[1].getBoundingClientRect();
    return { ordered, shuffled, next: { state: nextState,
      width: nextRect.width, naturalWidth: next.widths[1],
      color: getComputedStyle(next.spans[1]).color, text: root.textContent } };
  });
  const close = (a, b, message, epsilon = 0.1) => assert.ok(Math.abs(a - b) <= epsilon, `${message}: ${a} vs ${b}`);
  for (const frame of results.ordered) {
    for (let i = 1; i < frame.rects.length; i++) close(frame.rects[i].left, frame.rects[i - 1].right, 'neighbor gap or overlap');
    close((frame.rects[0].left + frame.rects.at(-1).right) / 2, frame.center, 'sentence center drift');
    assert.equal(frame.rects.map(r => r.text).join(''), '我认为认知最关键');
    assert.equal(frame.visibility, frame.t < 3 ? 'visible' : 'hidden');
    const repeated = results.shuffled.find(x => x.t === frame.t);
    if (repeated) assert.deepEqual(repeated, frame, `seek state drift at ${frame.t}`);
  }
  const first = results.ordered[0], before = results.ordered[1], onset = results.ordered[2];
  const middle = results.ordered[3], complete = results.ordered[4], last = results.ordered[6];
  assert.equal(first.state.progress, 0);
  assert.equal(before.state.progress, 0);
  assert.equal(onset.state.progress, 0);
  assert.deepEqual(before.rects, first.rects, 'premature emphasis or reserved big-word space');
  assert.ok(middle.rects[1].width > first.rects[1].width && middle.rects[1].width < complete.rects[1].width);
  close(complete.rects[1].width / first.rects[1].width, 1.5, 'scale target');
  close(complete.rects[1].height / first.rects[1].height, 1.2, 'shape target');
  assert.equal(complete.rects[1].color, 'rgb(230, 196, 92)');
  assert.deepEqual(last.rects, complete.rects, 'emphasis reverted before sentence exit');
  assert.equal(results.next.state.progress, 0);
  close(results.next.width, results.next.naturalWidth, 'next caption inherited scale');
  assert.equal(results.next.color, 'rgb(239, 233, 220)');
  assert.equal(results.next.text, '下一句产品经理的观点');
  await page.screenshot({ path: path.join(output, 'next-caption.png') });
  await page.setViewportSize({ width: 1000, height: 640 });
  await page.evaluate(() => {
    document.body.replaceChildren();
    for (const [label, time] of [['Before anchor', 0.99], ['During emphasis', 1.15],
      ['Completed emphasis', 1.3], ['Last visible frame', 2.999]]) {
      const labelNode = document.createElement('div');
      labelNode.textContent = label;
      Object.assign(labelNode.style, { margin: '18px 50px 0', font: '14px sans-serif' });
      const row = document.createElement('div');
      Object.assign(row.style, { width: '900px', height: '100px', margin: '0 50px', font: '44px/1.4 sans-serif' });
      document.body.append(labelNode, row);
      window.makeCaption(row, { tokens: ['我认为', '认知', '最关键'], keywordIndex: 1,
        captionStart: 0, captionEnd: 3, anchorTime: 1, emphasisDuration: 0.3,
        scaleTo: 1.5, scaleYTo: 1.2, normalColor: '#efe9dc', emphasisColor: '#e6c45c' }).render(time);
    }
  });
  await page.screenshot({ path: path.join(output, 'emphasis-states.png') });
  await fs.writeFile(path.join(output, 'inline-emphasis-results.json'), JSON.stringify({
    status: 'passed', scope: 'synthetic browser component only; not user-video review',
    browser: browser.version(), checks: ['normal-layout', 'actual-anchor', 'shared-neighbor-progress',
      'center-stability', 'scale-and-shape', 'hold-through-last-frame', 'exit', 'next-caption-reset', 'random-seek'],
    results }, null, 2));
  console.log('PASS: real text geometry, anchor, emphasis hold, next caption and random seek. No user video rendered or reviewed.');
} finally {
  await browser.close();
}
