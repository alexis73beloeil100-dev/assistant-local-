"""Verifie que ce qui est distribue l'est legalement.

Un manquement ici ne fait rien planter et ne se voit sur aucun ecran : le
logiciel fonctionne parfaitement en etant distribue en infraction. C'est
exactement pour ca que ces verifications doivent etre automatiques -- une
relecture ne les attrape pas, et personne ne pense a les refaire.

Trois obligations reelles :

- OpenRGB (GPLv2) est redistribue : son texte de licence doit l'accompagner ;
- openrgb-python (GPLv3) est IMPORTE par l'assistant, donc lie : le binaire se
  transmet sous GPLv3, et le code source doit accompagner ce binaire ;
- ce que l'installateur annonce doit correspondre a ce qu'il livre.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from outils import source_pour_gpl

RACINE = source_pour_gpl.RACINE


# --- Les textes de licence ---------------------------------------------------

def test_la_licence_du_projet_existe():
    assert (RACINE / "LICENSE").is_file()


def test_le_texte_gplv2_accompagne_openrgb():
    """OpenRGB est redistribue dans outils/OpenRGB : sa licence l'exige."""
    licence = RACINE / "outils" / "OpenRGB" / "LICENSE-GPLv2.txt"
    assert licence.is_file(), "OpenRGB serait redistribue sans sa licence"

    texte = licence.read_text(encoding="utf-8", errors="replace")
    assert "GNU GENERAL PUBLIC LICENSE" in texte
    assert "Version 2, June 1991" in texte
    assert "END OF TERMS AND CONDITIONS" in texte
    assert "gitlab.com/CalcProgrammer1/OpenRGB" in texte, (
        "l'adresse du code source doit figurer")


def test_le_releve_des_licences_tierces_existe_et_nomme_les_copyleft():
    releve = (RACINE / "LICENCES-TIERS.md").read_text(encoding="utf-8")

    for composant in ("openrgb-python", "OpenRGB", "PyInstaller", "pyttsx3"):
        assert composant in releve, f"{composant} n'est pas documente"
    assert "GPLv3" in releve
    assert "GPLv2" in releve


# --- Ce que l'installateur annonce -------------------------------------------

def lire_installateur() -> str:
    return (RACINE / "installateur.iss").read_text(encoding="utf-8")


def test_l_installateur_affiche_une_licence():
    ligne = next((l for l in lire_installateur().splitlines()
                  if l.startswith("LicenseFile=")), None)
    assert ligne, "aucune page de licence a l'installation"

    fichier = RACINE / ligne.split("=", 1)[1].strip()
    assert fichier.is_file(), f"LicenseFile pointe sur un absent : {fichier}"


def test_la_licence_affichee_annonce_la_bonne_licence():
    """Le point qui rend l'annonce exacte.

    Le code ecrit pour ce projet est sous MIT, mais l'assemblage distribue se
    transmet sous GPLv3 : openrgb-python y est integre. Une page annoncant
    "MIT" tout court decrirait autre chose que ce qui est livre.
    """
    texte = (RACINE / "LICENCE-INSTALLATION.txt").read_text(encoding="utf-8")

    assert "GPLv3" in texte
    assert "openrgb-python" in texte
    assert source_pour_gpl.NOM in texte, (
        "la page doit dire ou trouver le code source")


def test_la_promesse_d_absence_de_connexion_est_nuancee():
    """Elle ne doit pas etre absolue : le telechargement des composants en est
    une, et l'annoncer autrement serait faux."""
    texte = (RACINE / "LICENCE-INSTALLATION.txt").read_text(encoding="utf-8")

    assert "telechargement des composants" in texte


# --- L'archive du code source ------------------------------------------------

def test_l_archive_contient_tout_le_code_de_l_assistant(tmp_path):
    """Un module oublie rendrait le source incomplet, donc l'offre invalide."""
    archive = source_pour_gpl.construire(tmp_path / source_pour_gpl.NOM)
    with zipfile.ZipFile(archive) as z:
        noms = set(z.namelist())

    attendus = {p.relative_to(RACINE).as_posix()
                for p in (RACINE / "assistant").rglob("*.py")}
    assert attendus, "aucun module trouve : le test ne verifie rien"
    assert attendus <= noms, f"absents de l'archive : {sorted(attendus - noms)}"


def test_l_archive_contient_de_quoi_reconstruire(tmp_path):
    """Le source correspondant, ce n'est pas seulement les .py : c'est aussi
    ce qui permet de refabriquer le binaire."""
    archive = source_pour_gpl.construire(tmp_path / source_pour_gpl.NOM)
    with zipfile.ZipFile(archive) as z:
        noms = set(z.namelist())

    for indispensable in ("AssistantLocal.spec", "requirements.txt",
                          "reconstruire.py", "installateur.iss", "LICENSE"):
        assert indispensable in noms, f"{indispensable} manque a l'archive"


def test_l_archive_ne_transporte_ni_binaires_ni_environnement(tmp_path):
    """Elle doit rester legere, sinon elle ne sera plus regeneree."""
    archive = source_pour_gpl.construire(tmp_path / source_pour_gpl.NOM)
    with zipfile.ZipFile(archive) as z:
        noms = z.namelist()

    assert not [n for n in noms if n.startswith((".venv/", ".git/", "dist/"))]
    assert not [n for n in noms if n.endswith((".dll", ".exe", ".pyd", ".pyc"))]
    assert archive.stat().st_size < 20 * 1024 * 1024


@pytest.mark.skipif(not (source_pour_gpl.LIVRE).is_dir(),
                    reason="dist/AssistantLocal absent")
def test_le_dossier_livre_emporte_licences_et_source():
    """Ce qui compte n'est pas ce qu'il y a au depot, mais ce qui s'installe.

    Les fichiers sont copies dans dist/ plutot qu'ajoutes au script Inno :
    dist/ doit rester exactement ce qui s'installe, sinon un fichier livre
    echapperait au manifeste et ne serait jamais mis a jour.
    """
    livre = source_pour_gpl.LIVRE
    for nom in ("LICENSE", "LICENCES-TIERS.md", "LICENCE-INSTALLATION.txt",
                source_pour_gpl.NOM):
        assert (livre / nom).is_file(), f"{nom} ne serait pas installe"
