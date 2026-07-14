"""
verify_level.py — Vérification automatique post-build d'un level horror

Usage :
    from verify_level import run_verify
    run_verify()                          # vérification complète
    run_verify(take_screenshot=False)     # sans screenshot
    run_verify(level_name="BoucherieLevel")

Retourne True si le level est jouable, False si erreurs bloquantes.

Ce script détecte :
  1. Acteurs dans la géométrie (bounding box intersection)
  2. Sol manquant sous les acteurs (line trace bas)
  3. Items gameplay manquants (FlashlightPickup, LightSwitch)
  4. PlayerStart absent
  5. Lumières avec radius par défaut (1000 = non configuré)
  6. Ennemis sans tag "Enemy" (invisibles au LightSwitch)
  7. PostProcess dupliqués
  8. NavMeshBoundsVolume absent
  9. Matériaux par défaut restants sur murs/sol/plafond (BasicShapeMaterial, MI_ProcGrid...)
  10. PostProcessVolume absent ou Lumen non désactivé (pas d'ambiance horror possible sans ça)
  11. Lumières globales par défaut encore actives (SkyLight/DirectionalLight noient l'ambiance)
  12. Screenshot viewport automatique

Historique : ajouté le 2026-07-03 après diagnostic d'un level "AgentDemo" qui passait
run_verify() à 0 erreur/0 warning tout en étant visuellement une boîte grise plate sans
aucune ambiance horror (3/4 murs sur BasicShapeMaterial, sol sur MI_ProcGrid, aucun
PostProcessVolume, SkyLight/DirectionalLight par défaut toujours actifs). Les checks
structurels (overlap, sol, tags, NavMesh) ne disaient rien de la qualité de l'ambiance —
ces trois nouveaux checks comblent ce trou. Voir GAME_MEMORY.md pour le détail.
"""

import unreal, os, glob, time


# ──────────────────────────────────────────────
# Helpers internes
# ──────────────────────────────────────────────

def _world():
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()

def _aeas():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

def _actors():
    return _aeas().get_all_level_actors()

def _line_trace_down(world, x, y, z, range_down=400):
    """Trace une ligne vers le bas depuis (x,y,z+50).
    Retourne (hit:bool, distance:float, hit_actor_label:str)."""
    hit = unreal.SystemLibrary.line_trace_single(
        world,
        unreal.Vector(x, y, z + 50),
        unreal.Vector(x, y, z - range_down),
        unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
        True, [],
        unreal.DrawDebugTrace.NONE,
        True,
        unreal.LinearColor(1, 0, 0, 1),
        unreal.LinearColor(0, 1, 0, 1),
        0.0
    )
    t = hit.to_tuple()
    blocking = t[0]
    distance = t[3] if blocking else -1
    hit_actor = t[9].get_actor_label() if blocking and t[9] else "?"
    return blocking, distance, hit_actor


def _bb_inside_any_geo(loc, geo_boxes, margin=10):
    """Retourne le label du premier cube de géométrie contenant loc, ou None."""
    for lbl, origin, extent in geo_boxes:
        if (abs(loc.x - origin.x) < extent.x - margin and
            abs(loc.y - origin.y) < extent.y - margin and
            abs(loc.z - origin.z) < extent.z - margin):
            return lbl
    return None


def _get_geo_boxes(actors):
    """Collecte les bounding boxes de tous les StaticMeshActors (géométrie réelle).

    Exclut les meshes décoratifs à l'échelle absurde (skydome, skysphere...) — un
    SM_SkySphere fait ~1 638 400 UU d'extent, contre <2000 UU pour n'importe quel mur/
    sol/plafond réel du projet. Sans ce filtre, TOUT acteur du level se retrouve
    "à l'intérieur" du skydome (faux positif détecté 2026-07-03 sur AgentDemo).
    """
    MAX_PLAUSIBLE_EXTENT = 5000.0
    boxes = []
    for a in actors:
        if "StaticMeshActor" in a.get_class().get_name():
            label = (a.get_actor_label() or "").lower()
            if "sky" in label:
                continue
            origin, extent = a.get_actor_bounds(False)
            if extent.x > MAX_PLAUSIBLE_EXTENT or extent.y > MAX_PLAUSIBLE_EXTENT or extent.z > MAX_PLAUSIBLE_EXTENT:
                continue
            boxes.append((a.get_actor_label(), origin, extent))
    return boxes


# ──────────────────────────────────────────────
# Checks individuels
# ──────────────────────────────────────────────

def check_actor_positions(actors, world, geo_boxes):
    """Vérifie les positions des acteurs gameplay — moteur physique réel + line trace sol.

    Couche 1 — sphere_overlap_actors : collision UE5 réelle (pas d'approximation AABB).
    Couche 2 — line trace sol : détecte les acteurs sans plancher sous les pieds.
    Fallback AABB si sphere_overlap_actors n'est pas disponible dans ce contexte.

    IMPORTANT (corrigé 2026-07-07) : Couche 1 ne s'applique qu'aux acteurs "physiques"
    (Enemy/PlayerStart/JumpScare — quelque chose qui a réellement une présence physique,
    ou dont la capsule joueur va spawner à cet endroit). Les acteurs "trigger" (Pickup,
    Flashlight, LightSwitch, Medikit, HidingSpot) ont volontairement NO_COLLISION sur
    leur propre composant et sont, PAR DESIGN, censés être placés au contact d'un meuble
    (lampe torche posée sur une table, cachette juste à côté d'un casier) — les faire
    passer par le même sphere_overlap_actors que produisait N faux positifs "OVERLAP REEL"
    sur ces meubles cibles. Diagnostiqué en session sur HorrorLevel : 6 des 9 erreurs
    remontées par run_verify() étaient des HidingSpot/Pickup collés à leur meuble prévu,
    pas de vrais bugs de placement.
    """
    errors = []
    PHYSICAL_KEYWORDS = ["Enemy", "PlayerStart", "JumpScare"]
    TRIGGER_KEYWORDS = ["Pickup", "Flashlight", "LightSwitch", "Medikit", "HidingSpot"]
    gameplay_keywords = PHYSICAL_KEYWORDS + TRIGGER_KEYWORDS

    for a in actors:
        lbl = a.get_actor_label()
        if not any(k in lbl for k in gameplay_keywords):
            continue
        loc = a.get_actor_location()
        is_trigger_only = (any(k in lbl for k in TRIGGER_KEYWORDS)
                            and not any(k in lbl for k in PHYSICAL_KEYWORDS))

        # ── Couche 1 : overlap physique réel (sphere_overlap_actors) ─────────
        # UE5.7 : unreal.Array(ObjectTypeQuery) vide = tous les types (NE PAS passer [])
        # Sautée pour les acteurs trigger-only (voir docstring ci-dessus).
        if not is_trigger_only:
            try:
                obj_types = unreal.Array(unreal.ObjectTypeQuery)
                ignore    = unreal.Array(unreal.Actor)
                ignore.append(a)
                overlaps  = unreal.SystemLibrary.sphere_overlap_actors(
                    world, loc, 40.0,
                    obj_types, unreal.Actor, ignore
                )
                geo_overlaps = [o for o in overlaps
                                if "StaticMeshActor" in o.get_class().get_name()]
                if geo_overlaps:
                    names = [o.get_actor_label() for o in geo_overlaps]
                    errors.append(
                        f"OVERLAP REEL: {lbl} est en collision physique avec {names}"
                    )
            except Exception:
                # Fallback AABB si sphere_overlap_actors indisponible
                geo_boxes_filtered = [(gl, go, ge) for gl, go, ge in geo_boxes if gl != lbl]
                inside = _bb_inside_any_geo(loc, geo_boxes_filtered)
                if inside:
                    errors.append(f"DANS GEOMETRIE (AABB): {lbl} est à l'intérieur de {inside}")

        # ── Couche 2 : sol sous les pieds ────────────────────────────────────
        has_floor, dist, floor_actor = _line_trace_down(world, loc.x, loc.y, loc.z)
        if not has_floor:
            errors.append(
                f"PAS DE SOL: {lbl} @ ({int(loc.x)},{int(loc.y)},{int(loc.z)}) — tombe dans le vide"
            )
        elif dist > 250:
            errors.append(
                f"SOL TROP LOIN: {lbl} dist={int(dist)} — flottant ou Z incorrect"
            )

    return errors


