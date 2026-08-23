"""Verifie que ce qui est distribue l'est legalement.

Un manquement ici ne fait rien planter et ne se voit sur aucun ecran : le
logiciel fonctionne parfaitement en etant distribue en infraction. C'est
exactement pour ca que ces verifications doivent etre automatiques -- une
relecture ne les attrape pas, et personne ne pense a les refaire.

Quatre obligations reelles :

- OpenRGB (GPLv2) n'est PLUS redistribue : ni le depot ni le paquet ne
  doivent le contenir, sinon son texte de licence redeviendrait du : la
  regle du .spec est facile a elargir sans y penser ;
- openrgb-python (GPLv3) n'est PLUS importe depuis le 23/08/2026 : plus aucun
  composant integre n'impose sa licence a l'assemblage, et le binaire n'a plus
  a etre accompagne de son source ;
- ce que l'installateur annonce doit correspondre a ce qu'il livre ;
- et il doit RETIRER ce qu'il ne livre plus : Inno Setup ecrase, il n'efface
  pas, donc un retrait qui ne vaut que pour les installations neuves ne vaut
  pour personne.
"""
from __future__ import annotations

from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
LIVRE = RACINE / "dist" / "AssistantLocal"


# --- Les textes de licence ---------------------------------------------------

def test_la_licence_du_projet_existe():
    assert (RACINE / "LICENSE").is_file()


def test_openrgb_n_est_pas_redistribue():
    """L'application ne transporte plus le binaire d'OpenRGB.

    La regle du .spec balaie outils/ en entier : il suffit qu'on retire
    l'exclusion, ou qu'on renomme le dossier, pour se remettre a distribuer
    OpenRGB sans s'en apercevoir -- et l'obligation GPLv2 reviendrait avec,
    en silence, puisque rien ne planterait.

    Une copie portable posee a la main dans outils/OpenRGB/ reste permise :
    elle sert a CETTE machine et ne part nulle part. Ce qui est verifie ici,
    c'est le PAQUET.
    """
    livre = RACINE / "dist" / "AssistantLocal" / "_internal" / "outils"
    if not livre.is_dir():
        return          # rien a verifier tant que l'application n'est pas construite

    intrus = [str(f.relative_to(livre)) for f in livre.rglob("*")
              if f.is_file() and "openrgb" in str(f.relative_to(livre)).lower()]
    assert not intrus, (
        f"OpenRGB est reparti dans le paquet : {intrus}. L'obligation GPLv2 "
        "revient avec, et personne ne le verra")


def test_le_depot_ne_suit_aucun_fichier_openrgb():
    """Meme raison, cote depot : un `git add -f` malheureux suffirait."""
    import subprocess

    suivis = subprocess.run(
        ["git", "ls-files", "outils/OpenRGB"], cwd=RACINE,
        capture_output=True, text=True).stdout.split()
    assert not suivis, f"le depot suit a nouveau OpenRGB : {suivis}"


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

    Elle a ete fausse dans les deux sens. Elle annoncait MIT alors que
    openrgb-python imposait la GPLv3 a tout l'assemblage ; elle annoncerait
    maintenant la GPLv3 alors que plus rien ne l'impose. Une page de licence
    qui decrit autre chose que ce qui est livre ne protege personne.
    """
    texte = (RACINE / "LICENCE-INSTALLATION.txt").read_text(encoding="utf-8")

    assert "distribue sous licence MIT" in texte
    assert "assistant-local-source.zip" not in texte, (
        "la page promet un code source qui n'est plus livre")


def test_la_promesse_d_absence_de_connexion_est_nuancee():
    """Elle ne doit pas etre absolue : le telechargement des composants en est
    une, et l'annoncer autrement serait faux."""
    texte = (RACINE / "LICENCE-INSTALLATION.txt").read_text(encoding="utf-8")

    assert "telechargement des composants" in texte


def section_de_l_installateur(nom: str) -> list[str]:
    """Les lignes utiles d'une section du script Inno, commentaires exclus.

    On decoupe par section plutot que de chercher dans tout le fichier : les
    memes lignes rangees sous [UninstallDelete] n'effaceraient rien a
    l'installation, et une recherche de texte brut n'y verrait que du feu.
    """
    lignes: list[str] = []
    dedans = False
    for ligne in lire_installateur().splitlines():
        nue = ligne.strip()
        if nue.startswith("[") and nue.endswith("]"):
            dedans = nue.lower() == f"[{nom.lower()}]"
        elif dedans and nue and not nue.startswith(";"):
            lignes.append(nue)
    return lignes


