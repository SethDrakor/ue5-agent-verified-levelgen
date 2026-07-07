"""
test_suite.py — Filet de securite anti-regression pour HorrorGame plugin.

Usage:
    from test_suite import run_all
    run_all()

Lancer AVANT et APRES toute modification C++ ou Python du plugin.
Si un test passe au rouge apres modification = regression detectee.
"""

import unreal
import json
import os

_OK   = "[OK]  "
_FAIL = "[FAIL]"
_SKIP = "[SKIP]"

# ─────────────────────────────────────────────────────────────
# Infrastructure
# ─────────────────────────────────────────────────────────────

_results = []
_bp_test  = None
_BP_PATH  = "/Game/_TestSuite/BP_TestSuite"

def _test(name, fn):
    try:
        ok = fn()
        _results.append((_OK if ok else _FAIL, name, "" if ok else "returned falsy"))
    except Exception as e:
        _results.append((_FAIL, name, str(e)))

def _create_test_bp():
    global _bp_test
    if unreal.EditorAssetLibrary.does_asset_exist(_BP_PATH):
        unreal.EditorAssetLibrary.delete_asset(_BP_PATH)
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", unreal.Actor)
    at = unreal.AssetToolsHelpers.get_asset_tools()
    _bp_test = at.create_asset("BP_TestSuite", "/Game/_TestSuite", unreal.Blueprint, factory)
    return _bp_test is not None

def _cleanup():
    if unreal.EditorAssetLibrary.does_asset_exist(_BP_PATH):
        unreal.EditorAssetLibrary.delete_asset(_BP_PATH)

# ─────────────────────────────────────────────────────────────
# Groupes de tests
# ─────────────────────────────────────────────────────────────

def _test_bpes(bp):
    bpes = unreal.get_editor_subsystem(unreal.BlueprintEditingSubsystem)

    _test("bpes subsystem disponible",
          lambda: bpes is not None)

    _test("find_graph EventGraph",
          lambda: bpes.find_graph(bp, "EventGraph") is not None)

    _test("resolve_class /Script/Engine.Actor",
          lambda: bpes.resolve_class("/Script/Engine.Actor") is not None)

    _test("add_function_call_node PrintString",
          lambda: bpes.add_function_call_node(
              bp, "EventGraph", "PrintString",
              "/Script/Engine.KismetSystemLibrary", 0, 0) is not None)

    _test("add_cast_node Actor",
          lambda: bpes.add_cast_node(
              bp, "EventGraph", "/Script/Engine.Actor", 200, 0) is not None)

    _test("add_for_each_loop_node",
          lambda: bpes.add_for_each_loop_node(
              bp, "EventGraph", 400, 0) is not None)

    _test("add_macro_node ForEachLoop",
          lambda: bpes.add_macro_node(
              bp, "EventGraph", "ForEachLoop", 600, 0) is not None)


def _test_batch_wire(bp):
    bpes = unreal.get_editor_subsystem(unreal.BlueprintEditingSubsystem)

    def batch(payload):
        r = bpes.batch_wire_graph(bp, "EventGraph", json.dumps(payload))
        return r

    _test("batch_wire_graph disponible",
          lambda: hasattr(bpes, "batch_wire_graph"))

    _test("batch graphe vide → OK",
          lambda: batch({"nodes": [], "connections": []}).startswith("OK"))

    _test("batch branch node",
          lambda: "1 nodes" in batch({
              "nodes": [{"id": "b", "type": "branch", "x": 800, "y": 0}],
              "connections": []
          }))

    _test("batch sequence node",
          lambda: batch({
              "nodes": [{"id": "s", "type": "sequence", "x": 1000, "y": 0}],
              "connections": []
          }).startswith("OK"))

    _test("batch var_get node",
          lambda: batch({
              "nodes": [{"id": "v", "type": "var_get", "var": "AnyVar", "x": 1200, "y": 0}],
              "connections": []
          }).startswith("OK"))

    _test("batch function node PrintString",
          lambda: batch({
              "nodes": [{"id": "f", "type": "function",
                         "fn": "PrintString",
                         "cls": "/Script/Engine.KismetSystemLibrary",
                         "x": 1400, "y": 0,
                         "defaults": {"InString": "test"}}],
              "connections": []
          }).startswith("OK"))

    # Test connexion : branch → deux noeuds relies
    _test("batch connexion branch.then → fn.execute",
          lambda: "1 connections" in batch({
              "nodes": [
                  {"id": "br", "type": "branch",   "x": 1600, "y": 0},
                  {"id": "fn", "type": "function",
                   "fn": "PrintString",
                   "cls": "/Script/Engine.KismetSystemLibrary",
                   "x": 1900, "y": 0}
              ],
              "connections": [
                  {"from": "br", "fp": "then", "to": "fn", "tp": "execute"}
              ]
          }))


