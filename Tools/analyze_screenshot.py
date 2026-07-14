"""
analyze_screenshot.py — Check perceptuel réel d'un screenshot de level horror.

CONTEXTE (voir GAME_MEMORY.md session 2026-07-03) : verify_level.py tourne DANS l'éditeur
UE5 (Python embarqué), qui n'a NI PIL NI numpy (vérifié empiriquement le 2026-07-03 —
`import PIL` / `import numpy` échouent tous les deux dans ue5_execute). Impossible donc
d'analyser un fichier PNG pixel par pixel depuis verify_level.py directement.

Ce script tourne à côté, dans l'environnement Claude Cowork (bash sandbox, PIL+numpy
disponibles), sur le fichier PNG déjà exporté par capture_reference_screenshot(). Il complète
(sans le remplacer) le jugement visuel humain/vision-agent : c'est un filet de sécurité
NUMÉRIQUE et REPRODUCTIBLE contre le problème documenté plusieurs fois dans ce projet :
"run_verify() dit 0 erreur mais la salle est visuellement une boîte grise / noire".

Usage (depuis le bash de Claude Cowork, PAS depuis ue5_execute) :
    python3 analyze_screenshot.py /chemin/vers/capture.png

Retourne un rapport texte + code de sortie 0 (OK) / 1 (probable problème d'ambiance).

Ce script ne remplace JAMAIS la lecture directe de l'image avec le Read tool — il donne
juste des chiffres objectifs (luminance, contraste, point focal) qui permettent de détecter
à coup sûr le cas "scène quasi entièrement noire" même quand l'œil humain/vision hésite sur
une image compressée ou mal calibrée à l'écran.
"""

import sys
import json


