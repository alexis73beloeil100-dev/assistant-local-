"""Atelier Unreal, etape 4 : l'animation, par le Python de l'editeur.

L'editeur Unreal embarque Python (PythonScriptPlugin) et sait recevoir des
commandes d'un autre programme : c'est la "remote execution" d'Epic. On ne
livre pas son code : on charge remote_execution.py depuis le moteur de
l'utilisateur, la ou Epic l'installe.

Prerequis, poses par activer_python_editeur() : le plugin Python active dans
le .uproject, et l'execution a distance cochee dans DefaultEngine.ini. Elle
reste sur la machine (multicast local, connexion 127.0.0.1).

Ce que l'assistant en tire : lire un squelette et nommer chaque partie du
corps, inspecter une animation, verifier sa compatibilite, retargeter, creer
des Montages, poser des notifies et des courbes, et MESURER la qualite --
glissement des pieds, sauts de pose d'une image a l'autre.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

from assistant import safety

SECTION_PYTHON = "[/Script/PythonScriptPlugin.PythonScriptPluginSettings]"
MARQUEUR = "@@ASSISTANT@@"


class Indisponible(Exception):
    """Le Python de l'editeur ne repond pas."""


# --- Les parties du corps -----------------------------------------------------

# Motifs des conventions courantes : Mannequin d'Epic (UE4 et UE5), Mixamo,
# Biped de 3ds Max, packs du Fab. L'ordre compte : le plus precis d'abord.
PARTIES = [
    ("doigts", r"thumb|index|middle|ring|pinky|finger|pouce"),
    ("main", r"hand|wrist|palm|main"),
    ("avant-bras", r"lowerarm|forearm|lower_arm|elbow|_fore|avantbras"),
    ("bras", r"upperarm|upper_arm|shoulder|\barm\b|_arm|bras"),
    ("clavicule", r"clavicle|collar"),
    ("tete", r"head|skull|jaw|eye|tete"),
    ("cou", r"neck|cou"),
    ("orteils", r"toe|ball"),
    ("pied", r"foot|ankle|heel|pied"),
    ("mollet", r"calf|shin|lowerleg|lower_leg|knee|leg_lower"),
    ("cuisse", r"thigh|upperleg|upper_leg|upleg|leg_upper|\bleg\b|cuisse"),
    ("bassin", r"pelvis|hips?\b|bassin"),
    ("colonne", r"spine|chest|torso|abdomen|colonne"),
    ("racine", r"^root$|^armature$"),
    ("ik", r"\bik_|_ik\b|^ik"),
]


def cote(os_nom: str) -> str:
    n = os_nom.lower()
    if re.search(r"(^|[_.\s])(l|left|gauche)([_.\s]|$)|_l$|left", n):
        return "gauche"
    if re.search(r"(^|[_.\s])(r|right|droite)([_.\s]|$)|_r$|right", n):
        return "droite"
    return ""


def partie(os_nom: str) -> str:
    n = os_nom.lower()
    for nom, motif in PARTIES:
        if re.search(motif, n):
            return nom
    return "autre"


def carte_du_corps(os_noms: list[str]) -> dict[str, list[str]]:
    """{"main gauche": [...], "colonne": [...]} pour une liste d'os."""
    carte: dict[str, list[str]] = {}
    for o in os_noms:
        p = partie(o)
        c = cote(o) if p not in ("colonne", "bassin", "cou", "tete", "racine") else ""
        carte.setdefault(f"{p} {c}".strip(), []).append(o)
    return carte


# --- Mesures ------------------------------------------------------------------

