# Undocumented UE5.7 API quirks — found, diagnosed, fixed

A running log of behaviors that aren't in the official docs, discovered while
building an agent-driven editing pipeline on top of the UE5.7 Python API and
Blueprint editing internals. Kept here because a bug that silently does
nothing is worse than one that throws — several of these fail without any
error at all.

**Screenshot capture queues a frame that may never arrive.**
`take_screenshot()` / `AutomationLibrary.take_high_res_screenshot` schedule a
capture for a future frame. In a synchronous agent-execution context, the
file can be read back before that frame renders — returning a fully black
image, or a stale image from a previous call, with no error raised. Fixed by
switching to a `SceneCaptureComponent2D` with an explicit, synchronous
`capture_scene()` call (see `docs/ARCHITECTURE.md`).

**A `TextureRenderTarget2D` exported as `.png` can silently be an EXR file.**
The default render target format is `RTF_RGBA16F` (HDR). Exporting it with a
`"*.png"` filename still writes an OpenEXR file under the hood — the magic
bytes (`76 2f 31 01`) give it away, but the extension doesn't. Fix: force
`RTF_RGBA8` via `set_editor_property("render_target_format", ...)` before
capturing (direct attribute assignment fails silently as read-only).

**`set_attenuation_radius()` on a point light fails silently.** The radius
stays at the default (1000) with no exception. The working call is
`light_component.set_editor_property("attenuation_radius", value)`.

**`unreal.Color` takes BGRA, not RGBA.** `unreal.Color(r, g, b, a)` compiles
and runs, it just swaps the red and blue channels. Every color-setting
helper in this toolchain routes through a wrapper that does the swap once,
rather than relying on call sites to remember it.

**`sphere_overlap_actors()` needs typed `unreal.Array`, not a Python list.**
Passing `[]` or a Python list for `object_types`/`actors_to_ignore` raises a
`NoneType has no len()` deep inside the binding. It needs
`unreal.Array(unreal.ObjectTypeQuery)` (empty = all types) and
`unreal.Array(unreal.Actor)`. Separately, the function returns `None` (not an
empty list) when nothing overlaps — the most common case on a successful
placement — and an early version of this code let that `None` raise and get
swallowed by a bare `except`, silently disabling the physics-check layer on
every clean placement.

**A `class`-type Blueprint pin can't be set from Python.** Neither
`set_pin_default_value` nor `set_pin_default_object` actually works on a
`class` pin (e.g. `GetAllActorsOfClass.ActorClass`) — `compile_blueprint()`
returns `True` but the graph fails at runtime. Workaround: tag actors at
spawn time (`actor.tags = [unreal.Name("Enemy")]`) and use
`GetAllActorsWithTag` instead, which only needs a string pin.

**`compile_blueprint()` returning `True` doesn't mean the Blueprint runs.**
It can report success on a graph that will still fail when actually entering
PIE (Play In Editor). Any Blueprint-graph change needs an actual PIE run to
confirm, not just a green compile result.

**`BlueprintGraphHelper.add_function_call_node` returns `None` and adds
nothing** — a UE5.7-specific gap. `BlueprintEditingSubsystem.add_function_call_node`
(a different subsystem) does work, and is what `BatchWireGraph`'s
`"function"` node type uses internally.

**Enhanced Input modifiers don't survive a save/reload roundtrip.** Setting
`mapping.set_editor_property("modifiers", [unreal.InputModifierSwizzleAxis()])`
appears to work — reading it back immediately returns the modifier — but the
modifier instances are transient UObjects not owned by the Input Mapping
Context package, so serialization drops them. Reading state back from the
same in-memory object after a `set_editor_property` call is misleading here;
the only real test is reloading the asset from disk
(`EditorAssetLibrary.reload_asset()` + `load_asset()`) and checking again.
Workaround used for movement input that would otherwise need an axis
swizzle: read raw key state (`PlayerController.IsInputKeyDown(...)`) in Tick
instead of relying on the modifier.

**Blueprint redirectors can defeat `load_blueprint_class()` silently.** A
class path pointing through an old redirector loads fine with `load_class()`
or `load_asset()` but returns nothing usable through
`load_blueprint_class()`. `load_bp_class()` in this toolchain tries three
strategies in order (direct blueprint-class load, `load_class` for
`/Script/...` paths, then an auto-suffixed `_C` class load) rather than
assuming any single one is reliable.

**A floor-snap that lands exactly on the floor can register as an overlap
with the floor itself.** Placing an actor at precisely `floor_z +
actor_radius` — zero clearance — was sometimes detected as a collision with
the ground plane, failing the physics-check layer on an otherwise valid
placement. Fixed with a small explicit clearance margin above the computed
floor height.

**`Navigation.RebuildNavigation` (console command) doesn't fully rebuild the
NavMesh** after a geometry change — only the in-editor `Build > Build Paths`
action does. There's no scripted equivalent used here; it's called out
explicitly in the workflow as a manual step.
