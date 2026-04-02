---
name: cad-skill
description: "Use this skill whenever the user wants to design, generate, or iterate on 3D-printable parts, enclosures, brackets, mounts, cases, or any physical object described in conversation. Triggers include: mentions of STL, STEP, CadQuery, 3D printing, FDM, enclosure, bracket, mount, case, holder, stand, or any request to create a physical object. Also triggers when the user describes a shape, mechanism, or fitting they want fabricated. Do NOT use for Fusion 360 GUI workflows or non-physical software artifacts."
---

# CAD Skill — Parametric 3D-Printable Part Design with CadQuery

## Overview

This skill turns conversational descriptions into parametric CadQuery scripts that produce print-ready STL files. It uses an **interactive, checkpoint-driven workflow** so mistakes are caught early rather than discovered at the slicer.

## Dependencies

Before first use, run the setup script:
```bash
bash ~/.claude/skills/cad-skill/scripts/setup_env.sh
```
This installs CadQuery, trimesh, and rendering dependencies via pip.

To run any CadQuery script:
```bash
python <script.py>
```

## Version Control

The working directory is a git repo. Commit at milestones — after base shape approval, after batch gen works, after plate packing, before scrapping an approach. CAD projects iterate heavily; git is the safety net.

`.gitignore` should exclude generated output (`final/`, `*.stl`, `*.png`, `__pycache__/`) but **track** scripts, STEP source files, and research docs. The scripts ARE the project — STEPs are regenerable.

## Workflow — Three Visual Checkpoints

**NEVER batch the entire model.** Build incrementally with user feedback at each phase.

### Phase 0: Requirements Gathering
- Ask the user what they're building. Clarify dimensions, tolerances, material (PLA/PETG/TPU/ABS), and printer if known.
- If the part interfaces with a real product (phone, PCB, charger, sensor), **research exact dimensions** before designing. Use datasheets, manufacturer specs, or accessory design guidelines.
- Confirm understanding before generating any code.

### Pre-flight: Environment Check
- Verify CadQuery is importable: `python -c "import cadquery; print('OK')"`
- Verify trimesh: `python -c "import trimesh; print('OK')"`
- Verify matplotlib: `python -c "import matplotlib; print('OK')"`
- If any fail, run: `pip install cadquery trimesh matplotlib pillow`

### Phase 1: Base Shape
- Generate a CadQuery script that creates ONLY the primary form — the outer shell, the main body, the base plate.
- **Spec capture:** Immediately after the parameters block, lock in the design intent by writing a spec file. This happens BEFORE any geometry generation so the validators know what you meant to build:
  ```python
  import sys
  from pathlib import Path
  sys.path.insert(0, str(Path.home() / ".claude/skills/cad-skill/lib"))
  from spec_format import create_spec, write_spec

  spec = create_spec(
      "DDR4 DIMM tray",
      width=60.0, depth=40.0, height=25.0,
      material="PLA",
      min_wall_mm=2.0,
      components=[
          {"name": "DDR4 DIMM", "length": 133.35, "width": 31.25,
           "height": 3.8, "clearance_mm": 0.5},
      ],
      features=[
          {"type": "slot", "name": "DIMM slot", "width": 5.0,
           "probe_z": 5.0, "tolerance": 0.3},
      ],
  )
  write_spec(spec, "part.step")   # writes part.spec.json
  ```

  **Feature type guide:**
  - `"slot"` — a closed gap or through-cut between walls. Validator probes cross-section gap width. Use when the feature has material on BOTH sides.
  - `"pocket"` — an open cavity, recess, or trough. Validator checks component fit envelope. Use for open-top channels, blind pockets, and recesses where one side is open.
  - `"hole"` — a circular through-hole or blind hole. Validator matches by diameter.
  - `"channel"` — a long continuous groove. Validator checks cross-section profile.
  - When in doubt: if the feature is open on top or one side, use `"pocket"`. If it has walls on all sides, use `"slot"`.

  **Spec scope per phase:** The spec describes ONLY the geometry present in the current phase's export. Phase 1 spec = overall dimensions and material only — no features. Phase 2 spec = add features as they're built. Phase 3 spec = final complete spec. Each phase's export gets its own spec that matches what exists in that STEP file.

  **Every measurable feature MUST be declared.** Every hole, slot, pocket, screw boss, and structural feature in the geometry must appear in the spec. If the spec has no features, the validators cannot verify internal geometry and cross-sections have nothing to cut against. An empty `features` array on a part with holes is a spec capture failure — go back and declare them.

