"""Acces aux fichiers via l'index : la couche que le modele appelle.

Ces fonctions renvoient toujours du texte deja mis en forme. Le modele local
est bon pour comprendre une demande et choisir un outil, beaucoup moins pour
aligner des colonnes : on ne lui laisse pas ce travail.
"""
from __future__ import annotations

import functools
import os
import subprocess

from assistant.index import db
from assistant.util import human_date, human_size, norm


def _conn():
    return db.connect()


def needs_index(fn):
    """Refuse poliment tant que l'index n'est pas construit.

    En mode memoire, l'index se reconstruit a chaque demarrage. Repondre
    "aucun resultat" pendant ce temps serait un mensonge : on dit clairement
    que la connaissance des fichiers n'est pas encore disponible.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not db.is_ready():
            return (
                "L'index des fichiers est encore en construction "
                "(environ 80 secondes apres le demarrage). "
                "Le reste de l'assistant fonctionne deja."
            )
        return fn(*args, **kwargs)

    return wrapper


@needs_index
def search(query: str, limit: int = 15, ext: str | None = None) -> str:
    """Cherche un fichier ou un dossier par nom."""
    with _conn() as conn:
        rows = db.search(conn, query, limit=limit, ext=ext)
    if not rows:
        return f"Aucun resultat pour \"{query}\"."

    lines = [f"{len(rows)} resultat(s) pour \"{query}\" :"]
    for r in rows:
        tag = "[dossier]" if r["is_dir"] else human_size(r["size"])
        lines.append(f"  {tag:>12}  {human_date(r['mtime'])}  {r['path']}")
    return "\n".join(lines)


@needs_index
def biggest(limit: int = 15, under: str | None = None, ext: str | None = None) -> str:
    """Les plus gros fichiers du PC, ou d'un dossier precis."""
    with _conn() as conn:
        rows = db.largest(conn, limit=limit, under=under, ext=ext)
    if not rows:
        return "Rien trouve."

    where = f" dans {under}" if under else ""
    lines = [f"Les {len(rows)} plus gros fichiers{where} :"]
    for r in rows:
        mark = " (cache)" if r["is_cache"] else ""
        lines.append(f"  {human_size(r['size']):>12}  {r['path']}{mark}")
    return "\n".join(lines)


@needs_index
def folder_weight(path: str, limit: int = 15) -> str:
    """Ce qui pese dans un dossier, sous-dossier par sous-dossier."""
    with _conn() as conn:
        rows = db.dir_sizes(conn, path, limit=limit)
    if not rows:
        return f"Rien d'indexe sous {path}."

    total = sum(r["total"] for r in rows)
    lines = [f"Contenu de {path} ({human_size(total)} au total) :"]
    for r in rows:
        share = 100 * r["total"] / total if total else 0
        bar = "#" * int(share / 4)
        lines.append(
            f"  {human_size(r['total']):>12}  {share:5.1f} % {bar:<25} {r['bucket']}"
        )
    return "\n".join(lines)


@needs_index
def recent(limit: int = 15, ext: str | None = None) -> str:
    """Les fichiers modifies le plus recemment."""
    with _conn() as conn:
        rows = db.recent(conn, limit=limit, ext=ext)
    if not rows:
        return "Rien trouve."
    lines = ["Fichiers modifies recemment :"]
    for r in rows:
        lines.append(f"  {human_date(r['mtime'])}  {human_size(r['size']):>10}  {r['path']}")
    return "\n".join(lines)


@needs_index
def duplicates(min_mb: int = 50, limit: int = 15) -> str:
    """Candidats doublons, du plus couteux au moins couteux.

    Base sur nom + taille identiques, sans lire les fichiers : c'est instantane
    mais ce ne sont que des candidats. Rien n'est supprime ici.
    """
    with _conn() as conn:
        rows = db.duplicates(conn, min_size=min_mb * 1024 * 1024, limit=limit)
    if not rows:
        return f"Aucun doublon evident au-dessus de {min_mb} Mo."

    wasted = sum(r["wasted"] for r in rows)
    lines = [
        f"Doublons probables ({human_size(wasted)} recuperables au total).",
        "Meme nom et meme taille : a verifier avant toute suppression.",
    ]
    for r in rows:
        lines.append(
            f"  {human_size(r['wasted']):>12} perdus  {r['name']}  "
            f"({r['copies']} copies)"
        )
        for p in str(r["paths"]).split("|")[:3]:
            lines.append(f"                        {p}")
    return "\n".join(lines)


@needs_index
def caches(limit: int = 15) -> str:
    """Poids des dossiers de cache : ce qui se supprime sans rien casser.

    Les caches Unreal sont listes mais signales : les supprimer coute des
    heures de recompilation de shaders au prochain lancement.
    """
    sql = """
        SELECT parent, SUM(size) AS total, COUNT(*) AS n
        FROM files WHERE is_cache = 1 AND is_dir = 0
        GROUP BY parent ORDER BY total DESC LIMIT ?
    """
    with _conn() as conn:
        rows = conn.execute(sql, (limit * 4,)).fetchall()

    # Regroupe par dossier de cache racine plutot que par feuille.
    buckets: dict[str, list[int]] = {}
    for r in rows:
        p = norm(r["parent"])
        key = r["parent"]
        for marker in ("/deriveddatacache", "/node_modules", "/intermediate",
                       "/temp", "/d3dscache", "/nv_cache"):
            if marker in p:
                cut = p.index(marker) + len(marker)
                key = r["parent"][:cut]
                break
        agg = buckets.setdefault(key, [0, 0])
        agg[0] += r["total"]
        agg[1] += r["n"]

    ordered = sorted(buckets.items(), key=lambda kv: kv[1][0], reverse=True)[:limit]
    if not ordered:
        return "Aucun cache identifie dans l'index."

    total = sum(v[0] for _, v in ordered)
    lines = [f"Caches identifies ({human_size(total)}) :"]
    for path, (size, count) in ordered:
        warn = ""
        if "deriveddatacache" in norm(path):
            warn = "   <- cache Unreal : sa suppression coute des heures de shaders"
        lines.append(f"  {human_size(size):>12}  {count:>7} fichiers  {path}{warn}")
    return "\n".join(lines)


def reveal(path: str) -> str:
    """Ouvre l'explorateur sur un fichier, en le selectionnant."""
    if not os.path.exists(path):
        return f"{path} n'existe pas (ou plus) sur le disque."
    try:
        if os.path.isdir(path):
            os.startfile(path)
        else:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    except OSError as exc:
        return f"Impossible d'ouvrir l'explorateur : {exc}"
    return f"Explorateur ouvert sur {path}."


@needs_index
def index_status() -> str:
    """Age et taille de l'index."""
    with _conn() as conn:
        s = db.stats(conn)
    return (
        f"Index : {s['files']:,} fichiers et {s['dirs']:,} dossiers "
        f"({human_size(s['bytes'])}), dont {s['cache_entries']:,} entrees de cache.\n"
        f"Construit le {s['scanned_at']} en {s['scan_seconds']} s."
    ).replace(",", " ")
