# Architecture

## Layers

**Agent interface.** Two entry points exist for driving the editor: an
in-editor Slate panel backed by the Anthropic API (for standalone use without
an external agent session), and an MCP bridge that lets an external agent
(Claude Code, or any MCP-capable agent) call into the editor's embedded
Python interpreter directly. Both ultimately execute Python inside
`IPythonScriptPlugin`.

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
  along an axis from a structured JSON plan.

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