- Export STEP and run **post-export validation** (see below).
- Render a 4-view preview using the render script.
- **Render cross-sections** — these are mandatory at every checkpoint, not optional:
  ```bash
  python ~/.claude/skills/cad-skill/scripts/render_cross_sections.py part.step
  ```
  Cross-sections verify internal geometry that 3D renders cannot show. For thin parts, shallow slots, and internal cavities, the cross-sections ARE the review — the 3D preview only shows the outside.
- **Show the preview, cross-sections, and validator results to the user.** Ask: "Does this base shape and proportion look right?"
- Iterate until the base is approved.

> **GATE: Do not proceed to the next phase until the user explicitly approves this phase.** If the user has not responded, wait. If the user rejects, iterate on this phase until approved. Delivering a finished part without intermediate checkpoint approvals violates the workflow.

### Phase 1.5: Text & Labeling
If the part needs text labels, handle them BEFORE mechanical features (holes, chamfers) because those operations pollute the workplane origin.

1. **Measure text bounding boxes** — Generate each label with CadQuery `.text()` at a reference size, measure the bounding box, compute width/height ratios.
2. **Compute font size** — Use measured ratios to fit text within the available body area with 2mm margin on each side.
3. **Use a fresh workplane** — NEVER chain `.text()` from `.faces(">Z").workplane()` after other operations. Use `cq.Workplane("XY").transformed(offset=(...), rotate=(...))` instead.
4. **For deboss:** Create text on fresh workplane, then `.cut()`. (`combine='cut'` is unreliable.)
5. **For emboss:** Create text on fresh workplane, `.union()`, then `.intersect()` with body profile to clip overflow.
6. **Render close-up preview** and verify text is within bounds before proceeding.

### Post-Export Validation (after every phase)

After exporting STEP, run ALL THREE validation tools before showing anything to the user:
```bash
python ~/.claude/skills/cad-skill/scripts/validate_geometry.py part.step
python ~/.claude/skills/cad-skill/scripts/check_printability.py part.step
python ~/.claude/skills/cad-skill/scripts/render_cross_sections.py part.step
```
- **FAIL = fix before showing the user.** The whole point is Claude catches its own mistakes.
- **WARN = OK to show.** Flag warnings to the user so they can decide.
- **Cross-sections are mandatory every iteration.** Minimum 3 sections per checkpoint (XY, XZ, YZ). Feature-driven cuts are added on top. Show ALL section PNGs to the user alongside the 3D preview. For thin parts and internal geometry, the cross-sections are more informative than the 3D render.
- `validate_geometry.py` reads the `.spec.json` written during spec capture. If there's no spec file, it errors — that's the reminder to write one.
- `check_printability.py` works with or without a spec (falls back to FDM defaults).
- `render_cross_sections.py` reads the spec for smart cut locations but always produces at least 4 sections even with an empty spec.

### Phase 2: Features
- Add internal features: holes, slots, pockets, mounting posts, cable routes, fillets, chamfers.
- **Update the spec** to declare every new feature (holes, slots, pockets). An empty `features` array at Phase 2 is always wrong — you just added features, declare them.
- Export STEP, run ALL THREE post-export tools (validate_geometry, check_printability, render_cross_sections).
- Show preview, cross-sections, and validator results to the user.
- **Ask:** "Are the features positioned correctly? Anything to add or move?"
- Iterate until features are approved.

> **GATE: Do not proceed to the next phase until the user explicitly approves this phase.** If the user has not responded, wait. If the user rejects, iterate on this phase until approved. Delivering a finished part without intermediate checkpoint approvals violates the workflow.

> **When the user gives multiple corrections:** Fix functional mismatches first (wrong feature type, missing features, incorrect dimensions for interfacing parts), then aesthetic issues (depth, fillet radius, proportions). A part with the right features at wrong proportions is closer to done than a part with wrong features at right proportions.

### Phase 3: Print Optimization & Delivery
- Apply print-friendly adjustments: chamfer bottom edges (not fillet — fillets need supports), check overhang angles, ensure wall thickness.
- Export final STL + STEP.
- Run ALL THREE post-export tools. Fix any FAILs.
- Run the self-review checklist (see below) for anything the scripts can't check.
- Show final preview, cross-sections, and validator results to the user.
- Present a **parameter table** listing all key dimensions so the user can request quick tweaks.

