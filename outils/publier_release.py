"""Publie l'installateur sur GitHub, en une Release.

    .venv\\Scripts\\python.exe outils\\publier_release.py

Ce que voyait quelqu'un qui arrivait sur le depot : quatre-vingt-sept
fichiers source alignes, et nulle part le programme. L'installateur restait
sur la machine -- sauvegarder.py pousse le CODE, jamais ce qui est construit.

Pourquoi une Release, et pas un fichier du depot : GitHub refuse tout fichier
de plus de 100 Mo. L'installateur en pese onze fois plus. Un asset de Release
monte a 2 Go, et donne au visiteur UN fichier a telecharger au lieu d'une
liste de sources.

Ce que ce script ne fait PAS : rediger les notes de version. Elles se
reflechissent, comme un message de commit, et un script qui en invente
finirait par ecrire "corrections diverses" a chaque version. Il les lit dans
notes_de_version/<version>.md et s'arrete si elles manquent.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
INSTALLATEUR = RACINE / "installateur" / "Installer_AssistantLocal.exe"
NOTES = RACINE / "notes_de_version"
EN_LIGNE = "origin"
BRANCHE = "main"

# gh s'installe hors du PATH des shells deja ouverts. On cherche, on ne
# suppose pas -- meme demarche que pour OpenRGB.
CANDIDATS = [
    Path("C:/Program Files/GitHub CLI/gh.exe"),
    Path("C:/Program Files (x86)/GitHub CLI/gh.exe"),
]


def outil() -> Path | None:
    """Trouve gh, dans le PATH ou la ou il s'installe."""
    trouve = shutil.which("gh")
    if trouve:
        return Path(trouve)
    return next((c for c in CANDIDATS if c.is_file()), None)


