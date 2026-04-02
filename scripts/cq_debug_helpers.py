"""
CadQuery Debug Helpers — catch workplane drift, silent booleans, and feature overflow.

Usage:
    from cq_debug_helpers import debug_workplane, verify_boolean, verify_feature_bounds
"""
import cadquery as cq
import math


def debug_workplane(wp, label="", expected_origin=None, tolerance=0.1):
    """Print workplane origin/normal. Raise if origin drifts from expected."""
    origin = wp.plane.origin.toTuple()
    normal = wp.plane.zDir.toTuple()
    print(f"[WP {label}] origin=({origin[0]:.2f}, {origin[1]:.2f}, {origin[2]:.2f}) "
          f"normal=({normal[0]:.2f}, {normal[1]:.2f}, {normal[2]:.2f})")
    if expected_origin is not None:
        dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(origin, expected_origin)))
        if dist > tolerance:
            raise ValueError(
                f"[WP {label}] Origin drift detected! "
                f"Expected {expected_origin}, got {origin} (delta={dist:.3f}mm)"
            )
    return wp


def verify_boolean(before, after, operation="cut", label=""):
    """Compare two solids to detect silent boolean failure."""
    vol_before = before.val().Volume() if hasattr(before.val(), 'Volume') else 0
    vol_after = after.val().Volume() if hasattr(after.val(), 'Volume') else 0
    faces_before = len(before.val().Faces()) if hasattr(before.val(), 'Faces') else 0
    faces_after = len(after.val().Faces()) if hasattr(after.val(), 'Faces') else 0

    vol_changed = abs(vol_after - vol_before) > 0.001
    faces_changed = faces_after != faces_before

    bb_before_obj = before.val().BoundingBox()
    bb_after_obj = after.val().BoundingBox()
    cx_shift = abs((bb_after_obj.xmin + bb_after_obj.xmax)/2 - (bb_before_obj.xmin + bb_before_obj.xmax)/2)
    cy_shift = abs((bb_after_obj.ymin + bb_after_obj.ymax)/2 - (bb_before_obj.ymin + bb_before_obj.ymax)/2)
    cz_shift = abs((bb_after_obj.zmin + bb_after_obj.zmax)/2 - (bb_before_obj.zmin + bb_before_obj.zmax)/2)
    centroid_shifted = (cx_shift + cy_shift + cz_shift) > 0.01

    if not vol_changed and not faces_changed and not centroid_shifted:
        raise RuntimeError(
            f"[Boolean {label}] {operation} produced NO change! "
            f"Volume: {vol_before:.2f} -> {vol_after:.2f}, "
            f"Faces: {faces_before} -> {faces_after}"
        )
    return after


def verify_boolean_inline(body, operation_fn, operation="cut", label=""):
    """Verify a boolean inline: verify_boolean_inline(body, lambda b: b.cut(tool))."""
    result = operation_fn(body)
    return verify_boolean(body, result, operation, label)


def verify_feature_bounds(body_before, body_after, label="", tolerance=0.1):
    """Check that new geometry stays within the base body's XY footprint."""
    bb_before = body_before.val().BoundingBox()
    bb_after = body_after.val().BoundingBox()

    x_overflow = max(0, bb_after.xmax - bb_before.xmax - tolerance,
                     bb_before.xmin - bb_after.xmin - tolerance)
    y_overflow = max(0, bb_after.ymax - bb_before.ymax - tolerance,
                     bb_before.ymin - bb_after.ymin - tolerance)
    z_overflow = max(0, bb_after.zmax - bb_before.zmax - tolerance,
                     bb_before.zmin - bb_after.zmin - tolerance)

    if x_overflow > 0 or y_overflow > 0 or z_overflow > 0:
        raise RuntimeError(
            f"[Bounds {label}] Feature extends past body! "
            f"X overflow: {x_overflow:.2f}mm, Y overflow: {y_overflow:.2f}mm, Z overflow: {z_overflow:.2f}mm"
        )
    return body_after


class StepExporter:
    """Export intermediate geometry snapshots at each construction step."""

    def __init__(self, prefix="step", output_dir=".", enabled=False):
        self.prefix = prefix
        self.output_dir = output_dir
        self.enabled = enabled
        self.step_num = 0

    def export(self, solid, label=""):
        if not self.enabled:
            return solid
        self.step_num += 1
        import os
        name = f"{self.prefix}_{self.step_num:02d}_{label}.stl"
        path = os.path.join(self.output_dir, name)
        cq.exporters.export(solid, path)
        print(f"[Step {self.step_num}] Exported: {path}")
        return solid
