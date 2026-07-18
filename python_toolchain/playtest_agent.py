"""
playtest_agent.py -- Agent playtesteur autonome (verification comportementale)
===============================================================================

Pilote le personnage joueur pendant une session PIE reelle (pas de simulation
theorique), journalise des evenements HORODATES en lisant l'etat de jeu en
direct (Blackboard ennemi, destruction d'acteurs jumpscare, position joueur),
et capture un screenshot (HighResShot) a chaque evenement detecte.

Complete le pipeline QC existant (voir CLAUDE.md, section "Agent playtesteur
autonome") : run_verify()/qc_gate.py/visual_diff.py jugent la geometrie et
l'image (structure + composition, un instant fige) ; ce module juge le TEMPS
-- est-ce que l'IA reagit, est-ce que le joueur reste bloque, est-ce qu'un
jumpscare se declenche -- en jouant reellement la scene plutot qu'en
inspectant un etat statique.

Architecture (validee empiriquement le 2026-07-14 avant d'ecrire ce fichier,
voir session correspondante) :
- Le PIE tourne en temps reel entre deux appels ue5_execute. On pilote donc
  le joueur via un callback enregistre avec unreal.register_slate_post_tick_callback,
  qui continue de s'executer tout seul (aucun appel Python externe requis
  pendant la duree du test) jusqu'a la fin du scenario ou du timeout.
- pawn.add_movement_input()/controller.set_control_rotation() pilotent le
  personnage -- fonctions Unreal standard, aucun code C++ necessaire (le
  personnage est un Blueprint pur : verifie via bgh.list_graph_nodes avant
  d'ecrire ce module -- 147 nodes dans EventGraph, K2Node_EnhancedInputAction,
  aucune classe C++ dediee).
- La lecture Blackboard passe par enemy.get_controller().get_component_by_class(
  unreal.BlackboardComponent.static_class()).get_value_as_bool(cle) -- memes
  cles que documentees dans CLAUDE.md -- ATTENTION cle exacte "CanSeePlayer?"
  (avec le point d'interrogation, confirme en lisant BBD_AI.keys directement
  le 2026-07-14 -- ue5_get_project_context() l'affiche SANS le "?", ce qui a
  fait rater ce bug une premiere fois : 0 detection sur tout un run reel).
- capture_reference_screenshot() (ue5_utils.py) NE MARCHE PAS en PIE : il
  spawn via EditorActorSubsystem, qui cible le monde EDITEUR (verifie : 0
  acteur retourne pendant un PIE actif). A la place : console command
  "HighResShot" executee sur un WorldContextObject du monde PIE (le pawn) --
  verifie avec succes (capture nette, non perimee, lue avec le Read tool,
  contrairement a take_screenshot()/AutomationLibrary deja bannis ailleurs
  dans ce projet pour un probleme voisin en contexte editeur).
- MISE A JOUR 2026-07-16 : la navigation entre waypoints n'est plus une ligne
  droite. Chaque jambe de trajet est desormais calculee via
  NavigationSystemV1.find_path_to_location_synchronously() (_find_nav_path)
  -- meme API deja validee dans ce projet pour le diagnostic du bug de
  poursuite ennemi. Piege rencontre en testant cette fonction sur
  HorrorLevel : is_valid peut etre True avec path_points VIDE (destination
  hors NavMesh) -- d'ou le garde-fou sur la longueur de la liste plutot que
  sur is_valid seul. Si aucun chemin exploitable n'est trouve, retombe sur
  l'ancienne ligne droite pour cette jambe plutot que de bloquer tout le
  test (voir path_fallback_count dans le rapport). Le chemin est aussi
  recalcule automatiquement des qu'un "player_stuck" est detecte, au cas ou
  le point de passage courant serait devenu inatteignable.

Usage typique (depuis ue5_execute) :
    from playtest_agent import start_playtest, get_playtest_status, get_playtest_report
    start_playtest(
        zone_name="Z3A_scenario",
        waypoints=[(4800, -350), (5850, 0), (6300, -400)],
        duration=45.0,
    )
    # ... attendre quelques secondes REELLES (appel ue5_execute suivant) ...
    get_playtest_status()   # {"active": True/False, "elapsed": ..., "events_count": ...}
    # une fois active=False :
    report = get_playtest_report()   # dict complet, aussi ecrit sur disque (report_path)

Limites assumees (v1, scenario isole -- voir CLAUDE.md "Agent playtesteur
autonome") :
- Un seul test actif a la fois (pas de file d'attente de sessions).
- Un seul screenshot "en vol" a la fois : si deux evenements arrivent le
  meme tick, le second est journalise sans capture (champ
  "screenshot_skipped": true) plutot que de risquer d'associer la mauvaise
  image au mauvais evenement.
- Le "rythme de tension" n'est PAS encore mesure avec un seuil numerique
  ici : le rapport liste les intervalles entre evenements (calculables a
  partir des timestamps "t"), le jugement de rythme reste manuel pour cette
  v1 (lecture du rapport + des screenshots) -- a formaliser plus tard avec
  des donnees reelles, comme discute avec Thomas avant d'ecrire ce module.
- Ce n'est PAS un gate obligatoire : outil lance a la demande, pas encore
  branche dans execute_level_plan()/verified_zone_build().
"""

