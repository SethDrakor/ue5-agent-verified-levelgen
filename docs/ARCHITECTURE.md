# Architecture

## Layers

**Agent interface.** Two entry points exist for driving the editor: an
in-editor Slate panel backed by the Anthropic API (for standalone use without
an external agent session), and an MCP bridge that lets an external agent
(Claude Code, or any MCP-capable agent) call into the editor's embedded
Python interpreter directly. Both ultimately execute Python inside
`IPythonScriptPlugin`. The in-editor panel can optionally attach a screenshot
of the current viewport (at the exact camera pose the panel's own Python
helper reports) to the next outgoing message, reusing the same
`capture_reference_screenshot()` pipeline the rest of this toolchain relies
on rather than a separate C++ capture path. This is off by default and gated
behind its own checkbox: the panel's Anthropic key is billed independently
of any agent subscription driving the MCP bridge, so vision is opt-in rather
than attached to every message. The capture-and-attach code path itself
compiles and runs end-to-end (verified by exercising the underlying Python
helper directly); the actual round trip to the API with an image attached
has not been exercised with a real request, so "the wiring exists" and "the
model has been confirmed to see the screenshot" are two different claims —
only the first one currently holds.

**RoomGenerator plugin (C++, Editor Subsystem).**
- `RoomGeneratorSubsystem` — procedural room/corridor geometry generation
  (`generate_room`, `generate_corridor`, `spawn_scaled_cube`).
- `BlueprintEditingSubsystem` — exposes `batch_wire_graph()`, a JSON-driven
  DSL that builds an entire Blueprint graph (nodes + connections) in one
  call, instead of the 20+ individual API calls normally required to add
  nodes and wire pins one at a time.
- `VignetteManager` — a small runtime actor that polls enemy blackboards to
  drive a gameplay effect (a red vignette when the player is seen but not
  lit), included as an example of a runtime (not editor-only) subsystem.

**Python toolchain (~4,500 lines).**
- `ue5_utils.py` — actor spawning/placement helpers, the `BPGraph` DSL
  (syntactic sugar over `batch_wire_graph`), `safe_write`/`safe_append`
  (verify-after-write helpers), `safe_modify_plugin()` (anti-regression
  wrapper, see below), and `capture_reference_screenshot()`.
- `verify_level.py` — automatic level verification (`run_verify`, `fix_all`):
  actor/geometry intersection, missing floor under an actor, missing
  gameplay-critical actors, misconfigured lights, missing tags, duplicate
  post-process volumes, unbuilt NavMesh.
- `test_suite.py` — anti-regression suite covering the plugin's C++
  subsystems and the Python toolchain itself.
- `horror_presets.py` — reusable room/corridor/atmosphere templates and a
  small plan executor (`execute_level_plan`) that chains rooms and corridors
  from a structured JSON plan. Chaining defaults to a single axis (each step
  starts where the previous one ended), but a step can instead declare an
  `"anchor"` — the name of an already-built step in the same plan plus a
  side (`east`/`west`/`north`/`south`) — to branch off that step's edge on
  the perpendicular axis instead of continuing the main sequence. This turns
  a single `execute_level_plan()` call into a real (if still simple) 2D
  layout tool: a corridor can turn a corner, or a room can grow a side
  branch, without a second top-level call and without disturbing the main
  chain's position bookkeeping. The bounds/anchor math
  (`_compute_step_bounds`, `_resolve_anchor`) is deliberately factored out as
  pure functions with no engine calls, specifically so it can be unit-tested
  without ever touching a real level — the alternative (calling the real
  room-building functions to test geometry math) would mean every test run
  mutates the currently open level's actual lighting/post-process state,
  which nothing in this codebase wants as a side effect of running the test
  suite. The orchestration layer above that math (does the executor call the
  right builder for the right step, in the right order, with the right
  registered bounds) is covered separately by an integration test that
  temporarily substitutes fake builder functions, so the full call path
  through `execute_level_plan()` is exercised without generating any real
  geometry.

**Standalone QA/CI tooling (`Tools/`, ~800 lines, run outside the editor).**
- `analyze_screenshot.py` — numeric perceptual check on an exported
  screenshot (mean luminance, % of near-black pixels, brightest-point
  position) using PIL/numpy, which the embedded UE5 Python interpreter
  doesn't have.
- `qc_gate.py` — merges `verify_level.py`'s structural report with
  `analyze_screenshot.py`'s numeric read into one PASS/FAIL verdict per
  zone, and maintains a persistent manifest (`Saved/QC/qc_manifest.json`)
  tracking, per zone, whether it has ever had both a passing verdict *and*
  a human/vision confirmation that the screenshot was actually looked at —
  closing the gap where a structurally clean zone could still be declared
  "done" without anyone having looked at it.
- `visual_diff.py` — SSIM-based visual regression against a promoted
  per-zone baseline screenshot (see the README for the reliability
  rationale).

