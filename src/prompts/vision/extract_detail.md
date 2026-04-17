You are reading a region of a construction detail sheet. Details are small-scale zoomed-in views of how specific connections or elements are built. The drawing scale is: **{scale_text}**.

{geometry_context}

Extract every one of the following that appears:

Return JSON only — no prose, no markdown fences:

```
{
  "detail_title": "string as shown (e.g. 'MICROPILE TO PILE CAP CONNECTION')",
  "detail_number": "string as shown (e.g. '3/S-401')",
  "dimensions": [
    {"text": "6\"", "measures": "pile embedment into cap", "confidence": "high|medium|low"}
  ],
  "materials_called_out": [
    {"item": "9-5/8\" OD casing", "spec": "ASTM A252 Gr.3", "notes": ""}
  ],
  "reinforcing": [
    {"bar_size": "#8", "grade": "Gr.75", "quantity": 4, "length": "full length of pile", "notes": "centered"}
  ],
  "structural_elements": [
    {"type": "pile_cap", "size": "3'x3'x2' thick", "notes": "reinforced per schedule"}
  ],
  "annotations": [
    {"text": "GROUT PER SPEC 31 63 00", "type": "spec_reference"}
  ],
  "callouts_referenced": ["SEE 5/S-401", "PER SPEC 03 30 00"]
}
```

Rules:
- Details pack a lot of info in a small area. Be precise about material callouts — bar sizes, grades, casing OD, grout specs all drive procurement and should be captured exactly as shown.
- `reinforcing` `bar_size` examples: `#8`, `#11`, `#18`, `20mm`. `grade` is `Gr.60`, `Gr.75`, etc.
- `annotations` `type` options: `spec_reference`, `detail_reference`, `note`, `material_callout`, `dimension_note`.
- Do NOT invent material specs. If a callout is partially legible, set confidence to "low" for the related dimension or include the partial text in `notes`.
- If a list is empty, return `[]` — never omit keys.