def _test_bgh(bp):
    bgh = unreal.BlueprintGraphHelper

    _test("bgh disponible",
          lambda: bgh is not None)

    _test("list_graph_nodes retourne des noeuds",
          lambda: len(bgh.list_graph_nodes(bp, "EventGraph")) > 0)

    nodes = bgh.list_graph_nodes(bp, "EventGraph")
    first_id = nodes[0].split("|")[0] if nodes else None

    if first_id:
        node = bgh.find_node_by_name(bp, "EventGraph", first_id)
        _test("find_node_by_name",
              lambda: node is not None)
        _test("list_node_pins",
              lambda: bgh.list_node_pins(node) is not None)
    else:
        _results.append((_SKIP, "find_node_by_name", "aucun noeud"))
        _results.append((_SKIP, "list_node_pins",   "aucun noeud"))

    _test("compile_blueprint",
          lambda: (bgh.compile_blueprint(bp), True)[1])


def _test_ue5_utils(bp):
    try:
        from ue5_utils import aeas, bpes, bgh, BPGraph, load_bp, compile_bp
    except Exception as e:
        _results.append((_FAIL, "ue5_utils import", str(e)))
        return

    _test("aeas() subsystem",          lambda: aeas() is not None)
    _test("bpes() subsystem",          lambda: bpes() is not None)
    _test("bgh class",                 lambda: bgh is not None)

    _test("BPGraph instantiation",
          lambda: BPGraph(bp, "EventGraph") is not None)

    _test("BPGraph.wire() graphe vide",
          lambda: BPGraph(bp, "EventGraph").wire().startswith("OK"))

    def test_bpgraph_chain():
        g  = BPGraph(bp, "EventGraph")
        b  = g.branch(x=2100, y=0)
        fn = g.call("PrintString", "/Script/Engine.KismetSystemLibrary", x=2400, y=0)
        b >> fn
        r  = g.wire()
        return "2 nodes" in r and "1 connections" in r

    _test("BPGraph >> chain (branch >> call)", test_bpgraph_chain)

    _test("compile_bp()",
          lambda: (compile_bp(bp), True)[1])


# ─────────────────────────────────────────────────────────────
# Groupes de tests (2026-07-06) — fonctions a bug historique documente
# (point_light, safe_spawn_enemy, occupancy grid) — chacun de ces bugs
# s'est deja produit une fois et a ete corrige dans ue5_utils.py (voir
# CLAUDE.md) sans qu'aucun test ne le protege contre une regression future.
# Coordonnees tres eloignees ci-dessous : n'importe quel level reellement
# ouvert (HorrorLevel, BoucherieLevel, AgentDemo...) ne peut avoir aucune
# geometrie a ces coordonnees, donc aucun risque de faux positif/negatif
# lie au contenu du level en cours, et rien n'est visible dans le viewport
# (a des kilometres de toute zone de jeu).
# ─────────────────────────────────────────────────────────────

_TEST_FAR_X = 733000.0
_TEST_FAR_Y = 733000.0


