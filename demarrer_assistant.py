"""Lanceur silencieux, utilise par le demarrage automatique de Windows.

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
        from assistant.main import main as run

        return run([])
    except Exception:
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
