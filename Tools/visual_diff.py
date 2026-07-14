"""
visual_diff.py — CI visuelle : détecte qu'une zone déjà validée a visuellement dérivé,
par comparaison de screenshots entre deux versions, plutôt qu'un score numérique instantané.

CONTEXTE (ajouté 2026-07-14, voir CLAUDE.md section "BOUCLE QC FERMÉE") : qc_gate.py +
analyze_screenshot.py répondent à "ce screenshot est-il OK dans l'absolu ?" (luminance,
clipping, uniformité...) mais aucun mécanisme ne répondait à "cette zone, déjà validée la
semaine dernière, a-t-elle changé sans que personne ne le remarque ?" — un changement de
matériau, une lumière déplacée par erreur, un prop supprimé par un refactor de script
peuvent tous laisser un screenshot individuellement "OK" (luminance/couverture correctes)
tout en étant très différent de ce qui avait été approuvé. C'est le même point aveugle que
la CI classique (tests unitaires qui passent, régression visuelle silencieuse) transposé au
level design horror.

Principe : une fois qu'une zone a passé qc_gate PASS + lecture visuelle confirmée
(--confirm-visual-read dans qc_gate.py), son screenshot peut être promu "baseline" avec
--set-baseline. Tout appel ultérieur à --compare recapture la même zone et calcule un score
de similarité structurelle (SSIM approximé par blocs, pur numpy — pas de dépendance
scikit-image, cohérent avec la philosophie PIL+numpy seul déjà en place dans
analyze_screenshot.py) + un diff de luminance moyen + % de pixels changés. Un score bas =
dérive visuelle probable = à ré-examiner avec Read, pas une preuve absolue de régression
(un changement de style DÉLIBÉRÉ produira aussi un score bas — c'est un signal qui appelle
un jugement humain/vision, pas un verdict automatique final, exactement la même philosophie
que qc_gate.py).

Stocke les baselines dans Saved/QC/baselines/<zone>.png et les métadonnées directement dans
LE MÊME manifest que qc_gate.py (Saved/QC/qc_manifest.json, clés "baseline_screenshot",
"baseline_set_at", "baseline_note", "last_visual_diff") — pas de fichier séparé, pour que
--check-manifest / l'audit existant restent la seule source de vérité par zone.

Usage :
    # Promouvoir le screenshot ACTUEL d'une zone (déjà qc_gate PASS + lecture visuelle
    # confirmée dans le manifest) en référence pour les comparaisons futures :
    python3 Tools/visual_diff.py --set-baseline Z1

    # Comparer le screenshot actuel de la zone à sa baseline :
    python3 Tools/visual_diff.py --compare Z1

    # Comparer TOUTES les zones qui ont une baseline en un seul appel (CI visuelle complète
    # du niveau — à lancer après tout changement large : refactor de script, modif du
    # plugin RoomGenerator, etc.) :
    python3 Tools/visual_diff.py --compare-all

    # Lister les zones avec/sans baseline :
    python3 Tools/visual_diff.py --list-baselines

Retourne un JSON sur stdout + code de sortie 0 (pas de dérive détectée) / 1 (dérive
détectée sur au moins une zone) / 2 (erreur d'usage — zone/baseline introuvable).

NE REMPLACE PAS la lecture visuelle directe (Read) en cas de score bas — un score bas dit
seulement "quelque chose a changé", jamais "en bien" ou "en mal". Voir CLAUDE.md pour le
protocole complet.
"""

import sys
import os
import json
import shutil
import argparse
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qc_gate import _manifest_path, _load_manifest, _save_manifest  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Seuils par défaut — HYPOTHÈSE DE CALIBRATION, pas une mesure sourcée (même caveat que
# DEFAULT_CLIP_KWARGS dans analyze_screenshot.py : à corriger si l'écart avec le jugement
# visuel humain persiste sur des cas réels du projet). Point de départ : un score SSIM
# "parfait" vaut 1.0 ; en dessous de 0.85 sur une image de level design (pas une photo
# naturelle), une différence est presque toujours visible à l'œil dans ce contexte.
DEFAULT_SSIM_THRESHOLD = 0.85
DEFAULT_MAX_PCT_CHANGED = 12.0
DEFAULT_MAX_MEAN_DIFF = 10.0
DEFAULT_CHANGE_PIXEL_THRESHOLD = 20  # écart de luminance (0-255) au-delà duquel un pixel compte comme "changé"
SSIM_BLOCK = 16  # taille de bloc pour le SSIM approximé


def _baselines_dir():
    d = os.path.join(ROOT, "Saved", "QC", "baselines")
    os.makedirs(d, exist_ok=True)
    return d


def _safe_zone_filename(zone):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in zone) + ".png"