def test_l_installateur_complet_laisse_les_restes_de_l_ancienne_version():
    """Une installation mise a jour n'etait pas identique a une neuve.

    Inno Setup n'efface pas ce qui a disparu du paquet : il ajoute et il
    ecrase, rien de plus. Le 23/08/2026, un dossier passe de 1.0.1 a 1.0.2
    par l'installateur complet contenait encore 44 fichiers absents de
    manifestes/1.0.2.json : OpenRGB.exe avec son LICENSE-GPLv2.txt,
    openrgb-python en entier, l'archive du source.

    Rien ne le signalait, et l'application s'en servait : rgb.py cherche une
    copie portable dans outils/OpenRGB/, la trouvait dans le dossier
    installe, et l'eclairage marchait. Le retrait du GPL n'avait donc eu lieu
    que pour les installations neuves.

    La mise a jour differentielle sait deja les supprimer -- elle part du
    manifeste. Ce test protege l'autre chemin, celui qui l'ignorait.
    """
    efface = section_de_l_installateur("InstallDelete")
    assert efface, "l'installateur complet n'efface plus rien avant d'installer"

    for cible, genre in (
            (r"{app}\_internal\outils\OpenRGB", "filesandordirs"),
            (r"{app}\_internal\openrgb", "filesandordirs"),
            (r"{app}\_internal\openrgb_python-*.dist-info", "filesandordirs"),
            (r"{app}\assistant-local-source.zip", "files"),
    ):
        ligne = next((l for l in efface if f'Name: "{cible}"' in l), None)
        assert ligne, (
            f"{cible} survivrait a une mise a jour par l'installateur complet")
        assert f"Type: {genre}" in ligne, (
            f"{cible} : attendu 'Type: {genre}', trouve {ligne!r}. Un dossier "
            "laisse tout son contenu si le type n'est pas filesandordirs")


# --- Ce qui est livre --------------------------------------------------------

def test_le_source_n_est_plus_joint_au_binaire():
    """L'archive du source n'existait que pour tenir l'obligation GPLv3.

    Elle est partie avec elle. La laisser serait pire qu'inutile : le code de
    l'auteur repartirait chez chaque personne qui installe, sans que rien ne
    l'exige plus -- et sans que personne s'en apercoive, puisque le programme
    marcherait exactement pareil.
    """
    assert not (RACINE / "outils" / "source_pour_gpl.py").exists(), (
        "le generateur d'archive est revenu")

    if not LIVRE.is_dir():
        return          # rien a verifier tant que l'application n'est pas construite

    archives = [f.name for f in LIVRE.glob("*source*.zip")]
    assert not archives, f"le source est de nouveau livre : {archives}"


def test_la_bibliotheque_gpl_n_est_pas_livree():
    """Ne pas l'importer ne suffit pas : il faut ne pas la LIVRER.

    Le .spec la forcait en import cache et la collectait en entier, du temps
    ou rgb.py l'importait dans ses fonctions. Retirer l'import de rgb.py a
    donc laisse openrgb-python dans le paquet : le code n'y etait plus lie,
    mais l'application redistribuait toujours une bibliotheque GPLv3.

    Elle reste installee dans le .venv, donc PyInstaller peut la reprendre
    des qu'un import la rend visible. C'est ce test qui s'en apercevrait.
    """
    if not LIVRE.is_dir():
        return          # rien a verifier tant que l'application n'est pas construite

    intrus = [str(f.relative_to(LIVRE))
              for f in (LIVRE / "_internal").glob("openrgb*")]
    assert not intrus, (
        f"openrgb-python (GPLv3) est livre avec l'application : {intrus}")


def test_le_dossier_livre_emporte_les_licences():
    """Ce qui compte n'est pas ce qu'il y a au depot, mais ce qui s'installe.

    Les fichiers sont copies dans dist/ plutot qu'ajoutes au script Inno :
    dist/ doit rester exactement ce qui s'installe, sinon un fichier livre
    echapperait au manifeste et ne serait jamais mis a jour.
    """
    if not LIVRE.is_dir():
        return

    for nom in ("LICENSE", "LICENCES-TIERS.md", "LICENCE-INSTALLATION.txt"):
        assert (LIVRE / nom).is_file(), f"{nom} ne serait pas installe"
