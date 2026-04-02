#!/usr/bin/env python3
"""
render_preview.py — Renders a multi-view preview of a STEP or STL file.

STEP files render with per-face shading (clean flat surfaces).
STL falls back to per-triangle shading.

Usage:
    python render_preview.py part.step preview.png
    python render_preview.py part.stl  preview.png
    python render_preview.py part.step preview.png --size 1200
"""

import sys
import os
import numpy as np

# ── visual theme ──────────────────────────────────────────────
BG           = '#2B2B2B'   # dark charcoal background
TITLE_COLOR  = '#D0D0D0'   # light grey titles
# two-tone material: cool teal-blue
MAT_SHADOW   = np.array([0.12, 0.30, 0.44])   # deep steel
MAT_BASE     = np.array([0.24, 0.55, 0.75])   # mid blue
MAT_HIGHLIGHT= np.array([0.50, 0.78, 0.92])   # bright sky
# lighting
KEY_LIGHT    = np.array([ 0.35, -0.55,  0.75])  # upper-left-front
FILL_LIGHT   = np.array([-0.60,  0.30,  0.40])  # lower-right-back (softer)
FILL_STRENGTH= 0.35                              # fill intensity relative to key
AMBIENT      = 0.10                               # base illumination floor
# ──────────────────────────────────────────────────────────────


def _shade_color(key_dot, fill_dot):
    """Two-light shading with ambient floor (scalar, used for STEP per-face path)."""
    intensity = np.clip(key_dot + fill_dot * FILL_STRENGTH + AMBIENT, 0.0, 1.0)
    if intensity < 0.4:
        t = intensity / 0.4
        c = MAT_SHADOW * (1 - t) + MAT_BASE * t
    elif intensity < 0.75:
        t = (intensity - 0.4) / 0.35
        c = MAT_BASE * (1 - t) + MAT_HIGHLIGHT * t
    else:
        t = (intensity - 0.75) / 0.25
        SPECULAR = MAT_HIGHLIGHT + np.array([0.15, 0.15, 0.15])
        c = MAT_HIGHLIGHT * (1 - t) + SPECULAR * t
    return [float(np.clip(c[0], 0, 1)),
            float(np.clip(c[1], 0, 1)),
            float(np.clip(c[2], 0, 1)), 0.97]


def _shade_colors_vectorized(kd, fd):
    """Vectorized two-light shading for per-triangle STL path. Returns (N, 4) RGBA."""
    SPECULAR = MAT_HIGHLIGHT + np.array([0.15, 0.15, 0.15])
    intensity = np.clip(kd + fd * FILL_STRENGTH + AMBIENT, 0.0, 1.0)
    n = len(intensity)
    colors = np.empty((n, 4), dtype=np.float64)
    colors[:, 3] = 0.97

    # band 1: intensity < 0.4 — lerp shadow -> base
    m1 = intensity < 0.4
    t1 = intensity[m1] / 0.4
    colors[m1, :3] = MAT_SHADOW[None, :] * (1 - t1[:, None]) + MAT_BASE[None, :] * t1[:, None]

    # band 2: 0.4 <= intensity < 0.75 — lerp base -> highlight
    m2 = (~m1) & (intensity < 0.75)
    t2 = (intensity[m2] - 0.4) / 0.35
    colors[m2, :3] = MAT_BASE[None, :] * (1 - t2[:, None]) + MAT_HIGHLIGHT[None, :] * t2[:, None]

    # band 3: intensity >= 0.75 — lerp highlight -> specular
    m3 = ~(m1 | m2)
    t3 = (intensity[m3] - 0.75) / 0.25
    colors[m3, :3] = MAT_HIGHLIGHT[None, :] * (1 - t3[:, None]) + SPECULAR[None, :] * t3[:, None]

    np.clip(colors[:, :3], 0, 1, out=colors[:, :3])
    return colors


