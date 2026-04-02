"""
CadQuery Text Utilities — safe text placement that avoids workplane origin drift.

Usage:
    from cq_text_utils import place_text, measure_text_bbox, auto_font_size
"""
import cadquery as cq
import math

# Cache for measured text bounding box ratios
_bbox_cache = {}


def measure_text_bbox(text, font="Arial", ref_size=10.0):
    """Measure actual CadQuery text bounding box. Returns (width_ratio, height_ratio).
    Ratios are bbox_dimension / font_size. Multiply by desired font_size to get actual dims.
    Results are cached."""
    key = (text, font, ref_size)
    if key in _bbox_cache:
        return _bbox_cache[key]

    solid = cq.Workplane("XY").text(text, ref_size, 1.0, combine=False, font=font)
    bb = solid.val().BoundingBox()
    w_ratio = bb.xlen / ref_size
    h_ratio = bb.ylen / ref_size
    _bbox_cache[key] = (w_ratio, h_ratio)
    return w_ratio, h_ratio


def auto_font_size(text, avail_width, avail_height, font="Arial",
                   rotation_deg=0, max_size=12.0, margin=4.0):
    """Compute largest font size that fits text within available dimensions.
    avail_width/height are the body area dimensions BEFORE rotation.
    rotation_deg is the text rotation angle."""
    if not text:
        raise ValueError("Cannot auto-size empty text string")
    w_ratio, h_ratio = measure_text_bbox(text, font)

    # After rotation, text width maps to one axis and height to the other
    angle = math.radians(abs(rotation_deg))
    cos_a = abs(math.cos(angle))
    sin_a = abs(math.sin(angle))

    # Effective ratios after rotation
    eff_w = w_ratio * cos_a + h_ratio * sin_a  # maps to avail_width
    eff_h = w_ratio * sin_a + h_ratio * cos_a  # maps to avail_height

    usable_w = avail_width - margin
    usable_h = avail_height - margin

    max_by_w = usable_w / eff_w if eff_w > 0 else max_size
    max_by_h = usable_h / eff_h if eff_h > 0 else max_size

    return max(0.5, min(max_size, max_by_w, max_by_h))


def place_text(body, text, x, y, z, rotation_deg=0, font_size=None,
               mode="deboss", depth=0.6, font="Arial",
               avail_width=None, avail_height=None, clip_body=None):
    """Place text on a body at absolute global coordinates using a fresh workplane.

    Args:
        body: CadQuery Workplane object (the solid to modify)
        text: Label string
        x, y, z: Global position for text center
        rotation_deg: Rotation around Z axis (90 = vertical text)
        font_size: Font size in mm (None = auto-size using avail_width/avail_height)
        mode: "deboss" (cut into surface) or "emboss" (raised above surface)
        depth: Cut depth (deboss) or raise height (emboss) in mm
        font: Font name
        avail_width: Available width for auto-sizing
        avail_height: Available height for auto-sizing
        clip_body: For emboss mode, intersect result with this to clip overflow

    Returns:
        Modified body with text applied
    """
    if depth <= 0:
        raise ValueError(f"Text depth must be positive, got {depth}")
    if font_size is None:
        if avail_width is None or avail_height is None:
            raise ValueError("Must provide avail_width and avail_height for auto-sizing")
        font_size = auto_font_size(text, avail_width, avail_height, font, rotation_deg)

    if font_size <= 0:
        raise ValueError(f"Font size must be positive, got {font_size}")

    if mode == "deboss":
        text_solid = (
            cq.Workplane("XY")
            .transformed(offset=(x, y, z), rotate=(0, 0, rotation_deg))
            .text(text, font_size, -depth, font=font)
        )
        return body.cut(text_solid)

    elif mode == "emboss":
        text_solid = (
            cq.Workplane("XY")
            .transformed(offset=(x, y, z), rotate=(0, 0, rotation_deg))
            .text(text, font_size, depth, font=font)
        )
        result = body.union(text_solid)
        if clip_body is not None:
            result = result.intersect(clip_body)
        return result

    else:
        raise ValueError(f"mode must be 'deboss' or 'emboss', got '{mode}'")
