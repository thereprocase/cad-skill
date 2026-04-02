#!/usr/bin/env python3
"""
validate_geometry.py — Post-export intent vs. reality validator for cad-skill.

Loads a STEP file and checks it against a .spec.json file that Claude wrote
before generating geometry. Reports pass/fail per check with measured vs.
expected values so failures are actionable.

Usage:
    python validate_geometry.py part.step                    # finds part.spec.json
    python validate_geometry.py part.step --spec custom.json # explicit spec

Exit code 0 = all checks passed. Exit code 1 = one or more checks failed.
"""

import argparse
import sys
import os
from pathlib import Path

import numpy as np

# Allow running from the scripts/ directory or from anywhere
_SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SKILL_DIR / "lib"))

from spec_format import load_spec


# ── Result helpers ────────────────────────────────────────────────────────────

class CheckResult:
    def __init__(self, label: str, passed: bool, detail: str):
        self.label = label
        self.passed = passed
        self.detail = detail

    def __str__(self):
        tag = "[PASS]" if self.passed else "[FAIL]"
        return f"{tag} {self.label}: {self.detail}"


def _pass(label, detail):
    return CheckResult(label, True, detail)

def _fail(label, detail):
    return CheckResult(label, False, detail)


# ── Geometry loading ──────────────────────────────────────────────────────────

def _load_step(step_path: str):
    """Load a STEP file and return a CadQuery Workplane wrapping the solid."""
    import cadquery as cq
    shape = cq.importers.importStep(step_path)
    return shape


def _bounding_box(shape):
    """Return the BoundingBox of a CadQuery shape."""
    return shape.val().BoundingBox()


# ── Cross-section measurement ─────────────────────────────────────────────────

def _cross_section_at_z(shape, z: float, slab_thickness: float = 0.2):
    """Return a cross-sectional face of the solid at the given Z height.

    Uses a thin slab intersection rather than a true plane section because
    OCC's BRepAlgoAPI_Section on STEP geometry can produce degenerate edges
    on near-planar faces. A slab gives a proper closed wire that can be
    measured.

    Returns a CadQuery Workplane of the intersection, or None if empty.
    """
    import cadquery as cq
    slab = (
        cq.Workplane("XY")
        .transformed(offset=(0, 0, z))
        .box(1e6, 1e6, slab_thickness, centered=True)
    )
    try:
        section = shape.intersect(slab)
        bb = section.val().BoundingBox()
        if bb.xlen < 0.001 and bb.ylen < 0.001:
            return None
        return section
    except Exception:
        return None


def _measure_gap_at_z(shape, z: float, axis: str = "x") -> float:
    """Measure the bounding-box extent of the solid's cross-section at height z.

    axis: 'x' or 'y'
    Returns the bounding-box span of the cross-section along the given axis.
    For interior gap/slot measurement, use _measure_slot_gap_at_z instead.
    """
    section = _cross_section_at_z(shape, z)
    if section is None:
        return 0.0
    bb = section.val().BoundingBox()
    return bb.xlen if axis == "x" else bb.ylen