def _extract_face_groups_from_step(step_path, tolerance=0.05):
    """Load STEP and return per-B-rep-face triangle groups."""
    import cadquery as cq
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE
    from OCP.BRep import BRep_Tool
    from OCP.TopLoc import TopLoc_Location
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopoDS import TopoDS

    shape = cq.importers.importStep(step_path)
    solid = shape.val().wrapped
    BRepMesh_IncrementalMesh(solid, tolerance, False, 0.1)

    groups = []
    exp = TopExp_Explorer(solid, TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face_s(exp.Current())
        loc = TopLoc_Location()
        poly = BRep_Tool.Triangulation_s(face, loc)
        if poly is not None:
            trsf = loc.Transformation()
            is_identity = loc.IsIdentity()
            nodes = []
            for i in range(1, poly.NbNodes() + 1):
                p = poly.Node(i)
                if not is_identity:
                    p = p.Transformed(trsf)
                nodes.append([p.X(), p.Y(), p.Z()])
            tris = []
            for i in range(1, poly.NbTriangles() + 1):
                t = poly.Triangle(i)
                i1, i2, i3 = t.Get()
                tris.append([i1 - 1, i2 - 1, i3 - 1])
            if nodes and tris:
                groups.append((np.array(nodes), np.array(tris)))
        exp.Next()
    return groups


def _load_stl_triangles(stl_path):
    """Load STL and return (vertices_array, faces_array)."""
    import trimesh
    mesh = trimesh.load(stl_path)
    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(
            [g for g in mesh.geometry.values() if isinstance(g, trimesh.Trimesh)]
        )
    return mesh.vertices, mesh.faces


def render_preview(input_path, output_path, size=3200):
    """Render a multi-view preview from a STEP or STL file."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    ext = os.path.splitext(input_path)[1].lower()
    is_step = ext in ('.step', '.stp')

    key_dir = KEY_LIGHT / np.linalg.norm(KEY_LIGHT)
    fill_dir = FILL_LIGHT / np.linalg.norm(FILL_LIGHT)

    # ── load geometry ──
    if is_step:
        face_groups = _extract_face_groups_from_step(input_path)
        if not face_groups:
            print(f"Error: no geometry extracted from {input_path}")
            sys.exit(1)
        all_verts = np.vstack([v for v, _ in face_groups])
    else:
        verts, faces = _load_stl_triangles(input_path)
        face_groups = [(verts, faces)]
        all_verts = verts

    # center and normalise to [-1, 1]
    centroid = all_verts.mean(axis=0)
    for i, (v, f) in enumerate(face_groups):
        face_groups[i] = (v - centroid, f)
    all_verts = all_verts - centroid
    scale = np.abs(all_verts).max()
    if scale > 0:
        for i, (v, f) in enumerate(face_groups):
            face_groups[i] = (v / scale, f)

    # detect flat parts
    extents = all_verts.max(axis=0) - all_verts.min(axis=0)
    se = extents / scale if scale > 0 else extents
    is_flat = (se.min() / se.max() < 0.15) if se.max() > 0 else False

    if is_flat:
        views = [(90, 0, "TOP"), (25, -50, "PERSPECTIVE")]
        nrows, ncols = 1, 2
    else:
        views = [(0, 0, "FRONT"), (0, 90, "RIGHT"),
                 (90, 0, "TOP"), (25, -50, "PERSPECTIVE")]
        nrows, ncols = 2, 2

    # Compute axis range from actual normalized data bounds.
    # Previous fixed 0.55 clipped elongated parts — data lives in [-1, 1]
    # after normalization, so rng must be >= 1.0 to show everything.
    max_abs = np.abs(np.vstack([v for v, _ in face_groups])).max() if face_groups else 1.0
    rng_ortho = max_abs * 1.10   # 10% margin — shows everything
    rng_persp = max_abs * 1.20   # extra room for perspective diagonal

    dpi = 200
    fig_w = size / dpi
    fig_h = fig_w * nrows / ncols
    fig, axes = plt.subplots(nrows, ncols,
                             figsize=(fig_w, fig_h),
                             subplot_kw={'projection': '3d'})
    fig.patch.set_facecolor(BG)

    axes_flat = list(axes.flat) if hasattr(axes, 'flat') else [axes]

    for ax, (elev, azim, title) in zip(axes_flat, views):
        ax.set_facecolor(BG)
        is_persp_view = 'PERSP' in title

        for verts, faces in face_groups:
            triangles = verts[faces]

            if is_step:
                all_normals = np.cross(triangles[:, 1] - triangles[:, 0],
                                       triangles[:, 2] - triangles[:, 0])
                avg_n = all_normals.sum(axis=0)
                nm = np.linalg.norm(avg_n)
                if nm > 0:
                    avg_n /= nm
                kd = float(np.clip(np.dot(avg_n, key_dir), 0.0, 1.0))
                fd = float(np.clip(np.dot(avg_n, fill_dir), 0.0, 1.0))
                color = _shade_color(kd, fd)
                fc = [color] * len(faces)
            else:
                tri_normals = np.cross(triangles[:, 1] - triangles[:, 0],
                                       triangles[:, 2] - triangles[:, 0])
                norms = np.linalg.norm(tri_normals, axis=1, keepdims=True)
                norms[norms == 0] = 1
                tri_normals /= norms
                kd = np.clip(np.dot(tri_normals, key_dir), 0.0, 1.0)
                fd = np.clip(np.dot(tri_normals, fill_dir), 0.0, 1.0)
                fc = _shade_colors_vectorized(kd, fd)

            coll = Poly3DCollection(triangles,
                                    facecolors=fc,
                                    edgecolors='none',
                                    linewidths=0)
            ax.add_collection3d(coll)

        rng = rng_persp if is_persp_view else rng_ortho
        ax.set_xlim(-rng, rng)
        ax.set_ylim(-rng, rng)
        ax.set_zlim(-rng, rng)

        # clean title typography
        ax.set_title(title, fontsize=11, fontweight='bold',
                     color=TITLE_COLOR, pad=4,
                     fontfamily='sans-serif', fontstyle='normal',
                     fontdict={'fontstretch': 'condensed'})
        ax.view_init(elev=elev, azim=azim)
        ax.set_axis_off()

    plt.subplots_adjust(left=0.01, right=0.99, top=0.93, bottom=0.01,
                        wspace=0.02, hspace=0.08)
    plt.savefig(output_path, dpi=dpi, bbox_inches='tight',
                facecolor=fig.get_facecolor(), pad_inches=0.1)
    plt.close()
    print(f"Preview saved: {output_path}")


def main():
    if len(sys.argv) < 3:
        print("Usage: render_preview.py <input.step|.stl> <output.png> [--size N]")
        sys.exit(1)

    input_path = os.path.realpath(sys.argv[1])
    output_path = os.path.realpath(sys.argv[2])
    size = 3200
    if "--size" in sys.argv:
        idx = sys.argv.index("--size") + 1
        if idx >= len(sys.argv):
            print("Error: --size requires a value")
            sys.exit(1)
        size = int(sys.argv[idx])
    size = max(400, min(size, 8000))

    if not os.path.exists(input_path):
        print(f"Error: {input_path} not found")
        sys.exit(1)

    render_preview(input_path, output_path, size)


if __name__ == "__main__":
    main()