**Behavioral playtesting (`playtest_agent.py`, applied on top of the toolchain
above — project-specific, unlike the generic files listed above).** Every
tool up to this point judges a *static* level state — geometry, materials,
a screenshot. This module instead drives the actual player character through
a live PIE session and journals timestamped events by reading real game
state, closing the gap between "the level passed structural checks" and "the
level actually plays correctly." Architecture notes that mattered in
practice:
- PIE runs in real time between MCP calls, not during them. The player is
  piloted by a callback registered with
  `unreal.register_slate_post_tick_callback()`, which keeps running on its
  own between one agent call and the next — no polling loop needed on the
  agent side.
- Waypoint-to-waypoint movement is routed through
  `NavigationSystemV1.find_path_to_location_synchronously()` rather than a
  straight line, with a fallback to the straight line if no path is found
  (`is_valid` can be `True` with an empty `path_points`, which the code
  guards against explicitly) and an automatic replan whenever the player is
  detected as stuck.
- Enemy Blackboard state (`CanSeePlayer?`, `IsIlluminated`, ...) is
  re-queried by scanning live actors every tick rather than caching a
  reference across ticks — an intermittent Python binding bug
  (`SystemLibrary.is_valid()` raising `TypeError` on a cached actor
  reference between ticks) made caching unreliable enough to just avoid.
- Real key presses (for pickups, switches, doors) are simulated through a
  small C++ addition (`RoomGeneratorSubsystem::SimulateKeyPress`,
  `PC->InputKey(FInputKeyParams)`), since the Python API only exposes
  read-only input queries (`is_input_key_down`, `was_input_key_just_pressed`)
  with nothing to inject a key state.
- An "invincible" mode isolates a navigation/ambiance test from enemy
  combat behavior by toggling `generate_overlap_events` on the specific
  collision component that triggers a capture, on the live actor instance —
  no Blueprint edit, fully reversible at the end of the run.

This module is the one piece of the toolchain that is *not* generic — it
references this project's specific Blueprint paths and Blackboard key names.
It's included anyway because it's also the one piece that has caught a real
gameplay bug rather than a geometry/tooling one: a playtest run showed zero
enemy detections across the whole level, which traced back to
`AIPerceptionComponent.auto_activate = false` on the enemy Blueprint's
component template — invisible to every structural check in this repo, only
found by an agent actually playing the level and noticing nothing reacted.

## The placement problem, in three layers

Naively spawning an actor at a chosen (x, y) coordinate risks it landing
inside a wall, floating above the floor, or overlapping another actor. There
is no "correct" z without knowing the geometry underneath. `safe_place()`
(used by `safe_spawn_enemy()`/`safe_spawn()`) resolves this in three passes:

1. **Floor snap** — a downward raycast from a safe starting height (kept
   below the ceiling) finds the real floor z. `HitResult` in the UE5.7
   Python binding doesn't expose `impact_point`; the distance value in the
   returned tuple is used to compute it instead.
2. **Occupancy grid (fast pre-filter)** — a 2D grid built once from existing
   wall geometry (`build_occupancy_grid_from_level()`), used to reject an
   obviously bad position cheaply before doing a physics query. Floors and
   ceilings are excluded from the grid by filtering on bounding-box height,
   since their large flat bounding boxes otherwise register as false-positive
   walls everywhere.
3. **Real physics check** — `sphere_overlap_actors()` confirms there is no
   actual collision at the resolved position. If one is found, the nearest
   free position is used instead.

An actor is only ever placed at a position that passed all three checks — it
is never committed "as attempted."

## Anti-regression as a first-class step, not a suggestion

Early on, "run the test suite before and after a plugin change" was a written
convention with nothing enforcing it — an agent could skip it entirely.
`safe_modify_plugin()` makes it structural: it snapshots a test-suite
baseline, runs the caller's modification, re-runs the suite, and diffs
test-by-test (not just the aggregate score) — a test that passed in the
baseline and fails afterward raises an exception instead of silently slipping
through. `BPGraph.wire_and_compile()` (the main path for wiring a new
Blueprint graph) calls this automatically, so the common case needs no
explicit wrapping.

## Level-design workflow (enforced order)

1. Generate geometry → capture a screenshot from a fixed, chosen camera pose
   → read it back before continuing.
2. Place enemies via `safe_spawn_enemy()` (never a raw `spawn()`) → screenshot
   again from near the placed enemy.
3. Add lights via `point_light()` (a thin wrapper that sets
   `attenuation_radius` correctly — see `docs/KNOWN_ISSUES.md`).
4. Run `fix_all()` then `run_verify()`. Only continue to `save()` if it comes
   back clean.
5. Rebuild the NavMesh (`Build > Build Paths` — the console command
   `Navigation.RebuildNavigation` is insufficient) and re-verify.

## Reliable screenshots

Standard UE5 viewport/high-res screenshots (`take_screenshot()` /
`AutomationLibrary.take_high_res_screenshot`) are queued for a future frame
that, in an agent execution context (an MCP bridge calling into the editor
synchronously), sometimes never arrives before the file is read back — this
produced fully black or stale images from a previous call, diagnosed across
several sessions of otherwise-correct-looking Python. The fix:
`capture_reference_screenshot()` renders through a `SceneCaptureComponent2D`
with `capture_every_frame=True` and an explicit synchronous `capture_scene()`
call, exported via `RenderingLibrary.export_render_target()` — with a
deliberately chosen, reproducible camera pose rather than whatever position
the editor viewport happened to be left at.
