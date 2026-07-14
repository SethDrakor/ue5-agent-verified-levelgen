import unreal, os, math

def aeas(): return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
def bpes(): return unreal.get_editor_subsystem(unreal.BlueprintEditingSubsystem)
def room(): return unreal.get_editor_subsystem(unreal.RoomGeneratorSubsystem)
bgh = unreal.BlueprintGraphHelper

# -- Blueprint graph --
def load_bp(path): return unreal.load_asset(path)
def load_bp_class(path):
    """Charge une classe Blueprint. Essaie load_blueprint_class puis load_class avec _C.

    Chemin deja suffixe (contient un "." dans le dernier segment, ex: BP_IA_Enemy.BP_IA_Enemy_C) :
    saute directement a load_class(), qui est la seule strategie qui fonctionne pour ce format.
    Corrige le 2026-07-06 (voir GAME_MEMORY.md session 12) : appeler load_blueprint_class() sur un
    chemin deja suffixe echoue TOUJOURS ("The asset is not a Blueprint") et logge une LogEditorAsset
    Subsystem: Error bruyante dans l'Output Log a chaque appel — inoffensif (le fallback suivant
    reussissait deja), mais parasitait les logs et rendait les captures d'ecran illisibles.
    """
    last_segment = path.rstrip("/").split("/")[-1]
    if "." in last_segment:
        return unreal.load_class(None, path)

    cls = unreal.EditorAssetLibrary.load_blueprint_class(path)
    if cls is None:
        cls = unreal.load_class(None, path)
    if cls is None:
        cls = unreal.load_class(None, f"{path}.{last_segment}_C")
    return cls
def resolve_class(p): return bpes().resolve_class(p)

def add_fn_node(bp, graph, fn, cls, x=0, y=0):
    return bpes().add_function_call_node(bp, graph, fn, cls, x, y)

def add_cast(bp, graph, cls, x=0, y=0):
    return bpes().add_cast_node(bp, graph, cls, x, y)

def add_branch(bp, graph, x=0, y=0):
    return bgh.add_branch_node(bp, graph, x, y)

def add_foreach(bp, graph, x=0, y=0):
    return bgh.add_macro_node(bp, graph, "ForEachLoop", x, y)

def add_var_get(bp, graph, var, x=0, y=0):
    return bgh.add_variable_get_node(bp, graph, var, x, y)

def get_node(bp, g, nid): return bgh.find_node_by_name(bp, g, nid)
def list_nodes(bp, g): return bgh.list_graph_nodes(bp, g)
def get_pins(n): return bgh.list_node_pins(n)
def fn_of(n): return bgh.get_node_function_name(n)

def connect(fn, fp, tn, tp): return bgh.connect_pins(fn, fp, tn, tp)
def break_pin(n, p): return bgh.break_all_pin_links(n, p)
def set_default(bp, g, n, pin, val): return bgh.set_pin_default_value(bp, g, n, pin, val)
def delete_node(n): return bgh.delete_node(n)
def compile_bp(bp): bgh.compile_blueprint(bp); bgh.save_blueprint(bp)

# -- Actors --
def spawn(cls_or_path, x=0, y=0, z=100, label=None):
    if isinstance(cls_or_path, str): cls_or_path = load_bp_class(cls_or_path)
    a = aeas().spawn_actor_from_class(cls_or_path, unreal.Vector(x,y,z), unreal.Rotator(0,0,0))
    if a and label: a.set_actor_label(label)
    return a

def destroy(a): aeas().destroy_actor(a)
def all_actors(): return aeas().get_all_level_actors()
def actors_by_type(t): return [a for a in all_actors() if type(a).__name__ == t]
def actor_by_label(lbl): return next((a for a in all_actors() if a.get_actor_label()==lbl), None)
def set_loc(a, x, y, z): a.set_actor_location(unreal.Vector(x,y,z), False, False)

# -- Level --
def save(): unreal.EditorLoadingAndSavingUtils.save_current_level()
def open_level(p): unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).load_level(p)

# -- Room generation --
def gen_room(cx, cy, sx, sy, h=300, t=20, name="Room"):
    room().generate_room(unreal.Vector(cx,cy,0), unreal.Vector(sx,sy,0), h, t, name)

def gen_corridor(x1, x2, w=500, h=300, t=20, name="Corr"):
    room().generate_corridor(unreal.Vector(x1,0,0), unreal.Vector(x2,0,0), w, h, t, name)

def spawn_cube(x, y, z, sx, sy, sz, label="Cube"):
    room().spawn_scaled_cube(None, unreal.Vector(x,y,z), unreal.Vector(sx,sy,sz), label)

# -- Lights --
def point_light(x, y, z, intensity=3000, rgb=(255,255,255), radius=500, label=None):
    """Spawn une PointLight. IMPORTANT: utilise set_editor_property pour radius —
    set_attenuation_radius() échoue silencieusement en UE5.7.

    mobility forcé à MOVABLE : ce pipeline agent ne fait jamais de lighting build
    ("Build Lighting"), donc une lumière Stationary (mobilité par défaut du moteur)
    peut se comporter de façon incomplète/incorrecte sans bake. Bug diagnostiqué
    2026-07-03 sur AgentDemo (salle noire malgré intensité/radius corrects) —
    voir GAME_MEMORY.md."""
    pl = aeas().spawn_actor_from_class(unreal.PointLight.static_class(), unreal.Vector(x,y,z), unreal.Rotator(0,0,0))
    lc = pl.point_light_component
    lc.set_mobility(unreal.ComponentMobility.MOVABLE)
    lc.set_editor_property("intensity", float(intensity))
    lc.set_editor_property("light_color", unreal.Color(rgb[2],rgb[1],rgb[0],255))  # unreal.Color prend BGRA (pas RGBA) — r et b inversés
    lc.set_editor_property("attenuation_radius", float(radius))  # NE PAS utiliser set_attenuation_radius() — silently fails
    if label: pl.set_actor_label(label)
    # Vérification immédiate
    actual = int(lc.get_editor_property("attenuation_radius"))
    if actual != int(radius):
        unreal.log_warning(f"[point_light] radius non appliqué: target={radius} actual={actual}")
    return pl

def bake_lighting(labels=None, quality="production", with_reflection_captures=True,
                   revert_after=False):
    """Bake l'éclairage (Lightmass) via l'API Python native LevelEditorSubsystem.build_light_maps()
    (trouvée par introspection le 2026-07-03 — dir(unreal.LevelEditorSubsystem) contient bien
    'build_light_maps', contrairement à EditorLevelLibrary/UnrealEditorSubsystem qui n'ont rien).

    ATTENTION — piège n°1 : une lumière en mobilité MOVABLE (le défaut de ce pipeline, voir
    point_light() ci-dessus) est TOUJOURS 100% dynamique et IGNORE TOTALEMENT le bake, quel
    que soit le résultat de build_light_maps(). Pour qu'un bake ait un effet visible, les
    lumières ciblées doivent d'abord passer en Stationary — cette fonction le fait pour toi,
    automatiquement, avant d'appeler build_light_maps().

    ATTENTION — piège n°2 : ce projet utilise MOVABLE partout par choix délibéré, précisément
    pour ne JAMAIS dépendre d'un bake (voir GAME_MEMORY.md — bug historique où des lumières
    Stationary non-bakées rendaient des salles noires). Un bake devient PÉRIMÉ dès qu'on
    redéplace un mur, une lumière ou qu'on relance setup_horror_room() sur la zone — il
    faudrait alors rebaker à chaque itération. À réserver à un test ponctuel ("à quoi ça
    ressemblerait avec du bounce light baked ?") ou une passe de polish finale sur une salle
    figée, PAS au workflow itératif habituel (setup_horror_room, fix_all, etc.).

    labels    : liste de labels de PointLight à inclure (None = toutes les PointLight du level)
    quality   : "preview" (rapide, secondes) | "medium" | "high" | "production" (lent, peut
                prendre plusieurs minutes selon la taille de la scène — utiliser "preview"
                pour un test rapide avant de lancer "production")
    with_reflection_captures : rebuild aussi les reflection captures après le bake
    revert_after : si True, repasse les lumières en Movable juste après le bake (le lightmap
                   calculé reste sur les surfaces mais n'est plus utilisé — sert surtout à
                   comparer visuellement sans laisser le level dans un état Stationary
                   "à bakes obligatoires" pour les sessions suivantes)

    Retourne True si build_light_maps() a réussi.
    """
    quality_map = {
        "preview":    unreal.LightingBuildQuality.QUALITY_PREVIEW,
        "medium":     unreal.LightingBuildQuality.QUALITY_MEDIUM,
        "high":       unreal.LightingBuildQuality.QUALITY_HIGH,
        "production": unreal.LightingBuildQuality.QUALITY_PRODUCTION,
    }
    q = quality_map.get(quality, unreal.LightingBuildQuality.QUALITY_PRODUCTION)

    targets = [a for a in all_actors() if 'PointLight' in a.get_class().get_name()]
    if labels is not None:
        targets = [a for a in targets if a.get_actor_label() in labels]

    switched = []
    for a in targets:
        a.point_light_component.set_mobility(unreal.ComponentMobility.STATIONARY)
        switched.append(a.get_actor_label())
    print(f"[bake_lighting] {len(switched)} lumière(s) passée(s) en Stationary: {switched}")

    if quality == "production":
        print("[bake_lighting] quality='production' peut prendre plusieurs minutes — "
              "utiliser quality='preview' pour un test rapide si besoin.")

    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    ok = les.build_light_maps(quality=q, with_reflection_captures=with_reflection_captures)
    print(f"[bake_lighting] build_light_maps -> {'OK' if ok else 'ÉCHEC'} (quality={quality})")

    if revert_after:
        for a in targets:
            a.point_light_component.set_mobility(unreal.ComponentMobility.MOVABLE)
        print(f"[bake_lighting] {len(targets)} lumière(s) repassée(s) en Movable (revert_after=True)")

    return ok


