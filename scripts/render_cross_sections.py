#!/usr/bin/env python3
"""
render_cross_sections.py — Dimensioned raster cross-section renderer.

Slices a STEP file using mesh-based intersection (no OCC booleans),
rasterizes the cross-section polygons, measures from the bitmap, and
renders annotated technical drawings with dimension lines.

Reads the sibling .spec.json to determine where to cut and what to measure.

Usage:
    python render_cross_sections.py part.step
    python render_cross_sections.py part.step --spec custom.json
    python render_cross_sections.py part.step --output-dir ./sections/
"""

import argparse
import sys
import os
from pathlib import Path

import numpy as np

# Allow imports from the skill's lib/ directory
_SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SKILL_DIR / "lib"))

from spec_format import load_spec

# ── Visual theme (matches render_preview.py) ─────────────────────────────────
BG_COLOR = '#2B2B2B'
PART_FILL = (0.24, 0.55, 0.75)
PART_EDGE = (0.35, 0.70, 0.90)
DIM_LINE_COLOR = '#FFFFFF'
DIM_TEXT_COLOR = '#D0D0D0'
SCALE_BAR_COLOR = '#AAAAAA'
TITLE_COLOR = '#D0D0D0'
DPI = 200
MM_PER_PIXEL = 0.05


# ── Mesh loading ─────────────────────────────────────────────────────────────

def _load_mesh(step_path):
    """Load a STEP file and return a trimesh.Trimesh."""
    import trimesh
    import cadquery as cq
    import tempfile

    # Export STEP to a temp STL via CadQuery, then load with trimesh
    shape = cq.importers.importStep(step_path)
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        cq.exporters.export(shape, tmp_path, exportType="STL",
                            tolerance=0.01, angularTolerance=0.1)
        mesh = trimesh.load(tmp_path)
        if isinstance(mesh, trimesh.Scene):
            mesh = trimesh.util.concatenate(
                [g for g in mesh.geometry.values() if isinstance(g, trimesh.Trimesh)]
            )
        return mesh
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ── Slicing ──────────────────────────────────────────────────────────────────

def _slice_mesh(mesh, plane_origin, plane_normal):
    """Slice a mesh and return a list of 2D polygon paths.

    Returns (paths_2d, axis_labels, project_fn) where:
    - paths_2d: list of Nx2 arrays in the cut plane's local 2D coords
    - axis_labels: (horizontal_label, vertical_label) e.g. ("X", "Z")
    - project_fn: function mapping 3D points to 2D in the cut plane
    """
    normal = np.array(plane_normal, dtype=float)
    normal = normal / np.linalg.norm(normal)
    origin = np.array(plane_origin, dtype=float)

    lines = mesh.section(plane_origin=origin, plane_normal=normal)
    if lines is None:
        return [], ("?", "?"), None

    # Build local 2D coordinate frame on the cut plane
    # Choose u, v axes based on the dominant normal direction
    abs_n = np.abs(normal)
    if abs_n[2] > 0.9:
        # XY plane (cutting along Z)
        u_axis = np.array([1.0, 0.0, 0.0])
        v_axis = np.array([0.0, 1.0, 0.0])
        labels = ("X", "Y")
    elif abs_n[1] > 0.9:
        # XZ plane (cutting along Y)
        u_axis = np.array([1.0, 0.0, 0.0])
        v_axis = np.array([0.0, 0.0, 1.0])
        labels = ("X", "Z")
    elif abs_n[0] > 0.9:
        # YZ plane (cutting along X)
        u_axis = np.array([0.0, 1.0, 0.0])
        v_axis = np.array([0.0, 0.0, 1.0])
        labels = ("Y", "Z")
    else:
        # Arbitrary plane — pick u perpendicular to normal
        arbitrary = np.array([1.0, 0.0, 0.0])
        if abs(np.dot(normal, arbitrary)) > 0.9:
            arbitrary = np.array([0.0, 1.0, 0.0])
        u_axis = np.cross(normal, arbitrary)
        u_axis = u_axis / np.linalg.norm(u_axis)
        v_axis = np.cross(normal, u_axis)
        v_axis = v_axis / np.linalg.norm(v_axis)
        labels = ("U", "V")

    def project(pts_3d):
        rel = pts_3d - origin
        u = np.dot(rel, u_axis)
        v = np.dot(rel, v_axis)
        return np.column_stack([u, v])

    # Extract 2D paths from the section
    paths_2d = []
    try:
        # lines is a Path3D; get its discrete entities
        path_2d, _transform = lines.to_2D()
        for polygon in path_2d.polygons_full:
            coords = np.array(polygon.exterior.coords)
            paths_2d.append(coords)
            for interior in polygon.interiors:
                paths_2d.append(np.array(interior.coords))
    except Exception as e:
        print(f"[sections] Warning: to_2D() failed ({e}), falling back to vertex projection")
        for entity in lines.entities:
            pts_3d = lines.vertices[entity.points]
            pts_2d = project(pts_3d)
            paths_2d.append(pts_2d)

    if not paths_2d and lines.vertices is not None and len(lines.vertices) > 0:
        pts_2d = project(lines.vertices)
        paths_2d.append(pts_2d)

    return paths_2d, labels, project


