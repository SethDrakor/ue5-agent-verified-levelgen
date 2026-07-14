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

    # Consigner le verdict dans le manifest QC persistant (Saved/QC/qc_manifest.json)
    # pour une zone construite via verified_zone_build() :
    python3 Tools/qc_gate.py --screenshots a.png --errors-json report.json --zone Z1

    # Après avoir lu le screenshot avec Read et jugé le résultat :
    python3 Tools/qc_gate.py --confirm-visual-read Z1 --note "point focal clair, ambre OK"

    # Audit : quelles zones construites n'ont JAMAIS été complètement vérifiées
    # (qc_gate PASS + lecture visuelle confirmée) avant de déclarer un niveau terminé :
    python3 Tools/qc_gate.py --check-manifest

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
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_screenshot import analyze, DEFAULT_CLIP_KWARGS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ══════════════════════════════════════════════════════════════════════════════
# MANIFEST QC PERSISTANT — Saved/QC/qc_manifest.json (ajouté 2026-07-08)
#
# CONTEXTE : verified_zone_build() (verify_level.py, côté UE5) imprime "ETAPE
# OBLIGATOIRE SUIVANTE : Read + qc_gate.py" à chaque appel, mais rien ne vérifiait
# que cette étape avait réellement eu lieu — un agent pressé pouvait construire une
# zone, voir "structural_pass: True" et déclarer la zone terminée sans jamais lancer
# qc_gate.py ni lire le screenshot. Exactement le même trou de conception que celui
# fermé pour safe_write/safe_append côté intégrité fichier (convention non vérifiable
# plutôt qu'un mécanisme). Ce manifest rend l'oubli auditable : verify_level.py écrit
# une entrée "pending" à chaque construction de zone, ce script la complète avec le
# verdict numérique (--zone) et la confirmation de lecture visuelle
# (--confirm-visual-read), et --check-manifest permet de lister d'un coup toutes les
# zones jamais complètement vérifiées avant de considérer un niveau "terminé".
# ══════════════════════════════════════════════════════════════════════════════

def _manifest_path():
    d = os.path.join(ROOT, "Saved", "QC")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "qc_manifest.json")


