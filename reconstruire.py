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


def note_larret_deliberee() -> None:
    """Dit au journal de vie que c'est NOUS qui fermons l'application.

    Sans ca, chaque reconstruction ressemblait a une mort brutale : le
    taskkill ci-dessous ne laisse evidemment pas l'application ecrire sa
    ligne de fermeture, et l'assistant annoncait au demarrage suivant
    "arretee sans passer par la fermeture normale". Cinq reconstructions dans
    une soiree, et le journal accusait cinq plantages qui n'existaient pas.
    """
    try:
        import psutil

        from assistant import vie
    except ImportError:
        return

    for proc in psutil.process_iter(["name", "pid"]):
        try:
            nom = (proc.info.get("name") or "").lower()
            if nom in ("assistantlocal.exe", "pythonw.exe"):
                vie.arret_de(proc.info["pid"], "ferme par reconstruire.py")
        except Exception:  # noqa: BLE001
            continue


def stop_app() -> None:
    """Ferme tout ce qui peut tenir un fichier de dist/.

    llama-server est le processus de calcul d'Ollama. Une instance lancee
    avant le correctif de dossier de travail heritait du repertoire de
    l'application et chargeait ses DLL : elle verrouille alors dist/ sans
    aucun rapport apparent avec l'assistant. Le tuer est sans consequence,
    Ollama le relance a la demande suivante.
    """
    # OpenRGB est livre DANS le bundle depuis que l'eclairage est gere : son
    # serveur garde hidapi.dll ouverte tant qu'il tourne, et la
    # reconstruction echoue sur un WinError 5 qui ne nomme que la DLL.
    for image in ("AssistantLocal.exe", "pythonw.exe",
                  "llama-server.exe", "ollama.exe",
                  "OpenRGB.exe", "openrgb.exe"):
        subprocess.run(["taskkill", "/IM", image, "/F"],
                       capture_output=True, text=True)

    # OpenRGB tourne desormais EN ADMINISTRATEUR, lance par une tache
    # planifiee : le taskkill ci-dessus, non eleve, echoue en silence sur lui.
    # On arrete donc la tache, et on demande l'elevation pour le processus
    # s'il tient encore. Sans ca, la reconstruction repartait sur une DLL
    # verrouillee des que la tache visait la copie du bundle.
    subprocess.run(["schtasks", "/end", "/tn", "AssistantLocal - serveur OpenRGB"],
                   capture_output=True, text=True)
    if _tourne_encore("OpenRGB.exe"):
        print("  OpenRGB est elevé : autorisation demandée pour l'arrêter ...")
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden "
             "-ArgumentList '-NoProfile','-Command',"
             "'Get-Process OpenRGB -ErrorAction SilentlyContinue | "
             "Stop-Process -Force'"],
            capture_output=True, text=True)


def _tourne_encore(image: str) -> bool:
    """Un processus de ce nom est-il encore en vie ?"""
    try:
        import psutil
    except ImportError:
        return False
    cible = image.lower()
    return any((p.info.get("name") or "").lower() == cible
               for p in psutil.process_iter(["name"]))


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


LICENCES = ("LICENSE", "LICENCES-TIERS.md", "LICENCE-INSTALLATION.txt")


def copier_licences() -> None:
    """Fait voyager les licences avec l'application.

    Elles doivent etre INSTALLEES a cote de l'executable, pas seulement
    presentes dans le depot : c'est le binaire qu'on distribue, et la GPLv2
    d'OpenRGB comme la GPLv3 d'openrgb-python exigent que leur texte
    accompagne ce qui est redistribue.

    On les copie dans dist/ plutot que de les ajouter au script Inno, pour
    que dist/ reste exactement ce qui s'installe. Le manifeste des mises a
    jour repose sur cette egalite : un fichier installe qui n'est pas dans
    dist/ ne serait jamais mis a jour, et personne ne s'en apercevrait.
    """
    destination = EXE.parent
    for nom in LICENCES:
        source = ROOT / nom
        if source.exists():
            (destination / nom).write_bytes(source.read_bytes())


def main() -> int:
    print("  Fermeture de l'application ...")
    # L'ordre compte : on note AVANT de tuer, sinon les processus ont disparu
    # et on ne sait plus de qui parler.
    note_larret_deliberee()
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

    copier_licences()
    # Le source accompagne le binaire : la GPLv3 l'exige, et le joindre
    # dispense de tenir une promesse de fourniture sur trois ans.
    from outils import source_pour_gpl
    archive = source_pour_gpl.construire()
    print(f"  Source joint : {archive.stat().st_size / 1048576:.1f} Mo")
    print(f"  Executable pret : {EXE}")

    print("  Raccourci du Bureau ...")
    subprocess.run([str(PYTHON), str(ROOT / "creer_raccourci.py")])
    return 0


if __name__ == "__main__":
    sys.exit(main())
