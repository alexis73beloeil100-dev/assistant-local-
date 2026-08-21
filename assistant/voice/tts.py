"""Synthese vocale, via les voix Windows deja installees.

Pas de telechargement, pas de reseau : SAPI est deja la et parle francais.
La qualite est en dessous des voix neuronales, mais pour "Euro Truck Simulator
2 se lance" c'est largement suffisant, et ca ne coute ni VRAM ni latence.
"""
from __future__ import annotations

import re
import threading

_engine = None
_lock = threading.Lock()

# Un chemin Windows va de la lettre de lecteur jusqu'a la fin de la ligne.
# On ne peut pas s'arreter au premier espace : "C:\Program Files\..." en
# contient, et on ne garderait que "C:\Program".
_PATH_RE = re.compile(r"[A-Za-z]:\\.*$")


def _get_engine():
    global _engine
    if _engine is None:
        import pyttsx3

        _engine = pyttsx3.init()
        _engine.setProperty("rate", 190)
        for voice in _engine.getProperty("voices"):
            blob = f"{voice.id} {voice.name}".lower()
            if "fr" in blob or "hortense" in blob or "julie" in blob:
                _engine.setProperty("voice", voice.id)
                break
    return _engine


def voices() -> list[str]:
    return [v.name for v in _get_engine().getProperty("voices")]


def speakable(text: str, max_chars: int = 400) -> str:
    """Reduit un texte d'ecran a quelque chose d'ecoutable.

    Les chemins complets sont remplaces par le seul nom de fichier : entendre
    "C deux points antislash Program Files antislash..." n'aide personne.
    """
    lines = [
        _PATH_RE.sub(lambda m: m.group(0).rstrip().rsplit("\\", 1)[-1], line)
        for line in text.splitlines()
    ]
    text = ". ".join(line.strip() for line in lines if line.strip())
    text = re.sub(r"[#*`|>_]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        cut = text[:max_chars]
        text = cut.rsplit(".", 1)[0] + "." if "." in cut else cut
    return text


def say(text: str, blocking: bool = True) -> None:
    """Prononce un texte. SAPI n'aime pas les appels concurrents, d'ou le verrou."""
    text = speakable(text)
    if not text:
        return
    with _lock:
        engine = _get_engine()
        engine.say(text)
        if blocking:
            engine.runAndWait()