def _test_point_light():
    """Garde contre 3 bugs deja documentes dans CLAUDE.md :
    - set_attenuation_radius() qui echoue silencieusement (radius reste 1000)
    - mobilite Stationary par defaut du moteur, incompatible avec ce pipeline
      qui ne fait jamais de lighting build
    - unreal.Color qui prend BGRA et non RGBA (inversion facile a re-casser)
    """
    try:
        from ue5_utils import point_light, destroy
    except Exception as e:
        _results.append((_FAIL, "point_light import", str(e)))
        return

    pl = point_light(_TEST_FAR_X, _TEST_FAR_Y, 500, intensity=1000,
                      rgb=(255, 0, 0), radius=777, label="_TestSuite_PointLight")
    try:
        _test("point_light cree un acteur", lambda: pl is not None)
        if pl is None:
            return

        lc = pl.point_light_component

        _test("point_light mobilite = MOVABLE par defaut (ex-bug Stationary sans bake)",
              lambda: lc.get_editor_property("mobility") == unreal.ComponentMobility.MOVABLE)

        _test("point_light radius applique (ex-bug set_attenuation_radius silencieux)",
              lambda: abs(lc.get_editor_property("attenuation_radius") - 777.0) < 0.5)

        color = lc.get_editor_property("light_color")
        _test("point_light couleur correcte apres swap BGRA (rgb=(255,0,0) -> r=255,g=0,b=0)",
              lambda: color.r == 255 and color.g == 0 and color.b == 0)
    finally:
        if pl is not None:
            destroy(pl)


def _test_safe_spawn_enemy():
    """Garde contre l'oubli du tag 'Enemy' (necessaire a GetAllActorsWithTag,
    voir CLAUDE.md — le pin 'class' est non-settable via Python en UE5.7,
    GetAllActorsWithTag est le contournement obligatoire). Sol synthetique
    cree pour ne dependre d'aucune geometrie du level reellement ouvert.
    """
    try:
        from ue5_utils import place_static_mesh, safe_spawn_enemy, destroy, OccupancyGrid
    except Exception as e:
        _results.append((_FAIL, "safe_spawn_enemy import", str(e)))
        return

    floor_x, floor_y = _TEST_FAR_X + 5000, _TEST_FAR_Y + 5000
    floor = place_static_mesh("/Engine/BasicShapes/Cube.Cube", floor_x, floor_y, -10,
                               sx=20, sy=20, sz=0.2, label="_TestSuite_EnemyFloor")
    enemy = None
    try:
        _test("safe_spawn_enemy - sol de test cree", lambda: floor is not None)
        if floor is None:
            return

        # Grille dediee et vide : evite toute interference avec _global_grid
        # (qui peut deja contenir un etat d'une session de level design en cours)
        test_grid = OccupancyGrid(floor_x - 1000, floor_x + 1000,
                                   floor_y - 1000, floor_y + 1000, cell_size=50)

        enemy = safe_spawn_enemy(floor_x, floor_y, z=50, label="_TestSuite_Enemy",
                                  grid=test_grid)

        _test("safe_spawn_enemy - acteur spawne avec succes", lambda: enemy is not None)
        if enemy is None:
            return

        _test("safe_spawn_enemy - tag 'Enemy' applique automatiquement",
              lambda: unreal.Name("Enemy") in enemy.tags)
    finally:
        if enemy is not None:
            destroy(enemy)
        if floor is not None:
            destroy(floor)


