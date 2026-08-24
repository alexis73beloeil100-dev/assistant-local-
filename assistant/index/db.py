"""Base d'index : schema SQLite + requetes de recherche.

Depuis le 24/08/2026, l'index est CONSERVE sur le disque : le demarrage est
immediat au lieu de couter quatre-vingts secondes de scan. Voir
config.PERSIST_INDEX, qui permet de revenir a l'index en memoire vive.

La liste des fichiers subsiste donc apres la fermeture, ce qui n'etait pas le
cas avant. Elle ne contient que des chemins, des tailles et des dates :
aucun contenu de fichier n'est jamais lu ni conserve.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Iterable, Iterator

from assistant import config

# Base en memoire partagee entre connexions. Le cache partage est essentiel :
# sans lui, chaque connexion aurait sa propre base vide, et fermer une
# connexion detruirait l'index.
MEMORY_URI = "file:assistant_index?mode=memory&cache=shared"

# Connexion gardienne : tant qu'elle est ouverte, la base en memoire existe.
_keeper: sqlite3.Connection | None = None
_keeper_lock = threading.Lock()

# L'index est construit en tache de fond : les requetes doivent savoir s'il
# est pret plutot que de lire une base a moitie remplie.
_ready = threading.Event()

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS files (
    id       INTEGER PRIMARY KEY,
    path     TEXT    NOT NULL,
    name     TEXT    NOT NULL,
    parent   TEXT    NOT NULL,
    ext      TEXT    NOT NULL DEFAULT '',
    size     INTEGER NOT NULL DEFAULT 0,
    mtime    REAL    NOT NULL DEFAULT 0,
    is_dir   INTEGER NOT NULL DEFAULT 0,
    is_cache INTEGER NOT NULL DEFAULT 0,
    drive    TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Crees apres le scan : les maintenir pendant l'insertion coute tres cher.
INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_files_path   ON files(path);
CREATE INDEX IF NOT EXISTS idx_files_name          ON files(name);
CREATE INDEX IF NOT EXISTS idx_files_ext           ON files(ext);
CREATE INDEX IF NOT EXISTS idx_files_size          ON files(size DESC);
CREATE INDEX IF NOT EXISTS idx_files_parent        ON files(parent);
CREATE INDEX IF NOT EXISTS idx_files_mtime         ON files(mtime DESC);
"""

