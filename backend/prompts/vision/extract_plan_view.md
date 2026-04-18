You are reading a region of a construction plan view drawing. The drawing scale is: **{scale_text}** ({scale_type}).

{geometry_context}

Extract every one of the following that appears in this region. Use the geometry data above as ground-truth for dimension lines that are listed there — don't second-guess values the vector extraction already read. Report additional dimensions you can see in the image but that aren't in the geometry list.

Return JSON only — no prose, no markdown fences:

```
{
  "dimensions": [
    {"text": "25'-0\"", "measures": "pile spacing", "units": "feet", "confidence": "high|medium|low"}
  ],
  "pile_or_anchor_symbols": [
    {"symbol_type": "micropile", "approximate_location": "grid B-3", "count_in_region": 4}
  ],
  "wall_sections": [
    {"type": "soldier pile wall", "length": "45'-0\"", "height": "", "stations": "STA 2+00 to 2+45"}
  ],
  "annotations": [
    {"text": "SEE DETAIL 3/S-401", "type": "detail_reference"}
  ],
  "grid_lines": ["A", "B", "C", "1", "2", "3"]
}
```

Rules:
- Count EACH symbol only once — if a symbol straddles a region boundary it will appear in a neighboring region too; the caller will de-duplicate.
- For dimensions, `text` is the exact string as drawn; `measures` is what the dimension is between (pile-to-pile spacing, wall thickness, column grid, etc.); `units` is "feet" | "inches" | "meters" | "millimeters" | "mixed".
- Do NOT guess dimensions you cannot read — set `confidence` to "low" and include the partial reading.
- For `pile_or_anchor_symbols`, `symbol_type` should be one of: `micropile`, `soldier_pile`, `soil_nail`, `tieback`, `drilled_shaft`, `h_pile`, `pipe_pile`, `anchor`, `boring_location`, `other`.
- If a list is empty, return `[]` — never omit keys.
