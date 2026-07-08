"""
qc_gate.py — Verdict QC consolidé (structurel + numérique) pour la boucle fermée de
vérification perceptuelle du level design horror.

CONTEXTE (ajouté 2026-07-08, voir CLAUDE.md) : `verify_level.verified_zone_build()` (côté
UE5) ferme la partie STRUCTURELLE de la boucle (matériaux, PostProcess, Lumen, exposition,
couverture lumière...) avec relance automatique plafonnée, mais tourne dans le Python
embarqué UE5 — sans PIL ni numpy, impossible d'y mesurer un vrai pixel. Tools/analyze_
screenshot.py tourne à côté (bash Claude Cowork, PIL+numpy disponibles) et complète avec
des métriques numériques (luminance, clipping, uniformité...). Jusqu'ici ces deux verdicts
vivaient dans deux appels séparés qu'un agent pressé pouvait oublier de croiser — c'est
exactement le trou documenté plusieurs fois dans ce projet ("run_verify() dit 0 erreur
mais la salle est visuellement une boîte grise/plate/noire"). Ce script fusionne les deux
en UNE SEULE commande, UN SEUL verdict JSON.

NE REMPLACE TOUJOURS PAS le jugement visuel direct (Read + œil humain/vision-agent) — voir
CLAUDE.md "routage agent UE5 vs Claude Cowork". C'est un filet de sécurité numérique
supplémentaire qui rend impossible d'oublier l'un des deux checks existants, pas un
troisième substitut au premier qui rendrait la lecture de l'image facultative.

Usage :
    python3 Tools/qc_gate.py --screenshots a.png b.png --errors-json report.json
    # report.json = {"errors": [...], "warnings": [...]}  — sortie telle quelle de
    # verify_level.verified_zone_build() ou de run_verify().

    # Sans rapport structurel (juste le check numérique sur des screenshots) :
    python3 Tools/qc_gate.py --screenshots a.png

Retourne un JSON sur stdout + code de sortie 0 (PASS) / 1 (FAIL).

Protocole d'itération recommandé (voir CLAUDE.md) :
    1. verified_zone_build(...) côté UE5 (mcp__ue5-mcp__ue5_execute)
    2. qc_gate.py sur le(s) screenshot(s) + errors-json retournés
    3. Read() sur chaque screenshot — jugement visuel direct, jamais sauté
    4. Si le verdict JSON est FAIL OU si le jugement visuel détecte un problème non
       capturé par les métriques : corriger, rappeler verified_zone_build() sur la même
       zone. Plafond recommandé : 3 tentatives complètes, puis remonter le problème à
       l'utilisateur plutôt que boucler indéfiniment ou déclarer un faux succès.
"""

import sys
import os
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_screenshot import analyze, DEFAULT_CLIP_KWARGS  # noqa: E402


def run_gate(screenshots, errors=None, warnings=None):
    """Fusionne le rapport structurel (errors/warnings) et l'analyse numérique de
    chaque screenshot en un seul verdict. Retourne un dict JSON-sérialisable.
    """
    errors = list(errors or [])
    warnings = list(warnings or [])

    per_screenshot = {}
    numeric_problems = []
    for path in screenshots:
        report = analyze(path, **DEFAULT_CLIP_KWARGS)
        per_screenshot[path] = report
        if report["verdict"] != "OK":
            numeric_problems.extend(
                "[{}] {}".format(os.path.basename(path), p) for p in report["problems"]
            )

    overall_pass = (len(errors) == 0) and (len(numeric_problems) == 0)

    return {
        "structural_errors": errors,
        "structural_warnings": warnings,
        "numeric_problems": numeric_problems,
        "per_screenshot": per_screenshot,
        "verdict": "PASS" if overall_pass else "FAIL",
        "still_needs_visual_read": True,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--screenshots", nargs="+", required=True,
                     help="Chemin(s) vers les PNG à analyser (capture_reference_screenshot)")
    ap.add_argument("--errors-json", default=None,
                     help="Chemin vers un JSON {'errors': [...], 'warnings': [...]} — "
                          "sortie de verified_zone_build() ou run_verify()")
    args = ap.parse_args()

    errors, warnings = [], []
    if args.errors_json:
        with open(args.errors_json, encoding="utf-8") as f:
            data = json.load(f)
        errors = data.get("errors", [])
        warnings = data.get("warnings", [])

    result = run_gate(args.screenshots, errors, warnings)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    print("\n--- RAPPEL ---", file=sys.stderr)
    print("Ce verdict ne remplace pas la lecture directe des screenshots avec Read.",
          file=sys.stderr)

    sys.exit(0 if result["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
