"""Verifie qu'une mise a jour ne livre que ce qui a change, et rien d'autre.

Deux defauts sont possibles ici, et aucun ne se voit a l'oeil nu :

- livrer trop peu -- un fichier modifie oublie, et l'application tourne avec
  un melange de deux versions ;
- livrer trop -- le paquet regrossit vers le gigaoctet et perd sa raison
  d'etre.

Le premier est le plus dangereux : il ne fait rien planter a l'installation.
Il produit une application qui demarre et se comporte mal, sans que rien ne
relie le symptome a la mise a jour.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from outils import manifeste, paquet_maj


def dossier_avec(racine: Path, contenus: dict[str, bytes]) -> Path:
    for relatif, octets in contenus.items():
        chemin = racine / relatif
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_bytes(octets)
    return racine


# --- Le manifeste ------------------------------------------------------------

def test_le_manifeste_releve_chaque_fichier(tmp_path):
    dossier_avec(tmp_path, {
        "AssistantLocal.exe": b"binaire",
        "_internal/assistant/gui.pyc": b"code",
        "_internal/nvidia/cublas.dll": b"x" * 5000,
    })
    releve = manifeste.construire(tmp_path, version="1.0.0")

    assert set(releve["fichiers"]) == {
        "AssistantLocal.exe",
        "_internal/assistant/gui.pyc",
        "_internal/nvidia/cublas.dll",
    }
    assert releve["fichiers"]["_internal/nvidia/cublas.dll"]["taille"] == 5000
    assert releve["version"] == "1.0.0"


def test_les_chemins_du_manifeste_sont_en_barres_obliques(tmp_path):
    """Un manifeste doit rester comparable d'une machine a l'autre.

    Les chemins Windows en barres inversees rendraient chaque comparaison
    fausse des qu'un manifeste voyage.
    """
    dossier_avec(tmp_path, {"_internal/assistant/gui.pyc": b"code"})
    releve = manifeste.construire(tmp_path)

    assert all("\\" not in nom for nom in releve["fichiers"])


def test_deux_dossiers_identiques_ne_donnent_aucun_ecart(tmp_path):
    contenus = {"a.exe": b"un", "sous/b.dll": b"deux"}
    un = dossier_avec(tmp_path / "un", contenus)
    deux = dossier_avec(tmp_path / "deux", contenus)

    ecart = manifeste.differences(manifeste.construire(un),
                                  manifeste.construire(deux))

    assert ecart["ajoutes"] == []
    assert ecart["modifies"] == []
    assert ecart["supprimes"] == []
    assert ecart["poids_livre"] == 0


def test_un_contenu_change_a_taille_egale_est_detecte(tmp_path):
    """Le piege que la date et la taille ne voient pas.

    PyInstaller reecrit tout dist/ a chaque construction : les dates ne
    servent a rien. Et un correctif d'un caractere ne change pas la taille.
    Seule l'empreinte du contenu distingue les deux.
    """
    un = dossier_avec(tmp_path / "un", {"gui.pyc": b"version_A"})
    deux = dossier_avec(tmp_path / "deux", {"gui.pyc": b"version_B"})

    ecart = manifeste.differences(manifeste.construire(un),
                                  manifeste.construire(deux))

    assert ecart["modifies"] == ["gui.pyc"]
    assert ecart["ajoutes"] == []


def test_un_fichier_retire_apparait_en_supprime(tmp_path):
    un = dossier_avec(tmp_path / "un", {"a.exe": b"x", "vieux.pyc": b"y"})
    deux = dossier_avec(tmp_path / "deux", {"a.exe": b"x"})

    ecart = manifeste.differences(manifeste.construire(un),
                                  manifeste.construire(deux))

    assert ecart["supprimes"] == ["vieux.pyc"]
    assert ecart["inchanges"] == ["a.exe"]


def test_le_poids_livre_ne_compte_que_ce_qui_change(tmp_path):
    """La raison d'etre du mecanisme, en un chiffre."""
    un = dossier_avec(tmp_path / "un", {
        "petit.exe": b"a" * 100, "enorme.dll": b"z" * 100_000})
    deux = dossier_avec(tmp_path / "deux", {
        "petit.exe": b"b" * 100, "enorme.dll": b"z" * 100_000})

    ecart = manifeste.differences(manifeste.construire(un),
                                  manifeste.construire(deux))

    assert ecart["poids_livre"] == 100
    assert ecart["poids_total"] == 100_100


