# cad-skill — Parametric 3D-Printable Part Design for Claude Code

A skill that teaches Claude Code to design 3D-printable parts using CadQuery, with automated validation and self-checking.

## What It Does

Turn conversational descriptions into parametric CadQuery scripts that produce print-ready STEP/STL files. The skill uses an interactive checkpoint workflow with automated geometry and printability validation — catching mistakes before the user sees them.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  SKILL.md — Workflow instructions for Claude Code   │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Phase 0: Requirements ──► Phase 1: Base Shape      │
│       │                        │                    │
│       │                   ┌────┴────┐               │
│       │                   │ Spec    │               │
│       │                   │ Capture │               │
│       │                   └────┬────┘               │
│       │                        │                    │
│  Phase 2: Features ──► Phase 3: Print Optimization  │
│       │                        │                    │
│       └────────┬───────────────┘                    │
│                │                                    │
│    ┌───────────┴───────────┐                        │
│    │  Post-Export Checks   │                        │
│    ├───────────────────────┤                        │
│    │ validate_geometry.py  │  Intent vs. reality    │
│    │ check_printability.py │  FDM constraints       │
│    │ render_cross_sections │  Dimensioned slices    │
│    │ render_preview.py     │  4-view visual         │
│    └───────────────────────┘                        │
└─────────────────────────────────────────────────────┘
```

## Validation Pipeline

Two layers of automated checking remove the user from the error-catching loop:

### Layer 1 — Construction-Time (during build)
- `cq_debug_helpers.py` — catches silent boolean failures, workplane drift, feature overflow
- Used inline in CadQuery scripts via `verify_boolean()` and `verify_feature_bounds()`

### Layer 2 — Post-Export (after STEP export)
- `validate_geometry.py` — compares exported geometry to design spec (dimensions, slot widths, hole diameters, wall thickness)
- `check_printability.py` — checks FDM constraints (flat bottom, overhangs, bridge spans, min feature size)
- `render_cross_sections.py` — dimensioned raster cross-sections at critical feature locations

## File Structure

```
cad-skill/
├── SKILL.md                          # Workflow instructions (Claude reads this)
├── CADQUERY_REFERENCE.md             # CadQuery API patterns and gotchas
├── requirements.txt                  # Python dependencies
├── lib/
│   ├── spec_format.py                # Intent capture — JSON spec schema
│   └── cq_text_utils.py              # Safe text placement utilities
├── scripts/
│   ├── validate_geometry.py          # Post-export geometry validator
│   ├── check_printability.py         # FDM printability checker
│   ├── render_cross_sections.py      # Dimensioned cross-section renderer
│   ├── render_preview.py             # Multi-view 3D preview renderer
│   ├── cq_debug_helpers.py           # Construction-time debug utilities
│   └── setup_env.sh                  # Environment setup
├── tests/                            # Test STEP files and specs
│   ├── good_box.step / .spec.json
│   ├── broken_box.step / .spec.json
│   └── good_solid.step / .spec.json
└── review/                           # Design round test logs
    └── round1/
        ├── ent_report.md             # Builder's workflow report
        └── frodo_review.md           # UX review and recommendations
```

## Setup

```bash
bash ~/.claude/skills/cad-skill/scripts/setup_env.sh
```

Requires Python 3.10+. Installs CadQuery, trimesh, matplotlib, scipy, numpy, pillow.

## Known Issues

See [Issues](../../issues) for the current backlog. Key items from Round 1 testing:
- Wall thickness false positive on open-slot geometry (#2)
- Checkpoint gates need enforcement language (#5)
- Slot vs. pocket spec type needs decision guide (#3)

## Development

This skill was built and reviewed using the [Lord of the Code](https://github.com/thereprocase/lord-of-the-code) framework — a multi-agent code review system using Middle-earth characters mapped to Claude model tiers.

The validation pipeline was designed by Gandalf (architecture), built by Sauron (geometry validator, cross-sections) and Legolas (printability checker), UX-tested by Frodo, and bug-hunted by Uruk-Hai swarms.
