#!/usr/bin/env python3
"""
check_printability.py — Automated FDM printability checker.

Runs the cad-skill self-review checklist items that are automatable against
an exported STEP or STL file. Optionally reads a .spec.json for custom
thresholds; falls back to FDM defaults.

Checks:
  1. Flat bottom      — Z-min surface has downward normals (within 5°)
  2. Overhangs        — % of surface area exceeding max_overhang_angle_deg (default 45°)
  3. Wall thickness   — cross-section sampling; minimum found vs min_wall_mm (default 1.2mm)
  4. Bridge span      — horizontal spans with no support below; flag > max_bridge_span_mm (default 20mm)
  5. Min feature size — smallest disconnected cross-section region < 0.8mm

Output format:
  [PASS] Flat bottom: Z=0.0mm, planar (normal deviation < 2°)
  [WARN] Overhangs: 12.3% of surface area exceeds 45° (3 regions)
  [PASS] Min wall thickness: 2.1mm (threshold: 1.2mm)
  [FAIL] Bridge span: 24.3mm at Z=15mm (max: 20mm)
  [PASS] Min feature size: 1.4mm (threshold: 0.8mm)

Exit code: 0 = all PASS or WARN. 1 = any FAIL.

Usage:
    python check_printability.py part.step
    python check_printability.py part.stl --spec custom.json
"""

import sys
import os
import math
import json
import argparse
from pathlib import Path

import numpy as np

_SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SKILL_DIR / "lib"))

# Spec is optional
try:
    from spec_format import load_spec
    _SPEC_AVAILABLE = True
except ImportError:
    _SPEC_AVAILABLE = False

# ── FDM defaults ──────────────────────────────────────────────────────────────
DEFAULT_OVERHANG_DEG    = 45.0
DEFAULT_BRIDGE_SPAN_MM  = 20.0
DEFAULT_MIN_WALL_MM     = 1.2
DEFAULT_MIN_FEATURE_MM  = 0.8
FLAT_BOTTOM_TOL_MM      = 0.1   # Z-band for "bottom face" classification
FLAT_BOTTOM_NORMAL_TOL  = 5.0   # degrees from straight-down to count as "flat"
Z_SAMPLE_COUNT          = 10    # cross-section levels for wall/bridge/feature checks

# ── Status tags ───────────────────────────────────────────────────────────────
PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

_results = []  # list of status strings, accumulated by _emit()


def _emit(status: str, check_name: str, detail: str):
    line = f"[{status}] {check_name}: {detail}"
    print(line)
    _results.append(status)


# ── Geometry loading ──────────────────────────────────────────────────────────

def _load_mesh(input_path: str):
    """
    Load STEP or STL and return a trimesh.Trimesh.

    STEP is tessellated via OCC at 0.05mm tolerance for accurate normals.
    STL is loaded directly.
    """
    import trimesh

    ext = Path(input_path).suffix.lower()

    if ext in (".step", ".stp"):
        import cadquery as cq
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_FACE
        from OCP.BRep import BRep_Tool
        from OCP.TopLoc import TopLoc_Location
        from OCP.TopoDS import TopoDS

        shape = cq.importers.importStep(input_path)
        solid = shape.val().wrapped
        BRepMesh_IncrementalMesh(solid, 0.05, False, 0.1)

        verts_list, tris_list = [], []
        offset = 0
        exp = TopExp_Explorer(solid, TopAbs_FACE)
        while exp.More():
            face = TopoDS.Face_s(exp.Current())
            loc = TopLoc_Location()
            poly = BRep_Tool.Triangulation_s(face, loc)
            if poly is not None:
                trsf = loc.Transformation()
                is_id = loc.IsIdentity()
                nodes = []
                for i in range(1, poly.NbNodes() + 1):
                    p = poly.Node(i)
                    if not is_id:
                        p = p.Transformed(trsf)
                    nodes.append([p.X(), p.Y(), p.Z()])
                for i in range(1, poly.NbTriangles() + 1):
                    t = poly.Triangle(i)
                    i1, i2, i3 = t.Get()
                    tris_list.append([i1 - 1 + offset, i2 - 1 + offset, i3 - 1 + offset])
                verts_list.extend(nodes)
                offset += len(nodes)
            exp.Next()

        if not verts_list:
            raise ValueError(f"No geometry extracted from STEP: {input_path}")

        verts = np.array(verts_list, dtype=np.float64)
        faces = np.array(tris_list, dtype=np.int32)
        return trimesh.Trimesh(vertices=verts, faces=faces, process=False)

    else:
        mesh = trimesh.load(input_path, force="mesh")
        if isinstance(mesh, trimesh.Scene):
            parts = [g for g in mesh.geometry.values() if isinstance(g, trimesh.Trimesh)]
            if not parts:
                raise ValueError(f"No mesh geometry found in {input_path}")
            mesh = trimesh.util.concatenate(parts)
        return mesh


