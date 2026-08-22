"""Compile l'installateur ET son empreinte, dans le meme geste.

Ecrit parce que les deux avaient diverge. Le 22/08, l'empreinte publiee a cote
de l'installateur designait un fichier compile une heure et demie plus tot :
elle avait ete produite a la main, une fois, et plus jamais ensuite. Trois
recompilations l'ont laissee derriere sans que rien ne le signale.

Une empreinte qui ne correspond pas est PIRE que pas d'empreinte du tout.
Celui qui la verifie conclut que le fichier a ete altere en chemin -- c'est
exactement le soupcon qu'elle sert a lever.

La seule facon fiable de les tenir ensemble est de ne jamais les produire
separement. Ce script est donc le seul point d'entree pour publier :

    .venv\\Scripts\\python.exe outils\\publier.py

Il refuse de travailler sur un arbre modifie. Publier un etat qui n'existe
dans aucun commit, c'est se condamner a ne plus jamais savoir ce qui a ete
distribue.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SPEC = RACINE / "installateur.iss"
SORTIE = RACINE / "installateur" / "Installer_AssistantLocal.exe"

# Inno Setup s'installe volontiers en mode utilisateur : ni dans Program Files,
# ni dans le PATH. Chercher uniquement `iscc` conduit a croire qu'il manque.
ISCC = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("PROGRAMFILES", "")) / "Inno Setup 6" / "ISCC.exe",
]


def compilateur() -> Path | None:
    for chemin in ISCC:
        try:
            if chemin.is_file():
                return chemin
        except OSError:
            continue
    import shutil

    trouve = shutil.which("ISCC")
    return Path(trouve) if trouve else None


def empreinte(fichier: Path) -> str:
    """SHA-256, lue par blocs : le fichier pese plus d'un gigaoctet."""
    digest = hashlib.sha256()
    with fichier.open("rb") as fh:
        for bloc in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(bloc)
    return digest.hexdigest()


def arbre_propre() -> tuple[bool, str]:
    try:
        resultat = subprocess.run(
            ["git", "status", "--porcelain"], cwd=RACINE,
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return False, f"git injoignable : {exc}"
    modifies = [l for l in (resultat.stdout or "").splitlines() if l.strip()]
    if modifies:
        return False, "\n".join(f"    {l}" for l in modifies[:10])
    return True, ""


def version_publiee() -> str:
    import re

    texte = (RACINE / "assistant" / "__init__.py").read_text(encoding="utf-8")
    trouve = re.search(r'__version__\s*=\s*"([^"]+)"', texte)
    return trouve.group(1) if trouve else "?"


def main() -> int:
    force = "--force" in sys.argv

    propre, detail = arbre_propre()
    if not propre and not force:
        print("  L'arbre de travail n'est pas propre :")
        print(detail)
        print("\n  Commite d'abord. Publier un etat absent de l'historique,")
        print("  c'est ne plus jamais savoir ce qui a ete distribue.")
        print("  Passer outre : --force")
        return 1

    iscc = compilateur()
    if iscc is None:
        print("  Inno Setup introuvable. Installe-le, ou verifie :")
        for chemin in ISCC:
            print(f"    {chemin}")
        return 1

    version = version_publiee()
    print(f"  Version    : {version}")
    print(f"  Compilateur: {iscc}")
    print("  Compilation (plusieurs minutes, 2,5 Go a compresser) ...")

    resultat = subprocess.run([str(iscc), str(SPEC)], cwd=RACINE,
                              capture_output=True, text=True)
    if resultat.returncode != 0:
        print("  ECHEC de la compilation :")
        for ligne in (resultat.stdout + resultat.stderr).splitlines()[-12:]:
            print(f"    {ligne}")
        return 1

    if not SORTIE.is_file():
        print(f"  ECHEC : {SORTIE} n'a pas ete produit.")
        return 1

    # L'empreinte est calculee sur le fichier QUI VIENT D'ETRE ECRIT, dans le
    # meme processus. C'est tout l'interet : il n'existe aucun moment ou l'un
    # peut exister sans l'autre.
    somme = empreinte(SORTIE)
    fichier_somme = SORTIE.with_suffix(SORTIE.suffix + ".sha256")

    # newline="\n" : SANS CA, WINDOWS ECRIT \r\n ET LE FICHIER EST INUTILISABLE.
    #
    # Le format sha256sum est "empreinte espace etoile nomdufichier". Un
    # retour chariot en fin de ligne se colle au NOM : sha256sum -c cherche
    # alors un fichier appele "Installer_AssistantLocal.exe\r", ne le trouve
    # pas, et repond FAILED open or read. Sous Linux, macOS ou Git Bash, le
    # destinataire conclut a une corruption -- exactement le contraire de ce
    # que ce fichier sert a prouver.
    #
    # Get-FileHash sous Windows n'y voit rien, ce qui rend le defaut invisible
    # depuis la machine qui publie.
    with fichier_somme.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"{somme} *{SORTIE.name}\n")

    taille = SORTIE.stat().st_size / 1024**2
    print(f"\n  Installateur : {SORTIE}")
    print(f"  Taille       : {taille:,.0f} Mo".replace(",", " "))
    print(f"  SHA-256      : {somme}")
    print(f"  Empreinte    : {fichier_somme.name}")
    print("\n  Verification par l'utilisateur :")
    print(f"    Get-FileHash {SORTIE.name} -Algorithm SHA256")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
