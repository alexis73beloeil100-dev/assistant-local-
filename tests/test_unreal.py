"""Atelier Unreal, etape 1 : projet, moteur, compilation, journaux, plantages.

Sans Unreal installe : chaque test fabrique l'arborescence qu'il lit, au
format que l'editeur et ses outils ecrivent reellement.
"""
from __future__ import annotations

import json
from pathlib import Path, PureWindowsPath

import pytest

from assistant.skills import unreal


@pytest.fixture
def reglages(monkeypatch):
    memoire: dict = {}
    monkeypatch.setattr(unreal.settings, "get",
                        lambda k, d=None: memoire.get(k, d))
    monkeypatch.setattr(unreal.settings, "set",
                        lambda k, v: memoire.__setitem__(k, v))
    return memoire


def faux_projet(racine: Path, nom: str = "Tireur", association: str = "5.4",
                cpp: bool = True) -> Path:
    projet = racine / nom
    (projet / "Source" / nom).mkdir(parents=True)
    uproject = projet / f"{nom}.uproject"
    uproject.write_text(json.dumps({
        "FileVersion": 3,
        "EngineAssociation": association,
        "Modules": [{"Name": nom, "Type": "Runtime"}] if cpp else [],
        "Plugins": [{"Name": "EnhancedInput", "Enabled": True},
                    {"Name": "Water", "Enabled": False}],
    }), encoding="utf-8")
    if cpp:
        source = projet / "Source"
        (source / f"{nom}.Target.cs").write_text("// cible jeu", encoding="utf-8")
        (source / f"{nom}Editor.Target.cs").write_text("// cible editeur",
                                                      encoding="utf-8")
        (source / nom / "Arme.h").write_text(
            "#pragma once\nUCLASS()\nclass TIREUR_API UArmeComponent : "
            "public UActorComponent\n{\n};\n", encoding="utf-8")
        (source / nom / "Arme.cpp").write_text("#include \"Arme.h\"\n",
                                               encoding="utf-8")
    return uproject


# --- Projet ---------------------------------------------------------------------

def test_les_deux_formats_des_projets_recents_sont_lus():
    ini = (
        "[/Script/UnrealEd.EditorSettings]\n"
        'RecentlyOpenedProjectFiles=(ProjectName="D:/Jeux/Tireur/Tireur.uproject",'
        "LastOpenTime=2026.10.30-18.02.11)\n"
        "RecentlyOpenedProjectFiles=C:/Ancien/Ancien.uproject\n"
        "CreatedProjectPaths=C:/Users/x/Documents/Unreal Projects\n"
    )
    assert unreal.lire_projets_recents(ini) == [
        ("D:/Jeux/Tireur/Tireur.uproject", "2026.10.30-18.02.11"),
        ("C:/Ancien/Ancien.uproject", ""),
    ]


def test_les_projets_recents_sont_tries_et_sans_disparus(tmp_path, monkeypatch):
    a = faux_projet(tmp_path, "Ancien")
    b = faux_projet(tmp_path, "Recent")
    reglages_54 = tmp_path / "UE" / "5.4" / "Saved" / "Config" / "WindowsEditor"
    reglages_55 = tmp_path / "UE" / "5.5" / "Saved" / "Config" / "WindowsEditor"
    for d in (reglages_54, reglages_55):
        d.mkdir(parents=True)
    (reglages_54 / "EditorSettings.ini").write_text(
        f'RecentlyOpenedProjectFiles=(ProjectName="{a.as_posix()}",'
        "LastOpenTime=2026.01.01-10.00.00)\n"
        'RecentlyOpenedProjectFiles=(ProjectName="Z:/Disparu/X.uproject",'
        "LastOpenTime=2026.12.01-10.00.00)\n", encoding="utf-8")
    (reglages_55 / "EditorSettings.ini").write_text(
        f'RecentlyOpenedProjectFiles=(ProjectName="{b.as_posix()}",'
        "LastOpenTime=2026.10.30-18.02.11)\n", encoding="utf-8")
    monkeypatch.setattr(unreal, "_dossiers_reglages_editeur",
                        lambda: [reglages_54, reglages_55])

    assert unreal.projets_recents() == [b, a]


