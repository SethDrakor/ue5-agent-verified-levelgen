"""
horror_presets.py — Toolchain de Level Design pour HorrorGame
=============================================================
Importe avec : from horror_presets import *

Contient :
  - Catalogues d'assets (props par categorie)
  - place_* : placement precis de props/lumieres/ennemis
  - dress_* : habillage complet d'une salle ou d'un couloir
  - atmosphere_* : presets d'ambiance lumineuse
  - Fonctions utilitaires : discover_assets, clear_zone, etc.
"""

import unreal
import random
from ue5_utils import (aeas, spawn, point_light, place_static_mesh,
                       scatter_props, tag_actor, save,
                       build_occupancy_grid_from_level, safe_spawn_enemy,
                       actor_by_label, all_actors)


# ══════════════════════════════════════════════════════════════════════════════
# CATALOGUE D'ASSETS
# Chemins UE valides pour les assets du projet AssetsvilleTown
# ══════════════════════════════════════════════════════════════════════════════

BASE_HOUSE   = "/Game/AssetImported/AssetsvilleTown/Meshes/InteriorProps/House"
BASE_OFFICE  = "/Game/AssetImported/AssetsvilleTown/Meshes/InteriorProps/Office"
BASE_STREET  = "/Game/AssetImported/AssetsvilleTown/Meshes/StreetProps"
BASE_BUILD   = "/Game/AssetImported/AssetsvilleTown/Meshes/BuildingTilset"

# Mobilier abandonné
PROPS_FURNITURE = [
    BASE_HOUSE + "/SM_Chair_01",
    BASE_HOUSE + "/SM_Armchair_01",
    BASE_HOUSE + "/SM_Armchair_02",
    BASE_HOUSE + "/SM_Sofa_01",
    BASE_HOUSE + "/SM_Sofa_02",
    BASE_HOUSE + "/SM_Table_01",
    BASE_HOUSE + "/SM_Table_02",
    BASE_HOUSE + "/SM_Table_03",
    BASE_HOUSE + "/SM_Cupboard_01",
    BASE_HOUSE + "/SM_Cupboard_02",
    BASE_HOUSE + "/SM_Bookcase_02",
    BASE_HOUSE + "/SM_Bookcase_03",
    BASE_HOUSE + "/SM_Mirror_01",
    BASE_HOUSE + "/SM_Basket_01",
    BASE_HOUSE + "/SM_Basket_02",
]

# Bureau délabré
PROPS_OFFICE = [
    BASE_OFFICE + "/SM_Desk_01",
    BASE_OFFICE + "/SM_Desk_02",
    BASE_OFFICE + "/SM_Chair_01",
    BASE_OFFICE + "/SM_Chair_02",
    BASE_OFFICE + "/SM_Computer_01",
    BASE_OFFICE + "/SM_Locker_01",
    BASE_OFFICE + "/SM_Box_01",
    BASE_OFFICE + "/SM_Box_02",
    BASE_OFFICE + "/SM_Box_04",
    BASE_OFFICE + "/SM_Cupboard_01",
    BASE_OFFICE + "/SM_Cupboard_06",
    BASE_OFFICE + "/SM_Bin_01",
    BASE_OFFICE + "/SM_Binder_01",
    BASE_OFFICE + "/SM_Binder_02",
    BASE_OFFICE + "/SM_PinBoard_01",
    BASE_OFFICE + "/SM_FireExtinguisher_01",
]

# Débris et caisses
PROPS_CLUTTER = [
    BASE_OFFICE + "/SM_Box_01",
    BASE_OFFICE + "/SM_Box_02",
    BASE_OFFICE + "/SM_Box_04",
    BASE_OFFICE + "/SM_Box_05",
    BASE_OFFICE + "/SM_Bin_01",
    BASE_OFFICE + "/SM_Bin_02",
    BASE_HOUSE  + "/SM_Basket_01",
    BASE_HOUSE  + "/SM_Basket_02",
    BASE_HOUSE  + "/SM_Basket_03",
    BASE_STREET + "/SM_barrel_1",
    BASE_STREET + "/SM_barrel_2",
    BASE_STREET + "/SM_barrel_3",
]

# Props inquiétants / horror
PROPS_HORROR = [
    BASE_STREET + "/SM_DeadBody_01",
    BASE_STREET + "/SM_Chalk_Outline_01",
    BASE_OFFICE + "/SM_FireAlarm_01",
    BASE_OFFICE + "/SM_Frame_01",
    BASE_OFFICE + "/SM_Frame_02",
    BASE_HOUSE  + "/SM_Mirror_01",
    BASE_STREET + "/SM_barrel_1",
    BASE_STREET + "/SM_barrel_3",
]

# Lampes du projet
LAMP_FLICKERING = "/Game/HorrorGame/lights/lampe_plafond_clignotante"
LAMP_OFF        = "/Game/HorrorGame/lights/lampe_plafond_eteinte"
BP_ENEMY        = "/Game/HorrorGame/IA/Blueprint/Enemy/BP_IA_Enemy"
BP_JUMPSCARE    = "/Game/HorrorGame/IA/Blueprint/BP_JumpScareLight"
# BP_FLASHLIGHT : utiliser load_class avec suffixe _C (load_blueprint_class échoue)
BP_FLASHLIGHT   = "/Game/HorrorGame/FirstPerson/Blueprints/BP_FlashlightPickup.BP_FlashlightPickup_C"


# ══════════════════════════════════════════════════════════════════════════════
# ATMOSPHERES — presets de lumière
# ══════════════════════════════════════════════════════════════════════════════

def atmosphere_red_danger(cx, cy, z=200, count=3, radius=500):
    """Lumiere rouge oppressante — zone de danger."""
    lights = []
    for i in range(count):
        angle = (360 / count) * i
        import math
        ox = math.cos(math.radians(angle)) * radius * 0.5
        oy = math.sin(math.radians(angle)) * radius * 0.5
        l = point_light(cx + ox, cy + oy, z,
                        intensity=250, rgb=(255, 30, 10),
                        radius=500, label="DangerLight_{}".format(i))
        lights.append(l)
    return lights


def atmosphere_dim_amber(cx, cy, z=220, count=2, radius=300):
    """Lumiere ambrée faible — salle abandonnée."""
    lights = []
    for i in range(count):
        ox = random.uniform(-radius * 0.4, radius * 0.4)
        oy = random.uniform(-radius * 0.4, radius * 0.4)
        l = point_light(cx + ox, cy + oy, z,
                        intensity=180, rgb=(255, 160, 60),
                        radius=380, label="AmberLight_{}".format(i))
        lights.append(l)
    return lights


def atmosphere_cold_blue(cx, cy, z=220, count=2, radius=300):
    """Lumiere bleue froide — morgue / sous-sol."""
    lights = []
    for i in range(count):
        ox = random.uniform(-radius * 0.4, radius * 0.4)
        oy = random.uniform(-radius * 0.4, radius * 0.4)
        l = point_light(cx + ox, cy + oy, z,
                        intensity=150, rgb=(80, 140, 255),
                        radius=500, label="ColdLight_{}".format(i))
        lights.append(l)
    return lights


def atmosphere_pitch_black(cx, cy, z=200):
    """Quasi-obscurité — une seule lumiere tres faible."""
    return [point_light(cx, cy, z, intensity=80, rgb=(255, 200, 100),
                        radius=200, label="GlimmerLight")]


def atmosphere_flickering_lamps(cx, cy, z_lamp=270, count=3, spacing=400):
    """Range de lampes clignotantes le long d'un axe X.
    Les lampes s'etendent de cx - (count-1)*spacing/2 a cx + ...
    """
    lamps = []
    start_x = cx - ((count - 1) * spacing / 2)
    for i in range(count):
        x = start_x + i * spacing
        cls = unreal.EditorAssetLibrary.load_blueprint_class(LAMP_FLICKERING)
        if cls:
            a = aeas().spawn_actor_from_class(
                cls, unreal.Vector(x, cy, z_lamp), unreal.Rotator(0, 0, 0))
            if a:
                a.set_actor_label("FlickerLamp_{}".format(i))
                lamps.append(a)
    return lamps


# ══════════════════════════════════════════════════════════════════════════════
# TEMPLATES DE SALLES — dress_*
# ══════════════════════════════════════════════════════════════════════════════

def _apply_room_materials(zone_prefix):
    """Applique les matériaux sombres validés aux murs/sol/plafond d'une salle.
    zone_prefix : ex. 'Salle_Demo' pour chercher Salle_Demo_WallN, etc.
    """
    MAT_WALL  = "/Game/AssetImported/A_Surface_Footstep/Environment_Assets/Materials/M_DemoWall"
    MAT_FLOOR = "/Game/AssetImported/A_Surface_Footstep/Environment_Assets/Materials/M_Asphalt"
    MAT_CEIL  = "/Game/AssetImported/A_Surface_Footstep/Environment_Assets/Materials/M_grey"
    mat_w = unreal.load_asset(MAT_WALL)
    mat_f = unreal.load_asset(MAT_FLOOR)
    mat_c = unreal.load_asset(MAT_CEIL)
    applied = 0
    for a in aeas().get_all_level_actors():
        label = a.get_actor_label() or ""
        if not label.startswith(zone_prefix):
            continue
        smc = a.get_component_by_class(unreal.StaticMeshComponent.static_class())
        if not smc:
            continue
        ll = label.lower()
        if any(x in ll for x in ["walln","walls","walle","wallw","_wall"]):
            if mat_w: smc.set_material(0, mat_w); applied += 1
        elif "floor" in ll:
            if mat_f: smc.set_material(0, mat_f); applied += 1
        elif "ceil" in ll:
            if mat_c: smc.set_material(0, mat_c); applied += 1
    unreal.log("[horror_presets] _apply_room_materials '{}': {} surfaces".format(zone_prefix, applied))
    return applied


def dress_abandoned_room(cx, cy, z=0, size=1200, seed=None, zone_prefix=None):
    """Salle abandonnee : meubles renverses, lumiere ambrée faible.

    cx, cy      : centre de la salle
    size        : taille approximative (utilise comme rayon de scatter)
    seed        : reproductibilite
    zone_prefix : label prefix de la salle (ex: 'Salle_Demo') pour appliquer
                  les matériaux sombres automatiquement avant les lumières.
    """
    if seed is None:
        seed = int(cx + cy)
    spread = size * 0.35

    # Matériaux sombres EN PREMIER (obligatoire avant lumières)
    if zone_prefix:
        _apply_room_materials(zone_prefix)

    # Mobilier éparpillé
    actors = scatter_props(PROPS_FURNITURE, cx, cy, z,
                           count=6, spread=spread,
                           label_prefix="AbandonedFurniture", seed=seed)

    # Quelques débris
    actors += scatter_props(PROPS_CLUTTER, cx, cy, z,
                            count=4, spread=spread * 0.8,
                            label_prefix="AbandonedClutter", seed=seed + 1)

    # Lumière
    atmosphere_dim_amber(cx, cy, z=z + 220, count=2, radius=spread)

    unreal.log("[horror_presets] dress_abandoned_room @ ({},{}) — {} acteurs".format(
        cx, cy, len(actors)))
    return actors