def unbake_lighting(labels=None):
    """Repasse des PointLight en Movable (annule l'effet d'un bake_lighting() précédent
    sans recalculer quoi que ce soit). labels=None = toutes les PointLight du level.
    """
    targets = [a for a in all_actors() if 'PointLight' in a.get_class().get_name()]
    if labels is not None:
        targets = [a for a in targets if a.get_actor_label() in labels]
    for a in targets:
        a.point_light_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    print(f"[unbake_lighting] {len(targets)} lumière(s) repassée(s) en Movable")
    return len(targets)


# -- Static Mesh placement --
def place_static_mesh(ue_path, x, y, z, pitch=0, yaw=0, roll=0, sx=1, sy=1, sz=1, label=""):
    """Place un StaticMesh depuis son chemin UE (/Game/...) dans le level."""
    mesh = unreal.load_asset(ue_path)
    if mesh is None:
        unreal.log_warning("[place_static_mesh] asset introuvable : {}".format(ue_path))
        return None
    actor = aeas().spawn_actor_from_class(
        unreal.StaticMeshActor.static_class(),
        unreal.Vector(x, y, z),
        unreal.Rotator(pitch=pitch, yaw=yaw, roll=roll)  # IMPORTANT: args nommés obligatoires (ordre positif = roll,pitch,yaw en UE5.7)
    )
    if actor is None:
        return None
    comp = actor.get_component_by_class(unreal.StaticMeshComponent)
    if comp:
        comp.set_static_mesh(mesh)
    actor.set_actor_scale3d(unreal.Vector(sx, sy, sz))
    if label:
        actor.set_actor_label(label)
    return actor

def scatter_props(asset_paths, cx, cy, z=0, count=5, spread=300,
                  label_prefix="Prop", seed=None, scale_range=(0.9, 1.1)):
    """Place count props aleatoirement dans un rayon spread autour de (cx, cy, z).

    asset_paths  : liste de chemins UE parmi lesquels piocher aleatoirement.
    spread       : rayon max en UU (Unreal Units).
    seed         : graine pour reproduction deterministe (None = aleatoire).
    scale_range  : (min, max) variation d'echelle uniforme.
    Retourne la liste des acteurs spawnes.
    """
    import random
    if seed is not None:
        random.seed(seed)
    placed = []
    for i in range(count):
        path = random.choice(asset_paths)
        ox   = random.uniform(-spread, spread)
        oy   = random.uniform(-spread, spread)
        yaw  = random.uniform(0, 360)
        sc   = random.uniform(scale_range[0], scale_range[1])
        lbl  = "{}_{}".format(label_prefix, i)
        a = place_static_mesh(path, cx + ox, cy + oy, z,
                              yaw=yaw, sx=sc, sy=sc, sz=sc, label=lbl)
        if a:
            placed.append(a)
    return placed

def tag_actor(actor, tag):
    """Ajoute un gameplay tag a un acteur (utile pour GetAllActorsWithTag)."""
    tags = list(actor.tags)
    n    = unreal.Name(tag)
    if n not in tags:
        tags.append(n)
        actor.tags = tags
    return actor

def list_assets(ue_folder, recursive=True):
    """Liste tous les assets dans un dossier UE. Retourne les chemins /Game/..."""
    return unreal.EditorAssetLibrary.list_assets(ue_folder, recursive=recursive)


# ══════════════════════════════════════════════════════
# OCCUPANCY GRID — placement garanti zéro overlap
# ══════════════════════════════════════════════════════

class OccupancyGrid:
    """Grille d'occupation spatiale (plan XY).

    Avant de placer un acteur, on vérifie que la cellule est libre.
    Après placement, on marque la cellule comme occupée.
    Résultat : zéro overlap possible entre acteurs placés via safe_place().

    Workflow :
        grid = build_occupancy_grid_from_level()   # marque géométrie existante
        safe_spawn_enemy(1600, 0, grid=grid, label="Enemy_A")
        safe_spawn_enemy(2300, 450, grid=grid, label="Enemy_B")
    """
    def __init__(self, x_min, x_max, y_min, y_max, cell_size=50):
        self.cell_size = float(cell_size)
        self.x_min = float(x_min)
        self.y_min = float(y_min)
        self.nx = max(1, int((x_max - x_min) / cell_size) + 2)
        self.ny = max(1, int((y_max - y_min) / cell_size) + 2)
        self.grid = [[False] * self.ny for _ in range(self.nx)]
        unreal.log(f"[OccupancyGrid] {self.nx}×{self.ny} cells à {cell_size} UU/cell "
                   f"— X=[{int(x_min)},{int(x_max)}] Y=[{int(y_min)},{int(y_max)}]")

    def _to_cell(self, x, y):
        cx = int((x - self.x_min) / self.cell_size)
        cy = int((y - self.y_min) / self.cell_size)
        return max(0, min(cx, self.nx - 1)), max(0, min(cy, self.ny - 1))

    def mark_occupied(self, x, y, radius):
        """Marque un disque de rayon `radius` centré sur (x,y) comme occupé."""
        cx, cy = self._to_cell(x, y)
        r = int(radius / self.cell_size) + 1
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if dx * dx + dy * dy <= r * r:
                    nx_ = cx + dx; ny_ = cy + dy
                    if 0 <= nx_ < self.nx and 0 <= ny_ < self.ny:
                        self.grid[nx_][ny_] = True

    def is_free(self, x, y, radius):
        """Retourne True si le disque (x,y,radius) ne chevauche aucune cellule occupée."""
        cx, cy = self._to_cell(x, y)
        r = int(radius / self.cell_size) + 1
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if dx * dx + dy * dy <= r * r:
                    nx_ = cx + dx; ny_ = cy + dy
                    if 0 <= nx_ < self.nx and 0 <= ny_ < self.ny:
                        if self.grid[nx_][ny_]:
                            return False
        return True

    def find_nearest_free(self, x, y, radius, max_dist=600):
        """Trouve la position libre la plus proche de (x,y).
        Retourne (new_x, new_y) ou (None, None) si zone saturée."""
        step = self.cell_size
        d = step
        while d <= max_dist:
            for angle_deg in range(0, 360, 15):
                angle = math.radians(angle_deg)
                cx = x + d * math.cos(angle)
                cy = y + d * math.sin(angle)
                if self.is_free(cx, cy, radius):
                    return cx, cy
            d += step
        return None, None


_global_grid = None  # grille partagée pour toute la session de build


def build_occupancy_grid_from_level(cell_size=50, max_extent=20000.0, max_cells_per_actor=200000):
    """Construit une OccupancyGrid à partir de la géométrie existante du level.

    Marque les bounding boxes de tous les StaticMeshActors comme occupées
    (approche conservative : on marque plus que la collision réelle → safe).

    À appeler en DÉBUT de session avant tout placement.

    GARDE-FOU CRITIQUE (ajouté 2026-07-03 après crash UE5 reproductible) :
    les levels basés sur le template par défaut gardent souvent SM_SkySphere
    (bounding box ~1 638 400 UU de rayon — voulu pour un skydome). Sans filtre,
    le balayage ci-dessous devient O((extent/cell_size)^2) → plusieurs milliards
    d'itérations dans une boucle imbriquée → freeze puis crash UE5 (OOM / thread
    de jeu bloqué indéfiniment). Root cause diagnostiquée sur AgentDemo : tout
    appel qui atteint cette fonction (directement, ou via setup_horror_room()
    avec with_enemy=True) plantait systématiquement tant que SM_SkySphere était
    présent. Deux filtres appliqués : (1) ignorer tout actor dont extent.x ou
    extent.y dépasse max_extent (skydome/backdrop, pas de la géométrie de salle
    réelle) ; (2) capper le nombre de cellules balayées par actor en filet de
    sécurité générique, au cas où un futur mesh démesuré ne soit pas un skydome
    évident.

    Exemple :
        grid = build_occupancy_grid_from_level()
        safe_spawn_enemy(1600, 0, grid=grid, label="Enemy_A")
    """
    global _global_grid
    actors_list = aeas().get_all_level_actors()

    all_x, all_y = [], []
    for a in actors_list:
        loc = a.get_actor_location()
        all_x.append(loc.x); all_y.append(loc.y)

    if not all_x:
        _global_grid = OccupancyGrid(-5000, 5000, -5000, 5000, cell_size)
        return _global_grid

    _global_grid = OccupancyGrid(
        min(all_x) - 1000, max(all_x) + 1000,
        min(all_y) - 1000, max(all_y) + 1000,
        cell_size
    )

    marked = 0
    skipped_flat = 0
    skipped_huge = 0
    for a in actors_list:
        if "StaticMeshActor" in a.get_class().get_name():
            origin, extent = a.get_actor_bounds(False)
            # Ignorer les dalles horizontales (sols, plafonds) :
            # leur extent.z << extent.x ou extent.y
            # Un mur a extent.z ≈ 150 UU ; un sol/plafond extent.z < 20 UU
            if extent.z < 30.0:
                skipped_flat += 1
                continue
            # Ignorer les bounding box démesurées (skydome, backdrop, etc.)
            if extent.x > max_extent or extent.y > max_extent:
                skipped_huge += 1
                unreal.log_warning(
                    f"[build_occupancy_grid_from_level] Ignoré (bbox énorme, "
                    f"probable skydome/backdrop) : {a.get_actor_label()} "
                    f"extent=({extent.x:.0f},{extent.y:.0f})")
                continue
            # Balayer la bounding box en grille et marquer chaque point
            x_steps = max(1, int(extent.x * 2 / cell_size))
            y_steps = max(1, int(extent.y * 2 / cell_size))
            # Filet de sécurité générique : cap le nombre total de cellules
            if (x_steps + 1) * (y_steps + 1) > max_cells_per_actor:
                skipped_huge += 1
                unreal.log_warning(
                    f"[build_occupancy_grid_from_level] Ignoré (trop de cellules: "
                    f"{(x_steps + 1) * (y_steps + 1)}) : {a.get_actor_label()}")
                continue
            for xi in range(x_steps + 1):
                for yi in range(y_steps + 1):
                    px = origin.x - extent.x + xi * (extent.x * 2 / max(1, x_steps))
                    py = origin.y - extent.y + yi * (extent.y * 2 / max(1, y_steps))
                    _global_grid.mark_occupied(px, py, cell_size)
            marked += 1

    unreal.log(f"[build_occupancy_grid_from_level] {marked} murs marqués, "
               f"{skipped_flat} sols/plafonds ignorés, {skipped_huge} bbox énormes ignorées")
    return _global_grid


