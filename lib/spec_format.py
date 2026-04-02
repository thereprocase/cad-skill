"""
spec_format.py — Intent capture format for cad-skill validation.

Claude fills in a spec dict immediately after the parameters block, before
any geometry is generated. The spec is the contract between design intent
and post-export validation. Both validate_geometry.py and
check_printability.py read this file to know what to check against.

Usage in a CadQuery script:
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
    from spec_format import write_spec

    spec = {
        "part_name": "DDR4 DIMM tray",
        "overall_dimensions": {"width": 60.0, "depth": 40.0, "height": 25.0},
        "min_wall_mm": 2.0,
        "components": [
            {"name": "DDR4 DIMM", "length": 133.35, "width": 31.25,
             "height": 3.8, "clearance_mm": 0.5}
        ],
        "features": [
            {"type": "slot", "name": "DIMM slot", "width": 5.0,
             "probe_z": 5.0, "tolerance": 0.3}
        ],
        "material": "PLA",
    }
    write_spec(spec, "dimm_tray.step")   # writes dimm_tray.spec.json
"""

import json
import os
from pathlib import Path

# ── Defaults ──────────────────────────────────────────────────────────────────

# Minimum acceptable wall thickness per material. FDM extrusion width is
# typically 0.4–0.45mm; two walls = ~0.9mm. 1.2mm is the hard floor,
# 2.0mm is the structural target.
_MIN_WALL_DEFAULTS = {
    "PLA":  1.2,
    "PETG": 1.2,
    "TPU":  3.0,   # TPU needs more wall for structure; flex absorbs compression
    "ABS":  1.2,
}

# Extra clearance added per material on top of what the design specifies.
# PLA is the baseline. PETG strings slightly. TPU swells under compression.
_EXTRA_CLEARANCE = {
    "PLA":  0.0,
    "PETG": 0.1,
    "TPU":  0.2,
    "ABS":  0.0,
}

_VALID_MATERIALS = set(_MIN_WALL_DEFAULTS.keys())

_VALID_FEATURE_TYPES = {"slot", "hole", "pocket", "rail", "channel"}

_DEFAULT_TOLERANCE_MM = 0.3   # ±mm on nominal dimension checks
_DEFAULT_BRIDGE_SPAN_MM = 20.0
_DEFAULT_OVERHANG_ANGLE_DEG = 45.0


# ── Public API ────────────────────────────────────────────────────────────────

def validate_spec(spec: dict) -> dict:
    """Validate spec dict and fill in defaults for optional fields.

    Raises ValueError with a specific message if required fields are missing
    or values are out of range. Returns a new dict with defaults applied so
    downstream validators never have to handle missing keys.

    Required fields: part_name, overall_dimensions (with width/depth/height).
    All other fields are optional and get sensible defaults.
    """
    if not isinstance(spec, dict):
        raise ValueError("spec must be a dict")

    out = dict(spec)  # shallow copy — we'll mutate out, not the caller's dict

    # ── part_name ──
    if "part_name" not in out or not out["part_name"]:
        raise ValueError("spec requires 'part_name' (non-empty string)")
    out["part_name"] = str(out["part_name"])

    # ── overall_dimensions ──
    dims = out.get("overall_dimensions")
    if not dims:
        raise ValueError("spec requires 'overall_dimensions' with width, depth, height")
    for axis in ("width", "depth", "height"):
        if axis not in dims:
            raise ValueError(f"spec.overall_dimensions missing '{axis}'")
        val = float(dims[axis])
        if val <= 0:
            raise ValueError(f"spec.overall_dimensions.{axis} must be > 0, got {val}")
    # Normalize: ensure each axis is a float; add tolerance if absent
    out["overall_dimensions"] = {
        "width":     float(dims["width"]),
        "depth":     float(dims["depth"]),
        "height":    float(dims["height"]),
        "tolerance": float(dims.get("tolerance", _DEFAULT_TOLERANCE_MM)),
    }

    # ── material ──
    material = out.get("material", "PLA").upper()
    if material not in _VALID_MATERIALS:
        raise ValueError(
            f"spec.material '{material}' not recognized. "
            f"Valid values: {sorted(_VALID_MATERIALS)}"
        )
    out["material"] = material

    # ── min_wall_mm ──
    if "min_wall_mm" not in out:
        out["min_wall_mm"] = _MIN_WALL_DEFAULTS[material]
    else:
        out["min_wall_mm"] = float(out["min_wall_mm"])
        if out["min_wall_mm"] <= 0:
            raise ValueError(f"spec.min_wall_mm must be > 0, got {out['min_wall_mm']}")

    # ── components ──
    components = out.get("components", [])
    if not isinstance(components, list):
        raise ValueError("spec.components must be a list")
    validated_components = []
    for i, comp in enumerate(components):
        c = _validate_component(comp, i)
        # Add material extra clearance on top of the spec'd clearance.
        # The validator uses effective_clearance_mm so the check reflects
        # real FDM behavior, not just the nominal spec.
        c["effective_clearance_mm"] = (
            c["clearance_mm"] + _EXTRA_CLEARANCE[material]
        )
        validated_components.append(c)
    out["components"] = validated_components

    # ── features ──
    features = out.get("features", [])
    if not isinstance(features, list):
        raise ValueError("spec.features must be a list")
    out["features"] = [_validate_feature(f, i) for i, f in enumerate(features)]

    # ── printability thresholds ──
    out["overhangs_ok"] = bool(out.get("overhangs_ok", False))
    out["max_overhang_angle_deg"] = float(
        out.get("max_overhang_angle_deg", _DEFAULT_OVERHANG_ANGLE_DEG)
    )
    out["max_bridge_span_mm"] = float(
        out.get("max_bridge_span_mm", _DEFAULT_BRIDGE_SPAN_MM)
    )

    return out