> **GATE: Do not proceed to the next phase until the user explicitly approves this phase.** If the user has not responded, wait. If the user rejects, iterate on this phase until approved. Delivering a finished part without intermediate checkpoint approvals violates the workflow.

### Phase 4: Plate Packing (Bitmap Nesting)

When generating multiple parts for a single print bed, use **bitmap-based nesting** — not bounding boxes. Bounding boxes waste 30-50% of bed space on concave shapes (crescents, L-brackets, etc.). Bitmap nesting uses actual geometry so parts interlock.

#### Algorithm

1. **Confirm bed dimensions** — Ask for printer model. Common: Bambu P1S/P2S (256x256mm), Prusa MK4 (250x210mm).
2. **Rasterize each part's XY footprint** at 0.5mm/pixel resolution using PIL:
   ```python
   from PIL import Image, ImageDraw
   verts, faces = solid.tessellate(0.5)
   pts = np.array([(v.x, v.y) for v in verts])
   # shift to origin, scale to pixels
   img = Image.new('1', (w_px, h_px), 0)
   draw = ImageDraw.Draw(img)
   for f in faces:
       tri = pts[[f[0], f[1], f[2]]] / RESOLUTION
       draw.polygon([(tri[j][0], tri[j][1]) for j in range(3)], fill=1)
   bitmap = np.array(img, dtype=bool)
   ```
3. **Prepare rotations** — For each part, precompute bitmaps at 0°, 90°, 180°, 270°. Discard rotations that don't fit the bed.
4. **Bottom-left-fill placement** — Sort parts by area (largest first). For each part, scan the bed bitmap from bottom-left, try all rotations, pick the one giving the lowest Y placement:
   ```python
   def find_placement(blocked, part_bm):
       for y in range(0, max_y, step):
           for x in range(0, max_x, step):
               if blocked[y, x]: continue  # quick skip
               if not np.any(blocked[y:y+ph, x:x+pw] & part_bm):
                   return x, y
       return None
   ```
5. **Maintain spacing** — After placing each part, recompute the blocked bitmap as `scipy.ndimage.binary_dilation(occupied, spacing_struct)` plus bed margins. This ensures uniform spacing without cumulative drift.
6. **Build compound plates** using OCC directly (not `Compound.makeCompound` which expects CQ Shape wrappers):
   ```python
   from OCP.TopoDS import TopoDS_Compound
   from OCP.BRep import BRep_Builder
   builder = BRep_Builder()
   comp = TopoDS_Compound()
   builder.MakeCompound(comp)
   for item in plate:
       placed = item['solid'].moved(Location(Vector(x_mm, y_mm, 0)))
       builder.Add(comp, placed.wrapped)
   compound = cq.Shape(comp)
   ```
7. **Export both STL and STEP** per plate. Report plate assignments with part count and utilization.

#### Key Insights

- **Concave shapes interlock**: Crescents rotated 90°/270° nest into each other's concavities. This is invisible to bounding-box packers.
- **Coarse-then-fine scan**: Use step=4 for initial placement search, refine to step=1 around hits. Keeps runtime under 60s for 76 parts.
- **Oversize handling**: Parts exceeding the bed at all rotations get their own plate with a WARNING flag.
- **Dependencies**: `numpy`, `scipy`, `Pillow` — all standard. No nest2D/pynest2d needed (no Windows wheels available).

## Self-Review Checklist

The automated validators handle most of this list. The checklist below is the fallback for things the scripts can't see — visual shape correctness and design-intent items that require a human eye on the render.

After every preview render, check the following before showing to the user:

