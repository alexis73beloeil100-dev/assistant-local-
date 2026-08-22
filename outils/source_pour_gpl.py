"""Fabrique l'archive du code source, livree AVEC l'application.

La GPLv3 d'openrgb-python impose que le code source accompagne le binaire
distribue. Elle laisse le choix entre joindre le source et promettre de le
fournir sur demande pendant trois ans -- une promesse qui suppose de tenir une
adresse et de repondre. Joindre l'archive coute 30 Mo sur un installateur qui
en pese 1 150, et ne demande rien a personne ensuite.

L'archive est produite depuis le depot, pas depuis dist/ : c'est le code
modifiable qui est en jeu, pas les fichiers compiles.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
LIVRE = RACINE / "dist" / "AssistantLocal"
NOM = "assistant-local-source.zip"

# Ce qui n'est pas du source, ou qui ne se redistribue pas.
#
# .git en fait partie : l'historique n'est pas le "code source correspondant"
# au sens de la licence, et il ferait tripler l'archive.
IGNORE_DOSSIERS = {
    ".venv", ".git", "build", "dist", "installateur", "__pycache__",
    ".pytest_cache", "manifestes", "bac_de_test", "bac_suppression",
}
IGNORE_SUFFIXES = {".pyc", ".pyo", ".db", ".log", ".zip", ".exe", ".dll",
                   ".bin", ".pyd"}


def fichiers_du_source() -> list[Path]:
    """Le code source redistribuable, sans les binaires ni les caches."""
    trouves = []
    for chemin in sorted(RACINE.rglob("*")):
        if not chemin.is_file():
            continue
        relatif = chemin.relative_to(RACINE)
        if any(part in IGNORE_DOSSIERS for part in relatif.parts):
            continue
        if chemin.suffix.lower() in IGNORE_SUFFIXES:
            continue
        trouves.append(chemin)
    return trouves


def construire(destination: Path | None = None) -> Path:
    """Ecrit l'archive et rend son chemin.

    Elle atterrit dans dist/ et non a cote du script Inno : dist/ doit rester
    exactement ce qui s'installe, sinon l'archive echapperait au manifeste et
    ne serait jamais mise a jour -- on livrerait indefiniment le source de la
    premiere version.
    """
    if destination is None:
        destination = LIVRE / NOM
    destination.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for chemin in fichiers_du_source():
            archive.write(chemin, chemin.relative_to(RACINE).as_posix())

    return destination


def main() -> int:
    archive = construire()
    with zipfile.ZipFile(archive) as z:
        nombre = len(z.namelist())
    print(f"  {nombre} fichiers, {archive.stat().st_size / 1048576:.1f} Mo")
    print(f"  Source : {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
