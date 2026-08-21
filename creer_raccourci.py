"""Cree un raccourci "Assistant local" sur le Bureau.

Passe par le Windows Script Host plutot que par une dependance Python
supplementaire : WScript.Shell est present sur toutes les machines Windows et
sait ecrire un vrai .lnk, avec icone et dossier de travail.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXE = ROOT / "dist" / "AssistantLocal" / "AssistantLocal.exe"
NAME = "Assistant local.lnk"

VBS = """
Set shell = CreateObject("WScript.Shell")
Set link = shell.CreateShortcut("{lnk}")
link.TargetPath = "{target}"
link.WorkingDirectory = "{workdir}"
link.Description = "Assistant local - tout reste sur cette machine"
link.IconLocation = "{target}, 0"
link.Save
"""


def desktop() -> Path:
    """Le Bureau, y compris quand OneDrive l'a deplace."""
    candidates = [
        Path(os.environ.get("USERPROFILE", "")) / "OneDrive" / "Bureau",
        Path(os.environ.get("USERPROFILE", "")) / "OneDrive" / "Desktop",
        Path(os.environ.get("USERPROFILE", "")) / "Bureau",
        Path(os.environ.get("USERPROFILE", "")) / "Desktop",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return Path.home()


def create(target: Path | None = None) -> str:
    target = target or EXE
    if not target.exists():
        return f"Cible introuvable : {target}\nConstruis d'abord l'executable."

    lnk = desktop() / NAME
    script = VBS.format(
        lnk=str(lnk).replace("\\", "\\\\"),
        target=str(target).replace("\\", "\\\\"),
        workdir=str(target.parent).replace("\\", "\\\\"),
    )

    with tempfile.NamedTemporaryFile("w", suffix=".vbs", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(script)
        vbs_path = fh.name

    try:
        subprocess.run(["cscript", "//nologo", vbs_path], check=True,
                       capture_output=True, timeout=30)
    except (subprocess.SubprocessError, OSError) as exc:
        return f"Echec de la creation du raccourci : {exc}"
    finally:
        try:
            os.unlink(vbs_path)
        except OSError:
            pass

    return f"Raccourci cree : {lnk}"


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    print(create(target))
