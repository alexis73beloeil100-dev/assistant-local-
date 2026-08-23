"""Prepare le dossier du Bureau qu'on envoie a quelqu'un.

    .venv\\Scripts\\python.exe outils\\dossier_a_envoyer.py

Il contient l'installateur, son empreinte, et un LISEZ-MOI ecrit pour
quelqu'un qui ne connait pas le projet.

L'empreinte est recalculee ICI, sur la COPIE posee dans le dossier -- pas
recopiee depuis la sortie de publier.py. La difference compte : si la copie
echoue a moitie, une empreinte reprise de l'original certifierait un fichier
tronque, et la verification passerait pour bonne chez qui le recoit. C'est
exactement la garantie que le LISEZ-MOI promet.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

INSTALLATEUR = RACINE / "installateur" / "Installer_AssistantLocal.exe"
BUREAU = Path.home() / "Desktop"


def empreinte(chemin: Path) -> str:
    """SHA-256 lu par blocs : le fichier pese plus d'un gigaoctet."""
    sha = hashlib.sha256()
    with chemin.open("rb") as f:
        for bloc in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(bloc)
    return sha.hexdigest()


def lisez_moi(version: str, sha: str, taille_go: float) -> str:
    return f"""ASSISTANT LOCAL {version}
{'=' * (16 + len(version))}

Un assistant qui connait votre PC et agit dessus, en francais, a la voix ou au
texte. Tout tourne sur votre machine : rien ne part sur Internet.


CE QUE VOUS AVEZ RECU
---------------------

    Installer_AssistantLocal.exe          l'installateur ({taille_go:.1f} Go)
    Installer_AssistantLocal.exe.sha256   son empreinte, pour le verifier


VERIFIER LE FICHIER AVANT DE L'OUVRIR
-------------------------------------

Ouvrez PowerShell dans ce dossier et lancez :

    Get-FileHash Installer_AssistantLocal.exe -Algorithm SHA256

Le resultat doit etre exactement :

    {sha}

S'il differe, n'installez pas : le fichier est incomplet ou a ete modifie en
chemin. Redemandez-le.


WINDOWS VA AFFICHER UN AVERTISSEMENT
------------------------------------

Un ecran bleu << Windows a protege votre ordinateur >> apparaitra. C'est
normal : l'installateur n'est pas signe par un certificat commercial, et
Windows se mefie de tout programme qu'il ne connait pas encore.

Pour continuer : << Informations complementaires >>, puis << Executer quand
meme >>.

L'empreinte ci-dessus donne la meme garantie technique qu'une signature :
savoir que le fichier recu est bien celui qui a ete publie.


INSTALLER
---------

Aucun droit administrateur n'est necessaire.

Gardez le dossier propose si vous hesitez. Si vous en choisissez un autre,
evitez les dossiers tres profonds : au-dela d'environ 145 caracteres de
chemin, Windows refuse de creer les fichiers les plus enfouis et
l'installation s'annule d'elle-meme.

A la fin, un second ecran propose de telecharger le moteur d'intelligence
artificielle et le modele adapte a votre carte graphique. Ils ne sont pas
inclus ici : ils pesent plusieurs gigaoctets et dependent de votre materiel.
Comptez entre 2 et 6 Go de telechargement.


L'ECLAIRAGE RGB DEMANDE UN PROGRAMME A PART
-------------------------------------------

Le pilotage des LED fonctionne, mais il s'appuie sur OpenRGB, qui n'est pas
inclus ici. Installez-le depuis :

    https://openrgb.org

rubrique Downloads, version Windows 64-bit. L'assistant le trouvera tout seul.

Deux choses a savoir : l'eclairage d'une carte mere passe par le bus SMBus,
qui demande les droits administrateur, et le logiciel du fabricant doit etre
ferme -- deux programmes sur le meme controleur font clignoter les LED au
hasard.

Le reste de l'assistant fonctionne sans OpenRGB.


CE QU'IL FAUT
-------------

    Windows 10 ou 11, 64 bits
    Un micro pour la commande vocale (facultatif)
    Une carte graphique NVIDIA rend tout nettement plus rapide, sans etre
    obligatoire


LICENCE
-------

Logiciel libre, sous licence MIT. Vous pouvez l'utiliser, l'etudier, le
modifier et le redistribuer, y compris dans un logiciel commercial, a la
seule condition de conserver la mention de copyright.

Le texte complet est installe avec le programme, dans LICENSE. Le releve des
licences des composants tiers se trouve dans LICENCES-TIERS.md, a cote.
"""


def construire() -> Path:
    from assistant import __version__

    if not INSTALLATEUR.is_file():
        raise FileNotFoundError(
            f"installateur introuvable : {INSTALLATEUR}. Lance publier.py "
            "d'abord.")

    dossier = BUREAU / f"Assistant local {__version__} - a envoyer"
    dossier.mkdir(parents=True, exist_ok=True)

    copie = dossier / INSTALLATEUR.name
    shutil.copy2(INSTALLATEUR, copie)

    sha = empreinte(copie)
    (dossier / f"{INSTALLATEUR.name}.sha256").write_text(
        f"{sha} *{INSTALLATEUR.name}\n", encoding="utf-8")

    taille_go = copie.stat().st_size / 1024 ** 3
    (dossier / "LISEZ-MOI.txt").write_text(
        lisez_moi(__version__, sha, taille_go), encoding="utf-8")

    print(f"  Dossier   : {dossier}")
    print(f"  Taille    : {taille_go:.2f} Go")
    print(f"  SHA-256   : {sha}")
    return dossier


def main() -> int:
    construire()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