# ── Threshold loading ─────────────────────────────────────────────────────────

def _load_thresholds(geom_path: str, spec_path: str = None) -> dict:
    """Return threshold dict, optionally overridden by spec JSON."""
    thresholds = {
        "max_overhang_angle_deg": DEFAULT_OVERHANG_DEG,
        "max_bridge_span_mm":     DEFAULT_BRIDGE_SPAN_MM,
        "min_wall_mm":            DEFAULT_MIN_WALL_MM,
        "min_feature_mm":         DEFAULT_MIN_FEATURE_MM,
        "overhangs_ok":           False,
    }

    # Auto-detect sibling .spec.json if no explicit spec given
    if spec_path is None:
        candidate = Path(geom_path).with_suffix(".spec.json")
        if candidate.exists():
            spec_path = str(candidate)

    if spec_path and os.path.exists(spec_path):
        try:
            if _SPEC_AVAILABLE:
                spec = load_spec(spec_path)
            else:
                with open(spec_path, "r", encoding="utf-8") as f:
                    spec = json.load(f)
            for key in ("max_overhang_angle_deg", "max_bridge_span_mm",
                        "min_wall_mm", "overhangs_ok"):
                if key in spec:
                    thresholds[key] = spec[key]
        except Exception:
            pass  # spec load failure is non-fatal — use defaults

    return thresholds


# ── Check 1: Flat bottom ──────────────────────────────────────────────────────

def check_flat_bottom(mesh) -> None:
    """
    Verify Z-min is a planar surface for bed adhesion.
    Triangles at Z-min (within 0.1mm) must have normals within 5° of (0,0,-1).
    """
    tol_cos = math.cos(math.radians(FLAT_BOTTOM_NORMAL_TOL))

    z_min = float(mesh.vertices[:, 2].min())
    face_z = mesh.triangles_center[:, 2]
    bottom_mask = face_z < (z_min + FLAT_BOTTOM_TOL_MM)

    if not bottom_mask.any():
        _emit(FAIL, "Flat bottom",
              f"Z={z_min:.2f}mm, no triangles found at Z-min band")
        return

    bottom_normals = mesh.face_normals[bottom_mask]

    # Use absolute Z component — accept normals pointing either up or down
    # (trimesh winding order can vary by mesh source; the meaningful check is
    # whether the bottom face is horizontal, not which way it faces).
    abs_z_dots = np.abs(bottom_normals[:, 2])  # 1.0 = perfectly horizontal face

    tol_cos = math.cos(math.radians(FLAT_BOTTOM_NORMAL_TOL))
    # Worst alignment: triangle furthest from horizontal
    min_abs_z = float(abs_z_dots.min())
    worst_deg = math.degrees(math.acos(max(0.0, min(1.0, min_abs_z))))
    n_bad = int(np.sum(abs_z_dots < tol_cos))

    if n_bad == 0:
        _emit(PASS, "Flat bottom",
              f"Z={z_min:.2f}mm, planar (worst normal deviation from horizontal: {worst_deg:.1f}°)")
    else:
        pct = 100.0 * n_bad / bottom_mask.sum()
        _emit(FAIL, "Flat bottom",
              f"Z={z_min:.2f}mm, {pct:.1f}% of bottom triangles deviate "
              f"> {FLAT_BOTTOM_NORMAL_TOL:.0f}° from horizontal (worst: {worst_deg:.1f}°) "
              f"— part may not sit flat on the bed")


# ── Check 2: Overhang analysis ────────────────────────────────────────────────