def test_choisir_un_dossier_trouve_son_uproject(tmp_path, reglages):
    uproject = faux_projet(tmp_path)
    assert "Projet retenu : Tireur" in unreal.choisir_projet(str(uproject.parent))
    assert unreal.projet_actuel() == uproject
    assert "n'est pas un projet" in unreal.choisir_projet(str(tmp_path / "x.txt"))


def test_le_resume_nomme_moteur_modules_cibles_et_classes(tmp_path, reglages,
                                                          monkeypatch):
    uproject = faux_projet(tmp_path)
    unreal.choisir_projet(str(uproject))
    moteur = tmp_path / "UE_5.4"
    monkeypatch.setattr(unreal, "dossier_moteur", lambda _p, _a: moteur)

    resume = unreal.resume_projet()
    assert "Unreal Engine 5.4" in resume and str(moteur) in resume
    assert "Modules  Tireur" in resume
    assert "TireurEditor" in resume
    assert "EnhancedInput" in resume and "Water" not in resume
    assert "UArmeComponent" in resume
    assert "2 fichier(s)" in resume


# --- Moteur ----------------------------------------------------------------------

def test_le_moteur_installe_est_trouve_par_le_registre(tmp_path, monkeypatch):
    moteur = tmp_path / "UE_5.4"
    moteur.mkdir()
    monkeypatch.setattr(unreal, "_registre", lambda racine, cle: (
        {"InstalledDirectory": str(moteur)}
        if racine == "HKLM" and cle.endswith(r"Unreal Engine\5.4") else {}))
    assert unreal.dossier_moteur(tmp_path / "p.uproject", "5.4") == moteur


def test_a_defaut_de_registre_le_launcher_suffit(tmp_path, monkeypatch):
    moteur = tmp_path / "UE_5.5"
    moteur.mkdir()
    monkeypatch.setattr(unreal, "_registre", lambda *_a: {})
    monkeypatch.setattr(unreal, "_launcher_installes", lambda: {"5.5": moteur})
    assert unreal.dossier_moteur(tmp_path / "p.uproject", "5.5") == moteur


def test_un_moteur_compile_est_trouve_par_son_identifiant(tmp_path, monkeypatch):
    moteur = tmp_path / "UnrealEngine-source"
    moteur.mkdir()
    guid = "{9A1B2C3D-0000-1111-2222-333344445555}"
    monkeypatch.setattr(unreal, "_registre", lambda racine, cle: (
        {guid: str(moteur)} if racine == "HKCU" else {}))
    assert unreal.dossier_moteur(tmp_path / "p.uproject", guid) == moteur


def test_une_version_absente_le_dit(tmp_path, monkeypatch):
    monkeypatch.setattr(unreal, "_registre", lambda *_a: {})
    monkeypatch.setattr(unreal, "_launcher_installes", lambda: {})
    with pytest.raises(unreal.Echec, match="5.6 n'est pas installe"):
        unreal.dossier_moteur(tmp_path / "p.uproject", "5.6")


def test_la_liste_du_launcher_est_lue(tmp_path, monkeypatch):
    epic = tmp_path / "Epic" / "UnrealEngineLauncher"
    epic.mkdir(parents=True)
    (epic / "LauncherInstalled.dat").write_text(json.dumps({"InstallationList": [
        {"InstallLocation": "C:\\Program Files\\Epic Games\\UE_5.4",
         "AppName": "UE_5.4", "AppVersion": "5.4.4-35576357+++UE5+Release-5.4"},
        {"InstallLocation": "D:\\Fortnite", "AppName": "Fortnite"},
    ]}), encoding="utf-8")
    monkeypatch.setenv("ProgramData", str(tmp_path))
    assert unreal._launcher_installes() == {
        "5.4": Path("C:\\Program Files\\Epic Games\\UE_5.4")}


# --- Compilation -------------------------------------------------------------------