def _slice_mesh_polygons(mesh, plane_origin, plane_normal):
    """Slice mesh and return shapely polygons + metadata for rasterization.

    Returns (polygons, axis_labels, bbox_mm, transform_2d) where:
    - polygons: list of shapely Polygons in the cut plane
    - axis_labels: (h_label, v_label)
    - bbox_mm: (xmin, xmax, ymin, ymax) in mm
    - transform_2d: the 3x3 transform from to_planar()
    """
    normal = np.array(plane_normal, dtype=float)
    normal = normal / np.linalg.norm(normal)
    origin = np.array(plane_origin, dtype=float)

    lines = mesh.section(plane_origin=origin, plane_normal=normal)
    if lines is None:
        return [], ("?", "?"), None, None

    abs_n = np.abs(normal)
    if abs_n[2] > 0.9:
        labels = ("X", "Y")
    elif abs_n[1] > 0.9:
        labels = ("X", "Z")
    elif abs_n[0] > 0.9:
        labels = ("Y", "Z")
    else:
        labels = ("U", "V")

    try:
        path_2d, transform = lines.to_2D()
        polygons = list(path_2d.polygons_full)
        if not polygons:
            return [], labels, None, transform

        # Compute bounding box of all polygons
        all_bounds = np.array([p.bounds for p in polygons])
        bbox = (
            all_bounds[:, 0].min(),
            all_bounds[:, 2].max(),
            all_bounds[:, 1].min(),
            all_bounds[:, 3].max(),
        )
        return polygons, labels, bbox, transform
    except Exception as e:
        print(f"[sections] Warning: to_2D() polygon extraction failed: {e}")
        return [], labels, None, None


# ── Rasterization and measurement ────────────────────────────────────────────

def _rasterize_polygons(polygons, bbox, mm_per_pixel=MM_PER_PIXEL):
    """Rasterize shapely polygons to a boolean bitmap.

    Returns (bitmap, mm_per_pixel, x_offset, y_offset) where bitmap[row, col]
    is True where material exists.
    """
    from PIL import Image, ImageDraw
    import shapely.geometry

    xmin, xmax, ymin, ymax = bbox
    margin = 2.0  # mm margin around part
    xmin -= margin
    xmax += margin
    ymin -= margin
    ymax += margin

    w_px = int(np.ceil((xmax - xmin) / mm_per_pixel))
    h_px = int(np.ceil((ymax - ymin) / mm_per_pixel))

    # Cap at 8000x8000 to avoid memory issues
    if w_px > 8000 or h_px > 8000:
        scale = 8000 / max(w_px, h_px)
        mm_per_pixel = mm_per_pixel / scale
        w_px = int(np.ceil((xmax - xmin) / mm_per_pixel))
        h_px = int(np.ceil((ymax - ymin) / mm_per_pixel))

    img = Image.new('L', (w_px, h_px), 0)
    draw = ImageDraw.Draw(img)

    for poly in polygons:
        # Draw exterior as filled
        ext_coords = list(poly.exterior.coords)
        px_coords = [
            ((x - xmin) / mm_per_pixel, (ymax - y) / mm_per_pixel)
            for x, y in ext_coords
        ]
        draw.polygon(px_coords, fill=255)

        # Cut out interiors (holes)
        for interior in poly.interiors:
            int_coords = list(interior.coords)
            px_coords = [
                ((x - xmin) / mm_per_pixel, (ymax - y) / mm_per_pixel)
                for x, y in int_coords
            ]
            draw.polygon(px_coords, fill=0)

    bitmap = np.array(img) > 127
    return bitmap, mm_per_pixel, xmin, ymax  # ymax because Y is flipped in image