def create_spec(name: str, width: float = 0, depth: float = 0,
                height: float = 0, **kwargs) -> dict:
    """Build a spec dict with required fields pre-filled, then validate it.

    Positional shorthand for the common case where you know the outer dims
    and just need to tack on components/features:

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

    Returns a validated spec dict ready for write_spec().
    """
    raw = {
        "part_name": name,
        "overall_dimensions": {
            "width": width,
            "depth": depth,
            "height": height,
        },
    }
    raw.update(kwargs)

    # Let tolerance pass through to overall_dimensions if given as a kwarg
    if "tolerance" in kwargs:
        raw["overall_dimensions"]["tolerance"] = kwargs.pop("tolerance")

    return validate_spec(raw)


def write_spec(spec: dict, output_path: str) -> str:
    """Validate spec and write it as JSON alongside the output file.

    output_path can be:
    - A STEP/STL file path: "part.step" → writes "part.spec.json"
    - An explicit .spec.json path: written as-is

    Returns the path of the written .spec.json file.
    """
    validated = validate_spec(spec)

    p = Path(output_path)
    if p.suffix.lower() in (".step", ".stp", ".stl"):
        spec_path = p.with_suffix(".spec.json")
    elif p.suffix.lower() == ".json":
        spec_path = p
    else:
        # Unknown extension — append .spec.json
        spec_path = Path(str(p) + ".spec.json")

    spec_path.parent.mkdir(parents=True, exist_ok=True)
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(validated, f, indent=2)

    print(f"[spec] Written: {spec_path}")
    return str(spec_path)


def load_spec(spec_path: str) -> dict:
    """Load and validate a spec from a .spec.json file.

    Accepts:
    - Direct path to a .spec.json file
    - Path to a STEP/STL file — looks for the sibling .spec.json

    Raises FileNotFoundError if the spec file doesn't exist.
    Raises ValueError if the spec is malformed.
    """
    p = Path(spec_path)
    if p.suffix.lower() in (".step", ".stp", ".stl"):
        p = p.with_suffix(".spec.json")

    if not p.exists():
        raise FileNotFoundError(
            f"Spec file not found: {p}\n"
            f"Write a spec in your CadQuery script using write_spec() before exporting."
        )

    with open(p, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # Re-validate on load: catches hand-edited files with bad values
    return validate_spec(raw)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _validate_component(comp: dict, idx: int) -> dict:
    """Validate a single component spec dict. Returns normalized copy."""
    if not isinstance(comp, dict):
        raise ValueError(f"spec.components[{idx}] must be a dict")

    c = dict(comp)
    name = c.get("name", f"component_{idx}")
    c["name"] = str(name)

    for dim in ("length", "width", "height"):
        if dim not in c:
            raise ValueError(
                f"spec.components[{idx}] ('{name}') missing '{dim}'"
            )
        val = float(c[dim])
        if val <= 0:
            raise ValueError(
                f"spec.components[{idx}].{dim} must be > 0, got {val}"
            )
        c[dim] = val

    c["clearance_mm"] = float(c.get("clearance_mm", 0.3))
    if c["clearance_mm"] < 0:
        raise ValueError(
            f"spec.components[{idx}].clearance_mm must be >= 0, got {c['clearance_mm']}"
        )

    return c


def _validate_feature(feat: dict, idx: int) -> dict:
    """Validate a single feature spec dict. Returns normalized copy."""
    if not isinstance(feat, dict):
        raise ValueError(f"spec.features[{idx}] must be a dict")

    f = dict(feat)
    feat_type = f.get("type", "").lower()
    if feat_type not in _VALID_FEATURE_TYPES:
        raise ValueError(
            f"spec.features[{idx}].type '{feat_type}' not recognized. "
            f"Valid values: {sorted(_VALID_FEATURE_TYPES)}"
        )
    f["type"] = feat_type
    f["name"] = str(f.get("name", f"{feat_type}_{idx}"))
    f["tolerance"] = float(f.get("tolerance", _DEFAULT_TOLERANCE_MM))

    if feat_type == "slot":
        if "width" not in f:
            raise ValueError(f"spec.features[{idx}] (slot '{f['name']}') missing 'width'")
        f["width"] = float(f["width"])
        if f["width"] <= 0:
            raise ValueError(f"spec.features[{idx}].width must be > 0")
        # probe_z: Z height at which to measure the slot width via cross-section.
        # Defaults to half the part height, which the validator will resolve
        # once it loads the geometry — 0.0 here signals "use midpoint".
        f["probe_z"] = float(f.get("probe_z", 0.0))

    elif feat_type == "hole":
        if "diameter" not in f:
            raise ValueError(f"spec.features[{idx}] (hole '{f['name']}') missing 'diameter'")
        f["diameter"] = float(f["diameter"])
        if f["diameter"] <= 0:
            raise ValueError(f"spec.features[{idx}].diameter must be > 0")
        # position is optional — if absent, the validator finds the nearest hole
        if "position" in f:
            pos = f["position"]
            if not isinstance(pos, (list, tuple)) or len(pos) < 2:
                raise ValueError(
                    f"spec.features[{idx}].position must be [x, y] or [x, y, z]"
                )
            f["position"] = [float(v) for v in pos]

    elif feat_type in ("pocket", "rail", "channel"):
        # These are checked by bounding-box clearance rather than exact probing.
        # width and depth are required; height is optional (checked as minimum).
        for dim in ("width", "depth"):
            if dim in f:
                f[dim] = float(f[dim])

    return f
