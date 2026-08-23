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
    3. le manifeste            outils/manifeste.py
    4. l'installateur          outils/publier.py
    5. le dossier du Bureau    outils/dossier_a_envoyer.py
    6. les sauvegardes         outils/sauvegarder.py  (H:, cle USB, GitHub)
    7. la version installee    l'installateur, en silencieux
    8. la relance              l'assistant et le serveur OpenRGB

L'ordre n'est pas negociable. Le manifeste doit decrire le paquet REEL, donc
il vient apres la construction ; l'installateur compresse ce paquet, donc il
vient apres le manifeste ; et le dossier du Bureau copie l'installateur.

Ce qu'il ne fait PAS : commiter. Un message de commit se reflechit, et un
script qui en invente un finirait par ecrire "mise a jour" soixante fois.

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
    jamais savoir ce qui a ete distribue. Mais il le decouvre a la fin, apres
    dix minutes de construction. Autant le dire en une seconde.
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

    n += 1
    titre(n, etapes, "Manifeste du paquet")
    if not lancer(PYTHON, RACINE / "outils" / "manifeste.py"):
        return 1

    n += 1
    titre(n, etapes, "Installateur")
    if not lancer(PYTHON, RACINE / "outils" / "publier.py"):
        return 1
    if not INSTALLATEUR.is_file():
        # publier.py sort en code 0 meme quand il renonce. Constater le
        # fichier est la seule facon de savoir qu'il a vraiment travaille.
        print("\n  publier.py n'a produit aucun installateur. Relis sa sortie "
              "ci-dessus.")
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