def check_enemy_tags(actors):
    """Vérifie que tous les BP_IA_Enemy ont le tag 'Enemy'."""
    errors = []
    for a in actors:
        if "BP_IA_Enemy" in a.get_class().get_name() or "IA_Enemy" in a.get_actor_label():
            tags = [str(t) for t in a.tags]
            if "Enemy" not in tags:
                errors.append(f"TAG MANQUANT: {a.get_actor_label()} n'a pas le tag 'Enemy' — LightSwitch ne le cachera pas")
    return errors


def check_lights(actors):
    """Vérifie que les lumières ont des radius configurés (pas la valeur par défaut 1000)."""
    warnings = []
    for a in actors:
        if "PointLight" in a.get_class().get_name():
            lbl = a.get_actor_label()
            lc = a.point_light_component
            radius = int(lc.get_editor_property("attenuation_radius"))
            intensity = int(lc.get_editor_property("intensity"))
            if radius == 1000:
                # Exactement 1000 = très probablement la valeur par défaut jamais configurée
                # (set_attenuation_radius() échoue silencieusement — voir CLAUDE.md). Un radius
                # volontairement > 1000 (ex: grande salle) ne doit PAS déclencher ce warning —
                # faux positif corrigé 2026-07-03 (était >= 1000, cassait sur HR_ColdSide=1100).
                warnings.append(f"RADIUS PAR DEFAUT: {lbl} radius={radius} — set_attenuation_radius() a échoué, utiliser set_editor_property('attenuation_radius')")
            if intensity == 0:
                warnings.append(f"LUMIERE ETEINTE: {lbl} intensity=0")
    return warnings


def check_gameplay_completeness(actors):
    """Vérifie la présence des éléments gameplay obligatoires."""
    errors = []
    labels = [a.get_actor_label() for a in actors]
    cls_names = [a.get_class().get_name() for a in actors]

    has_player_start = any("PlayerStart" in c for c in cls_names)
    has_flashlight = any("Flashlight" in l or "Pickup" in l for l in labels)
    has_lightswitch = any("LightSwitch" in l or "Switch" in l for l in labels)
    has_navmesh_vol = any("NavMesh" in l and "Recast" not in l for l in labels)
    enemy_count = sum(1 for a in actors if "BP_IA_Enemy" in a.get_class().get_name())

    if not has_player_start:
        errors.append("MANQUANT: PlayerStart — le joueur n'a nulle part où spawner")
    if not has_flashlight:
        errors.append("MANQUANT: FlashlightPickup — le joueur n'a pas de lampe torche")
    if not has_lightswitch:
        errors.append("MANQUANT: BP_LightSwitch — pas de condition de victoire")
    if not has_navmesh_vol:
        errors.append("MANQUANT: NavMeshBoundsVolume — les ennemis ne peuvent pas naviguer")
    if enemy_count == 0:
        errors.append("MANQUANT: Aucun ennemi — le jeu n'a aucun danger")

    return errors


def check_duplicates(actors):
    """Détecte les acteurs dupliqués (PostProcess, PlayerStart, etc.)."""
    warnings = []
    pp_count = sum(1 for a in actors if "PostProcess" in a.get_actor_label())
    ps_count = sum(1 for a in actors if "PlayerStart" in a.get_class().get_name())
    if pp_count > 1:
        warnings.append(f"DOUBLON: {pp_count} PostProcessVolume — effets imprévisibles, garder 1")
    if ps_count > 1:
        warnings.append(f"DOUBLON: {ps_count} PlayerStart — spawn aléatoire")
    return warnings


def check_navmesh_rebuild(world):
    """Vérifie si le NavMesh a été builté en testant une projection.
    Signature correcte UE5.7 : project_point_to_navigation(world, point, nav_data, filter_class, query_extent)
    """
    warnings = []
    try:
        nav = unreal.NavigationSystemV1.get_navigation_system(world)
        # Chercher le RecastNavMesh pour le passer en nav_data
        aeas = _aeas()
        nav_data = None
        for a in aeas.get_all_level_actors():
            if "RecastNavMesh" in a.get_class().get_name():
                nav_data = a
                break

        test_pos = unreal.Vector(700, 0, 100)  # centre Zone 1 — doit être sur NavMesh
        proj = nav.project_point_to_navigation(
            world, test_pos, nav_data, None, unreal.Vector(500, 500, 500)
        )
        if proj == unreal.Vector(0, 0, 0):
            warnings.append("NAVMESH NON BUILTÉ: faire Build → Build Paths dans UE5 (menu Build en haut)")
        else:
            pass  # NavMesh OK, pas de warning
    except Exception:
        # Fallback : vérifier juste que RecastNavMesh-Default existe
        has_recast = any("RecastNavMesh" in a.get_class().get_name()
                         for a in _actors())
        if not has_recast:
            warnings.append("NAVMESH NON BUILTÉ: aucun RecastNavMesh trouvé — Build → Build Paths")
    return warnings


# ──────────────────────────────────────────────
# Checks atmosphère (ajoutés 2026-07-03 — voir docstring en tête de fichier)
# ──────────────────────────────────────────────

# Matériaux "par défaut" : leur présence sur une surface signifie que l'étape
# d'application des matériaux horror a été sautée ou a échoué silencieusement.
BAD_MATERIAL_KEYWORDS = [
    "basicshapematerial", "worldgridmaterial", "mi_procgrid",
    "defaultmaterial", "t_default",
]

MAT_WALL  = "/Game/AssetImported/A_Surface_Footstep/Environment_Assets/Materials/M_DemoWall"
MAT_FLOOR = "/Game/AssetImported/A_Surface_Footstep/Environment_Assets/Materials/M_Asphalt"
MAT_CEIL  = "/Game/AssetImported/A_Surface_Footstep/Environment_Assets/Materials/M_grey"


