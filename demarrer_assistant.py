"""Lanceur de secours, quand l'executable n'a pas encore ete construit.

Le demarrage automatique doit pointer sur dist/AssistantLocal.exe : c'est ce
que startup.command() inscrit. Ce script ne sert que depuis les sources.

Lance par pythonw.exe, il n'y a pas de console : tout ce qui serait affiche
part dans data/logs/assistant.log, sinon la moindre erreur au demarrage
serait invisible.

Python ajoute le dossier de ce script a sys.path, ce qui rend le paquet
"assistant" importable sans dependre du dossier courant.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

LOG = Path(__file__).resolve().parent / "data" / "logs" / "assistant.log"


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    stream = LOG.open("a", encoding="utf-8", buffering=1)
    sys.stdout = stream
    sys.stderr = stream
    print(f"\n=== demarrage {datetime.now().isoformat(timespec='seconds')} ===")

    try:
        # La FENETRE, pas la boucle vocale. assistant.main ouvrait l'ecoute
        # sans interface : au demarrage de Windows, l'utilisateur n'avait
        # rien a l'ecran et croyait que rien ne s'etait lance.
        from assistant.gui import main as run

        return run()
    except Exception:
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
