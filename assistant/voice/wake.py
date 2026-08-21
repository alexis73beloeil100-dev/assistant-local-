"""Boucle vocale : mot-cle permanent + raccourci clavier.

Un seul flux micro pour tout. Ouvrir un deuxieme flux pour enregistrer la
commande pendant que le detecteur tient deja le peripherique donne, selon les
pilotes, soit une erreur soit un enregistrement muet. On lit donc le micro a
un seul endroit et on bascule entre deux modes : guet et enregistrement.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16_000
CHUNK = 1280            # 80 ms : la taille attendue par openWakeWord

# Score au-dela duquel on considere le mot-cle prononce. 0.5 est le defaut
# recommande ; monte a 0.6-0.7 si le micro declenche tout seul.
WAKE_THRESHOLD = 0.5

# Apres un declenchement, on ignore le detecteur un instant : le mot-cle
# resterait dans la fenetre glissante et se redeclencherait en boucle.
WAKE_COOLDOWN = 2.0

# Apres le mot-cle, personne ne peut cliquer pour dire "j'ai fini" : il faut
# bien detecter la fin de phrase. Mais la version naive coupait sur un simple
# pic de bruit -- mesure faite sur ce PC : "parole detectee" a 2,3 s puis
# arret a 6,2 s alors que personne n'avait parle. Trois regles corrigent ca.

# 1. Il faut plusieurs blocs consecutifs au-dessus du seuil pour croire a de
#    la parole. Un claquement de clavier ne dure qu'un bloc.
BLOCS_PAROLE = 4                 # 4 x 80 ms = 320 ms de son continu

# 2. On n'arrete jamais avant ce delai, meme si tout semble silencieux : une
#    hesitation au debut de la phrase ne doit pas couper l'enregistrement.
DUREE_MINIMALE = 2.5

# 3. Le silence exige est plus long qu'avant : on prefere une seconde de trop
#    a une phrase tronquee.
SILENCE_TO_STOP = 1.5

MAX_UTTERANCE = 15.0
LEAD_IN = 6.0           # secondes max d'attente avant que tu commences a parler


@dataclass
class Trigger:
    source: str         # "mot-cle" ou "raccourci"
    score: float = 0.0


class VoiceLoop:
    """Ecoute en continu et rend les commandes transcrites."""

    def __init__(
        self,
        wake_model: str = "hey_jarvis",
        device: int | None = None,
        threshold: float = WAKE_THRESHOLD,
        use_wake_word: bool = True,
    ):
        self.device = device
        self.threshold = threshold
        self.use_wake_word = use_wake_word
        self.wake_model = wake_model
        self._forced = threading.Event()
        self._stop = threading.Event()
        self._oww = None
        self._hotkey = None
        # Estimation continue du bruit de fond, entretenue pendant le guet.
        self._noise_floor = 0.005

    # --- mot-cle ---------------------------------------------------------

    def _load_wake(self):
        if self._oww is not None or not self.use_wake_word:
            return
        import openwakeword
        from openwakeword.model import Model

        openwakeword.utils.download_models([self.wake_model])
        self._oww = Model(
            wakeword_models=[self.wake_model], inference_framework="onnx"
        )

    # --- raccourci clavier ------------------------------------------------

    def start_hotkey(self, combo: str = "<ctrl>+<alt>+<space>") -> None:
        """Ecoute globale d'un raccourci, meme quand un jeu a le focus.

        Indispensable en jeu ou en vocal : le mot-cle se declencherait sur ce
        que disent les autres, ou serait couvert par le son du jeu.
        """
        from pynput import keyboard

        def on_press():
            self._forced.set()

        self._hotkey = keyboard.GlobalHotKeys({combo: on_press})
        self._hotkey.daemon = True
        self._hotkey.start()

    def trigger_now(self) -> None:
        """Declenche l'ecoute par programme (bouton, test, autre thread)."""
        self._forced.set()

    def stop(self) -> None:
        self._stop.set()

    # --- boucle -----------------------------------------------------------

    def run(self, on_command, on_trigger=None, on_status=None) -> None:
        """Boucle principale.

        on_command(texte)  : appele avec chaque commande transcrite
        on_trigger(Trigger): appele des le declenchement, avant l'enregistrement
        on_status(texte)   : messages d'etat pour l'affichage
        """
        self._load_wake()
        say = on_status or (lambda _msg: None)

        with sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            blocksize=CHUNK, device=self.device,
        ) as stream:
            say("Ecoute active.")
            last_wake = 0.0

            while not self._stop.is_set():
                block, overflowed = stream.read(CHUNK)
                if overflowed:
                    continue
                mono = block[:, 0]

                # Suivi du bruit de fond : descend vite vers le calme, remonte
                # lentement, pour ne pas se caler sur la voix elle-meme.
                level = float(np.sqrt(np.mean(mono**2)))
                weight = 0.1 if level < self._noise_floor else 0.005
                self._noise_floor = (
                    (1 - weight) * self._noise_floor + weight * level
                )

                trigger = None
                if self._forced.is_set():
                    self._forced.clear()
                    trigger = Trigger("raccourci")
                elif self._oww is not None and time.time() - last_wake > WAKE_COOLDOWN:
                    # openWakeWord travaille en entiers 16 bits.
                    pcm = (mono * 32767).astype(np.int16)
                    scores = self._oww.predict(pcm)
                    best = max(scores.values()) if scores else 0.0
                    if best >= self.threshold:
                        last_wake = time.time()
                        trigger = Trigger("mot-cle", round(float(best), 3))

                if trigger is None:
                    continue

                if on_trigger:
                    on_trigger(trigger)

                audio = self._record(stream)
                if audio.size == 0:
                    say("Rien entendu.")
                    continue

                say("Transcription ...")
                from assistant.voice import stt

                text = stt.transcribe(audio)
                if text:
                    on_command(text)
                else:
                    say("Transcription vide.")

                # Le detecteur a accumule l'audio de la commande : on le remet
                # a zero pour qu'il ne redeclenche pas sur ce qu'on vient de dire.
                if self._oww is not None:
                    self._oww.reset()

    def _record(self, stream) -> np.ndarray:
        """Enregistre la commande sur le flux deja ouvert."""
        from assistant.voice import stt

        frames: list[np.ndarray] = []
        heard = False
        consecutifs = 0
        silence_since = None

        # Le mot-cle vient d'etre prononce : le bruit de fond a ete mesure
        # juste avant, pendant le guet, ce qui evite de faire attendre.
        threshold = stt.speech_threshold(self._noise_floor)
        started = time.time()

        while not self._stop.is_set():
            block, _ = stream.read(CHUNK)
            mono = block[:, 0]
            frames.append(mono.copy())

            rms = float(np.sqrt(np.mean(mono**2)))
            now = time.time()
            ecoule = now - started

            if rms > threshold:
                consecutifs += 1
                # Il faut du son CONTINU pour croire a de la parole : un pic
                # isole est un claquement de clavier ou un ventilateur.
                if consecutifs >= BLOCS_PAROLE:
                    heard = True
                silence_since = None
            else:
                consecutifs = 0
                # On n'arrete jamais avant la duree minimale, meme si tout
                # semble calme : une hesitation au debut de la phrase
                # tronquait l'enregistrement.
                if heard and ecoule >= DUREE_MINIMALE:
                    silence_since = silence_since or now
                    if now - silence_since >= SILENCE_TO_STOP:
                        break

            if ecoule >= MAX_UTTERANCE:
                break
            if not heard and ecoule >= LEAD_IN:
                # Meme raison que dans stt.record_until_silence : on laisse
                # Whisper juger, un seuil de volume se trompe sur un micro a
                # faible gain.
                break

        if not frames:
            return np.zeros(0, dtype=np.float32)

        audio = np.concatenate(frames)
        if float(np.max(np.abs(audio))) < stt.DEAD_PEAK:
            return np.zeros(0, dtype=np.float32)
        return audio


def list_microphones() -> list[tuple[int, str]]:
    return [
        (i, d["name"])
        for i, d in enumerate(sd.query_devices())
        if d["max_input_channels"] > 0
    ]