def check_materials(actors):
    """Vérifie qu'aucun StaticMeshActor de géométrie n'a gardé un matériau par défaut.

    Corrigé le 2026-07-07 (audit BoucherieLevel, fermeture de la boucle vision) : la
    version précédente ne scannait QUE les labels contenant wall/floor/ceil/mur/sol/
    plafond — 22 surfaces réelles sur BoucherieLevel (murs "Funnel_N", segments abrégés
    "WN_L"/"WS_L"/"WE_S", murs de fond de niche "*_End", générés par un script ad hoc de
    la session 8 jamais retrouvé dans Content/Python) étaient encore sur WorldGridMaterial
    et ne matchaient AUCUN de ces mots-clés — jamais détectées, alors que run_verify()
    répondait "0 erreur" sur les matériaux. Fix : ne plus filtrer par label du tout.
    BAD_MATERIAL_KEYWORDS est déjà un signal suffisamment spécifique en soi (un asset
    importé n'a jamais WorldGridMaterial/BasicShapeMaterial — seule une primitive
    oubliée par un script générateur les porte) : scanner TOUT StaticMeshActor élimine
    ce point aveugle définitivement, quel que soit le nom donné par un futur script.

    Retourne (errors, warnings) — pas juste une liste. Deuxième bug trouvé en retirant
    le filtre de label ci-dessus : sur HorrorLevel, ça a fait remonter Table_Z2 et
    Cover_1..8 (props de gameplay, pas des murs/sol/plafond) au même niveau BLOQUANT
    qu'une vraie surface structurelle — un cover au damier gris est moche mais ne casse
    pas l'ambiance de toute la pièce comme un mur non habillé. Sévérité maintenant basée
    sur _classify_surface_by_geometry() (même heuristique de forme que fix_default_
    materials()) : structurel (mur/sol/plafond, par label OU par forme) → erreur
    bloquante ; prop compact (table, cover...) → warning seulement.
    """
    errors, warnings = [], []
    for a in actors:
        if "StaticMeshActor" not in a.get_class().get_name():
            continue
        label = a.get_actor_label() or ""
        ll = label.lower()
        smc = a.get_component_by_class(unreal.StaticMeshComponent.static_class())
        if not smc:
            continue
        mat = smc.get_material(0)
        mat_name = mat.get_name().lower() if mat else "none"
        if mat is None or any(bad in mat_name for bad in BAD_MATERIAL_KEYWORDS):
            is_structural = any(k in ll for k in ["wall", "floor", "sol", "ceil", "plafond", "mur"])
            if not is_structural:
                origin, extent = a.get_actor_bounds(False)
                is_structural = _classify_surface_by_geometry(a.get_actor_location(), extent) is not None
            msg = (f"MATERIAU PAR DEFAUT: {label} a le matériau '{mat_name}' — "
                   f"l'étape d'application des matériaux horror n'a pas eu lieu ou a échoué")
            if is_structural:
                errors.append(msg)
            else:
                warnings.append(msg + " (prop non structurel — cosmétique, pas bloquant)")
    return errors, warnings


def _classify_surface_by_geometry(location, extent, floor_ceiling_split_z=150.0):
    """Devine si une bounding box représente un mur, un sol ou un plafond à partir de sa
    FORME plutôt que de son label — filet de secours pour les labels non standards
    ("Funnel_N", segments abrégés "WN_L"/"WS_L"/"WE_S", murs de fond de niche "*_End"...)
    qui ne contiennent aucun des mots-clés habituels. Complète _group_walls_by_zone() /
    check_materials() sur le même bug de fond : un nom de label n'est jamais une garantie,
    la géométrie réelle l'est.

    extent.z nettement plus petit que extent.x ET extent.y → surface horizontale (sol si
    location.z sous floor_ceiling_split_z, plafond sinon — 150 UU = moitié de la hauteur
    de salle standard du projet, cohérent avec sol≈-20/0 et plafond≈300 partout ailleurs).
    extent.x OU extent.y nettement plus petit que les deux autres → mur (l'orientation
    N/S/E/W n'a pas besoin d'être déterminée, un seul MAT_WALL est utilisé de toute façon).
    Retourne None si la forme n'est pas assez plate/allongée (ratio > 0.35) pour être une
    surface structurelle — évite de classer à tort un prop compact (meuble, caisse...).
    """
    e = [extent.x, extent.y, extent.z]
    thin, thick = min(e), max(e)
    if thick <= 0 or thin / thick > 0.35:
        return None
    thin_axis = e.index(thin)
    if thin_axis == 2:
        return "floor" if location.z < floor_ceiling_split_z else "ceiling"
    return "wall"


def check_postprocess_atmosphere(actors):
    """Vérifie qu'un PostProcessVolume existe et désactive bien Lumen (GI + reflections).

    Sans ça : pas de vignette, pas de grain, pas de color grading, et Lumen fait
    rebondir la lumière sur les murs → impossible d'obtenir des ombres dures/noirs
    profonds quels que soient les réglages des point lights.
    """
    errors = []
    pp_actors = [a for a in actors if "PostProcessVolume" in a.get_class().get_name()]
    if not pp_actors:
        errors.append(
            "POSTPROCESS ABSENT: aucun PostProcessVolume dans le level — "
            "zéro vignette/grain/color grading, Lumen actif par défaut (rebond de lumière = pas d'ambiance horror)"
        )
        return errors
    for pp in pp_actors:
        try:
            unbound = pp.get_editor_property("unbound")
            if not unbound:
                errors.append(f"POSTPROCESS NON-UNBOUND: {pp.get_actor_label()} — n'affecte peut-être pas toute la salle")
            s = pp.settings
            gi_overridden = s.override_dynamic_global_illumination_method
            gi_is_none = (s.dynamic_global_illumination_method == unreal.DynamicGlobalIlluminationMethod.NONE)
            if not (gi_overridden and gi_is_none):
                errors.append(
                    f"LUMEN ACTIF: {pp.get_actor_label()} n'a pas désactivé le Global Illumination — "
                    f"les ombres seront diffuses au lieu d'être dures (voir CLAUDE.md règle 2)"
                )

            # Piège découvert le 2026-07-03 sur AgentDemo : AEM_MANUAL sans camera_iso
            # overridé garde ISO=100 par défaut (calibré plein jour) => salle noire quel
            # que soit l'intensité des point lights. Voir GAME_MEMORY.md.
            if str(s.auto_exposure_method).endswith("AEM_MANUAL"):
                iso_overridden = s.override_camera_iso
                iso_value = s.camera_iso
                if not iso_overridden or iso_value < 400:
                    errors.append(
                        f"EXPOSITION MANUELLE MAL CALIBREE: {pp.get_actor_label()} utilise AEM_MANUAL "
                        f"avec camera_iso={iso_value} (override={iso_overridden}) — ISO 100 par défaut "
                        f"est calibré plein jour, la salle sera noire. Overrider camera_iso >= 800-1600."
                    )
        except Exception as e:
            errors.append(f"POSTPROCESS ILLISIBLE: {pp.get_actor_label()} — {e}")
    return errors


def _group_walls_by_zone(wall_boxes, min_span=300.0):
    """Regroupe des wall boxes par zone (préfixe avant "_Wall"), en fusionnant les
    groupes dégénérés dans leur voisin le plus proche.

    Bug diagnostiqué le 2026-07-07 (juste après le fix "per-zone" du même jour) : sur
    HorrorLevel, Zone 1 et Zone 2 partagent les mêmes murs N/S continus, labellisés
    "Z2_WallN"/"Z2_WallS" (extent.x=1938, couvre les DEUX zones) — seul le mur de bout
    "Z1_WallW" porte le préfixe "Z1_". Un regroupement naïf par préfixe crée donc un
    groupe fantôme "Z1" avec UNE SEULE box fine (20×1200 UU, quasi une ligne), dont le
    centre calculé (0,0) tombe exactement sur le mur de bout — pas dans la pièce. Un
    screenshot pris à ce centre est collé au mur (noir total) et le % de couverture
    lumière calculé sur cette bounding box dégénérée ne mesure presque rien de la vraie
    pièce. Confirmé : `Z1_Floor` n'existe même pas, la pièce partage `Z2_Floor`.

    Fix : tout groupe dont l'étendue X ET Y est sous `min_span` (une simple ligne, pas
    une vraie salle) est fusionné dans le groupe "sain" le plus proche en X plutôt que
    traité comme une zone à part — cohérent avec la réalité géométrique (mur de bout
    d'un espace ouvert partagé, pas une pièce indépendante).
    """
    import re
    raw = {}
    for lbl, o, e in wall_boxes:
        m = re.match(r"(.+?)_wall", lbl, re.IGNORECASE)
        zone_key = m.group(1) if m else lbl
        raw.setdefault(zone_key, []).append((lbl, o, e))

    def _span_and_center(items):
        xs = [o.x for _, o, e in items] + [o.x + e.x for _, o, e in items] + [o.x - e.x for _, o, e in items]
        ys = [o.y for _, o, e in items] + [o.y + e.y for _, o, e in items] + [o.y - e.y for _, o, e in items]
        return (max(xs) - min(xs), max(ys) - min(ys), sum(xs) / len(xs))

    good, degenerate = {}, {}
    for zk, items in raw.items():
        sx, sy, cx = _span_and_center(items)
        # Dégénéré si : moins de 2 murs (un seul mur de bout ne définit aucune vraie
        # étendue de salle — il aura toujours un grand span dans SA propre longueur,
        # ce qui ne dit rien de l'étendue réelle de la pièce sur cet axe), OU span nul
        # sur les deux axes (cas limite, tous les murs au même endroit).
        if len(items) < 2 or (sx < min_span and sy < min_span):
            degenerate[zk] = (items, cx)
        else:
            good[zk] = items

    for zk, (items, cx) in degenerate.items():
        if not good:
            good[zk] = items
            continue
        nearest = min(good.keys(), key=lambda gk: abs(_span_and_center(good[gk])[2] - cx))
        good[nearest] = good[nearest] + items

    return good


