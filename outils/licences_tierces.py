"""Releve les licences des dependances embarquees, depuis leurs metadonnees.

Ecrire ces licences a la main dans LICENCES-TIERS.md, c'est signer une
affirmation juridique qui vieillit en silence : une dependance change de
licence a une mise a jour mineure, et le document continue d'annoncer
l'ancienne. On les relit donc a la source, dans les metadonnees du paquet
installe.

Sortie : le tableau Markdown a recopier dans LICENCES-TIERS.md, et surtout la
liste des licences copyleft, qui sont les seules a imposer quelque chose.
"""
from __future__ import annotations

from importlib import metadata

# Ce qui part reellement dans l'installateur. Les outils de developpement
# (pytest, flake8) n'y sont pas : ils ne sont pas redistribues.
EMBARQUE = [
    "faster-whisper", "ctranslate2", "onnxruntime", "comtypes", "mss",
    "sounddevice", "opencv-python", "openwakeword", "rapidocr-onnxruntime",
    "watchdog", "huggingface-hub", "requests", "numpy", "scipy",
    "scikit-learn", "psutil", "send2trash", "reportlab", "av", "pyttsx3",
    "pycaw", "nvidia-cublas-cu12", "nvidia-cudnn-cu12",
]

# Celles qui imposent quelque chose a la redistribution. Le programme les
# signale a part : c'est la seule partie du document qui demande une decision.
COPYLEFT = ("GPL", "MPL", "LGPL", "AGPL", "EUPL", "CDDL")


def licence_de(nom: str) -> tuple[str, str] | None:
    """(version, licence) d'un paquet installe, ou None s'il est absent."""
    try:
        meta = metadata.metadata(nom)
        version = metadata.version(nom)
    except metadata.PackageNotFoundError:
        return None

    # License-Expression est le champ moderne et normalise ; License est
    # l'ancien, et contient parfois le texte entier de la licence -- d'ou la
    # bascule sur les classificateurs quand la valeur est trop longue.
    licence = meta.get("License-Expression") or meta.get("License") or ""
    if not licence or len(licence) > 60:
        licence = next(
            (c.split("::")[-1].strip()
             for c in meta.get_all("Classifier") or []
             if c.startswith("License ::")),
            licence[:60] or "non declaree")
    return version, licence


def main() -> int:
    lignes, manquants, a_surveiller = [], [], []

    for nom in sorted(EMBARQUE):
        trouve = licence_de(nom)
        if trouve is None:
            manquants.append(nom)
            continue
        version, licence = trouve
        lignes.append(f"| {nom} | {version} | {licence} |")
        if any(marque in licence.upper() for marque in COPYLEFT):
            a_surveiller.append(f"{nom} {version} : {licence}")

    print("| Composant | Version | Licence |")
    print("|---|---|---|")
    print("\n".join(lignes))

    if manquants:
        print(f"\nAbsents de l'environnement : {', '.join(manquants)}")

    print("\nCopyleft -- les seules qui imposent quelque chose :")
    for ligne in a_surveiller or ["  aucune"]:
        print(f"  {ligne}")
    print("\nOpenRGB (GPLv2) et PyInstaller (GPLv2 + exception) ne sont pas")
    print("dans cette liste : ils ne s'installent pas par pip. Voir")
    print("LICENCES-TIERS.md, qui les traite en detail.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
