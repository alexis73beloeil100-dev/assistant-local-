"""Point d'entree de l'executable.

PyInstaller part de ce fichier. Il reste volontairement minuscule : tout ce
qui est importe ici est analyse au moment de la construction, donc on garde
une seule porte d'entree, claire.

Une application packagee en mode fenetre n'a pas de console : sans le filet
ci-dessous, la moindre erreur au demarrage ferait disparaitre la fenetre sans
laisser la moindre trace. Tout part donc dans un fichier a cote de l'exe, et
l'erreur est affichee dans une boite de dialogue.
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path


def crash_log() -> Path:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) \
        else Path(__file__).resolve().parent
    return base / "erreurs.log"


def report(exc_text: str) -> None:
    path = crash_log()
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"\n=== {datetime.now().isoformat(timespec='seconds')} ===\n")
            fh.write(exc_text)
    except OSError:
        pass

    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            f"L'assistant n'a pas pu demarrer.\n\n"
            f"{exc_text.strip().splitlines()[-1]}\n\n"
            f"Details complets : {path}",
            "Assistant local",
            0x10,
        )
    except Exception:
        pass


def main() -> int:
    """Ouvre la fenetre de l'assistant, ou l'installateur avec --installer.

    Les deux partagent le meme executable : construire un second bundle de
    2,3 Go rien que pour afficher des cases a cocher serait absurde, et les
    deux fenetres dependent de toute facon des memes modules.
    """
    try:
        if "--autotest" in sys.argv or "--verifier" in sys.argv:
            from assistant.selftest import main as run
        elif "--installer" in sys.argv or "--installation" in sys.argv:
            from assistant.installer import main as run
        else:
            from assistant.gui import main as run

        return run()
    except Exception:
        report(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