def check_light_coverage(actors, geo_boxes, min_playable_pct=50.0, ideal_pct=60.0,
                          corridor_min_pct=15.0, corridor_ideal_pct=25.0):
    """Échantillonne une grille de points sur le sol, PAR ZONE, et vérifie qu'un
    pourcentage suffisant de la surface est réellement à portée d'au moins un point
    light actif.

    Approximation 2D par distance (pas de line-of-sight/occlusion par les murs —
    heuristique volontairement simple). Objectif : détecter le cas "toutes les checks
    structurelles passent mais la salle est noire" (signalé 2026-07-03 sur AgentDemo :
    2 point lights radius=500 dans une salle de 1600×1200, donc ~80% de la surface
    hors de portée de toute lumière, alors que run_verify() disait "JOUABLE").

    Corrigé le 2026-07-07 : la version précédente calculait UNE SEULE bounding box sur
    tous les murs du level entier puis échantillonnait dessus. Sur un level multi-zones
    (HorrorLevel : 9 zones + couloirs sur ~9600 UU), ça mélange des salles éclairées et
    des couloirs volontairement sombres (voir HORROR_DESIGN.md / CLAUDE.md "couloir
    sombre, mannequins décoratifs") dans une seule moyenne globale — un niveau où
    chaque salle est correctement éclairée peut quand même se retrouver sous 50% de
    couverture "globale" simplement parce que les couloirs, sombres par design,
    tirent la moyenne vers le bas. Diagnostiqué en session sur HorrorLevel (9 zones) :
    22% de couverture globale alors qu'aucune salle individuelle n'était réellement
    sous-éclairée une fois recalculé zone par zone.

    Les murs sont regroupés par préfixe de label avant "_Wall" (ex: "Z1_WallN",
    "Z1_WallS" → zone "Z1"). Un groupe dont le nom contient "corr"/"couloir"
    (insensible à la casse) est traité comme un couloir et reçoit un seuil bien plus
    bas (corridor_min_pct/corridor_ideal_pct) — cohérent avec le fait qu'un couloir
    sombre entre deux salles est une intention de design, pas un bug.

    Seuil salle : < 50% de couverture = ERREUR bloquante (le joueur ne voit littéralement
    rien sur la majorité du sol, ce n'est plus "sombre et effrayant", c'est cassé).
    50-60% = warning (en dessous du ratio cible HORROR_DESIGN.md section 9 : "60%
    visible, 40% dans l'ombre"). Couloir : mêmes principes mais seuils abaissés
    (15%/25% par défaut) puisque l'obscurité y est voulue.
    """
    import re

    errors, warnings = [], []

    lights = []
    for a in actors:
        if "PointLight" in a.get_class().get_name():
            lc = a.point_light_component
            intensity = lc.get_editor_property("intensity")
            radius = lc.get_editor_property("attenuation_radius")
            if intensity > 0 and radius > 0:
                lights.append((a.get_actor_location(), radius))

    if not lights:
        errors.append("AUCUNE LUMIERE ACTIVE: 0 point light avec intensity>0 — la salle est nécessairement noire")
        return errors, warnings

    wall_boxes = [(lbl, o, e) for lbl, o, e in geo_boxes if "wall" in lbl.lower() or "mur" in lbl.lower()]
    if not wall_boxes:
        warnings.append("COUVERTURE LUMIERE: aucun mur identifiable (label contenant 'wall') — check ignoré")
        return errors, warnings

    # Regroupement par zone : préfixe avant "_Wall" (insensible à la casse), avec
    # fusion des groupes dégénérés (mur de bout d'un espace partagé) — voir
    # _group_walls_by_zone() pour le détail du bug corrigé le 2026-07-07.
    zones_raw = _group_walls_by_zone(wall_boxes)
    zones = {zk: [(o, e) for _, o, e in items] for zk, items in zones_raw.items()}

    GRID = 8  # par zone (plus petite qu'un level entier) — 8x8 = 64 échantillons suffisent
    for zone_key, boxes in zones.items():
        xs = [o.x for o, e in boxes] + [o.x + e.x for o, e in boxes] + [o.x - e.x for o, e in boxes]
        ys = [o.y for o, e in boxes] + [o.y + e.y for o, e in boxes] + [o.y - e.y for o, e in boxes]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        floor_z = min((o.z for o, e in boxes), default=100.0) - 100.0  # approx niveau du sol

        total, covered = 0, 0
        for i in range(GRID):
            for j in range(GRID):
                px = x_min + (x_max - x_min) * (i + 0.5) / GRID
                py = y_min + (y_max - y_min) * (j + 0.5) / GRID
                total += 1
                for loc, radius in lights:
                    dx, dy, dz = px - loc.x, py - loc.y, floor_z - loc.z
                    if (dx*dx + dy*dy + dz*dz) ** 0.5 <= radius:
                        covered += 1
                        break

        pct = (covered / total * 100.0) if total else 0.0
        is_corridor = bool(re.search(r"corr|couloir", zone_key, re.IGNORECASE))
        threshold = corridor_min_pct if is_corridor else min_playable_pct
        ideal = corridor_ideal_pct if is_corridor else ideal_pct
        kind = "couloir" if is_corridor else "jouable"

        if pct < threshold:
            errors.append(
                f"SALLE TROP SOMBRE [{zone_key}]: seulement {pct:.0f}% du sol est à portée d'une lumière "
                f"(seuil {kind}: {threshold:.0f}%) — ajouter des point lights ou augmenter leur radius"
            )
        elif pct < ideal:
            warnings.append(
                f"ECLAIRAGE LIMITE [{zone_key}]: {pct:.0f}% du sol couvert (cible: ~{ideal:.0f}%)"
            )
    return errors, warnings


