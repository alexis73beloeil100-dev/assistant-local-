"""Livrer, en une seule commande.

    .venv\\Scripts\\python.exe livrer.py

Ce script existe parce que la livraison demandait sept commandes dans un
ordre precis, et qu'en sauter une ne se voyait nulle part : l'application
fonctionnait, les tests passaient, `git status` etait propre -- et la version
installee n'avait pas le correctif, ou le dossier du Bureau annoncait une
empreinte qui n'etait plus la bonne.

Ce qu'il enchaine :

    1. les tests
    2. l'executable            reconstruire.py
    3. l'installateur          outils/publier.py
    4. le manifeste            outils/manifeste.py, puis commit
    5. le dossier du Bureau    outils/dossier_a_envoyer.py
    6. les sauvegardes         outils/sauvegarder.py  (H:, cle USB, GitHub)
    7. la version installee    l'installateur, en silencieux
    8. la relance              l'assistant et le serveur OpenRGB

L'ordre n'est pas negociable, et il a ete appris a la dure. Le manifeste et
l'installateur lisent tous deux dist/ sans le modifier, donc leur ordre
semblait libre -- sauf que le manifeste est un fichier SUIVI : le regenerer
salit l'arbre, et publier.py refuse alors de publier. La premiere version de
ce script verifiait l'arbre au demarrage, puis le salissait elle-meme.

Ce qu'il ne fait PAS : commiter le code. Un message de commit se reflechit, et
un script qui en invente un finirait par ecrire "mise a jour" soixante fois.
Seule exception, le manifeste : c'est un releve d'empreintes produit par une
machine, il n'y a rien a rediger, et sans son commit l'etape des sauvegardes
s'arrete a son tour.

    --sans-installer   s'arreter avant de toucher a la version installee
    --sans-tests       pour reprendre une livraison interrompue plus loin
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent
PYTHON = RACINE / ".venv" / "Scripts" / "python.exe"
INSTALLATEUR = RACINE / "installateur" / "Installer_AssistantLocal.exe"
EXE = RACINE / "dist" / "AssistantLocal" / "AssistantLocal.exe"
TACHE_RGB = "AssistantLocal - serveur OpenRGB"

if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))


def titre(numero: int, sur: int, texte: str) -> None:
    print(f"\n[{numero}/{sur}] {texte}")
    print("  " + "-" * 66)


def lancer(*commande, ou: Path | None = None) -> bool:
    """Rend False au premier echec. Les sorties restent visibles."""
    resultat = subprocess.run([str(c) for c in commande], cwd=str(ou or RACINE))
    return resultat.returncode == 0


def arbre_propre() -> bool:
    """Verifie AVANT de construire, pas apres.

    publier.py refuse deja de publier un etat non commite -- et c'est la
    bonne regle : publier ce qui n'est pas dans l'historique, c'est ne plus
    jamais savoir ce qui a ete distribue. Mais il ne le decouvre qu'a son
    tour, apres la construction. Autant le dire en une seconde.
    """
    sortie = subprocess.run(
        ["git", "status", "--porcelain"], cwd=str(RACINE),
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    modifies = [l for l in (sortie.stdout or "").splitlines() if l.strip()]
    if modifies:
        print("  L'arbre n'est pas propre -- commite d'abord :")
        for ligne in modifies[:10]:
            print(f"    {ligne}")
        return False
    return True


def commiter_le_manifeste() -> bool:
    """Commite le manifeste regenere, et lui seul.

    C'est la seule exception a la regle "ce script ne commite pas". Elle se
    justifie parce qu'il n'y a rien a rediger : le manifeste est un releve
    d'empreintes produit par une machine, et son message tient en une ligne
    qui ne varie qu'au numero de version.

    Sans ce commit, l'etape suivante s'arrete : sauvegarder.py refuse un
    arbre sale, exactement comme publier.py. Et laisser le manifeste non
    commite serait pire que tout -- on ne saurait plus, plus tard, a quoi
    correspondait la version distribuee.
    """
    from assistant import __version__

    sortie = subprocess.run(
        ["git", "status", "--porcelain", "manifestes"], cwd=str(RACINE),
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if not (sortie.stdout or "").strip():
        print("  Manifeste inchange : rien a commiter.")
        return True

    if not lancer("git", "add", "manifestes"):
        return False
    if not lancer("git", "commit", "-q", "-m",
                  f"Manifeste du paquet {__version__}"):
        return False
    print(f"  Manifeste commite (version {__version__}).")
    return True


def relancer() -> None:
    """Remet en marche ce que la reconstruction a ferme.

    Elle arrete l'assistant, Ollama, llama-server et OpenRGB pour liberer les
    fichiers de dist/. Sans cette etape, on repart d'une session ou
    l'eclairage ne repond plus, et on cherche la cause dans le code.
    """
    subprocess.run(["schtasks.exe", "/run", "/tn", TACHE_RGB],
                   capture_output=True)
    installe = Path.home() / "AppData" / "Local" / "AssistantLocal"
    exe = installe / "AssistantLocal.exe"
    if exe.is_file():
        subprocess.Popen([str(exe)], cwd=str(installe))
        print(f"  Assistant relance : {exe}")
    else:
        print(f"  Assistant installe introuvable ({exe}) -- rien a relancer.")
    time.sleep(2)
    print(f"  Serveur RGB : tache \"{TACHE_RGB}\" demandee.")


def main() -> int:
    from assistant import __version__

    sans_installer = "--sans-installer" in sys.argv
    sans_tests = "--sans-tests" in sys.argv
    etapes = 8 - (1 if sans_installer else 0) - (1 if sans_tests else 0)
    n = 0

    print(f"\n  LIVRAISON DE L'ASSISTANT LOCAL {__version__}")
    print("  " + "=" * 66)

    if not arbre_propre():
        return 1

    if not sans_tests:
        n += 1
        titre(n, etapes, "Tests")
        if not lancer(PYTHON, "-m", "pytest", "tests", "-q"):
            print("\n  Tests en echec -- rien n'a ete construit ni publie.")
            return 1

    n += 1
    titre(n, etapes, "Executable")
    if not lancer(PYTHON, RACINE / "reconstruire.py"):
        return 1

    # L'INSTALLATEUR PASSE AVANT LE MANIFESTE, et l'ordre a ete appris a la
    # dure : le manifeste est un fichier SUIVI. Le regenerer salit l'arbre,
    # et publier.py refuse alors de publier -- a juste titre. La premiere
    # version de ce script verifiait l'arbre au demarrage, puis le salissait
    # elle-meme trois lignes plus loin.
    #
    # Les deux ne dependent pas l'un de l'autre : tous deux lisent dist/, que
    # ni l'un ni l'autre ne modifie.
    n += 1
    titre(n, etapes, "Installateur")
    if not lancer(PYTHON, RACINE / "outils" / "publier.py"):
        return 1
    if INSTALLATEUR.stat().st_mtime < EXE.stat().st_mtime:
        # Constater plutot que croire : un installateur plus VIEUX que
        # l'executable est celui d'une livraison precedente. Verifier sa
        # simple existence ne prouve rien, il en traine toujours un.
        print("\n  L'installateur est plus ancien que l'executable : "
              "publier.py n'a rien produit cette fois.")
        return 1

    n += 1
    titre(n, etapes, "Manifeste du paquet")
    if not lancer(PYTHON, RACINE / "outils" / "manifeste.py"):
        return 1
    if not commiter_le_manifeste():
        return 1

    n += 1
    titre(n, etapes, "Dossier du Bureau")
    if not lancer(PYTHON, RACINE / "outils" / "dossier_a_envoyer.py"):
        return 1

    n += 1
    titre(n, etapes, "Sauvegardes")
    if not lancer(PYTHON, RACINE / "outils" / "sauvegarder.py"):
        return 1

    if not sans_installer:
        n += 1
        titre(n, etapes, "Version installee")
        subprocess.run(["taskkill.exe", "/IM", "AssistantLocal.exe", "/F"],
                       capture_output=True)
        time.sleep(2)
        if not lancer(INSTALLATEUR, "/VERYSILENT", "/TASKS="):
            print("  L'installation silencieuse a echoue.")
            return 1
        print(f"  Version {__version__} installee.")

    n += 1
    titre(n, etapes, "Relance")
    relancer()

    print(f"\n  Livraison terminee : version {__version__}.")
    print("  Verifier d'un coup d'oeil : AssistantLocal.exe --autotest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