def _test_occupancy_grid_skydome_guard():
    """Garde contre le crash UE5 reproductible documente dans CLAUDE.md :
    build_occupancy_grid_from_level() balayait autrefois la bounding box de
    TOUT StaticMeshActor sans filtre de taille -> un acteur demesure type
    SM_SkySphere (~1 638 400 UU d'extent) declenchait ~4x10^15 iterations
    imbriquees -> freeze puis crash OOM. Ce test recree un acteur a bbox
    demesuree (simulateur de skydome) et verifie que la fonction termine
    quand meme dans un temps raisonnable au lieu de raccrocher le thread.
    """
    try:
        from ue5_utils import place_static_mesh, build_occupancy_grid_from_level, destroy
    except Exception as e:
        _results.append((_FAIL, "occupancy_grid import", str(e)))
        return

    mega = place_static_mesh(
        "/Engine/BasicShapes/Cube.Cube",
        _TEST_FAR_X - 20000, _TEST_FAR_Y - 20000, 0,
        sx=800, sy=800, sz=800,  # 100 UU * 800 = 80 000 UU d'extent > max_extent=20000
        label="_TestSuite_MegaSkydomeProxy")
    try:
        _test("occupancy_grid guard - acteur demesure cree (simule skydome)",
              lambda: mega is not None)
        if mega is None:
            return

        import time
        t0 = time.time()
        grid = build_occupancy_grid_from_level(cell_size=50)
        elapsed = time.time() - t0

        _test("occupancy_grid guard - grille retournee (pas de crash/exception)",
              lambda: grid is not None)
        _test("occupancy_grid guard - termine en temps raisonnable "
              "(<30s — ex-bug OOM SM_SkySphere, jamais de retour avant)",
              lambda: elapsed < 30.0)
    finally:
        if mega is not None:
            destroy(mega)


def _test_load_bp_class():
    """Garde contre le bug documente dans CLAUDE.md : load_blueprint_class()
    echoue pour les chemins Blueprint qui incluent deja le suffixe '.Xxx_C'
    (ex: safe_spawn_enemy sur BP_IA_Enemy_C) -> load_bp_class() doit reussir
    a la fois sur le chemin nu ET sur le chemin suffixe via ses 3 strategies
    de fallback (load_blueprint_class -> load_class -> auto-suffixe _C).

    Chemin corrige le 2026-07-06 (voir GAME_MEMORY.md session 12) :
    "/Game/HorrorGame/IA/Blueprint/Enemy/BP_IA_Enemy" (chemin documente dans le
    tableau d'assets de CLAUDE.md) est en realite un REDIRECTOR residuel de la
    reorganisation Content/ (session 4-5) vers le vrai chemin ci-dessous.
    unreal.load_asset()/load_class() suivent silencieusement ce redirector (d'ou
    le "chemin nu, strategie 1" qui semblait fonctionner), mais load_blueprint_
    class() ne le suit PAS et echoue TOUJOURS dessus ("The asset is not a
    Blueprint") — logge une erreur bruyante a CHAQUE execution, quel que soit le
    suffixe. Utiliser directement le chemin reel evite le redirector entierement.
    """
    try:
        from ue5_utils import load_bp_class
    except Exception as e:
        _results.append((_FAIL, "load_bp_class import", str(e)))
        return

    enemy_path = "/Game/HorrorGame/Blueprint/Enemy/BP_IA_Enemy"
    enemy_path_suffixed = enemy_path + ".BP_IA_Enemy_C"

    if not unreal.EditorAssetLibrary.does_asset_exist(enemy_path):
        _results.append((_SKIP, "load_bp_class BP_IA_Enemy (chemin nu)",
                          "asset introuvable dans ce projet"))
        _results.append((_SKIP, "load_bp_class BP_IA_Enemy (chemin suffixe _C)",
                          "asset introuvable dans ce projet"))
        return

    _test("load_bp_class BP_IA_Enemy (chemin nu, strategie 1)",
          lambda: load_bp_class(enemy_path) is not None)
    _test("load_bp_class BP_IA_Enemy (chemin suffixe _C, ex-bug strategie 1 seule)",
          lambda: load_bp_class(enemy_path_suffixed) is not None)