def _luminance(path):
    from PIL import Image
    import numpy as np
    img = np.array(Image.open(path).convert("RGB")).astype(float)
    return 0.2126 * img[:, :, 0] + 0.7152 * img[:, :, 1] + 0.0722 * img[:, :, 2], img.shape[:2]


def _block_ssim(lum_a, lum_b, block=SSIM_BLOCK):
    """SSIM approximé par blocs non chevauchants, pur numpy (pas de scikit-image
    disponible dans ce sandbox — voir docstring du module). Découpe l'image en blocs
    block x block, calcule le SSIM classique (moyenne/variance/covariance) par bloc,
    retourne la moyenne sur tous les blocs. Rogne l'image aux dimensions multiples de
    `block` (perte marginale de quelques pixels en bord, sans impact sur le signal
    global recherché ici)."""
    import numpy as np

    h, w = lum_a.shape
    h2 = (h // block) * block
    w2 = (w // block) * block
    if h2 == 0 or w2 == 0:
        return None  # image trop petite pour ce block size, pas de score fiable
    a = lum_a[:h2, :w2].reshape(h2 // block, block, w2 // block, block)
    b = lum_b[:h2, :w2].reshape(h2 // block, block, w2 // block, block)

    mu_a = a.mean(axis=(1, 3))
    mu_b = b.mean(axis=(1, 3))
    var_a = a.var(axis=(1, 3))
    var_b = b.var(axis=(1, 3))
    cov_ab = ((a - mu_a[:, None, :, None]) * (b - mu_b[:, None, :, None])).mean(axis=(1, 3))

    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2
    ssim_map = ((2 * mu_a * mu_b + C1) * (2 * cov_ab + C2)) / \
               ((mu_a ** 2 + mu_b ** 2 + C1) * (var_a + var_b + C2))
    return float(ssim_map.mean())


def compare_images(baseline_path, current_path,
                    ssim_threshold=DEFAULT_SSIM_THRESHOLD,
                    max_pct_changed=DEFAULT_MAX_PCT_CHANGED,
                    max_mean_diff=DEFAULT_MAX_MEAN_DIFF,
                    change_pixel_threshold=DEFAULT_CHANGE_PIXEL_THRESHOLD):
    """Compare deux screenshots et retourne un dict de métriques + verdict.
    Ne lève pas d'exception sur des tailles différentes : redimensionne `current` sur la
    taille de `baseline` (LANCZOS) et le signale dans le rapport plutôt que d'échouer —
    un changement de résolution de capture ne devrait pas silencieusement désactiver ce
    garde-fou, mais doit rester visible.
    """
    from PIL import Image
    import numpy as np

    lum_base, shape_base = _luminance(baseline_path)
    lum_cur, shape_cur = _luminance(current_path)

    resized = False
    if shape_cur != shape_base:
        resized = True
        img_cur = Image.open(current_path).convert("RGB").resize(
            (shape_base[1], shape_base[0]), Image.LANCZOS
        )
        lum_cur = np.array(img_cur).astype(float)
        lum_cur = 0.2126 * lum_cur[:, :, 0] + 0.7152 * lum_cur[:, :, 1] + 0.0722 * lum_cur[:, :, 2]

    diff = np.abs(lum_base - lum_cur)
    mean_diff = float(diff.mean())
    pct_changed = float((diff >= change_pixel_threshold).mean() * 100)
    ssim = _block_ssim(lum_base, lum_cur)

    problems = []
    if ssim is not None and ssim < ssim_threshold:
        problems.append(
            f"SIMILARITE STRUCTURELLE BASSE: SSIM={ssim:.3f} (seuil mini {ssim_threshold}) "
            f"— la composition de la zone a probablement changé vs la baseline"
        )
    if pct_changed > max_pct_changed:
        problems.append(
            f"CHANGEMENT ETENDU: {pct_changed:.1f}% des pixels ont changé de plus de "
            f"{change_pixel_threshold}/255 de luminance (max toléré {max_pct_changed}%)"
        )
    if mean_diff > max_mean_diff:
        problems.append(
            f"DIFF MOYENNE ELEVEE: écart de luminance moyen {mean_diff:.2f}/255 "
            f"(max toléré {max_mean_diff})"
        )
    notes = []
    if resized:
        notes.append(
            f"RESOLUTIONS DIFFERENTES: baseline={shape_base[1]}x{shape_base[0]} vs "
            f"actuel={shape_cur[1]}x{shape_cur[0]} — comparaison faite après redimensionnement, "
            f"moins fiable qu'une comparaison pixel-natif (informationnel, n'affecte pas le "
            f"verdict à lui seul)"
        )

    return {
        "baseline": baseline_path,
        "current": current_path,
        "ssim_score": round(ssim, 4) if ssim is not None else None,
        "mean_luminance_diff": round(mean_diff, 3),
        "pct_pixels_changed": round(pct_changed, 2),
        "resized_for_comparison": resized,
        "problems": problems,
        "notes": notes,
        "verdict": "STABLE" if not problems else "DERIVE_VISUELLE_DETECTEE",
    }


def _cmd_set_baseline(zone, screenshot_override, force, note):
    data = _load_manifest()
    entry = data.get(zone)
    if entry is None:
        print(f"ERREUR: zone '{zone}' introuvable dans le manifest QC ({_manifest_path()}). "
              f"Construire la zone via verified_zone_build() d'abord.", file=sys.stderr)
        sys.exit(2)

    src = screenshot_override or entry.get("screenshot")
    if not src or not os.path.isfile(src):
        print(f"ERREUR: pas de screenshot exploitable pour la zone '{zone}' "
              f"(source: {src!r}).", file=sys.stderr)
        sys.exit(2)

    if not force:
        if entry.get("qc_gate_verdict") != "PASS" or not entry.get("visual_read_confirmed"):
            print(
                "ERREUR: cette zone n'a pas encore (qc_gate PASS + lecture visuelle confirmée) "
                "— promouvoir ce screenshot en baseline reviendrait à figer une référence non "
                "vérifiée. Lancer qc_gate.py --zone puis --confirm-visual-read d'abord, ou "
                "passer --force avec --note expliquant pourquoi (ex: référence intentionnellement "
                "provisoire).",
                file=sys.stderr,
            )
            sys.exit(2)

    dest = os.path.join(_baselines_dir(), _safe_zone_filename(zone))
    shutil.copy2(src, dest)

    entry["baseline_screenshot"] = dest
    entry["baseline_source_screenshot"] = src
    entry["baseline_set_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    entry["baseline_note"] = note or None
    entry.pop("last_visual_diff", None)  # une nouvelle baseline invalide l'ancien diff
    data[zone] = entry
    _save_manifest(data)

    print(f"[visual_diff] Baseline enregistrée pour '{zone}': {dest}")
    sys.exit(0)


def compare_zone(zone, screenshot_override=None, record=True):
    """Cœur de --compare, réutilisable par d'autres scripts (qc_gate.py notamment) sans
    passer par sys.exit(). Retourne toujours un dict avec au moins une clé "verdict" parmi
    NO_BASELINE / STABLE / DERIVE_VISUELLE_DETECTEE / ZONE_INCONNUE / SCREENSHOT_MANQUANT —
    jamais d'exception pour un cas attendu (zone/baseline/screenshot absents), pour rester
    appelable depuis un chemin qui ne doit pas planter (ex: qc_gate.py --zone sur une zone
    qui n'a simplement pas encore de baseline, ce qui est le cas normal la première fois).
    """
    data = _load_manifest()
    entry = data.get(zone)
    if entry is None:
        return {"zone": zone, "verdict": "ZONE_INCONNUE",
                "message": f"zone '{zone}' introuvable dans le manifest QC."}

    baseline = entry.get("baseline_screenshot")
    if not baseline or not os.path.isfile(baseline):
        return {"zone": zone, "verdict": "NO_BASELINE",
                "message": "Aucune baseline enregistrée — lancer --set-baseline d'abord."}

    current = screenshot_override or entry.get("screenshot")
    if not current or not os.path.isfile(current):
        return {"zone": zone, "verdict": "SCREENSHOT_MANQUANT",
                "message": f"pas de screenshot actuel exploitable pour '{zone}'."}

    result = compare_images(baseline, current)
    result["zone"] = zone

    if record:
        entry["last_visual_diff"] = {
            "verdict": result["verdict"],
            "ssim_score": result["ssim_score"],
            "pct_pixels_changed": result["pct_pixels_changed"],
            "mean_luminance_diff": result["mean_luminance_diff"],
            "compared_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "compared_screenshot": current,
        }
        data[zone] = entry
        _save_manifest(data)

    return result


def _cmd_compare(zone, screenshot_override, record):
    result = compare_zone(zone, screenshot_override, record)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["verdict"] in ("ZONE_INCONNUE", "SCREENSHOT_MANQUANT"):
        sys.exit(2)
    if result["verdict"] == "NO_BASELINE":
        sys.exit(2)
    sys.exit(0 if result["verdict"] == "STABLE" else 1)


def _cmd_compare_all():
    data = _load_manifest()
    zones_with_baseline = [z for z, e in data.items() if e.get("baseline_screenshot")]
    if not zones_with_baseline:
        print(json.dumps({"verdict": "EMPTY", "message": "Aucune zone n'a de baseline."},
                          indent=2, ensure_ascii=False))
        sys.exit(0)

    results = {}
    any_drift = False
    any_error = False
    for zone in zones_with_baseline:
        entry = data[zone]
        baseline = entry.get("baseline_screenshot")
        current = entry.get("screenshot")
        if not baseline or not os.path.isfile(baseline) or not current or not os.path.isfile(current):
            results[zone] = {"verdict": "ERROR", "message": "baseline ou screenshot actuel introuvable sur disque"}
            any_error = True
            continue
        r = compare_images(baseline, current)
        results[zone] = r
        entry["last_visual_diff"] = {
            "verdict": r["verdict"], "ssim_score": r["ssim_score"],
            "pct_pixels_changed": r["pct_pixels_changed"],
            "mean_luminance_diff": r["mean_luminance_diff"],
            "compared_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "compared_screenshot": current,
        }
        data[zone] = entry
        if r["verdict"] != "STABLE":
            any_drift = True

    _save_manifest(data)

    report = {
        "total_zones_with_baseline": len(zones_with_baseline),
        "zones_with_drift": [z for z, r in results.items() if r.get("verdict") == "DERIVE_VISUELLE_DETECTEE"],
        "per_zone": results,
        "verdict": "DRIFT_DETECTED" if any_drift else ("ERROR" if any_error else "ALL_STABLE"),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    sys.exit(1 if (any_drift or any_error) else 0)


def _cmd_list_baselines():
    data = _load_manifest()
    out = {}
    for zone, entry in data.items():
        out[zone] = {
            "has_baseline": bool(entry.get("baseline_screenshot")),
            "baseline_set_at": entry.get("baseline_set_at"),
            "last_visual_diff_verdict": (entry.get("last_visual_diff") or {}).get("verdict"),
        }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set-baseline", metavar="ZONE", default=None,
                     help="Promeut le screenshot actuel de ZONE (déjà qc_gate PASS + lecture "
                          "visuelle confirmée, sauf --force) en référence de comparaison")
    ap.add_argument("--compare", metavar="ZONE", default=None,
                     help="Compare le screenshot actuel de ZONE à sa baseline enregistrée")
    ap.add_argument("--compare-all", action="store_true",
                     help="Compare toutes les zones ayant une baseline en un seul appel")
    ap.add_argument("--list-baselines", action="store_true",
                     help="Liste les zones du manifest QC avec/sans baseline")
    ap.add_argument("--screenshot", default=None,
                     help="Chemin explicite vers un screenshot, au lieu de celui du manifest "
                          "(--set-baseline / --compare uniquement)")
    ap.add_argument("--force", action="store_true",
                     help="Autorise --set-baseline même sans (qc_gate PASS + lecture visuelle "
                          "confirmée) — nécessite --note")
    ap.add_argument("--note", default="",
                     help="Note jointe à --set-baseline 