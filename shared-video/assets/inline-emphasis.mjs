/** V24 single-line caption. Absolute-time evaluation; no timers or yoyo state. */
export function createInlineEmphasis(root, config) {
  const { tokens, keywordIndex, captionStart, captionEnd, anchorTime,
    emphasisDuration, scaleTo = 1.4, scaleYTo = scaleTo,
    normalColor = '#efe9dc', emphasisColor = '#e6c45c' } = config;
  if (!Array.isArray(tokens) || !tokens.length || tokens.some(t => typeof t !== 'string' || !t.length)) {
    throw new Error('tokens must contain non-empty real text runs');
  }
  if (!Number.isInteger(keywordIndex) || keywordIndex < 0 || keywordIndex >= tokens.length ||
      ![captionStart, captionEnd, anchorTime, emphasisDuration, scaleTo, scaleYTo].every(Number.isFinite) ||
      captionStart < 0 || captionStart > anchorTime || emphasisDuration <= 0 ||
      anchorTime + emphasisDuration >= captionEnd || scaleTo <= 1 || scaleYTo <= 0) {
    throw new Error('invalid caption window, anchor, duration or scale');
  }
  const rgb = value => {
    if (!/^#[\da-f]{6}$/i.test(value)) throw new Error('use explicit #rrggbb colors');
    return [1, 3, 5].map(i => parseInt(value.slice(i, i + 2), 16));
  };
  const from = rgb(normalColor), to = rgb(emphasisColor);
  root.replaceChildren();
  Object.assign(root.style, { position: 'relative', whiteSpace: 'pre', overflow: 'visible' });
  const spans = tokens.map(text => {
    const span = document.createElement('span');
    span.textContent = text;
    Object.assign(span.style, { position: 'absolute', display: 'inline-block', left: '0px', top: '0px',
      transformOrigin: '0% 50%', font: 'inherit', letterSpacing: 'inherit', transition: 'none' });
    root.append(span);
    return span;
  });
  // Call after document.fonts.ready. Rebuild when the font or layout changes.
  const widths = spans.map(span => span.getBoundingClientRect().width);
  if (widths.some(width => !(width > 0))) throw new Error('caption font/layout is not measurable');
  const baseWidth = widths.reduce((sum, width) => sum + width, 0);
  function render(time) {
    if (!Number.isFinite(time)) throw new Error('time must be finite');
    const active = time >= captionStart && time < captionEnd;
    const raw = Math.max(0, Math.min(1, (time - anchorTime) / emphasisDuration));
    const p = 1 - (1 - raw) ** 3;
    const sx = 1 + (scaleTo - 1) * p, sy = 1 + (scaleYTo - 1) * p;
    const totalWidth = baseWidth + widths[keywordIndex] * (sx - 1);
    const centerX = config.centerX ?? root.clientWidth / 2;
    let x = centerX - totalWidth / 2;
    const color = `rgb(${from.map((v, i) => Math.round(v + (to[i] - v) * p)).join(', ')})`;
    root.style.visibility = active ? 'visible' : 'hidden';
    root.setAttribute('aria-hidden', active ? 'false' : 'true');
    spans.forEach((span, index) => {
      const keyword = index === keywordIndex;
      span.style.transform = `translateX(${x}px) scale(${keyword ? sx : 1}, ${keyword ? sy : 1})`;
      span.style.color = keyword ? color : normalColor;
      x += widths[index] * (keyword ? sx : 1);
    });
    return { active, progress: p, scaleX: sx, scaleY: sy, totalWidth, baseWidth, centerX, color };
  }
  render(captionStart - 1);
  return { render, spans, widths };
}