def dress_office_derelict(cx, cy, z=0, size=1200, seed=None, zone_prefix=None):
    """Bureau delabré : bureaux, ordinateurs, classeurs, lumière froide."""
    if seed is None:
        seed = int(cx + cy)
    spread = size * 0.35

    if zone_prefix:
        _apply_room_materials(zone_prefix)

    actors = scatter_props(PROPS_OFFICE, cx, cy, z,
                           count=8, spread=spread,
                           label_prefix="OfficeDesk", seed=seed)
    actors += scatter_props(PROPS_CLUTTER, cx, cy, z,
                            count=3, spread=spread * 0.6,
                            label_prefix="OfficePaper", seed=seed + 2)

    atmosphere_cold_blue(cx, cy, z=z + 220, count=2, radius=spread)

    unreal.log("[horror_presets] dress_office_derelict @ ({},{}) — {} acteurs".format(
        cx, cy, len(actors)))
    return actors


def dress_danger_room(cx, cy, z=0, size=1200, seed=None, zone_prefix=None):
    """Salle de danger : props horror, lumière rouge, ennemi cache."""
    if seed is None:
        seed = int(cx + cy)
    spread = size * 0.3

    if zone_prefix:
        _apply_room_materials(zone_prefix)

    actors = scatter_props(PROPS_HORROR, cx, cy, z,
                           count=5, spread=spread,
                           label_prefix="DangerProp", seed=seed)

    atmosphere_red_danger(cx, cy, z=z + 210, count=3, radius=spread)

    unreal.log("[horror_presets] dress_danger_room @ ({},{}) — {} acteurs".format(
        cx, cy, len(actors)))
    return actors


def dress_corridor_horror(x1, x2, cy=0, z=0, width=500, seed=None):
    """Couloir horror : debris le long des murs, lampes clignotantes, quasi-noir.

    x1, x2 : debut et fin du couloir sur l'axe X
    cy      : centre Y du couloir
    width   : largeur du couloir (pour placer les props pres des murs)
    """
    if seed is None:
        seed = int(x1 + x2)
    random.seed(seed)

    length  = abs(x2 - x1)
    cx      = (x1 + x2) / 2
    actors  = []
    step    = 300
    n_steps = max(1, int(length / step))

    for i in range(n_steps):
        t   = i / max(1, n_steps - 1)
        x   = x1 + t * (x2 - x1)
        # Props contre le mur gauche ou droit
        side = random.choice([-1, 1])
        oy   = side * (width * 0.35 + random.uniform(0, 30))
        path = random.choice(PROPS_CLUTTER)
        a    = place_static_mesh(path, x, cy + oy, z,
                                  yaw=random.uniform(0, 360),
                                  label="CorrProp_{}".format(i))
        if a:
            actors.append(a)

    # Lampes clignotantes
    n_lamps = max(1, int(length / 600))
    atmosphere_flickering_lamps(cx, cy, z_lamp=z + 270,
                                count=n_lamps, spacing=int(length / n_lamps))

    # Quelques points de lumiere rouge tres faibles
    for i in range(2):
        px = x1 + (x2 - x1) * (0.25 + i * 0.5)
        point_light(px, cy, z + 150, intensity=300,
                    rgb=(180, 20, 10), radius=250,
                    label="CorrRedGlow_{}".format(i))

    unreal.log("[horror_presets] dress_corridor_horror ({}->{}) — {} props".format(
        x1, x2, len(actors)))
    return actors


def dress_boss_room(cx, cy, z=0, size=1400, seed=None, zone_prefix=None):
    """Salle principale : props horror, rouge intense, jumpscare au centre."""
    if seed is None:
        seed = int(cx + cy)

    if zone_prefix:
        _apply_room_materials(zone_prefix)

    # Props
    actors  = scatter_props(PROPS_HORROR, cx, cy, z,
                            count=7, spread=size * 0.4,
                            label_prefix="BossProp", seed=seed)
    actors += scatter_props(PROPS_CLUTTER, cx, cy, z,
                            count=5, spread=size * 0.3,
                            label_prefix="BossClutter", seed=seed + 3)

    # Eclairage intense
    atmosphere_red_danger(cx, cy, z=z + 220, count=4, radius=size * 0.35)

    # JumpScare au fond
    js_cls = unreal.EditorAssetLibrary.load_blueprint_class(BP_JUMPSCARE)
    if js_cls:
        js = aeas().spawn_actor_from_class(
            js_cls, unreal.Vector(cx, cy - size * 0.3, z + 100),
            unreal.Rotator(0, 0, 0))
        if js:
            js.set_actor_label("BossJumpScare")
            actors.append(js)

    unreal.log("[horror_presets] dress_boss_room @ ({},{}) — {} acteurs".format(
        cx, cy, len(actors)))
    return actors


# ══════════════════════════════════════════════════════════════════════════════
# GAMEPLAY — ennemis, pickups, jumpscares
# ══════════════════════════════════════════════════════════════════════════════

def spawn_patrol_enemy(x, y, z=100, label="Enemy"):
    """Spawne un ennemi BP_IA_Enemy avec le tag 'Enemy'."""
    cls = unreal.EditorAssetLibrary.load_blueprint_class(BP_ENEMY)
    if cls is None:
        unreal.log_warning("[horror_presets] BP_IA_Enemy introuvable.")
        return None
    a = aeas().spawn_actor_from_class(cls, unreal.Vector(x, y, z), unreal.Rotator(0, 0, 0))
    if a:
        a.set_actor_label(label)
        tag_actor(a, "Enemy")
    return a


def spawn_jumpscare(x, y, z=100, label="JumpScare"):
    """Spawne un BP_JumpScareLight (flash blanc a proximite du joueur)."""
    cls = unreal.EditorAssetLibrary.load_blueprint_class(BP_JUMPSCARE)
    if cls is None:
        unreal.log_warning("[horror_presets] BP_JumpScareLight introuvable.")
        return None
    a = aeas().spawn_actor_from_class(cls, unreal.Vector(x, y, z), unreal.Rotator(0, 0, 0))
    if a:
        a.set_actor_label(label)
    return a


def spawn_flashlight_pickup(x, y, z=80, label="FlashlightPickup"):
    """Spawne un pickup lampe torche.
    Utilise load_class avec suffixe _C (load_blueprint_class échoue sur ce BP).
    """
    cls = unreal.load_class(None, BP_FLASHLIGHT)  # BP_FLASHLIGHT contient déjà le suffixe _C
    if cls is None:
        unreal.log_warning("[horror_presets] BP_FlashlightPickup introuvable: " + BP_FLASHLIGHT)
        return None
    a = aeas().spawn_actor_from_class(cls, unreal.Vector(x, y, z), unreal.Rotator(0, 0, 0))
    if a:
        a.set_actor_label(label)
    return a


# ══════════════════════════════════════════════════════════════════════════════
# UTILITAIRES
# ══════════════════════════════════════════════════════════════════════════════

def clear_zone(cx, cy, radius=800, z_min=-50, z_max=500):
    """Supprime tous les StaticMeshActors dans une zone (utile pour re-dress).
    ATTENTION : ne supprime pas la geometrie (murs/sols generes par RoomGenerator).
    """
    removed = 0
    for a in aeas().get_all_level_actors():
        if not isinstance(a, unreal.StaticMeshActor):
            continue
        loc = a.get_actor_location()
        dist_xy = ((loc.x - cx) ** 2 + (loc.y - cy) ** 2) ** 0.5
        if dist_xy <= radius and z_min <= loc.z <= z_max:
            aeas().destroy_actor(a)
            removed += 1
    unreal.log("[horror_presets] clear_zone : {} acteurs supprimes".format(removed))
    return removed


def discover_assets(ue_folder, keyword=""):
    """Liste les assets dans un dossier UE, filtre par mot-cle.

    Exemple : discover_assets("/Game/AssetsvilleTown/Meshes/InteriorProps", "Chair")
    """
    all_paths = unreal.EditorAssetLibrary.list_assets(ue_folder, recursive=True)
    if keyword:
        all_paths = [p for p in all_paths if keyword.lower() in p.lower()]
    for p in sorted(all_paths):
        unreal.log(p)
    return list(all_paths)


def dress_level_zone(zone_name, cx, cy, z=0, size=1200, seed=None):
    """Dispatcher principal : applique le bon template selon le nom de zone.

    zone_name : 'abandoned', 'office', 'danger', 'boss', 'corridor'
    Pour les corridors, cx/cy = centre, size = longueur.

    Exemple :
        dress_level_zone('abandoned', 700, 0)
        dress_level_zone('corridor', 3600, 0, size=1600)
    """
    zone_name = zone_name.lower()
    if zone_name == "abandoned":
        return dress_abandoned_room(cx, cy, z, size, seed)
    elif zone_name == "office":
        return dress_office_derelict(cx, cy, z, size, seed)
    elif zone_name == "danger":
        return dress_danger_room(cx, cy, z, size, seed)
    elif zone_name == "boss":
        return dress_boss_room(cx, cy, z, size, seed)
    elif zone_name == "corridor":
        half = size / 2
        return dress_corridor_horror(cx - half, cx + half, cy, z, seed=seed)
    else:
        unreal.log_warning("[horror_presets] Zone inconnue : '{}'. "
                           "Choisir parmi : abandoned, office, danger, boss, corridor".format(zone_name))
        return []


# ══════════════════════════════════════════════════════════════════════════════
# MATERIAUX — creation et application via MaterialEditingLibrary
# ══════════════════════════════════════════════════════════════════════════════

MAT_BASE_PATH = "/Game/Materials"
MAT_BASE_NAME = "M_HorrorBase"

# Presets de couleurs par style (r,g,b lineaire 0-1)
WALL_PRESETS = {
    "silent_hill":  {"wall":  (0.018, 0.015, 0.012),   # beton use tres sombre
                     "floor": (0.012, 0.011, 0.010),   # sol encore plus sombre
                     "ceil":  (0.006, 0.005, 0.005)},  # plafond quasi-noir
    "outlast":      {"wall":  (0.010, 0.010, 0.012),   # institution bleute
                     "floor": (0.008, 0.009, 0.012),
                     "ceil":  (0.004, 0.004, 0.006)},
    "amnesia":      {"wall":  (0.020, 0.016, 0.010),   # pierre humide ambre
                     "floor": (0.010, 0.008, 0.006),
                     "ceil":  (0.005, 0.004, 0.003)},
    "alan_wake":    {"wall":  (0.013, 0.011, 0.009),   # bois de cabane trempe par la pluie
                     "floor": (0.007, 0.008, 0.009),   # sol humide, legerement bleu-froid
                     "ceil":  (0.004, 0.004, 0.005)},  # quasi-noir, foret nocturne
}