def check_default_level_lighting(actors):
    """Vérifie que les lumières globales par défaut d'un nouveau level UE5 sont éteintes.

    SkyLight/DirectionalLight/VolumetricCloud à leur intensité par défaut inondent
    la scène de lumière ambiante et annulent tout le travail de point lights calibrés.
    """
    errors = []
    for a in actors:
        cls = a.get_class().get_name()
        if "SkyLight" in cls:
            c = a.get_component_by_class(unreal.SkyLightComponent.static_class())
            if c and c.get_editor_property("intensity") > 0.5:
                errors.append(f"SKYLIGHT ACTIF: intensity={c.get_editor_property('intensity')} — éteindre (intensity=0) ou justifier")
        elif "DirectionalLight" in cls:
            c = a.get_component_by_class(unreal.DirectionalLightComponent.static_class())
            if c and c.get_editor_property("intensity") > 0.5:
                errors.append(f"DIRECTIONALLIGHT ACTIF: intensity={c.get_editor_property('intensity')} — éteindre (intensity=0) ou justifier")
    return errors


# ──────────────────────────────────────────────
# Screenshot
# ──────────────────────────────────────────────

def take_verify_screenshot(name="verify", capture_pos=None):
    """Prend un screenshot fiable et retourne le chemin du fichier.

    Utilise capture_reference_screenshot() (ue5_utils.py) — SceneCaptureComponent2D
    synchrone, PAS take_high_res_screenshot (mis en file d'attente, souvent noir/périmé
    dans un contexte agent — bug diagnostiqué 2026-07-03, voir GAME_MEMORY.md).

    capture_pos : (x, y, z, pitch, yaw, roll) optionnel — position fixe de la caméra de
    capture. Sans ça, capture depuis le centre du level courant (moyenne des origins de
    géométrie), en regardant vers -X, à hauteur d'yeux (z=170). Toujours préférer une
    position explicite si tu connais déjà le PlayerStart ou un point d'intérêt précis.
    """
    try:
        from ue5_utils import capture_reference_screenshot
    except ImportError:
        # Fallback historique si ue5_utils indisponible (ne devrait pas arriver en usage normal)
        unreal.AutomationLibrary.take_high_res_screenshot(1920, 1080, f"{name}.png")
        time.sleep(2.0)
        screenshot_dir = os.path.join(unreal.Paths.project_saved_dir(), "Screenshots", "WindowsEditor")
        matches = sorted(glob.glob(os.path.join(screenshot_dir, f"{name}.png")),
                         key=os.path.getmtime, reverse=True)
        if matches:
            return matches[0]
        all_shots = sorted(glob.glob(os.path.join(screenshot_dir, "*.png")),
                           key=os.path.getmtime, reverse=True)
        return all_shots[0] if all_shots else None

    if capture_pos:
        x, y, z, pitch, yaw, roll = capture_pos
    else:
        actors = _actors()
        geo = _get_geo_boxes(actors)
        if geo:
            xs = [o.x for _, o, _ in geo]
            ys = [o.y for _, o, _ in geo]
            x, y = sum(xs) / len(xs), sum(ys) / len(ys)
        else:
            x, y = 0.0, 0.0
        z, pitch, yaw, roll = 170.0, 0, 180, 0

    return capture_reference_screenshot(x, y, z, pitch=pitch, yaw=yaw, roll=roll, name=name)


def capture_all_zones_screenshots(name_prefix="verify_zone"):
    """Un screenshot PAR ZONE plutôt qu'un point moyen sur tout le level.

    Bug diagnostiqué le 2026-07-07 sur HorrorLevel : take_verify_screenshot() sans
    capture_pos explicite prend la moyenne des origins de TOUTE la géométrie du level
    comme position de caméra. Sur un level à une seule salle (AgentDemo, sa cible
    d'origine) cette moyenne tombe au centre de la salle — correct. Sur un level
    multi-zones (HorrorLevel : 9 zones/couloirs sur ~10000 UU en X), la moyenne tombe
    n'importe où — ici en plein dans le couloir vers Zone 3 — et le screenshot résultant
    est presque entièrement noir (caméra collée à un mur, vue en tunnel à travers une
    ouverture lointaine). run_verify() annonçait pourtant "0 erreur, JOUABLE" : le texte
    du rapport était correct, mais le seul artefact visuel produit ne permettait de
    juger aucune zone réelle — la boucle vision n'était fermée qu'en apparence.

    Réutilise le même regroupement par zone que check_light_coverage() (préfixe avant
    "_Wall", couloirs détectés par "corr"/"couloir") pour que screenshot et check de
    couverture lumière portent exactement sur les mêmes zones. Un point de vue par
    zone (centre XY, z=170 hauteur des yeux, pitch=0, yaw=180 — convention du projet,
    voir CLAUDE.md "Screenshot fiable") permet de juger visuellement chaque salle
    individuellement au lieu d'un seul point arbitraire sur tout le level.

    Retourne {zone_key: chemin_png}.
    """
    import re
    from ue5_utils import capture_reference_screenshot

    actors = _actors()
    geo_boxes = _get_geo_boxes(actors)
    wall_boxes = [(lbl, o, e) for lbl, o, e in geo_boxes if "wall" in lbl.lower() or "mur" in lbl.lower()]

    zones_raw = _group_walls_by_zone(wall_boxes)

    paths = {}
    for zone_key, boxes in zones_raw.items():
        xs = [o.x for _, o, e in boxes]
        ys = [o.y for _, o, e in boxes]
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)

        # yaw=180 (regarder vers -X) suppose une salle fermée avec un mur de bout à
        # l'ouest — correct pour les zones avec des murs Est/Ouest (ou L/R pour un
        # couloir, où "descendre le couloir" est la vue naturelle). Mais Z3A/Z3B/Z3C
        # (voir GAME_MEMORY.md layout) n'ont QUE des murs N/S — pas de mur de bout en
        # X — elles sont ouvertes sur le reste du niveau dans cet axe. Un yaw=180 y
        # regarde alors à l'infini dans le couloir de jeu entier (vue tunnel jusqu'à
        # la zone la plus proche encore éclairée), pas la salle elle-même. Pour ces
        # zones "salle ouverte" (nom ne contenant pas corr/couloir ET aucun mur
        # E/W/L/R), on tourne la caméra à 90° pour regarder à travers la largeur
        # contrainte (N à S) à la place — cadrage représentatif de LA zone, pas du
        # niveau entier vu au travers.
        has_cap_wall = any(re.search(r"wall(e|w|l|r)\b", lbl, re.IGNORECASE) for lbl, _, _ in boxes)
        is_corridor_name = bool(re.search(r"corr|couloir", zone_key, re.IGNORECASE))
        safe_name = re.sub(r"[^A-Za-z0-9_]", "_", zone_key)

        if has_cap_wall or is_corridor_name:
            yaws = [180]
        else:
            # Testé le 2026-07-07 : pour une zone sans mur de bout (ouverte sur le
            # reste du niveau des deux côtés en X, ex: Z3A/B/C), AUCUN angle fixe
            # n'est fiable à coup sûr — yaw=180 tombe parfois sur une vue tunnel du
            # niveau entier, parfois sur le décor réel de la zone (cas Z3B, où
            # yaw=180 montrait un bon aperçu et yaw=90 était noir total) ; l'inverse
            # est vrai ailleurs (Z3A). Pas de règle géométrique simple qui distingue
            # les deux cas à l'avance avec les seules bounding boxes de murs. Plutôt
            # que de deviner un seul angle et risquer un screenshot inutile, on
            # capture les deux — coût négligeable (screenshot de vérification, pas
            # un chemin runtime), et un humain/agent choisit celui qui est lisible.
            yaws = [180, 90]

        for yaw in yaws:
            path = capture_reference_screenshot(cx, cy, 170, pitch=0, yaw=yaw, name=f"{name_prefix}_{safe_name}_yaw{yaw}")
            paths[f"{zone_key}_yaw{yaw}"] = path
            print(f"  [{zone_key}] centre=({int(cx)},{int(cy)}) yaw={yaw} -> {path}")

    return paths