def _test_capture_reference_screenshot():
    """Garde contre le bug documente dans CLAUDE.md (section 'Screenshot fiable') :
    le TextureRenderTarget2D cree par defaut est en RTF_RGBA16F (HDR) — l'exporter
    vers un nom '*.png' ecrivait en realite un fichier OpenEXR illisible malgre
    l'extension (magic bytes EXR '76 2f 31 01', pas PNG '89 50 4E 47'). Le fix
    (forcer RTF_RGBA8 avant capture) est deja applique dans capture_reference_
    screenshot(), ce test verifie juste qu'il ne regresse jamais silencieusement.
    """
    try:
        from ue5_utils import capture_reference_screenshot
    except Exception as e:
        _results.append((_FAIL, "capture_reference_screenshot import", str(e)))
        return

    path = capture_reference_screenshot(
        _TEST_FAR_X, _TEST_FAR_Y, 500, pitch=0, yaw=0,
        name="_testsuite_capture", resolution=(160, 90))

    try:
        _test("capture_reference_screenshot - fichier cree sur disque",
              lambda: bool(path) and os.path.exists(path))
        if not path or not os.path.exists(path):
            return

        with open(path, "rb") as f:
            magic = f.read(8)

        PNG_MAGIC = b"\x89\x50\x4E\x47"
        EXR_MAGIC = b"\x76\x2f\x31\x01"

        _test("capture_reference_screenshot - vrai PNG (ex-bug RTF_RGBA16F -> EXR deguise)",
              lambda: magic[:4] == PNG_MAGIC)
        _test("capture_reference_screenshot - PAS de magic bytes EXR",
              lambda: magic[:4] != EXR_MAGIC)
    finally:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass


def _test_occupancy_grid_unit():
    """Tests unitaires directs sur OccupancyGrid (pure Python, aucun acteur UE5
    necessaire, tres rapide) — renforce le systeme ou le bug de tangence exacte
    de safe_place() a ete decouvert (voir GAME_MEMORY.md session 12).
    """
    try:
        from ue5_utils import OccupancyGrid
    except Exception as e:
        _results.append((_FAIL, "OccupancyGrid import", str(e)))
        return

    grid = OccupancyGrid(0, 1000, 0, 1000, cell_size=50)

    _test("OccupancyGrid - position vide est libre au depart",
          lambda: grid.is_free(500, 500, 60))

    grid.mark_occupied(500, 500, 60)

    _test("OccupancyGrid - position marquee occupee n'est plus libre",
          lambda: not grid.is_free(500, 500, 60))

    _test("OccupancyGrid - position eloignee reste libre apres marquage local",
          lambda: grid.is_free(900, 900, 60))

    def _find_nearest_free_works():
        nx, ny = grid.find_nearest_free(500, 500, 60)
        return nx is not None and ny is not None and grid.is_free(nx, ny, 60)

    _test("OccupancyGrid - find_nearest_free retourne une position reellement libre",
          _find_nearest_free_works)


# ─────────────────────────────────────────────────────────────
# Test MANUEL (PAS appele par run_all()) — bake_lighting()/unbake_lighting()
# ─────────────────────────────────────────────────────────────
# Volontairement exclu du chemin automatique (run_all(), donc aussi
# wire_and_compile()/safe_modify_plugin()) : un bake reel meme en quality=
# "preview" a mesure ~8.4s sur ce level (voir GAME_MEMORY.md session 12) —
# double a ~17s dans le mecanisme avant/apres, et touche reellement les
# donnees d'eclairage du niveau ENTIER (pas juste une fixture isolee comme
# les autres tests). A appeler explicitement apres toute modification de
# bake_lighting()/unbake_lighting() dans ue5_utils.py :
#   from test_suite import test_bake_lighting_mobility
#   test_bake_lighting_mobility()

