# Frodo UX Review: SO-DIMM + M.2 Sliding Case v1

**Reviewer:** Frodo (UX)
**Date:** 2026-04-02
**Status:** CONDITIONAL APPROVAL -- bottom tray has 3 open issues, top tray not delivered

---

## Bottom Tray (SO-DIMM carrier) -- CONDITIONAL APPROVAL

### Phase 1: Base Shape -- PASS

- **Outer shell:** 76mm x 136.5mm x 8mm (originally 6mm, revised to 8mm to clear 3.8mm SO-DIMMs)
- **Wall thickness:** 2mm confirmed in XY cross-sections
- **Corner fillets:** 2mm radius on exterior vertical edges
- **T-rails:** Symmetric on both long-axis walls. Stem 2mm wide, 3mm tall. Cap 1.5mm thick, 5mm span.
- **Total envelope with rails:** 76mm x 143.5mm x 8mm

### Phase 2: Internal Features -- 3 ISSUES OPEN

Verified correct:
- 4 SO-DIMM pockets: 32mm outer, 30mm inner at shelf level
- Relief channel: 6mm wide, 1.5mm deep, 66mm long -- suspends edge connector over air
- Key notch tab at 10.8mm offset from center
- End retention tabs at both ends of each pocket
- Detent bumps 0.4mm proud, verified in zoomed cross-section at X=30.5mm
- Total envelope: 76mm x 144.3mm x 8mm

**ISSUE 1 -- BLOCKING: Detent shape is rectangular, not ramped.**
Design study requires hemispherical nub with ramped entry side, steep retention side. Implementation uses `rect()` -- a flat box. Rectangular bumps will bind during slide. Zoomed cross-section at X=30.5mm confirms flat profile. Must be asymmetric ramp.

**ISSUE 2 -- BLOCKING: Shelf wraps all 4 pocket edges.**
Design study requires shelf on two long edges and ONE short edge only. Implementation puts shelf on all four edges. One short end must be open for module insertion. Visible in Z=2.7mm XY section -- inner rectangle is inset symmetrically from outer on all sides.

**ISSUE 3 -- MODERATE: No interior corner fillets.**
Design study requires 2mm minimum fillet on ALL corners (interior and exterior). Only exterior vertical edges are filleted. Interior pocket corners and relief channel corners are sharp. Stress concentrators + print quality degradation.

### Dimension Verification Table

| Feature | Spec | Measured | Status |
|---------|------|----------|--------|
| SO-DIMM L x W x H | 69.6 x 30 x 3.8mm | N/A (component) | Reference |
| Pocket outer width | 32mm | 32.05mm | PASS |
| Pocket inner width (shelf) | 30mm | 30.05mm | PASS |
| Pocket depth | 4mm | 4mm (code) | PASS |
| Relief channel width | 6mm | 6mm (code) | PASS |
| Relief channel depth | 1.5mm | 1.5mm (code) | PASS |
| Wall thickness | 2mm | 2.00mm | PASS |
| T-rail stem | 2mm x 3mm | Visible in section | PASS |
| T-rail cap | 1.5mm x 5mm | Visible in section | PASS |
| Detent proud | 0.4mm | 0.4mm (labeled zoom) | PASS (size), FAIL (shape) |
| Detent ramp profile | asymmetric ramp | rectangular box | FAIL |
| Shelf edges | 3 edges (2 long, 1 short) | 4 edges (all) | FAIL |
| Interior corner fillets | 2mm min | none | FAIL |
| Tray height | 8mm | 8.00mm | PASS |

---

## Top Tray (M.2 holder) -- NOT DELIVERED

Required features for review:

1. Complementary T-rail channel matching bottom tray's T-profile with 0.35mm clearance per side
2. Detent recesses at matching positions (asymmetric profile to match bumps)
3. 3 M.2 2280 pockets: 84mm x 25mm x 2mm deep
4. Edge rails (1mm) contacting only bare PCB border
5. 1.5mm deep relief channel for bottom-side NAND clearance
6. M-key and B+M key accommodation
7. 1.5mm walls between M.2 pockets
8. Total closed envelope ~98 x 80 x 30mm

---

## Design Study Cross-Reference

| Design Study Requirement | Implementation | Verdict |
|--------------------------|---------------|---------|
| PETG, 2mm walls | Correct | PASS |
| T-rail slide, 5 DOF constrained | T-profile present, channel not yet built | PARTIAL |
| 0.35mm/side rail clearance | Cannot verify without top tray | PENDING |
| Hemispherical ramped detent | Rectangular box | FAIL |
| Shelf on 3 edges (2L + 1S) | Shelf on 4 edges | FAIL |
| 2mm fillets ALL corners | Exterior only | FAIL |
| Relief channels suspend connectors | 6mm x 1.5mm channels present | PASS |
| DDR4 key notch tab | Present at correct offset | PASS |
| End retention tabs | Present at both ends | PASS |
| Top tray floor = SO-DIMM retention | Top tray not built | PENDING |
| Print open-face-up, no supports | Geometry compatible | PASS |

---

## Notes

- The 4mm pocket depth (vs 2mm in design study) was my revision. Design study intended the top tray floor to provide top-face retention. The 4mm depth works either way -- module sits fully below rim even without the top tray.
- Relief channel leaves 3mm of solid floor at each pocket end -- sufficient support.
- PETG is NOT ESD-safe -- this is a transport organizer, not a Faraday enclosure. Noted.

---

## Review Status

| Part | Phase | Status |
|------|-------|--------|
| Bottom tray | Phase 1 (base) | APPROVED |
| Bottom tray | Phase 2 (features) | 3 ISSUES OPEN |
| Top tray | Phase 1 (base) | NOT STARTED |
| Top tray | Phase 2 (features) | NOT STARTED |
| Assembly | Fit check | NOT STARTED |
