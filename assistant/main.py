"""Assistant vocal : point d'entree.

    python -m assistant.main                 -> mot-cle + raccourci
    python -m assistant.main --no-wake       -> raccourci seul (zero CPU au repos)
    python -m assistant.main --micros        -> liste les micros
    python -m assistant.main --mic 11        -> force un micro
    python -m assistant.main --muet          -> repond a l'ecrit, sans voix

Dis le mot-cle (voir wake.WAKE_PHRASE), ou appuie sur Ctrl+Alt+Espace,
puis parle.
"""
from __future__ import annotations

import argparse
import sys

from assistant import llm
from assistant.index import db, scanner
from assistant.skills import files
from assistant.voice import stt, tts, wake

HOTKEY = "<ctrl>+<alt>+<space>"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Assistant vocal local")
    p.add_argument("--mic", type=int, default=None, help="index du micro")
    p.add_argument("--micros", action="store_true", help="liste les micros et sort")
    p.add_argument("--no-wake", action="store_true", help="desactive le mot-cle")
    p.add_argument("--muet", action="store_true", help="pas de synthese vocale")
    p.add_argument("--seuil", type=float, default=wake.WAKE_THRESHOLD,
                   help="sensibilite du mot-cle (0.3 laxiste, 0.7 strict)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.micros:
        for index, name in wake.list_microphones():
            print(f"  [{index:>2}] {name}")
        return 0

    ok, message = llm.available()
    print(f"  Modele   : {message}")
    if not ok:
        print("  Lance Ollama avant de demarrer l'assistant vocal.")
        return 1

    print("  Whisper  : chargement ...", end=" ", flush=True)
    print(stt.device_label())

    if db.is_ready():
        print(f"  Fichiers : {files.index_status().splitlines()[0]}")
    else:
        print("  Fichiers : scan en cours. L'index est conserve pour les "
              "lancements suivants.")
        scanner.rebuild_in_background(
            on_done=lambda s: print(
                f"  Fichiers : {s.get('files', 0):,} fichiers connus".replace(",", " ")
                if "error" not in s
                else f"  Fichiers : echec du scan ({s['error']})"
            )
        )

    loop = wake.VoiceLoop(
        device=args.mic,
        threshold=args.seuil,
        use_wake_word=not args.no_wake,
    )
    loop.start_hotkey(HOTKEY)

    if args.no_wake:
        print(f"  Declencheur : {HOTKEY} uniquement")
    else:
        print(f"  Declencheur : \"{wake.WAKE_PHRASE}\" ou {HOTKEY}")
    print()

    convo = llm.new_conversation()

    def on_trigger(trigger: wake.Trigger) -> None:
        detail = f" ({trigger.score})" if trigger.score else ""
        print(f"[{trigger.source}{detail}] je t'ecoute ...")

    def on_status(message: str) -> None:
        print(f"    {message}")

    def on_command(text: str) -> None:
        nonlocal convo
        print(f"  > {text}")
        convo.append({"role": "user", "content": text})
        try:
            answer, convo = llm.chat(
                convo, on_tool=lambda n, a: print(f"    ... {n}({a})")
            )
        except Exception as exc:  # noqa: BLE001
            answer = f"Erreur interne : {exc}"
            print(f"  ! {exc}")

        print(f"  < {answer}\n")
        if not args.muet:
            tts.say(answer)

        # Le contexte d'un modele local sature vite si on lui renvoie tout
        # l'historique des sorties d'outils.
        convo = llm.trim_conversation(convo)

    try:
        loop.run(on_command, on_trigger=on_trigger, on_status=on_status)
    except KeyboardInterrupt:
        print("\n  Arret.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