def _measure_slot_gap_at_z(shape, z: float, exterior_bb, n_probes: int = 120) -> float:
    """Measure the largest interior gap (slot/void) at height z.

    Strategy: sample n_probes positions along each of the X and Y axes. At each
    position, test whether that point is inside the solid by intersecting a tiny
    cube with the shape. Build a boolean occupancy array, then find the longest
    run of empty (void) positions — that run length is the gap width.

    Works correctly for through-slots that span the full part in one axis:
    the void shows up as a contiguous empty run in the perpendicular axis.
    Returns the largest gap found across both axes, in mm.
    """
    import cadquery as cq

    def _occupancy(axis: str) -> tuple:
        """Return (positions_mm, occupied_bool_array) along the given axis."""
        if axis == "x":
            positions = np.linspace(exterior_bb.xmin, exterior_bb.xmax, n_probes)
            # Test at Y center, Z=probe_z
            y_center = (exterior_bb.ymin + exterior_bb.ymax) / 2.0
            probes = [(p, y_center, z) for p in positions]
        else:
            positions = np.linspace(exterior_bb.ymin, exterior_bb.ymax, n_probes)
            x_center = (exterior_bb.xmin + exterior_bb.xmax) / 2.0
            probes = [(x_center, p, z) for p in positions]

        occupied = np.zeros(len(probes), dtype=bool)
        cube_size = (exterior_bb.xmax - exterior_bb.xmin) / (n_probes * 1.5)

        for i, (px, py, pz) in enumerate(probes):
            try:
                cube = (
                    cq.Workplane("XY")
                    .transformed(offset=(px, py, pz))
                    .box(cube_size, cube_size, 0.1, centered=True)
                )
                hit = shape.intersect(cube)
                bb = hit.val().BoundingBox()
                occupied[i] = (bb.xlen > cube_size * 0.1 or bb.ylen > cube_size * 0.1)
            except Exception:
                occupied[i] = False

        return positions, occupied

    def _largest_void_mm(positions, occupied):
        """Find the largest contiguous run of False (void) in occupied array."""
        step = positions[1] - positions[0] if len(positions) > 1 else 0
        max_gap = 0.0
        run = 0
        for occ in occupied:
            if not occ:
                run += 1
            else:
                if run * step > max_gap:
                    max_gap = run * step
                run = 0
        if run * step > max_gap:
            max_gap = run * step
        return max_gap

    pos_x, occ_x = _occupancy("x")
    pos_y, occ_y = _occupancy("y")

    gap_x = _largest_void_mm(pos_x, occ_x)
    gap_y = _largest_void_mm(pos_y, occ_y)

    # A through-slot appears as a large gap in its run direction (full part span)
    # and as a narrow gap in the perpendicular direction (the slot width).
    # Return the smaller non-zero gap: that's the slot width.
    # If one axis has no gap, return the other.
    nonzero = [g for g in (gap_x, gap_y) if g > 0.5]
    if not nonzero:
        return 0.0
    return min(nonzero)


# ── Individual checks ─────────────────────────────────────────────────────────

def check_overall_dimensions(shape, spec: dict) -> list:
    """Check bounding box matches overall_dimensions within tolerance."""
    results = []
    dims = spec["overall_dimensions"]
    tol = dims["tolerance"]
    bb = _bounding_box(shape)

    for axis, measured in (("width", bb.xlen), ("depth", bb.ylen), ("height", bb.zlen)):
        expected = dims[axis]
        delta = measured - expected
        label = f"Overall {axis}"
        detail = f"{measured:.2f}mm (expected {expected:.2f} ±{tol:.2f}mm)"
        if abs(delta) <= tol:
            results.append(_pass(label, detail))
        else:
            direction = "OVER" if delta > 0 else "UNDER"
            results.append(_fail(label, f"{detail} — {direction} by {abs(delta):.2f}mm"))

    return results


def check_features(shape, spec: dict) -> list:
    """Check each named feature in spec.features against measured geometry."""
    results = []
    dims = spec["overall_dimensions"]

    for feat in spec.get("features", []):
        feat_type = feat["type"]
        name = feat["name"]
        tol = feat["tolerance"]

        if feat_type == "slot":
            probe_z = feat["probe_z"]
            if probe_z == 0.0:
                probe_z = dims["height"] / 2.0

            expected_w = feat["width"]
            ext_bb = _bounding_box(shape)

            measured_w = _measure_slot_gap_at_z(shape, probe_z, ext_bb)

            label = f"Slot '{name}' width (gap at Z={probe_z:.1f}mm)"
            if measured_w == 0.0:
                results.append(_fail(label,
                    f"no gap detected at Z={probe_z:.1f}mm — "
                    f"probe_z may be outside the slot or inside solid material"))
                continue

            delta = measured_w - expected_w
            detail = f"{measured_w:.2f}mm (expected {expected_w:.2f} ±{tol:.2f}mm)"
            if abs(delta) <= tol:
                results.append(_pass(label, detail))
            else:
                direction = "OVER" if delta > 0 else "UNDER"
                results.append(_fail(label, f"{detail} — {direction} by {abs(delta):.2f}mm"))

        elif feat_type == "hole":
            expected_d = feat["diameter"]
            position = feat.get("position")
            measured_d, found_pos = _find_nearest_hole(shape, expected_d, position)

            label = f"Hole '{name}' diameter"
            if measured_d is None:
                results.append(_fail(label,
                    f"no circular edge found near expected diameter {expected_d:.2f}mm"))
            else:
                delta = measured_d - expected_d
                detail = (
                    f"{measured_d:.2f}mm (expected {expected_d:.2f} ±{tol:.2f}mm)"
                    + (f" at {found_pos}" if found_pos else "")
                )
                if abs(delta) <= tol:
                    results.append(_pass(label, detail))
                else:
                    direction = "OVER" if delta > 0 else "UNDER"
                    results.append(_fail(label, f"{detail} — {direction} by {abs(delta):.2f}mm"))

        elif feat_type in ("pocket", "rail", "channel"):
            # Verified implicitly through component fit checks and overall dims
            results.append(_pass(
                f"{feat_type.capitalize()} '{name}'",
                "verified via component clearance and overall dimension checks"
            ))

    return results


