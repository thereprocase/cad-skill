#!/usr/bin/env python3
"""
test_validators.py — Generate good and bad test parts for validator smoke testing.

Generates:
1. A GOOD part — 60x40x25mm box with 2mm walls, 5mm slot, 4mm hole, flat bottom
2. A BAD part — deliberately broken: 0.8mm wall, 4.7mm slot, 50° overhang, 25mm bridge

Exports both as STEP files with .spec.json sidecar files.
"""

import sys
from pathlib import Path

# Add parent/lib to path for spec_format import
_SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SKILL_DIR / "lib"))

from spec_format import write_spec
import cadquery as cq
from cadquery import exporters


def create_good_part():
    """
    Create a GOOD test part:
    - 60x40x25mm bounding box
    - 2mm walls
    - 5mm slot through the middle (width exactly 5mm)
    - 4mm diameter hole
    - Flat bottom for bed adhesion
    """

    spec = {
        "part_name": "Good Test Part",
        "overall_dimensions": {
            "width": 60.0,
            "depth": 40.0,
            "height": 25.0,
            "tolerance": 0.3,
        },
        "min_wall_mm": 2.0,
        "material": "PLA",
        "features": [
            {
                "type": "slot",
                "name": "center slot",
                "width": 5.0,
                "probe_z": 12.5,  # middle height
                "tolerance": 0.3,
            },
            {
                "type": "hole",
                "name": "mounting hole",
                "diameter": 4.0,
                "position": [30.0, 20.0],
            },
        ],
    }

    # Build the part in CadQuery
    # Start with a solid box
    part = (
        cq.Workplane("XY")
        .box(60, 40, 25)
    )

    # Cut a slot through the center: 5mm wide, spans the full depth, goes through height
    # Slot positioned at Y center, spanning X direction
    # Use rect + cutThruAll to create the slot
    part = (
        part
        .faces(">Z")  # top face
        .workplane()
        .center(0, 0)  # center of the top face
        .rect(60, 5.0)  # slot spans 60mm X, 5mm wide in Y direction
        .cutThruAll()
    )

    # Cut a hole: 4mm diameter at position (30, 20)
    part = (
        part
        .faces(">Z")
        .workplane()
        .center(0, 0)
        .moveTo(30 - 30, 20 - 20)  # offset to part center
        .hole(4.0)  # 4mm diameter hole
    )

    return part, spec


def create_bad_part():
    """
    Create a BAD test part with deliberate failures:
    - One wall at 0.8mm (below 1.2mm minimum)
    - Slot width 4.7mm instead of 5.0mm
    - 50° overhang (above 45° threshold)
    - 25mm bridge span (above 20mm threshold)
    """

    spec = {
        "part_name": "Bad Test Part",
        "overall_dimensions": {
            "width": 60.0,
            "depth": 40.0,
            "height": 25.0,
            "tolerance": 0.3,
        },
        "min_wall_mm": 1.2,
        "material": "PLA",
        "max_overhang_angle_deg": 45.0,
        "max_bridge_span_mm": 20.0,
        "features": [
            {
                "type": "slot",
                "name": "narrow slot",
                "width": 4.7,  # Under the nominal 5.0mm
                "probe_z": 12.5,
                "tolerance": 0.3,
            },
        ],
    }

    # Start with the base box
    # Main box: 60x40x25
    part = (
        cq.Workplane("XY")
        .box(60, 40, 25)
    )

    # Cut the slot (4.7mm wide instead of 5.0mm)
    part = (
        part
        .faces(">Z")
        .workplane()
        .rect(60, 4.7)  # 60mm X, 4.7mm wide slot (under-sized)
        .cutThruAll()
    )

    # Add a 50° overhang feature on top: a thin lip extending horizontally
    # Create a wedge-like shape that overhangs at ~50°
    part = (
        part
        .faces(">Z")
        .workplane()
        .center(0, 0)
        .moveTo(0, -17)  # position at edge
        .rect(20, 1)  # small rectangular pad
        .extrude(4)  # extrude up 4mm
    )

    # Create a horizontal surface near the top with a 25mm gap (bridge span)
    # Add a thin platform at height ~20mm that spans 25mm with nothing below it
    part = (
        part
        .faces(">Z")
        .workplane(offset=-7)  # 7mm down from top
        .center(0, 0)
        .moveTo(20, 0)  # position the bridge on one side
        .rect(25, 2)  # 25mm long, 2mm wide (the bridge span)
        .extrude(1)  # extrude 1mm up
    )

    return part, spec


def export_parts():
    """Generate, export, and write spec files for both parts."""

    output_dir = Path(__file__).parent

    print("Generating GOOD part...")
    good_part, good_spec = create_good_part()
    good_step = output_dir / "test_good.step"
    exporters.export(good_part, str(good_step))
    write_spec(good_spec, str(good_step))
    print(f"  Exported: {good_step}")
    print(f"  Spec: {good_step.with_suffix('.spec.json')}")

    print("\nGenerating BAD part...")
    bad_part, bad_spec = create_bad_part()
    bad_step = output_dir / "test_bad.step"
    exporters.export(bad_part, str(bad_step))
    write_spec(bad_spec, str(bad_step))
    print(f"  Exported: {bad_step}")
    print(f"  Spec: {bad_step.with_suffix('.spec.json')}")

    return good_step, bad_step


if __name__ == "__main__":
    export_parts()
    print("\nTest parts generated successfully.")
