"""Aucune fenetre noire : chaque processus console est lance cache.

L'application est en mode fenetre : elle n'a pas de console. Sous Windows,
tout programme console qu'elle lance (powershell, nvidia-smi, wmic, cmd...)
en recoit alors une NEUVE, qui s'affiche en noir le temps qu'il tourne. Le
code de l'assistant passe CREATE_NO_WINDOW a chacun de ses appels ; mais des
bibliotheques tierces lancent aussi les leurs, sans ce drapeau -- joblib
compte les coeurs du processeur avec wmic, platform interroge "ver" -- et
c'etaient autant de fenetres qui clignotaient au demarrage.

On pose donc le drapeau a la source, sur subprocess.Popen, pour tout appel
qui n'a pas choisi lui-meme. Sans effet sur un programme graphique : un
installateur, un jeu ou l'explorateur ouvrent leur fenetre comme avant ;
seule la console vide disparait.

Chaque lancement rattrape ainsi est note dans consoles.log, a cote de
l'executable : c'est ce qui permet de savoir qui les ouvrait.
"""
from __future__ import annotations

import inspect
import subprocess
import sys
import time
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
JOURNAL_MAX = 200

# Rang de creationflags parmi les arguments positionnels qui suivent `args`.
_RANG = list(inspect.signature(subprocess.Popen.__init__).parameters).index(
    "creationflags") - 2

_installe = False
_notes = 0


def journal() -> Path:
    base = (Path(sys.executable).parent if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parent.parent)
    return base / "consoles.log"


def _noter(args) -> None:
    global _notes
    if _notes >= JOURNAL_MAX:
        return
    _notes += 1
    try:
        commande = args if isinstance(args, str) else " ".join(map(str, args))
        with journal().open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {commande[:300]}\n")
    except (OSError, TypeError):
        pass


def installer() -> bool:
    """Pose le filet. Rend True s'il est actif (Windows seulement)."""
    global _installe
    if _installe:
        return True
    if sys.platform != "win32":
        return False

    origine = subprocess.Popen.__init__

    def __init__(self, args, *a, **kw):
        # Un appelant qui a choisi ses drapeaux sait ce qu'il fait : on n'y
        # touche pas. Les drapeaux passes en position (rarissime) aussi.
        if "creationflags" not in kw and len(a) <= _RANG:
            kw["creationflags"] = CREATE_NO_WINDOW
            _noter(args)
        origine(self, args, *a, **kw)

    subprocess.Popen.__init__ = __init__
    _installe = True
    return True