def glissement_des_pieds(positions: list[tuple[float, float, float]],
                         seuil_hauteur: float = 3.0) -> dict:
    """Glissement horizontal d'un pied pendant qu'il est au sol.

    Positions en cm, espace monde, une par image. Le pied est "au sol"
    quand il est a moins de `seuil_hauteur` cm au-dessus de son point le
    plus bas. Le glissement est la distance horizontale parcourue pendant
    ces images-la : c'est ce qui se voit comme un pied qui patine.
    """
    if len(positions) < 2:
        return {"images_au_sol": 0, "glissement_cm": 0.0, "pire_image_cm": 0.0}
    sol = min(p[2] for p in positions) + seuil_hauteur
    total, pire, au_sol = 0.0, 0.0, 0
    for a, b in zip(positions, positions[1:]):
        if a[2] <= sol and b[2] <= sol:
            d = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
            total += d
            pire = max(pire, d)
            au_sol += 1
    return {"images_au_sol": au_sol, "glissement_cm": round(total, 2),
            "pire_image_cm": round(pire, 2)}


def sauts_de_pose(poses: list[dict[str, tuple[float, float, float]]],
                  seuil_cm: float = 1.0) -> list[tuple[int, str, float]]:
    """(image, os, deplacement) quand un os bouge de plus de seuil_cm."""
    sauts = []
    for i, (a, b) in enumerate(zip(poses, poses[1:]), 1):
        for os_nom, pa in a.items():
            pb = b.get(os_nom)
            if pb is None:
                continue
            d = sum((x - y) ** 2 for x, y in zip(pa, pb)) ** 0.5
            if d > seuil_cm:
                sauts.append((i, os_nom, round(d, 2)))
    return sorted(sauts, key=lambda s: -s[2])


# --- Le Python de l'editeur ----------------------------------------------------

def _module_epic():
    """remote_execution.py, charge depuis le moteur du projet."""
    _projet, moteur = _projet_et_moteur()
    candidats = [
        moteur / "Engine/Plugins/Experimental/PythonScriptPlugin/Content/Python/remote_execution.py",
        moteur / "Engine/Plugins/Scripting/PythonScriptPlugin/Content/Python/remote_execution.py",
    ]
    fichier = next((c for c in candidats if c.is_file()), None)
    if fichier is None:
        trouves = list((moteur / "Engine" / "Plugins").glob("**/PythonScriptPlugin/Content/Python/remote_execution.py"))
        fichier = trouves[0] if trouves else None
    if fichier is None:
        raise Indisponible(f"remote_execution.py introuvable dans le moteur {moteur}.")
    spec = importlib.util.spec_from_file_location("ue_remote_execution", fichier)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _projet_et_moteur():
    from assistant.skills import unreal

    projet = unreal.projet_actuel()
    if projet is None:
        raise Indisponible("Aucun projet Unreal choisi.")
    try:
        donnees = unreal.lire_uproject(projet)
        moteur = unreal.dossier_moteur(projet, str(donnees.get("EngineAssociation", "")))
    except unreal.Echec as exc:
        raise Indisponible(str(exc))
    return projet, moteur


DUREE_ARRIERE_PLAN = 600