# --- Le script Inno genere ---------------------------------------------------

def ecart_fictif(ajoutes=(), modifies=(), supprimes=()) -> dict:
    return {
        "ajoutes": list(ajoutes), "modifies": list(modifies),
        "supprimes": list(supprimes), "inchanges": [],
        "poids_livre": 1024, "poids_total": 2048,
    }


def test_le_script_ne_contient_que_ce_qui_change():
    ecart = ecart_fictif(modifies=["AssistantLocal.exe"],
                         ajoutes=["_internal/assistant/maj.pyc"])
    genere = paquet_maj.script("1.0.1", "1.0.2", ecart)

    assert "AssistantLocal.exe" in genere
    assert "maj.pyc" in genere
    # Le coeur du sujet : rien qui ressemble a une livraison complete.
    assert "recursesubdirs" not in genere
    assert 'Source: "dist\\AssistantLocal\\*"' not in genere


def test_le_script_place_chaque_fichier_dans_son_sous_dossier():
    genere = paquet_maj.script(
        "1.0.1", "1.0.2", ecart_fictif(modifies=["_internal/assistant/gui.pyc"]))

    assert ('Source: "dist\\AssistantLocal\\_internal\\assistant\\gui.pyc"; '
            'DestDir: "{app}\\_internal\\assistant"') in genere


def test_un_fichier_de_la_racine_va_a_la_racine():
    """Path('a.exe').parent vaut '.', qui ne doit pas finir dans le chemin."""
    genere = paquet_maj.script(
        "1.0.1", "1.0.2", ecart_fictif(modifies=["AssistantLocal.exe"]))

    assert 'DestDir: "{app}"' in genere
    assert "{app}\\." not in genere


def test_les_fichiers_disparus_sont_effaces():
    genere = paquet_maj.script(
        "1.0.1", "1.0.2", ecart_fictif(supprimes=["_internal/vieux.pyc"]))

    assert "[InstallDelete]" in genere
    assert 'Name: "{app}\\_internal\\vieux.pyc"' in genere


def test_sans_suppression_le_bloc_installdelete_est_absent():
    """Un [InstallDelete] vide fait echouer la compilation."""
    genere = paquet_maj.script("1.0.1", "1.0.2",
                               ecart_fictif(modifies=["a.exe"]))

    assert "[InstallDelete]" not in genere


def test_chaque_fichier_est_marque_ignoreversion():
    """Sans ce drapeau, Inno refuse d'ecraser une DLL dont le numero de
    version n'a pas bouge -- ce qui est le cas de toutes les notres."""
    genere = paquet_maj.script("1.0.1", "1.0.2",
                               ecart_fictif(modifies=["a.dll", "b.dll"]))

    assert genere.count("Flags: ignoreversion") == 2


# --- Les garde-fous ----------------------------------------------------------

def test_le_paquet_porte_le_meme_identifiant_que_l_installateur_complet():
    """Le point qui decide si c'est une mise a jour ou un second logiciel.

    Avec un AppId different, Windows afficherait deux "Assistant local" dans
    les applications installees, et la desinstallation de l'un laisserait
    l'autre derriere.
    """
    complet = (Path(paquet_maj.RACINE) / "installateur.iss").read_text(
        encoding="utf-8")
    ligne = next(l for l in complet.splitlines() if l.startswith("AppId="))
    genere = paquet_maj.script("1.0.1", "1.0.2", ecart_fictif(modifies=["a"]))

    assert ligne in genere.splitlines()


def test_la_cle_de_registre_cherchee_n_a_pas_d_accolade_en_trop():
    """Le defaut qui aurait fait refuser toutes les mises a jour.

    SetupSetting("AppId") rend la valeur telle qu'ecrite dans [Setup],
    accolade doublee comprise. La cle aurait porte '{{...}' au lieu de
    '{...}', la lecture du registre n'aurait jamais rien trouve, et la garde
    aurait conclu que l'application n'etait pas installee.
    """
    genere = paquet_maj.script("1.0.1", "1.0.2", ecart_fictif(modifies=["a"]))
    cle = next(l for l in genere.splitlines() if "_is1'" in l)

    assert f"{{{paquet_maj.APP_ID}}}_is1" in cle
    assert "{{" not in cle
    assert "@APP_ID@" not in genere


