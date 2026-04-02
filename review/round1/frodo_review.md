# Round 1: Frodo UX Review -- Cable Organizer

## Request

"I need a cable organizer that holds 3 USB-C cables. Make it compact. PLA. Something that keeps the cable ends from sliding off the back when I unplug them."

Clarifications given: 4-5mm standard cables, straight connectors, vertical retention slots (cable drops in from top, connector head catches), 50mm depth is fine, no color preference.

## What I Got

An open-top trough tray -- three parallel channels milled into a rectangular block. No retention feature. Cables sit in troughs and can lift straight out. This is functionally an ice cube tray, not a cable clip.

The Ent did address my depth feedback (55mm -> 30mm) and the proportions improved. But the core design intent -- retention slots -- was never implemented across two iterations.

---

## Checkpoint Experience

### Phase 0 (Requirements): Good

The Ent asked 5 targeted clarifying questions before building. Cable diameter, connector style, slot orientation, depth, material. This was genuinely useful -- it surfaced the "vertical slot vs. open trough" distinction early. I clearly answered "vertical slots where the cable drops in from the top and the connector head stops it from pulling through."

**Verdict:** Phase 0 worked as designed. No changes needed.

### Phases 1-3: Skipped

The Ent jumped from requirements gathering straight to a finished part with STL/STEP exports and a parameter table. I never saw a Phase 1 base shape checkpoint or a Phase 2 features checkpoint. The first render I saw was the "final" product.

This is exactly the failure mode the checkpoint workflow is supposed to prevent. If I'd seen a Phase 1 rough block, I could have said "this needs to be taller" before slots were cut. If I'd seen Phase 2 with the trough features, I could have said "these aren't retention slots" before print optimization was applied.

**Verdict:** The checkpoint workflow exists in SKILL.md but was not followed. The Ent's own report mentions Phase 1-3 internally, but the user (me) was never shown intermediate checkpoints for approval.

### Revision Cycle

After I rejected the final, the Ent addressed secondary issues (depth, render clarity) but not the primary issue (wrong slot type). After two rounds of feedback saying "these are troughs, not retention slots," the geometry was unchanged in its fundamental approach.

**Verdict:** The revision loop works mechanically (Ent can regenerate and re-render) but the Ent didn't close on the most important feedback. SKILL.md doesn't give guidance on how to prioritize user corrections.

---

## Validator Assessment

The Ent's own report documents 4 bugs found during the build:

1. **validate_geometry.py Unicode crash** -- `>=` symbol crashes Windows console. Real bug, blocks all validation on Windows.
2. **check_printability.py wall thickness false positive** -- open-slot geometry triggers incorrect wall measurements. Real bug.
3. **SKILL.md slot vs. pocket confusion** -- spec vocabulary doesn't match conversational vocabulary. Real documentation gap.
4. **SKILL.md phased spec ambiguity** -- unclear whether spec describes current-phase geometry or final-part geometry. Real documentation gap.

These are all legitimate findings. But none of them would have caught the actual problem: the part doesn't match what the user asked for. The validators check that geometry matches the spec, and the spec matches the geometry -- but nobody checks that the spec matches the user's request. That's what the checkpoints are for, and they were skipped.

**Verdict:** Validators are necessary but not sufficient. They catch "did you build what you said you'd build?" but not "did you understand what the user wanted?" The checkpoint workflow is the only defense against misunderstanding, and it wasn't used.

---

## What the Workflow Got Right

1. **Phase 0 requirements gathering** -- structured, thorough, surfaced the right questions.
2. **Parameter table at delivery** -- clear, well-formatted, makes tweaks easy to request.
3. **Validator infrastructure** -- finding 4 real bugs in a single round proves the validators add value.
4. **Ent report format** -- the ent_report.md is well-structured and honest about bugs found.

## What Was Missing or Confusing

1. **Checkpoint enforcement** -- SKILL.md says "NEVER batch the entire model" and "show the preview to the user" at each phase, but nothing prevents the designer from skipping straight to final. The instruction is there; the compliance mechanism is not.
2. **Design intent validation** -- no tool checks "does the spec match the user's words?" The user said "retention slots" and the designer built open troughs. Both validators passed.
3. **Revision prioritization** -- when the user gives multiple corrections, SKILL.md doesn't say "fix the biggest functional issue first." The Ent fixed depth and render angles but not the fundamental geometry mismatch.
4. **Retention/clip geometry guidance** -- SKILL.md has no examples or guidance for snap-fit, press-fit, or retention features. These are common in cable organizers, phone holders, and clip designs. A "common feature patterns" section would help.

---

## Specific SKILL.md Changes I'd Recommend

### 1. Add checkpoint gate language

After each phase description, add explicit gate text:

> **GATE: Do not proceed to Phase N+1 until the user explicitly approves Phase N.** If the user has not responded, wait. If the user rejects, iterate on the current phase. Showing a "final" part without intermediate approvals violates the workflow.

### 2. Add a "Common Feature Patterns" section

Include sketches or descriptions of:
- **Retention slots** (narrow opening, wider pocket below -- for cable clips, card holders)
- **Snap-fit clips** (cantilever beam with catch)
- **Press-fit holes** (interference fit sizing)
- **Screw bosses** (hole + surrounding material for self-tapping screws)

This gives the designer vocabulary to match against user descriptions.

### 3. Add revision priority guidance

> When the user provides multiple corrections, address **functional mismatches first** (wrong feature type, missing features, incorrect dimensions for interfacing parts), then **aesthetic or proportion issues** (depth, fillet radius, chamfer size). A part with the right features at the wrong depth is closer to done than a part with the wrong features at the right depth.

### 4. Add a "spec vs. user intent" self-check

Before writing the spec, the designer should re-read the user's requirements and confirm each spec feature maps to a stated requirement. Add to Phase 1:

> **Before writing the spec:** Re-read the user's requirements from Phase 0. For each feature in the spec, identify which user requirement it satisfies. If a user requirement has no corresponding spec feature, the spec is incomplete. If a spec feature has no corresponding user requirement, question whether it belongs.

### 5. Clarify phased spec scope (Bug 4 from Ent report)

Add to Phase 1:

> **Spec scope:** The spec describes the geometry of the CURRENT phase export, not the final part. Phase 1 spec should only declare features present in Phase 1 geometry. Update the spec at each phase to add new features as they're built.

### 6. Add slot vs. pocket decision guide (Bug 3 from Ent report)

Add to the spec capture example:

> **Feature type guide:**
> - `"slot"` -- a through-cut or open channel. Validator probes for gap width.
> - `"pocket"` -- a closed cavity or recess. Validator checks depth and floor.
> - `"retention_slot"` -- a slot with a narrow opening and wider interior. Validator checks both opening width and pocket width.
> - When in doubt, describe the cross-section shape, not the conversational name.

---

## Summary Verdict

The SKILL.md workflow is well-designed in theory. Phase 0 works. The validators find real bugs. The parameter table is useful. But the core value proposition -- "mistakes are caught early rather than discovered at the slicer" -- failed in practice because the checkpoint gates were advisory, not enforced. The designer skipped straight to a finished part, built the wrong feature type, and two rounds of feedback didn't fix the fundamental mismatch.

The highest-impact change is making checkpoint gates explicit and mandatory. Everything else is refinement.