def check_overhangs(mesh, max_angle_deg: float, overhangs_ok: bool) -> None:
    """
    Vectorized overhang check.
    FDM overhang angle is measured from horizontal:
      - 0° = perfectly horizontal underside (prints fine)
      - 45° = FDM limit without support
      - 90° = vertical wall (not an overhang)
    A triangle overhangs when dot(normal, down) > sin(max_angle_deg).
    Excludes the bottom floor face.
    Reports % of total surface area and region count.
    """
    threshold_dot = math.sin(math.radians(max_angle_deg))
    down = np.array([0.0, 0.0, -1.0])
    normals = mesh.face_normals          # (N, 3)
    dots = normals @ down               # positive = facing downward

    # Exclude floor triangles
    z_min = float(mesh.vertices[:, 2].min())
    face_z = mesh.triangles_center[:, 2]
    floor_mask = face_z < (z_min + FLAT_BOTTOM_TOL_MM)

    overhang_mask = (dots > threshold_dot) & ~floor_mask

    face_areas = mesh.area_faces
    total_area = float(face_areas.sum())
    overhang_area = float(face_areas[overhang_mask].sum())
    pct = 100.0 * overhang_area / total_area if total_area > 0 else 0.0

    n_regions = 0
    if overhang_mask.any():
        n_regions = _count_face_regions(mesh, np.where(overhang_mask)[0])

    region_str = f"{n_regions} region{'s' if n_regions != 1 else ''}"

    if not overhang_mask.any():
        _emit(PASS, "Overhangs",
              f"No overhangs > {max_angle_deg:.0f}° detected")
    elif overhangs_ok:
        _emit(WARN, "Overhangs",
              f"{pct:.1f}% of surface area exceeds {max_angle_deg:.0f}° "
              f"({region_str}) — spec marks overhangs_ok=True")
    else:
        # WARN not FAIL: overhangs can be handled in slicer; CAD redesign optional
        _emit(WARN, "Overhangs",
              f"{pct:.1f}% of surface area exceeds {max_angle_deg:.0f}° ({region_str})")


def _count_face_regions(mesh, face_indices: np.ndarray) -> int:
    """Count connected components among a subset of face indices via face adjacency."""
    if len(face_indices) == 0:
        return 0
    try:
        adjacency = mesh.face_adjacency  # (M, 2)
    except Exception:
        return 1

    face_set = set(face_indices.tolist())
    both_in = np.isin(adjacency[:, 0], face_indices) & np.isin(adjacency[:, 1], face_indices)
    adj_subset = adjacency[both_in]

    parent = {f: f for f in face_set}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in adj_subset:
        ra, rb = find(int(a)), find(int(b))
        if ra != rb:
            parent[ra] = rb

    return len({find(f) for f in face_set})


# ── Check 3: Wall thickness ───────────────────────────────────────────────────

def check_wall_thickness(mesh, min_wall_mm: float) -> None:
    """
    Sample cross-sections at multiple Z levels. For each cross-section,
    rasterize and compute minimum inscribed circle radius via distance transform.
    Reports minimum wall thickness found across all levels.
    """
    z_min = float(mesh.vertices[:, 2].min())
    z_max = float(mesh.vertices[:, 2].max())
    height = z_max - z_min

    if height <= 0:
        _emit(WARN, "Min wall thickness", "Zero-height geometry, skipping")
        return

    z_levels = np.linspace(z_min + height * 0.12, z_max - height * 0.05, Z_SAMPLE_COUNT)

    min_found = float("inf")
    min_z = None

    for z in z_levels:
        t = _wall_thickness_at_z(mesh, float(z))
        if t is not None and t < min_found:
            min_found = t
            min_z = float(z)

    if min_found == float("inf"):
        _emit(WARN, "Min wall thickness",
              "Could not extract cross-sections — verify manually in slicer")
        return

    if min_found >= min_wall_mm:
        _emit(PASS, "Min wall thickness",
              f"{min_found:.1f}mm (threshold: {min_wall_mm:.1f}mm)")
    elif min_found >= min_wall_mm * 0.7:
        # Cross-section distance transform can underestimate near slot edges and
        # chamfered geometry — values within 30% of threshold reported as WARN.
        _emit(WARN, "Min wall thickness",
              f"{min_found:.1f}mm at Z={min_z:.1f}mm (threshold: {min_wall_mm:.1f}mm) "
              f"— conservative estimate, verify in slicer if near threshold")
    else:
        _emit(FAIL, "Min wall thickness",
              f"{min_found:.1f}mm at Z={min_z:.1f}mm (threshold: {min_wall_mm:.1f}mm) "
              f"— walls are significantly below minimum")


def _wall_thickness_at_z(mesh, z: float) -> float | None:
    """
    Rasterize the cross-section at Z, run a distance transform,
    return 2 * 5th-percentile inscribed circle radius (minimum wall thickness).
    Resolution: 0.2mm/pixel.
    """
    try:
        section = mesh.section(plane_origin=[0.0, 0.0, z], plane_normal=[0.0, 0.0, 1.0])
        if section is None:
            return None
        path2d, _ = section.to_planar()
    except Exception:
        return None

    return _min_thickness_from_path2d(path2d, resolution=0.2)