1. **Shape match** — Does the geometry match what was requested? *(visual — not automatable)*
2. **Feature completeness** — Are all holes, slots, and cutouts present and visible? *(visual — not automatable)*
3. **Flat bottom** — *(automated by `check_printability.py`)* Verify the script reported PASS.
4. **Overhang check** — *(automated by `check_printability.py`)* WARNs are OK; FAILs need redesign. Prefer chamfer over fillet at bed contact edges.
5. **Wall thickness** — *(automated by both `check_printability.py` and `validate_geometry.py`)* Scripts check cross-sections; visually confirm corners too.
6. **Corner wall thinning** — At a filleted corner the diagonal wall = `r_ext - r_int`. If the interior cavity has sharp corners (r_int = 0) and r_ext = 2mm, the diagonal wall collapses to ~0.83mm. Fix: set `r_int = r_ext - wall` for concentric arcs (uniform thickness). Easiest implementation: fillet exterior edges first, then use `shell(-wall)` — CadQuery propagates the fillet inward automatically, giving correct r_int at vertical corners AND floor-to-wall transitions. For slip-on lids, set `r_lid_int = r_ext + clearance` so the lid slides over without catching. *(partially automated — scripts catch the result; this explains the fix)*
7. **Boolean integrity** — *(automated by `cq_debug_helpers.verify_boolean()` during construction)* If you used inline checks, this is already covered. If not, look for floating geometry or missing material in the render.
8. **Printability** — *(automated by `check_printability.py`)* Bridge spans, min feature size. Verify PASS.
9. **Clearance** — Hole diameters include +0.3mm clearance for FDM. *(automated by `validate_geometry.py` when holes are declared in the spec)*

If any automated check FAILed, fix it BEFORE showing the preview.

## CadQuery Script Template

Every generated script should follow this structure:

```python
import cadquery as cq
import sys
from pathlib import Path

# Construction-time checks — catch silent boolean failures as they happen
sys.path.insert(0, str(Path.home() / ".claude/skills/cad-skill/scripts"))
from cq_debug_helpers import verify_boolean, verify_feature_bounds

# Spec capture — lock in design intent before building geometry
sys.path.insert(0, str(Path.home() / ".claude/skills/cad-skill/lib"))
from spec_format import create_spec, write_spec

# ============================================================
# PARAMETERS — edit these to customize the part
# ============================================================
width = 60.0        # mm
depth = 40.0        # mm
height = 25.0       # mm
wall = 2.0          # mm — wall thickness
r_ext = 3.0         # mm — exterior corner fillet radius
r_int = r_ext - wall  # 1.0 mm — interior corner radius (concentric = uniform wall at corners)
                      # For a slip-on lid: r_lid_int = r_ext + clearance (clears box corners)
clearance = 0.3     # mm — FDM clearance for mating parts

# ============================================================
# SPEC — declare what you're building (validators read this)
# ============================================================
spec = create_spec("Example box", width=width, depth=depth, height=height,
                   material="PLA", min_wall_mm=wall)
write_spec(spec, "part.step")

# ============================================================
# MODEL
# ============================================================
result = (
    cq.Workplane("XY")
    .box(width, depth, height)
    # ... more operations
)

# Inline boolean verification — use after every .cut() or .union()
# before = result
# result = result.cut(pocket)
# result = verify_boolean(before, result, "cut", "pocket")
#
# Inline bounds check — use after adding embossed features
# result = verify_feature_bounds(base_body, result, "label emboss")

# ============================================================
# EXPORT — prefer STEP (exact arcs), STL only if slicer needs it
# ============================================================
cq.exporters.export(result, "part.step")
print(f"Exported: {width}x{depth}x{height}mm")
```

### Construction-Time Checks

Use `cq_debug_helpers` inline during geometry construction to catch problems the moment they happen — not after export:

```python
from cq_debug_helpers import verify_boolean, verify_feature_bounds

# After a boolean cut: catches silent failures where .cut() returns unchanged geometry
before = result
result = result.cut(pocket)
result = verify_boolean(before, result, "cut", "pocket")

# After adding features: catches geometry that overflows the base body footprint
result = verify_feature_bounds(base_body, result, "mounting posts")
```

These raise `RuntimeError` immediately on failure, so you fix the problem in the same script run rather than discovering it in the render 60 seconds later.

## Preview Rendering

Render a multi-view preview from STEP (preferred) or STL:
```bash
python ~/.claude/skills/cad-skill/scripts/render_preview.py part.step preview.png
```
- **STEP files** render with per-face shading — flat surfaces are clean, no triangle mesh lines.
- **STL files** fall back to per-triangle shading (visible mesh artifacts on flat surfaces).
- Produces a 2x2 grid (front/right/top/perspective) or 2-view (top/perspective) for flat parts.
- Dark charcoal background, two-light setup, 3200px default at 200 DPI.
- Parts fill ~80% of their frame. Titles are light grey condensed sans-serif.
- Read the resulting image to self-review before showing to the user.
- When reviewing renders, check for: missing geometry (unexpected flat areas), z-fighting artifacts (flickering overlapping faces), and features too small to evaluate visually (flag these to the user for slicer verification).