# unicode61 + remove_diacritics : "resume" trouve "resume", "Resume", "resume".
FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    name,
    path,
    content='files',
    content_rowid='id',
    tokenize="unicode61 remove_diacritics 2 tokenchars '-_.'"
);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Ouvre une connexion vers l'index, sur disque ou en memoire."""
    global _keeper

    if path is not None or config.PERSIST_INDEX:
        conn = sqlite3.connect(path or config.DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    with _keeper_lock:
        if _keeper is None:
            _keeper = sqlite3.connect(MEMORY_URI, uri=True, check_same_thread=False)

    conn = sqlite3.connect(MEMORY_URI, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def is_ready() -> bool:
    """L'index est-il utilisable ?

    En memoire, il faut attendre la fin de la construction : interroger une
    base a moitie remplie donnerait des reponses fausses sans le dire.

    Sur disque, cette fonction se contentait de constater que le FICHIER
    existe. C'etait faux, et le 24/08/2026 en passant PERSIST_INDEX a True on
    l'a vu tout de suite : sqlite3.connect() cree le fichier au premier
    acces, meme pour une simple lecture. Un fichier vide suffisait donc a
    faire dire "index pret", et toutes les recherches tombaient sur
    "no such table: files" -- l'assistant se declarait pret et ne repondait
    rien. Un scan interrompu laisse exactement le meme etat.

    On constate donc la table ET une ligne dedans, pas le fichier.
    """
    if not config.PERSIST_INDEX:
        return _ready.is_set()

    if not config.DB_PATH.exists():
        return False
    try:
        conn = sqlite3.connect(config.DB_PATH)
        try:
            existe = conn.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'files'").fetchone()
            if existe is None:
                return False
            return conn.execute(
                "SELECT 1 FROM files LIMIT 1").fetchone() is not None
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def mark_ready(ready: bool = True) -> None:
    _ready.set() if ready else _ready.clear()


# Au-dela de cet age, un index conserve est refait au demarrage.
#
# Un index en memoire etait forcement frais : il naissait avec le processus.
# Conserve, il ne l'est plus. La surveillance rattrape ce qui bouge PENDANT
# que l'assistant tourne, mais rien de ce qui a bouge pendant qu'il etait
# ferme -- une installation, un grand menage, un disque rempli le week-end.
# Sans peremption, l'assistant repondrait avec assurance sur des fichiers
# effaces depuis des mois.
PEREMPTION_JOURS = 7


def age_de_l_index() -> float | None:
    """Age du dernier scan complet, en jours. None si la question n'a pas lieu.

    Lu dans meta.scanned_at, et pas sur la date du fichier : la surveillance
    ecrit dans la base a chaque fichier touche, ce qui rajeunirait la date du
    fichier sans que l'index ait ete refait.
    """
    if not config.PERSIST_INDEX or not config.DB_PATH.exists():
        return None
    from datetime import datetime

    try:
        conn = connect()
        try:
            quand = get_meta(conn, "scanned_at", "")
        finally:
            conn.close()
        if not quand:
            return None
        return (datetime.now() - datetime.fromisoformat(quand)).total_seconds() / 86400
    except (sqlite3.Error, ValueError, OSError):
        return None


def index_perime() -> bool:
    """Faut-il refaire le scan complet ?"""
    age = age_de_l_index()
    return age is not None and age > PEREMPTION_JOURS


def wait_ready(timeout: float | None = None) -> bool:
    return _ready.wait(timeout)


def reset_memory() -> None:
    """Vide l'index en memoire (utilise avant une reconstruction)."""
    global _keeper
    with _keeper_lock:
        _ready.clear()
        if _keeper is not None:
            _keeper.close()
            _keeper = None


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.executescript(FTS)
    conn.commit()


def create_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(INDEXES)
    conn.commit()


def rebuild_fts(conn: sqlite3.Connection) -> None:
    """Reconstruit l'index plein texte a partir de la table files."""
    conn.execute("INSERT INTO files_fts(files_fts) VALUES('rebuild')")
    conn.commit()


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def insert_batch(conn: sqlite3.Connection, rows: Iterable[tuple]) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO files"
        "(path, name, parent, ext, size, mtime, is_dir, is_cache, drive) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


# --- Recherche --------------------------------------------------------------

def _fts_query(text: str) -> str:
    """Transforme une requete humaine en syntaxe FTS5 sure.

    Chaque mot devient un prefixe : "moza ffb" -> "moza"* AND "ffb"*.
    Les guillemets neutralisent les caracteres que FTS5 interprete.
    """
    words = [w for w in text.replace('"', " ").split() if w]
    if not words:
        return '""'
    return " AND ".join(f'"{w}"*' for w in words)


def search(
    conn: sqlite3.Connection,
    text: str,
    limit: int = 30,
    ext: str | None = None,
    dirs_only: bool = False,
    include_cache: bool = False,
) -> list[sqlite3.Row]:
    """Recherche par nom/chemin, la plus pertinente en premier."""
    where = ["files_fts MATCH ?"]
    params: list = [_fts_query(text)]

    if ext:
        where.append("f.ext = ?")
        params.append(ext.lower().lstrip("."))
    if dirs_only:
        where.append("f.is_dir = 1")
    if not include_cache:
        where.append("f.is_cache = 0")

    sql = f"""
        SELECT f.path, f.name, f.ext, f.size, f.mtime, f.is_dir, f.is_cache
        FROM files_fts
        JOIN files f ON f.id = files_fts.rowid
        WHERE {' AND '.join(where)}
        ORDER BY bm25(files_fts, 10.0, 1.0), f.mtime DESC
        LIMIT ?
    """
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def largest(
    conn: sqlite3.Connection,
    limit: int = 25,
    under: str | None = None,
    ext: str | None = None,
) -> list[sqlite3.Row]:
    """Les plus gros fichiers, eventuellement sous un dossier donne."""
    where = ["is_dir = 0"]
    params: list = []
    if under:
        where.append("path LIKE ?")
        params.append(under.rstrip("\\") + "\\%")
    if ext:
        where.append("ext = ?")
        params.append(ext.lower().lstrip("."))

    sql = f"""
        SELECT path, name, ext, size, mtime, is_cache
        FROM files WHERE {' AND '.join(where)}
        ORDER BY size DESC LIMIT ?
    """
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def dir_sizes(conn: sqlite3.Connection, under: str, limit: int = 25) -> list[sqlite3.Row]:
    """Poids total des sous-dossiers directs de `under`.

    Somme recursive : chaque fichier est attribue au sous-dossier de premier
    niveau qui le contient.
    """
    base = under.rstrip("\\") + "\\"
    sql = """
        SELECT
            substr(path, 1, instr(substr(path, ?), '\\') + ? - 1) AS bucket,
            SUM(size) AS total,
            COUNT(*)  AS n
        FROM files
        WHERE is_dir = 0 AND path LIKE ?
        GROUP BY bucket
        ORDER BY total DESC
        LIMIT ?
    """
    return conn.execute(sql, (len(base) + 1, len(base), base + "%", limit)).fetchall()


def recent(conn: sqlite3.Connection, limit: int = 25, ext: str | None = None) -> list[sqlite3.Row]:
    where = ["is_dir = 0", "is_cache = 0"]
    params: list = []
    if ext:
        where.append("ext = ?")
        params.append(ext.lower().lstrip("."))
    sql = f"""
        SELECT path, name, ext, size, mtime FROM files
        WHERE {' AND '.join(where)}
        ORDER BY mtime DESC LIMIT ?
    """
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def duplicates(conn: sqlite3.Connection, min_size: int = 10 * 1024 * 1024,
               limit: int = 30) -> list[sqlite3.Row]:
    """Candidats doublons : meme nom ET meme taille, au moins 2 copies.

    Rapide car sans lecture disque. A confirmer par hash avant toute action.
    """
    sql = """
        SELECT name, size, COUNT(*) AS copies,
               SUM(size) - size AS wasted,
               GROUP_CONCAT(path, '|') AS paths
        FROM files
        WHERE is_dir = 0 AND size >= ?
        GROUP BY name, size
        HAVING copies > 1
        ORDER BY wasted DESC
        LIMIT ?
    """
    return conn.execute(sql, (min_size, limit)).fetchall()


def stats(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS n, SUM(size) AS total, "
        "SUM(is_dir) AS dirs, SUM(is_cache) AS cached FROM files"
    ).fetchone()
    return {
        "files": (row["n"] or 0) - (row["dirs"] or 0),
        "dirs": row["dirs"] or 0,
        "bytes": row["total"] or 0,
        "cache_entries": row["cached"] or 0,
        "scanned_at": get_meta(conn, "scanned_at", "jamais"),
        "scan_seconds": get_meta(conn, "scan_seconds", "?"),
    }
