"""Reglages choisis par l'utilisateur, conserves d'une session a l'autre.

Un tout petit fichier JSON, et rien d'autre : le modele choisi a
l'installation, le micro selectionne, la voix activee ou non. Aucune donnee
personnelle, aucune liste de fichiers -- l'index reste en memoire vive.

Sans ce fichier, l'installateur pouvait telecharger un modele que
l'application n'utilisait jamais, parce que le nom du modele etait fige dans
le code.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

# Verrou REENTRANT, et resolution du chemin en dehors du verrou.
#
# La version precedente utilisait un Lock simple et appelait _path() en le
# tenant. Or _path() importe assistant.config, dont l'import appelle
# config.llm_model(), qui rappelle settings.get() -- qui redemande le meme
# verrou. Interblocage complet, et l'application se figeait au demarrage sans
# le moindre message. Ca ne se declenchait que si settings etait touche avant
# que config soit importe, ce qui arrive au premier lancement.
_lock = threading.RLock()
_cache: dict | None = None


def _path() -> Path:
    from assistant import config

    return config.DATA_DIR / "settings.json"


def _load(chemin: Path) -> dict:
    if not chemin.is_file():
        return {}
    try:
        données = json.loads(chemin.read_text(encoding="utf-8"))
        return données if isinstance(données, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def recharger() -> dict:
    """Relit le fichier, en ignorant ce qui est deja en memoire.

    Le cache suffit tant qu'un seul processus ecrit et lit. Il ne suffit plus
    des qu'un autre modifie le fichier : le 24/08/2026, une macro enregistree
    depuis un script est restee invisible au serveur local, qui gardait la
    liste chargee a son demarrage. Rien n'echouait -- le telephone affichait
    simplement une liste vide, et on cherchait la cause du cote du reseau.

    A appeler quand la fraicheur compte davantage que le cout d'une lecture :
    ce fichier fait quelques centaines d'octets.
    """
    global _cache

    chemin = _path()
    with _lock:
        _cache = _load(chemin)
        return dict(_cache)


def all() -> dict:
    global _cache
    chemin = _path()          # hors du verrou : cet appel importe config
    with _lock:
        if _cache is None:
            _cache = _load(chemin)
        return dict(_cache)


def get(key: str, default=None):
    return all().get(key, default)


def set(key: str, value) -> None:
    global _cache
    chemin = _path()
    with _lock:
        # On relit le fichier si rien n'est encore en cache : partir d'un
        # dictionnaire vide ecraserait tous les reglages existants au premier
        # set() de la session.
        if _cache is None:
            _cache = _load(chemin)
        données = dict(_cache)
        données[key] = value
        _cache = données

    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(
            json.dumps(données, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass  # un reglage non conserve ne doit jamais faire planter l'app