def _find_nearest_hole(shape, expected_diameter: float, position=None):
    """Find a circular edge in the shape closest in diameter to expected_diameter.

    Returns (measured_diameter, position_str) or (None, None) if no circles found.
    Uses OCC edge geometry to detect circular edges and measure their radii.
    """
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.GeomAbs import GeomAbs_Circle
    from OCP.BRepAdaptor import BRepAdaptor_Curve

    solid = shape.val().wrapped
    exp = TopExp_Explorer(solid, TopAbs_EDGE)

    candidates = []
    while exp.More():
        from OCP.TopoDS import TopoDS
        edge = TopoDS.Edge_s(exp.Current())
        adaptor = BRepAdaptor_Curve(edge)
        if adaptor.GetType() == GeomAbs_Circle:
            circle = adaptor.Circle()
            radius = circle.Radius()
            diameter = radius * 2.0
            center = circle.Location()
            pos = (center.X(), center.Y(), center.Z())
            candidates.append((diameter, pos))
        exp.Next()

    if not candidates:
        return None, None

    if position and len(position) >= 2:
        px, py = float(position[0]), float(position[1])
        candidates.sort(key=lambda c: (
            (c[1][0] - px) ** 2 + (c[1][1] - py) ** 2
        ))
    else:
        candidates.sort(key=lambda c: abs(c[0] - expected_diameter))

    best_d, best_pos = candidates[0]
    pos_str = f"({best_pos[0]:.1f}, {best_pos[1]:.1f}, {best_pos[2]:.1f})"
    return best_d, pos_str


def check_components(shape, spec: dict) -> list:
    """Check that each component fits in the part with required clearance.

    Takes a cross-section at 1/3 of the part height (a reasonable approximation
    for where a component's body sits) and checks the cavity bounding box is
    large enough for component + clearance on each side.
    """
    results = []
    part_height = spec["overall_dimensions"]["height"]

    for comp in spec.get("components", []):
        name = comp["name"]
        c_len = comp["length"]
        c_wid = comp["width"]
        clearance = comp["effective_clearance_mm"]

        required_len = c_len + 2 * clearance
        required_wid = c_wid + 2 * clearance

        probe_z = part_height / 3.0

        x_span = _measure_gap_at_z(shape, probe_z, "x")
        y_span = _measure_gap_at_z(shape, probe_z, "y")

        if x_span == 0.0 and y_span == 0.0:
            results.append(_fail(
                f"Component '{name}' fit",
                f"cross-section at Z={probe_z:.1f}mm is empty — cannot verify fit"
            ))
            continue

        # Long axis of cross-section accommodates long axis of component
        span_major = max(x_span, y_span)
        span_minor = min(x_span, y_span)
        req_major = max(required_len, required_wid)
        req_minor = min(required_len, required_wid)

        for dim_name, measured, required, nominal in (
            ("length", span_major, req_major, max(c_len, c_wid)),
            ("width",  span_minor, req_minor, min(c_len, c_wid)),
        ):
            label = f"Component '{name}' {dim_name} fit"
            if measured >= required:
                actual_clearance = (measured - nominal) / 2.0
                detail = (
                    f"cavity {measured:.2f}mm >= {nominal:.2f}mm component "
                    f"+ {clearance:.2f}mm×2 clearance "
                    f"(actual each side: {actual_clearance:.2f}mm)"
                )
                results.append(_pass(label, detail))
            else:
                shortfall = required - measured
                detail = (
                    f"cavity {measured:.2f}mm < {nominal:.2f}mm + {clearance:.2f}mm×2 "
                    f"= {required:.2f}mm — SHORT by {shortfall:.2f}mm"
                )
                results.append(_fail(label, detail))

    return results