def _load_manifest():
    path = _manifest_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_manifest(data):
    path = _manifest_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def _record_qc_gate_verdict(zone, result):
    """Appelé quand --zone est fourni : consigne le verdict qc_gate (structurel +
    numérique) dans l'entrée manifest de cette zone. Ne touche PAS aux champs de
    lecture visuelle — un nouveau verdict qc_gate ne vaut pas confirmation visuelle,
    ce sont deux attestations distinctes (voir --confirm-visual-read)."""
    data = _load_manifest()
    entry = data.setdefault(zone, {
        "zone_name": zone, "screenshot": None, "structural_errors": [],
        "structural_warnings": [], "built_at": None,
        "visual_read_confirmed": False, "visual_read_note": None,
    })
    entry["qc_gate_verdict"] = result["verdict"]
    entry["qc_gate_ran_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    entry["numeric_problems"] = result["numeric_problems"]
    _save_manifest(data)


def _cmd_check_manifest():
    """--check-manifest : audit de toutes les zones connues du manifest QC. Sort en
    erreur (code 1) si au moins une zone n'a pas à la fois un verdict qc_gate PASS
    ET une lecture visuelle confirmée — c'est la seule commande qui répond à
    'ai-je oublié de vérifier une zone avant de déclarer le niveau terminé ?'"""
    data = _load_manifest()
    if not data:
        print(json.dumps({"verdict": "EMPTY", "total_zones": 0, "pending_zones": []},
                          indent=2, ensure_ascii=False))
        sys.exit(0)

    pending = []
    for zone, entry in data.items():
        reasons = []
        verdict = entry.get("qc_gate_verdict")
        if verdict is None:
            reasons.append("qc_gate.py jamais lancé sur cette zone (--zone manquant)")
        elif verdict != "PASS":
            reasons.append(f"dernier verdict qc_gate: {verdict}")
        if not entry.get("visual_read_confirmed"):
            reasons.append("lecture visuelle jamais confirmée (--confirm-visual-read manquant)")
        if reasons:
            pending.append({"zone": zone, "reasons": reasons,
                             "screenshot": entry.get("screenshot")})

    report = {
        "total_zones": len(data),
        "pending_zones": pending,
        "verdict": "ALL_CLEAR" if not pending else "PENDING_VERIFICATION",
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    sys.exit(0 if not pending else 1)


def _cmd_confirm_visual_read(zone, note):
    """--confirm-visual-read ZONE : attestation explicite qu'un agent avec vision a
    réellement appelé Read sur le screenshot de cette zone et jugé le résultat.
    Ne PEUT PAS vérifier techniquement que la lecture a eu lieu (aucun mécanisme ne
    le peut) — mais rend l'omission un choix visible dans le manifest plutôt qu'un
    silence, exactement comme le reste de ce garde-fou."""
    data = _load_manifest()
    if zone not in data:
        print(f"ERREUR: zone '{zone}' introuvable dans le manifest QC ({_manifest_path()}). "
              f"Zones connues: {list(data.keys())}", file=sys.stderr)
        sys.exit(2)
    data[zone]["visual_read_confirmed"] = True
    data[zone]["visual_read_note"] = note
    data[zone]["visual_read_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    _save_manifest(data)
    print(f"[qc_gate] Zone '{zone}' marquée comme visuellement vérifiée.")
    sys.exit(0)


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
    ap.add_argument("--screenshots", nargs="+", default=None,
                     help="Chemin(s) vers les PNG à analyser (capture_reference_screenshot)")
    ap.add_argument("--errors-json", default=None,
                     help="Chemin vers un JSON {'errors': [...], 'warnings': [...]} — "
                          "sortie de verified_zone_build() ou run_verify()")
    ap.add_argument("--zone", default=None,
                     help="Nom de zone — si fourni, consigne ce verdict dans le manifest "
                          "QC persistant (Saved/QC/qc_manifest.json) pour cette zone")
    ap.add_argument("--check-manifest", action="store_true",
                     help="Ignore --screenshots : audit de toutes les zones du manifest QC, "
                          "sort en erreur si une zone n'a pas (qc_gate PASS + lecture visuelle confirmée)")
    ap.add_argument("--confirm-visual-read", metavar="ZONE", default=None,
                     help="Marque ZONE comme visuellement vérifiée (Read + jugement humain/"
                          "vision effectué) dans le manifest QC")
    ap.add_argument("--note", default="",
                     help="Note optionnelle jointe à --confirm-visual-read")
    args = ap.parse_args()

    if args.check_manifest:
        _cmd_check_manifest()
        return

    if args.confirm_visual_read:
        _cmd_confirm_visual_read(args.confirm_visual_read, args.note)
        return

    if not args.screenshots:
        ap.error("--screenshots est requis (sauf --check-manifest / --confirm-visual-read)")

    errors, warnings = [], []
    if args.errors_json:
        with open(args.errors_json, encoding="utf-8") as f:
            data = json.load(f)
        errors = data.get("errors", [])
        warnings = data.get("warnings", [])

    result = run_gate(args.screenshots, errors, warnings)

    if args.zone:
        _record_qc_gate_verdict(args.zone, result)
        # CI visuelle (visual_diff.py, ajouté 2026-07-14) : si cette zone a déjà une
        # baseline enregistrée, comparer automatiquement le screenshot actuel à cette
        # référence et joindre le verdict au rapport — sans ça, un agent pressé qui ne
        # connaît pas visual_diff.py pourrait ne jamais savoir qu'une baseline existe pour
        # cette zone. Silencieux (verdict NO_BASELINE) si aucune baseline n'existe encore,
        # ce qui est le cas normal pour une zone jamais promue.
        try:
            from visual_diff import compare_zone  # noqa: E402 (import tardif