def _measure_overall(bitmap, mm_per_pixel):
    """Measure bounding box of filled region. Returns (width_mm, height_mm, col_min, col_max, row_min, row_max)."""
    rows = np.any(bitmap, axis=1)
    cols = np.any(bitmap, axis=0)
    if not np.any(rows) or not np.any(cols):
        return 0, 0, 0, 0, 0, 0
    row_min, row_max = np.where(rows)[0][[0, -1]]
    col_min, col_max = np.where(cols)[0][[0, -1]]
    width_mm = (col_max - col_min) * mm_per_pixel
    height_mm = (row_max - row_min) * mm_per_pixel
    return width_mm, height_mm, col_min, col_max, row_min, row_max


def _measure_gaps(bitmap, mm_per_pixel, axis='horizontal'):
    """Find interior gaps (voids) in the bitmap along the given axis.

    Returns list of (center_px, width_mm) for each gap found.
    axis='horizontal' scans columns at mid-row.
    axis='vertical' scans rows at mid-col.
    """
    gaps = []
    if axis == 'horizontal':
        rows = np.any(bitmap, axis=1)
        if not np.any(rows):
            return gaps
        row_min, row_max = np.where(rows)[0][[0, -1]]
        mid_row = (row_min + row_max) // 2
        scan_line = bitmap[mid_row, :]
    else:
        cols = np.any(bitmap, axis=0)
        if not np.any(cols):
            return gaps
        col_min, col_max = np.where(cols)[0][[0, -1]]
        mid_col = (col_min + col_max) // 2
        scan_line = bitmap[:, mid_col]

    # Find contiguous runs of False (void) between True (material) regions
    in_material = False
    in_gap = False
    gap_start = 0
    first_material = -1
    last_material = -1

    for i, val in enumerate(scan_line):
        if val:
            if not in_material and first_material >= 0:
                in_material = True
            if first_material < 0:
                first_material = i
                in_material = True
            last_material = i
            if in_gap:
                gap_width_mm = (i - gap_start) * mm_per_pixel
                if gap_width_mm > 0.3:  # ignore sub-0.3mm noise
                    center = (gap_start + i) / 2.0
                    gaps.append((center, gap_width_mm))
                in_gap = False
        else:
            if in_material and not in_gap:
                in_gap = True
                gap_start = i
                in_material = False

    return gaps


def _measure_wall_thickness(bitmap, mm_per_pixel, axis='horizontal'):
    """Measure wall thicknesses (runs of filled pixels between gaps or edges).

    Returns list of (center_px, thickness_mm).
    """
    walls = []
    rows = np.any(bitmap, axis=1)
    cols = np.any(bitmap, axis=0)

    if axis == 'horizontal':
        if not np.any(rows):
            return walls
        row_min, row_max = np.where(rows)[0][[0, -1]]
        mid_row = (row_min + row_max) // 2
        scan_line = bitmap[mid_row, :]
    else:
        if not np.any(cols):
            return walls
        col_min, col_max = np.where(cols)[0][[0, -1]]
        mid_col = (col_min + col_max) // 2
        scan_line = bitmap[:, mid_col]

    # Find runs of True (material)
    run_start = None
    for i, val in enumerate(scan_line):
        if val and run_start is None:
            run_start = i
        elif not val and run_start is not None:
            thickness_mm = (i - run_start) * mm_per_pixel
            center = (run_start + i) / 2.0
            walls.append((center, thickness_mm))
            run_start = None
    if run_start is not None:
        thickness_mm = (len(scan_line) - run_start) * mm_per_pixel
        center = (run_start + len(scan_line)) / 2.0
        walls.append((center, thickness_mm))

    return walls


# ── Cut plane computation from spec ──────────────────────────────────────────