# ──────────────────────────────────────────────
# Entrée principale
# ──────────────────────────────────────────────

def run_verify(take_screenshot=True, level_name=None):
    """Vérifie le level courant et retourne True si jouable.

    Affiche un rapport complet avec erreurs bloquantes et warnings.
    """
    world = _world()
    actors = _actors()
    geo_boxes = _get_geo_boxes(actors)

    name_str = level_name or world.get_name()
    print(f"\n{'='*50}")
    print(f"VERIFY LEVEL — {name_str} ({len(actors)} acteurs)")
    print(f"{'='*50}")

    all_errors = []
    all_warnings = []

    # Screenshot en premier (montre l'état avant les checks)
    screenshot_path = None
    if take_screenshot:
        print("\n[1/11] Screenshot viewport...")
        screenshot_path = take_verify_screenshot(f"verify_{name_str}")
        if screenshot_path:
            print(f"      Screenshot: {screenshot_path}")
        else:
            all_warnings.append("Screenshot non trouvé (UE5 pas en focus ?)")

    # Checks
    print("\n[2/11] Positions acteurs (dans géométrie / sol manquant)...")
    errs = check_actor_positions(actors, world, geo_boxes)
    all_errors.extend(errs)
    print(f"      {len(errs)} erreur(s)")

    print("\n[3/11] Tags ennemis...")
    errs = check_enemy_tags(actors)
    all_errors.extend(errs)
    print(f"      {len(errs)} erreur(s)")

    print("\n[4/11] Lumières (radius configuré)...")
    warns = check_lights(actors)
    all_warnings.extend(warns)
    print(f"      {len(warns)} warning(s)")

    print("\n[5/11] Gameplay completeness...")
    errs = check_gameplay_completeness(actors)
    all_errors.extend(errs)
    print(f"      {len(errs)} erreur(s)")

    print("\n[6/11] Doublons...")
    warns = check_duplicates(actors)
    all_warnings.extend(warns)
    print(f"      {len(warns)} warning(s)")

    print("\n[7/11] NavMesh builté...")
    warns = check_navmesh_rebuild(world)
    all_warnings.extend(warns)
    print(f"      {len(warns)} warning(s)")

    print("\n[8/11] Matériaux (défauts restants sur murs/sol/plafond)...")
    errs, warns = check_materials(actors)
    all_errors.extend(errs)
    all_warnings.extend(warns)
    print(f"      {len(errs)} erreur(s), {len(warns)} warning(s)")

    print("\n[9/11] PostProcess (présence + Lumen désactivé)...")
    errs = check_postprocess_atmosphere(actors)
    all_errors.extend(errs)
    print(f"      {len(errs)} erreur(s)")

    print("\n[10/11] Lumières globales par défaut (SkyLight/DirectionalLight)...")
    errs = check_default_level_lighting(actors)
    all_errors.extend(errs)
    print(f"      {len(errs)} erreur(s)")

    print("\n[11/11] Couverture lumière (le sol est-il vraiment visible ?)...")
    errs, warns = check_light_coverage(actors, geo_boxes)
    all_errors.extend(errs)
    all_warnings.extend(warns)
    print(f"      {len(errs)} erreur(s), {len(warns)} warning(s)")

    # Rapport final
    print(f"\n{'='*50}")
    print("RAPPORT FINAL")
    print(f"{'='*50}")

    if all_errors:
        print(f"\n❌ ERREURS BLOQUANTES ({len(all_errors)}) — level NON jouable :")
        for e in all_errors:
            print(f"   • {e}")
    else:
        print("\n✅ Aucune erreur bloquante")

    if all_warnings:
        print(f"\n⚠  WARNINGS ({len(all_warnings)}) — level jouable mais imparfait :")
        for w in all_warnings:
            print(f"   • {w}")
    else:
        print("\n✅ Aucun warning")

    if not all_errors and not all_warnings:
        print("\n🎮 LEVEL PARFAITEMENT JOUABLE")

    if screenshot_path:
        print(f"\n📸 Screenshot: {screenshot_path}")
        print("   (lire avec Read tool pour vérification visuelle)")

    playable = len(all_errors) == 0
    print(f"\n{'='*50}")
    print(f"VERDICT: {'JOUABLE ✅' if playable else 'NON JOUABLE ❌'}")
    print(f"{'='*50}\n")
    return playable


# ──────────────────────────────────────────────
# Fix automatique des problèmes détectés
# ──────────────────────────────────────────────

def fix_light_radius(target_radius_map=None):
    """Corrige les radius de toutes les lumières avec radius=1000 (valeur par défaut).

    target_radius_map : dict {label: radius} pour des valeurs précises.
    Sans map, applique 400 par défaut à toutes les lumières non configurées.

    Exemple:
        fix_light_radius({"Z1_Entry_Amber": 320, "Corr_Red": 500})
    """
    actors = _actors()
    fixed = 0
    for a in actors:
        if "PointLight" in a.get_class().get_name():
            lbl = a.get_actor_label()
            lc = a.point_light_component
            current = int(lc.get_editor_property("attenuation_radius"))
            if current >= 1000:
                target = (target_radius_map or {}).get(lbl, 400)
                lc.set_editor_property("attenuation_radius", float(target))
                print(f"  Fixed: {lbl} radius {current} → {target}")
                fixed += 1
    print(f"fix_light_radius: {fixed} lumière(s) corrigée(s)")
    return fixed


def fix_enemy_tags():
    """Ajoute le tag 'Enemy' à tous les BP_IA_Enemy qui ne l'ont pas."""
    actors = _actors()
    fixed = 0
    for a in actors:
        if "BP_IA_Enemy" in a.get_class().get_name():
            tags = [str(t) for t in a.tags]
            if "Enemy" not in tags:
                a.tags = list(a.tags) + [unreal.Name("Enemy")]
                print(f"  Fixed: {a.get_actor_label()} — tag 'Enemy' ajouté")
                fixed += 1
    print(f"fix_enemy_tags: {fixed} ennemi(s) corrigé(s)")
    return fixed


def fix_duplicate_postprocess():
    """Supprime les PostProcessVolume en double, garde le premier."""
    actors = _actors()
    aeas = _aeas()
    pp_actors = [a for a in actors if "PostProcess" in a.get_actor_label()]
    removed = 0
    for a in pp_actors[1:]:
        aeas.destroy_actor(a)
        removed += 1
    print(f"fix_duplicate_postprocess: {removed} doublon(s) supprimé(s)")
    return removed