**Always prefer STEP for previews.** Export STEP alongside STL, or STEP-only (slicers import STEP directly).

## FDM Print Defaults

| Parameter | Default | Notes |
|-----------|---------|-------|
| Wall thickness | 2.0mm | Minimum 1.2mm for structural integrity |
| Bottom chamfer | 0.5mm at 45° | Use chamfer, NOT fillet (fillets need supports) |
| Hole clearance | +0.3mm | Added to nominal diameter for FDM fit |
| Screw post ID | screw_d + 0.3mm | Tight fit for self-tapping |
| Screw post OD | screw_d × 2.5 | Enough meat around the hole |
| Max bridge span | 20mm | Longer spans sag |
| Max overhang | 45° | Steeper needs support |
| Min feature size | 0.8mm | Below this, features may not print |
| Snap-fit deflection | 0.5–1.0mm | For PLA; more for TPU |

## Export Format: STEP over STL

**Default to STEP export.** STEP files preserve exact B-rep geometry — arcs are arcs, circles are circles, planes are planes. STL decimates everything to triangles, losing precision and creating ugly preview renders.

- **STEP advantages**: Exact arcs (critical for radius gauges, gears, threads), clean preview rendering, smaller files for curved geometry, slicers (Bambu Studio, PrusaSlicer) import STEP natively.
- **STL only when**: The slicer explicitly requires it, or for compound plate files where STEP export is slow.
- **For preview rendering**: Always use STEP. The render script extracts per-face topology from STEP via OCC, giving uniform shading per B-rep face. STL previews show triangle mesh artifacts on flat surfaces.

### Material Adjustments
- **PLA**: Default tolerances. Rigid, easy to print.
- **PETG**: +0.1mm extra clearance. Slight stringing.
- **TPU**: +0.2mm clearance, 3mm+ walls for structure, flexible snap-fits.
- **ABS**: Standard clearance but account for warping on large flat surfaces.

## Parameter Table Format

After final delivery, present parameters like this:

```
┌─────────────────────┬─────────┬──────────────────────┐
│ Parameter           │ Value   │ Notes                │
├─────────────────────┼─────────┼──────────────────────┤
│ Overall width       │ 60mm    │                      │
│ Overall depth       │ 40mm    │                      │
│ Overall height      │ 25mm    │                      │
│ Wall thickness      │ 2.0mm   │ Min 1.2mm            │
│ Corner radius       │ 3.0mm   │                      │
│ Hole diameter       │ 4.3mm   │ M4 + 0.3mm clearance │
└─────────────────────┴─────────┴──────────────────────┘
```

Tell the user: "Want to adjust any of these? Just say 'make it 5mm taller' or 'move the hole left 10mm' and I'll regenerate."

## Common Patterns

### Box with lid
Use `shell(-wall)` to hollow after filleting exterior vertical edges — the shell propagates `r_int = r_ext - wall` automatically, keeping corner walls uniform and strengthening floor-to-wall transitions. For a slip-on lid: lid interior dims = box exterior dims + 2×clearance each side; lid interior corner r = r_ext + clearance (so it slides over box corners without catching). Fillet lid exterior corners concentrically: r_lid_ext = r_lid_int + lid_wall.

### PCB enclosure
Start from PCB dimensions + clearance. Add standoffs at mounting hole positions. Route cable slots from connector positions.

### Phone/device case
Research exact device dimensions from manufacturer specs. Use shell() for the inner cavity. Taper lips at 40° for printability. Button cutouts as bumps (not recesses) for tactile feedback.

### Bracket/mount
L-shape or U-shape base. Screw holes with countersinks. Fillet the inside corner for strength.

### Radius/fillet gauges and arc templates
Two forms depending on size:
- **Paddle** (small radii, ≤ ~32mm): Convex semicircle bump at one end, concave notch at other end. Straight body with string hole, taper to convex tip. Fillet the notch-to-body junction corners.
- **Crescent** (large radii, > ~32mm): Circle1 minus Circle2, both radius R, centers offset by strip width W = max(15, R/4). **85° arc sweep** — covers 90° corners with margin, avoids wasted material. Sharp measuring tip at one end (where arcs naturally intersect), semicircular key ring cap at the other. No boss needed — the constant-width strip accommodates the hole naturally.

