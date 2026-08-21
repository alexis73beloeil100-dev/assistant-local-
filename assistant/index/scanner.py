"""Scan des disques vers l'index SQLite.

Strategie : os.scandir en pile explicite (pas de recursion, pas de
os.walk qui refait des stat inutiles), insertion par lots, index et
plein texte construits seulement a la fin.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime

from assistant import config
from assistant.index import db

# Attribut Windows d'un point de reparse : jonction, lien symbolique,
# dossier OneDrive a la demande. On les enregistre mais on ne descend pas
# dedans, sinon C:\Users\...\Documents boucle sur lui-meme.
FILE_ATTRIBUTE_REPARSE_POINT = 0x400


BACKSLASH = "\\"


def _probe(path: str) -> str:
    """Forme normalisee d'un chemin, encadree de slashs.

    Calculee une seule fois par entree : sur 2 millions de fichiers, la
    difference entre une et trois normalisations est mesurable.
    """
    return "/" + path.replace(BACKSLASH, "/").lower().strip("/") + "/"


def walk(root: str, on_progress=None):
    """Genere les lignes a inserer pour une racine donnee.

    Les dossiers illisibles (droits, verrous) sont ignores silencieusement :
    sur un disque systeme il y en a toujours, ce n'est pas une erreur.
    """
    drive = root[:2].upper()
    stack = [root]
    seen = 0

    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except (PermissionError, OSError):
            continue

        for e in entries:
            try:
                path = e.path
                probe = _probe(path)

                # Un seul stat par entree : c'est le poste de cout dominant.
                st = e.stat(follow_symlinks=False)
                is_dir = e.is_dir(follow_symlinks=False)

                if is_dir and any(f in probe for f in config.EXCLUDED_DIRS):
                    continue

                name = e.name
                if is_dir or "." not in name:
                    ext = ""
                else:
                    ext = name.rpartition(".")[2].lower()
                    if len(ext) > 12:  # pas une vraie extension
                        ext = ""

                yield (
                    path,
                    name,
                    current,
                    ext,
                    0 if is_dir else st.st_size,
                    st.st_mtime,
                    1 if is_dir else 0,
                    1 if any(f in probe for f in config.CACHE_MARKERS) else 0,
                    drive,
                )

                seen += 1
                if on_progress and seen % 25_000 == 0:
                    on_progress(seen, path)

                if is_dir:
                    attrs = getattr(st, "st_file_attributes", 0)
                    if not attrs & FILE_ATTRIBUTE_REPARSE_POINT:
                        stack.append(path)

            except (PermissionError, OSError, ValueError):
                continue


def rebuild(roots: list[str] | None = None, verbose: bool = True) -> dict:
    """Reconstruit l'index de zero. Retourne les statistiques finales."""
    roots = roots or config.SCAN_ROOTS
    started = time.time()

    # En mode memoire il n'y a aucun fichier a remplacer : on repart
    # simplement d'une base vierge (voir plus bas).
    if config.PERSIST_INDEX and config.DB_PATH.exists():
        config.DB_PATH.unlink()
    for suffix in ("-wal", "-shm"):
        side = config.DB_PATH.with_name(config.DB_PATH.name + suffix)
        if side.exists():
            side.unlink()

    if not config.PERSIST_INDEX:
        # Base en memoire vierge, et index marque indisponible tant que la
        # reconstruction n'est pas terminee.
        db.reset_memory()

    conn = db.connect()
    db.init(conn)

    total = 0
    for root in roots:
        if not os.path.isdir(root):
            if verbose:
                print(f"  [!] {root} introuvable, ignore")
            continue
        if verbose:
            print(f"  Scan de {root} ...")

        done_before = total

        def progress(n, path):
            sys.stdout.write(f"\r    {done_before + n:>9,} entrees   {path[:66]:<66}")
            sys.stdout.flush()

        batch = []
        for row in walk(root, on_progress=progress if verbose else None):
            batch.append(row)
            if len(batch) >= config.INSERT_BATCH:
                db.insert_batch(conn, batch)
                total += len(batch)
                batch.clear()
        if batch:
            db.insert_batch(conn, batch)
            total += len(batch)
        conn.commit()
        if verbose:
            print(f"\r    {total:>9,} entrees   {'termine':<66}")

    if verbose:
        print("  Construction des index ...")
    db.create_indexes(conn)
    if verbose:
        print("  Construction de la recherche plein texte ...")
    db.rebuild_fts(conn)

    elapsed = time.time() - started
    db.set_meta(conn, "scanned_at", datetime.now().isoformat(timespec="seconds"))
    db.set_meta(conn, "scan_seconds", f"{elapsed:.1f}")
    db.set_meta(conn, "roots", ";".join(roots))

    conn.execute("ANALYZE")
    conn.commit()
    result = db.stats(conn)
    db.mark_ready()
    conn.close()
    return result


def rebuild_in_background(on_done=None):
    """Lance la construction de l'index dans un thread, sans bloquer.

    C'est ce qui permet a l'assistant de repondre tout de suite au demarrage
    (jeux, diagnostic, etat machine) pendant que la connaissance des fichiers
    se met en place derriere.
    """
    import threading

    def work():
        try:
            stats = rebuild(verbose=False)
        except Exception as exc:  # noqa: BLE001
            stats = {"error": f"{type(exc).__name__}: {exc}"}
        if on_done:
            on_done(stats)

    thread = threading.Thread(target=work, name="index-builder", daemon=True)
    thread.start()
    return thread