def fix_default_materials():
    """Remplace les matériaux par défaut (BasicShapeMaterial, MI_ProcGrid...) restants
    sur tout StaticMeshActor structurel, indépendamment du préfixe de zone (filet de
    sécurité générique, complète _apply_room_materials de horror_presets.py qui exige
    un préfixe exact).

    Corrigé le 2026-07-07 : la classification wall/floor/ceiling se basait uniquement
    sur le label, donc les mêmes 22 surfaces à label non standard que check_materials()
    ratait (Funnel_N, WN_L, *_End...) étaient certes ATTEINTES par la boucle (aucun
    filtre is_room_surface ici) mais ne matchaient aucune des 3 branches wall/floor/
    ceiling → jamais réparées silencieusement, `fixed` jamais incrémenté pour elles.
    Fallback ajouté : _classify_surface_by_geometry() sur la forme réelle de la bounding
    box quand le label ne dit rien — voir sa docstring pour le détail de la heuristique.
    """
    mat_w = unreal.load_asset(MAT_WALL)
    mat_f = unreal.load_asset(MAT_FLOOR)
    mat_c = unreal.load_asset(MAT_CEIL)
    fixed = 0
    for a in _actors():
        if "StaticMeshActor" not in a.get_class().get_name():
            continue
        label = a.get_actor_label() or ""
        ll = label.lower()
        smc = a.get_component_by_class(unreal.StaticMeshComponent.static_class())
        if not smc:
            continue
        mat = smc.get_material(0)
        mat_name = mat.get_name().lower() if mat else "none"
        if mat is not None and not any(bad in mat_name for bad in BAD_MATERIAL_KEYWORDS):
            continue  # déjà un matériau custom, ne pas écraser un choix volontaire

        if "wall" in ll or "mur" in ll:
            kind = "wall"
        elif "floor" in ll or "sol" in ll:
            kind = "floor"
        elif "ceil" in ll or "plafond" in ll:
            kind = "ceiling"
        else:
            origin, extent = a.get_actor_bounds(False)
            kind = _classify_surface_by_geometry(a.get_actor_location(), extent)

        if kind == "wall" and mat_w:
            smc.set_material(0, mat_w); fixed += 1
        elif kind == "floor" and mat_f:
            smc.set_material(0, mat_f); fixed += 1
        elif kind == "ceiling" and mat_c:
            smc.set_material(0, mat_c); fixed += 1
    print(f"fix_default_materials: {fixed} surface(s) corrigée(s)")
    return fixed


def fix_global_lights():
    """Éteint SkyLight/DirectionalLight à leur valeur par défaut (workflow CLAUDE.md
    étape 1 : 'Éteindre lumières globales'). N'y touche pas si déjà à 0."""
    fixed = 0
    for a in _actors():
        cls = a.get_class().get_name()
        if "SkyLight" in cls:
            c = a.get_component_by_class(unreal.SkyLightComponent.static_class())
            if c and c.get_editor_property("intensity") > 0.5:
                c.set_editor_property("intensity", 0.0)
                fixed += 1
        elif "DirectionalLight" in cls:
            c = a.get_component_by_class(unreal.DirectionalLightComponent.static_class())
            if c and c.get_editor_property("intensity") > 0.5:
                c.set_editor_property("intensity", 0.0)
                fixed += 1
    print(f"fix_global_lights: {fixed} lumière(s) globale(s) éteinte(s)")
    return fixed


def fix_all():
    """Applique tous les correctifs automatiques disponibles."""
    print("=== FIX ALL ===")
    fix_light_radius()
    fix_enemy_tags()
    fix_duplicate_postprocess()
    fix_default_materials()
    fix_global_lights()
    print("fix_all terminé — relancer run_verify() pour confirmer")
    print("NOTE: fix_all ne peut PAS créer un PostProcessVolume manquant ni désactiver")
    print("      Lumen à ta place — si run_verify() signale POSTPROCESS ABSENT ou")
    print("      LUMEN ACTIF, utiliser setup_global_atmosphere(style) de horror_presets.py")


print("[verify_level] loaded — from verify_level import run_verify, fix_all")


# ══════════════════════════════════════════════════════
# BOUCLE QC FERMEE — verified_zone_build()
# Ajoute le 2026-07-08 : ferme la partie STRUCTURELLE de la boucle de verification
# perceptuelle (voir CLAUDE.md "point le plus critique" identifie en session -- jusqu'ici
# execute_level_plan() lancait fix_all()+run_verify() UNE SEULE fois a la fin, sans relance
# si des erreurs auto-corrigibles connues restaient, et sans jamais consolider le retour
# numerique de Tools/analyze_screenshot.py avec le retour structurel de run_verify(). Cette
# fonction NE REMPLACE PAS le jugement visuel (impossible depuis l'UE5 Python embarque, qui
# n'a ni PIL ni numpy ni acces vision) -- elle relance automatiquement les correctifs connus
# (PostProcess absent, Lumen actif, exposition mal calibree, couverture lumiere insuffisante)
# jusqu'a un plafond d'iterations, PUIS capture un screenshot fiable et remet la main a
# l'agent avec vision (Claude Cowork) pour la partie perceptuelle -- voir Tools/qc_gate.py
# qui consolide ce retour structurel avec l'analyse numerique de pixels en un seul verdict.
# ══════════════════════════════════════════════════════

def _qc_manifest_path():
    """Chemin du manifest QC persistant (Saved/QC/qc_manifest.json) -- partagé entre
    verified_zone_build() (côté UE5, écrit les entrées "pending") et Tools/qc_gate.py
    (côté Cowork bash, met à jour verdict numérique + confirmation de lecture visuelle).
    Saved/ est ignoré par git (état éphémère de build, pas une source)."""
    import os
    d = os.path.join(unreal.Paths.project_dir(), "Saved", "QC")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "qc_manifest.json")


def _load_qc_manifest():
    import json, os
    path = _qc_manifest_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _record_qc_pending(zone_name, screenshot_path, errors, warnings):
    """Enregistre dans le manifest QC qu'une zone vient d'être (re)construite et a un
    screenshot frais qui attend encore Tools/qc_gate.py + une lecture visuelle confirmée
    -- voir CLAUDE.md section "BOUCLE QC FERMÉE". Avant ce manifest, "ne jamais déclarer
    terminé sans Read + qc_gate.py" n'était qu'un message imprimé -- rien n'empêchait un
    agent pressé de l'ignorer silencieusement, exactement le même trou de conception que
    celui fermé pour safe_write/safe_append (convention non vérifiable -> mécanisme
    persistant et auditable). Écrase l'entrée précédente de cette zone : un nouveau
    screenshot invalide l'ancien verdict qc_gate, qui ne s'appliquait qu'à l'ancienne image.
    """
    import json, datetime
    data = _load_qc_manifest()
    data[zone_name] = {
        "zone_name": zone_name,
        "screenshot": screenshot_path,
        "structural_errors": list(errors),
        "structural_warnings": list(warnings),
        "built_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "qc_gate_verdict": None,
        "qc_gate_ran_at": None,
        "visual_read_confirmed": False,
        "visual_read_note": None,
    }
    path = _qc_manifest_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def check_qc_pending(zone_names=None):
    """Audit du manifest QC (Saved/QC/qc_manifest.json) -- liste les zones qui n'ont
    PAS encore (qc_gate_verdict == "PASS" ET visual_read_confirmed == True).

    zone_names : si fourni, limite l'audit à ces zones (typiquement celles construites
    par le plan en cours, voir execute_level_plan()) ; sinon audite TOUTES les zones
    connues du manifest.

    Lit exactement le même fichier que `python3 Tools/qc_gate.py --check-manifest`
    (côté Cowork bash) mais en pur stdlib -- lire le manifest ne demande ni PIL ni
    numpy, seule l'ANALYSE de pixels (qc_gate.py --zone, analyze_screenshot.analyze())
    en a besoin et doit donc rester côté Cowork bash. Cette fonction ne remplace pas
    qc_gate.py, elle permet juste de brancher l'audit "quelles zones n'ont jamais été
    complètement vérifiées" directement dans execute_level_plan(), sans dépendre d'un
    appel manuel séparé après coup (voir CLAUDE.md "BOUCLE QC FERMÉE").

    Retourne une liste de dicts {"zone": str, "reasons": [...]} -- liste vide = tout
    est vérifié (qc_gate PASS + lecture visuelle confirmée) pour les zones demandées.
    """
    data = _load_qc_manifest()
    keys = zone_names if zone_names is not None else list(data.keys())

    pending = []
    for zone in keys:
        entry = data.get(zone)
        if entry is None:
            pending.append({"zone": zone, "reasons": [
                "aucune entrée manifest (pas construite via verified_zone_build() ?)"]})
            continue
        reasons = []
        verdict = entry.get("qc_gate_verdict")
        if verdict is None:
            reasons.append("qc_gate.py jamais lancé sur cette zone (--zone manquant côté Cowork)")
        elif verdict != "PASS":
            reasons.append(f"dernier verdict qc_gate: {verdict}")
        if not entry.get("visual_read_confirmed"):
            reasons.append("lecture visuelle jamais confirmée (--confirm-visual-read manquant)")
        if reasons:
            pending.append({"zone": zone, "reasons": reasons})
    return pending


