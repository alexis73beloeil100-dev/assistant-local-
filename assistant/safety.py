"""Garde-fou : lecture libre, ecriture confirmee.

Toute fonction qui modifie la machine (registre, service, fichier, reglage
de jeu) passe par `guard()`. Rien ne s'execute sans un accord explicite, et
certains chemins sont refuses meme si tu dis oui.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from assistant import config
from assistant.util import norm

AUDIT_LOG = config.LOG_DIR / "actions.jsonl"


class Refused(Exception):
    """Action refusee : chemin protege, ou refus de l'utilisateur."""


@dataclass
class Action:
    """Une modification proposee, decrite avant d'etre faite."""

    kind: str                 # "fichier", "registre", "service", "processus"
    summary: str              # une ligne, lisible a voix haute
    targets: list[str] = field(default_factory=list)
    reversible: bool = True
    details: str = ""
    # Comment revenir en arriere, sous la forme {"operation": ..., "args": ...}.
    #
    # `reversible` disait seulement qu'un retour etait concevable ; personne ne
    # savait comment le faire, et le journal restait en lecture seule. On
    # enregistre desormais le moyen exact, au moment ou l'action est faite --
    # c'est le seul moment ou on le connait encore. Les operations disponibles
    # sont listees dans assistant.annulation.
    annulation: dict | None = None

    def describe(self) -> str:
        lines = [f"[{self.kind}] {self.summary}"]
        for t in self.targets[:10]:
            lines.append(f"    - {t}")
        if len(self.targets) > 10:
            lines.append(f"    ... et {len(self.targets) - 10} autres")
        if self.details:
            lines.append(f"    {self.details}")
        if not self.reversible:
            lines.append("    /!\\ IRREVERSIBLE")
        return "\n".join(lines)


def is_protected(path: str) -> bool:
    p = norm(path)
    return any(p.startswith(prot) for prot in config.PROTECTED_PATHS)


def _audit(action: Action, verdict: str) -> str:
    """Ecrit une ligne dans le journal et rend son identifiant."""
    identifiant = uuid.uuid4().hex[:12]
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "id": identifiant,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": action.kind,
        "summary": action.summary,
        "targets": action.targets,
        "verdict": verdict,
    }
    # Une action refusee n'a rien fait : lui proposer une annulation n'aurait
    # aucun sens, et ferait croire qu'elle a eu lieu.
    if action.annulation and verdict == "accepte":
        entry["annulation"] = action.annulation
    with AUDIT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return identifiant


def noter_annulation(entry_id: str, message: str, ok: bool) -> None:
    """Consigne qu'une entree du journal vient d'etre annulee.

    Le journal est ecrit en ajout seul, jamais reecrit : c'est un journal
    d'audit, et une ligne qu'on peut modifier apres coup ne prouve plus rien.
    L'annulation est donc une NOUVELLE ligne qui designe la precedente.
    """
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "id": uuid.uuid4().hex[:12],
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": "annulation",
        "summary": message,
        "targets": [],
        "verdict": "accepte" if ok else "echec",
        "annule": entry_id,
    }
    with AUDIT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


# Fonction chargee de demander l'accord de l'utilisateur. L'interface
# graphique en enregistre une au demarrage ; sans elle, on retombe sur le
# terminal.
_asker = None


def set_asker(fn) -> None:
    """Definit comment demander l'accord de l'utilisateur.

    L'interface graphique enregistre ici sa fenetre de confirmation. Sans
    cela, guard() se rabat sur le terminal -- et une application packagee en
    mode fenetre n'en a pas : la demande echouait sur "lost sys.stdin" et
    TOUTE action du modele plantait.
    """
    global _asker
    _asker = fn


def guard(action: Action, ask=None) -> bool:
    """Valide une action avant execution.

    `ask` recoit le texte de l'action et renvoie True/False. Par defaut on
    demande dans le terminal. Tout est journalise dans data/logs/actions.jsonl,
    accepte comme refuse : tu peux toujours savoir ce que l'assistant a fait.
    """
    for target in action.targets:
        if is_protected(target):
            _audit(action, "refuse:protege")
            raise Refused(
                f"{target} est dans les chemins proteges (config.PROTECTED_PATHS). "
                "Je ne touche pas a ca, meme sur confirmation."
            )

    if not config.REQUIRE_CONFIRMATION:
        _audit(action, "auto")
        return True

    ask = ask or _asker or _ask_terminal
    try:
        ok = bool(ask(action.describe()))
    except (RuntimeError, EOFError, OSError) as exc:
        # Aucune facon de demander : pas de console, pas d'interface. On
        # refuse plutot que de laisser passer une action non confirmee.
        _audit(action, "refuse:impossible-de-demander")
        raise Refused(
            "Impossible de demander confirmation "
            f"({type(exc).__name__}). L'action n'a pas ete effectuee."
        ) from exc
    _audit(action, "accepte" if ok else "refuse:utilisateur")
    if not ok:
        raise Refused("Action annulee.")
    return True


def _ask_terminal(text: str) -> bool:
    print()
    print(text)
    answer = input("  Confirmer ? [o/N] ").strip().lower()
    return answer in ("o", "oui", "y", "yes")


def history(limit: int = 20) -> list[dict]:
    """Les dernieres actions proposees, avec leur verdict."""
    if not AUDIT_LOG.exists():
        return []
    lines = AUDIT_LOG.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
