"""Point d'entree en texte.

    python -m assistant.cli              -> conversation avec le modele local
    python -m assistant.cli scan         -> reconstruit l'index des disques
    python -m assistant.cli etat         -> etat de la machine
    python -m assistant.cli diag         -> diagnostic de lenteur
    python -m assistant.cli jeux         -> jeux installes
    python -m assistant.cli jouer <nom>  -> lance un jeu
    python -m assistant.cli cherche <q>  -> recherche dans l'index
"""
from __future__ import annotations

import sys

from assistant import config, llm, startup
from assistant.index import db, scanner
from assistant.skills import files, games, system


def ensure_index() -> None:
    """Garantit un index utilisable avant une commande qui en depend.

    En mode memoire, une commande ponctuelle doit reconstruire l'index : il
    n'a pas survecu a la fermeture precedente, c'est precisement le but.
    L'assistant resident, lui, ne paie ce cout qu'une fois au demarrage.
    """
    if db.is_ready():
        return
    if config.PERSIST_INDEX:
        print("Aucun index. Lance 'scan' d'abord.")
        return
    print("L'index vit en memoire et repart de zero a chaque lancement.")
    print("Construction (environ 80 secondes) ...")
    scanner.rebuild(verbose=True)
    print()

BANNER = r"""
  Assistant local  --  tout reste sur cette machine
"""


def cmd_scan(args: list[str]) -> None:
    print("Reconstruction de l'index (quelques minutes) ...")
    stats = scanner.rebuild(verbose=True)
    print()
    print(files.index_status())


def cmd_etat(args: list[str]) -> None:
    print(system.report())


def cmd_diag(args: list[str]) -> None:
    print(system.diagnose())


def cmd_jeux(args: list[str]) -> None:
    found = games.all_games()
    if not found:
        print("Aucun jeu detecte.")
        return
    print(f"{len(found)} jeux installes :")
    for g in found:
        size = f"{g.size_bytes / 1e9:.1f} Go" if g.size_bytes else ""
        print(f"  {g.name:<45} {g.launcher:<9} {size}")


def cmd_jouer(args: list[str]) -> None:
    if not args:
        print("Precise le nom du jeu.")
        return
    ok, message = games.launch(" ".join(args))
    print(message)


def cmd_cherche(args: list[str]) -> None:
    ensure_index()
    if not args:
        print("Precise ce que tu cherches.")
        return
    print(files.search(" ".join(args)))


def cmd_gros(args: list[str]) -> None:
    ensure_index()
    print(files.biggest(under=args[0] if args else None))


def cmd_caches(args: list[str]) -> None:
    ensure_index()
    print(files.caches())


def cmd_doublons(args: list[str]) -> None:
    ensure_index()
    print(files.duplicates())


def cmd_demarrage(args: list[str]) -> None:
    for item in system.startup_items():
        print(f"  [{item['source']}] {item['name']}")
        print(f"        {item['command'][:110]}")


def cmd_demarrage_auto(args: list[str]) -> None:
    """Active ou desactive le lancement avec la session Windows."""
    choice = (args[0].lower() if args else "status")
    if choice in ("on", "oui", "active"):
        print(startup.enable())
    elif choice in ("off", "non", "desactive"):
        print(startup.disable())
    else:
        active, command = startup.status()
        print("  actif" if active else "  inactif")
        if active:
            print(f"  {command}")



COMMANDS = {
    "scan": cmd_scan,
    "etat": cmd_etat,
    "diag": cmd_diag,
    "jeux": cmd_jeux,
    "jouer": cmd_jouer,
    "cherche": cmd_cherche,
    "gros": cmd_gros,
    "caches": cmd_caches,
    "doublons": cmd_doublons,
    "demarrage": cmd_demarrage,
    "demarrage-auto": cmd_demarrage_auto,
}


def repl() -> None:
    """Conversation libre avec le modele local."""
    print(BANNER)
    ok, message = llm.available()
    print(f"  Modele : {message}")
    if not ok:
        print("  Demarre Ollama, ou lance les sous-commandes directes "
              "(etat, diag, jeux, cherche ...).")
        return
    if db.is_ready():
        print(f"  {files.index_status().splitlines()[0]}")
    else:
        print("  Fichiers : scan en cours en tache de fond, "
              "rien n'est ecrit sur le disque.")
        scanner.rebuild_in_background(
            on_done=lambda s: print(
                f"\n  [fichiers] {s.get('files', 0):,} fichiers connus, "
                f"en memoire uniquement.\n> ".replace(",", " ")
                if "error" not in s
                else f"\n  [fichiers] echec du scan : {s['error']}\n> "
            )
        )
    print("  Tape ta demande, ou 'quit' pour sortir.\n")

    convo = llm.new_conversation()
    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not question:
            continue
        if question.lower() in ("quit", "exit", "q"):
            return

        convo.append({"role": "user", "content": question})
        try:
            answer, convo = llm.chat(
                convo,
                on_tool=lambda name, args: print(f"  ... {name}({args})"),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  Erreur : {exc}")
            continue
        print(f"\n{answer}\n")

        # La conversation est bornee : un modele local sature vite son
        # contexte si on lui renvoie tout l'historique des resultats d'outils.
        convo = llm.trim_conversation(convo)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        repl()
        return 0

    command, *rest = argv
    handler = COMMANDS.get(command.lower())
    if not handler:
        print(__doc__)
        return 1
    handler(rest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