def _compute_cut_planes(spec, mesh):
    """Determine cut planes from the spec features plus general checks.

    Returns list of dicts:
        {
            'origin': [x, y, z],
            'normal': [nx, ny, nz],
            'label': str,          # e.g. "Section at Y=32.0mm — XZ Plane"
            'filename': str,       # e.g. "section_Y32.0_XZ.png"
            'expected': [          # spec dimensions to verify at this cut
                {'name': str, 'value': float, 'tolerance': float, 'type': str}
            ]
        }
    """
    cuts = []
    bb = mesh.bounds  # [[xmin,ymin,zmin],[xmax,ymax,zmax]]
    xmin, ymin, zmin = bb[0]
    xmax, ymax, zmax = bb[1]
    xmid = (xmin + xmax) / 2.0
    ymid = (ymin + ymax) / 2.0
    zmid = (zmin + zmax) / 2.0
    height = zmax - zmin
    width = xmax - xmin
    depth = ymax - ymin

    dims = spec.get("overall_dimensions", {})
    overall_tol = dims.get("tolerance", 0.3)

    # Process features for targeted cuts
    for feat in spec.get("features", []):
        feat_type = feat["type"]
        name = feat["name"]
        tol = feat.get("tolerance", 0.3)

        if feat_type == "slot":
            probe_z = feat.get("probe_z", 0.0)
            if probe_z == 0.0:
                probe_z = height / 2.0 + zmin
            else:
                probe_z = probe_z + zmin  # probe_z is relative to part bottom

            slot_width = feat.get("width", 0.0)

            # Slot typically runs along Y. Cut in XZ plane at ~45% along Y
            cut_y = ymin + depth * 0.45
            cuts.append({
                'origin': [xmid, cut_y, zmid],
                'normal': [0, 1, 0],
                'label': f"Section at Y={cut_y:.1f}mm — XZ Plane — {name}",
                'filename': f"section_Y{cut_y:.1f}_XZ_{_safe_name(name)}.png",
                'expected': [
                    {'name': f"{name} width", 'value': slot_width,
                     'tolerance': tol, 'type': 'gap_horizontal'},
                ]
            })

            # Also cut XY at the probe_z to verify slot profile
            cuts.append({
                'origin': [xmid, ymid, probe_z],
                'normal': [0, 0, 1],
                'label': f"Section at Z={probe_z:.1f}mm — XY Plane — {name}",
                'filename': f"section_Z{probe_z:.1f}_XY_{_safe_name(name)}.png",
                'expected': [
                    {'name': f"{name} profile", 'value': slot_width,
                     'tolerance': tol, 'type': 'gap_vertical'},
                ]
            })

        elif feat_type == "hole":
            diameter = feat.get("diameter", 0.0)
            position = feat.get("position", None)
            if position and len(position) >= 2:
                hx, hy = position[0], position[1]
            else:
                hx, hy = xmid, ymid
            # Cut XY at ~45% of the hole depth
            hole_z = zmin + height * 0.45
            cuts.append({
                'origin': [hx, hy, hole_z],
                'normal': [0, 0, 1],
                'label': f"Section at Z={hole_z:.1f}mm — XY Plane — {name}",
                'filename': f"section_Z{hole_z:.1f}_XY_{_safe_name(name)}.png",
                'expected': [
                    {'name': f"{name} diameter", 'value': diameter,
                     'tolerance': tol, 'type': 'hole_diameter'},
                ]
            })

        elif feat_type in ("pocket", "rail", "channel"):
            # Cut perpendicular to the long axis at ~55%
            cut_y = ymin + depth * 0.55
            cuts.append({
                'origin': [xmid, cut_y, zmid],
                'normal': [0, 1, 0],
                'label': f"Section at Y={cut_y:.1f}mm — XZ Plane — {name}",
                'filename': f"section_Y{cut_y:.1f}_XZ_{_safe_name(name)}.png",
                'expected': []
            })

    # Component-based cuts
    for comp in spec.get("components", []):
        name = comp["name"]
        c_len = comp.get("length", 0)
        c_wid = comp.get("width", 0)
        clearance = comp.get("effective_clearance_mm", comp.get("clearance_mm", 0.3))

        # Cut XZ at ~45% depth to check component cavity
        cut_y = ymin + depth * 0.45
        cuts.append({
            'origin': [xmid, cut_y, zmid],
            'normal': [0, 1, 0],
            'label': f"Section at Y={cut_y:.1f}mm — XZ Plane — {name} cavity",
            'filename': f"section_Y{cut_y:.1f}_XZ_{_safe_name(name)}.png",
            'expected': [
                {'name': f"{name} cavity width",
                 'value': max(c_len, c_wid) + 2 * clearance,
                 'tolerance': overall_tol, 'type': 'gap_horizontal'},
            ]
        })

    # General check cuts: XY at 1/3 and 2/3 height
    for frac, tag in [(1/3, "lower"), (2/3, "upper")]:
        cut_z = zmin + height * frac
        cuts.append({
            'origin': [xmid, ymid, cut_z],
            'normal': [0, 0, 1],
            'label': f"Section at Z={cut_z:.1f}mm — XY Plane — {tag} general",
            'filename': f"section_Z{cut_z:.1f}_XY_{tag}.png",
            'expected': [
                {'name': 'overall width', 'value': dims.get('width', 0),
                 'tolerance': overall_tol, 'type': 'overall_h'},
                {'name': 'overall depth', 'value': dims.get('depth', 0),
                 'tolerance': overall_tol, 'type': 'overall_v'},
            ]
        })

    # Always add XZ and YZ cuts through centroid for parts with no/few features
    # These catch geometry issues invisible in XY-only cuts (e.g., curved hooks,
    # L-brackets, wall-mount profiles)
    if len(spec.get("features", [])) == 0 and len(spec.get("components", [])) == 0:
        # XZ cut at Y midpoint — shows the part's side profile
        cuts.append({
            'origin': [xmid, ymid, zmid],
            'normal': [0, 1, 0],
            'label': f"Section at Y={ymid:.1f}mm — XZ Plane — side profile",
            'filename': f"section_Y{ymid:.1f}_XZ_side_profile.png",
            'expected': [
                {'name': 'overall width', 'value': dims.get('width', 0),
                 'tolerance': overall_tol, 'type': 'overall_h'},
                {'name': 'overall height', 'value': dims.get('height', 0),
                 'tolerance': overall_tol, 'type': 'overall_v'},
            ]
        })
        # YZ cut at X midpoint — shows the part's front profile
        cuts.append({
            'origin': [xmid, ymid, zmid],
            'normal': [1, 0, 0],
            'label': f"Section at X={xmid:.1f}mm — YZ Plane — front profile",
            'filename': f"section_X{xmid:.1f}_YZ_front_profile.png",
            'expected': [
                {'name': 'overall depth', 'value': dims.get('depth', 0),
                 'tolerance': overall_tol, 'type': 'overall_h'},
                {'name': 'overall height', 'value': dims.get('height', 0),
                 'tolerance': overall_tol, 'type': 'overall_v'},
            ]
        })

    # Deduplicate cuts at near-identical positions (within 0.5mm)
    deduped = []
    for cut in cuts:
        duplicate = False
        for existing in deduped:
            dist = np.linalg.norm(
                np.array(cut['origin']) - np.array(existing['origin']))
            same_normal = np.allclose(cut['normal'], existing['normal'], atol=0.1)
            if dist < 0.5 and same_normal:
                # Merge expected measurements
                existing['expected'].extend(cut['expected'])
                duplicate = True
                break
        if not duplicate:
            deduped.append(cut)

    return deduped