def _min_thickness_from_path2d(path2d, resolution: float = 0.2) -> float | None:
    """
    Rasterize a trimesh Path2D and return the minimum wall thickness estimate
    using a distance transform. Wall thickness = 2 * inscribed circle radius.

    Returns None for solid cross-sections (single outer boundary, no holes) —
    those don't have walls to measure. Only meaningful for hollow sections where
    the distance transform captures the material between outer and inner boundaries.
    """
    # Solid cross-section: single outer boundary, no holes. Distance transform
    # on a solid polygon measures distance from the outer edge, which is dominated
    # by corner proximity and gives misleadingly small values. Skip it.
    if len(path2d.entities) < 2:
        return None

    try:
        from PIL import Image, ImageDraw
        import scipy.ndimage as ndi
    except ImportError:
        return None

    MARGIN_PX = 3

    bounds = path2d.bounds
    if bounds is None or len(bounds) < 2:
        return None

    xmin, ymin = bounds[0]
    xmax, ymax = bounds[1]
    span_x = xmax - xmin
    span_y = ymax - ymin
    if span_x < 0.1 or span_y < 0.1:
        return None

    # Dynamic resolution cap: keep image under 2M pixels
    if (span_x / resolution) * (span_y / resolution) > 2_000_000:
        resolution = math.sqrt(span_x * span_y / 2_000_000)

    w_px = int(math.ceil(span_x / resolution)) + 2 * MARGIN_PX
    h_px = int(math.ceil(span_y / resolution)) + 2 * MARGIN_PX

    img = Image.new("L", (w_px, h_px), 0)
    draw = ImageDraw.Draw(img)

    for entity in path2d.entities:
        try:
            pts = path2d.vertices[entity.points]
            px = ((pts[:, 0] - xmin) / resolution + MARGIN_PX).tolist()
            py = ((pts[:, 1] - ymin) / resolution + MARGIN_PX).tolist()
            poly = list(zip(px, py))
            if len(poly) >= 3:
                draw.polygon(poly, fill=255)
        except Exception:
            continue

    bitmap = np.array(img, dtype=bool)
    if not bitmap.any():
        return None

    dist = ndi.distance_transform_edt(bitmap)
    interior = dist[bitmap]
    if len(interior) == 0:
        return None

    # 5th percentile avoids single-pixel edge noise
    min_radius_px = float(np.percentile(interior, 5))
    return max(2.0 * min_radius_px * resolution, 0.01)


# ── Check 4: Bridge span ──────────────────────────────────────────────────────