def safe_place(cls_or_path, x, y, z_hint=0, actor_radius=60.0, grid=None, label=None):
    """Place un acteur avec garantie zéro overlap — 3 couches de vérification.

    Couche 1 — Floor snap (line trace)
        Trouve le vrai Z du sol. L'acteur est posé dessus, jamais dans le sol.

    Couche 2 — OccupancyGrid (fast)
        Vérifie que la position est libre dans la grille d'occupation.
        Si bloqué → trouve automatiquement la position libre la plus proche.

    Couche 3 — sphere_overlap_actors (moteur physique UE5 réel)
        Confirmation finale via le système de collision d'UE5.
        Si overlap → ne place pas (retourne None).

    grid : OccupancyGrid (optionnel, utilise _global_grid si None).
    Retourne l'acteur spawné ou None si placement impossible.
    """
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    g = grid if grid is not None else _global_grid
    # start_z = z_hint + 50 : légèrement au-dessus du z_hint (doit rester dans la pièce)
    # +300 mettait au-dessus du plafond → la trace frappait le plafond d'abord
    start_z = z_hint + 50

    # Marge de clearance verticale (bug corrigé le 2026-07-06, voir GAME_MEMORY.md
    # session 12) : sans cette marge, final_z = floor_z + actor_radius pose la sphère
    # de collision EXACTEMENT au contact du sol (0 UU de jeu). Confirmé par diagnostic
    # direct : sphere_overlap_actors() détecte ce contact exact comme un OVERLAP avec
    # le sol lui-même, faisant échouer Couche 3 sur un placement pourtant valide. +2 UU
    # suffit à sortir de la zone de contact exact sans changer le comportement perçu.
    _FLOOR_CLEARANCE = 2.0

    # ── Couche 1 : floor snap ────────────────────────────────────────────────
    hit = unreal.SystemLibrary.line_trace_single(
        world,
        unreal.Vector(x, y, start_z),
        unreal.Vector(x, y, z_hint - 500),
        unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
        False, [], unreal.DrawDebugTrace.NONE, True,
        unreal.LinearColor(1, 0, 0, 1), unreal.LinearColor(0, 1, 0, 1), 0.0
    )
    t = hit.to_tuple()
    if not t[0]:
        unreal.log_warning(f"[safe_place] Pas de sol sous ({int(x)},{int(y)}) — skip")
        return None
    # t[3] = Distance UU depuis start_z jusqu'au point d'impact
    floor_z = start_z - t[3]
    final_z  = floor_z + actor_radius + _FLOOR_CLEARANCE
    final_x, final_y = x, y

    # ── Couche 2 : OccupancyGrid ─────────────────────────────────────────────
    if g is not None and not g.is_free(x, y, actor_radius):
        nx_, ny_ = g.find_nearest_free(x, y, actor_radius)
        if nx_ is None:
            unreal.log_warning(f"[safe_place] Zone saturée autour de ({int(x)},{int(y)}) — skip")
            return None
        unreal.log_warning(
            f"[safe_place] ({int(x)},{int(y)}) bloqué → déplacé vers ({int(nx_)},{int(ny_)})"
        )
        final_x, final_y = nx_, ny_
        # Re-snap sol à la nouvelle position XY
        hit2 = unreal.SystemLibrary.line_trace_single(
            world,
            unreal.Vector(final_x, final_y, z_hint + 50),
            unreal.Vector(final_x, final_y, z_hint - 500),
            unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
            False, [], unreal.DrawDebugTrace.NONE, True,
            unreal.LinearColor(1, 0, 0, 1), unreal.LinearColor(0, 1, 0, 1), 0.0
        )
        t2 = hit2.to_tuple()
        if t2[0]:
            floor_z = (z_hint + 50) - t2[3]
            final_z = floor_z + actor_radius + _FLOOR_CLEARANCE

    # ── Couche 3 : moteur physique réel ──────────────────────────────────────
    # UE5.7 : utiliser unreal.Array(unreal.ObjectTypeQuery) vide = tous les types
    # Ne PAS passer une liste Python [] — provoque NoneType error
    #
    # BUG CORRIGE le 2026-07-06 (voir GAME_MEMORY.md session 12) : sphere_overlap_actors()
    # retourne None (pas une liste vide) quand AUCUN acteur n'est trouvé — le cas le plus
    # frequent (placement reussi, rien a signaler). L'ancienne version faisait directement
    # `[o for o in overlaps if ...]` sans filet, ce qui levait TypeError sur ce None et
    # etait alors avalé par le `except` ci-dessous → Couche 3 se desactivait SILENCIEUSEMENT
    # a chaque placement propre, et ne fonctionnait par accident que lorsqu'un overlap
    # existait reellement. `overlaps or []` traite explicitement le None comme "rien trouve"
    # au lieu de laisser une exception accidentelle produire le meme resultat pour la
    # mauvaise raison.
    try:
        obj_types = unreal.Array(unreal.ObjectTypeQuery)   # vide = all types en UE5.7
        ignore    = unreal.Array(unreal.Actor)
        overlaps  = unreal.SystemLibrary.sphere_overlap_actors(
            world,
            unreal.Vector(final_x, final_y, final_z),
            actor_radius,
            obj_types, unreal.Actor, ignore
        )
        geo_overlaps = [o for o in (overlaps or [])
                        if "StaticMeshActor" in o.get_class().get_name()]
        if geo_overlaps:
            names = [o.get_actor_label() for o in geo_overlaps[:3]]
            unreal.log_warning(
                f"[safe_place] Overlap physique réel @ ({int(final_x)},{int(final_y)}) "
                f"avec géométrie {names} — skip"
            )
            return None
    except Exception as e:
        unreal.log_warning(f"[safe_place] sphere_overlap_actors échoué ({e}) — couche 3 ignorée")

    # ── Spawn ─────────────────────────────────────────────────────────────────
    if isinstance(cls_or_path, str):
        # Ordre de tentatives :
        # 1. load_class  (fonctionne avec le suffixe .ClassName_C)
        # 2. load_blueprint_class (chemin sans suffixe)
        # 3. Auto-suffixe _C (chemin sans suffixe → tente asset_name_C)
        cls_obj = unreal.load_class(None, cls_or_path)
        if cls_obj is None:
            cls_obj = unreal.EditorAssetLibrary.load_blueprint_class(cls_or_path)
        if cls_obj is None and "." not in cls_or_path.rstrip("/").split("/")[-1]:
            asset_name = cls_or_path.rstrip("/").split("/")[-1]
            cls_obj = unreal.load_class(None, f"{cls_or_path}.{asset_name}_C")
    else:
        cls_obj = cls_or_path

    if cls_obj is None:
        unreal.log_warning(f"[safe_place] Classe introuvable : {cls_or_path}")
        return None

    actor = aeas().spawn_actor_from_class(
        cls_obj, unreal.Vector(final_x, final_y, final_z), unreal.Rotator(0, 0, 0)
    )
    if actor is None:
        unreal.log_warning("[safe_place] spawn_actor_from_class a retourné None")
        return None

    if label:
        actor.set_actor_label(label)

    # Marquer la grille après placement réussi
    if g is not None:
        g.mark_occupied(final_x, final_y, actor_radius)

    unreal.log(f"[safe_place] ✅ {label or 'actor'} @ ({int(final_x)},{int(final_y)},{int(final_z)})")
    return actor


# ══════════════════════════════════════════════════════
# VERIFICATION & SCREENSHOT — boucle de retour visuel
# ══════════════════════════════════════════════════════