def _safe_name(s):
    """Convert a name to a filename-safe string."""
    return "".join(c if c.isalnum() or c in '-_' else '_' for c in s).strip('_')


# ── Rendering ────────────────────────────────────────────────────────────────

def _draw_dimension_h(ax, y, x1, x2, label, mm_per_px, x_off, y_off,
                      offset_px=40, color=DIM_LINE_COLOR, text_color=DIM_TEXT_COLOR):
    """Draw a horizontal dimension line with arrows and label."""
    # Convert pixel coords to mm coords for the annotation
    x1_mm = x1 * mm_per_px + x_off
    x2_mm = x2 * mm_per_px + x_off
    y_mm = y * mm_per_px + y_off

    y_line = y_mm - offset_px * mm_per_px

    # Extension lines
    ax.plot([x1_mm, x1_mm], [y_mm, y_line - 2 * mm_per_px],
            color=color, linewidth=0.8, alpha=0.6)
    ax.plot([x2_mm, x2_mm], [y_mm, y_line - 2 * mm_per_px],
            color=color, linewidth=0.8, alpha=0.6)

    # Dimension line with arrows
    ax.annotate('', xy=(x2_mm, y_line), xytext=(x1_mm, y_line),
                arrowprops=dict(arrowstyle='<->', color=color, lw=1.5))

    # Label
    mid_x = (x1_mm + x2_mm) / 2.0
    ax.text(mid_x, y_line - 4 * mm_per_px, label,
            ha='center', va='top', fontsize=7, color=text_color,
            fontfamily='sans-serif', fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.2', facecolor=BG_COLOR,
                      edgecolor='none', alpha=0.8))