**Crescent geometry:**
```python
h = sqrt(R² - W²/4)              # tip distance from center axis
a1 = atan2(W/2, h)               # angle from C1 to tip
sweep = radians(85)               # arc sweep
out_end = C1 + R * (cos(a1 - sweep), sin(a1 - sweep))  # outer arc endpoint
```

**Text on curved strips — sagitta correction:**
Straight text on a curved strip clips at the edges. The sagitta (chord deviation from arc) = L²/(8R). Max safe text length:
```python
margin = 0.15 * W + 3.4          # remaining width after text height
avail_along = 0.7 * sqrt(4 * R * margin)
```
Use closed-loop verification: intersect text solid with body, compare volumes (98% threshold), shrink 0.75× per iteration until fit. See `_deboss_text()` pattern.

**Gauge set sizing by Weber fraction:**
For tactile identification (not just detection), curvature gaps between adjacent gauges must be < 6%. This drives step sizes: 1/16" for 1-2", 1/8" for 2-4", 1/4" for 4-6".

### Multi-filament text inlays

For parts with debossed text that need multi-color printing, export the text as a **separate solid** that fills the debossed pocket:

1. **Generate text and body separately:** `_deboss_text(gauge, ..., split_text=True)` returns `(body_with_pocket, text_inlay)`. The inlay = text solid intersected with gauge body, so it fills the pocket exactly.
2. **Export as two STEP files** at identical coordinates: `plate_body.step` + `plate_text.step`. Import both into OrcaSlicer, assign different filaments.
3. **Why two files, not one multi-body STEP:** OrcaSlicer has known bugs with multi-body STEP import (explodes compounds into individual solids, loses component hierarchy). Two aligned files is reliable.
4. **Plate packing carries text through:** `pack_plates.prepare_item(solid, name, text_solid=text)` applies identical centering + rotation + translation to both body and text. The `pack_group()` and `export_plates()` functions handle body and text compounds in parallel.

### Closed-loop text fitting (the `_deboss_text()` pattern)

Never trust geometric text size estimates alone — always verify with a boolean intersection check:

```python
# 1. Estimate font size from available space
font_size = _fit_text(label, avail_w, avail_h)
# 2. Generate text solid
text_solid = cq.Workplane("XY").transformed(...).text(label, font_size, -depth)
# 3. Intersect with body, compare volumes
clipped = text_solid_ws.intersect(gauge_ws)
ratio = abs(clipped.val().Volume()) / abs(text_solid.val().Volume())
# 4. If ratio < 0.98: shrink 0.75× and retry (up to 8 iterations)
```