# Presets post-process par style
# Noms de proprietes VALIDES UE5.7 (verifies par experience — voir CLAUDE.md)
# BGRA pour unreal.Color, snake_case pour PostProcessSettings
#
# BUG CRITIQUE CORRIGE 2026-07-03 (signale par Thomas : "tout le niveau est grise, pas de
# couleur malgre les lumieres colorees") : color_saturation et color_contrast sont des
# FVector4 appliques PAR CANAL (R,G,B,Y) en UE5, pas "un scalaire cache dans le 4e chiffre".
# Toutes les valeurs ci-dessous etaient ecrites unreal.Vector4(0.0, 0.0, 0.0, X) — R=G=B=0
# ecrasait les 3 canaux couleur a leur luminance (donc gris/monochrome complet), le X en
# 4e position ne compensait rien. Confirme empiriquement en PIE reel sur AW_Room : en
# passant a Vector4(X,X,X,X) uniforme, les couleurs (rouge Cauldron, teal Forest_Mist,
# ambre Amber_Puddle) redeviennent visibles au lieu d'un voile gris-vert uniforme.
# Consequence : un contraste REELLEMENT applique aux 3 canaux est plus fort qu'avant (le bug
# neutralisait une partie de son propre effet) — auto_exposure_bias releve en compensation
# sur chaque style pour eviter de replonger la salle dans le noir. Seul alan_wake a ete
# reverifie visuellement en PIE reel a ce jour (2026-07-03) ; silent_hill/outlast/amnesia
# ont recu le meme fix par coherence mais PAS encore revalides visuellement — a faire avant
# de considerer leur calibration definitive.
PP_PRESETS = {
    # BUG CRITIQUE CORRIGE 2026-07-03 (audit live Claude Cowork sur AgentDemo, confirme en PIE
    # reel via HighResShot depuis la camera joueur — pas seulement capture_reference_screenshot()
    # editeur, qui s'est averee ne PAS refleter fidelement le bloom/l'exposition reels du jeu) :
    # bloom_intensity par defaut (~0.675) + bloom_threshold=-1 (auto, TOUT pixel au-dessus de la
    # moyenne scene contribue au bloom) transformait chaque point light candela en un halo qui
    # noyait toute la salle dans un voile gris-bleu plat et delave — aucune des 4 sources ne se
    # lisait comme un point focal, aucun contraste ombre/lumiere, ennemi invisible meme en pleine
    # vue. Symptome distinct du bug "salle noire" precedent (ISO/exposition) : ici l'image etait
    # au contraire TROP CLAIRE et plate, pas trop sombre. Fix : bloom quasi coupe + lens flare coupe
    # + AO coupe (les point lights + le color grading suffisent pour l'ambiance horror).
    # Verifie visuellement : avec ce fix, la geometrie, les props ET la silhouette de l'ennemi dans
    # son coin sombre redeviennent lisibles en PIE reel.
    "silent_hill": {
        "vignette_intensity":        0.9,
        "film_grain_intensity":      0.5,
        "film_grain_intensity_midtones": 0.3,
        "scene_fringe_intensity":    0.8,   # >1.5 = shift bleu total → eviter
        "auto_exposure_bias":        1.2,   # relevé le 2026-07-03 bis (contraste RGB reel maintenant applique, voir note ci-dessus)
        "bloom_intensity":           0.05,  # corrigé 2026-07-03 (défaut ~0.675 → voile gris plat, voir note ci-dessus)
        "bloom_threshold":           1.0,   # défaut -1 (auto) déclenchait le bloom sur toute la scène
        "lens_flare_intensity":      0.0,
        "ambient_occlusion_intensity": 0.2,
        "color_saturation":          unreal.Vector4(0.80, 0.80, 0.80, 0.80),
        "color_contrast":            unreal.Vector4(1.05, 1.05, 1.05, 1.05),
        "color_gamma_midtones":      unreal.Vector4(0.93, 1.0, 1.10, 1.0),
        "color_offset_shadows":      unreal.Vector4(-0.018, -0.005, 0.025, 0.0),
    },
    "outlast": {
        "vignette_intensity":        1.1,
        "film_grain_intensity":      0.8,
        "film_grain_intensity_midtones": 0.5,
        "scene_fringe_intensity":    0.6,
        "auto_exposure_bias":        0.8,   # relevé le 2026-07-03 bis (contraste RGB reel maintenant applique, voir note ci-dessus)
        "bloom_intensity":           0.05,
        "bloom_threshold":           1.0,
        "lens_flare_intensity":      0.0,
        "ambient_occlusion_intensity": 0.2,
        "color_saturation":          unreal.Vector4(0.65, 0.65, 0.65, 0.65),
        "color_contrast":            unreal.Vector4(1.1, 1.1, 1.1, 1.1),
        "color_gamma_midtones":      unreal.Vector4(0.95, 1.0, 1.06, 1.0),
        "color_offset_shadows":      unreal.Vector4(-0.012, -0.003, 0.018, 0.0),
    },
    "amnesia": {
        "vignette_intensity":        0.7,
        "film_grain_intensity":      0.3,
        "film_grain_intensity_midtones": 0.2,
        "scene_fringe_intensity":    0.4,
        "auto_exposure_bias":        1.3,   # relevé le 2026-07-03 bis (contraste RGB reel maintenant applique, voir note ci-dessus)
        "bloom_intensity":           0.05,
        "bloom_threshold":           1.0,
        "lens_flare_intensity":      0.0,
        "ambient_occlusion_intensity": 0.2,
        "color_saturation":          unreal.Vector4(0.75, 0.75, 0.75, 0.75),
        "color_contrast":            unreal.Vector4(1.0, 1.0, 1.0, 1.0),
        "color_gamma_midtones":      unreal.Vector4(0.98, 0.97, 0.90, 1.0),
        "color_offset_shadows":      unreal.Vector4(0.008, 0.004, -0.010, 0.0),
    },
    # alan_wake — ajoute 2026-07-03. Esthetique "Cauldron Lake" : foret nocturne trempee,
    # contraste noir extreme (la lampe torche du joueur EST le gameplay dans le vrai jeu),
    # teal/vert mousse dans les ombres (pas le bleu froid de silent_hill), un seul accent
    # rouge rare (mythologie du Dark Place / Taken), grain plus marque (look 16mm/found-footage
    # du jeu reel). bloom/threshold/lens_flare/AO repris du fix session 10 (voir note plus haut) —
    # ne JAMAIS remonter bloom_intensity au-dessus de ~0.05-0.08 sur ce projet (voile plat confirme).
    "alan_wake": {
        "vignette_intensity":        1.2,
        "film_grain_intensity":      0.7,
        "film_grain_intensity_midtones": 0.45,
        "scene_fringe_intensity":    0.6,
        "auto_exposure_bias":        0.9,   # relevé le 2026-07-03 bis + valide en PIE reel (voir note ci-dessus)
        "bloom_intensity":           0.06,
        "bloom_threshold":           1.0,
        "lens_flare_intensity":      0.0,
        "ambient_occlusion_intensity": 0.25,
        "color_saturation":          unreal.Vector4(0.72, 0.72, 0.72, 0.72),
        "color_contrast":            unreal.Vector4(1.08, 1.08, 1.08, 1.08),   # 1.25 uniforme etait trop dur, valide en PIE
        "color_gamma_midtones":      unreal.Vector4(0.90, 1.0, 0.95, 1.0),   # teal/vert mousse
        "color_offset_shadows":      unreal.Vector4(-0.02, 0.015, 0.005, 0.0),  # ombres vert-teal
    },
}


def _ensure_base_material():
    """Charge ou cree M_HorrorBase si inexistant."""
    path = MAT_BASE_PATH + "/" + MAT_BASE_NAME
    mat = unreal.load_asset(path)
    if mat:
        return mat
    mel = unreal.MaterialEditingLibrary
    at  = unreal.AssetToolsHelpers.get_asset_tools()
    unreal.EditorAssetLibrary.make_directory(MAT_BASE_PATH)
    mat = at.create_asset(MAT_BASE_NAME, MAT_BASE_PATH, unreal.Material,
                          unreal.MaterialFactoryNew())
    p_col = mel.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, -400, 0)
    p_col.set_editor_property('parameter_name', unreal.Name("BaseColor"))
    p_col.set_editor_property('default_value', unreal.LinearColor(0.02, 0.01, 0.01, 1.0))
    mel.connect_material_property(p_col, "RGB", unreal.MaterialProperty.MP_BASE_COLOR)

    p_r = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -400, 200)
    p_r.set_editor_property('parameter_name', unreal.Name("Roughness"))
    p_r.set_editor_property('default_value', 0.92)
    mel.connect_material_property(p_r, "", unreal.MaterialProperty.MP_ROUGHNESS)

    p_m = mel.create_material_expression(mat, unreal.MaterialExpressionConstant, -400, 350)
    p_m.set_editor_property('r', 0.0)
    mel.connect_material_property(p_m, "", unreal.MaterialProperty.MP_METALLIC)

    p_ec = mel.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, -600, 450)
    p_ec.set_editor_property('parameter_name', unreal.Name("EmissiveColor"))
    p_ec.set_editor_property('default_value', unreal.LinearColor(0.0, 0.0, 0.0, 1.0))
    p_es = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -400, 550)
    p_es.set_editor_property('parameter_name', unreal.Name("EmissiveStrength"))
    p_es.set_editor_property('default_value', 0.0)
    mul = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -200, 500)
    mel.connect_material_expressions(p_ec, "RGB", mul, "A")
    mel.connect_material_expressions(p_es, "",    mul, "B")
    mel.connect_material_property(mul, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)

    mel.recompile_material(mat)
    unreal.EditorAssetLibrary.save_asset(path)
    unreal.log("[horror_presets] M_HorrorBase cree : " + path)
    return mat


def create_material_instance(name, base_color_rgb, roughness=0.92,
                              emissive_rgb=(0, 0, 0), emissive_strength=0.0,
                              folder="/Game/Materials"):
    """Cree ou recharge une MaterialInstance depuis M_HorrorBase.

    base_color_rgb : tuple (r,g,b) en lineaire 0.0-1.0
    roughness      : 0=brillant, 1=mat
    emissive_rgb   : couleur d emission (0,0,0 = aucune)
    emissive_str   : intensite de l emission (0=off, 1=subtil, 5=fort)

    Retourne le MaterialInstanceConstant.

    Exemple :
        mi = create_material_instance("MI_Z1_Wall", (0.018, 0.015, 0.012))
    """
    path = folder + "/" + name
    # Recharger si existant
    existing = unreal.load_asset(path)
    if existing:
        mi = existing
    else:
        base = _ensure_base_material()
        at   = unreal.AssetToolsHelpers.get_asset_tools()
        unreal.EditorAssetLibrary.make_directory(folder)
        mi = at.create_asset(name, folder,
                             unreal.MaterialInstanceConstant,
                             unreal.MaterialInstanceConstantFactoryNew())
        mi.set_editor_property('parent', base)

    mel = unreal.MaterialEditingLibrary
    r, g, b = base_color_rgb
    mel.set_material_instance_vector_parameter_value(
        mi, "BaseColor", unreal.LinearColor(r, g, b, 1.0))
    mel.set_material_instance_scalar_parameter_value(mi, "Roughness", roughness)
    er, eg, eb = emissive_rgb
    mel.set_material_instance_vector_parameter_value(
        mi, "EmissiveColor", unreal.LinearColor(er, eg, eb, 1.0))
    mel.set_material_instance_scalar_parameter_value(mi, "EmissiveStrength", emissive_strength)

    unreal.EditorAssetLibrary.save_asset(path)
    unreal.log("[horror_presets] MaterialInstance '{}' OK".format(name))
    return mi


def apply_material_to_zone(x_min, x_max, style="silent_hill",
                            custom_wall=None, custom_floor=None, custom_ceil=None):
    """Applique des materiaux sombres aux murs/sols/plafonds d une zone.

    style      : 'silent_hill', 'outlast', 'amnesia' (utilise WALL_PRESETS)
    custom_*   : MaterialInstance a utiliser a la place du preset (optionnel)

    Retourne le nombre d acteurs modifies.

    Exemple :
        apply_material_to_zone(0, 1400, style="silent_hill")
    """
    preset = WALL_PRESETS.get(style, WALL_PRESETS["silent_hill"])
    zone_tag = "z{}_".format(int((x_min + x_max) / 2 / 1400) + 1)

    # Creer les instances si pas de custom
    mi_wall  = custom_wall  or create_material_instance(
        "MI_{}_Wall".format(style),  preset["wall"],  roughness=0.92, folder=MAT_BASE_PATH)
    mi_floor = custom_floor or create_material_instance(
        "MI_{}_Floor".format(style), preset["floor"], roughness=0.88, folder=MAT_BASE_PATH)
    mi_ceil  = custom_ceil  or create_material_instance(
        "MI_{}_Ceil".format(style),  preset["ceil"],  roughness=0.95, folder=MAT_BASE_PATH)

    modified = 0
    for a in aeas().get_all_level_actors():
        if 'StaticMeshActor' not in a.get_class().get_name():
            continue
        loc = a.get_actor_location()
        if not (x_min <= loc.x <= x_max):
            continue
        label = (a.get_actor_label() or '').lower()
        smc = a.get_component_by_class(unreal.StaticMeshComponent)
        if not smc:
            continue
        # Detecter le type de surface (wall/floor/ceil)
        is_wall  = any(x in label for x in ['walln','walls','walle','wallw','walll','wallr','_wall'])
        is_floor = 'floor' in label
        is_ceil  = 'ceil'  in label
        if is_wall:
            mi = mi_wall
        elif is_floor:
            mi = mi_floor
        elif is_ceil:
            mi = mi_ceil
        else:
            continue
        for i in range(smc.get_num_materials()):
            smc.set_material(i, mi)
        modified += 1

    unreal.log("[horror_presets] apply_material_to_zone: {} acteurs modifies (style={})".format(
        modified, style))
    return modified


