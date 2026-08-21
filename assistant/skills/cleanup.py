"""Nettoyage disque : proposer, puis agir seulement sur accord.

Deux regles absolues ici :
  - rien n'est supprime definitivement, tout part a la corbeille ;
  - rien ne part sans passer par assistant.safety.guard().

L'index sert a chiffrer les candidats sans relire le disque, mais chaque
candidat est reverifie sur le disque avant suppression : l'index est une
photographie, il peut avoir vieilli.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from assistant import safety
from assistant.index import db
from assistant.skills.files import needs_index
from assistant.util import human_size, norm


@dataclass
class Candidate:
    path: str
    size: int
    label: str
    why: str
    caution: str = ""       # non vide = a lire avant d'accepter


def _bounds(folder: str) -> tuple[str, str]:
    """Bornes d'un sous-arbre, pour une comparaison d'intervalle.

    "path LIKE 'C:/x/%'" oblige SQLite a parcourir le million de lignes :
    LIKE est insensible a la casse par defaut, donc inexploitable avec un
    index binaire. Un encadrement path >= debut AND path < fin utilise
    l'index et fait tomber le rapport de plusieurs minutes a une seconde.
    """
    base = folder.rstrip("\\") + "\\"
    return base, base + "\uffff"


def _size_of(conn, folder: str) -> int:
    low, high = _bounds(folder)
    row = conn.execute(
        "SELECT COALESCE(SUM(size), 0) AS total FROM files "
        "WHERE path >= ? AND path < ? AND is_dir = 0",
        (low, high),
    ).fetchone()
    return row["total"] or 0


def epic_orphans(conn) -> list[Candidate]:
    """Dossiers .egstore dont le jeu n'est plus installe.

    Epic garde dans .egstore les blocs de reparation et de mise a jour. Quand
    le jeu est desinstalle a la main ou que l'installation a echoue, ce dossier
    reste seul : des dizaines de Go qui ne servent plus a rien.
    """
    rows = conn.execute(
        "SELECT DISTINCT path FROM files WHERE is_dir = 1 AND name = '.egstore'"
    ).fetchall()

    out = []
    for row in rows:
        egstore = row["path"]
        parent = str(Path(egstore).parent)

        # Le jeu est-il encore la ? On compte ce qui existe a cote de .egstore.
        p_low, p_high = _bounds(parent)
        e_low, e_high = _bounds(egstore)
        siblings = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(size), 0) AS total FROM files "
            "WHERE path >= ? AND path < ? AND is_dir = 0 "
            "AND NOT (path >= ? AND path < ?)",
            (p_low, p_high, e_low, e_high),
        ).fetchone()

        size = _size_of(conn, egstore)
        if size < 100 * 1024**2:
            continue

        if siblings["n"] == 0:
            out.append(
                Candidate(
                    path=egstore,
                    size=size,
                    label=f"Residus Epic de {Path(parent).name}",
                    why=(
                        "Le dossier du jeu ne contient plus que .egstore : le jeu "
                        "lui-meme n'est plus installe, seuls les blocs de "
                        "reparation Epic restent."
                    ),
                )
            )
        else:
            out.append(
                Candidate(
                    path=egstore,
                    size=size,
                    label=f"Cache de reparation Epic de {Path(parent).name}",
                    why=(
                        f"Le jeu est toujours installe "
                        f"({human_size(siblings['total'])} a cote)."
                    ),
                    caution=(
                        "Supprimer ce cache oblige Epic a retelecharger en cas "
                        "de verification de fichiers."
                    ),
                )
            )
    return out


def temp_folders(conn) -> list[Candidate]:
    """Dossiers temporaires : ce qui se supprime sans rien casser."""
    targets = [
        (os.environ.get("TEMP", ""), "Temporaires utilisateur"),
        (r"C:\Windows\Temp", "Temporaires Windows"),
        (str(Path.home() / r"AppData\Local\CrashDumps"), "Rapports de plantage"),
        (str(Path.home() / r"AppData\Local\D3DSCache"), "Cache de shaders Direct3D"),
        (str(Path.home() / r"AppData\Local\NVIDIA\DXCache"), "Cache de shaders NVIDIA"),
    ]
    out = []
    for path, label in targets:
        if not path or not os.path.isdir(path):
            continue
        size = _size_of(conn, path)
        if size < 200 * 1024**2:
            continue
        out.append(
            Candidate(
                path=path,
                size=size,
                label=label,
                why="Contenu regenere automatiquement par Windows ou les pilotes.",
                caution=(
                    "Le premier lancement des jeux sera un peu plus long, "
                    "le temps que les shaders se recompilent."
                    if "hader" in label
                    else ""
                ),
            )
        )
    return out


def unreal_caches(conn) -> list[Candidate]:
    """Caches Unreal : gros, mais tres couteux a reconstruire."""
    rows = conn.execute(
        "SELECT DISTINCT path FROM files WHERE is_dir = 1 "
        "AND (name = 'DerivedDataCache' OR name = 'Intermediate')"
    ).fetchall()

    out = []
    for row in rows:
        size = _size_of(conn, row["path"])
        if size < 500 * 1024**2:
            continue
        out.append(
            Candidate(
                path=row["path"],
                size=size,
                label=f"Cache Unreal ({Path(row['path']).name})",
                why="Reconstruit automatiquement par l'editeur.",
                caution=(
                    "ATTENTION : sa suppression coute des heures de recompilation "
                    "de shaders au prochain ouverture du projet. A ne faire que si "
                    "tu as vraiment besoin de la place."
                ),
            )
        )
    return out


def candidates() -> list[Candidate]:
    """Tout ce qui est recuperable, du plus gros au plus petit."""
    conn = db.connect()
    try:
        found = epic_orphans(conn) + temp_folders(conn) + unreal_caches(conn)
    finally:
        conn.close()
    return sorted(found, key=lambda c: c.size, reverse=True)


@needs_index
def report() -> str:
    found = candidates()
    if not found:
        return "Rien de significatif a nettoyer."

    total = sum(c.size for c in found)
    safe = sum(c.size for c in found if not c.caution)

    lines = [
        f"{human_size(total)} recuperables, dont {human_size(safe)} sans aucune "
        f"contrepartie.",
        "",
    ]
    for i, c in enumerate(found, 1):
        lines.append(f"  {i}. {human_size(c.size):>12}  {c.label}")
        lines.append(f"      {c.path}")
        lines.append(f"      {c.why}")
        if c.caution:
            lines.append(f"      /!\\ {c.caution}")
        lines.append("")
    lines.append("Rien n'a ete supprime. Utilise 'nettoyer <numeros>' pour agir.")
    return "\n".join(lines)


@needs_index
def clean(indexes: list[int], ask=None) -> str:
    """Envoie a la corbeille les candidats choisis, apres confirmation."""
    found = candidates()
    chosen = []
    for i in indexes:
        if 1 <= i <= len(found):
            chosen.append(found[i - 1])
        else:
            return f"Numero {i} hors de la liste (1 a {len(found)})."
    if not chosen:
        return "Rien de selectionne."

    # L'index peut avoir vieilli : on revalide sur le disque.
    missing = [c.path for c in chosen if not os.path.isdir(c.path)]
    if missing:
        return (
            "Ces dossiers ne sont plus la, l'index a vieilli. Relance 'scan' :\n  "
            + "\n  ".join(missing)
        )

    total = sum(c.size for c in chosen)
    action = safety.Action(
        kind="fichier",
        summary=f"Envoyer {human_size(total)} a la corbeille",
        targets=[c.path for c in chosen],
        reversible=True,
        details="Corbeille, donc restaurable tant que tu ne la vides pas.",
    )

    try:
        safety.guard(action, ask=ask)
    except safety.Refused as exc:
        return str(exc)

    from send2trash import send2trash

    done, failed = [], []
    for c in chosen:
        try:
            send2trash(c.path)
            done.append(f"  {human_size(c.size):>12}  {c.label}")
        except Exception as exc:  # noqa: BLE001
            failed.append(f"  {c.label} : {type(exc).__name__}: {exc}")

    out = []
    if done:
        out.append(f"Envoye a la corbeille ({human_size(total)}) :")
        out.extend(done)
    if failed:
        out.append("Echecs :")
        out.extend(failed)
    out.append("")
    out.append("Relance 'scan' pour remettre l'index a jour.")
    return "\n".join(out)


# --- Retour en arriere -------------------------------------------------------

# Colonne du dossier special "Corbeille" qui contient l'emplacement d'origine.
# C'est la colonne 1 sur Windows 10 et 11, mais on ne s'y fie pas : le libelle
# et l'ordre changent selon la version et la langue. On la cherche.
_COLONNES_A_SONDER = 12


def _verbe_restaurer(element) -> object | None:
    """Le verbe "Restaurer" du menu contextuel, quelle que soit la langue.

    Il s'appelle "R&estaurer" en francais et "&Restore" en anglais -- le "&"
    marque la lettre soulignee et n'est pas dans le nom affiche. On le retire
    avant de comparer, et on accepte les deux racines.
    """
    for verbe in element.Verbs():
        nom = str(verbe.Name).replace("&", "").casefold()
        if nom.startswith("restaur") or nom.startswith("restor"):
            return verbe
    return None


def _origine(corbeille, element) -> str:
    """Chemin qu'occupait l'element avant sa suppression."""
    import os

    for colonne in range(_COLONNES_A_SONDER):
        valeur = str(corbeille.GetDetailsOf(element, colonne) or "")
        # Un emplacement d'origine est un chemin absolu : il porte une lettre
        # de lecteur. Les autres colonnes sont des dates et des tailles.
        if ":\\" in valeur:
            return os.path.join(valeur, str(element.Name))
    return ""


def restaurer(chemins: list[str]) -> tuple[bool, str]:
    """Ressort de la corbeille exactement les dossiers qu'on y a envoyes.

    On ne restaure QUE les chemins demandes : la corbeille contient aussi ce
    que l'utilisateur y a mis lui-meme, et tout ressortir en bloc serait une
    surprise desagreable.
    """
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return False, ("La restauration demande pywin32, qui n'est pas "
                       "installe. Ouvre la corbeille pour le faire a la main.")

    # COM appartient au thread qui l'initialise, et l'interface travaille dans
    # des threads de fond. Sans cet appel, la corbeille est illisible.
    try:
        pythoncom.CoInitialize()
    except Exception:  # noqa: BLE001 - deja initialise dans ce thread
        pass

    voulus = {norm(c) for c in chemins}
    if not voulus:
        return False, "Aucun chemin a restaurer."

    try:
        shell = win32com.client.Dispatch("Shell.Application")
        corbeille = shell.Namespace(10)      # 10 = ssfBITBUCKET, la corbeille
        elements = corbeille.Items()
    except Exception as exc:  # noqa: BLE001
        return False, f"Corbeille illisible : {type(exc).__name__}: {exc}"

    restaures, echecs = [], []
    introuvables = set(voulus)

    for index in range(elements.Count):
        element = elements.Item(index)
        origine = _origine(corbeille, element)
        if not origine or norm(origine) not in voulus:
            continue

        introuvables.discard(norm(origine))
        verbe = _verbe_restaurer(element)
        if verbe is None:
            echecs.append(f"  {origine} : aucun verbe de restauration")
            continue
        try:
            verbe.DoIt()
            restaures.append(f"  {origine}")
        except Exception as exc:  # noqa: BLE001
            echecs.append(f"  {origine} : {type(exc).__name__}")

    lignes = []
    if restaures:
        lignes.append(f"Ressorti de la corbeille ({len(restaures)}) :")
        lignes.extend(restaures)
    if introuvables:
        lignes.append("Plus dans la corbeille (deja restaure, ou corbeille "
                      "videe) :")
        lignes.extend(f"  {c}" for c in sorted(introuvables))
    if echecs:
        lignes.append("Echecs :")
        lignes.extend(echecs)
    if restaures:
        lignes.append("")
        lignes.append("Relance 'scan' pour remettre l'index a jour.")

    return bool(restaures), "\n".join(lignes) or "Rien a restaurer."
