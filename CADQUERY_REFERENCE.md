# CadQuery Quick Reference for Claude Code

## Core Pattern

CadQuery uses a fluent API. Chain operations on Workplane objects:

```python
import cadquery as cq

result = (
    cq.Workplane("XY")       # Start on XY plane
    .box(50, 30, 10)          # Create centered box
    .faces(">Z")              # Select top face
    .workplane()              # Create workplane on selection
    .hole(5)                  # Cut centered hole
)
```

## Coordinate System
- XY = top/bottom (Z is up)
- XZ = front/back (Y is depth)
- YZ = left/right (X is width)
- All dimensions in **millimeters**

## Basic Shapes

```python
# Box (centered at origin by default)
.box(width, depth, height)

# Cylinder
.cylinder(height, radius)

# Sphere
.sphere(radius)

# Wedge
.wedge(xLen, yLen, zLen, xMin, zMin, xMax, zMax)
```

## 2D Sketch → 3D

```python
# Rectangle sketch + extrude
result = (
    cq.Workplane("XY")
    .rect(50, 30)
    .extrude(10)
)

# Circle sketch + extrude
result = (
    cq.Workplane("XY")
    .circle(25)
    .extrude(10)
)

# Polygon
result = (
    cq.Workplane("XY")
    .polygon(6, 20)      # hexagon, circumradius 20
    .extrude(10)
)

# Rounded rectangle
result = (
    cq.Workplane("XY")
    .rect(50, 30)
    .extrude(10)
    .edges("|Z")          # vertical edges only
    .fillet(5)            # round the corners
)
```

## Face Selection (Selectors)

```python
.faces(">Z")    # top face (highest Z)
.faces("<Z")    # bottom face (lowest Z)
.faces(">X")    # right face
.faces("<X")    # left face
.faces(">Y")    # back face
.faces("<Y")    # front face
```

## Edge Selection

```python
.edges("|Z")    # edges parallel to Z axis (vertical)
.edges("|X")    # edges parallel to X axis
.edges("|Y")    # edges parallel to Y axis
.edges(">Z")    # top edges
.edges("<Z")    # bottom edges
```

## Cutting and Adding

```python
# Hole (centered on current workplane)
.hole(diameter)
.hole(diameter, depth)

# Through-hole at offset position
.faces(">Z").workplane()
.center(10, 5)           # offset from face center
.hole(4)

# Cut arbitrary shape
.cut(other_solid)

# Boolean union
.union(other_solid)

# Counterbore hole
.cboreHole(hole_d, cbore_d, cbore_depth)

# Countersink hole
.cskHole(hole_d, csk_d, csk_angle)
```

## Shell (Hollowing)

```python
# Shell from top (remove top face, hollow inside)
result = (
    cq.Workplane("XY")
    .box(50, 30, 20)
    .faces(">Z")
    .shell(-2)            # negative = inward, 2mm wall
)

# Shell keeping top and bottom
result = (
    cq.Workplane("XY")
    .box(50, 30, 20)
    .faces(">Z or <Z")
    .shell(-2)
)
```

## Fillets and Chamfers

```python
# Fillet all edges
.edges().fillet(2)

# Fillet specific edges
.edges("|Z").fillet(3)           # vertical edges only
.edges(">Z").fillet(1)           # top edges only

# Chamfer (better for bottom edges — no support needed)
.edges("<Z").chamfer(0.5)        # bottom edges
.edges(">Z").chamfer(1.0, 0.5)  # asymmetric chamfer
```

## Positioning and Arrays

```python
# Move workplane center
.center(x_offset, y_offset)

# Array of features
.faces(">Z").workplane()
.rect(30, 20, forConstruction=True)   # construction rectangle
.vertices()                            # select its 4 corners
.hole(3)                               # hole at each corner

# Linear array
.faces(">Z").workplane()
.rarray(10, 10, 3, 3)    # xSpacing, ySpacing, xCount, yCount
.hole(2)                  # 3x3 grid of holes

# Push points (arbitrary positions)
.faces(">Z").workplane()
.pushPoints([(10, 5), (-10, 5), (0, -10)])
.hole(3)
```

## Loft, Sweep, Revolve

```python
# Loft between two profiles
result = (
    cq.Workplane("XY")
    .rect(40, 40)
    .workplane(offset=30)
    .circle(15)
    .loft()
)

# Revolve a profile
result = (
    cq.Workplane("XZ")
    .lineTo(10, 0)
    .lineTo(10, 20)
    .lineTo(5, 25)
    .close()
    .revolve(360)
)
```

## Assemblies (Multi-part)

```python
assy = cq.Assembly()
assy.add(base, name="base", color=cq.Color("gray"))
assy.add(lid, name="lid", loc=cq.Location((0, 0, height)), color=cq.Color("blue"))
```

## Export

```python
# STL (for slicing/printing)
cq.exporters.export(result, "part.stl")
cq.exporters.export(result, "part.stl", tolerance=0.01)  # higher quality mesh

# STEP (lossless CAD format)
cq.exporters.export(result, "part.step")
```

## Common Gotchas