def analyze(path, dark_threshold=5, bright_threshold=40,
            min_mean_luminance=3.0, max_uniform_pct=97.0,
            min_pct_dark=20.0, max_pct_visible=75.0,
            clip_threshold=250, max_pct_clipped=None, max_p99=None):
    """Analyse un PNG et retourne un dict de métriques + verdict.

    dark_threshold       : luminance (0-255) en dessous de laquelle un pixel est "noir"
    bright_threshold     : luminance au-dessus de laquelle un pixel est "visible/lisible"
    min_mean_luminance   : luminance moyenne minimale pour ne pas déclencher "SALLE NOIRE"
    max_uniform_pct      : % de pixels quasi-identiques (±2) au-delà duquel "PLATE/SANS RELIEF"
    min_pct_dark         : % minimum de pixels sombres — sous ce seuil, pas assez d'ombre
                            (ajouté 2026-07-03 : bug bloom découvert sur AgentDemo, retour Thomas —
                            ce script ne détectait QUE "trop noir", jamais "trop clair/plat/pas
                            assez d'ombre". Cible HORROR_DESIGN.md section 9 : ~40% d'ombre)
    max_pct_visible       : % maximum de pixels "visibles" — au-dessus, la salle est trop
                            uniformément éclairée pour lire comme horror (cible section 9 : ~60%)
    clip_threshold        : luminance (0-255) au-dessus de laquelle un pixel est considéré "cramé"
    max_pct_clipped        : % maximum de pixels cramés (luminance >= clip_threshold) toléré.
                            AJOUTÉ 2026-07-03 (2e retour Thomas sur AgentDemo) : après le fix
                            "pas assez d'ombre" ci-dessus, la salle avait de meilleurs % sombre/
                            visible mais restait "trop claire et saturée" dans les flaques de
                            lumière elles-mêmes — un problème d'EXPOSITION DANS LA ZONE ÉCLAIRÉE,
                            orthogonal à la COUVERTURE (combien de la salle est éclairée) que les
                            checks pct_dark/pct_visible mesurent. Aucun check existant ne voyait
                            les hautes lumières brûlées (proches de blanc pur). None = pas de check
                            (valeur fournie à l'appel une fois calibrée sur des références réelles,
                            voir GAME_MEMORY.md section "seuils sourcés").
    max_p99                : valeur maximale tolérée pour le 99e percentile de luminance — signal
                            robuste au bruit (contrairement à max/argmax) de "les pixels les plus
                            clairs de la scène sont-ils déjà proches du blanc". None = pas de check.
    """
    from PIL import Image
    import numpy as np

    img = np.array(Image.open(path).convert("RGB")).astype(float)
    lum = 0.2126 * img[:, :, 0] + 0.7152 * img[:, :, 1] + 0.0722 * img[:, :, 2]

    mean_lum = float(lum.mean())
    std_lum = float(lum.std())
    p50 = float(np.percentile(lum, 50))
    p99 = float(np.percentile(lum, 99))
    pct_dark = float((lum <= dark_threshold).mean() * 100)
    pct_visible = float((lum >= bright_threshold).mean() * 100)
    pct_clipped = float((lum >= clip_threshold).mean() * 100)
    # Clipping par canal individuel (R, G ou B saturé) — capte aussi les hautes lumières
    # colorées (ex: orange qui brûle en cramant juste R+G) que la seule luminance peut manquer
    pct_channel_clipped = float((img.max(axis=2) >= 253).mean() * 100)

    # Point le plus lumineux — proxy de "point focal" (HORROR_DESIGN.md section 9 :
    # une salle doit avoir UNE source dominante identifiable, pas un éclairage plat)
    h, w = lum.shape
    flat_idx = int(np.argmax(lum))
    peak_y, peak_x = divmod(flat_idx, w)
    peak_dx_pct = abs(peak_x - w / 2) / (w / 2) * 100  # 0 = centre, 100 = bord
    peak_dy_pct = abs(peak_y - h / 2) / (h / 2) * 100

    # Uniformité : combien de pixels sont à ±2 de la médiane (scène plate/sans relief)
    pct_uniform = float((np.abs(lum - p50) <= 2).mean() * 100)

    problems = []
    if mean_lum < min_mean_luminance:
        problems.append(
            f"SALLE QUASI NOIRE: luminance moyenne {mean_lum:.2f}/255 "
            f"(seuil mini {min_mean_luminance}) — un joueur ne verra rien"
        )
    if pct_visible < 5.0:
        problems.append(
            f"QUASI RIEN DE LISIBLE: seulement {pct_visible:.1f}% des pixels au-dessus "
            f"du seuil de visibilité ({bright_threshold}/255)"
        )
    if pct_uniform > max_uniform_pct:
        problems.append(
            f"IMAGE PLATE: {pct_uniform:.1f}% des pixels quasi-identiques — pas de relief, "
            f"probablement pas de géométrie/lumière visible (boîte grise ou noire uniforme)"
        )
    if std_lum < 2.0 and mean_lum < 10:
        problems.append(
            f"AUCUN CONTRASTE: écart-type luminance {std_lum:.2f} — image quasi monochrome, "
            f"aucun point focal détectable"
        )
    if pct_dark < min_pct_dark:
        problems.append(
            f"PAS ASSEZ D'OMBRE: seulement {pct_dark:.1f}% de pixels sombres (cible ~40%, "
            f"mini {min_pct_dark}%) — la salle risque d'être trop uniformément éclairée "
            f"(voir bug bloom 2026-07-03 : 'JOUABLE' peut cacher une salle plate et pas effrayante)"
        )
    if pct_visible > max_pct_visible:
        problems.append(
            f"TROP UNIFORMÉMENT ÉCLAIRÉ: {pct_visible:.1f}% de pixels visibles (cible ~60%, "
            f"max {max_pct_visible}%) — pas assez de zones d'ombre pour un point focal lisible"
        )
    if max_pct_clipped is not None and pct_clipped > max_pct_clipped:
        problems.append(
            f"HAUTES LUMIÈRES CRAMÉES: {pct_clipped:.1f}% des pixels au-dessus de "
            f"{clip_threshold}/255 (max toléré {max_pct_clipped}%) — les flaques de lumière "
            f"brûlent en blanc/pastel au lieu de rester des sources ponctuelles contrastées "
            f"(2e bug AgentDemo 2026-07-03 : coverage corrigée mais exposition dans la flaque "
            f"jamais vérifiée)"
        )
    if max_p99 is not None and p99 > max_p99:
        problems.append(
            f"99e PERCENTILE TROP CLAIR: p99={p99:.1f}/255 (max {max_p99}) — même les pixels "
            f"les plus clairs devraient rester en dessous du blanc pur dans une scène horror"
        )

    verdict_ok = len(problems) == 0

    report = {
        "path": path,
        "mean_luminance": round(mean_lum, 3),
        "std_luminance": round(std_lum, 3),
        "p99_luminance": round(p99, 2),
        "pct_pixels_dark": round(pct_dark, 2),
        "pct_pixels_visible": round(pct_visible, 2),
        "pct_pixels_uniform": round(pct_uniform, 2),
        "pct_pixels_clipped": round(pct_clipped, 2),
        "pct_pixels_channel_clipped": round(pct_channel_clipped, 2),
        "brightest_point_offset_from_center_pct": {
            "x": round(peak_dx_pct, 1), "y": round(peak_dy_pct, 1)
        },
        "problems": problems,
        "verdict": "OK" if verdict_ok else "PROBLEME_AMBIANCE_DETECTE",
    }
    return report


