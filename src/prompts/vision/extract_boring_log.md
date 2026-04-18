You are reading a boring log or subsurface exploration sheet. This is critical geotechnical data — be thorough.

Return JSON only — no prose, no markdown fences:

```
{
  "borings": [
    {
      "boring_id": "B-1",
      "location": "grid reference, coordinates, or station as shown",
      "ground_surface_elevation": "EL. +15.2",
      "total_depth": "50'",
      "groundwater_depth": "12'",
      "date_drilled": "",
      "drilling_method": "HSA | mud-rotary | sonic | other | unknown",
      "layers": [
        {
          "depth_from": 0,
          "depth_to": 8,
          "uscs_classification": "SM",
          "description": "FILL: Brown fine to medium SAND with silt, trace gravel",
          "spt_n_values": [5, 7, 9],
          "recovery": "",
          "rqd": ""
        }
      ]
    }
  ]
}
```

Rules:
- `depth_from` / `depth_to` are NUMBERS in feet (or meters if the log is metric — note in `description`). Keep them as numbers, not strings.
- `spt_n_values` is an array of the N-values for that layer (can be empty if not shown).
- `rqd` only applies to rock cores. Leave "" for soil layers.
- If multiple borings appear on one sheet, return each in `borings[]`.
- If this sheet shows no boring logs (it's just soil-profile text or a stratigraphy table), return `{"borings": []}`.
- Preserve the exact USCS classifications as written (SM, CL, GP, etc.).