def test_le_script_refuse_une_machine_sans_installation():
    genere = paquet_maj.script("1.0.1", "1.0.2", ecart_fictif(modifies=["a"]))

    assert "function InitializeSetup" in genere
    assert "n''est pas installe sur cette machine" in genere
    assert "Result := False" in genere


def test_le_script_annonce_sa_version_de_depart_et_d_arrivee():
    genere = paquet_maj.script("1.0.1", "1.0.2", ecart_fictif(modifies=["a"]))

    assert '#define MaVersion "1.0.2"' in genere
    assert '#define VersionAttendue "1.0.1"' in genere


def test_partir_de_la_version_courante_est_refuse(capsys):
    """Une mise a jour va d'une version a une autre."""
    from assistant import __version__

    assert paquet_maj.construire(__version__) == 1
    assert "toujours la" in capsys.readouterr().out


def test_partir_d_une_version_sans_manifeste_est_refuse(capsys):
    assert paquet_maj.construire("0.0.1-inexistante") == 1
    assert "aucun manifeste" in capsys.readouterr().out


# --- La preuve de bout en bout -----------------------------------------------

def test_le_manifeste_de_la_version_publiee_est_versionne():
    """Sans lui, la premiere mise a jour n'a aucune reference de depart.

    C'est le fichier qu'on oublie de committer, et on ne s'en apercoit qu'au
    moment de publier un correctif -- quand il est trop tard, puisque la
    version publiee n'existe plus nulle part.
    """
    from assistant import __version__

    reference = manifeste.MANIFESTES / f"{__version__}.json"
    assert reference.exists(), (
        f"manifeste manquant pour la version publiee {__version__} : "
        "lance outils/manifeste.py")

    releve = manifeste.lire(reference)
    assert releve["version"] == __version__
    assert len(releve["fichiers"]) > 1000


@pytest.mark.skipif(not paquet_maj.ISCC.exists(),
                    reason="Inno Setup absent de cette machine")
def test_le_script_genere_compile_vraiment(tmp_path):
    """Le seul test qui prouve que le paquet existe.

    Tout le reste verifie du texte. Ici, Inno Setup lit reellement le script,
    trouve les fichiers, compile le Pascal et produit un executable. Une
    erreur de syntaxe dans le bloc [Code] ne se voit qu'ici.
    """
    livre = paquet_maj.LIVRE
    if not livre.is_dir():
        pytest.skip("dist/AssistantLocal absent : rien a empaqueter")

    # Deux vrais petits fichiers du bundle : le script doit les retrouver.
    petits = sorted(
        (f.relative_to(livre).as_posix()
         for f in livre.rglob("*") if f.is_file() and f.stat().st_size < 40_000),
        key=len)[:2]
    if len(petits) < 2:
        pytest.skip("pas assez de petits fichiers pour un essai")

    genere = paquet_maj.script("1.0.1", "9.9.9", ecart_fictif(modifies=petits))
    # OutputDir est relatif a SourceDir : on le rend absolu pour ne rien
    # deposer dans installateur/ pendant une execution de tests.
    genere = genere.replace("OutputDir=installateur",
                            f"OutputDir={tmp_path}")
    script = tmp_path / "essai.iss"
    script.write_text(genere, encoding="utf-8")

    resultat = subprocess.run(
        [str(paquet_maj.ISCC), str(script)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(paquet_maj.RACINE), timeout=180)

    assert resultat.returncode == 0, (
        "Inno Setup a refuse le script :\n"
        + "\n".join((resultat.stdout + resultat.stderr).splitlines()[-20:]))

    produit = tmp_path / "MiseAJour_AssistantLocal_9.9.9.exe"
    assert produit.exists(), "aucun paquet produit"
    # Deux fichiers de moins de 40 Ko : le paquet doit rester minuscule
    # devant les 1,15 Go de l'installateur complet.
    assert produit.stat().st_size < 5_000_000, (
        f"paquet anormalement gros : {produit.stat().st_size} octets")
