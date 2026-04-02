# Frodo Review — Round 3: Wall-Mount Headphone Hook

## Verdict: APPROVED

## Phase 1 (Base Shape)
- Backplate 40x80x4mm with 3mm corner fillets. Arm extends 60mm from wall face, 18mm wide, originally 8mm thick.
- Tip upturn: last 20mm rises 8mm — provides headband retention.
- Proportions looked right for a headphone hook. 60mm reach gives clearance from wall.
- Suggested bumping arm thickness to 10mm for stiffness — Ent accepted.

## Phase 2 (Features)
- Arm thickness increased to 10mm. ~2x bending stiffness improvement.
- Two M4 countersunk screw holes added: 4.3mm through-hole, 8.5mm x 2.4mm countersink.
- Holes at Z=20 and Z=60 (40mm apart, 20mm from each edge) — well-balanced for load.
- Countersink on wall face for flush screw heads.
- Validators 6/6 PASS. Bug 10 fixed (duplicate hole detection with identical diameters at same XY).

## Phase 3 (Print Optimization)
- Structural gusset at arm-to-backplate junction: 12x12mm triangular profile, full arm width.
- Clearly visible in right view and perspective renders.
- Overhang percentage dropped 11.4% to 9.2% — gusset fills the junction underhang.
- 0.5mm bottom chamfer on backplate Z=0 edge for elephant's foot.
- Print orientation: backplate face on bed, arm vertical. No supports needed.
- Validators all PASS.

## UX Assessment
- Hook reach (60mm) provides enough clearance for most over-ear headphones to hang without touching the wall.
- 10mm thick arm with gusset reinforcement should handle headphones up to 400g+ without flex concerns.
- 18mm arm width fits any headband — not so wide it looks chunky, not so narrow it creates pressure points.
- 8mm tip upturn is enough retention to keep headphones from sliding off during normal use.
- Two-screw mount with 40mm spacing gives stable mounting — won't pivot or wobble.
- Countersunk screws sit flush — backplate lies flat against wall.
- Print orientation puts arm layers parallel to load direction — optimal for FDM tensile strength along the arm.

## Process Issues

### Issue 1: Incomplete spec — no features or components declared
The spec for this round had empty features and components arrays. The two M4 screw holes should have been declared as type "hole" features in the spec. This means the Ent skipped proper spec capture for the most important measurable features on the part. The validator still confirmed the holes via geometry probing, but the spec should have driven that check, not ad-hoc queries. Without spec'd features, the validation workflow is running on luck rather than intent.

### Issue 2: No cross-sections rendered
Zero cross-section PNGs were generated for Round 3. The cross-section renderer had nothing to cut against because the spec declared no features or components. I reviewed the part from the 4-view preview only and relied on the validator numbers for hole confirmation. For a part with through-holes and countersinks, a YZ section through the screw axis would have been the definitive geometry check — and it never happened. The renderer should have a fallback for featureless specs (e.g., auto-generate sections at 25/50/75% of each axis) so this gap doesn't silently pass review again.

## Bugs Found During Round 3
- Bug 10: validate_geometry.py hole finder returned same hole twice when two identical-diameter holes shared the same XY position at different Z. Fixed with Z tiebreaker.