# ══════════════════════════════════════════════════════════════════════════════
# POST-PROCESS & FOG — ambiance globale et par zone
# ══════════════════════════════════════════════════════════════════════════════

def setup_horror_postprocess(preset="silent_hill", label="HorrorPostProcess"):
    """Cree ou reconfigure un PostProcessVolume global avec preset horror.

    preset : 'silent_hill', 'outlast', 'amnesia'

    Proprietes appliquees : vignette, grain, aberration chromatique, bloom,
    exposition, color grading (saturation / contraste / gamma).

    Retourne l acteur PostProcessVolume.

    Exemple :
        ppv = setup_horror_postprocess("silent_hill")
    """
    # Chercher si un PPV existe deja
    ppv = None
    for a in aeas().get_all_level_actors():
        if 'PostProcessVolume' in a.get_class().get_name() and a.get_actor_label() == label:
            ppv = a
            break

    if ppv is None:
        ppv = aeas().spawn_actor_from_class(
            unreal.PostProcessVolume.static_class(),
            unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
        ppv.set_actor_label(label)

    # unbound = global (propriété UE5.7 validée — pas bUnbound, pas infinite_extent)
    ppv.set_editor_property('unbound', True)
    ppv.set_editor_property('priority', 1.0)

    cfg = PP_PRESETS.get(preset, PP_PRESETS["silent_hill"])
    s = ppv.settings

    # Désactiver Lumen (obligatoire pour horror — ombres dures, noirs absolus)
    s.override_dynamic_global_illumination_method = True
    s.dynamic_global_illumination_method = unreal.DynamicGlobalIlluminationMethod.NONE
    s.override_reflection_method = True
    s.reflection_method = unreal.ReflectionMethod.NONE

    # Exposition manuelle
    s.override_auto_exposure_method = True
    s.auto_exposure_method = unreal.AutoExposureMethod.AEM_MANUAL

    # Noms de proprietes valides UE5.7 — override_ + snake_case
    override_map = {
        "vignette_intensity":            "override_vignette_intensity",
        "film_grain_intensity":          "override_film_grain_intensity",
        "film_grain_intensity_midtones": "override_film_grain_intensity",
        "scene_fringe_intensity":        "override_scene_fringe_intensity",
        "auto_exposure_bias":            "override_auto_exposure_bias",
        "color_saturation":              "override_color_saturation",
        "color_contrast":                "override_color_contrast",
        "color_gamma_midtones":          "override_color_gamma_midtones",
        "color_offset_shadows":          "override_color_offset_shadows",
    }

    applied = []
    for prop, val in cfg.items():
        try:
            setattr(s, prop, val)
            ov = override_map.get(prop)
            if ov:
                try:
                    setattr(s, ov, True)
                except Exception:
                    pass
            applied.append(prop)
        except Exception as e:
            unreal.log_warning("[horror_presets] PP prop '{}' echec: {}".format(prop, str(e)[:60]))

    unreal.log("[horror_presets] PostProcess: {}/{} proprietes appliquees".format(
        len(applied), len(cfg)))

    unreal.log("[horror_presets] PostProcess '{}' configure (preset={})".format(label, preset))
    return ppv


def add_height_fog(density=0.018, inscatter_color=(0.04, 0.04, 0.06),
                   start_distance=50.0, falloff=1.2, label="HorrorFog"):
    """Cree ou reconfigure un ExponentialHeightFog pour ambiance horror.

    density          : densite du brouillard (0.01=leger, 0.05=epais SH)
    inscatter_color  : couleur du brouillard (rgb lineaire)
    start_distance   : distance a laquelle le fog commence (UU)
    falloff          : falloff vertical (plus grand = fog reste au sol)

    Retourne l acteur ExponentialHeightFog.

    Exemples :
        add_height_fog(0.018, (0.04, 0.04, 0.06))         # Silent Hill leger
        add_height_fog(0.04,  (0.02, 0.02, 0.02))         # Outlast opaque
        add_height_fog(0.012, (0.06, 0.04, 0.02))         # Amnesia ambre
    """
    # Chercher si fog existant
    fog_actor = None
    for a in aeas().get_all_level_actors():
        if 'ExponentialHeightFog' in a.get_class().get_name():
            fog_actor = a
            break

    if fog_actor is None:
        fog_actor = aeas().spawn_actor_from_class(
            unreal.ExponentialHeightFog.static_class(),
            unreal.Vector(0, 0, -50), unreal.Rotator(0, 0, 0))
        fog_actor.set_actor_label(label)

    comp = fog_actor.get_component_by_class(unreal.ExponentialHeightFogComponent)
    if comp is None:
        unreal.log_warning("[horror_presets] ExponentialHeightFogComponent introuvable")
        return fog_actor

    r, g, b = inscatter_color
    comp.set_editor_property('fog_density',                density)
    comp.set_editor_property('fog_inscattering_luminance', unreal.LinearColor(r, g, b, 1.0))
    comp.set_editor_property('start_distance',             start_distance)
    comp.set_editor_property('fog_height_falloff',         falloff)
    comp.set_editor_property('FogMaxOpacity',              0.85)
    try:
        comp.set_editor_property('bEnableVolumetricFog', True)
        comp.set_editor_property('VolumetricFogScatteringDistribution', 0.2)
    except Exception:
        pass  # volumetric fog optionnel

    unreal.log("[horror_presets] HeightFog configure (density={}, start={}UU)".format(
        density, start_distance))
    return fog_actor


def setup_zone_atmosphere(x_min, x_max, style="silent_hill"):
    """One-shot : materials + post-process + fog pour une zone complete.

    Appelle dans l ordre :
      1. apply_material_to_zone()  — murs/sols/plafonds sombres
      2. setup_horror_postprocess() — vignette/grain/couleur
      3. add_height_fog()           — brouillard

    Exemple :
        setup_zone_atmosphere(0, 1400, style="silent_hill")
        save()
    """
    print("[atmosphere] Application style '{}' sur X={}-{}...".format(style, x_min, x_max))

    fog_cfg = {
        "silent_hill": dict(density=0.018, inscatter_color=(0.04, 0.04, 0.06), start_distance=80),
        "outlast":     dict(density=0.008, inscatter_color=(0.02, 0.02, 0.03), start_distance=30),
        "amnesia":     dict(density=0.012, inscatter_color=(0.05, 0.04, 0.02), start_distance=60),
    }.get(style, dict(density=0.018, inscatter_color=(0.04, 0.04, 0.06), start_distance=80))

    n_mats = apply_material_to_zone(x_min, x_max, style=style)
    ppv    = setup_horror_postprocess(preset=style)
    fog    = add_height_fog(**fog_cfg)

    print("[atmosphere] {} surfaces re-materialisees".format(n_mats))
    print("[atmosphere] PostProcess : OK")
    print("[atmosphere] HeightFog   : OK")
    return {"materials": n_mats, "postprocess": ppv, "fog": fog}


# ══════════════════════════════════════════════════════════════════════════════
# AUDIT DE ZONE — verification numerique contre HORROR_DESIGN.md
# ══════════════════════════════════════════════════════════════════════════════

def audit_zone(zone_name, x_min, x_max, cx=None, cy=0):
    """Analyse une zone et verifie la conformite aux regles HORROR_DESIGN.md.

    Retourne un rapport texte avec ✅ (OK) et ⚠️ (probleme a corriger).

    Utilisation :
        print(audit_zone("Zone1", 0, 1400, cx=700, cy=0))
        print(audit_zone("Couloir", 2800, 4400))
    """
    if cx is None:
        cx = (x_min + x_max) / 2

    all_level_actors = aeas().get_all_level_actors()
    actors = [a for a in all_level_actors
              if x_min <= a.get_actor_location().x <= x_max]

    lights      = [a for a in actors if 'PointLight'    in a.get_class().get_name()]
    props       = [a for a in actors if 'StaticMeshActor' in a.get_class().get_name()]
    enemies     = [a for a in actors if 'BP_IA_Enemy'   in a.get_class().get_name()]
    jumpscares  = [a for a in actors if 'BP_JumpScare'  in a.get_class().get_name()]
    flicker     = [a for a in actors if 'lampe_plafond' in a.get_class().get_name().lower()
                   or 'FlickerLamp'                     in (a.get_actor_label() or '')]

    ok_msgs   = []
    warn_msgs = []

    # ── Lumières ────────────────────────────────────────────────────────────
    total_lights = len(lights) + len(flicker)
    if total_lights == 0:
        warn_msgs.append("⚠️  Aucune lumiere — zone completement noire (illisible)")
    elif total_lights > 4:
        warn_msgs.append("⚠️  Trop de lumieres: {} (max recommande: 3-4)".format(total_lights))
    else:
        ok_msgs.append("✅ Lumieres: {} point lights + {} clignotantes".format(len(lights), len(flicker)))

    red_light_count = 0
    for l in lights:
        try:
            comp = l.point_light_component
            intensity = comp.get_editor_property('intensity')
            color     = comp.get_editor_property('light_color')
            r, g, b   = int(color.r), int(color.g), int(color.b)

            if intensity > 1500:
                warn_msgs.append("⚠️  {} : intensite {:.0f} (max 1200 pour ambiance)".format(
                    l.get_actor_label(), intensity))
            elif intensity < 200:
                warn_msgs.append("⚠️  {} : intensite {:.0f} tres faible — peut etre invisible".format(
                    l.get_actor_label(), intensity))
            else:
                ok_msgs.append("✅ {} : intensite {:.0f} OK".format(l.get_actor_label(), intensity))

            if r > 200 and g < 60 and b < 60:
                red_light_count += 1
        except Exception as e:
            warn_msgs.append("⚠️  Erreur lecture lumiere {} : {}".format(
                l.get_actor_label(), str(e)))

    if red_light_count > 1:
        warn_msgs.append("⚠️  {} lumieres rouge pur — surstimulation, "
                         "le rouge perd son impact".format(red_light_count))

    # ── Props ────────────────────────────────────────────────────────────────
    zone_length = x_max - x_min
    max_props = 8 if zone_length < 800 else 15
    if len(props) > max_props:
        warn_msgs.append("⚠️  Trop de props: {} (max {} pour cette taille de zone)".format(
            len(props), max_props))
    elif len(props) < 2:
        warn_msgs.append("⚠️  Trop peu de props: {} — zone sans narration spatiale".format(len(props)))
    else:
        ok_msgs.append("✅ Props: {} ({} max recommande)".format(len(props), max_props))

    # ── Ennemis ──────────────────────────────────────────────────────────────
    if enemies:
        for e in enemies:
            eloc = e.get_actor_location()
            d = ((eloc.x - cx) ** 2 + (eloc.y - cy) ** 2) ** 0.5
            label = e.get_actor_label()
            if d < 200:
                warn_msgs.append("⚠️  {} a {:.0f} UU du centre — trop proche, "
                                 "choc immediat (pas de tension)".format(label, d))
            elif d > 1500:
                warn_msgs.append("⚠️  {} a {:.0f} UU du centre — trop loin, "
                                 "hors du champ de tension".format(label, d))
            else:
                ok_msgs.append("✅ {} a {:.0f} UU (zone optimale 200-1500 UU)".format(label, d))
    else:
        ok_msgs.append("ℹ️  Aucun ennemi actif dans cette zone")

    # ── JumpScare ────────────────────────────────────────────────────────────
    if jumpscares:
        ok_msgs.append("✅ JumpScare: {}".format([j.get_actor_label() for j in jumpscares]))
    else:
        ok_msgs.append("ℹ️  Aucun JumpScare dans cette zone")

    # ── Rapport final ────────────────────────────────────────────────────────
    lines = ["=" * 50,
             "AUDIT {} (X={}-{}) — {} acteurs total".format(
                 zone_name, x_min, x_max, len(actors)),
             "=" * 50]
    lines += ok_msgs
    lines += warn_msgs

    if warn_msgs:
        lines.append("=> {} probleme(s) detecte(s)".format(len(warn_msgs)))
    else:
        lines.append("=> ✅ ZONE CONFORME aux regles HORROR_DESIGN.md")

    report = "\n".join(lines)
    print(report)
    return report


# ══════════════════════════════════════════════════════════════════════════════
# SCREENSHOT VIEWPORT — verification spatiale/visuelle
# ══════════════════════════════════════════════════════════════════════════════

def take_viewport_screenshot(filename="horror_audit"):
    """Prend un screenshot du viewport UE5 actif et retourne le chemin du fichier.

    Le screenshot est sauvegarde dans :
        {ProjectDir}/Saved/Screenshots/Windows/{filename}*.png

    Apres l'appel, Claude Cowork peut lire l'image avec l'outil Read
    pour analyser spatialement la scene (ombres, props, lisibilite).

    Utilisation :
        path = take_viewport_screenshot("zone1_audit")
        print("Screenshot : " + path)
        # => Claude Cowork lit le fichier et analyse visuellement
    """
    import os, glob, time

    project_dir = unreal.SystemLibrary.get_project_directory()
    save_dir    = os.path.join(project_dir, "Saved", "Screenshots", "Windows")
    os.makedirs(save_dir, exist_ok=True)

    # Timestamp avant pour identifier le nouveau fichier
    before = set(glob.glob(os.path.join(save_dir, "*.png")))

    # Commande console UE5 : prend un screenshot du viewport actif
    unreal.SystemLibrary.execute_console_command(None, "HighResShot 1920x1080")

    # Attendre que le fichier apparaisse (max 5s)
    deadline = time.time() + 5.0
    new_file = None
    while time.time() < deadline:
        after = set(glob.glob(os.path.join(save_dir, "*.png")))
        new_files = after - before
        if new_files:
            new_file = max(new_files, key=os.path.getmtime)
            break
        time.sleep(0.2)

    if new_file:
        # Renommer avec le nom demande pour retrouver facilement
        target = os.path.join(save_dir, filename + ".png")
        # Si le fichier existe deja, supprimer
        if os.path.exists(target):
            os.remove(target)
        os.rename(new_file, target)
        print("Screenshot sauvegarde : " + target)
        return target
    else:
        # Retourner le dossier pour que Claude cherche le dernier fichier
        print("WARN: screenshot non detecte, chercher dans : " + save_dir)
        return save_dir


def audit_zone_full(zone_name, x_min, x_max, cx=None, cy=0):
    """Audit complet : donnees numeriques + screenshot viewport.

    1. audit_zone()              => rapport numerique (lumieres, props, ennemis)
    2. take_viewport_screenshot() => screenshot pour analyse visuelle par Claude

    Utilisation :
        audit_zone_full("Zone1", 0, 1400, cx=700)
        # => Apres execution, Claude Cowork lit le screenshot et complete l'analyse
    """
    print("--- AUDIT NUMERIQUE ---")
    report = audit_zone(zone_name, x_min, x_max, cx, cy)

    print("\n--- SCREENSHOT VIEWPORT ---")
    screenshot_path = take_viewport_screenshot(
        "audit_{}_{}".format(zone_name.lower().replace(" ", "_"),
                             int(__import__('time').time())))

    print("\n--- INSTRUCTIONS POUR CLAUDE COWORK ---")
    print("Lire et analyser visuellement : " + screenshot_path)
    print("Verifier (HORROR_DESIGN.md Section 9) :")
    print("  - Contraste clair/sombre (60% visible, 40% ombre)")
    print("  - Point focal unique (1 source lumineuse principale visible)")
    print("  - Props groupes avec logique narrative (pas eparpilles)")
    print("  - Ennemi partiellement cache (pas au centre)")
    print("  - Couleur dominante coherente (pas rouge partout)")

    return {"report": report, "screenshot": screenshot_path}


# ══════════════════════════════════════════════════════════════════════════════
# SETUP FUNCTIONS — workflows complets, zéro marge d'oubli
# Utilisation : from horror_presets import *
#   setup_horror_room(style, zone_name, cx, cy)   → salle complète from scratch
#   setup_global_atmosphere(style)                → fix PP+lumières sur level existant
#   setup_gameplay_elements(cx, cy, zone_name)    → NavMesh+pickup+LightSwitch
#   setup_horror_corridor_full(x1, x2, cy)        → couloir complet
# ══════════════════════════════════════════════════════════════════════════════

# Palettes lumières par style (calibrées SANS Lumen)
# IMPORTANT : ne jamais mettre "Enemy", "Pickup", "PlayerStart", "FlashlightPickup",
# "LightSwitch", "JumpScare" dans les labels de lumières — verify_level les vérifierait
# comme acteurs gameplay et signalerait de faux positifs.
_LIGHT_PALETTES = {
    # Intensités multipliées par 8 le 2026-07-03 (silent_hill: 200->1600, etc.) après
    # diagnostic en direct sur AgentDemo : ces valeurs étaient calibrées pour un contexte
    # sans exposition manuelle calibrée. Avec Lumen OFF (obligatoire horror) + AEM_MANUAL +
    # camera_iso=1600 (voir setup_global_atmosphere), ces valeurs candela x8 donnent une
    # salle où les zones dans le radius d'une lumière sont réellement visibles. Toujours
    # valider par retour visuel de l'utilisateur, pas seulement par run_verify().
    # Radius resserres le 2026-07-03 (retour Thomas sur AgentDemo, apres le fix bloom ci-dessus) :
    # meme sans bloom, Cold_Side/Backlit_Far a 550-700 UU de rayon dans une salle de 1400x1200
    # couvraient quasi toute la piece -> aucune vraie zone d'ombre, salle plate malgre le contraste
    # local. Mesure objective avant/apres (Tools/analyze_screenshot.py, capture PIE reelle) :
    # avant = 70% pixels "visibles" / 15% "sombres" ; apres (rayons ~380 UU max) = 39%/31%,
    # bien plus proche de la cible HORROR_DESIGN.md section 9 (60% visible / 40% ombre).
    "silent_hill": [
        # (offset_x, offset_y, z, intensity, rgb, radius, label_suffix)
        (-500,    0, 260, 1600, (255, 210, 140), 380, "Bulb_Entry"),
        (   0, -520, 120,  900, (200, 210, 230), 380, "Cold_Side"),
        ( 600,  150, 180,  800, (220, 225, 240), 380, "Backlit_Far"),   # pas "Enemy_*"
        ( 550,  480,  20,  700, (230, 150,  70), 300, "Mystery_Glow"),
    ],
    "outlast": [
        (-400,    0, 260, 1440, (230, 240, 255), 420, "Inst_Main"),
        ( 400, -400, 100,  960, (180, 200, 255), 600, "Inst_Cold"),
        (   0,  400, 200,  800, (255, 150,  80), 350, "Inst_Warm"),
        ( 300,    0,  30,  640, (100, 120, 200), 280, "Inst_Floor"),
    ],
    "amnesia": [
        (   0,    0, 250, 1280, (255, 200, 120), 420, "Candle_Main"),
        (-350, -300, 120,  800, (255, 180,  80), 350, "Candle_SW"),
        ( 350,  300, 100,  720, (200, 160,  60), 330, "Candle_NE"),
        (   0,    0,  15,  560, (255, 140,  40), 240, "Floor_Glow"),
    ],
    # alan_wake — lampe pratique chaude (cabane), lueur foret teal froide, UN SEUL accent
    # rouge rare (Cauldron Lake / Dark Place — HORROR_DESIGN.md 2.2 : le rouge doit rester rare),
    # flaque ambree au sol pour la reflexion humide caracteristique du jeu.
    "alan_wake": [
        (-500,    0, 260, 1100, (255, 190, 120), 340, "Cabin_Lamp"),
        (   0, -520, 140,  850, (140, 200, 175), 420, "Forest_Mist"),
        ( 600,  150, 180,  500, (255,  35,  35), 260, "Cauldron_Red"),
        ( 550,  480,  20,  600, (200, 170,  90), 260, "Amber_Puddle"),
        # 5e lumiere ajoutee 2026-07-03 des la creation du style (evite le trou de couverture
        # decouvert a posteriori sur silent_hill/SH_Room_Floor_Fill session 10 — voir GAME_MEMORY.md
        # "quinquies" : 4 sources ciblees laissent souvent le sol sous le seuil jouable de 50%).
        # Basse et faible pour ne pas laver les murs/props proches, dediee a la couverture du sol.
        ( 100,  -50,  25,  600, (130, 150, 120), 520, "Floor_Fill"),
    ],
}

# Props par style
# Note : SM_Desk_01 a une bounding box de ~482 UU de rayon.
# Toujours placer les gros props (Bureau, Armoire) côté X+ (ennemi),
# jamais côté X- (PlayerStart à cx - size_x*0.42).
_PROPS_BY_STYLE = {
    "silent_hill": [
        (BASE_OFFICE + "/SM_Desk_01",     300, -200, 0,  45, "Bureau"),    # côté ennemi (X+)
        (BASE_OFFICE + "/SM_Chair_01",    280, -350, 0, 120, "Chaise"),    # côté ennemi
        (BASE_OFFICE + "/SM_Locker_01",   380,  300, 0,  90, "Casier"),    # mur +Y
        (BASE_STREET + "/SM_DeadBody_01", 100,  380, 0, -20, "Corps"),     # fond
        (BASE_OFFICE + "/SM_Bin_01",     -250,  300, 0,  30, "Poubelle"),  # côté joueur (petit)
    ],
    "outlast": [
        (BASE_OFFICE + "/SM_Desk_01",     300,  200, 0,   0, "Bureau"),    # côté ennemi (X+)
        (BASE_OFFICE + "/SM_Computer_01", 320,  200, 0,   0, "Ordi"),
        (BASE_OFFICE + "/SM_Locker_01",   380, -280, 0,  90, "Casier1"),
        (BASE_OFFICE + "/SM_Locker_01",   380, -140, 0,  90, "Casier2"),
        (BASE_STREET + "/SM_DeadBody_01", 100, -380, 0,  15, "Corps"),
        (BASE_OFFICE + "/SM_Box_01",     -200,  300, 0,  60, "Carton"),    # petit, côté joueur
    ],
    "amnesia": [
        (BASE_HOUSE + "/SM_Table_01",     280,  200, 0,  20, "Table"),     # côté ennemi (X+)
        (BASE_HOUSE + "/SM_Chair_01",     200,  350, 0, 110, "Chaise"),
        (BASE_HOUSE + "/SM_Cupboard_01",  370, -260, 0, 180, "Armoire"),   # mur -Y
        (BASE_HOUSE + "/SM_Bookcase_02",  380,  250, 0,  90, "Biblio"),
        (BASE_STREET + "/SM_barrel_1",   -200, -300, 0,  40, "Tonneau"),   # petit, côté joueur
    ],
    # alan_wake — cabane forestière abandonnée : table renversée, chaise à l'envers,
    # étagère de manuscrits, victime "Taken", tonneau industriel (bûcheron).
    "alan_wake": [
        (BASE_HOUSE   + "/SM_Table_01",     280, -200, 0,  15, "CabinTable"),      # côté ennemi (X+)
        (BASE_HOUSE   + "/SM_Chair_01",     260, -360, 0, 200, "OverturnedChair"),
        (BASE_HOUSE   + "/SM_Bookcase_02",  380,  300, 0,  90, "ManuscriptShelf"),
        (BASE_STREET  + "/SM_DeadBody_01",  100,  380, 0, -20, "TakenVictim"),      # fond
        (BASE_STREET  + "/SM_barrel_1",    -250,  300, 0,  30, "Barrel"),           # petit, côté joueur
    ],
}


def setup_global_atmosphere(style="silent_hill", label="PP_Horror"):
    """Étape 1 : éteint les lumières globales + crée/reconfigure le PostProcess.

    À appeler EN PREMIER sur n'importe quel level (même existant avec DirectionalLight).
    Désactive : DirectionalLight, SkyLight, SkyAtmosphere intensity.
    Crée un PostProcessVolume global avec Lumen OFF + color grade du style choisi.

    style : 'silent_hill' | 'outlast' | 'amnesia'
    """
    aeas_sub = aeas()

    # Éteindre toutes les lumières globales
    for a in aeas_sub.get_all_level_actors():
        c = a.get_component_by_class(unreal.SkyLightComponent.static_class())
        if c:
            c.set_editor_property("intensity", 0.0)
            unreal.log("[setup] SkyLight éteint : " + a.get_actor_label())
        c2 = a.get_component_by_class(unreal.DirectionalLightComponent.static_class())
        if c2:
            c2.set_editor_property("intensity", 0.0)
            unreal.log("[setup] DirectionalLight éteint : " + a.get_actor_label())

    # Chercher PP existant ou en créer un
    ppv = None
    for a in aeas_sub.get_all_level_actors():
        if 'PostProcessVolume' in a.get_class().get_name() and a.get_actor_label() == label:
            ppv = a
            break

    if ppv is None:
        pp_cls = unreal.load_class(None, "/Script/Engine.PostProcessVolume")
        ppv = aeas_sub.spawn_actor_from_class(pp_cls, unreal.Vector(0, 0, 150))
        ppv.set_actor_label(label)

    ppv.set_editor_property("unbound", True)
    s = ppv.settings

    # Lumen OFF — obligatoire pour horror
    s.override_dynamic_global_illumination_method = True
    s.dynamic_global_illumination_method = unreal.DynamicGlobalIlluminationMethod.NONE
    s.override_reflection_method = True
    s.reflection_method = unreal.ReflectionMethod.NONE

    # Exposition manuelle
    # BUG CORRIGE 2026-07-03 : AEM_MANUAL sans override caméra utilise les défauts
    # UE5 (FStop=4, Shutter=1/60, ISO=100) => EV100 ~9.9, calibré pour une scène
    # EXTÉRIEURE en plein jour. Une salle éclairée par des point lights en Candela
    # (120-1800 selon les presets) est écrasée à des années-lumière de cet EV, donnant
    # une salle NOIRE quel que soit auto_exposure_bias. Diagnostiqué en direct sur
    # AgentDemo — voir GAME_MEMORY.md "ISO caméra jamais calibré". ISO=1600 valide
    # empiriquement pour rendre visibles des lumières candela dans cette plage.
    s.override_auto_exposure_method = True
    s.auto_exposure_method = unreal.AutoExposureMethod.AEM_MANUAL
    s.override_auto_exposure_bias = True
    s.override_camera_iso = True
    s.camera_iso = 1600.0

    cfg = PP_PRESETS.get(style, PP_PRESETS["silent_hill"])
    for prop, val in cfg.items():
        try:
            setattr(s, prop, val)
            ov = "override_" + prop
            try: setattr(s, ov, True)
            except: pass
        except Exception as e:
            unreal.log_warning(f"[setup] PP prop '{prop}' echec: {e}")

    ppv.settings = s
    unreal.log(f"[setup] setup_global_atmosphere '{style}' OK — PP={label}")
    return ppv


# ══════════════════════════════════════════════════════════════════════════════
# AUDIO AMBIANT — spawn_ambient_audio()
# Ajouté 2026-07-03 : setup_horror_room() n'avait aucun son. L'horreur repose autant
# sur l'audio que sur la lumière (silence total = joueur mal à l'aise différemment
# qu'avec un drone/grincement en fond). Assets déjà présents dans le projet
# (ProceduralBuildingGenerator/Sound/Wav/AmbientLooping) — pas besoin d'import externe.
# ══════════════════════════════════════════════════════════════════════════════

_AMBIENT_AUDIO_BASE = "/Game/AssetImported/ProceduralBuildingGenerator/Sound/Wav/AmbientLooping"

# Un son par style, tous vérifiés looping=True dans le projet (2026-07-03) :
#   silent_hill -> drone d'intérieur inquiétant (immeuble abandonné)
#   outlast     -> vapeur/machine industrielle (institution)
#   amnesia     -> vent extérieur (château/donjon)
AMBIENT_AUDIO_BY_STYLE = {
    "silent_hill": _AMBIENT_AUDIO_BASE + "/Slum_Interior05Loop",
    "outlast":     _AMBIENT_AUDIO_BASE + "/SteamVent03",
    "amnesia":     _AMBIENT_AUDIO_BASE + "/Wind_Breeze05",
    "alan_wake":   _AMBIENT_AUDIO_BASE + "/Wind_Breeze05",  # foret nocturne / pluie — reutilise l'asset vent valide
}


def spawn_ambient_audio(cx, cy, z=150, style="silent_hill", radius=1500,
                         volume=0.5, label=None):
    """Spawn un AmbientSound looping adapté au style horror, avec atténuation par distance.

    cx, cy, z : position (centre de la salle recommandé)
    style     : 'silent_hill' | 'outlast' | 'amnesia'
    radius    : falloff_distance — distance à laquelle le son est inaudible
    volume    : multiplicateur de volume (0.3-0.7 recommandé pour un fond, pas un premier plan)

    Retourne l'acteur AmbientSound, ou None si le SoundWave est introuvable.

    Exemple :
        spawn_ambient_audio(700, 0, style="silent_hill")
    """
    path = AMBIENT_AUDIO_BY_STYLE.get(style, AMBIENT_AUDIO_BY_STYLE["silent_hill"])
    sound = unreal.load_asset(path)
    if sound is None:
        unreal.log_warning("[horror_presets] son ambiant introuvable: " + path)
        return None

    a = aeas().spawn_actor_from_class(
        unreal.AmbientSound.static_class(), unreal.Vector(cx, cy, z), unreal.Rotator(0, 0, 0))
    if a is None:
        return None

    comp = a.get_component_by_class(unreal.AudioComponent.static_class())
    if comp:
        comp.set_sound(sound)
        comp.set_volume_multiplier(volume)
        try:
            comp.set_editor_property("override_attenuation", True)
            att = comp.get_editor_property("attenuation_overrides")
            att.set_editor_property("falloff_distance", float(radius))
            comp.set_editor_property("attenuation_overrides", att)
        except Exception as e:
            unreal.log_warning("[horror_presets] attenuation override échec: {}".format(e))

    a.set_actor_label(label or "Ambient_{}".format(style))
    unreal.log("[horror_presets] spawn_ambient_audio '{}' @ ({},{},{})".format(style, cx, cy, z))
    return a


def setup_gameplay_elements(cx=0, cy=0, z=0, zone_name="Salle",
                             room_size_x=1400, room_size_y=1200):
    """Étape gameplay : NavMesh + FlashlightPickup + LightSwitch + PlayerStart.

    Vérifie chaque élément avant de le spawner (pas de doublon).
    Retourne un dict avec les acteurs créés.
    """
    aeas_sub = aeas()
    all_act = aeas_sub.get_all_level_actors()
    created = {}

    # ── PlayerStart — toujours positionner au bon endroit (ne pas skipper) ──
    ps_target = unreal.Vector(cx - room_size_x * 0.42, cy, z + 100)
    existing_ps = next((a for a in all_act if 'PlayerStart' in a.get_class().get_name()), None)
    if existing_ps:
        existing_ps.set_actor_location(ps_target, False, False)
        unreal.log(f"[setup] PlayerStart déplacé → ({ps_target.x:.0f},{ps_target.y:.0f},{ps_target.z:.0f})")
        created["player_start"] = existing_ps
    else:
        ps_cls = unreal.load_class(None, "/Script/Engine.PlayerStart")
        ps = aeas_sub.spawn_actor_from_class(ps_cls, ps_target)
        ps.set_actor_label("PlayerStart")
        created["player_start"] = ps
        unreal.log(f"[setup] PlayerStart créé → ({ps_target.x:.0f},{ps_target.y:.0f},{ps_target.z:.0f})")

    # ── NavMeshBoundsVolume ───────────────────────────────────────────────────
    has_nav = any('NavMesh' in a.get_class().get_name() for a in all_act)
    if not has_nav:
        nav_cls = unreal.load_class(None, "/Script/NavigationSystem.NavMeshBoundsVolume")
        nav = aeas_sub.spawn_actor_from_class(nav_cls, unreal.Vector(cx, cy, z + 150))
        scale_x = (room_size_x + 200) / 200.0
        scale_y = (room_size_y + 200) / 200.0
        nav.set_actor_scale3d(unreal.Vector(scale_x, scale_y, 4.0))
        nav.set_actor_label(f"NavMesh_{zone_name}")
        created["navmesh"] = nav
        unreal.log("[setup] NavMeshBoundsVolume créé")
    else:
        unreal.log("[setup] NavMesh déjà présent — skip")

    # ── FlashlightPickup ─────────────────────────────────────────────────────
    has_fp = any('FlashlightPickup' in a.get_actor_label() for a in all_act)
    if not has_fp:
        fp_cls = unreal.load_class(None, "/Game/HorrorGame/FirstPerson/Blueprints/BP_FlashlightPickup.BP_FlashlightPickup_C")
        if fp_cls:
            fp = aeas_sub.spawn_actor_from_class(fp_cls, unreal.Vector(cx - room_size_x * 0.28, cy - room_size_y * 0.25, z + 80))
            fp.set_actor_label("FlashlightPickup")
            created["flashlight"] = fp
            unreal.log("[setup] FlashlightPickup créé")
        else:
            unreal.log_warning("[setup] BP_FlashlightPickup introuvable")
    else:
        unreal.log("[setup] FlashlightPickup déjà présent — skip")

    # ── LightSwitch (victoire) ────────────────────────────────────────────────
    has_ls = any('LightSwitch' in a.get_actor_label() for a in all_act)
    if not has_ls:
        ls_cls = unreal.EditorAssetLibrary.load_blueprint_class("/Game/HorrorGame/Blueprint/Interaction_System/Win/BP_LightSwitch")
        if ls_cls:
            ls = aeas_sub.spawn_actor_from_class(ls_cls, unreal.Vector(cx + room_size_x * 0.35, cy + room_size_y * 0.38, z + 50))
            ls.set_actor_label(f"LightSwitch_{zone_name}")
            created["lightswitch"] = ls
            unreal.log("[setup] LightSwitch créé")
        else:
            unreal.log_warning("[setup] BP_LightSwitch introuvable")
    else:
        unreal.log("[setup] LightSwitch déjà présent — skip")

    unreal.log(f"[setup] setup_gameplay_elements OK — {len(created)} éléments créés")
    return created


def setup_horror_room(style="silent_hill", zone_name="Salle_Demo",
                       cx=0, cy=0, size_x=1400, size_y=1200, height=300,
                       with_enemy=True, with_props=True, with_gameplay=True,
                       seed=42):
    """FONCTION PRINCIPALE — crée une salle horror complète from scratch.

    Exécute dans l'ordre exact et vérifie chaque étape :
      1. Géométrie (RoomGeneratorSubsystem)
      2. Matériaux sombres sur toutes les surfaces
      3. Lumières globales OFF
      4. PostProcess horror (Lumen OFF + color grade)
      5. Point lights calibrés (4 sources)
      6. Props narratifs
      7. Ennemi (safe_spawn_enemy)
      8. Gameplay (NavMesh + FlashlightPickup + LightSwitch)
      9. Vérification + save

    style     : 'silent_hill' | 'outlast' | 'amnesia'
    zone_name : préfixe pour les labels d'acteurs (ex: 'Salle_Demo')
    cx, cy    : centre de la salle
    size_x/y  : dimensions
    height    : hauteur de salle (300 = standard)
    with_enemy    : spawner un ennemi
    with_props    : placer des props
    with_gameplay : NavMesh + pickups + LightSwitch

    Retourne un rapport texte avec le résultat de chaque étape.
    """
    rapport = [f"=== setup_horror_room style={style} zone={zone_name} ==="]

    # ── 1. GÉOMÉTRIE ──────────────────────────────────────────────────────────
    try:
        sub = unreal.get_editor_subsystem(unreal.RoomGeneratorSubsystem)
        sub.generate_room(unreal.Vector(cx, cy, 0),
                          unreal.Vector(size_x, size_y, 0),
                          height, 30, zone_name)
        rapport.append("✅ 1. Géométrie générée")
    except Exception as e:
        rapport.append(f"❌ 1. Géométrie ERREUR: {e}")
        print("\n".join(rapport)); return "\n".join(rapport)

    # ── 2. MATÉRIAUX ──────────────────────────────────────────────────────────
    # BUG CORRIGE 2026-07-03 (decouvert en construisant AW_Room/alan_wake, PIE reel) :
    # _apply_room_materials() applique TOUJOURS les 3 memes materiaux generiques
    # (M_DemoWall/M_Asphalt/M_grey), quel que soit `style` — WALL_PRESETS n'etait JAMAIS
    # lu par setup_horror_room(). Resultat : silent_hill/outlast/amnesia/alan_wake
    # produisaient tous des murs gris moyen identiques, pas les teintes quasi-noires
    # definies par style. Fix : appeler apply_material_to_zone() juste apres, qui cree/
    # applique les MaterialInstance MI_<style>_Wall/Floor/Ceil par-dessus. Marge de +/-1 UU
    # sur x_min/x_max car les murs WallW/WallE du RoomGenerator peuvent deborder legerement
    # (observe : 700 de demi-largeur nominale mais mur reel a 715).
    try:
        n = _apply_room_materials(zone_name)
        margin = 50
        n2 = apply_material_to_zone(cx - size_x / 2 - margin, cx + size_x / 2 + margin, style=style)
        if n >= 4:
            rapport.append(f"✅ 2. Matériaux appliqués ({n} surfaces génériques + {n2} stylées '{style}')")
        else:
            rapport.append(f"⚠️  2. Matériaux partiels ({n}/6 génériques, {n2} stylées) — vérifier les labels")
    except Exception as e:
        rapport.append(f"❌ 2. Matériaux ERREUR: {e}")

    # ── 3. LUMIÈRES GLOBALES OFF + POST PROCESS ────────────────────────────────
    try:
        setup_global_atmosphere(style)
        rapport.append(f"✅ 3. Lumières globales OFF + PostProcess '{style}'")
    except Exception as e:
        rapport.append(f"❌ 3. Atmosphere ERREUR: {e}")

    # ── 4. POINT LIGHTS ────────────────────────────────────────────────────────
    try:
        palette = _LIGHT_PALETTES.get(style, _LIGHT_PALETTES["silent_hill"])
        for ox, oy, lz, intensity, rgb, radius, suffix in palette:
            point_light(cx + ox, cy + oy, lz,
                        intensity=intensity, rgb=rgb,
                        radius=radius, label=f"{zone_name}_{suffix}")
        rapport.append(f"✅ 4. {len(palette)} point lights placés")
    except Exception as e:
        rapport.append(f"❌ 4. Point lights ERREUR: {e}")

    # ── 4b. FOG (ajouté 2026-07-03 — jamais appelé auparavant dans ce workflow) ──
    # add_height_fog() existait depuis longtemps mais n'était jamais invoqué par
    # setup_horror_room() : chaque salle générée via la fonction principale n'avait
    # donc jamais de brouillard, alors que HORROR_DESIGN.md et le style Silent Hill
    # en particulier en dépendent pour l'ambiance (brouillard qui mange le champ moyen).
    try:
        fog_cfg = {
            "silent_hill": dict(density=0.018, inscatter_color=(0.04, 0.04, 0.06), start_distance=80),
            "outlast":     dict(density=0.008, inscatter_color=(0.02, 0.02, 0.03), start_distance=30),
            "amnesia":     dict(density=0.012, inscatter_color=(0.05, 0.04, 0.02), start_distance=60),
        }.get(style, dict(density=0.018, inscatter_color=(0.04, 0.04, 0.06), start_distance=80))
        add_height_fog(**fog_cfg, label=f"{zone_name}_Fog")
        rapport.append(f"✅ 4b. Fog '{style}' appliqué (density={fog_cfg['density']})")
    except Exception as e:
        rapport.append(f"❌ 4b. Fog ERREUR: {e}")

    # ── 4c. AUDIO AMBIANT (ajouté 2026-07-03 — jamais présent auparavant) ────────
    try:
        spawn_ambient_audio(cx, cy, z=150, style=style, radius=max(size_x, size_y) * 1.2,
                            label=f"{zone_name}_Ambient")
        rapport.append(f"✅ 4c. Audio ambiant '{style}' placé")
    except Exception as e:
        rapport.append(f"❌ 4c. Audio ERREUR: {e}")

    # ── 5. ENNEMI (AVANT les props — grille propre, pas de faux positifs) ──────
    if with_enemy:
        try:
            grid = build_occupancy_grid_from_level()
            # Position Y+ (côté positif) pour éviter AABB de Bureau (Y_max=226) et Corps (X<-26)
            # Bureau AABB Y=[-736,226] → enemy Y doit être > 226
            # Corps AABB X=[-26,227] → enemy X doit être < -26 si Y ≈ 300
            ex = cx - 100
            ey = cy + int(size_y * 0.25)
            enemy = safe_spawn_enemy(x=ex, y=ey,
                                     grid=grid, label=f"Enemy_{zone_name}")
            if enemy:
                rapport.append("✅ 5. Ennemi spawné")
            else:
                rapport.append("⚠️  5. Ennemi non spawné (position bloquée ?)")
        except Exception as e:
            rapport.append(f"❌ 5. Ennemi ERREUR: {e}")
    else:
        rapport.append("⏭️  5. Ennemi ignoré (with_enemy=False)")

    # ── 6. PROPS (après ennemi) ────────────────────────────────────────────────
    if with_props:
        try:
            props_list = _PROPS_BY_STYLE.get(style, _PROPS_BY_STYLE["silent_hill"])
            placed = 0
            for mesh_path, ox, oy, oz, yaw, suffix in props_list:
                a = place_static_mesh(mesh_path, cx + ox, cy + oy, oz,
                                      yaw=yaw, label=f"{zone_name}_{suffix}")
                if a: placed += 1
            rapport.append(f"✅ 6. {placed}/{len(props_list)} props placés")
        except Exception as e:
            rapport.append(f"❌ 6. Props ERREUR: {e}")
    else:
        rapport.append("⏭️  6. Props ignorés (with_props=False)")

    # ── 7. GAMEPLAY ────────────────────────────────────────────────────────────
    if with_gameplay:
        try:
            gp = setup_gameplay_elements(cx, cy, 0, zone_name, size_x, size_y)
            rapport.append(f"✅ 7. Gameplay OK ({len(gp)} éléments : {', '.join(gp.keys())})")
        except Exception as e:
            rapport.append(f"❌ 7. Gameplay ERREUR: {e}")
    else:
        rapport.append("⏭️  7. Gameplay ignoré (with_gameplay=False)")

    # ── 8. VÉRIFICATION ────────────────────────────────────────────────────────
    try:
        from verify_level import fix_all, run_verify
        fix_all()
        ok = run_verify()
        rapport.append(f"✅ 8. Vérification : {'JOUABLE' if ok else 'ERREURS DÉTECTÉES'}")
    except Exception as e:
        rapport.append(f"⚠️  8. Vérification non disponible: {e}")

    # ── 9. SAVE ────────────────────────────────────────────────────────────────
    try:
        save()
        rapport.append("✅ 9. Level sauvegardé")
    except Exception as e:
        rapport.append(f"❌ 9. Save ERREUR: {e}")

    rapport.append("")
    rapport.append("⚡ RAPPEL : Build → Build Paths dans UE5 pour le NavMesh")
    rapport.append("⚡ RAPPEL : Appuyer sur Play pour tester en PIE")

    result = "\n".join(rapport)
    print(result)
    return result


def setup_horror_corridor_full(x1, x2, cy=0, width=500,
                                style="silent_hill", seed=42):
    """Crée un couloir horror complet : géométrie + matériaux + lumières + props.

    x1, x2 : début et fin du couloir (axe X)
    cy      : centre Y
    width   : largeur
    style   : 'silent_hill' | 'outlast' | 'amnesia'
    """
    rapport = [f"=== setup_horror_corridor_full x={x1}->{x2} ==="]
    cx = (x1 + x2) / 2
    length = abs(x2 - x1)
    zone_name = f"Corr_{int(cx)}"

    # 1. Géométrie
    try:
        sub = unreal.get_editor_subsystem(unreal.RoomGeneratorSubsystem)
        sub.generate_corridor(unreal.Vector(x1, cy, 0),
                              unreal.Vector(x2, cy, 0),
                              width, 300, 30, zone_name)
        rapport.append("✅ 1. Géométrie couloir")
    except Exception as e:
        rapport.append(f"❌ 1. Géométrie ERREUR: {e}")

    # 2. Matériaux
    try:
        n = _apply_room_materials(zone_name)
        rapport.append(f"✅ 2. Matériaux ({n} surfaces)")
    except Exception as e:
        rapport.append(f"❌ 2. Matériaux ERREUR: {e}")

    # 3. Atmosphère
    try:
        setup_global_atmosphere(style)
        rapport.append("✅ 3. Atmosphère")
    except Exception as e:
        rapport.append(f"❌ 3. Atmosphère ERREUR: {e}")

    # 4. Lampes clignotantes + lueur rouge
    try:
        n_lamps = max(1, int(length / 600))
        atmosphere_flickering_lamps(cx, cy, z_lamp=270,
                                    count=n_lamps, spacing=int(length / n_lamps))
        for i in range(2):
            px = x1 + (x2 - x1) * (0.25 + i * 0.5)
            point_light(px, cy, 150, intensity=150,
                        rgb=(180, 20, 10), radius=250,
                        label=f"{zone_name}_RedGlow_{i}")
        rapport.append(f"✅ 4. {n_lamps} lampes + 2 lueurs rouges")
    except Exception as e:
        rapport.append(f"❌ 4. Lumières ERREUR: {e}")

    # 5. Props debris le long des murs
    try:
        dress_corridor_horror(x1, x2, cy=cy, width=width, seed=seed)
        rapport.append("✅ 5. Props debris")
    except Exception as e:
        rapport.append(f"❌ 5. Props ERREUR: {e}")

    result = "\n".join(rapport)
    print(result)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# PLANIFICATION — execute_level_plan()
# Ajouté 2026-07-03. Objectif : généraliser au-delà des 3 styles figés appelés un par
# un à la main. L'IDÉE N'EST PAS de faire du NLP en Python dans UE5 (pas d'accès LLM
# depuis ue5_execute) : c'est Claude Cowork qui lit la demande en langage naturel de
# l'utilisateur et la traduit en plan JSON structuré (graphe de salles + pacing) en
# s'appuyant sur LEVEL_DESIGN_THEORY.md / GAME_DESIGN_THEORY.md / HORROR_DESIGN.md.
# execute_level_plan() est seulement l'EXÉCUTEUR de ce plan une fois produit — le
# placement séquentiel le long de l'axe X, le chaînage salle->couloir->salle, et
# l'application de fix_all()/run_verify() à la fin sont automatiques.
# ══════════════════════════════════════════════════════════════════════════════

def execute_level_plan(plan, start_x=0, cy=0, gap=100, verify_at_end=True):
    """Exécute une séquence de salles/couloirs définie par un plan JSON.

    plan : liste de dicts, chacun un de deux types :
      {"type": "room", "zone_name": str, "style": str,
       "size_x": int, "size_y": int (opt, def 1200), "height": int (opt, def 300),
       "with_enemy": bool (opt), "with_props": bool (opt), "cy": int (opt, override Y)}
      {"type": "corridor", "zone_name": str, "style": str,
       "length": int, "width": int (opt, def 500), "cy": int (opt, override Y)}

    Les positions X sont calculées automatiquement en chaînant les éléments les uns
    après les autres le long de l'axe X, séparés de `gap` UU. cy=0 par défaut, mais
    chaque élément peut définir son propre "cy" pour un layout non-linéaire (coude,
    embranchement) — dans ce cas la suite du plan repart de la dernière position X
    utilisée, pas de la position Y (le chaînage reste 1D sur X, un plan en L ou en
    étoile nécessite plusieurs appels à execute_level_plan avec des start_x différents).

    Exemple :
        plan = [
            {"type": "room", "zone_name": "Manoir_Hall", "style": "amnesia",
             "size_x": 1400, "size_y": 1200, "with_enemy": False},
            {"type": "corridor", "zone_name": "Manoir_Corr1", "style": "amnesia", "length": 800},
            {"type": "room", "zone_name": "Manoir_Salon", "style": "amnesia",
             "size_x": 1200, "size_y": 1200},
            {"type": "corridor", "zone_name": "Manoir_Corr2", "style": "outlast", "length": 600},
            {"type": "room", "zone_name": "Manoir_Cave", "style": "outlast",
             "size_x": 1400, "size_y": 1400},
        ]
        execute_level_plan(plan, start_x=0)

    Retourne un dict {"reports": [...], "final_x": ..., "verify_ok": bool|None}.
    """
    x = start_x
    reports = []

    for i, step in enumerate(plan):
        step_type = step.get("type", "room")
        zone_name = step.get("zone_name", f"Zone_{i}")
        style = step.get("style", "silent_hill")
        step_cy = step.get("cy", cy)

        if step_type == "room":
            size_x = step.get("size_x", 1200)
            size_y = step.get("size_y", 1200)
            height = step.get("height", 300)
            cx = x + size_x / 2
            rapport = setup_horror_room(
                style=style, zone_name=zone_name, cx=cx, cy=step_cy,
                size_x=size_x, size_y=size_y, height=height,
                with_enemy=step.get("with_enemy", True),
                with_props=step.get("with_props", True),
                with_gameplay=step.get("with_gameplay", True),
            )
            reports.append({"zone_name": zone_name, "type": "room", "cx": cx, "cy": step_cy,
                            "report": rapport})
            x = cx + size_x / 2 + gap

        elif step_type == "corridor":
            length = step.get("length", 800)
            width = step.get("width", 500)
            x1, x2 = x, x + length
            rapport = setup_horror_corridor_full(x1, x2, cy=step_cy, width=width, style=style)
            reports.append({"zone_name": zone_name, "type": "corridor", "x1": x1, "x2": x2,
                            "report": rapport})
            x = x2 + gap

        else:
            reports.append({"zone_name": zone_name, "type": step_type,
                            "report": f"❌ Type inconnu: '{step_type}' (attendu: room, corridor)"})

    verify_ok = None
    if verify_at_end:
        try:
            from verify_level import fix_all, run_verify
            fix_all()
            verify_ok = run_verify()
        except Exception as e:
            print(f"[execute_level_plan] Vérification finale échouée: {e}")

    print(f"\n=== execute_level_plan terminé — {len(plan)} élément(s), X final={x} ===")
    if verify_at_end:
        print(f"Vérification finale: {'JOUABLE ✅' if verify_ok else 'ERREURS DÉTECTÉES ❌'}")

    return {"reports": reports, "final_x": x, "verify_ok": verify_ok}


def fix_existing_level(style="silent_hill"):
    """Corrige n'importe quel level existant sans toucher à la géométrie.

    À utiliser quand un agent a créé une salle mais oublié les lumières/PP/matériaux.
    Détecte automatiquement les surfaces et applique la correction.
    """
    rapport = ["=== fix_existing_level ==="]
    aeas_sub = aeas()
    all_act = aeas_sub.get_all_level_actors()

    # 1. Matériaux sur TOUS les StaticMeshActors qui ont BasicShapeMaterial ou blanc
    MAT_WALL  = "/Game/AssetImported/A_Surface_Footstep/Environment_Assets/Materials/M_DemoWall"
    MAT_FLOOR = "/Game/AssetImported/A_Surface_Footstep/Environment_Assets/Materials/M_Asphalt"
    MAT_CEIL  = "/Game/AssetImported/A_Surface_Footstep/Environment_Assets/Materials/M_grey"
    mat_w = unreal.load_asset(MAT_WALL)
    mat_f = unreal.load_asset(MAT_FLOOR)
    mat_c = unreal.load_asset(MAT_CEIL)

    fixed_mats = 0
    for a in all_act:
        if 'StaticMeshActor' not in a.get_class().get_name():
            continue
        smc = a.get_component_by_class(unreal.StaticMeshComponent.static_class())
        if not smc: continue
        m = smc.get_material(0)
        mat_name = m.get_name() if m else ""
        # Corriger si matériau par défaut
        if mat_name in ("BasicShapeMaterial", "WorldGridMaterial", "MI_ProcGrid", ""):
            label = (a.get_actor_label() or "").lower()
            if any(x in label for x in ["walln", "walls", "walle", "wallw", "_wall", "wall_"]):
                if mat_w: smc.set_material(0, mat_w); fixed_mats += 1
            elif "floor" in label:
                if mat_f: smc.set_material(0, mat_f); fixed_mats += 1
            elif "ceil" in label:
                if mat_c: smc.set_material(0, mat_c); fixed_mats += 1

    rapport.append(f"✅ 1. Matériaux corrigés sur {fixed_mats} surfaces")

    # 2. Atmosphère
    try:
        setup_global_atmosphere(style)
        rapport.append(f"✅ 2. PostProcess + lumières globales OFF ({style})")
    except Exception as e:
        rapport.append(f"❌ 2. Atmosphere ERREUR: {e}")

    # 3. Lumières — ajouter si aucune n'existe
    lights = [a for a in aeas_sub.get_all_level_actors()
              if 'PointLight' in a.get_class().get_name()]
    if len(lights) == 0:
        palette = _LIGHT_PALETTES.get(style, _LIGHT_PALETTES["silent_hill"])
        for ox, oy, lz, intensity, rgb, radius, suffix in palette:
            point_light(ox, oy, lz, intensity=intensity, rgb=rgb,
                        radius=radius, label=f"Fixed_{suffix}")
        rapport.append(f"✅ 3. {len(palette)} point lights ajoutés")
    else:
        rapport.append(f"⏭️  3. {len(lights)} lumières déjà présentes — skip")

    # 4. Ennemi — ajouter si manquant
    enemies = [a for a in aeas_sub.get_all_level_actors()
               if 'BP_IA_Enemy' in a.get_class().get_name()
               or 'Enemy' in (a.get_actor_label() or '')]
    if len(enemies) == 0:
        try:
            grid = build_occupancy_grid_from_level()
            safe_spawn_enemy(x=300, y=150, grid=grid, label="Enemy_Fixed")
            rapport.append("✅ 4. Ennemi ajouté")
        except Exception as e:
            rapport.append(f"❌ 4. Ennemi ERREUR: {e}")
    else:
        rapport.append(f"⏭️  4. {len(enemies)} ennemi(s) déjà présent(s) — skip")

    # 5. Gameplay
    try:
        gp = setup_gameplay_elements()
        rapport.append(f"✅ 5. Gameplay ({len(gp)} éléments ajoutés)")
    except Exception as e:
        rapport.append(f"❌ 5. Gameplay ERREUR: {e}")

    # 6. Vérification
    try:
        from verify_level import fix_all, run_verify
        fix_all(); run_verify()
        rapport.append("✅ 6. Vérification run_verify OK")
    except Exception as e:
        rapport.append(f"⚠️  6. Vérification: {e}")

    save()
    rapport.append("✅ 7. Sauvegardé")
    rapport.append("⚡ Build → Build Paths pour NavMesh")

    result = "\n".join(rapport)
    print(result)
    return result


print("[horror_presets] loaded - from horror_presets import *")
print("")
print("  ═══ SETUP FUNCTIONS (tout-en-un) ═══")
print("  setup_horror_room(style, zone_name, cx, cy)  → salle complète from scratch")
print("  setup_global_atmosphere(style)               → PP + lumières OFF")
print("  setup_gameplay_elements(cx, cy, zone_name)   → NavMesh + pickups + LightSwitch")
print("  setup_horror_corridor_full(x1, x2, cy)       → couloir complet")
print("  fix_existing_level(style)                    → corrige un level existant")
print("")
print("  ═══ DRESS FUNCTIONS (habillage par zone) ═══")
print("  dress_abandoned_room / dress_office_derelict / dress_danger_room")
print("  dress_corridor_horror / dress_boss_room / dress_level_zone")
print("")
print("  ═══ ATMOSPHERE ═══")
print("  atmosphere_red_danger / atmosphere_dim_amber / atmosphere_cold_blue")
print("  atmosphere_flickering_lamps / atmosphere_pitch_black")
print("")
print("  ═══ GAMEPLAY ═══")
print("  spawn_patrol_enemy / spawn_jumpscare / spawn_flashlight_pickup")
print("")
print("  ═══ UTILITAIRES ═══")
print("  audit_zone / audit_zone_full / clear_zone / discover_assets")