def executer_en_arriere_plan(code_python: str) -> str:
    """Lance Unreal sans fenetre, execute le script, et se referme.

    Plus lent (le moteur demarre : 30 s a une minute), mais il n'y a pas
    besoin d'ouvrir l'editeur : c'est ce qui permet de lire un Blueprint ou
    une animation l'editeur ferme.
    """
    import os
    import subprocess
    import tempfile

    projet, moteur = _projet_et_moteur()
    exe = moteur / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
    if not exe.is_file():
        raise Indisponible(f"UnrealEditor-Cmd.exe introuvable : {exe}")
    with tempfile.TemporaryDirectory() as dossier:
        script = Path(dossier) / "geste.py"
        script.write_text(code_python, encoding="utf-8")
        try:
            r = subprocess.run(
                [str(exe), str(projet), "-run=pythonscript", f"-script={script}",
                 "-unattended", "-nop4", "-nosplash", "-nullrhi", "-stdout",
                 "-FullStdOutLogOutput"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=DUREE_ARRIERE_PLAN,
                creationflags=0x08000000 if os.name == "nt" else 0)
        except subprocess.TimeoutExpired:
            raise Indisponible("Unreal en arriere-plan n'a pas fini en 10 minutes.")
        except OSError as exc:
            raise Indisponible(f"Unreal en arriere-plan impossible a lancer : {exc}")
    sortie = r.stdout + "\n" + r.stderr
    if MARQUEUR not in sortie:
        erreurs = [l for l in sortie.splitlines()
                   if "LogPython: Error" in l or "Traceback" in l or "Error:" in l]
        raise Indisponible("Unreal en arriere-plan n'a rien rendu.\n"
                           + "\n".join(erreurs[-20:] or sortie.splitlines()[-20:]))
    return sortie


def executer_python(code_python: str, delai: float = 5.0) -> str:
    """Execute du Python dans l'editeur ouvert, sinon dans Unreal en
    arriere-plan, et rend ce qu'il affiche."""
    import time

    re_mod = _module_epic()
    session = re_mod.RemoteExecution()
    session.start()
    try:
        debut = time.time()
        while not session.remote_nodes and time.time() - debut < delai:
            time.sleep(0.2)
        if not session.remote_nodes:
            session.stop()
            try:
                return executer_en_arriere_plan(code_python)
            except Indisponible as exc:
                raise Indisponible(
                    "L'editeur n'est pas ouvert (ou son Python n'est pas "
                    "active), et Unreal en arriere-plan a echoue : "
                    f"{exc}\nActive le Python de l'editeur (outil "
                    "activer_python_editeur), puis reessaie.")
        session.open_command_connection(session.remote_nodes[0]["node_id"])
        resultat = session.run_command(code_python, unattended=True,
                                       exec_mode=re_mod.MODE_EXEC_FILE,
                                       raise_on_failure=False)
    finally:
        session.stop()
    sortie = "\n".join(str(o.get("output", "")).rstrip()
                       for o in resultat.get("output", []))
    if not resultat.get("success", False):
        return "Erreur dans l'editeur :\n" + (sortie or str(resultat.get("result")))
    return sortie or "Execute, sans affichage."


def activer_python_editeur(ask=None) -> str:
    """Active le plugin Python et l'execution a distance dans le projet."""
    from assistant.skills import unreal

    projet = unreal.projet_actuel()
    if projet is None:
        return "Aucun projet Unreal choisi."
    ini = projet.parent / "Config" / "DefaultEngine.ini"
    action = safety.Action(
        kind="projet", summary=f"Activer le Python de l'editeur dans {projet.stem}",
        targets=[str(projet), str(ini)], reversible=True,
        details="Plugin PythonScriptPlugin, et execution a distance limitee "
                "a cette machine. Redemarrer l'editeur ensuite.")
    try:
        if not safety.guard(action, ask=ask):
            return "Annule."
    except safety.Refused as exc:
        return str(exc)
    donnees = json.loads(projet.read_text(encoding="utf-8-sig"))
    plugins = donnees.setdefault("Plugins", [])
    for nom in ("PythonScriptPlugin", "EditorScriptingUtilities"):
        e = next((p for p in plugins if p.get("Name") == nom), None)
        if e is None:
            plugins.append({"Name": nom, "Enabled": True})
        else:
            e["Enabled"] = True
    projet.write_text(json.dumps(donnees, indent="\t", ensure_ascii=False) + "\n",
                      encoding="utf-8")
    ini.parent.mkdir(parents=True, exist_ok=True)
    texte = ini.read_text(encoding="utf-8", errors="replace") if ini.exists() else ""
    ini.write_text(activer_dans_ini(texte), encoding="utf-8")
    return ("Python de l'editeur active (plugin et execution a distance). "
            "Redemarre l'editeur pour que ce soit pris en compte.")


def activer_dans_ini(texte: str) -> str:
    """Pose bRemoteExecution=True dans la bonne section, sans doublon."""
    lignes = texte.splitlines()
    if SECTION_PYTHON not in lignes:
        return (texte.rstrip("\n") + ("\n\n" if texte.strip() else "")
                + f"{SECTION_PYTHON}\nbRemoteExecution=True\n")
    i = lignes.index(SECTION_PYTHON) + 1
    fin = next((j for j in range(i, len(lignes)) if lignes[j].startswith("[")),
               len(lignes))
    bloc = [l for l in lignes[i:fin] if not l.startswith("bRemoteExecution=")]
    lignes[i:fin] = ["bRemoteExecution=True"] + bloc
    return "\n".join(lignes) + "\n"


# --- Les gestes d'animation ------------------------------------------------------
#
# Chaque geste est un petit script execute DANS l'editeur. Il imprime une
# ligne JSON apres le MARQUEUR : c'est ce qu'on lit en retour, le reste de la
# sortie (avertissements de l'editeur) est ignore.

_ENTETE = f"""import unreal, json
def _rendre(v): print({MARQUEUR!r} + json.dumps(v, default=str))
def _charger(p):
    a = unreal.EditorAssetLibrary.load_asset(p)
    if a is None: raise RuntimeError("asset introuvable : " + p)
    return a
"""


def _geste(script: str, **valeurs) -> dict | list | str:
    code = _ENTETE + "".join(f"{k} = {json.dumps(v)}\n" for k, v in valeurs.items()) + script
    sortie = executer_python(code)
    for ligne in sortie.splitlines():
        # En arriere-plan, la ligne arrive prefixee par le journal
        # ("LogPython: ...") : on cherche le marqueur dans la ligne.
        if MARQUEUR in ligne:
            return json.loads(ligne[ligne.index(MARQUEUR) + len(MARQUEUR):])
    raise Indisponible(sortie)


_OS_DU_SQUELETTE = """
a = _charger(chemin)
noms = []
pose = None
if isinstance(a, unreal.AnimSequence):
    pose = unreal.AnimPoseExtensions.get_anim_pose_at_time(a, 0.0, unreal.AnimPoseEvaluationOptions())
elif isinstance(a, unreal.SkeletalMesh):
    pose = unreal.AnimPoseExtensions.get_reference_pose(a.skeleton)
elif isinstance(a, unreal.Skeleton):
    pose = unreal.AnimPoseExtensions.get_reference_pose(a)
if pose is None: raise RuntimeError("ni squelette, ni maillage, ni animation : " + chemin)
noms = [str(n) for n in unreal.AnimPoseExtensions.get_bone_names(pose)]
parents = {}
for n in noms:
    try: parents[n] = str(unreal.AnimPoseExtensions.get_parent_bone_name(pose, n))
    except Exception: pass
_rendre({"os": noms, "parents": parents})
"""


def squelette(chemin: str) -> str:
    """Les os d'un squelette, d'un maillage ou d'une animation, par partie du corps."""
    try:
        r = _geste(_OS_DU_SQUELETTE, chemin=chemin)
    except Indisponible as exc:
        return str(exc)
    carte = carte_du_corps(r["os"])
    lignes = [f"{len(r['os'])} os dans {chemin}, par partie du corps :"]
    for p in sorted(carte):
        lignes.append(f"  {p:<18} {', '.join(carte[p][:14])}"
                      + (" ..." if len(carte[p]) > 14 else ""))
    if r.get("parents"):
        lignes.append("Hierarchie (os -> parent) :")
        lignes += [f"  {o} -> {p}" for o, p in list(r["parents"].items())[:200]]
    return "\n".join(lignes)


_INFOS = """
a = _charger(chemin)
lib = unreal.AnimationLibrary
infos = {"classe": a.get_class().get_name(),
         "squelette": a.get_editor_property("skeleton").get_path_name() if a.get_editor_property("skeleton") else None}
try: infos["duree_s"] = a.get_play_length()
except Exception: pass
try: infos["images"] = lib.get_num_frames(a)
except Exception: pass
try: infos["cadence"] = str(lib.get_frame_rate(a))
except Exception: pass
try: infos["root_motion"] = a.get_editor_property("enable_root_motion")
except Exception: pass
try: infos["notifies"] = [(str(e.notify_name), round(e.get_editor_property("trigger_time_offset"), 3)) if hasattr(e, "notify_name") else str(e) for e in lib.get_animation_notify_events(a)]
except Exception as x: infos["notifies"] = "illisibles : " + str(x)
try: infos["courbes"] = [str(c) for c in lib.get_animation_curve_names(a, unreal.RawCurveTrackTypes.RCT_FLOAT)]
except Exception: pass
_rendre(infos)
"""


def infos_animation(chemin: str) -> str:
    try:
        return json.dumps(_geste(_INFOS, chemin=chemin), ensure_ascii=False, indent=1)
    except Indisponible as exc:
        return str(exc)


_POSITIONS = """
a = _charger(chemin)
ext = unreal.AnimPoseExtensions
duree = a.get_play_length()
n = max(2, int(round(duree * cadence)) + 1)
opts = unreal.AnimPoseEvaluationOptions()
images = []
for i in range(n):
    pose = ext.get_anim_pose_at_time(a, min(duree, i / cadence), opts)
    image = {}
    for o in os_noms:
        t = ext.get_bone_pose(pose, o, unreal.AnimPoseSpaces.WORLD)
        image[o] = [t.translation.x, t.translation.y, t.translation.z]
    images.append(image)
_rendre(images)
"""


def mesurer(chemin: str, pieds: list[str] | None = None, cadence: float = 30.0) -> str:
    """Glissement des pieds et sauts de pose, en centimetres."""
    try:
        os_info = _geste(_OS_DU_SQUELETTE, chemin=chemin)
        tous = os_info["os"]
        if not pieds:
            pieds = [o for o in tous if partie(o) == "pied"][:2]
        suivis = sorted(set(pieds) | {o for o in tous
                                      if partie(o) in ("main", "tete", "bassin", "pied")})
        images = _geste(_POSITIONS, chemin=chemin, os_noms=suivis, cadence=float(cadence))
    except Indisponible as exc:
        return str(exc)
    lignes = [f"Mesures de {chemin} ({len(images)} images a {cadence:g} i/s) :"]
    for p in pieds:
        g = glissement_des_pieds([tuple(i[p]) for i in images if p in i])
        etat = "OK" if g["pire_image_cm"] < 2.0 else "A CORRIGER"
        lignes.append(f"  {p}: glissement au sol {g['glissement_cm']} cm sur "
                      f"{g['images_au_sol']} images, pire image {g['pire_image_cm']} cm "
                      f"(tolerance 2 cm) -> {etat}")
    sauts = sauts_de_pose([{o: tuple(v) for o, v in i.items()} for i in images], 5.0)
    if sauts:
        lignes.append("  Sauts de plus de 5 cm d'une image a l'autre :")
        lignes += [f"    image {i}, {o} : {d} cm" for i, o, d in sauts[:12]]
    else:
        lignes.append("  Aucun saut de plus de 5 cm d'une image a l'autre.")
    return "\n".join(lignes)


_NOTIFY = """
a = _charger(chemin)
lib = unreal.AnimationLibrary
classe = unreal.load_class(None, classe_notify) if classe_notify.startswith("/") else getattr(unreal, classe_notify)
lib.add_animation_notify_event(a, piste, temps, classe)
unreal.EditorAssetLibrary.save_loaded_asset(a)
_rendre({"ok": True})
"""


def ajouter_notify(chemin: str, temps: float, classe: str = "AnimNotify_PlaySound",
                   piste: str = "1") -> str:
    _journal(f"Notify {classe} a {temps} s dans {chemin}")
    try:
        _geste(_NOTIFY, chemin=chemin, temps=float(temps), classe_notify=classe,
               piste=piste)
    except Indisponible as exc:
        return str(exc)
    return f"Notify {classe} ajoute a {temps} s sur la piste {piste} de {chemin}."


_COURBE = """
a = _charger(chemin)
lib = unreal.AnimationLibrary
lib.add_curve(a, nom, unreal.RawCurveTrackTypes.RCT_FLOAT, False)
lib.add_float_curve_keys(a, nom, [k[0] for k in cles], [k[1] for k in cles])
unreal.EditorAssetLibrary.save_loaded_asset(a)
_rendre({"ok": True})
"""


def ajouter_courbe(chemin: str, nom: str, cles: list) -> str:
    _journal(f"Courbe {nom} dans {chemin}")
    try:
        _geste(_COURBE, chemin=chemin, nom=nom, cles=[[float(t), float(v)] for t, v in cles])
    except Indisponible as exc:
        return str(exc)
    return f"Courbe {nom} : {len(cles)} cle(s) posee(s) dans {chemin}."


_MONTAGE = """
a = _charger(chemin)
dossier, nom_seq = chemin.rsplit("/", 1)
fab = unreal.AnimMontageFactory()
fab.set_editor_property("source_animation", a)
outils = unreal.AssetToolsHelpers.get_asset_tools()
m = outils.create_asset(nom or ("AM_" + nom_seq.split(".")[0]), dossier, unreal.AnimMontage, fab)
if m is None: raise RuntimeError("montage non cree")
try:
    m.set_editor_property("blend_in", unreal.AlphaBlend(blend_time=fondu_entree))
    m.set_editor_property("blend_out", unreal.AlphaBlend(blend_time=fondu_sortie))
except Exception: pass
unreal.EditorAssetLibrary.save_loaded_asset(m)
_rendre({"montage": m.get_path_name()})
"""


def creer_montage(chemin: str, nom: str = "", fondu_entree: float = 0.25,
                  fondu_sortie: float = 0.25) -> str:
    _journal(f"Montage depuis {chemin}")
    try:
        r = _geste(_MONTAGE, chemin=chemin, nom=nom, fondu_entree=float(fondu_entree),
                   fondu_sortie=float(fondu_sortie))
    except Indisponible as exc:
        return str(exc)
    return f"Montage cree : {r['montage']} (fondus {fondu_entree} s / {fondu_sortie} s)."


_RETARGET = """
outils = [unreal.EditorAssetLibrary.find_asset_data(p) for p in animations]
rtg = _charger(retargeter)
src = _charger(source) if source else None
dst = _charger(cible)
res = unreal.IKRetargetBatchOperation.duplicate_and_retarget(
    outils, src, dst, rtg, "", "", prefixe, "", True, True)
_rendre({"crees": [str(a.package_name) for a in res]})
"""


def retargeter(animations: list[str], retargeter_ik: str, maillage_cible: str,
               maillage_source: str = "", prefixe: str = "RTG_") -> str:
    _journal(f"Retarget de {len(animations)} animation(s) vers {maillage_cible}")
    try:
        r = _geste(_RETARGET, animations=list(animations), retargeter=retargeter_ik,
                   cible=maillage_cible, source=maillage_source, prefixe=prefixe)
    except Indisponible as exc:
        return str(exc)
    return "Animations retargetees :\n" + "\n".join(f"  {c}" for c in r["crees"])


_COMPATIBLE = """
a = _charger(animation)
m = _charger(maillage)
sa = a.get_editor_property("skeleton")
sm = m.skeleton if isinstance(m, unreal.SkeletalMesh) else m
ext = unreal.AnimPoseExtensions
os_a = set(str(n) for n in ext.get_bone_names(ext.get_anim_pose_at_time(a, 0.0, unreal.AnimPoseEvaluationOptions())))
os_m = set(str(n) for n in ext.get_bone_names(ext.get_reference_pose(sm)))
_rendre({"meme_squelette": sa == sm, "squelette_anim": sa.get_path_name() if sa else None,
         "squelette_maillage": sm.get_path_name() if sm else None,
         "manquants": sorted(os_a - os_m), "en_plus": sorted(os_m - os_a)})
"""


def compatibilite(animation: str, maillage: str) -> str:
    try:
        r = _geste(_COMPATIBLE, animation=animation, maillage=maillage)
    except Indisponible as exc:
        return str(exc)
    if r["meme_squelette"]:
        return "Compatible : l'animation et le maillage partagent le meme squelette."
    lignes = [f"Squelettes differents : {r['squelette_anim']} / {r['squelette_maillage']}."]
    if r["manquants"]:
        lignes.append(f"Os de l'animation absents du maillage ({len(r['manquants'])}) : "
                      + ", ".join(r["manquants"][:30]))
    if r["en_plus"]:
        lignes.append(f"Os du maillage absents de l'animation ({len(r['en_plus'])}) : "
                      + ", ".join(r["en_plus"][:30]))
    lignes.append("Il faut un retargeting (IK Rig + IK Retargeter) : outil "
                  "retargeter_animations.")
    return "\n".join(lignes)


def _journal(resume: str) -> None:
    safety.guard(safety.Action(kind="animation", summary=resume,
                               targets=[resume[:200]], routine=True))


def python_editeur(script: str, ask=None) -> str:
    """Execute un script Python libre dans l'editeur, apres accord."""
    action = safety.Action(kind="editeur", summary="Script Python dans l'editeur Unreal",
                           targets=["editeur"], reversible=False,
                           details=script[:3000])
    try:
        if not safety.guard(action, ask=ask):
            return "Script refuse."
    except safety.Refused as exc:
        return str(exc)
    try:
        return executer_python(script)
    except Indisponible as exc:
        return str(exc)


# --- Jouer dans l'editeur (PIE) ----------------------------------------------------

_JOUER = """
sub = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
if action == "jouer":
    sub.editor_request_begin_play()
elif action == "simuler":
    sub.editor_play_simulate()
else:
    sub.editor_request_end_play()
_rendre({"ok": True, "action": action})
"""


def jouer_dans_editeur(action: str = "jouer") -> str:
    """Lance (ou arrete) une partie de test dans l'editeur ouvert."""
    from assistant.skills import unreal

    action = action if action in ("jouer", "simuler", "arreter") else "jouer"
    try:
        _geste_editeur_ouvert(_JOUER, action=action)
    except Indisponible:
        if action == "arreter":
            return "Aucun editeur ouvert a arreter."
        return ("L'editeur n'est pas ouvert, ou son Python n'est pas active : "
                "je lance le jeu seul a la place.\n" + unreal.lancer_jeu())
    return {"jouer": "Partie de test lancee dans l'editeur (Play In Editor).",
            "simuler": "Simulation lancee dans l'editeur.",
            "arreter": "Partie de test arretee."}[action]


def _geste_editeur_ouvert(script: str, **valeurs):
    """Comme _geste, mais seulement dans l'editeur OUVERT : jouer n'a pas de
    sens dans un Unreal en arriere-plan."""
    import time

    code = _ENTETE + "".join(f"{k} = {json.dumps(v)}\n" for k, v in valeurs.items()) + script
    re_mod = _module_epic()
    session = re_mod.RemoteExecution()
    session.start()
    try:
        debut = time.time()
        while not session.remote_nodes and time.time() - debut < 5:
            time.sleep(0.2)
        if not session.remote_nodes:
            raise Indisponible("editeur ferme")
        session.open_command_connection(session.remote_nodes[0]["node_id"])
        r = session.run_command(code, unattended=True, exec_mode=re_mod.MODE_EXEC_FILE,
                                raise_on_failure=False)
    finally:
        session.stop()
    if not r.get("success"):
        raise Indisponible(str(r.get("result")))
    return r
