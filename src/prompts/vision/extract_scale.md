You are reading the title block of a construction drawing. Find the scale.

Look for:
- Text like `SCALE: 1/4" = 1'-0"` or `1" = 10'` or `SCALE 1:100`
- Graphical scale bars (a ruler-like bar with distance markings)
- `NTS` or `NOT TO SCALE` annotations
- Multiple scales — some sheets have different scales for different views (e.g., plan at 1"=10', details at 1"=1')

Return JSON only — no prose, no markdown fences:

```
{
  "scale_text": "exact text as shown on the drawing",
  "scale_ratio": <number: real-world inches per drawing inch, e.g. 120 for 1"=10'>,
  "scale_type": "engineering | architectural | metric | nts | none",
  "confidence": "high | medium | low",
  "multiple_scales": [
    {"view": "plan", "scale_text": "...", "scale_ratio": <number>}
  ] | null
}
```

Conversion rules for `scale_ratio`:
- Engineering (1" = 10'): ratio = 120 (10 feet × 12 inches)
- Engineering (1" = 20'): ratio = 240
- Architectural (1/4" = 1'-0"): ratio = 48 (1 foot / 0.25)
- Architectural (1/8" = 1'-0"): ratio = 96
- Metric (1:100): ratio = 100 (keep unitless — this is a straight ratio)
- NTS or unknown: ratio = null

If multiple scales are visible for different views, populate `multiple_scales` with each one. Otherwise set it to null. Set `confidence` to "high" only when you can read the scale text directly; "medium" if inferred from a scale bar; "low" if you had to guess.