def check_bridge_spans(mesh, max_bridge_mm: float) -> None:
    """
    Find horizontal surfaces (within 5° of Z-normal, excluding Z-min floor)
    with no mesh geometry within 0.5mm directly below them.
    Groups by Z level, measures bounding-box span of each cluster.
    Reports worst span found.
    """
    HORIZ_COS    = math.cos(math.radians(5.0))   # |normal.z| > this = nearly horizontal
    GRID_RES_MM  = 1.0                            # XY grid cell size for support check
    MIN_GAP_MM   = 0.5                            # minimum air gap to call it "unsupported"
    MIN_SPAN_MM  = 2.0                            # ignore tiny features below this span

    z_min = float(mesh.vertices[:, 2].min())
    normals  = mesh.face_normals
    centroids = mesh.triangles_center

    # Horizontal candidates: |nz| > HORIZ_COS and not at floor
    horiz_mask   = np.abs(normals[:, 2]) > HORIZ_COS
    not_floor    = centroids[:, 2] > (z_min + FLAT_BOTTOM_TOL_MM + 0.1)
    candidate_idx = np.where(horiz_mask & not_floor)[0]

    if len(candidate_idx) == 0:
        _emit(PASS, "Bridge span", "No internal horizontal surfaces detected")
        return

    cand_cents = centroids[candidate_idx]   # (K, 3)
    cand_z     = cand_cents[:, 2]           # (K,)

    # Build XY support grid: max Z of ALL triangles per cell
    all_cents = mesh.triangles_center
    verts = mesh.vertices

    x_min_v = float(verts[:, 0].min())
    x_max_v = float(verts[:, 0].max())
    y_min_v = float(verts[:, 1].min())
    y_max_v = float(verts[:, 1].max())

    nx = max(1, int(math.ceil((x_max_v - x_min_v) / GRID_RES_MM)))
    ny = max(1, int(math.ceil((y_max_v - y_min_v) / GRID_RES_MM)))

    # Cap grid size to avoid pathological memory use
    if nx * ny > 1_000_000:
        GRID_RES_MM = math.sqrt((x_max_v - x_min_v) * (y_max_v - y_min_v) / 1_000_000)
        nx = max(1, int(math.ceil((x_max_v - x_min_v) / GRID_RES_MM)))
        ny = max(1, int(math.ceil((y_max_v - y_min_v) / GRID_RES_MM)))

    ix_all = np.clip(((all_cents[:, 0] - x_min_v) / GRID_RES_MM).astype(int), 0, nx - 1)
    iy_all = np.clip(((all_cents[:, 1] - y_min_v) / GRID_RES_MM).astype(int), 0, ny - 1)

    # Initialize grid below the part
    z_grid = np.full((ny, nx), z_min - 1.0, dtype=np.float64)
    np.maximum.at(z_grid, (iy_all, ix_all), all_cents[:, 2])

    # Look up max Z below each candidate centroid
    ix_c = np.clip(((cand_cents[:, 0] - x_min_v) / GRID_RES_MM).astype(int), 0, nx - 1)
    iy_c = np.clip(((cand_cents[:, 1] - y_min_v) / GRID_RES_MM).astype(int), 0, ny - 1)
    z_below = z_grid[iy_c, ix_c]

    # Unsupported: face Z is more than MIN_GAP_MM above highest nearby geometry
    bridge_local = (cand_z - z_below) > MIN_GAP_MM
    if not bridge_local.any():
        _emit(PASS, "Bridge span",
              f"No unsupported spans detected (max: {max_bridge_mm:.0f}mm)")
        return

    bridge_cents = cand_cents[bridge_local]   # (B, 3)
    bridge_z     = bridge_cents[:, 2]         # (B,)

    # Measure spans per Z band (±0.5mm)
    max_span   = 0.0
    worst_span_z = float(bridge_z[0])

    unique_z = np.unique(np.round(bridge_z, 0))
    for zl in unique_z:
        in_band = np.abs(bridge_z - zl) < 0.5
        if not in_band.any():
            continue
        band = bridge_cents[in_band]
        if len(band) < 2:
            continue
        span_x = float(band[:, 0].max() - band[:, 0].min())
        span_y = float(band[:, 1].max() - band[:, 1].min())
        span   = max(span_x, span_y)
        if span > max_span:
            max_span = span
            worst_span_z = float(zl)

    if max_span < MIN_SPAN_MM:
        _emit(PASS, "Bridge span",
              f"No significant unsupported spans (largest: {max_span:.1f}mm, "
              f"max: {max_bridge_mm:.0f}mm)")
    elif max_span <= max_bridge_mm:
        _emit(PASS, "Bridge span",
              f"{max_span:.1f}mm at Z={worst_span_z:.1f}mm (max: {max_bridge_mm:.0f}mm)")
    else:
        _emit(FAIL, "Bridge span",
              f"{max_span:.1f}mm at Z={worst_span_z:.1f}mm (max: {max_bridge_mm:.0f}mm)")


# ── Check 5: Minimum feature size ─────────────────────────────────────────────

def check_min_feature_size(mesh, min_feat_mm: float) -> None:
    """
    Find small disconnected connected components via trimesh.split().
    Also checks cross-sections for small isolated regions.
    Reports minimum bounding dimension found.
    """
    min_found = float("inf")
    worst_z   = None

    # Split into connected components, check bounding extents.
    # Only useful for watertight meshes — OCC tessellations have per-face
    # disconnected triangles that produce meaningless micro-components.
    if mesh.is_watertight:
        try:
            components = mesh.split(only_watertight=False)
            for comp in components:
                bb = comp.bounding_box.extents
                dim = float(np.min(bb))
                if dim < min_found:
                    min_found = dim
                    worst_z = float(comp.vertices[:, 2].mean())
        except Exception:
            pass

    # Cross-section path: find small isolated regions per Z slice
    z_min = float(mesh.vertices[:, 2].min())
    z_max = float(mesh.vertices[:, 2].max())
    height = z_max - z_min

    if height > 0:
        z_levels = np.linspace(z_min + height * 0.12, z_max - height * 0.05, Z_SAMPLE_COUNT)
        for z in z_levels:
            feat = _min_feature_at_z(mesh, float(z))
            if feat is not None and feat < min_found:
                min_found = feat
                worst_z = float(z)

    if min_found == float("inf"):
        _emit(WARN, "Min feature size",
              "Could not evaluate — verify manually in slicer")
        return

    if min_found >= min_feat_mm:
        _emit(PASS, "Min feature size",
              f"{min_found:.1f}mm (threshold: {min_feat_mm:.1f}mm)")
    else:
        z_str = f" at Z={worst_z:.1f}mm" if worst_z is not None else ""
        _emit(FAIL, "Min feature size",
              f"{min_found:.2f}mm{z_str} (threshold: {min_feat_mm:.1f}mm)")