import unreal
import os
import glob
import json
import math
import shutil
import time

from ue5_utils import load_bp_class, safe_write

ENEMY_BP_PATH = "/Game/HorrorGame/IA/Blueprint/Enemy/BP_IA_Enemy"
JUMPSCARE_BP_PATH = "/Game/HorrorGame/IA/Blueprint/BP_JumpScareLight"

_SESSION = {"active": False}


def _game_world():
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    return ues.get_game_world()


def _ensure_pie():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.is_in_play_in_editor():
        les.editor_request_begin_play()
    return les


def _shot_dir():
    return unreal.Paths.project_saved_dir() + "Screenshots/WindowsEditor/"


def _report_dir():
    d = unreal.Paths.project_saved_dir() + "QC/playtest_reports/"
    os.makedirs(d, exist_ok=True)
    return d


def _enemy_bb(enemy):
    ctrl = enemy.get_controller()
    if not ctrl:
        return None
    return ctrl.get_component_by_class(unreal.BlackboardComponent.static_class())


def _dist2d(loc_a, loc_b):
    return math.sqrt((loc_a.x - loc_b.x) ** 2 + (loc_a.y - loc_b.y) ** 2)


def _find_nav_path(world, start_loc, end_loc):
    """Calcule un vrai chemin NavMesh entre deux points, au lieu de la ligne
    droite utilisee jusqu'ici -- meme API deja validee dans ce projet pour
    diagnostiquer le bug de poursuite ennemi du 2026-07-14 (voir CLAUDE.md,
    section "Bug reel du jeu trouve grace a ce testeur") :
    NavigationSystemV1.find_path_to_location_synchronously(world, start, end).

    Verifie manuellement le 2026-07-16 sur HorrorLevel (PlayerStart -> Zone 2,
    700,0,100 -> 1800,450,100) : retourne un NavigationPath avec is_valid=True
    et 4 path_points recoupant un vrai virage (pas une ligne droite). Verifie
    aussi le cas d'echec (destination hors NavMesh, ex. Z=50000) :
    is_valid=True mais path_points VIDE -- piege reel rencontre en testant
    cette fonction, d'ou le garde-fou len(points) < 2 ci-dessous plutot que de
    se fier a is_valid seul.

    Retourne une liste de tuples (x, y) du depart (inclus) a l'arrivee, ou
    None si aucun chemin exploitable n'a ete trouve -- dans ce cas l'appelant
    retombe sur l'ancien comportement ligne droite (v1) plutot que de bloquer
    le playtest entier pour une seule jambe de trajet.
    """
    try:
        path = unreal.NavigationSystemV1.find_path_to_location_synchronously(world, start_loc, end_loc)
        if not path or not getattr(path, "is_valid", False):
            return None
        points = list(path.path_points) if path.path_points else []
        if len(points) < 2:
            return None
        return [(p.x, p.y) for p in points]
    except Exception:
        return None