SORTIE_ECHEC = r"""Using bundled DotNet SDK version: 8.0.300
Running UnrealBuildTool: dotnet "..\..\Engine\Binaries\DotNET\UnrealBuildTool\UnrealBuildTool.dll" TireurEditor Win64 Development -Project="D:\Jeux\Tireur\Tireur.uproject" -WaitMutex -FromMsBuild
D:\Jeux\Tireur\Source\Tireur\Arme.h(14): Error: Missing ';' in 'variable declaration'
[3/6] Compile [x64] Arme.cpp
D:\Jeux\Tireur\Source\Tireur\Arme.cpp(42): error C2065: 'Munitions': undeclared identifier
D:\Jeux\Tireur\Source\Tireur\Arme.cpp(42): error C2065: 'Munitions': undeclared identifier
D:\Jeux\Tireur\Source\Tireur\Arme.cpp(57,9): warning C4996: 'FOo::Ancienne': Please use Nouvelle instead
Arme.cpp.obj : error LNK2019: unresolved external symbol "public: void __cdecl UArmeComponent::Tirer(void)"
D:\Jeux\Tireur\Binaries\Win64\UnrealEditor-Tireur.dll : fatal error LNK1120: 1 unresolved externals
Result: Failed (OtherCompilationError)
Total execution time: 12.41 seconds
"""


def test_les_erreurs_de_compilation_sont_toutes_retrouvees_avec_leur_ligne():
    diagnostics = unreal.analyser_sortie(SORTIE_ECHEC)
    erreurs = [d for d in diagnostics if d.genre == "erreur"]
    avertissements = [d for d in diagnostics if d.genre == "avertissement"]

    assert [(PureWindowsPath(d.fichier).name, d.ligne, d.code) for d in erreurs] == [
        ("Arme.h", 14, ""), ("Arme.cpp", 42, "C2065"),
        ("Arme.cpp.obj", 0, "LNK2019"), ("UnrealEditor-Tireur.dll", 0, "LNK1120"),
    ], "doublon retire, et les erreurs d'edition de liens comptent aussi"
    assert erreurs[0].message == "Missing ';' in 'variable declaration'"
    assert [(d.ligne, d.code) for d in avertissements] == [(57, "C4996")]


def test_le_compte_rendu_dit_echec_et_nomme_les_erreurs():
    texte = unreal.compte_rendu("Tireur", 6, SORTIE_ECHEC, 12.4)
    assert texte.startswith("Compilation de Tireur : ECHEC en 12 s -- "
                            "4 erreur(s), 1 avertissement(s).")
    assert "Arme.cpp(42): C2065 'Munitions': undeclared identifier" in texte


def test_une_compilation_reussie_le_dit():
    sortie = "Building TireurEditor...\n[1/1] Link UnrealEditor-Tireur.dll\nResult: Succeeded\n"
    assert "REUSSIE" in unreal.compte_rendu("Tireur", 0, sortie, 3)


def test_l_editeur_ouvert_avec_live_coding_est_explique():
    sortie = ("Unable to build while Live Coding is active. Exit the editor and "
              "game, or press Ctrl+Alt+F11 if iterating on code in the editor")
    assert "Ctrl+Alt+F11" in unreal.compte_rendu("Tireur", 6, sortie, 1)


def test_un_echec_sans_erreur_reconnue_montre_la_fin_de_la_sortie():
    sortie = "ligne 1\nERROR: Unable to find target 'TireurEditor'\nResult: Failed\n"
    texte = unreal.compte_rendu("Tireur", 6, sortie, 1)
    assert "Unable to find target" in texte


def test_la_commande_vise_la_cible_editor_du_projet(tmp_path):
    uproject = faux_projet(tmp_path)
    moteur = tmp_path / "UE_5.4"
    build = moteur / "Engine" / "Build" / "BatchFiles" / "Build.bat"
    build.parent.mkdir(parents=True)
    build.write_text("@echo off", encoding="utf-8")

    commande = unreal.commande_compilation(unreal.analyser(uproject), moteur,
                                           "Development")
    assert commande == [str(build), "TireurEditor", "Win64", "Development",
                        f"-Project={uproject}", "-WaitMutex", "-FromMsBuild"]


def test_un_projet_blueprint_n_a_rien_a_compiler(tmp_path):
    uproject = faux_projet(tmp_path, cpp=False)
    with pytest.raises(unreal.Echec, match="projet Blueprint"):
        unreal.commande_compilation(unreal.analyser(uproject), tmp_path, "Development")