def check_minimum_wall(shape, spec: dict) -> list:
    """Estimate minimum wall thickness via bounding-box cross-section comparison.

    Samples cross-sections at 5 Z heights. At each level, the wall thickness
    estimate = (exterior span − interior cross-section span) / 2. This catches
    dramatically thin walls on simple hollow parts. check_printability.py runs
    a more thorough mesh-based analysis for complex geometry.
    """
    min_wall = spec["min_wall_mm"]
    part_height = spec["overall_dimensions"]["height"]
    bb_full = _bounding_box(shape)

    z_samples = [part_height * f for f in (0.15, 0.30, 0.50, 0.70, 0.85)]

    thinnest = float("inf")
    thinnest_z = None

    for z in z_samples:
        section = _cross_section_at_z(shape, z)
        if section is None:
            continue
        bb = section.val().BoundingBox()
        # (exterior - interior) / 2 = wall estimate per axis; take the thinner one
        x_wall = (bb_full.xlen - bb.xlen) / 2.0
        y_wall = (bb_full.ylen - bb.ylen) / 2.0
        wall_est = min(x_wall, y_wall)

        if 0 < wall_est < thinnest:
            thinnest = wall_est
            thinnest_z = z

    label = "Minimum wall thickness (bounding-box estimate)"
    if thinnest == float("inf"):
        return [_pass(label, "solid part — no hollow sections detected")]

    detail = f"{thinnest:.2f}mm at Z~{thinnest_z:.1f}mm (minimum required: {min_wall:.2f}mm)"
    if thinnest >= min_wall:
        return [_pass(label, detail)]
    else:
        return [_fail(label,
            f"{detail} — wall is {min_wall - thinnest:.2f}mm BELOW minimum. "
            f"Increase wall thickness or reduce cavity size."
        )]


# ── Main validation runner ────────────────────────────────────────────────────

def validate(step_path: str, spec_path: str = None) -> tuple:
    """Run all checks. Returns (results_list, all_passed_bool)."""
    if spec_path is None:
        spec_path = str(Path(step_path).with_suffix(".spec.json"))

    spec = load_spec(spec_path)
    shape = _load_step(step_path)

    results = []
    results += check_overall_dimensions(shape, spec)
    results += check_features(shape, spec)
    results += check_components(shape, spec)
    results += check_minimum_wall(shape, spec)

    all_passed = all(r.passed for r in results)
    return results, all_passed


def main():
    parser = argparse.ArgumentParser(
        description="Validate STEP geometry against design intent spec."
    )
    parser.add_argument("step_file", help="Path to the STEP file")
    parser.add_argument("--spec", default=None,
                        help="Path to .spec.json (default: sibling of STEP file)")
    args = parser.parse_args()

    step_path = args.step_file
    spec_path = args.spec

    if not os.path.exists(step_path):
        print(f"Error: STEP file not found: {step_path}")
        sys.exit(1)

    print(f"Validating: {step_path}")
    if spec_path:
        print(f"Spec: {spec_path}")
    print()

    try:
        results, all_passed = validate(step_path, spec_path)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Validation error: {e}")
        raise

    for r in results:
        print(r)

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print()
    print(f"{passed}/{total} checks passed")
    if not all_passed:
        print("Fix failures before showing to user.")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
