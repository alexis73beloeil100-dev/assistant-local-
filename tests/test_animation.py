"""Atelier Unreal, etape 4 : l'animation."""
from __future__ import annotations

import json

import pytest

from assistant import llm
from assistant.skills import animation as anim

MANNEQUIN_UE5 = [
    "root", "pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "spine_05",
    "neck_01", "neck_02", "head", "clavicle_l", "upperarm_l", "lowerarm_l",
    "hand_l", "index_01_l", "thumb_02_l", "clavicle_r", "upperarm_r",
    "lowerarm_r", "hand_r", "pinky_03_r", "thigh_l", "calf_l", "foot_l",
    "ball_l", "thigh_r", "calf_r", "foot_r", "ball_r", "ik_foot_root", "ik_hand_gun",
]
MIXAMO = ["mixamorig:Hips", "mixamorig:Spine2", "mixamorig:Head",
          "mixamorig:LeftArm", "mixamorig:LeftForeArm", "mixamorig:LeftHand",
          "mixamorig:LeftHandIndex1", "mixamorig:RightUpLeg", "mixamorig:RightLeg",
          "mixamorig:RightFoot", "mixamorig:RightToeBase"]


def test_chaque_partie_du_corps_du_mannequin_est_reconnue():
    carte = anim.carte_du_corps(MANNEQUIN_UE5)
    assert carte["tete"] == ["head"]
    assert carte["cou"] == ["neck_01", "neck_02"]
    assert carte["colonne"] == ["spine_01", "spine_02", "spine_03", "spine_04", "spine_05"]
    assert carte["bassin"] == ["pelvis"]
    assert carte["bras gauche"] == ["upperarm_l"]
    assert carte["avant-bras droite"] == ["lowerarm_r"]
    assert carte["main gauche"] == ["hand_l"]
    assert carte["doigts gauche"] == ["index_01_l", "thumb_02_l"]
    assert carte["cuisse droite"] == ["thigh_r"]
    assert carte["mollet gauche"] == ["calf_l"]
    assert carte["pied droite"] == ["foot_r"]
    assert carte["orteils gauche"] == ["ball_l"]
    assert carte["clavicule droite"] == ["clavicle_r"]
    assert "autre" not in carte


def test_un_squelette_mixamo_est_compris_aussi():
    carte = anim.carte_du_corps(MIXAMO)
    assert carte["bassin"] == ["mixamorig:Hips"]
    assert carte["avant-bras gauche"] == ["mixamorig:LeftForeArm"]
    assert carte["doigts gauche"] == ["mixamorig:LeftHandIndex1"]
    assert carte["cuisse droite"] == ["mixamorig:RightUpLeg"]
    assert carte["pied droite"] == ["mixamorig:RightFoot"]
    assert carte["orteils droite"] == ["mixamorig:RightToeBase"]


def test_un_pied_qui_patine_est_mesure_en_centimetres():
    # Au sol (z=0) pendant 4 images, en glissant de 1,5 cm puis 0,5 cm ;
    # puis il se leve (z=12) et avance de 30 cm : ce n'est pas du glissement.
    positions = [(0, 0, 0), (1.5, 0, 0), (2.0, 0, 0.5), (2.0, 0, 0),
                 (10, 0, 12), (30, 0, 12), (32, 0, 0)]
    g = anim.glissement_des_pieds(positions)
    assert g == {"images_au_sol": 3, "glissement_cm": 2.0, "pire_image_cm": 1.5}


def test_un_saut_de_pose_est_trouve_a_la_bonne_image():
    poses = [{"hand_r": (0, 0, 100)}, {"hand_r": (0.5, 0, 100)},
             {"hand_r": (12.5, 0, 100)}, {"hand_r": (13, 0, 100)}]
    assert anim.sauts_de_pose(poses, 5.0) == [(2, "hand_r", 12.0)]


def test_l_execution_a_distance_se_pose_sans_doublon():
    texte = ("[/Script/EngineSettings.GameMapsSettings]\nGameDefaultMap=/Game/A\n\n"
             "[/Script/PythonScriptPlugin.PythonScriptPluginSettings]\n"
             "bRemoteExecution=False\nbDeveloperMode=True\n")
    resultat = anim.activer_dans_ini(texte)
    assert resultat.count("bRemoteExecution") == 1
    assert "bRemoteExecution=True" in resultat
    assert "bDeveloperMode=True" in resultat and "GameDefaultMap=/Game/A" in resultat
    vide = anim.activer_dans_ini("")
    assert vide == f"{anim.SECTION_PYTHON}\nbRemoteExecution=True\n"


class FauxModuleEpic:
    """Le module remote_execution.py d'Epic, tel que ses fonctions s'appellent."""
    MODE_EXEC_FILE = "ExecuteFile"
    recu: list = []
    reponse = None

    class RemoteExecution:
        def __init__(self):
            self.remote_nodes = [{"node_id": "ue-1"}]

        def start(self):
            pass

        def stop(self):
            pass

        def open_command_connection(self, noeud):
            assert noeud == "ue-1"

        def run_command(self, code, unattended, exec_mode, raise_on_failure):
            FauxModuleEpic.recu.append((code, exec_mode))
            return FauxModuleEpic.reponse


def test_un_geste_part_comme_un_fichier_python_et_revient_en_json(monkeypatch):
    FauxModuleEpic.recu = []
    FauxModuleEpic.reponse = {"success": True, "output": [
        {"type": "Warning", "output": "LogPython: Warning: rien"},
        {"type": "Info", "output": anim.MARQUEUR + json.dumps({"os": MANNEQUIN_UE5,
                                                               "parents": {"hand_l": "lowerarm_l"}})}]}
    monkeypatch.setattr(anim, "_module_epic", lambda: FauxModuleEpic)
    texte = anim.squelette("/Game/Characters/SKM_Manny")
    code, mode = FauxModuleEpic.recu[0]
    assert mode == "ExecuteFile"
    assert 'chemin = "/Game/Characters/SKM_Manny"' in code
    assert "31 os" in texte and "main gauche" in texte and "hand_l -> lowerarm_l" in texte


def test_une_erreur_python_dans_l_editeur_remonte_telle_quelle(monkeypatch):
    FauxModuleEpic.reponse = {"success": False, "output": [
        {"output": "RuntimeError: asset introuvable : /Game/X"}]}
    monkeypatch.setattr(anim, "_module_epic", lambda: FauxModuleEpic)
    assert "asset introuvable : /Game/X" in anim.squelette("/Game/X")


def test_editeur_sans_python_le_dit(monkeypatch):
    class Muet(FauxModuleEpic):
        class RemoteExecution(FauxModuleEpic.RemoteExecution):
            def __init__(self):
                self.remote_nodes = []

    monkeypatch.setattr(anim, "_module_epic", lambda: Muet)
    monkeypatch.setattr("time.sleep", lambda s: None)
    texte = anim.infos_animation("/Game/A")
    assert "activer_python_editeur" in texte


def test_les_outils_d_animation_sont_en_mode_dev(monkeypatch):
    assert llm.OUTILS_ANIMATION <= llm.OUTILS_DEV_SEULEMENT
    monkeypatch.setattr(llm, "mode_actuel", lambda: "dev")
    monkeypatch.setattr(anim, "compatibilite", lambda a, m: f"{a}|{m}")
    assert llm.dispatch("anim_compatibilite",
                        {"animation": "/Game/A", "maillage": "/Game/M"}) == "/Game/A|/Game/M"