def test_bake_lighting_mobility():
    """Garde contre 2 pieges deja documentes dans CLAUDE.md/ue5_utils.py :
    piege n°1 — une lumiere Movable ignore totalement un bake (donc bake_lighting()
    DOIT basculer la mobilite en Stationary avant de bake) ; piege n°2 — ce pipeline
    utilise Movable partout par choix delibere, donc unbake_lighting() doit pouvoir
    revenir proprement en Movable apres un bake ponctuel.
    """
    try:
        from ue5_utils import point_light, bake_lighting, unbake_lighting, destroy
    except Exception as e:
        unreal.log_error(f"[FAIL] bake_lighting import: {e}")
        return False

    local_results = []

    def _t(name, fn):
        try:
            ok = fn()
            local_results.append((_OK if ok else _FAIL, name, "" if ok else "returned falsy"))
        except Exception as e:
            local_results.append((_FAIL, name, str(e)))

    pl = point_light(_TEST_FAR_X, _TEST_FAR_Y, 500, intensity=500,
                      rgb=(255, 255, 255), radius=300, label="_TestSuite_BakeLight")
    try:
        _t("bake_lighting - acteur de test cree", lambda: pl is not None)
        if pl is None:
            return False
        lc = pl.point_light_component

        _t("bake_lighting - mobilite initiale MOVABLE",
           lambda: lc.get_editor_property("mobility") == unreal.ComponentMobility.MOVABLE)

        ok = bake_lighting(labels=["_TestSuite_BakeLight"], quality="preview",
                            with_reflection_captures=False)
        _t("bake_lighting - build_light_maps reussi", lambda: ok)
        _t("bake_lighting - mobilite basculee en STATIONARY avant bake (ex-piege n°1)",
           lambda: lc.get_editor_property("mobility") == unreal.ComponentMobility.STATIONARY)

        unbake_lighting(labels=["_TestSuite_BakeLight"])
        _t("unbake_lighting - mobilite revenue en MOVABLE (ex-piege n°2)",
           lambda: lc.get_editor_property("mobility") == unreal.ComponentMobility.MOVABLE)
    finally:
        if pl is not None:
            destroy(pl)

    passed = sum(1 for s, _, _ in local_results if s == _OK)
    failed = sum(1 for s, _, _ in local_results if s == _FAIL)
    total = len(local_results)

    unreal.log("=" * 55)
    unreal.log("  TEST MANUEL — bake_lighting() / unbake_lighting()")
    unreal.log("=" * 55)
    for status, name, msg in local_results:
        line = f"  {status} {name}"
        if msg:
            line += f"  ({msg})"
        if status == _OK:
            unreal.log(line)
        else:
            unreal.log_error(line)
    icon = "TOUT OK" if failed == 0 else f"{failed} ECHEC(S) !"
    unreal.log(f"  {passed}/{total} passes → {icon}")
    unreal.log("=" * 55)

    return failed == 0


# ─────────────────────────────────────────────────────────────
# Point d'entree
# ─────────────────────────────────────────────────────────────

def run_all(verbose=True):
    global _results
    _results = []

    if not _create_test_bp():
        unreal.log_error("[TEST SUITE] Impossible de creer le BP de test")
        return False

    bp = _bp_test

    _test_bpes(bp)
    _test_batch_wire(bp)
    _test_bgh(bp)
    _test_ue5_utils(bp)

    _cleanup()

    _test_point_light()
    _test_safe_spawn_enemy()
    _test_occupancy_grid_skydome_guard()
    _test_load_bp_class()
    _test_capture_reference_screenshot()
    _test_occupancy_grid_unit()

    passed = sum(1 for s, _, _ in _results if s == _OK)
    failed = sum(1 for s, _, _ in _results if s == _FAIL)
    skipped= sum(1 for s, _, _ in _results if s == _SKIP)
    total  = len(_results)

    if verbose:
        unreal.log("=" * 55)
        unreal.log("  TEST SUITE — HorrorGame Plugin")
        unreal.log("=" * 55)
        for status, name, msg in _results:
            line = f"  {status} {name}"
            if msg: line += f"  ({msg})"
            if status == _OK:   unreal.log(line)
            elif status == _SKIP: unreal.log(line)
            else:               unreal.log_error(line)
        unreal.log("=" * 55)
        icon = "TOUT OK" if failed == 0 else f"{failed} ECHEC(S) !"
        unreal.log(f"  {passed}/{total} passes  {skipped} skips  → {icon}")
        unreal.log("=" * 55)

    return failed == 0