def gh(*args, exe: Path | None = None) -> tuple[int, str]:
    chemin = exe or outil()
    if chemin is None:
        return 127, "gh introuvable"
    resultat = subprocess.run(
        [str(chemin), *args], cwd=str(RACINE),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return resultat.returncode, (resultat.stdout or "") + (resultat.stderr or "")


def git(*args) -> tuple[int, str]:
    resultat = subprocess.run(
        ["git", *args], cwd=str(RACINE),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return resultat.returncode, (resultat.stdout or "") + (resultat.stderr or "")


def empreinte(chemin: Path) -> str:
    """SHA-256 lu par blocs : le fichier pese plus d'un gigaoctet."""
    sha = hashlib.sha256()
    with chemin.open("rb") as f:
        for bloc in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(bloc)
    return sha.hexdigest()


def cible() -> str | None:
    """Le commit que la Release doit etiqueter : celui qui est EN LIGNE.

    En SHA complet, et ce n'est pas un detail de style. L'API GitHub rejette
    un SHA court en 422 "Release.target_commitish is invalid", sans dire que
    la longueur est en cause -- on cherche alors du cote des droits ou du nom
    du depot.

    On lit la tete du depot distant, pas la locale : etiqueter un commit que
    GitHub n'a pas encore recu echoue de la meme facon.
    """
    code, sortie = git("ls-remote", EN_LIGNE, BRANCHE)
    if code != 0 or not sortie.split():
        return None
    return sortie.split()[0]


def notes_de(version: str) -> Path:
    return NOTES / f"{version}.md"


def etat_de_la_release(tag: str) -> dict | None:
    """Ce que GitHub dit de la Release, ou None si elle n'existe pas."""
    code, sortie = gh("release", "view", tag,
                      "--json", "isDraft,tagName,url,assets")
    if code != 0:
        return None
    try:
        return json.loads(sortie)
    except json.JSONDecodeError:
        return None


def conforme(etat: dict, taille: int, sha: str) -> tuple[bool, str]:
    """Constate ce qui est en ligne, au lieu de croire un code de retour.

    Trois choses peuvent etre vraies separement et fausses ensemble : la
    Release existe, elle est publiee, et elle porte l'installateur ENTIER.

    Pendant l'envoi -- plusieurs minutes pour 1,1 Go -- elle existe en
    brouillon, sans asset et sans tag. Cet etat-la ressemble trait pour trait
    a un echec, et c'est ainsi qu'on l'a pris la premiere fois. Ici gh a
    rendu la main, donc l'etat lu est definitif.

    L'empreinte est celle que GitHub a calculee sur le fichier RECU. La
    comparer a celle du fichier local est ce qui prouve que l'envoi n'a rien
    tronque -- meme garantie que celle du LISEZ-MOI de la cle USB.
    """
    if etat.get("isDraft"):
        return False, "elle est restee en brouillon : l'envoi ne s'est pas termine"

    assets = [a for a in etat.get("assets", [])
              if a.get("name") == INSTALLATEUR.name]
    if not assets:
        return False, f"aucun {INSTALLATEUR.name} n'y est attache"

    asset = assets[0]
    if asset.get("state") != "uploaded":
        return False, f"l'installateur est dans l'etat \"{asset.get('state')}\""
    if asset.get("size") != taille:
        return False, (f"taille en ligne {asset.get('size')} octets, "
                       f"locale {taille} octets")

    distant = str(asset.get("digest") or "").removeprefix("sha256:")
    if distant and distant != sha:
        return False, f"empreinte en ligne {distant[:12]}..., locale {sha[:12]}..."
    return True, ""


def publier(version: str) -> int:
    exe = outil()
    if exe is None:
        print("  gh introuvable. Installe-le :  winget install GitHub.cli")
        return 1

    code, _ = gh("auth", "status", exe=exe)
    if code != 0:
        print("  gh n'est pas authentifie. Ouvre un terminal et lance :")
        print(f'    & "{exe}" auth login --hostname github.com '
              "--git-protocol https --web")
        print("  Le code a coller dans le navigateur s'affiche dans CE "
              "terminal, pas dans le navigateur.")
        return 1

    notes = notes_de(version)
    if not notes.is_file():
        print(f"  Notes de version absentes : {notes}")
        print("  Elles se redigent -- ce script n'en invente pas.")
        return 1

    if not INSTALLATEUR.is_file():
        print(f"  Installateur introuvable : {INSTALLATEUR}")
        return 1

    commit = cible()
    if commit is None:
        print(f"  Impossible de lire la tete de {EN_LIGNE}/{BRANCHE}. "
              "La sauvegarde vers GitHub a-t-elle eu lieu ?")
        return 1

    tag = f"v{version}"
    taille = INSTALLATEUR.stat().st_size
    sha = empreinte(INSTALLATEUR)

    # Une Release deja en place n'est pas forcement un probleme : relancer
    # une livraison interrompue doit pouvoir aboutir. Ce qui compte est
    # qu'elle soit conforme, pas qu'elle soit neuve.
    dejala = etat_de_la_release(tag)
    if dejala is not None:
        ok, pourquoi = conforme(dejala, taille, sha)
        if ok:
            print(f"  {tag} est deja publiee et conforme : {dejala.get('url')}")
            return 0
        print(f"  {tag} existe deja mais {pourquoi}.")
        print(f"  Supprime-la avant de recommencer :  gh release delete {tag}")
        return 1

    print(f"  Envoi de {taille / 1024 ** 3:.2f} Go vers {tag} "
          f"({commit[:7]})... plusieurs minutes, sans affichage.")
    code, sortie = gh("release", "create", tag,
                      "--target", commit,
                      "--title", f"Assistant local {version}",
                      "--notes-file", str(notes),
                      str(INSTALLATEUR), exe=exe)
    if code != 0:
        print(f"  ECHEC de la publication\n{sortie.strip()}")
        return 1

    etat = etat_de_la_release(tag)
    if etat is None:
        print("  Publiee, mais GitHub ne rend pas son etat : a verifier a la main.")
        return 1
    ok, pourquoi = conforme(etat, taille, sha)
    if not ok:
        print(f"  Publication incomplete : {pourquoi}")
        return 1

    print(f"  Release {tag} en ligne, installateur verifie ({sha[:12]}...)")
    print(f"  {etat.get('url')}")
    return 0


def main() -> int:
    from assistant import __version__

    return publier(__version__)


if __name__ == "__main__":
    if str(RACINE) not in sys.path:
        sys.path.insert(0, str(RACINE))
    raise SystemExit(main())