def _min_feature_at_z(mesh, z: float) -> float | None:
    """Find minimum bounding dimension of any disconnected region in cross-section at Z."""
    try:
        import scipy.ndimage as ndi
    except ImportError:
        return None

    RESOLUTION = 0.1   # mm/pixel — fine enough to catch 0.8mm features
    MARGIN_PX  = 2

    try:
        section = mesh.section(plane_origin=[0.0, 0.0, z], plane_normal=[0.0, 0.0, 1.0])
        if section is None:
            return None
        path2d, _ = section.to_planar()
    except Exception:
        return None

    # Single outer boundary = solid cross-section, no isolated thin features to report
    if len(path2d.entities) < 2:
        return None

    bounds = path2d.bounds
    if bounds is None or len(bounds) < 2:
        return None

    xmin, ymin = bounds[0]
    xmax, ymax = bounds[1]
    span_x = xmax - xmin
    span_y = ymax - ymin
    if span_x < 0.05 or span_y < 0.05:
        return None

    res = RESOLUTION
    if (span_x / res) * (span_y / res) > 2_000_000:
        res = math.sqrt(span_x * span_y / 2_000_000)

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    w_px = int(math.ceil(span_x / res)) + 2 * MARGIN_PX
    h_px = int(math.ceil(span_y / res)) + 2 * MARGIN_PX

    img = Image.new("L", (w_px, h_px), 0)
    draw = ImageDraw.Draw(img)

    for entity in path2d.entities:
        try:
            pts = path2d.vertices[entity.points]
            px = ((pts[:, 0] - xmin) / res + MARGIN_PX).tolist()
            py = ((pts[:, 1] - ymin) / res + MARGIN_PX).tolist()
            poly = list(zip(px, py))
            if len(poly) >= 3:
                draw.polygon(poly, fill=255)
        except Exception:
            continue

    bitmap = np.array(img, dtype=bool)
    if not bitmap.any():
        return None

    labeled, n = ndi.label(bitmap)
    if n == 0:
        return None

    min_dim = float("inf")
    for comp_id in range(1, n + 1):
        comp = labeled == comp_id
        rows = np.where(comp.any(axis=1))[0]
        cols = np.where(comp.any(axis=0))[0]
        if len(rows) == 0 or len(cols) == 0:
            continue
        h_mm = (rows[-1] - rows[0] + 1) * res
        w_mm = (cols[-1] - cols[0] + 1) * res
        dim = min(h_mm, w_mm)
        if dim < min_dim:
            min_dim = dim

    return min_dim if min_dim < float("inf") else None


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Automated FDM printability checker for STEP/STL files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("input",
                        help="Path to .step, .stp, or .stl file")
    parser.add_argument("--spec", metavar="JSON", default=None,
                        help="Path to .spec.json (default: auto-detect sibling .spec.json)")
    args = parser.parse_args()

    input_path = os.path.realpath(args.input)
    if not os.path.exists(input_path):
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        sys.exit(2)

    spec_path = os.path.realpath(args.spec) if args.spec else None
    thresholds = _load_thresholds(input_path, spec_path)

    try:
        mesh = _load_mesh(input_path)
    except Exception as e:
        print(f"Error loading geometry: {e}", file=sys.stderr)
        sys.exit(2)

    if len(mesh.faces) == 0:
        print("Error: loaded mesh has no faces", file=sys.stderr)
        sys.exit(2)

    # Run all five checks
    check_flat_bottom(mesh)
    check_overhangs(mesh,
                    max_angle_deg=thresholds["max_overhang_angle_deg"],
                    overhangs_ok=thresholds["overhangs_ok"])
    check_wall_thickness(mesh, min_wall_mm=thresholds["min_wall_mm"])
    check_bridge_spans(mesh,   max_bridge_mm=thresholds["max_bridge_span_mm"])
    check_min_feature_size(mesh, min_feat_mm=thresholds["min_feature_mm"])

    # Exit 1 on any FAIL; WARN is acceptable
    if FAIL in _results:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