def take_screenshot(name="viewport"):
    """Prend un screenshot du viewport UE5 et retourne le chemin du fichier.

    ⚠️ PEU FIABLE dans un contexte d'exécution agent (bridge MCP) : take_high_res_screenshot
    est mis en file d'attente pour un frame futur qui n'arrive parfois jamais avant la
    lecture du fichier → image noire ou périmée. Bug diagnostiqué 2026-07-03 (voir
    GAME_MEMORY.md). PRÉFÉRER capture_reference_screenshot() qui capture de façon
    synchrone et fiable, quitte à perdre la vue "réelle" du viewport éditeur au profit
    d'une position de caméra fixe que tu choisis.

    WORKFLOW OBLIGATOIRE après chaque étape majeure :
        path = take_screenshot("step1_geo")
        # puis Read(path) dans l'agent pour vérification visuelle

    Retourne le chemin absolu du fichier PNG, ou None si échec.
    """
    import glob as _glob, time as _time
    unreal.AutomationLibrary.take_high_res_screenshot(1920, 1080, f"{name}.png")
    _time.sleep(2.0)
    screenshot_dir = os.path.join(unreal.Paths.project_saved_dir(), "Screenshots", "WindowsEditor")
    matches = sorted(_glob.glob(os.path.join(screenshot_dir, f"{name}.png")), key=os.path.getmtime, reverse=True)
    if matches:
        unreal.log(f"[take_screenshot] {matches[0]}")
        return matches[0]
    all_shots = sorted(_glob.glob(os.path.join(screenshot_dir, "*.png")), key=os.path.getmtime, reverse=True)
    return all_shots[0] if all_shots else None


CAPTURE_RT_PATH = "/Game/Temp"
CAPTURE_RT_NAME = "TempCaptureRT"
CAPTURE_ACTOR_LABEL = "UTIL_SceneCapture"

def capture_reference_screenshot(x, y, z, pitch=0, yaw=0, roll=0, name="capture", resolution=(1280, 720)):
    """Screenshot fiable via SceneCaptureComponent2D — À UTILISER À LA PLACE de
    take_screenshot() partout où c'est possible.

    take_screenshot() (AutomationLibrary.take_high_res_screenshot) est mis en file
    d'attente pour un frame futur : dans un contexte d'exécution agent (bridge MCP),
    ce frame n'arrive parfois jamais avant la lecture du fichier → image noire, ou image
    périmée d'un appel précédent. Bug diagnostiqué et contourné le 2026-07-03 (voir
    GAME_MEMORY.md "Screenshots automatiques non fiables").

    capture_reference_screenshot() capture de façon synchrone (capture_every_frame=True
    sur le SceneCaptureComponent2D) depuis une position/rotation FIXES que tu contrôles —
    contrairement à take_screenshot() qui capture la vue aléatoire du viewport éditeur,
    celle-ci est reproductible et comparable d'un appel à l'autre (même angle = diff
    visuelle fiable avant/après une modif).

    Piège corrigé : le TextureRenderTarget2D créé par défaut est en RGBA16F (HDR) —
    l'exporter en ".png" écrit en réalité un fichier .exr illisible malgré l'extension.
    Forcer RTF_RGBA8 via set_editor_property AVANT la capture (render_target_format
    est en lecture seule via assignation directe `.render_target_format = ...`).

    x, y, z / pitch, yaw, roll : position et orientation de la caméra de capture.
    name : préfixe du fichier PNG généré dans Saved/Screenshots/WindowsEditor/.
    resolution : (largeur, hauteur).

    Retourne le chemin absolu du fichier PNG.

    Exemple :
        # Vue depuis le centre d'une salle, en regardant vers -X
        path = capture_reference_screenshot(0, 0, 170, pitch=0, yaw=180, name="salle_ouest")
        # → lire path avec Read tool pour vérification visuelle
    """
    at = unreal.AssetToolsHelpers.get_asset_tools()

    rt = unreal.load_asset(f"{CAPTURE_RT_PATH}/{CAPTURE_RT_NAME}")
    if rt is None:
        unreal.EditorAssetLibrary.make_directory(CAPTURE_RT_PATH)
        rt = at.create_asset(CAPTURE_RT_NAME, CAPTURE_RT_PATH, unreal.TextureRenderTarget2D,
                             unreal.TextureRenderTargetFactoryNew())
    rt.set_editor_property("size_x", resolution[0])
    rt.set_editor_property("size_y", resolution[1])
    rt.set_editor_property("render_target_format", unreal.TextureRenderTargetFormat.RTF_RGBA8)

    cap = actor_by_label(CAPTURE_ACTOR_LABEL)
    if cap is None:
        cap = aeas().spawn_actor_from_class(unreal.SceneCapture2D.static_class(),
                                            unreal.Vector(x, y, z),
                                            unreal.Rotator(pitch=pitch, yaw=yaw, roll=roll))
        cap.set_actor_label(CAPTURE_ACTOR_LABEL)
    else:
        cap.set_actor_location(unreal.Vector(x, y, z), False, False)
        cap.set_actor_rotation(unreal.Rotator(pitch=pitch, yaw=yaw, roll=roll), False)

    comp = cap.capture_component2d
    comp.texture_target = rt
    comp.capture_source = unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR
    comp.capture_scene()

    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    out_dir = os.path.join(unreal.Paths.project_saved_dir(), "Screenshots", "WindowsEditor")
    filename = f"{name}.png"
    unreal.RenderingLibrary.export_render_target(world, rt, out_dir, filename)
    path = os.path.join(out_dir, filename)
    unreal.log(f"[capture_reference_screenshot] {path}")
    return path


def get_live_viewport_transform():
    """Retourne la position/rotation EXACTE de la caméra du viewport éditeur actuel.

    Utile pour faire correspondre une capture_reference_screenshot() à ce que
    l'utilisateur voit réellement à l'écran au même instant — plutôt que deviner
    une position. Découvert/validé le 2026-07-03 lors du diagnostic du bug de
    capture "output identique quel que soit l'état de la scène" (voir GAME_MEMORY.md
    "capture_reference_screenshot() suspecté non-fiable") : comparer un screenshot
    pris à la position EXACTE de l'utilisateur, au moment où il regarde son écran,
    est le seul moyen fiable de valider que le pipeline de capture reflète la réalité.

    Retourne (x, y, z, pitch, yaw, roll).

    Exemple :
        x, y, z, pitch, yaw, roll = get_live_viewport_transform()
        path = capture_reference_screenshot(x, y, z, pitch=pitch, yaw=yaw, roll=roll, name="live_check")
        # Lire path avec Read tool, comparer avec ce que l'utilisateur rapporte voir à l'écran
    """
    loc, rot = unreal.EditorLevelLibrary.get_level_viewport_camera_info()
    return (loc.x, loc.y, loc.z, rot.pitch, rot.yaw, rot.roll)


def build_and_critique(build_fn, capture_pos=None, name="critique", *args, **kwargs):
    """Exécute une fonction de construction puis prend IMMÉDIATEMENT un screenshot
    pour que Claude Cowork (qui a la vision) puisse le lire et critiquer avant de
    déclarer quoi que ce soit "terminé".

    NE REMPLACE PAS le jugement visuel — c'est un raccourci qui garantit que
    l'étape "capture" n'est jamais oubliée après un build. Le vrai travail
    (lire le screenshot avec Read, juger si l'ambiance est bonne, corriger si
    besoin, recapturer) doit être fait par l'agent qui a appelé cette fonction,
    PAS par un agent texte-seul (voir CLAUDE.md — routage agent UE5 vs Claude Cowork :
    tout ce qui touche à l'ambiance doit passer par un agent avec vision).

    build_fn     : fonction à exécuter (ex: lambda: setup_horror_room("silent_hill", ...))
    capture_pos  : (x,y,z,pitch,yaw,roll) — si None, utilise get_live_viewport_transform()
                   (recommandé si un humain regarde l'écran en même temps que le build)
    name         : préfixe du fichier screenshot

    Retourne {"build_result": ..., "screenshot": path}. Le caller DOIT lire le
    screenshot avant de considérer la tâche terminée.
    """
    result = build_fn(*args, **kwargs)
    if capture_pos is None:
        capture_pos = get_live_viewport_transform()
    x, y, z, pitch, yaw, roll = capture_pos
    path = capture_reference_screenshot(x, y, z, pitch=pitch, yaw=yaw, roll=roll, name=name)
    print(f"[build_and_critique] Build terminé. Screenshot: {path}")
    print("[build_and_critique] ÉTAPE OBLIGATOIRE SUIVANTE : lire ce fichier avec Read "
          "et juger visuellement avant de dire que c'est fait.")
    return {"build_result": result, "screenshot": path}


