export function quantileScale(values, ramp) {
  const clean = values
    .filter(v => v != null && !Number.isNaN(v))
    .sort((a, b) => a - b);

  const bins = ramp.length;
  const breaks = [];

  if (clean.length === 0) {
    return { color: () => '#E3E6EB', breaks: [], ramp, min: null, max: null };
  }

  for (let i = 1; i < bins; i++) {
    const pos = (i / bins) * (clean.length - 1);
    const lo = Math.floor(pos);
    const hi = Math.ceil(pos);
    const t = pos - lo;
    breaks.push(clean[lo] * (1 - t) + clean[hi] * t);
  }

  function color(v) {
    if (v == null || Number.isNaN(v)) return '#E3E6EB';
    for (let i = 0; i < breaks.length; i++) {
      if (v < breaks[i]) return ramp[i];
    }
    return ramp[bins - 1];
  }

  return {
    color, breaks, ramp,
    min: clean[0],
    max: clean[clean.length - 1],
  };
}

export function legendRanges(scale, formatter = (x) => x) {
  if (scale.breaks.length === 0) return [];
  const ranges = [];
  const all = [scale.min, ...scale.breaks, scale.max];
  for (let i = 0; i < scale.ramp.length; i++) {
    ranges.push({
      color: scale.ramp[i],
      label: `${formatter(all[i])} – ${formatter(all[i + 1])}`,
    });
  }
  return ranges;
}
export function sizeScale(values, [rMin, rMax] = [4, 20]) {
  const clean = values.filter(v => v != null && !Number.isNaN(v)).sort((a, b) => a - b);
  if (clean.length === 0) {
    return { radius: () => rMin, min: null, max: null };
  }
  const min = clean[0];
  const max = clean[clean.length - 1];
  const span = max - min;

  function radius(v) {
    if (v == null || Number.isNaN(v)) return rMin;
    if (span <= 0) return (rMin + rMax) / 2;
    const t = Math.max(0, Math.min(1, (v - min) / span));
    return rMin + (rMax - rMin) * Math.sqrt(t);
  }
  return { radius, min, max };
}