"""Suivi des changements de fichiers, pour que l'index ne vieillisse pas.

L'index est une photographie prise au demarrage. Sans surveillance, un
fichier telecharge pendant que l'assistant tourne reste invisible jusqu'au
prochain lancement -- et l'utilisateur croit legitimement que le logiciel
ment.

On ne surveille pas les disques entiers : Windows genere des milliers
d'evenements par minute dans Windows/, AppData/ et les caches, pour des
fichiers dont personne ne cherchera jamais le nom. On surveille les dossiers
ou l'utilisateur travaille vraiment.

Les mises a jour vont dans l'index, ou qu'il vive : en memoire ou sur le
disque, selon config.PERSIST_INDEX -- passe a True le 24/08/2026.

Depuis ce jour, cette surveillance ne rafraichit plus une photographie qui
allait de toute facon mourir a la fermeture : c'est elle qui empeche un index
CONSERVE de vieillir pendant que l'assistant tourne. Ce qu'elle ne peut pas
rattraper, c'est ce qui bouge pendant qu'il est ferme -- d'ou la peremption
de db.PEREMPTION_JOURS, qui refait le scan au-dela de sept jours.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from assistant import config
from assistant.index import db
from assistant.util import matches

# Les evenements arrivent en rafale (un enregistrement de fichier en produit
# cinq). On accumule et on applique par paquets.
FLUSH_SECONDS = 2.0
MAX_PENDING = 5_000

BACKSLASH = "\\"


def watched_folders() -> list[str]:
    """Dossiers surveilles : la ou l'utilisateur cree et supprime des choses."""
    home = Path.home()
    candidats = [
        home / "Downloads",
        home / "Documents",
        home / "Desktop",
        home / "Pictures",
        home / "Videos",
        home / "Music",
    ]
    return [str(p) for p in candidats if p.is_dir()]