def _draw_dimension_v(ax, x, y1, y2, label, mm_per_px, x_off, y_off,
                      offset_px=40, color=DIM_LINE_COLOR, text_color=DIM_TEXT_COLOR):
    """Draw a vertical dimension line with arrows and label."""
    x_mm = x * mm_per_px + x_off
    y1_mm = y1 * mm_per_px + y_off
    y2_mm = y2 * mm_per_px + y_off

    x_line = x_mm + offset_px * mm_per_px

    # Extension lines
    ax.plot([x_mm, x_line + 2 * mm_per_px], [y1_mm, y1_mm],
            color=color, linewidth=0.8, alpha=0.6)
    ax.plot([x_mm, x_line + 2 * mm_per_px], [y2_mm, y2_mm],
            color=color, linewidth=0.8, alpha=0.6)

    # Dimension line with arrows
    ax.annotate('', xy=(x_line, y2_mm), xytext=(x_line, y1_mm),
                arrowprops=dict(arrowstyle='<->', color=color, lw=1.5))

    # Label
    mid_y = (y1_mm + y2_mm) / 2.0
    ax.text(x_line + 4 * mm_per_px, mid_y, label,
            ha='left', va='center', fontsize=7, color=text_color,
            fontfamily='sans-serif', fontweight='bold',
            rotation=90,
            bbox=dict(boxstyle='round,pad=0.2', facecolor=BG_COLOR,
                      edgecolor='none', alpha=0.8))