def capture_pipeline_selftest(cleanup=True):
    """Test canari : confirme que capture_reference_screenshot() reflète bien un changement
    réel de scène, plutôt que de le supposer.

    Doute jamais reconfirmé depuis la session "quinquies" du 2026-07-03 (voir GAME_MEMORY.md) :
    7 captures consécutives étaient revenues pixel-identiques malgré des changements radicaux de
    scène (matériau, intensité ×44, mobilité de 8 lumières, fog à 0...). Tant que ce doute n'était
    pas retesté, toute validation d'ambiance basée sur capture_reference_screenshot() restait
    fragile. Ce test construit une scène isolée à (733000, 733000) — loin de toute géométrie de
    jeu réelle, même convention que les tests de test_suite.py qui spawnent de vrais acteurs —
    capture une baseline (sol + lumière faible), ajoute un cube + lumière colorée bien identifiable
    à côté (sans bloquer la première lumière — piège rencontré lors du premier essai manuel : un
    gros cube placé PILE devant la lumière donne un écran noir légitime, pas un bug de pipeline),
    recapture, puis compare les deux fichiers.

    Comparaison en pur stdlib (taille + MD5) : le Python embarqué UE5 n'a NI PIL NI numpy (vérifié
    2026-07-03) donc ce check ne peut PAS mesurer un vrai diff pixel — seulement détecter le cas
    grossier "fichier identique => pipeline probablement figé/périmé". Pour une analyse fine
    (% pixels changés, luminance...), passer les 2 chemins retournés à un diff PIL/numpy côté
    Claude Cowork (sandbox) — voir Tools/analyze_screenshot.py pour le pattern équivalent côté
    ambiance perceptuelle.

    cleanup : si True (défaut), détruit les acteurs de test après capture.

    Retourne {"baseline": path, "after": path, "size_baseline": int, "size_after": int,
              "md5_baseline": str, "md5_after": str, "identical": bool, "verdict": str}.

    Exemple :
        r = capture_pipeline_selftest()
        print(r["verdict"])
        # Puis, côté Claude Cowork : Read(r["baseline"]) et Read(r["after"]) pour confirmer
        # visuellement — ce test ne remplace pas le jugement visuel, il détecte juste le cas où
        # le pipeline ne bouge plus du tout, avant même d'y regarder.
    """
    import hashlib

    TX, TY = 733000.0, 733000.0
    a_sub = aeas()

    def _cleanup_canary():
        for a in a_sub.get_all_level_actors():
            if a.get_actor_label() and a.get_actor_label().startswith("CANARY_"):
                a_sub.destroy_actor(a)

    _cleanup_canary()  # résidu d'un appel précédent interrompu

    cube_mesh = unreal.load_asset("/Engine/BasicShapes/Cube.Cube")

    floor = a_sub.spawn_actor_from_class(unreal.StaticMeshActor.static_class(), unreal.Vector(TX, TY, 0))
    floor.set_actor_label("CANARY_Floor")
    floor.set_actor_scale3d(unreal.Vector(20, 20, 1))
    floor.get_component_by_class(unreal.StaticMeshComponent.static_class()).set_static_mesh(cube_mesh)

    light = a_sub.spawn_actor_from_class(unreal.PointLight.static_class(), unreal.Vector(TX, TY, 300))
    light.set_actor_label("CANARY_Light")
    lc = light.point_light_component
    lc.set_editor_property("intensity", 5000.0)
    lc.set_editor_property("attenuation_radius", 1500.0)
    lc.set_mobility(unreal.ComponentMobility.MOVABLE)

    path_baseline = capture_reference_screenshot(TX, TY - 400, 150, pitch=0, yaw=90, name="canary_selftest_baseline")

    # Cube + lumière décalés SUR LE CÔTÉ (x+150) — ne bloquent pas CANARY_Light, sinon un
    # écran noir serait un vrai résultat physique (occlusion) et non un signal de pipeline figé.
    cube = a_sub.spawn_actor_from_class(unreal.StaticMeshActor.static_class(), unreal.Vector(TX + 150, TY - 250, 100))
    cube.set_actor_label("CANARY_SideCube")
    cube.set_actor_scale3d(unreal.Vector(1.2, 1.2, 1.2))
    cube.get_component_by_class(unreal.StaticMeshComponent.static_class()).set_static_mesh(cube_mesh)

    side_light = a_sub.spawn_actor_from_class(unreal.PointLight.static_class(), unreal.Vector(TX + 150, TY - 250, 200))
    side_light.set_actor_label("CANARY_SideLight")
    slc = side_light.point_light_component
    slc.set_editor_property("light_color", unreal.Color(0, 0, 255, 255))
    slc.set_editor_property("intensity", 15000.0)
    slc.set_editor_property("attenuation_radius", 400.0)
    slc.set_mobility(unreal.ComponentMobility.MOVABLE)

    path_after = capture_reference_screenshot(TX, TY - 400, 150, pitch=0, yaw=90, name="canary_selftest_after")

    if cleanup:
        _cleanup_canary()

    def _md5(p):
        with open(p, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()

    size_b, size_a = os.path.getsize(path_baseline), os.path.getsize(path_after)
    md5_b, md5_a = _md5(path_baseline), _md5(path_after)
    identical = (md5_b == md5_a)

    if identical:
        verdict = ("SUSPECT: fichiers identiques (meme MD5) malgre un changement de scene "
                   "radical -> pipeline de capture probablement fige/perime, voir GAME_MEMORY.md "
                   "'quinquies' 2026-07-03. NE PAS FAIRE CONFIANCE a capture_reference_screenshot() "
                   "avant investigation (focus fenetre editeur ? throttling Slate ?).")
    else:
        verdict = ("OK: fichiers differents (MD5 differents, tailles {} vs {} octets) -> le "
                   "pipeline reflete bien le changement de scene.".format(size_b, size_a))

    unreal.log("[capture_pipeline_selftest] " + verdict)

    return {
        "baseline": path_baseline, "after": path_after,
        "size_baseline": size_b, "size_after": size_a,
        "md5_baseline": md5_b, "md5_after": md5_a,
        "identical": identical, "verdict": verdict,
    }


def safe_spawn(cls_or_path, x, y, z=100, label=None, grid=None):
    """Spawn un acteur avec garantie zéro overlap (utilise safe_place).

    Couches : floor snap → OccupancyGrid → sphere_overlap_actors.
    grid : OccupancyGrid optionnel (utilise _global_grid si None).
    """
    return safe_place(cls_or_path, x, y, z_hint=z, actor_radius=50.0,
                      grid=grid, label=label)


def safe_spawn_enemy(x, y, z=100, label="Enemy", grid=None):
    """Spawn un BP_IA_Enemy avec garantie zéro overlap + tag 'Enemy' auto.

    3 couches : floor snap → OccupancyGrid → sphere_overlap_actors (physique réelle).
    Si la position est bloquée → déplacement automatique vers la plus proche libre.

    grid : OccupancyGrid via build_occupancy_grid_from_level() (optionnel).

    Exemple :
        grid = build_occupancy_grid_from_level()
        safe_spawn_enemy(1600, 0, grid=grid, label="Enemy_Endormi")
    """
    ENEMY_RADIUS = 60.0  # rayon capsule + marge (AgentRadius UE5 = 35 UU)

    actor = safe_place(
        "/Game/HorrorGame/IA/Blueprint/Enemy/BP_IA_Enemy.BP_IA_Enemy_C",
        x, y, z_hint=z,
        actor_radius=ENEMY_RADIUS,
        grid=grid if grid is not None else _global_grid,
        label=label
    )
    if actor:
        actor.tags = [unreal.Name("Enemy")]
        unreal.log(f"[safe_spawn_enemy] {label} tag=Enemy ✅")
    return actor


print("[ue5_utils] loaded - from ue5_utils import *")

# ══════════════════════════════════════════════════════
# BPGraph DSL — cable tout un graphe en 1 appel Python
# ══════════════════════════════════════════════════════

class NodeRef:
    """Reference a un noeud dans un BPGraph en construction."""
    def __init__(self, graph, nid):
        self._g = graph
        self.nid = nid

    def then(self, other, from_pin="then", to_pin="execute"):
        self._g._conn(self.nid, from_pin, other.nid, to_pin)
        return other

    def __rshift__(self, other):
        return self.then(other)

    def data(self, other, fp, tp):
        self._g._conn(self.nid, fp, other.nid, tp)
        return other


class BPGraph:
    """Builder de graphe Blueprint. Accumule noeuds + connexions
    puis les envoie en UN seul appel C++ via BatchWireGraph.

    Exemple:
        bp = load_bp("/Game/Blueprints/BP_Door")
        g  = BPGraph(bp, "EventGraph")
        ev   = g.event("ActorBeginOverlap")
        cast = g.cast("/Game/BP_Player.BP_Player_C", x=300)
        fn   = g.call("OpenDoor", "/Script/Engine.Actor", x=600)
        ev >> cast >> fn
        g.wire_and_compile()
    """
    def __init__(self, bp, graph_name="EventGraph"):
        self._bp  = bp
        self._gn  = graph_name
        self._nodes = []
        self._conns = []
        self._ctr   = 0

    def _nid(self):
        n = "n{}".format(self._ctr); self._ctr += 1; return n

    def _node(self, d):
        nid = self._nid()
        d["id"] = nid
        self._nodes.append(d)
        return NodeRef(self, nid)

    def _conn(self, f, fp, t, tp):
        self._conns.append({"from": f, "fp": fp, "to": t, "tp": tp})

    def event(self, name, x=0, y=0):
        return self._node({"type": "event", "name": name, "x": x, "y": y})

    def custom_event(self, name, x=0, y=0):
        return self._node({"type": "custom_event", "name": name, "x": x, "y": y})

    def call(self, fn, cls, x=0, y=0, defaults=None):
        d = {"type": "function", "fn": fn, "cls": cls, "x": x, "y": y}
        if defaults: d["defaults"] = defaults
        return self._node(d)

    def cast(self, cls, x=0, y=0):
        return self._node({"type": "cast", "cls": cls, "x": x, "y": y})

    def branch(self, x=0, y=0):
        return self._node({"type": "branch", "x": x, "y": y})

    def foreach(self, x=0, y=0):
        return self._node({"type": "macro", "name": "ForEachLoop", "x": x, "y": y})

    def macro(self, name, x=0, y=0):
        return self._node({"type": "macro", "name": name, "x": x, "y": y})

    def var_get(self, var, x=0, y=0):
        return self._node({"type": "var_get", "var": var, "x": x, "y": y})

    def var_set(self, var, x=0, y=0):
        return self._node({"type": "var_set", "var": var, "x": x, "y": y})

    def sequence(self, x=0, y=0):
        return self._node({"type": "sequence", "x": x, "y": y})

    def conn(self, fr, fp, to, tp):
        self._conn(fr.nid, fp, to.nid, tp)
        return self

    def wire(self):
        import json
        payload = json.dumps({"nodes": self._nodes, "connections": self._conns})
        result  = bpes().batch_wire_graph(self._bp, self._gn, payload)
        unreal.log("[BPGraph] {}".format(result))
        return result

    def wire_and_compile(self):
        """Cable + compile, avec verification anti-regression AUTOMATIQUE par defaut
        (2026-07-06) : encapsule l'operation dans safe_modify_plugin(), plus besoin
        de l'appeler separement pour un cablage BPGraph. Leve une Exception si cette
        modification casse un test qui passait avant (regression reelle), ou si la
        baseline elle-meme est deja rouge.

        Cout : ~10-20s au lieu de <1s (deux passages de la suite de 26 tests).
        Scope volontairement limite a CETTE methode — PAS a compile_bp() (utilise
        en interne par test_suite.py -> boucle infinie sinon) ni a save() (usage
        generique level design, sans baseline naturelle, cout injustifie sur un
        simple deplacement de lumiere).

        Pour l'ancien comportement sans verification (iteration rapide sur un BP
        jetable) : appeler self.wire() puis compile_bp(self._bp) separement, en
        connaissance de cause — safe_modify_plugin() reste alors sautee.
        """
        def _do():
            r = self.wire()
            compile_bp(self._bp)
            return r
        return safe_modify_plugin(_do)

    def reset(self):
        self._nodes = []; self._conns = []; self._ctr = 0
        return self


# ══════════════════════════════════════════════════════
# BOUCLE AUTONOME — run_steps()
# Exécute N étapes Python en séquence dans un contexte partagé.
# Auto-stop sur erreur, log du résultat, save() automatique.
# ══════════════════════════════════════════════════════

def run_steps(steps, stop_on_error=True, auto_save=True, verbose=True):
    """Exécute une séquence d'étapes Python de façon autonome.

    steps : dict ordonné { "nom_etape": "code python" }
    stop_on_error : arrêt dès la première erreur (défaut True)
    auto_save  : appelle save() à la fin si tout est OK
    verbose    : affiche le résultat de chaque étape

    Retourne un dict { nom: {"status": "OK"|"ERROR", "output": str} }

    Exemple :
        run_steps({
            "Nettoyer zone": "actors = [...]; [destroy(a) for a in actors]",
            "Ajouter lumière": "point_light(700, 0, 250, intensity=2000)",
            "Vérifier": "print(f'{len(all_actors())} acteurs total')",
        })
    """
    import io, sys, traceback

    shared = {}
    exec("from ue5_utils import *\nimport unreal", shared)

    results = {}
    all_ok = True
    total = len(steps)

    print(f"[run_steps] Démarrage — {total} étape(s)")

    for i, (name, code) in enumerate(steps.items(), 1):
        print(f"\n[{i}/{total}] {name}...")
        buf = io.StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = buf
        try:
            exec(code, shared)
            sys.stdout, sys.stderr = old_out, old_err
            output = buf.getvalue().strip()
            results[name] = {"status": "OK", "output": output}
            if verbose:
                preview = output[:200] if output else "(pas de sortie)"
                print(f"  ✅ OK — {preview}")
        except Exception:
            sys.stdout, sys.stderr = old_out, old_err
            tb = traceback.format_exc()
            results[name] = {"status": "ERROR", "output": tb}
            all_ok = False
            print(f"  ❌ ERREUR :\n{tb}")
            if stop_on_error:
                print(f"[run_steps] Arrêt à l'étape '{name}'.")
                break

    status_str = "SUCCÈS" if all_ok else "ÉCHEC"
    print(f"\n[run_steps] {status_str} — {sum(1 for r in results.values() if r['status']=='OK')}/{total} étapes OK")

    if auto_save and all_ok:
        save()
        print("[run_steps] Level sauvegardé.")

    return results


def retry_step(step_name, corrected_code, previous_results, shared_ctx=None):
    """Re-exécute une étape avec du code corrigé après une erreur.
    Retourne le résultat de la nouvelle tentative.
    """
    import io, sys, traceback
    shared = shared_ctx or {}
    if not shared:
        exec("from ue5_utils import *\nimport unreal", shared)

    buf = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = buf
    try:
        exec(corrected_code, shared)
        sys.stdout, sys.stderr = old_out, old_err
        output = buf.getvalue().strip()
        result = {"status": "OK", "output": output}
        print(f"[retry] ✅ '{step_name}' corrigé — {output[:150]}")
    except Exception:
        sys.stdout, sys.stderr = old_out, old_err
        tb = traceback.format_exc()
        result = {"status": "ERROR", "output": tb}
        print(f"[retry] ❌ '{step_name}' toujours en erreur :\n{tb}")

    if previous_results is not None:
        previous_results[step_name] = result
    return result


# ══════════════════════════════════════════════════════
# GARDE-FOU D'INTÉGRITÉ FICHIER — Content/Python/ réel
# ══════════════════════════════════════════════════════
#
# Deux fois documenté dans GAME_MEMORY.md (sessions 15-16) : le pont
# Windows↔sandbox Linux de Claude Cowork a corrompu silencieusement des
# fichiers de ce projet — une fois avec des octets NUL de padding en fin de
# fichier après un edit qui raccourcit, une autre fois avec une troncature
# mi-instruction — sans qu'aucun outil ne lève d'erreur au moment de l'écriture.
# `check_repo_integrity.py` (repo public ue5-agent-verified-levelgen) protège
# déjà la copie de vitrine avec ce même principe (aucun octet NUL, ast.parse
# valide) mais ne tourne QUE sur cette copie — jamais sur les fichiers réels
# de Content/Python/ que le jeu charge réellement. Ce qui suit ferme ce trou
# ici, côté fichiers réels, et est branché automatiquement dans safe_write()/
# safe_append() plutôt que de dépendre d'un commit git ou d'une relecture
# manuelle.

# Fichiers legacy avec une incompatibilite Python <3.12 preexistante
# (backslash dans la partie expression d'un f-string — invalide avant 3.12,
# et l'interpreteur embarque dans UE5.7 est < 3.12), decouverte PAR ce
# garde-fou lui-meme le jour de sa creation, sans aucun rapport avec de la
# corruption : blueprint_modifier.py / paste_helpers.py sont des scripts
# manuels de generation de T3D a coller dans l'editeur de graphe (workflow
# pre-BatchWireGraph/BPGraph, confirme non importes par le reste du pipeline
# actuel via grep). Une partie des occurrences a ete corrigee (variables
# pre-quotees), le reste est une toile de guillemets imbriques trop dense
# pour une correction mecanique sans risque — voir GAME_MEMORY.md pour la
# decision (reecrire completement ou supprimer, non tranchee a ce jour).
# Exemptes UNIQUEMENT du check ast.parse ci-dessous ; le check NUL bytes
# (le vrai signal de corruption) reste actif dessus comme sur tout le reste.
# Ne jamais ajouter un fichier ici pour faire taire un vrai probleme sans
# une raison documentee equivalente.
_INTEGRITY_PARSE_EXEMPT = {"blueprint_modifier.py", "paste_helpers.py"}


def verify_file_integrity(path, expected_text=None, check_parse=True):
    """Vérifie qu'un fichier écrit sur disque n'est pas silencieusement
    corrompu. Lit TOUJOURS en binaire (jamais en mode texte) pour ne rater
    aucun octet NUL — un f.read() en mode texte laisse passer un octet NUL
    au milieu d'une chaîne sans lever d'erreur, ce qui a fait rater ce bug
    par le passé.

    Vérifie, dans l'ordre :
      1. Absence totale d'octets NUL (signature de troncature/padding corrompu).
      2. Si expected_text est fourni : égalité EXACTE caractère par caractère
         avec le contenu attendu (pas une heuristique de taille approximative).
      3. Si le chemin finit en .py ET check_parse=True : le contenu parse
         comme Python valide (ast.parse) — attrape aussi les troncatures
         mi-instruction qui laissent un fichier syntaxiquement invalide même
         sans octet NUL. check_parse=False sert uniquement à l'exemption
         documentée ci-dessus (_INTEGRITY_PARSE_EXEMPT) — ne pas l'utiliser
         ailleurs sans la même justification écrite.

    Ne lève jamais d'exception elle-même — retourne (True, "") ou
    (False, message). C'est à l'appelant (safe_write/safe_append, ou un audit
    manuel) de décider si l'échec doit être bloquant.
    """
    import os
    if not os.path.isfile(path):
        return False, "fichier introuvable: {}".format(path)

    data = open(path, "rb").read()

    if b"\x00" in data:
        count = data.count(b"\x00")
        first = data.index(b"\x00")
        return False, "{} octet(s) NUL trouve(s) (premier a l'offset {}) — fichier probablement tronque/corrompu".format(count, first)

    try:
        actual_text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        return False, "decode UTF-8 echoue: {}".format(e)

    if expected_text is not None:
        # Comparaison sur texte normalise (\r\n -> \n) : open(path,"w") en
        # mode texte traduit chaque "\n" ecrit en "\r\n" sur Windows (universal
        # newlines), donc une lecture binaire brute ne matchera JAMAIS un
        # expected_text ecrit avec de simples "\n" — decouvert en testant cette
        # fonction elle-meme (safe_write levait une Exception sur CHAQUE
        # ecriture). Ce n'est pas de la corruption, juste la traduction normale
        # de fin de ligne ; on la neutralise avant de comparer. Le check NUL
        # bytes plus haut, lui, reste sur les octets bruts et n'est pas affecte.
        actual_normalized = actual_text.replace("\r\n", "\n")
        expected_normalized = expected_text.replace("\r\n", "\n")
        if actual_normalized != expected_normalized:
            m = min(len(actual_normalized), len(expected_normalized))
            i = 0
            while i < m and actual_normalized[i] == expected_normalized[i]:
                i += 1
            return False, "contenu different de l'attendu a partir du caractere {} (attendu {} chars, obtenu {} chars, fins de ligne normalisees)".format(
                i, len(expected_normalized), len(actual_normalized))

    if path.endswith(".py") and check_parse:
        import ast
        try:
            ast.parse(actual_text, filename=path)
        except (SyntaxError, ValueError) as e:
            return False, "ne parse pas comme Python valide: {}".format(e)

    return True, ""


def scan_content_python_integrity(verbose=True):
    """Audit d'intégrité de TOUS les .py de Content/Python/ — équivalent, pour
    les fichiers RÉELS utilisés par le jeu, de check_repo_integrity.py qui ne
    protège que la copie de vitrine du repo public. À lancer en début/fin de
    session, ou après tout doute (édition suspecte, sync, crash, relecture
    du shell sandbox qui semble différer de ce que montre l'outil de lecture).

    Les fichiers listés dans _INTEGRITY_PARSE_EXEMPT restent vérifiés pour les
    octets NUL (le vrai signal de corruption) mais pas pour le parsing Python
    — un souci de syntaxe déjà connu et documenté chez eux est loggé à part
    en warning, sans faire échouer l'audit ni les tests de régression.

    Retourne la liste des (path, message) en échec bloquant — liste vide =
    tout sain (les warnings des fichiers exemptés n'y figurent pas).
    """
    import os, glob
    d = os.path.dirname(os.path.abspath(__file__))
    problems = []
    warnings = []
    all_py = sorted(glob.glob(os.path.join(d, "*.py")))
    for f in all_py:
        base = os.path.basename(f)
        exempt = base in _INTEGRITY_PARSE_EXEMPT
        ok, msg = verify_file_integrity(f, check_parse=not exempt)
        if not ok:
            problems.append((f, msg))
        elif exempt:
            # NUL/decode OK, mais on sait que le parsing échoue — le confirmer
            # explicitement et le logger en warning plutôt que de le taire.
            parse_ok, parse_msg = verify_file_integrity(f, check_parse=True)
            if not parse_ok:
                warnings.append((f, parse_msg))
    if verbose:
        if problems:
            unreal.log_error("[INTEGRITY] {} probleme(s) trouve(s) dans Content/Python/ :".format(len(problems)))
            for f, msg in problems:
                unreal.log_error("  - {}: {}".format(os.path.basename(f), msg))
        else:
            unreal.log("[INTEGRITY] OK — tous les .py de Content/Python/ sont sains ({} fichiers)".format(len(all_py)))
        for f, msg in warnings:
            unreal.log("[INTEGRITY][warning connu, non bloquant] {}: {}".format(os.path.basename(f), msg))
    return problems


def safe_write(path, content, must_contain=None):
    """Ecrit un fichier de facon ATOMIQUE et verifie le contenu AVANT de toucher
    le fichier final. Leve une Exception si ecriture ratee, token attendu absent,
    OU si verify_file_integrity() detecte une corruption (octets NUL, contenu
    different de l'attendu, syntaxe Python invalide) — voir section
    "GARDE-FOU D'INTÉGRITÉ FICHIER" plus haut pour le bug que ceci ferme.

    Ecriture atomique (ajoute 2026-07-08) : le contenu est d'abord ecrit dans un
    fichier temporaire (meme dossier => meme systeme de fichiers), verifie
    integralement, et SEULEMENT si la verification passe, bascule sur le fichier
    final via os.replace() (atomique sous Windows et POSIX). Avant ce changement,
    l'ecriture visait DIRECTEMENT le fichier final puis verifiait apres coup : si
    l'ecriture elle-meme etait corrompue par le pont Windows<->sandbox Linux de
    Cowork (NUL de padding, troncature — voir CLAUDE.md sessions 15-16), le
    fichier corrompu passait un instant reel sur disque, a l'emplacement que UE5
    charge, avant que l'Exception ne soit levee. Avec l'ecriture atomique, une
    ecriture ratee ne touche JAMAIS le fichier final : le pire cas est un fichier
    .tmp orphelin nettoye dans le finally, jamais une corruption du vrai fichier.

    Usage: safe_write(path, content, must_contain=["BatchWireGraph","FindPinByName"])
    """
    import os

    tmp_path = "{}.tmp_safewrite_{}".format(path, os.getpid())
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)

        ok, msg = verify_file_integrity(tmp_path, expected_text=content)
        if not ok:
            raise Exception("safe_write ECHEC integrite (fichier final NON touche) dans {}: {}".format(path, msg))

        if must_contain:
            for needle in (must_contain if isinstance(must_contain, list) else [must_contain]):
                if needle not in content:
                    raise Exception("safe_write ECHEC (fichier final NON touche): '{}' manquant dans {}".format(needle, path))

        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    unreal.log("[safe_write] OK {} ({} chars, ecriture atomique + integrite verifiee octet par octet)".format(os.path.basename(path), len(content)))
    return len(content)