1. **Shell before complex fillets** — shell can fail if there are already small fillets
2. **Fillet radius must be smaller than the shortest edge** it touches
3. **Boolean cuts must fully intersect** — add 0.01mm extra depth to ensure clean cuts
4. **`.center()` is cumulative** — each call offsets from the CURRENT center, not origin
5. **Use `forConstruction=True`** for reference geometry that shouldn't become solid
6. **Workplane offset** — `.workplane(offset=10)` creates a new workplane 10mm above current
7. **Workplane origin stacking** — `.center(x, y)` permanently mutates the plane origin. Subsequent `.faces().workplane()` inherits the shifted origin via `ProjectedOrigin` (the default `centerOption`). This causes features placed later to be offset. See Workplane Context Stacking section below.
8. **`combine='cut'` text deboss fails silently** — CadQuery's `.text(..., combine='cut')` often produces no change. Use a fresh workplane + explicit `.cut()` instead. See Text Deboss section below.
9. **Additive text overflows body** — `.text(..., combine='a')` can create geometry outside the body outline. Clip with `.intersect()` or use deboss instead.
10. **Revolved profiles on non-XY workplanes** — `.transformed(offset=(a,b,c))` on XZ or YZ workplanes maps offset to the LOCAL frame, not world coordinates. On an XZ workplane, local-Y is world-Z and the normal is world-Y. A revolve tool placed with `offset=(cx, top_z, cy)` on XZ ends up at world (cx, cy, top_z) — which may be wrong if you assumed world mapping. For revolved chamfer/fillet tools, prefer building on XY and translating the result, or verify with `verify_boolean` that the cut actually changed the geometry.

---

## Workplane Context Stacking (Origin Drift)

`.center(x, y)` calls `plane.setOrigin2d()` which **permanently mutates** the workplane origin. When you later call `.faces(">Z").workplane()`, the default `centerOption="ProjectedOrigin"` projects the *current* (shifted) origin onto the new face — NOT the face center.

**Example of the bug:**
```python
result = (
    cq.Workplane("XY").box(40, 40, 10)
    .faces(">Z").workplane()
    .center(0, 10).hole(5)           # origin shifts to (0, 10)
    .faces(">Z").workplane()          # origin is STILL (0, 10)!
    .text("HELLO", 8, -0.5)          # text placed 10mm off-center
)
```

**Fix 1 (recommended): Explicit origin reset**
```python
.faces(">Z").workplane(origin=(0, 0, height))
```

**Fix 2: Use CenterOfBoundBox**
```python
.faces(">Z").workplane(centerOption="CenterOfBoundBox")
```

**Fix 3: Fresh workplane (safest for text)**
```python
text = cq.Workplane("XY").transformed(offset=(0, y, z), rotate=(0, 0, 90)).text(...)
body = body.cut(text)  # or .union(text)
```

**Prevention:** Use `.moveTo()` instead of `.center()` when you only need to reposition a single feature. `.moveTo()` does NOT mutate the plane origin.

---

## Text Deboss: combine='cut' Silent Failure

`combine='cut'` in `.text()` often silently fails, producing unchanged geometry. This appears related to workplane context contamination and OCCT boolean sensitivity on coplanar surfaces.

**Canonical deboss pattern — always works:**
```python
# Create text on a FRESH workplane at absolute coordinates
text_solid = (
    cq.Workplane("XY")
    .transformed(offset=(0, text_y, top_z), rotate=(0, 0, 90))
    .text(label, font_size, -depth, font="Arial")
)
# Explicitly cut from body
body = body.cut(text_solid)
```

**Detection:** Compare face count or file size before/after. If unchanged, the cut failed silently.

---

## Embossed Text Overflow and Clipping

`combine='a'` (additive text) creates geometry outside the body boundary. Characters that extend past the body outline become floating protrusions.

**Clip pattern:**
```python
# After adding embossed text
clip = body_profile(cq.Workplane("XY")).extrude(thickness + emboss_height)
result = result.intersect(clip)
```

---

## Measuring Text Bounding Boxes

CadQuery has no API for font metrics. Measure empirically:

```python
def measure_text_bbox(text, font_size=10.0, font="Arial"):
    solid = cq.Workplane("XY").text(text, font_size, 1.0, combine=False)
    bb = solid.val().BoundingBox()
    return bb.xlen / font_size, bb.ylen / font_size  # width_ratio, height_ratio
```

Cache ratios for known labels. Multiply ratio by desired font_size to get actual dimensions.

---

## The Fresh Workplane Pattern

When placing features at known global coordinates, bypass `.faces().workplane()` entirely:

```python
feature = (
    cq.Workplane("XY")
    .transformed(offset=(x, y, z), rotate=(rx, ry, rz))
    .circle(r).extrude(h)
)
body = body.union(feature)  # or .cut(feature)
```

**Use when:** placing text, adding features after hole operations, any time workplane origin drift is a concern.

**Don't use when:** you need the feature to follow a face's orientation (e.g., features on angled faces).

---

## Non-Overlapping Part Assembly

For plates/arrays where parts don't touch, skip `.union()` (O(n²) OCCT booleans) and use:

```python
from cadquery import Compound
parts = [gauge1, gauge2, ...]  # list of CQ Workplane objects
compound = Compound.makeCompound([p.val() for p in parts])
cq.exporters.export(compound, "plate.stl")
```

This is 5-10x faster for 20+ parts.

**Note:** `makeCompound()` works for CQ Workplane `.val()` objects. For raw OCC solids (e.g., after `.moved()` or Location transforms), use `BRep_Builder` + `TopoDS_Compound` instead — see the Plate Packing section in SKILL.md for the pattern.

---

## Drawing Arcs by Sagitta

`.sagittaArc(endPoint, sag)` draws an arc from current point to endPoint:
- **Positive sag**: arc bows LEFT of travel direction
- Going left→right: positive sag = arc bows upward (convex)
- Sagitta formula: `sag = R - sqrt(R² - (chord/2)²)`