def _record_event(kind, elapsed, **extra):
    evt = {"kind": kind, "t": round(elapsed, 2)}
    evt.update(extra)
    _SESSION["events"].append(evt)
    _SESSION["pending_event_for_shot"] = evt
    unreal.log("[playtest_agent] event t={:.2f}s kind={} {}".format(elapsed, kind, extra))


def _find_box_detection(enemy):
    """Retrouve le composant de collision "BoxDetection" d'un ennemi -- celui
    dont l'overlap (On Component Begin Overlap) declenche la capture du
    joueur dans BP_IA_Enemy.EventGraph (K2_SetActorLocation vers
    RespawnPlayerPoint, puis OpenLevel -- voir CLAUDE.md, section "Bug reel
    du jeu trouve grace a ce testeur", et l'inspection du graphe faite le
    2026-07-16 pour le mode invincible). Retourne None si absent -- un
    ennemi sans ce composant ne peut de toute facon pas capturer le joueur,
    rien a desactiver."""
    for c in enemy.get_components_by_class(unreal.BoxComponent.static_class()):
        if c.get_name() == "BoxDetection":
            return c
    return None


def _interact_subsystem():
    return unreal.get_editor_subsystem(unreal.RoomGeneratorSubsystem)


def start_playtest(zone_name, waypoints, duration=60.0, stuck_window=5.0,
                    stuck_distance=60.0, arrive_radius=100.0, tail_time=4.0,
                    teleport_jump_threshold=400.0, interact_points=None,
                    interact_radius=150.0, invincible=False):
    """Demarre une session de playtest autonome. Non-bloquant : enregistre un
    callback tick et retourne immediatement. Utiliser get_playtest_status()/
    get_playtest_report() dans un appel ue5_execute SUIVANT pour suivre puis
    recuperer le resultat, une fois que du temps REEL s'est ecoule (le test
    tourne pendant les "blancs" entre deux appels ue5_execute, pas pendant
    l'execution de start_playtest() elle-meme).

    teleport_jump_threshold : distance (UU) au-dela de laquelle un deplacement
    du joueur EN UN SEUL TICK est considere comme une teleportation (capture
    par un ennemi, "K2_SetActorLocation" trouve dans BP_IA_Enemy.EventGraph le
    2026-07-14 -- voir CLAUDE.md/discussion) plutot qu'un deplacement normal a
    pied. 400 UU est une marge large (~10x un deplacement plausible par tick a
    vitesse de sprint) pour eviter les faux positifs sur un hitch de framerate.
    Une fois detectee ("player_caught"), on arrete de piloter le joueur vers
    l'ancien waypoint (devenu sans objet) et on arrete la detection de blocage
    (rester immobile apres une capture n'est pas un bug de nav) -- mais on
    CONTINUE de journaliser Blackboard/jumpscares jusqu'a la fin normale du
    test (duration), pour observer ce qui se passe apres la capture (fondu
    ecran, comportement de l'ennemi, etc.) -- decision explicite de Thomas.

    interact_points : liste optionnelle de (x, y) -- des qu'un point n'est
    pas encore declenche et que le joueur passe a moins de interact_radius,
    une touche E reelle est simulee UNE FOIS (via SimulateKeyPress, ajoute au
    plugin RoomGenerator le 2026-07-16 -- voir sa docstring C++ pour le
    pourquoi : Python n'a aucune API pour ecrire un etat de touche, seulement
    le lire). Un evenement "interact_attempted" est journalise (avec
    screenshot, comme les autres evenements) -- v1 ne verifie PAS
    automatiquement l'effet (porte ouverte, pickup ramasse) : ce jugement
    reste visuel (lire le screenshot associe), le meme principe que le reste
    du pipeline QC de ce projet (qc_gate.py/visual_diff.py ne remplacent
    jamais une lecture humaine/vision).

    invincible : si True, desactive generate_overlap_events sur le composant
    "BoxDetection" de chaque ennemi suivi PENDANT la duree du test (restaure
    a la fin, meme en cas d'arret anticipe ou d'erreur) -- c'est ce composant
    dont l'overlap declenche la capture (K2_SetActorLocation vers
    RespawnPlayerPoint + OpenLevel dans BP_IA_Enemy.EventGraph). Permet
    d'isoler un test de navigation/ambiance d'un test de comportement ennemi,
    sans toucher au Blueprint lui-meme -- juste une propriete de composant
    desactivee sur l'instance vivante, restauree apres coup."""
    if _SESSION.get("active"):
        raise Exception(
            "Un playtest est deja actif (zone={}) -- appeler get_playtest_report() "
            "ou stop_playtest() avant d'en lancer un autre.".format(_SESSION.get("zone_name")))

    _ensure_pie()
    world = _game_world()
    if not world:
        raise Exception(
            "Impossible d'obtenir le monde PIE juste apres editor_request_begin_play() -- "
            "reessayer dans un appel ue5_execute suivant (demarrage async).")

    enemy_cls = load_bp_class(ENEMY_BP_PATH)
    jumpscare_cls = load_bp_class(JUMPSCARE_BP_PATH)

    enemies = list(unreal.GameplayStatics.get_all_actors_of_class(world, enemy_cls)) if enemy_cls else []
    jumpscares = list(unreal.GameplayStatics.get_all_actors_of_class(world, jumpscare_cls)) if jumpscare_cls else []

    # --- Mode invincible : desactiver l'overlap qui declenche la capture ---
    # Fait AVANT _SESSION.clear() plus bas n'a pas d'importance (etat local),
    # mais doit rester avant le premier tick pour ne jamais laisser une
    # fenetre ou la capture est encore active alors que invincible=True a
    # ete demande.
    invincible_boxes = []
    if invincible:
        for e in enemies:
            box = _find_box_detection(e)
            if not box:
                continue
            try:
                prev = bool(box.get_editor_property("generate_overlap_events"))
                box.set_editor_property("generate_overlap_events", False)
                invincible_boxes.append((box, prev))
            except Exception as ex:
                unreal.log("[playtest_agent] invincible: echec desactivation sur {} -- {}".format(
                    e.get_actor_label(), str(ex)))

    _SESSION.clear()
    _SESSION.update({
        "active": True,
        "zone_name": zone_name,
        "start_wall_time": time.time(),
        "waypoints": [tuple(w) for w in waypoints],
        "wp_idx": 0,
        "path_queue": None,
        "path_fallback_count": 0,
        "path_navmesh_count": 0,
        "last_wp_change_t": 0.0,
        "duration": duration,
        "stuck_window": stuck_window,
        "stuck_distance": stuck_distance,
        "arrive_radius": arrive_radius,
        "tail_time": tail_time,
        "moving_done": False,
        "moving_done_t": None,
        "pos_history": [],
        "stuck_active": False,
        "teleport_jump_threshold": teleport_jump_threshold,
        "last_tick_pos": None,
        "caught": False,
        "interact_points": [tuple(p) for p in (interact_points or [])],
        "interact_triggered": [False] * len(interact_points or []),
        "interact_radius": interact_radius,
        "invincible": bool(invincible),
        "invincible_boxes": invincible_boxes,
        "enemy_cls": enemy_cls,
        "jumpscare_cls": jumpscare_cls,
        "enemy_state": {e.get_actor_label(): {"seen": False, "illum": False} for e in enemies},
        "jumpscare_alive": {j.get_actor_label(): True for j in jumpscares},
        "events": [],
        "pending_event_for_shot": None,
        "pending_shot_known_files": None,
        "shots": [],
        "finished": False,
        "reason": None,
        "report_path": None,
        "last_sample_t": -999.0,
    })

    handle = unreal.register_slate_post_tick_callback(_tick)
    _SESSION["handle"] = handle
    unreal.log("[playtest_agent] Playtest demarre -- zone={} waypoints={} enemies={} jumpscares={} invincible={}".format(
        zone_name, len(waypoints), len(enemies), len(jumpscares), invincible))
    return {
        "status": "started",
        "zone_name": zone_name,
        "enemies_tracked": list(_SESSION["enemy_state"].keys()),
        "jumpscares_tracked": list(_SESSION["jumpscare_alive"].keys()),
        "invincible": bool(invincible),
        "invincible_boxes_disabled": len(invincible_boxes),
    }


