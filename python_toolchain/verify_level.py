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
    from collections import Counter
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
    except Exception as e:
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
    """Vérifie qu'aucun mur/sol/plafond de géométrie n'a gardé un matériau par défaut.

    Ne se base PAS sur un préfixe de zone (contrairement à _apply_room_materials côté
    horror_presets.py) — scanne TOUT StaticMeshActor dont le label contient wall/floor/
    ceil, quel que soit le système qui a généré la salle. C'est volontaire : une salle
    avec des labels non standard (ex: "Wall_North" sans préfixe) doit quand même être
    détectée si elle a un matériau par défaut.
    """
    errors = []
    for a in actors:
        if "StaticMeshActor" not in a.get_class().get_name():
            continue
        label = a.get_actor_label() or ""
        ll = label.lower()
        is_room_surface = any(k in ll for k in
            ["wall", "floor", "sol", "ceil", "plafond", "mur"])
        if not is_room_surface:
            continue
        smc = a.get_component_by_class(unreal.StaticMeshComponent.static_class())
        if not smc:
            continue
        mat = smc.get_material(0)
        mat_name = mat.get_name().lower() if mat else "none"
        if mat is None or any(bad in mat_name for bad in BAD_MATERIAL_KEYWORDS):
            errors.append(
                f"MATERIAU PAR DEFAUT: {label} a le matériau '{mat_name}' — "
                f"l'étape d'application des matériaux horror n'a pas eu lieu ou a échoué"
            )
    return errors


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

    # Regroupement par zone : préfixe avant "_Wall" (insensible à la casse).
    # Fallback : le label complet sert de clé si le motif "_Wall" n'est pas trouvé.
    zones = {}
    for lbl, o, e in wall_boxes:
        m = re.match(r"(.+?)_wall", lbl, re.IGNORECASE)
        zone_key = m.group(1) if m else lbl
        zones.setdefault(zone_key, []).append((o, e))

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
    errs = check_materials(actors)
    all_errors.extend(errs)
    print(f"      {len(errs)} erreur(s)")

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
    print(f"RAPPORT FINAL")
    print(f"{'='*50}")

    if all_errors:
        print(f"\n❌ ERREURS BLOQUANTES ({len(all_errors)}) — level NON jouable :")
        for e in all_errors:
            print(f"   • {e}")
    else:
        print(f"\n✅ Aucune erreur bloquante")

    if all_warnings:
        print(f"\n⚠  WARNINGS ({len(all_warnings)}) — level jouable mais imparfait :")
        for w in all_warnings:
            print(f"   • {w}")
    else:
        print(f"\n✅ Aucun warning")

    if not all_errors and not all_warnings:
        print(f"\n🎮 LEVEL PARFAITEMENT JOUABLE")

    if screenshot_path:
        print(f"\n📸 Screenshot: {screenshot_path}")
        print(f"   (lire avec Read tool pour vérification visuelle)")

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
    print(f"fix_enemy_tags: {fixed} ennemi(s)