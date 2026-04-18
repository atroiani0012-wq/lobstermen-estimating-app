You are reading a region of a structural or geotechnical section drawing. The drawing scale is: **{scale_text}**.

{geometry_context}

A section shows the ground / structure cut vertically. Extract:

Return JSON only — no prose, no markdown fences:

```
{
  "depths": [
    {"text": "35'-0\"", "measures": "pile embedment depth", "from": "top of pile", "to": "tip elevation", "confidence": "high|medium|low"}
  ],
  "elevations": [
    {"text": "EL. -22.5", "reference": "pile tip elevation", "datum": "MLLW | NAVD88 | site | unknown"}
  ],
  "soil_layers": [
    {"depth_from": "0'", "depth_to": "8'", "description": "FILL - sand and gravel", "spt_n": ""}
  ],
  "structural_elements": [
    {"type": "micropile", "size": "7\" casing", "length": "40'", "angle": "15° from vertical", "spacing": "6' O.C."}
  ],
  "other_dimensions": [
    {"text": "value", "measures": "what it measures", "confidence": "high|medium|low"}
  ]
}
```

Rules:
- Use the geometry data above for any dimension line already listed — don't re-read the same value.
- For `soil_layers`, include SPT N-values when shown as `spt_n`. Leave it `""` when not on this sheet.
- `structural_elements` `type` options: `micropile`, `soldier_pile`, `soil_nail`, `tieback`, `drilled_shaft`, `helical_pile`, `lagging`, `wale`, `shotcrete`, `grade_beam`, `pile_cap`, `other`.
- Do NOT guess elevations or depths you cannot read clearly — mark confidence "low" and include the partial reading.
- If a list is empty, return `[]` — never omit keys.
