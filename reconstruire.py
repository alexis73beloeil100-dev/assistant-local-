"""Reconstruit l'executable proprement.

PyInstaller ecrase dist/ sans verifier que l'application n'y tourne pas. Si
elle tourne, la copie echoue sur un WinError 5 -- et PyInstaller sort quand
meme avec un code de succes, ce qui laisse croire que tout va bien alors que
l'exe date d'avant. Ce script ferme l'application et attend que Windows ait
reellement lache les fichiers avant de lancer la construction.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SPEC = ROOT / "AssistantLocal.spec"
EXE = ROOT / "dist" / "AssistantLocal" / "AssistantLocal.exe"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

LOCK_TIMEOUT = 20.0


def stop_app() -> None:
    """Ferme tout ce qui peut tenir un fichier de dist/.

    llama-server est le processus de calcul d'Ollama. Une instance lancee
    avant le correctif de dossier de travail heritait du repertoire de
    l'application et chargeait ses DLL : elle verrouille alors dist/ sans
    aucun rapport apparent avec l'assistant. Le tuer est sans consequence,
    Ollama le relance a la demande suivante.
    """
    for image in ("AssistantLocal.exe", "pythonw.exe",
                  "llama-server.exe", "ollama.exe"):
        subprocess.run(["taskkill", "/IM", image, "/F"],
                       capture_output=True, text=True)


def wait_unlocked(path: Path, timeout: float = LOCK_TIMEOUT) -> bool:
    """Attend que le fichier soit reellement liberable.

    La fin d'un processus ne signifie pas que ses fichiers sont libres :
    Windows relache les descripteurs avec un peu de retard. On teste
    l'ouverture en ecriture jusqu'a ce qu'elle passe.
    """
    if not path.exists():
        return True
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with path.open("ab"):
                return True
        except PermissionError:
            time.sleep(0.5)
    return False


def main() -> int:
    print("  Fermeture de l'application ...")
    stop_app()

    print("  Attente de la liberation des fichiers ...", end=" ", flush=True)
    if not wait_unlocked(EXE):
        print("ECHEC")
        print(f"  {EXE} reste verrouille. Ferme l'assistant a la main.")
        return 1
    print("ok")

    print("  Construction (environ 90 s) ...")
    result = subprocess.run(
        [str(PYTHON), "-m", "PyInstaller", "--noconfirm", str(SPEC)],
        capture_output=True, text=True,
    )

    # PyInstaller rend 0 meme quand la copie a echoue : on verifie le texte.
    sortie = result.stdout + result.stderr
    for probleme in ("PermissionError", "WinError 5", "Traceback"):
        if probleme in sortie:
            print(f"  ECHEC : {probleme} pendant la construction.")
            for ligne in sortie.splitlines():
                if probleme in ligne:
                    print("   ", ligne.strip())
            return 1

    if not EXE.exists():
        print("  ECHEC : aucun executable produit.")
        return 1

    age = time.time() - EXE.stat().st_mtime
    if age > 300:
        print(f"  ECHEC : l'executable date de {age / 60:.0f} min, il n'a pas "
              "ete reconstruit.")
        return 1

    print(f"  Executable pret : {EXE}")

    print("  Raccourci du Bureau ...")
    subprocess.run([str(PYTHON), str(ROOT / "creer_raccourci.py")])
    return 0


if __name__ == "__main__":
    sys.exit(main())
