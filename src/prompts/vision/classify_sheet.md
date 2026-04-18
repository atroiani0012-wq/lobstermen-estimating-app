You are analyzing a construction plan sheet. Look at the full page and classify it.

Return JSON only — no prose, no markdown fences:

```
{
  "sheet_type": "plan_view | section | detail | elevation | boring_log | schedule | cover | notes | general",
  "sheet_number": "string, e.g. S-101, or null",
  "sheet_title": "string, e.g. Foundation Plan, or null",
  "discipline": "structural | civil | geotech | architectural | mechanical | general",
  "contains_dimensions": true|false,
  "contains_symbols": true|false,
  "contains_boring_logs": true|false,
  "contains_tables": true|false,
  "notes": "one short sentence summarizing what this sheet shows"
}
```

Rules:
- Pick the SINGLE best `sheet_type`. "plan_view" means a top-down layout; "section" is a vertical cut; "detail" is a zoomed-in callout; "boring_log" is a subsurface exploration record; "schedule" is a table of items (e.g., a pile schedule); "notes" is a text-only sheet.
- Read the title block for `sheet_number` and `sheet_title` when possible.
- `discipline` should reflect the drawing's primary purpose. Geotech = borings, soil profiles, shoring, ground-improvement; structural = foundations, piles, walls; civil = grading, utilities, site plans.
- If you cannot read a field clearly, use null (for strings) or false (for booleans). Do not guess.
