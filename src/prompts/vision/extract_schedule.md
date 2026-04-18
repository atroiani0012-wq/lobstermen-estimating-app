You are reading a schedule (table) on a construction drawing. Common schedules include: pile schedule, tieback schedule, boring schedule, anchor schedule, load schedule.

Return JSON only — no prose, no markdown fences:

```
{
  "schedule_title": "string as shown (e.g. 'MICROPILE SCHEDULE')",
  "columns": ["ID", "TYPE", "DIAMETER", "BOND LENGTH", "TOTAL LENGTH", "DESIGN LOAD", "NOTES"],
  "rows": [
    {
      "ID": "MP-1",
      "TYPE": "Micropile",
      "DIAMETER": "9-5/8\"",
      "BOND LENGTH": "25'",
      "TOTAL LENGTH": "80'",
      "DESIGN LOAD": "300 kip",
      "NOTES": ""
    }
  ],
  "row_count": 42,
  "summary": "42 micropiles, 300-kip design load, 80' total length each"
}
```

Rules:
- Preserve the table header text EXACTLY as drawn, including capitalization, because procurement later searches for these. Use them as the keys in each row object.
- If the table contains ranges (e.g., `MP-1 through MP-42`), expand `row_count` to the total and list as many individual rows as you can read.
- If a cell is empty or illegible, use an empty string `""`. Don't guess.
- The `summary` should be a single sentence an estimator can read quickly to understand the scope implied by the schedule.
- If this region is not actually a schedule but was classified as one by mistake, return `{"schedule_title": "", "columns": [], "rows": [], "row_count": 0, "summary": "no schedule present in this region"}`.