def _tick(delta_time):
    if not _SESSION.get("active"):
        return
    try:
        _tick_inner(delta_time)
    except Exception as e:
        # Ne jamais laisser une exception dans un tick callback planter en boucle --
        # on arrete proprement la session et on note l'erreur dans le rapport.
        _SESSION["events"].append({
            "kind": "internal_error",
            "t": round(time.time() - _SESSION["start_wall_time"], 2),
            "error": str(e),
        })
        _finish_session("internal_error")


def _tick_inner(delta_time):
    world = _game_world()
    if not world:
        return
    elapsed = time.time() - _SESSION["start_wall_time"]

    pawn = unreal.GameplayStatics.get_player_pawn(world, 0)
    controller = unreal.GameplayStatics.get_player_controller(world, 0)

    # --- Detection "joueur capture" (teleportation en un seul tick) ---
    # Doit passer AVANT le pilotage/detection de blocage ci-dessous, pour que
    # le reste du tick reagisse deja au nouvel etat "caught" cette meme frame.
    if pawn:
        cur = pawn.get_actor_location()
        last = _SESSION["last_tick_pos"]
        if last is not None:
            jump = math.sqrt((cur.x - last[0]) ** 2 + (cur.y - last[1]) ** 2)
            if jump > _SESSION["teleport_jump_threshold"]:
                _record_event("player_caught", elapsed,
                              from_x=round(last[0], 1), from_y=round(last[1], 1),
                              to_x=round(cur.x, 1), to_y=round(cur.y, 1),
                              distance=round(jump, 1))
                _SESSION["caught"] = True
        _SESSION["last_tick_pos"] = (cur.x, cur.y)

    if pawn and controller and not _SESSION["moving_done"] and not _SESSION["caught"]:
        wps = _SESSION["waypoints"]
        idx = _SESSION["wp_idx"]
        loc = pawn.get_actor_location()
        tx, ty = wps[idx]

        # (Re)calcule un chemin NavMesh vers le waypoint courant si on n'en a
        # pas deja un en cours -- remplace la ligne droite d'origine (limite
        # connue, documentee dans CLAUDE.md : se coince contre un obstacle
        # hors trajectoire directe, ex. un pilier de couloir). Le premier
        # point du chemin (~position actuelle) est ignore : on vise le point
        # suivant directement.
        if not _SESSION["path_queue"]:
            pts = _find_nav_path(world, loc, unreal.Vector(tx, ty, loc.z))
            if pts and len(pts) >= 2:
                _SESSION["path_queue"] = pts[1:]
                _SESSION["path_navmesh_count"] += 1
            else:
                _SESSION["path_queue"] = [(tx, ty)]
                _SESSION["path_fallback_count"] += 1

        px, py = _SESSION["path_queue"][0]
        dx, dy = px - loc.x, py - loc.y
        dist = math.sqrt(dx * dx + dy * dy)
        is_final_point = len(_SESSION["path_queue"]) == 1
        # Rayon large sur le waypoint final (comportement d'origine),
        # rayon plus serre sur un point de passage intermediaire du chemin
        # NavMesh -- sinon l'agent "coupe" les virages et peut recoller au
        # meme obstacle que la ligne droite etait censee eviter.
        radius = _SESSION["arrive_radius"] if is_final_point else 120.0

        if dist < radius:
            _SESSION["path_queue"].pop(0)
            if is_final_point:
                _record_event("waypoint_reached", elapsed, index=idx, x=tx, y=ty)
                idx += 1
                _SESSION["wp_idx"] = idx
                _SESSION["last_wp_change_t"] = elapsed
                _SESSION["path_queue"] = None
                if idx >= len(wps):
                    _SESSION["moving_done"] = True
                    _SESSION["moving_done_t"] = elapsed
        else:
            nx, ny = dx / dist, dy / dist
            pawn.add_movement_input(unreal.Vector(nx, ny, 0.0), 1.0, False)
            yaw = math.degrees(math.atan2(ny, nx))
            controller.set_control_rotation(unreal.Rotator(0.0, yaw, 0.0))

    # --- Interaction (E) sur les points declares ---
    # Independant de moving_done (le joueur peut passer pres d'un point
    # d'interaction sans que ce soit un waypoint de destination) mais pas
    # apres une capture (mêmes raisons que le pilotage : plus rien a tester
    # une fois le joueur teleporte). Chaque point ne se declenche qu'UNE
    # fois par session (interact_triggered).
    if pawn and controller and not _SESSION["caught"]:
        loc = pawn.get_actor_location()
        for i, (ix, iy) in enumerate(_SESSION["interact_points"]):
            if _SESSION["interact_triggered"][i]:
                continue
            d = math.sqrt((ix - loc.x) ** 2 + (iy - loc.y) ** 2)
            if d >= _SESSION["interact_radius"]:
                continue
            _SESSION["interact_triggered"][i] = True
            ok = False
            err = None
            try:
                sub = _interact_subsystem()
                ok = bool(sub.simulate_key_press(controller, "E")) if sub else False
            except Exception as ex:
                err = str(ex)
            if ok:
                _record_event("interact_attempted", elapsed, index=i, x=ix, y=iy)
            else:
                _record_event("interact_failed", elapsed, index=i, x=ix, y=iy, error=err)

    # --- Detection "joueur coince" ---
    # Desactivee apres une capture : rester immobile suite a un
    # K2_SetActorLocation/fondu ecran n'est pas un bug de navigation.
    if pawn and not _SESSION["moving_done"] and not _SESSION["caught"]:
        loc = pawn.get_actor_location()
        if elapsed - _SESSION["last_sample_t"] >= 0.5:
            _SESSION["pos_history"].append((elapsed, loc.x, loc.y))
            _SESSION["last_sample_t"] = elapsed
            window = _SESSION["stuck_window"]
            recent = [p for p in _SESSION["pos_history"] if elapsed - p[0] <= window]
            if elapsed - _SESSION["last_wp_change_t"] > window and len(recent) >= 2:
                xs = [p[1] for p in recent]
                ys = [p[2] for p in recent]
                spread = math.sqrt((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2)
                stuck_now = spread < _SESSION["stuck_distance"]
                if stuck_now and not _SESSION["stuck_active"]:
                    _record_event("player_stuck", elapsed, x=loc.x, y=loc.y, waypoint_index=_SESSION["wp_idx"])
                    _SESSION["stuck_active"] = True
                    # Force un recalcul du chemin NavMesh au prochain tick --
                    # le point de passage courant est peut-etre devenu
                    # inatteignable (obstacle deplace, coin mal negocie).
                    # Sans ca, un chemin bloque restait bloque pour le reste
                    # du test.
                    _SESSION["path_queue"] = None
                elif not stuck_now:
                    _SESSION["stuck_active"] = False

    # --- Blackboard ennemis ---
    # NOTE (decouvert en testant ce module le 2026-07-14) : unreal.SystemLibrary.is_valid()
    # sur une reference d'acteur mise en cache entre plusieurs ticks leve un TypeError
    # ("Cannot nativize 'Character'/'Actor' as 'Object'") de facon intermittente dans ce
    # binding UE5.7 -- meme famille de bug que les coercions de type deja documentees
    # ailleurs dans ce projet (class pin, sphere_overlap_actors). Constate sur un ENNEMI
    # (jamais detruit pendant un test) ET sur un JUMPSCARE (detruit par design) -- donc
    # pas specifique a un type d'acteur, plutot au fait de garder un handle Python d'un
    # tick a l'autre. Fix : ne plus jamais garder de reference d'acteur en cache -- on
    # re-scanne les acteurs VIVANTS via GameplayStatics.get_all_actors_of_class() a
    # CHAQUE tick et on raisonne uniquement par label. Cout negligeable (une dizaine
    # d'acteurs), et ca evite is_valid() entierement.
    if pawn:
        ploc = pawn.get_actor_location()
        try:
            live_enemies = unreal.GameplayStatics.get_all_actors_of_class(world, _SESSION["enemy_cls"])
        except Exception:
            live_enemies = []
        for enemy in live_enemies:
            label = None
            try:
                label = enemy.get_actor_label()
                if label not in _SESSION["enemy_state"]:
                    continue
                bb = _enemy_bb(enemy)
                if not bb:
                    continue
                seen = bool(bb.get_value_as_bool("CanSeePlayer?"))
                illum = bool(bb.get_value_as_bool("IsIlluminated"))
                melee = bool(bb.get_value_as_bool("IsPlayerInMeleeRange"))
                stunned = bool(bb.get_value_as_bool("IsStunned"))
                prev = _SESSION["enemy_state"][label]
                dist = _dist2d(enemy.get_actor_location(), ploc)
                if seen != prev["seen"]:
                    _record_event("enemy_detected" if seen else "enemy_lost", elapsed, enemy=label, distance=round(dist, 1))
                if illum != prev["illum"]:
                    _record_event("enemy_illuminated" if illum else "enemy_dark", elapsed, enemy=label)
                if melee != prev.get("melee", False):
                    _record_event("enemy_melee_range" if melee else "enemy_melee_range_exit", elapsed, enemy=label, distance=round(dist, 1))
                if stunned != prev.get("stunned", False):
                    _record_event("enemy_stunned" if stunned else "enemy_unstunned", elapsed, enemy=label)
                prev["seen"], prev["illum"] = seen, illum
                prev["melee"], prev["stunned"] = melee, stunned
            except Exception as e:
                once_key = "_enemy_err_logged_" + str(label)
                if not _SESSION.get(once_key):
                    _SESSION[once_key] = True
                    _SESSION["events"].append({"kind": "enemy_check_error", "t": round(elapsed, 2), "enemy": label, "error": str(e)})

    # --- Jumpscares (detection par disparition de l'acteur d'un scan frais) ---
    try:
        live_jumpscares = set(j.get_actor_label() for j in
                               unreal.GameplayStatics.get_all_actors_of_class(world, _SESSION["jumpscare_cls"]))
    except Exception:
        live_jumpscares = None
    if live_jumpscares is not None:
        for label, was_alive in list(_SESSION["jumpscare_alive"].items()):
            if not was_alive:
                continue
            if label not in live_jumpscares:
                _record_event("jumpscare_triggered", elapsed, jumpscare=label)
                _SESSION["jumpscare_alive"][label] = False

    # --- File d'attente screenshot (1 seul "en vol" a la fois) ---
    _process_screenshot_queue(pawn, elapsed)

    # --- Conditions de fin ---
    reason = None
    if elapsed >= _SESSION["duration"]:
        reason = "duration_reached"
    elif _SESSION["moving_done"] and elapsed - _SESSION["moving_done_t"] >= _SESSION["tail_time"]:
        reason = "waypoints_complete"
    if reason:
        _finish_session(reason)


def _process_screenshot_queue(pawn, elapsed):
    pending = _SESSION.get("pending_event_for_shot")
    known = _SESSION.get("pending_shot_known_files")

    if known is not None:
        # Une capture est deja en cours -- on regarde si le fichier est arrive.
        current = set(glob.glob(_shot_dir() + "*.png"))
        new_files = current - known
        if new_files:
            newest = max(new_files, key=os.path.getmtime)
            dest_name = "{}__evt{:03d}_{}.png".format(
                _SESSION["zone_name"], len(_SESSION["shots"]), pending["kind"])
            dest_path = _report_dir() + dest_name
            try:
                shutil.copyfile(newest, dest_path)
                pending["screenshot"] = dest_path
                _SESSION["shots"].append({"event": pending["kind"], "t": pending["t"], "path": dest_path})
            except Exception as e:
                pending["screenshot_error"] = str(e)
            _SESSION["pending_event_for_shot"] = None
            _SESSION["pending_shot_known_files"] = None
        return

    if pending is not None and pawn is not None:
        _SESSION["pending_shot_known_files"] = set(glob.glob(_shot_dir() + "*.png"))
        unreal.SystemLibrary.execute_console_command(pawn, "HighResShot 640x360")
    elif pending is not None and pawn is None:
        pending["screenshot_skipped"] = True
        _SESSION["pending_event_for_shot"] = None


def _finish_session(reason):
    handle = _SESSION.get("handle")
    if handle is not None:
        try:
            unreal.unregister_slate_post_tick_callback(handle)
        except Exception:
            pass
    try:
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        if les.is_in_play_in_editor():
            les.editor_request_end_play()
    except Exception:
        pass

    # --- Mode invincible : restaurer generate_overlap_events, TOUJOURS ---
    # (fin normale, stop_playtest manuel, ou exception dans _tick -- ce bloc
    # tourne dans les 3 cas puisque _finish_session est l'unique point de
    # sortie). Un ennemi qui reste "invincible" apres la fin du test serait
    # un bug bien pire que celui que ce mode est cense isoler.
    for box, prev in _SESSION.get("invincible_boxes", []):
        try:
            box.set_editor_property("generate_overlap_events", prev)
        except Exception as ex:
            unreal.log("[playtest_agent] invincible: echec restauration -- {}".format(str(ex)))

    elapsed = time.time() - _SESSION["start_wall_time"]
    events = _SESSION["events"]
    report = {
        "zone_name": _SESSION["zone_name"],
        "reason": reason,
        "duration_actual": round(elapsed, 2),
        "waypoints": _SESSION["waypoints"],
        "invincible": _SESSION.get("invincible", False),
        "events": events,
        "screenshots": _SESSION["shots"],
        "enemies_tracked": list(_SESSION["enemy_state"].keys()),
        "jumpscares_tracked": list(_SESSION["jumpscare_alive"].keys()),
        "summary": {
            "events_count": len(events),
            "enemy_detections": len([e for e in events if e["kind"] == "enemy_detected"]),
            "jumpscares_triggered": len([e for e in events if e["kind"] == "jumpscare_triggered"]),
            "player_stuck_episodes": len([e for e in events if e["kind"] == "player_stuck"]),
            "player_caught_episodes": len([e for e in events if e["kind"] == "player_caught"]),
            "waypoints_reached": len([e for e in events if e["kind"] == "waypoint_reached"]),
            "navmesh_paths_used": _SESSION.get("path_navmesh_count", 0),
            "straight_line_fallbacks": _SESSION.get("path_fallback_count", 0),
            "interactions_attempted": len([e for e in events if e["kind"] == "interact_attempted"]),
            "interactions_failed": len([e for e in events if e["kind"] == "interact_failed"]),
        },
    }
    ts = int(time.time())
    report_path = _report_dir() + "{}_{}.json".format(_SESSION["zone_name"], ts)
    content = json.dumps(report, indent=2, ensure_ascii=False)
    safe_write(report_path, content, must_contain=["zone_name", "events"])

    _SESSION["finished"] = True
    _SESSION["report_path"] = report_path
    _SESSION["active"] = False
    unreal.log("[playtest_agent] Playtest termine -- raison={} rapport={}".format(reason, report_path))


def get_playtest_status():
    if not _SESSION:
        return {"active": False, "never_started": True}
    if _SESSION.get("active"):
        elapsed = time.time() - _SESSION["start_wall_time"]
        return {
            "active": True,
            "zone_name": _SESSION["zone_name"],
            "elapsed": round(elapsed, 2),
            "duration": _SESSION["duration"],
            "wp_idx": _SESSION["wp_idx"],
            "events_count": len(_SESSION["events"]),
        }
    return {
        "active": False,
        "finished": _SESSION.get("finished", False),
        "zone_name": _SESSION.get("zone_name"),
        "report_path": _SESSION.get("report_path"),
    }


def get_playtest_report():
    if _SESSION.get("active"):
        return {"status": "running", "info": get_playtest_status()}
    path = _SESSION.get("report_path")
    if not path or not os.path.exists(path):
        return {"status": "no_report"}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def stop_playtest(reason="manual_stop"):
    if _SESSION.get("active"):
        _finish_session(reason)
        return {"status": "stopped", "report_path": _SESSION.get("report_path")}
    return {"status": "not_active"}