class Watcher:
    """Maintient l'index a jour a partir des evenements du systeme de fichiers."""

    def __init__(self, folders: list[str] | None = None):
        self.folders = folders if folders is not None else watched_folders()
        self._observer = None
        self._lock = threading.Lock()
        self._added: dict[str, tuple] = {}
        self._removed: set[str] = set()
        self._stop = threading.Event()
        self._flusher: threading.Thread | None = None
        self.applied = 0

    # --- collecte ---------------------------------------------------------

    def _row_for(self, path: str) -> tuple | None:
        """Construit la ligne d'index d'un chemin, ou None s'il a disparu."""
        try:
            st = os.stat(path)
            is_dir = os.path.isdir(path)
        except (OSError, ValueError):
            return None

        name = os.path.basename(path)
        if is_dir or "." not in name:
            ext = ""
        else:
            ext = name.rpartition(".")[2].lower()
            if len(ext) > 12:
                ext = ""

        return (
            path,
            name,
            os.path.dirname(path),
            ext,
            0 if is_dir else st.st_size,
            st.st_mtime,
            1 if is_dir else 0,
            1 if matches(path, config.CACHE_MARKERS) else 0,
            path[:2].upper(),
        )

    def note_created(self, path: str) -> None:
        if matches(path, config.EXCLUDED_DIRS):
            return
        row = self._row_for(path)
        if row is None:
            return
        with self._lock:
            if len(self._added) < MAX_PENDING:
                self._added[path] = row
            self._removed.discard(path)

    def note_deleted(self, path: str) -> None:
        with self._lock:
            self._added.pop(path, None)
            if len(self._removed) < MAX_PENDING:
                self._removed.add(path)

    # --- application ------------------------------------------------------

    def flush(self) -> int:
        """Applique les changements accumules a l'index en memoire."""
        with self._lock:
            ajouts = list(self._added.values())
            suppressions = list(self._removed)
            self._added.clear()
            self._removed.clear()

        if not ajouts and not suppressions:
            return 0
        if not db.is_ready():
            return 0

        conn = db.connect()
        try:
            # files_fts est une table FTS5 a contenu externe : elle ne suit
            # PAS automatiquement les modifications de la table files. Il faut
            # lui signaler chaque ligne, avec les valeurs qu'elle indexait.
            #
            # Surtout pas de reconstruction complete ici : elle reindexe les
            # 935 000 lignes, ce qui prend plusieurs secondes et finit par
            # corrompre la table quand deux flushes se chevauchent.
            if suppressions:
                for chemin in suppressions:
                    base = chemin.rstrip(BACKSLASH) + BACKSLASH
                    condamnes = conn.execute(
                        "SELECT id, name, path FROM files "
                        "WHERE path = ? OR (path >= ? AND path < ?)",
                        (chemin, base, base + "￿"),
                    ).fetchall()
                    for ligne in condamnes:
                        conn.execute(
                            "INSERT INTO files_fts(files_fts, rowid, name, path) "
                            "VALUES('delete', ?, ?, ?)",
                            (ligne["id"], ligne["name"], ligne["path"]),
                        )
                        conn.execute("DELETE FROM files WHERE id = ?",
                                     (ligne["id"],))

            for ligne in ajouts:
                # Une modification renvoie un chemin deja connu : on remplace
                # proprement plutot que de creer un doublon.
                existant = conn.execute(
                    "SELECT id, name, path FROM files WHERE path = ?",
                    (ligne[0],),
                ).fetchone()
                if existant:
                    conn.execute(
                        "INSERT INTO files_fts(files_fts, rowid, name, path) "
                        "VALUES('delete', ?, ?, ?)",
                        (existant["id"], existant["name"], existant["path"]),
                    )
                    conn.execute("DELETE FROM files WHERE id = ?",
                                 (existant["id"],))

                curseur = conn.execute(
                    "INSERT INTO files"
                    "(path, name, parent, ext, size, mtime, is_dir, is_cache, drive) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ligne,
                )
                conn.execute(
                    "INSERT INTO files_fts(rowid, name, path) VALUES (?, ?, ?)",
                    (curseur.lastrowid, ligne[1], ligne[0]),
                )

            conn.commit()
        except Exception:  # noqa: BLE001 - une mise a jour ratee n'est pas fatale
            conn.rollback()
            return 0
        finally:
            conn.close()

        total = len(ajouts) + len(suppressions)
        self.applied += total
        return total

    def _flush_loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(FLUSH_SECONDS)
            self.flush()

    # --- cycle de vie -----------------------------------------------------

    def start(self, on_change=None) -> bool:
        """Demarre la surveillance. False si watchdog est indisponible."""
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            return False

        watcher = self

        class Handler(FileSystemEventHandler):
            def on_created(self, event):
                watcher.note_created(event.src_path)
                if on_change:
                    on_change("cree", event.src_path)

            def on_deleted(self, event):
                watcher.note_deleted(event.src_path)
                if on_change:
                    on_change("supprime", event.src_path)

            def on_moved(self, event):
                watcher.note_deleted(event.src_path)
                watcher.note_created(event.dest_path)
                if on_change:
                    on_change("deplace", event.dest_path)

            def on_modified(self, event):
                # Seule la taille change : on rafraichit la ligne existante.
                if not event.is_directory:
                    watcher.note_created(event.src_path)

        self._observer = Observer()
        handler = Handler()
        surveilles = 0
        for folder in self.folders:
            try:
                self._observer.schedule(handler, folder, recursive=True)
                surveilles += 1
            except OSError:
                continue

        if not surveilles:
            return False

        self._observer.daemon = True
        self._observer.start()

        self._flusher = threading.Thread(target=self._flush_loop,
                                         name="index-flush", daemon=True)
        self._flusher.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._observer is not None:
            self._observer.stop()

    def status(self) -> str:
        if self._observer is None:
            return "Surveillance inactive."
        return (f"Surveillance active sur {len(self.folders)} dossier(s), "
                f"{self.applied} changement(s) pris en compte depuis le "
                "demarrage.")


_watcher: Watcher | None = None


def start(on_change=None) -> Watcher | None:
    """Demarre la surveillance globale, une seule fois."""
    global _watcher
    if _watcher is not None:
        return _watcher
    candidate = Watcher()
    if candidate.start(on_change):
        _watcher = candidate
        return _watcher
    return None


def status() -> str:
    return _watcher.status() if _watcher else "Surveillance inactive."
