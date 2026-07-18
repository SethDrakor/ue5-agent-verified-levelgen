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

**A physics-overlap check applied uniformly to all "gameplay" actors produces
false positives on actors that are supposed to touch furniture.** A pickup
resting on a table, or a hiding spot flush against its own locker, will
correctly overlap that mesh — that's the intended placement, not a bug. An
early version of the placement checker ran the same `sphere_overlap_actors`
test on every gameplay-tagged actor regardless of type, so ~2/3 of the
"physical overlap" errors it reported on a real level were these intentional
contacts. Fix: split gameplay actors into two categories — actors with real
physical presence (enemies, the player start, jumpscare triggers) still get
the overlap check; actors that are deliberately placed in contact with static
props (pickups, light switches, hiding spots) skip it and rely on the
floor-trace check alone.

**Averaging every wall's position to auto-aim a verification screenshot
breaks down on multi-room levels.** A "take one screenshot from the average
position of all geometry" heuristic works when there's one room (the average
*is* the room center) but not on a level with several rooms strung along a
corridor — the average can land inside a wall, or in the corridor between two
lit rooms, producing a screenshot that's almost entirely black despite the
level being correctly lit. The fix that generalizes: group walls by a zone
label first, screenshot (or measure light coverage) per zone, not once for
the whole level. Even then, watch for degenerate groups — two adjacent rooms
sharing a long wall (with only a short end-cap wall carrying the "owning"
room's own label prefix) will otherwise produce a phantom zone whose
"bounding box" is a sliver along that one wall, with a center point sitting
on the wall itself rather than in the room. Detected by requiring at least 2
walls per zone group (a single wall can't bound a room) and merging any
group that fails that test into its nearest neighbor by position.

**No single fixed camera angle reliably frames an open-plan room** (one with
partition walls on only one axis, common in a level with no doors between
sections — a "room" here is really just a wider stretch of one long
corridor). Looking down the open axis can either show the room's own
lighting and props, or tunnel straight through to whatever is lit several
rooms away, depending on where exactly the far light happens to sit — and
there's no way to tell which outcome a given room will produce without
already knowing what's in it. Rather than guess, the toolchain captures both
the along-corridor and across-corridor angles for these rooms and leaves the
choice of which is representative to whoever is reviewing the screenshots.

**A "reliable" screenshot function had never actually been proven reliable —
it had only been suspected unreliable once, and never re-tested.** An earlier
session logged 7 consecutive captures that came back pixel-identical despite
radical scene changes (material swap, light intensity ×44, 8 lights' mobility
flipped, fog zeroed), and flagged the capture pipeline as suspect. That
finding sat undisturbed for days — every later session kept building on top
of the same capture function without anyone re-running the experiment. The
fix isn't the retest itself (a baseline capture, a deliberate scene change
placed so it can't self-occlude the one light in frame, a second capture,
then a diff) — it's turning that retest into a permanent, one-call function
(`capture_pipeline_selftest()`) with an automated regression test around it,
so "is the capture pipeline actually working" stops being a fact someone
remembers from a stale log entry and becomes something re-verified every time
the test suite runs. Comparison is done by MD5 + file size, not a pixel diff
— the embedded UE5 Python interpreter has neither PIL nor numpy, so anything
finer has to happen outside the engine, in the sandbox that does have them.

**A material-defaults check scoped to `wall`/`floor`/`ceil` in the actor
label silently stopped covering geometry the moment a level's naming
convention drifted.** A one-off room-dressing script from an earlier session
(never reintegrated into the shared toolchain) had named its wall segments
things like `Funnel_N`, `WN_L`, `WS_R`, and named niche end-caps `*_End` —
none of which contain any of the keywords the checker looked for. 22 surfaces
sat on the engine's default checkerboard material, on a level whose verifier
had been reporting zero material errors the whole time. The label-keyword
filter wasn't just incomplete, it was the wrong kind of check for this
problem — it required predicting every future naming convention in advance.
Fixed by dropping the label filter entirely: the check now scans every
`StaticMeshActor` and relies solely on the material name itself (default
engine materials like `WorldGridMaterial`/`BasicShapeMaterial` are already an
unambiguous signal — no legitimate imported asset carries them). The
auto-fixer that picks a *replacement* material still needs to know wall vs.
floor vs. ceiling, so it keeps the label check as a first pass and falls back
to classifying the actor's own bounding-box shape (thin on one horizontal
axis → wall; thin on Z, low → floor, high → ceiling) when the label doesn't
say. That same widened check then had a second-order effect worth noting:
once it stopped filtering by label, it started flagging small gameplay props
(a table, cover objects) that also happened to carry a default material —
correct to detect, but treating a mislabeled cover object as a level-blocking
error alongside an un-textured wall was disproportionate. The check now
returns errors and warnings separately, using the same bounding-box shape
test to decide which bucket a given surface belongs in.

