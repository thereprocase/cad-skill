# Round 1: Ent Designer Report — Cable Organizer Box

## Design
28×55×12mm desk block. 3 open-top troughs, 6mm wide (5mm USB-C cable + 0.5mm clearance per side). 9mm-wide connector heads catch on the 2mm floor. Cable retention depth 50mm. PLA.

## Bugs Found

### Bug 1 — validate_geometry.py UnicodeEncodeError on Windows
The `≥` character in PASS messages crashes Windows cp1252 console encoding. Exits code 1 even when all checks pass. Fix: use ASCII `>=`.

### Bug 2 — check_printability.py wall thickness false positive on open-slot geometry
`_min_thickness_from_path2d()` uses `draw.polygon(..., fill=255)` for all entities. Open-top slots (inner rectangles inside outer perimeter) get painted white-over-white — no hole rendered. Distance transform measures corner proximity of solid rectangle, not actual walls. Reports 1.2mm regardless of true 2.5mm walls. Fix: implement even-odd fill rule.

### Bug 3 — SKILL.md: undocumented slot vs pocket distinction
`"slot"` triggers gap probing, `"pocket"` triggers component-fit checking. Open-top troughs need `"pocket"` but read as `"slot"` conversationally. SKILL.md needs a decision guide.

### Bug 4 — SKILL.md: ambiguous spec guidance for phased builds
"Write spec immediately after parameters" implies final-part spec, but validators check against current phase geometry. Phase 1 spec with slot features fails on solid box. Need: spec should only declare features present in current export.

## Phase Notes
- Phase 0: Workflow correctly gates on user requirements. No issues.
- Phase 1: Spec scope confusion (Bug 4). After fix, 4/4 pass.
- Phase 2: Slot vs pocket confusion (Bug 3), wall thickness false positive (Bug 2). 
- Phase 3: Clean. Bottom chamfer applied, verify_boolean confirmed. 6/6 PASS.