def render_single_section(mesh, cut_info, output_path):
    """Render one cross-section to a PNG with dimensions.

    Returns dict with measured values, or None if the section is empty.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.patches import FancyArrowPatch

    origin = cut_info['origin']
    normal = cut_info['normal']
    label = cut_info['label']
    expected = cut_info.get('expected', [])

    polygons, axis_labels, bbox, transform = _slice_mesh_polygons(
        mesh, origin, normal)

    if not polygons or bbox is None:
        return None

    xmin, xmax, ymin, ymax = bbox
    margin = max((xmax - xmin), (ymax - ymin)) * 0.15
    margin = max(margin, 3.0)  # at least 3mm margin

    # Rasterize for measurement
    bitmap, actual_mpp, bmp_x_off, bmp_y_off = _rasterize_polygons(
        polygons, bbox, MM_PER_PIXEL)

    # Measure overall dimensions from bitmap
    ow, oh, col_min, col_max, row_min, row_max = _measure_overall(
        bitmap, actual_mpp)

    # Measure gaps and walls
    h_gaps = _measure_gaps(bitmap, actual_mpp, 'horizontal')
    v_gaps = _measure_gaps(bitmap, actual_mpp, 'vertical')
    h_walls = _measure_wall_thickness(bitmap, actual_mpp, 'horizontal')
    v_walls = _measure_wall_thickness(bitmap, actual_mpp, 'vertical')

    measurements = {
        'overall_width': ow,
        'overall_height': oh,
        'h_gaps': h_gaps,
        'v_gaps': v_gaps,
        'h_walls': h_walls,
        'v_walls': v_walls,
    }

    # ── Render ────
    fig_w = 10
    fig_h = 10 * (ymax - ymin + 2 * margin) / max(xmax - xmin + 2 * margin, 0.1)
    fig_h = max(fig_h, 6)
    fig_h = min(fig_h, 14)

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)

    # Draw polygons
    for poly in polygons:
        ext = np.array(poly.exterior.coords)
        patch = mpatches.Polygon(ext, closed=True,
                                  facecolor=PART_FILL, edgecolor=PART_EDGE,
                                  linewidth=1.0, alpha=0.95)
        ax.add_patch(patch)

        for interior in poly.interiors:
            int_coords = np.array(interior.coords)
            hole_patch = mpatches.Polygon(int_coords, closed=True,
                                           facecolor=BG_COLOR,
                                           edgecolor=PART_EDGE,
                                           linewidth=0.8, alpha=1.0)
            ax.add_patch(hole_patch)

    ax.set_xlim(xmin - margin, xmax + margin)
    ax.set_ylim(ymin - margin, ymax + margin)
    ax.set_aspect('equal')

    # ── Dimension annotations ────

    # Overall width (horizontal)
    if ow > 0.1:
        spec_match = _find_expected(expected, 'overall_h', ow)
        dim_label = _format_dim(ow, spec_match)
        # Position below the part
        y_pos_px = row_max
        _draw_dimension_h(ax,
                          y_pos_px, col_min, col_max,
                          dim_label, actual_mpp,
                          bbox[0] - 2.0,  # x offset (xmin - margin)
                          bbox[3] + 2.0,  # y offset (ymax + margin), flipped
                          offset_px=60)

    # Overall height (vertical)
    if oh > 0.1:
        spec_match = _find_expected(expected, 'overall_v', oh)
        dim_label = _format_dim(oh, spec_match)
        x_pos_px = col_max
        _draw_dimension_v(ax,
                          x_pos_px, row_min, row_max,
                          dim_label, actual_mpp,
                          bbox[0] - 2.0,
                          bbox[3] + 2.0,
                          offset_px=60)

    # Gap dimensions (slots/cavities)
    gap_expected_h = [e for e in expected if e['type'] == 'gap_horizontal']
    gap_expected_v = [e for e in expected if e['type'] == 'gap_vertical']

    for i, (center_px, gap_mm) in enumerate(h_gaps):
        spec_match = gap_expected_h[i] if i < len(gap_expected_h) else None
        dim_label = _format_dim(gap_mm, spec_match)
        # Draw inline at the gap position
        gap_start = center_px - (gap_mm / actual_mpp) / 2.0
        gap_end = center_px + (gap_mm / actual_mpp) / 2.0
        rows_filled = np.any(bitmap, axis=1)
        if np.any(rows_filled):
            mid_row = (np.where(rows_filled)[0][0] + np.where(rows_filled)[0][-1]) // 2
        else:
            mid_row = bitmap.shape[0] // 2
        _draw_dimension_h(ax,
                          mid_row, gap_start, gap_end,
                          dim_label, actual_mpp,
                          bbox[0] - 2.0,
                          bbox[3] + 2.0,
                          offset_px=25)

    for i, (center_px, gap_mm) in enumerate(v_gaps):
        spec_match = gap_expected_v[i] if i < len(gap_expected_v) else None
        dim_label = _format_dim(gap_mm, spec_match)
        gap_start = center_px - (gap_mm / actual_mpp) / 2.0
        gap_end = center_px + (gap_mm / actual_mpp) / 2.0
        cols_filled = np.any(bitmap, axis=0)
        if np.any(cols_filled):
            mid_col = (np.where(cols_filled)[0][0] + np.where(cols_filled)[0][-1]) // 2
        else:
            mid_col = bitmap.shape[1] // 2
        _draw_dimension_v(ax,
                          mid_col, gap_start, gap_end,
                          dim_label, actual_mpp,
                          bbox[0] - 2.0,
                          bbox[3] + 2.0,
                          offset_px=25)

    # Wall thickness callouts (show the two thinnest walls)
    for walls, axis_name in [(h_walls, 'h'), (v_walls, 'v')]:
        if len(walls) < 2:
            continue
        # Sort by thickness, annotate the two thinnest
        sorted_walls = sorted(walls, key=lambda w: w[1])
        for center_px, thick_mm in sorted_walls[:2]:
            wall_label = f"wall: {thick_mm:.2f}mm"
            # Find spec min_wall
            min_wall = spec.get("min_wall_mm", None) if 'spec' in dir() else None
            if axis_name == 'h':
                wall_x = center_px * actual_mpp + (bbox[0] - 2.0)
                rows_f = np.any(bitmap, axis=1)
                if np.any(rows_f):
                    wall_y = np.where(rows_f)[0][0] * actual_mpp + (bbox[3] + 2.0)
                else:
                    wall_y = (ymin + ymax) / 2.0
                ax.annotate(wall_label,
                            xy=(wall_x, wall_y),
                            fontsize=6, color='#FFD700',
                            fontfamily='sans-serif',
                            ha='center', va='bottom',
                            bbox=dict(boxstyle='round,pad=0.15',
                                      facecolor=BG_COLOR, edgecolor='#FFD700',
                                      alpha=0.8, linewidth=0.5))

    # ── Scale bar ────
    scale_len_mm = _nice_scale(max(ow, oh, 1.0) * 0.2)
    sb_x = xmin - margin * 0.5
    sb_y = ymin - margin * 0.6
    ax.plot([sb_x, sb_x + scale_len_mm], [sb_y, sb_y],
            color=SCALE_BAR_COLOR, linewidth=2.5, solid_capstyle='butt')
    ax.plot([sb_x, sb_x], [sb_y - 0.5, sb_y + 0.5],
            color=SCALE_BAR_COLOR, linewidth=1.5)
    ax.plot([sb_x + scale_len_mm, sb_x + scale_len_mm],
            [sb_y - 0.5, sb_y + 0.5],
            color=SCALE_BAR_COLOR, linewidth=1.5)
    ax.text(sb_x + scale_len_mm / 2, sb_y - 1.0,
            f"{scale_len_mm:.0f}mm", ha='center', va='top',
            fontsize=7, color=SCALE_BAR_COLOR, fontfamily='sans-serif')

    # ── Title ────
    ax.set_title(label, fontsize=11, fontweight='bold',
                 color=TITLE_COLOR, pad=12,
                 fontfamily='sans-serif')

    # ── Axis labels ────
    ax.set_xlabel(f"{axis_labels[0]} (mm)", fontsize=8, color=TITLE_COLOR,
                  fontfamily='sans-serif')
    ax.set_ylabel(f"{axis_labels[1]} (mm)", fontsize=8, color=TITLE_COLOR,
                  fontfamily='sans-serif')
    ax.tick_params(colors=TITLE_COLOR, labelsize=6)
    for spine in ax.spines.values():
        spine.set_color('#555555')

    plt.tight_layout()
    plt.savefig(output_path, dpi=DPI, facecolor=fig.get_facecolor(),
                bbox_inches='tight', pad_inches=0.15)
    plt.close()

    return measurements


def _find_expected(expected_list, dim_type, measured_value):
    """Find a matching expected dimension spec for the given type."""
    for e in expected_list:
        if e['type'] == dim_type:
            return e
    return None


def _format_dim(measured_mm, spec_match=None):
    """Format a dimension label, optionally with spec comparison."""
    if spec_match and spec_match.get('value', 0) > 0:
        tol = spec_match.get('tolerance', 0.3)
        expected = spec_match['value']
        return f"{measured_mm:.2f}mm (spec: {expected:.1f} \u00b1{tol:.1f})"
    return f"{measured_mm:.2f}mm"


def _nice_scale(target_mm):
    """Return a nice round scale bar length close to target_mm."""
    nice = [1, 2, 5, 10, 15, 20, 25, 50, 75, 100, 150, 200]
    return min(nice, key=lambda n: abs(n - target_mm))


# ── Main API ─────────────────────────────────────────────────────────────────

def render_sections(step_path, spec_path=None, output_dir=None):
    """Render all cross-sections for a STEP file.

    Args:
        step_path: path to the STEP file
        spec_path: path to the .spec.json (default: sibling of STEP)
        output_dir: directory for output PNGs (default: same as STEP file)

    Returns:
        list of dicts with 'file', 'label', 'measurements' for each section
    """
    step_path = str(Path(step_path).resolve())

    if spec_path is None:
        spec_path = str(Path(step_path).with_suffix(".spec.json"))
    spec_path = str(Path(spec_path).resolve())

    if output_dir is None:
        output_dir = str(Path(step_path).parent)
    output_dir = str(Path(output_dir).resolve())
    os.makedirs(output_dir, exist_ok=True)

    spec = load_spec(spec_path)
    print(f"[sections] Loading mesh from {step_path}...")
    mesh = _load_mesh(step_path)
    print(f"[sections] Mesh loaded: {len(mesh.faces)} triangles")

    cuts = _compute_cut_planes(spec, mesh)
    print(f"[sections] {len(cuts)} cross-sections planned")

    results = []
    for i, cut in enumerate(cuts):
        out_path = os.path.join(output_dir, cut['filename'])
        print(f"[sections] [{i+1}/{len(cuts)}] {cut['label']}")

        measurements = render_single_section(mesh, cut, out_path)

        if measurements is None:
            print(f"  -> empty section, skipped")
            continue

        print(f"  -> {out_path}")
        ow = measurements['overall_width']
        oh = measurements['overall_height']
        print(f"     overall: {ow:.2f} x {oh:.2f}mm")
        for center, gap in measurements['h_gaps']:
            print(f"     h-gap: {gap:.2f}mm")
        for center, gap in measurements['v_gaps']:
            print(f"     v-gap: {gap:.2f}mm")

        results.append({
            'file': out_path,
            'label': cut['label'],
            'measurements': measurements,
        })

    print(f"[sections] Done — {len(results)} sections rendered to {output_dir}")
    return results


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Render dimensioned cross-section views of a STEP file."
    )
    parser.add_argument("step_file", help="Path to the STEP file")
    parser.add_argument("--spec", default=None,
                        help="Path to .spec.json (default: sibling of STEP file)")
    parser.add_argument("--output-dir", default=None,
                        help="Output directory for PNGs (default: same as STEP)")
    args = parser.parse_args()

    step_path = args.step_file
    if not os.path.exists(step_path):
        print(f"Error: STEP file not found: {step_path}")
        sys.exit(1)

    results = render_sections(step_path, args.spec, args.output_dir)

    if not results:
        print("No sections rendered — check spec and geometry.")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