**The Cowork agent's Linux sandbox can serve a stale, truncated view of a
file that was just edited on the Windows side — with no error, and no
convergence after retrying or waiting.** After editing a ~90KB Python file
through the agent's file-edit tool, a shell command in the same agent's
Linux sandbox (`wc -l`, `tail`, `sha256sum`) reported a *shorter* file than
what was actually on disk — cut off mid-statement, at a fixed byte offset
that didn't move across repeated checks, several `sleep`s, or several
minutes of elapsed time. `python3 -m py_compile` even reported success on
the truncated copy, because the cut happened to land right after a complete
assignment statement — truncation alone isn't guaranteed to produce a
`SyntaxError`. The authoritative file-read tool (the one backing the editor,
not the shell) showed the complete, correct file throughout; re-importing
the module directly inside the running Unreal Engine process and executing
it (not just compiling it) also worked correctly and matched the edit. The
mismatch was specific to the shell's mounted view of that one file, not the
file itself. Root cause not confirmed (a caching layer on the Windows↔Linux
bridge is the leading suspect, consistent with the NUL-padding bug logged
above, but this manifested as truncation with zero padding bytes instead).
**Practical rule adopted**: after editing a file that lives on this mount,
verify its content through the same tool that did the edit (or by re-running
it in the real target process, e.g. Unreal's embedded Python), never through
a shell command in the agent's sandbox — and never `cp` such a file from the
sandbox shell as a way to "sync" it elsewhere, since that would just copy
the stale truncated view. Copying it via a script executed by the *target*
process (Unreal's own Python, which reads the real Windows filesystem
directly) and verifying with a hash comparison in that same call sidesteps
the problem entirely.

**Live Coding can crash the editor outright if a `UFUNCTION` is added to a
class with a live, actively-referenced instance in a running Python
session.** Adding a new Blueprint-callable function to an `UEditorSubsystem`
that a Python-driven MCP session already held a handle to and was calling
regularly, then triggering `LiveCoding.Compile`, compiled successfully —
but immediately after the hot-reload, the same Python bridge that had been
returning real stdout/exceptions started returning a generic
"script executed without error" message for *every* script sent, including
one that did nothing but `raise Exception(...)`. A few calls later the editor
crashed with `EXCEPTION_ACCESS_VIOLATION` (write), stack
`python311 → PythonScriptPlugin → CoreUObject → LiveCoding`. Best-guess root
cause (not instrumented further — the editor was gone before it could be):
Live Coding patches a class's function/reflection table in place; a Python
call landing on that table mid-patch, or immediately after, can read a
half-updated pointer. The genuinely useful part of this finding isn't the
crash itself — it's that the bridge misbehaving (real output replaced by a
canned success message) was a legible warning *before* the crash, not just
in hindsight. **Rule adopted**: for any C++ change that adds or changes a
`UFUNCTION` on a class with an instance actively in use by a running agent
session, recompile via a full editor-closed build (`Build.bat`) instead of
Live Coding. If Live Coding is used anyway, treat a bridge that stops
echoing real stdout/exceptions immediately after a hot-reload as a hard stop
— restart the editor rather than continuing to issue commands hoping it
self-recovers.