def verified_zone_build(build_fn, zone_name, x_min, x_max, cx=None, cy=0,
                          style="silent_hill", max_passes=3, capture_pos=None):
    """Boucle fermee build -> fix -> re-verifie -> capture, avec relance automatique
    plafonnee des correctifs structurels connus (PAS un remplacement du jugement visuel).

    Workflow :
      1. build_fn() -- construit la salle/le couloir.
      2. Boucle (max max_passes) : fix_all() -> checks structurels complets -> si une
         erreur connue auto-corrigible reste (PostProcess absent / Lumen actif /
         exposition mal calibree -> setup_global_atmosphere(style) ; couverture lumiere
         insuffisante -> lumiere de remplissage ciblee) -> reboucle. Sinon, sort de la
         boucle immediatement (pas d'iteration inutile).
      3. Capture UN screenshot fiable (capture_pos explicite, sinon centre de zone calcule
         depuis x_min/x_max/cx/cy, hauteur des yeux, yaw=180 -- convention du projet).
      4. Retourne un rapport consolide -- NE DECLARE JAMAIS le level "termine" seul.

    ETAPE OBLIGATOIRE SUIVANTE (a faire par l'agent qui a appele cette fonction, PAS par
    un agent texte seul -- voir CLAUDE.md routage agent UE5 vs Claude Cowork : tout ce qui
    touche a l'ambiance visuelle doit passer par un agent avec vision) :
        - Lire le screenshot retourne avec Read
        - Lancer Tools/qc_gate.py dessus (+ le rapport errors/warnings de ce retour) pour
          le verdict numerique consolide
        - Si echec (structurel restant, numerique, OU jugement visuel direct) : appliquer
          le correctif approprie, rappeler verified_zone_build() sur la MEME zone, jusqu'a
          un plafond raisonnable (recommande : 3 appels complets) puis remonter le probleme
          a l'utilisateur plutot que boucler indefiniment ou declarer un faux succes.

    LIMITE CONNUE (scaffold, pas une solution complete) : le correctif de couverture
    lumiere ajoute une lumiere de remplissage au centre (cx, cy) fourni en argument --
    correct pour un appel salle-par-salle (le cas d'usage principal), mais n'essaie pas de
    localiser precisement quelle sous-zone d'un level multi-salles est concernee si
    verified_zone_build() est appele sur un level entier deja construit (cx/cy unique).

    Retourne :
        {"zone_name": str, "errors": [...], "warnings": [...], "screenshot": path,
         "passes": int, "structural_pass": bool, "qc_manifest": path}

    Chaque appel enregistre aussi une entrée "pending" dans le manifest QC persistant
    (Saved/QC/qc_manifest.json, voir _record_qc_pending()) -- `python3 Tools/qc_gate.py
    --check-manifest` permet d'auditer, depuis Cowork, quelles zones construites n'ont
    JAMAIS eu leur screenshot passé par qc_gate.py ni leur lecture visuelle confirmée,
    plutôt que de compter sur le fait qu'aucun agent n'a oublié cette étape.
    """
    import re, time
    from ue5_utils import capture_reference_screenshot, point_light

    build_fn()

    if cx is None:
        cx = (x_min + x_max) / 2

    world = _world()
    passes_done = 0
    errors, warnings = [], []

    for i in range(max_passes):
        passes_done = i + 1
        fix_all()

        actors = _actors()
        geo_boxes = _get_geo_boxes(actors)

        errors, warnings = [], []
        errors += check_actor_positions(actors, world, geo_boxes)
        errors += check_enemy_tags(actors)
        warnings += check_lights(actors)
        errors += check_gameplay_completeness(actors)
        warnings += check_duplicates(actors)
        warnings += check_navmesh_rebuild(world)
        e, w = check_materials(actors)
        errors += e; warnings += w
        errors += check_postprocess_atmosphere(actors)
        errors += check_default_level_lighting(actors)
        e, w = check_light_coverage(actors, geo_boxes)
        errors += e; warnings += w

        atmosphere_issues = [er for er in errors if any(k in er for k in (
            "POSTPROCESS ABSENT", "LUMEN ACTIF", "EXPOSITION MANUELLE MAL CALIBREE"
        ))]
        coverage_issues = [er for er in errors if "SALLE TROP SOMBRE" in er]

        if not atmosphere_issues and not coverage_issues:
            print(f"[verified_zone_build] '{zone_name}' pass {passes_done}: "
                  f"plus d'erreur auto-corrigible connue -- arret de la boucle.")
            break

        if atmosphere_issues:
            try:
                from horror_presets import setup_global_atmosphere
                setup_global_atmosphere(style)
                print(f"[verified_zone_build] pass {passes_done}: setup_global_atmosphere("
                      f"'{style}') relance ({len(atmosphere_issues)} erreur(s) PP/Lumen/exposition)")
            except Exception as ex:
                print(f"[verified_zone_build] setup_global_atmosphere a echoue: {ex}")

        if coverage_issues:
            point_light(cx, cy, 30, intensity=700, rgb=(200, 190, 170), radius=550,
                        label=f"AutoFix_Fill_{zone_name}_{passes_done}")
            print(f"[verified_zone_build] pass {passes_done}: lumiere de remplissage "
                  f"ajoutee @ ({int(cx)},{int(cy)},30) pour couverture insuffisante "
                  f"({len(coverage_issues)} zone(s) concernee(s))")

    if capture_pos:
        px, py, pz, ppitch, pyaw, proll = capture_pos
    else:
        px, py, pz, ppitch, pyaw, proll = cx, cy, 170, 0, 180, 0

    safe_name = re.sub(r"[^A-Za-z0-9_]", "_", zone_name.lower())
    screenshot_path = capture_reference_screenshot(
        px, py, pz, pitch=ppitch, yaw=pyaw, roll=proll,
        name=f"vzb_{safe_name}_{int(time.time())}"
    )

    structural_pass = len(errors) == 0
    manifest_path = _record_qc_pending(zone_name, screenshot_path, errors, warnings)
    print(f"\n[verified_zone_build] '{zone_name}' -- {passes_done} passe(s), "
          f"{len(errors)} erreur(s) restante(s), {len(warnings)} warning(s)")
    print(f"[verified_zone_build] Screenshot: {screenshot_path}")
    print(f"[verified_zone_build] Manifest QC (pending) : {manifest_path}")
    print("[verified_zone_build] ETAPE OBLIGATOIRE SUIVANTE : Read(screenshot) + "
          "Tools/qc_gate.py --zone {} avant de declarer quoi que ce soit termine "
          "(sinon 'python3 Tools/qc_gate.py --check-manifest' verra cette zone "
          "'PENDING_VERIFICATION' indefiniment).".format(zone_name))

    return {
        "zone_name": zone_name, "errors": errors, "warnings": warnings,
        "screenshot": screenshot_path, "passes": passes_done,
        "structural_pass": structural_pass, "qc_manifest": manifest_path,
    }


print("[verify_level] verified_zone_build() charge -- boucle QC fermee (structurel + capture)")