# ══════════════════════════════════════════════════════
# AXE 1 — Boucle auto-correction
# read_log(), start_pie(), stop_pie(), test_in_pie()
# ══════════════════════════════════════════════════════

def read_log(n=80, filter_kw=None):
    """Lit les n dernières lignes du log UE5 (Saved/Logs/HorrorGame.log).
    filter_kw : si fourni, ne retourne que les lignes contenant ce mot-clé.
    Utilisation : print(read_log(50, "Error"))
    """
    import os, glob
    log_dir = os.path.join(unreal.Paths.project_saved_dir(), "Logs")
    logs = sorted(glob.glob(os.path.join(log_dir, "*.log")), key=os.path.getmtime, reverse=True)
    if not logs:
        return "Aucun fichier log trouvé."
    with open(logs[0], encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    if filter_kw:
        lines = [l for l in lines if filter_kw.lower() in l.lower()]
    return "".join(lines[-n:])

def start_pie():
    """Lance le Play In Editor (mode joueur)."""
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    les.editor_request_begin_play()

def stop_pie():
    """Arrête le Play In Editor."""
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    les.editor_request_end_play()

def is_pie_running():
    """Retourne True si le PIE est actuellement actif."""
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    return les.is_in_play_in_editor()

def test_in_pie(duration=5.0):
    """Lance PIE, attend duration secondes, arrête, retourne les erreurs du log.
    Utiliser pour détecter les crashes/erreurs Blueprint runtime.
    """
    import time
    start_pie()
    time.sleep(duration)
    stop_pie()
    time.sleep(1.0)
    errors = read_log(100, "Error")
    warnings = read_log(50, "Warning")
    return f"=== ERREURS ===\n{errors}\n=== WARNINGS ===\n{warnings}"

def check_errors():
    """Raccourci : lit les 30 dernières erreurs du log. Appeler après une exécution."""
    return read_log(30, "Error") or "Aucune erreur trouvée."


# ══════════════════════════════════════════════════════
# AXE 2 — Génération de mécaniques complètes
# create_trigger_zone(), create_door_bp(), create_sequence_puzzle()
# ══════════════════════════════════════════════════════

def create_trigger_zone(bp_path, trigger_event="ActorBeginOverlap",
                        action_fn="PrintString", action_cls="/Script/Engine.KismetSystemLibrary",
                        action_defaults=None, x=0, y=0):
    """Crée dans un BP existant : Overlap → action.
    Exemple : create_trigger_zone("/Game/MyBP", action_defaults={"InString": "Triggered!"})
    """
    bp = load_bp(bp_path)
    g = BPGraph(bp, "EventGraph")
    ev = g.event(trigger_event, x=x, y=y)
    fn = g.call(action_fn, action_cls, x=x+400, y=y,
                defaults=action_defaults or {})
    ev >> fn
    return g.wire_and_compile()

def create_door_mechanism(bp_path, open_z_offset=300.0):
    """Génère dans bp_path un système d'ouverture de porte :
    E pressé → SetActorLocation vers le haut (simule porte coulissante).
    """
    bp = load_bp(bp_path)
    g = BPGraph(bp, "EventGraph")
    ev     = g.event("InputAction Interact", x=0, y=0)
    vg_loc = g.call("GetActorLocation", "/Script/Engine.Actor", x=250, y=0)
    fn_add = g.call("Add_VectorVector", "/Script/Engine.KismetMathLibrary", x=500, y=0,
                    defaults={"B": f"(X=0.0,Y=0.0,Z={open_z_offset})"})
    fn_set = g.call("SetActorLocation", "/Script/Engine.Actor", x=750, y=0)
    ev >> vg_loc >> fn_add >> fn_set
    return g.wire_and_compile()

def create_sequence_puzzle(zone_center_x, zone_center_y, n_switches=3):
    """Spawn n interrupteurs BP_LightSwitch dans la zone.
    Le joueur doit tous les activer pour déclencher la victoire.
    (Scaffolding : à relier manuellement à la win condition.)
    """
    spacing = 300
    spawned = []
    for i in range(n_switches):
        x = zone_center_x + (i - n_switches//2) * spacing
        a = spawn("/Game/IA/Blueprint/BP_LightSwitch.BP_LightSwitch_C",
                  x=x, y=zone_center_y, z=50, label=f"Puzzle_Switch_{i+1}")
        spawned.append(a)
        print(f"Switch {i+1} spawné @ ({x:.0f}, {zone_center_y:.0f}, 50)")
    return spawned


# ══════════════════════════════════════════════════════
# AXE 3 — Mémoire persistante
# update_memory(), append_todo(), mark_done()
# ══════════════════════════════════════════════════════

def _memory_path():
    import os
    return os.path.join(unreal.Paths.project_dir(), "GAME_MEMORY.md")

def update_memory(section, content):
    """Met à jour une section de GAME_MEMORY.md.
    section : titre exact de la section (ex: "## TODO — Prochaines sessions")
    content : nouveau contenu à écrire sous cette section (remplace jusqu'à la prochaine ##)
    Si la section n'existe pas, l'ajoute à la fin.
    """
    import re, datetime
    path = _memory_path()
    with open(path, encoding="utf-8") as f:
        text = f.read()

    # Mettre à jour la date
    text = re.sub(r"Dernière mise à jour : .*",
                  f"Dernière mise à jour : {datetime.date.today().isoformat()}", text)

    # Remplacer ou ajouter la section
    pattern = rf"({re.escape(section)}\n)(.*?)(?=\n## |\Z)"
    replacement = f"{section}\n{content}\n"
    if re.search(pattern, text, re.DOTALL):
        text = re.sub(pattern, replacement, text, flags=re.DOTALL)
    else:
        text = text.rstrip() + f"\n\n{section}\n{content}\n"

    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[update_memory] Section '{section}' mise à jour.")

def append_todo(item):
    """Ajoute un item TODO dans GAME_MEMORY.md."""
    path = _memory_path()
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # Insère après la ligne "### Idées futures" ou à la fin de la section TODO
    new_line = f"- [ ] {item}\n"
    if "### Idées futures" in text:
        text = text.replace("### Idées futures\n", f"### Idées futures\n{new_line}")
    else:
        text += f"\n{new_line}"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[append_todo] Ajouté : {item}")

def mark_done(item_substring):
    """Marque un TODO comme terminé dans GAME_MEMORY.md (- [ ] → - [x])."""
    path = _memory_path()
    with open(path, encoding="utf-8") as f:
        text = f.read()
    import re
    pattern = rf"- \[ \] (.*{re.escape(item_substring)}.*)"
    text = re.sub(pattern, r"- [x] \1", text)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[mark_done] Marqué terminé : '{item_substring}'")

def memory_snapshot():
    """Affiche un résumé de GAME_MEMORY.md (TODO en cours uniquement)."""
    path = _memory_path()
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    todos = [l.strip() for l in lines if l.strip().startswith("- [ ]")]
    done  = [l.strip() for l in lines if l.strip().startswith("- [x]")]
    print("=== GAME MEMORY SNAPSHOT ===")
    print(f"TODO ({len(todos)}) :")
    for t in todos: print(f"  {t}")
    print(f"DONE ({len(done)}) :")
    for d in done: print(f"  {d}")


def safe_append(path, content, must_contain=None):
    """Ajoute du contenu a un fichier de facon ATOMIQUE (ajoute 2026-07-08) et
    verifie. must_contain cherche dans le fichier entier. Leve une Exception si
    le contenu final ne se termine pas exactement par le contenu ajoute, ou si
    verify_file_integrity() detecte une corruption (octets NUL, syntaxe Python
    invalide) — voir section "GARDE-FOU D'INTÉGRITÉ FICHIER" plus haut.

    Comme safe_write() : lit l'ancien contenu, construit le contenu final EN
    MEMOIRE, l'ecrit dans un fichier temporaire, verifie integralement, et
    bascule seulement ensuite via os.replace(). L'ancienne version faisait un
    open(path, "a") en ecriture DIRECTE sur le fichier reel — exactement le
    chemin qui a produit la corruption documentee (NUL de padding, CLAUDE.md
    sessions 15-16) lors d'un edit qui modifie un fichier existant deja present
    sur disque. Cette version ne touche jamais le fichier reel avant d'avoir
    confirme que le contenu complet (ancien + nouveau) est sain."""
    import os

    with open(path, encoding="utf-8") as f:
        old_content = f.read()

    new_content = old_content + content

    if not new_content.endswith(content):
        raise Exception("safe_append ECHEC: incoherence interne de concatenation pour {} (ne devrait jamais arriver)".format(path))

    tmp_path = "{}.tmp_safeappend_{}".format(path, os.getpid())
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        ok, msg = verify_file_integrity(tmp_path, expected_text=new_content)
        if not ok:
            raise Exception("safe_append ECHEC integrite (fichier final NON touche) dans {}: {}".format(path, msg))

        if must_contain:
            for needle in (must_contain if isinstance(must_contain, list) else [must_contain]):
                if needle not in new_content:
                    raise Exception("safe_append ECHEC (fichier final NON touche): '{}' manquant dans {}".format(needle, path))

        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    unreal.log("[safe_append] OK {} ({} chars total, ecriture atomique + integrite verifiee)".format(os.path.basename(path), len(new_content)))
    return len(new_content)


# ══════════════════════════════════════════════════════
# ANTI-REGRESSION AUTOMATIQUE — safe_modify_plugin()
# ══════════════════════════════════════════════════════
#
# Avant cette fonction, "lancer run_all() avant/apres toute modif C++/Python"
# n'etait qu'une regle ECRITE dans CLAUDE.md — rien dans le code ne l'imposait.
# Un agent (ou un humain) pressé pouvait modifier le plugin et sauvegarder sans
# avoir lancé un seul test, exactement comme il pouvait autrefois appeler save()
# sans avoir passé run_verify() avant que ce garde-fou existe pour le level design.
# safe_modify_plugin() transforme cette convention en mécanisme : baseline avant,
# modification, re-check après, comparaison test par test — pas juste "ça passe
# globalement" mais "CE test précis, qui passait avant, échoue maintenant".

def safe_modify_plugin(fn, *args, **kwargs):
    """Encapsule une modification risquée du plugin (C++/Python, BP wiring, etc.)
    avec un filet de sécurité anti-régression automatique.

    Principe (identique à fix_all()+run_verify() avant save() pour le level design,
    appliqué ici au CODE du plugin plutôt qu'à la géométrie du niveau) :
        1. Lance test_suite.run_all() AVANT la modification → baseline.
        2. Si la baseline elle-même a des échecs → arrêt immédiat (pas de baseline
           fiable, inutile de comparer après).
        3. Exécute fn(*args, **kwargs) — la modification à risque.
        4. Relance test_suite.run_all() APRès la modification.
        5. Compare test par test (pas juste le score global) : si un test qui
           était [OK] en baseline est [FAIL] après → régression réelle détectée
           → lève une Exception. Un test déjà cassé avant qui l'est encore après
           n'est PAS une régression (ce n'est pas la faute de cette modification).

    fn : callable sans argument obligatoire qui effectue la modification
         (ex: une fonction qui appelle BPGraph(...).wire_and_compile(), ou qui
         réimporte un module C++ après recompilation).

    Retourne le résultat de fn() si aucune régression n'est détectée.
    Lève une Exception si :
      - la baseline elle-même échoue (tests déjà cassés avant modif — corriger
        d'abord, ne pas empiler une nouvelle modif sur une base déjà rouge) ;
      - une régression réelle est détectée après la modif.

    Exemple :
        def ma_modif():
            bp = load_bp("/Game/Path/BP_Name")
            g  = BPGraph(bp, "EventGraph")
            ev = g.event("BeginPlay")
            fn = g.call("PrintString", "/Script/Engine.KismetSystemLibrary")
            ev >> fn
            return g.wire_and_compile()

        result = safe_modify_plugin(ma_modif)
        # → lève une Exception si la modif casse un test qui passait avant,
        #   sinon retourne le "OK: N nodes, M connections" de wire_and_compile().
    """
    import sys

    def _reload_and_run(verbose):
        # Reimport obligatoire : sans ça, un test_suite/ue5_utils déjà en mémoire
        # masquerait une régression introduite par une recompilation C++ récente
        # (voir CLAUDE.md — "Cache Python — reimporter apres modif ue5_utils").
        for m in list(sys.modules):
            if m in ("ue5_utils", "test_suite"):
                del sys.modules[m]
        import test_suite as _ts
        ok = _ts.run_all(verbose=verbose)
        snapshot = {name: status for status, name, _ in _ts._results}
        return ok, snapshot, _ts._OK, _ts._FAIL

    print("[safe_modify_plugin] Baseline AVANT modification...")
    baseline_ok, baseline, OK_TAG, FAIL_TAG = _reload_and_run(verbose=False)
    if not baseline_ok:
        failed = [n for n, s in baseline.items() if s == FAIL_TAG]
        raise Exception(
            "[safe_modify_plugin] ARRET : {} test(s) déjà en échec AVANT la "
            "modification (baseline non fiable) : {}. Corriger l'existant "
            "d'abord — ne pas modifier sur une base déjà rouge.".format(
                len(failed), failed))
    print("[safe_modify_plugin] Baseline OK ({} tests). Exécution de la "
          "modification...".format(len(baseline)))

    result = fn(*args, **kwargs)

    print("[safe_modify_plugin] Vérification APRÈS modification...")
    after_ok, after, _, _ = _reload_and_run(verbose=False)

    regressions = [
        name for name, status in after.items()
        if baseline.get(name) == OK_TAG and status == FAIL_TAG
    ]

    if regressions:
        raise Exception(
            "[safe_modify_plugin] REGRESSION DETECTEE : {} test(s) passaient "
            "avant la modification et échouent maintenant : {}. La modification "
            "N'A PAS été considérée sûre — corriger avant de sauvegarder ou de "
            "continuer.".format(len(regressions), regressions))

    if not after_ok:
        still_failing = [n for n, s in after.items() if s == FAIL_TAG]
        print("[safe_modify_plugin] ATTENTION : {} test(s) toujours en échec, "
              "mais déjà cassés avant la modif — pas une nouvelle régression : "
              "{}".format(len(still_failing), still_failing))

    print("[safe_modify_plugin] OK — aucune régression détectée ({} tests).".format(
        len(after)))
    return result
