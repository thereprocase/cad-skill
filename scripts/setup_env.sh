#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# setup_env.sh — Set up the CadQuery environment for cad-skill
# Run once: bash ~/.claude/skills/cad-skill/scripts/setup_env.sh
# Uses pip + system Python — no conda required.
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  CAD Skill — Environment Setup                         ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ---- Step 1: Check Python ----
if ! command -v python &>/dev/null && ! command -v python3 &>/dev/null; then
    echo "ERROR: Python not found. Install Python 3.10+ and ensure it is on your PATH."
    exit 1
fi

PYTHON=$(command -v python || command -v python3)
PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "[1/4] Using Python $PY_VERSION at $PYTHON"
"$PYTHON" -c "import sys; assert sys.version_info >= (3,10), f'Python 3.10+ required, got {sys.version_info.major}.{sys.version_info.minor}'" || { echo "ERROR: Python 3.10 or later is required."; exit 1; }

# ---- Step 2: Install packages ----
echo "[2/4] Installing packages via pip..."
"$PYTHON" -m pip install --quiet --upgrade \
    cadquery \
    trimesh \
    numpy \
    matplotlib \
    pillow \
    scipy
echo "    ✓ Packages installed"

# ---- Step 3: Verify installation ----
echo "[3/4] Verifying installation..."
"$PYTHON" -c "
import cadquery as cq
import trimesh
import numpy
print(f'    CadQuery:  OK')
print(f'    trimesh:   {trimesh.__version__}')
print(f'    numpy:     {numpy.__version__}')

import tempfile, os
tmp = tempfile.mktemp(suffix='.stl')
result = cq.Workplane('XY').box(10, 10, 10)
cq.exporters.export(result, tmp)
mesh = trimesh.load(tmp)
assert mesh.is_watertight, 'Test mesh is not watertight!'
print('    Smoke test: OK')
os.remove(tmp)
"

# ---- Step 4: Summary ----
echo "[4/4] Setup complete!"
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Ready to use!                                         ║"
echo "║                                                        ║"
echo "║  Run CadQuery scripts with:                            ║"
echo "║    python script.py                                    ║"
echo "║                                                        ║"
echo "║  Render preview with:                                  ║"
echo "║    python $SKILL_DIR/scripts/render_preview.py \\"
echo "║      part.stl preview.png                              ║"
echo "║                                                        ║"
echo "║  Skill files:                                          ║"
echo "║    $SKILL_DIR/SKILL.md                                 ║"
echo "║    $SKILL_DIR/CADQUERY_REFERENCE.md                    ║"
echo "╚══════════════════════════════════════════════════════════╝"