# ══════════════════════════════════════════════════════════════════════════════
# SEUILS DE CLIPPING — sourcés le 2026-07-03 (3e retour Thomas, "arrête d'inventer
# tes propres seuils")
#
# Impossible d'obtenir des captures brutes de Silent Hill 2 / Outlast / Amnesia pour une
# mesure pixel-par-pixel : les galeries (MobyGames, wikis Fandom) sont en JS côté client,
# WebFetch n'y voit que des pages vides — pas de contournement tenté (règle du projet).
#
# À la place, sourcé sur deux références déjà utilisées par ce projet / le game design
# en général :
#   1. book.leveldesignbook.com/process/lighting/darkness (déjà la source de
#      LEVEL_DESIGN_THEORY.md) — convention "Hollywood Darkness" : une scène nocturne
#      lisible est "en fait assez claire ; ce qui la fait paraître sombre, c'est le
#      CONTRASTE" ; et "ne mets pas d'ambiant plat partout — certaines ombres doivent
#      aller jusqu'au 0% noir, sinon la lumière ne sert plus de repère".
#   2. dreadeddesigns.com/mastering-lighting-horror-art — section "Point Light" (notre
#      cas exact : point lights UE5) : "peut rendre les zones alentour anormalement
#      sombres OU DÉLAVÉES si mal équilibré" ; section "Flat Lighting" : "les hautes
#      lumières ne doivent jamais paraître fades/lessivées".
#
# Traduction en seuils numériques (interprétation de ces principes, PAS une mesure
# directe d'un jeu — c'est une hypothèse de calibration à corriger si l'écart avec le
# jugement visuel humain persiste) :
#   max_pct_clipped=3.0  : un point lumineux peut avoir un cœur proche du blanc, mais
#                          seulement sur une toute petite fraction de l'image (pas des
#                          flaques entières délavées)
#   max_p99=235.0        : même le 1% de pixels les plus clairs doit garder un peu de
#                          rolloff — jamais complètement cramé à 255
DEFAULT_CLIP_KWARGS = dict(max_pct_clipped=3.0, max_p99=235.0)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 analyze_screenshot.py <chemin.png> [chemin2.png ...]")
        sys.exit(2)

    any_problem = False
    for path in sys.argv[1:]:
        report = analyze(path, **DEFAULT_CLIP_KWARGS)
        print(f"\n{'='*60}")
        print(f"ANALYSE: {path}")
        print(f"{'='*60}")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        if report["verdict"] != "OK":
            any_problem = True

    sys.exit(1 if any_problem else 0)


if __name__ == "__main__":
    main()