This catches cases where geometric estimates fail: text near pointed crescent tips, long labels on narrow curved strips, text placed near tapers or holes. The 98% threshold catches edge clipping that a 93% threshold misses (a partially clipped character may lose only 5-7% of total text volume).

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Boolean fails silently | Check that cut shapes fully intersect the body. Add 0.01mm extra depth. |
| Shell fails | Reduce fillet radii before shelling. Shell first, fillet after on complex shapes. |
| Fillet fails on edge | Try smaller radius or chamfer instead. Some edge combinations confuse OCCT. |
| Two fillet types on same solid fail | OCCT often fails chaining `edges("<Z").fillet()` then `edges("\|Z").fillet()` (or vice versa) on the same solid. Fix: apply only one fillet type to the solid, then add the second fillet **after** a cut/union using a `BoxSelector` to isolate the target edges by Z-band. Example for interior floor fillet after cut: `tray.edges(cq.selectors.BoxSelector((-x,-y,z-0.1),(x,y,z+0.1), boundingbox=False)).fillet(r)` where z = interior floor height. **Always use `boundingbox=False`** — the default `boundingbox=True` selects edges whose bounding box *intersects* the band, catching tall vertical arcs that merely *start* at that Z level. `boundingbox=False` selects by edge center point, which correctly isolates horizontal perimeter edges only. |
| STL has holes | Increase mesh tolerance: `exporters.export(result, "part.stl", tolerance=0.01)` |
| Preview looks wrong | Re-export STL and re-render. Check units (CadQuery uses mm). |
| Text offset after `.center()` or `.hole()` | `.center()` permanently shifts the workplane origin. Use `.workplane(origin=(0,0,z))` or a fresh `cq.Workplane("XY").transformed(...)` for subsequent features. |
| Deboss produces no visible change | `combine='cut'` often fails silently. Use fresh workplane + explicit `.cut()` instead. Check file size — degenerate STLs are < 1KB. |
| Text rotated wrong direction | `.transformed(rotate=(0,0,90))` rotates CCW. Text string direction follows transformed X axis. |
| Font looks different than expected | CadQuery silently falls back to a default font if the requested font is missing. Verify with a test `.text()` call. |
| Embossed text creates floating geometry | `combine='a'` extends past body outline. Clip with `.intersect(body_profile.extrude(h))` or use deboss instead. |
| `threePointArc` fails with `StdFail_NotDone` | Three points are collinear (e.g., fillet radius ≈ arc radius). Cap fillet at `R * 0.6` to keep the arc midpoint off the line joining endpoints. |
| `Compound.makeCompound()` fails on OCC solids | CQ's wrapper expects `Shape` objects. Use OCC directly: `BRep_Builder` + `TopoDS_Compound`, then wrap with `cq.Shape(comp)`. |
| Crescent has two convex edges (lens shape) | You built an intersection (∩) of two circles — both edges bulge outward. Use **difference** (Circle1 − Circle2) instead: outer edge is convex, inner edge is concave, both radius R. |
| Large crescent doesn't fit print bed | Cap the half-length: `h = min(sqrt(R²-W²/4), max_half_len)`. Cap both ends with semicircular caps if truncated. 85° sweep keeps all gauges ≤ 6" under 176mm. |
| Multi-body STEP explodes in OrcaSlicer | Known slicer bug with compound STEPs. Workaround: export body and text as **separate aligned STEP files**. Import both, assign filaments independently. |
| Multiple features offset after one `.center()` | Each `.center()` is cumulative and persistent. Reset with `.workplane(origin=...)` or break the chain into separate variables. |
| Preview has triangle mesh lines on flat surfaces | Render from STEP, not STL. The STEP renderer uses per-B-rep-face shading so coplanar triangles get identical colors. |
| FDM parts catch/snag on each other | Chamfer ALL edges (0.3-0.4mm) including measuring surfaces. FDM oozes at direction changes, creating micro-bumps at every sharp edge. For gauge sets or stacked parts, this is critical. |
| `validate_geometry.py` reports FAIL on dimensions | Check the spec — do the `overall_dimensions` in `.spec.json` match your parameter block? A mismatch means the spec was written with different values than the geometry used. Fix the spec or the parameters, re-export, re-validate. |
| `validate_geometry.py` can't find `.spec.json` | You forgot the spec capture step. Add `write_spec(spec, "part.step")` after the parameters block, before geometry generation. |
| `validate_geometry.py` reports FAIL on slot/hole width | The feature's actual dimension doesn't match the spec within tolerance. Check probe_z is at the right height (slot may taper). For holes, verify the diameter includes FDM clearance. |
| `check_printability.py` reports FAIL on wall thickness | Thinnest wall is below the threshold. Check corner wall thinning (see checklist item 6). Use `shell(-wall)` after filleting to get concentric arcs. |
| `check_printability.py` reports FAIL on bridge span | An unsupported horizontal span exceeds the max (default 20mm). Add support ribs, split the span, or redesign the cavity. |
| `verify_boolean` raises RuntimeError | The `.cut()` or `.union()` didn't change the geometry — the tool solid probably doesn't intersect the body. Check positioning; add 0.01mm extra depth to through-cuts. |
| `verify_feature_bounds` raises RuntimeError | A feature (emboss, post, tab) extends past the base body footprint. Clip with `.intersect()` or reposition the feature. |

### Parametric Batch Generation

When creating a family of related parts (gauge sets, bracket sizes, etc.):

1. **Approve a single template first** — Get user sign-off on one representative part.
2. **Preview boundary instances** — Show the smallest, largest, and a mid-range size.
3. **Extract into shared module** — Put `make_part()` in its own file. Never duplicate across generate and plate scripts.
4. **Add validation** — `assert result.val().isValid()` after each part. Check file size after export.
5. **Report progress** — Print each part as it generates, with dimensions.