def test_compiler_passe_par_le_garde_fou_et_le_journal(tmp_path, reglages,
                                                       monkeypatch):
    uproject = faux_projet(tmp_path)
    unreal.choisir_projet(str(uproject))
    moteur = tmp_path / "UE_5.4"
    build = moteur / "Engine" / "Build" / "BatchFiles" / "Build.bat"
    build.parent.mkdir(parents=True)
    build.write_text("@echo off", encoding="utf-8")
    monkeypatch.setattr(unreal, "dossier_moteur", lambda _p, _a: moteur)

    gardes = []
    monkeypatch.setattr(unreal.safety, "guard",
                        lambda action, ask=None: gardes.append(action) or True)

    class Fini:
        returncode, stdout, stderr = 0, "Result: Succeeded", ""

    lances = []
    monkeypatch.setattr(unreal.subprocess, "run",
                        lambda cmd, **kw: lances.append((cmd, kw)) or Fini())
    texte = unreal.compiler()

    assert "REUSSIE" in texte
    assert gardes and gardes[0].kind == "compilation" and gardes[0].routine
    assert lances[0][1]["creationflags"] == unreal.CREATE_NO_WINDOW


# --- Journaux et plantages ---------------------------------------------------------

def test_le_journal_ne_garde_que_erreurs_et_avertissements(tmp_path, reglages):
    uproject = faux_projet(tmp_path)
    unreal.choisir_projet(str(uproject))
    logs = uproject.parent / "Saved" / "Logs"
    logs.mkdir(parents=True)
    (logs / "Tireur.log").write_text(
        "[2026.11.02-07.00.00:000][  0]LogInit: Display: Running engine\n"
        "[2026.11.02-07.00.01:000][  1]LogBlueprint: Warning: Variable inutilisee\n"
        "[2026.11.02-07.00.02:000][  2]LogScript: Error: Accessed None trying to read Arme\n"
        "[2026.11.02-07.00.03:000][  3]LogTemp: tout va bien\n", encoding="utf-8")

    texte = unreal.journaux()
    assert "4 lignes, 1 erreur(s), 1 avertissement(s)" in texte
    assert "Accessed None" in texte and "Running engine" not in texte


CRASH = """<?xml version="1.0" encoding="UTF-8"?>
<FGenericCrashContext>
  <RuntimeProperties>
    <ErrorMessage>Unhandled Exception: EXCEPTION_ACCESS_VIOLATION reading address 0x0000000000000058</ErrorMessage>
    <CallStack>UnrealEditor_Tireur!UArmeComponent::Tirer() [D:\\Jeux\\Tireur\\Source\\Tireur\\Arme.cpp:88]
UnrealEditor_Engine!UActorComponent::TickComponent()
UnrealEditor_Core!FTickTaskManager::RunTickGroup()</CallStack>
  </RuntimeProperties>
</FGenericCrashContext>
"""


def test_le_plantage_donne_le_message_et_signale_le_code_du_projet(tmp_path,
                                                                   reglages):
    uproject = faux_projet(tmp_path)
    unreal.choisir_projet(str(uproject))
    rapport = uproject.parent / "Saved" / "Crashes" / "UECC-Windows-1234"
    rapport.mkdir(parents=True)
    (rapport / "CrashContext.runtime-xml").write_text(CRASH, encoding="utf-8")

    texte = unreal.dernier_plantage()
    assert "EXCEPTION_ACCESS_VIOLATION" in texte
    assert ">> UnrealEditor_Tireur!UArmeComponent::Tirer() [D:\\Jeux\\Tireur\\Source\\Tireur\\Arme.cpp:88]" in texte
    assert "   UnrealEditor_Engine!UActorComponent::TickComponent()" in texte


def test_sans_projet_choisi_il_propose_les_recents(tmp_path, reglages,
                                                   monkeypatch):
    a, b = faux_projet(tmp_path, "A"), faux_projet(tmp_path, "B")
    monkeypatch.setattr(unreal, "projets_recents", lambda: [a, b])
    texte = unreal.resume_projet()
    assert "Aucun projet choisi" in texte and str(a) in texte

    monkeypatch.setattr(unreal, "projets_recents", lambda: [a])
    unreal.resume_projet()
    assert unreal.projet_actuel() == a, "un seul projet recent : il est pris"
