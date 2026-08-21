"""Ecoute et transcription, en local.

Whisper tourne sur la RTX 5060 Ti. Le modele reste charge en VRAM entre deux
commandes : le recharger a chaque fois couterait 7 secondes, le garder coute
environ 1 Go de VRAM, ce qui est sans consequence sur 16 Go.
"""
from __future__ import annotations

import threading
import time

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16_000
BLOCK = 1600            # 100 ms

# Un seuil absolu ne marche pas : le niveau depend entierement du gain de la
# carte son. Sur ce PC le micro arriere sort un ambiant a 0.0106, soit juste
# sous un seuil fixe a 0.012 -- la parole n'etait jamais detectee et
# l'enregistrement rendait toujours du vide.
#
# On mesure donc le bruit de fond au debut de chaque enregistrement et on
# place le seuil au-dessus. Ca s'adapte a n'importe quel micro, casque ou
# ventilateur bruyant.
CALIBRATION_SECONDS = 0.4
SPEECH_FACTOR = 2.2       # multiple du bruit de fond a depasser pour "parle"
MIN_THRESHOLD = 0.004     # plancher : un micro parfaitement silencieux
# Plafond volontairement bas. Avec 0.05, un micro dont le bruit de fond
# atteint 0.019 (cas du Mappeur de sons Microsoft sur cette machine) donnait
# un seuil de 0.042 que la voix ne franchissait jamais : l'enregistrement
# repartait vide sans que rien n'explique pourquoi.
MAX_THRESHOLD = 0.02

# Niveau en dessous duquel le flux est un silence numerique : le peripherique
# ne capte rien du tout, ce n'est pas une question de gain.
DEAD_PEAK = 1e-5

SILENCE_TO_STOP = 1.1   # secondes de blanc avant de couper l'enregistrement
MAX_UTTERANCE = 15.0    # garde-fou : jamais plus de 15 s d'un coup
LEAD_IN = 6.0           # temps laisse pour commencer a parler

_model = None
_device_used = ""
_dlls_registered = False


def _register_cuda_dlls() -> None:
    """Rend visibles les DLL CUDA installees par pip.

    Les paquets nvidia-cublas-cu12 et nvidia-cudnn-cu12 deposent leurs DLL
    dans site-packages/nvidia/*/bin, un endroit ou Windows ne va pas les
    chercher. Sans cette declaration, le modele se charge sur GPU mais
    echoue a la premiere inference sur "cublas64_12.dll is not found".
    """
    global _dlls_registered
    if _dlls_registered:
        return

    import glob
    import os
    import site
    import sys

    roots = []
    # Application packagee : les DLL sont posees a cote de l'executable, il
    # n'y a plus de site-packages a interroger.
    if getattr(sys, "frozen", False):
        roots.append(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
        roots.append(os.path.dirname(sys.executable))
    else:
        roots.extend(site.getsitepackages())
        roots.append(os.path.join(sys.prefix, "Lib", "site-packages"))

    found = []
    for root in roots:
        for folder in glob.glob(os.path.join(root, "nvidia", "*", "bin")):
            if folder in found:
                continue
            found.append(folder)
            try:
                os.add_dll_directory(folder)
            except OSError:
                pass

    # add_dll_directory ne sert qu'aux chargements qui demandent explicitement
    # la recherche etendue. CTranslate2 appelle LoadLibrary tout court, qui
    # lui consulte PATH : il faut donc les deux.
    if found:
        os.environ["PATH"] = os.pathsep.join(found) + os.pathsep + os.environ.get("PATH", "")
    _dlls_registered = True


def _inference_works(model) -> bool:
    """Verifie que le modele calcule vraiment, pas qu'il se charge.

    Distinction cruciale : CTranslate2 accepte device="cuda" et n'echoue
    qu'au premier encode si les bibliotheques manquent. Un fallback qui ne
    teste que la construction laisse donc passer un GPU inutilisable.
    """
    try:
        probe = np.zeros(SAMPLE_RATE, dtype=np.float32)
        probe[::100] = 0.05          # un peu de signal, sinon le VAD coupe tout
        segments, _ = model.transcribe(probe, language="fr", vad_filter=False)
        list(segments)
        return True
    except Exception:  # noqa: BLE001
        return False


def load(model_size: str = "medium") -> tuple[object, str]:
    """Charge Whisper une fois pour toutes.

    On tente le GPU puis on retombe sur le CPU : sur cette machine le GPU
    passe, mais l'assistant doit rester utilisable si le pilote change ou si
    la VRAM est prise par un jeu.
    """
    global _model, _device_used
    if _model is not None:
        return _model, _device_used

    _register_cuda_dlls()
    from faster_whisper import WhisperModel

    errors = []
    for device, compute in (("cuda", "float16"), ("cpu", "int8")):
        try:
            candidate = WhisperModel(model_size, device=device, compute_type=compute)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{device}: {type(exc).__name__}")
            continue
        if not _inference_works(candidate):
            errors.append(f"{device}: charge mais inference impossible")
            continue
        _model = candidate
        _device_used = f"{device}/{compute}"
        return _model, _device_used

    raise RuntimeError("Whisper inutilisable. Essais : " + " ; ".join(errors))


def rms(block: np.ndarray) -> float:
    return float(np.sqrt(np.mean(block**2)))


def measure_noise(stream, seconds: float = CALIBRATION_SECONDS) -> float:
    """Mesure le bruit de fond juste avant d'enregistrer.

    On prend la mediane et non la moyenne : un claquement de clavier pendant
    la calibration ferait exploser une moyenne et rendrait le seuil
    inatteignable pour le reste de l'enregistrement.
    """
    levels = []
    for _ in range(max(int(seconds * SAMPLE_RATE / BLOCK), 1)):
        block, _ = stream.read(BLOCK)
        levels.append(rms(block[:, 0]))
    return float(np.median(levels)) if levels else 0.0


def speech_threshold(noise: float) -> float:
    return min(max(noise * SPEECH_FACTOR, MIN_THRESHOLD), MAX_THRESHOLD)


def record_until_silence(
    max_seconds: float = MAX_UTTERANCE,
    silence_stop: float = SILENCE_TO_STOP,
    device: int | None = None,
    on_level=None,
) -> np.ndarray:
    """Enregistre tant que tu parles, s'arrete quand tu te tais.

    Le seuil de parole est calibre sur le bruit de fond de ton micro au debut
    de chaque enregistrement, pas fixe dans le code.

    Le blanc n'est compte qu'apres avoir entendu du son : sinon la fonction
    se couperait immediatement pendant que tu prends ta respiration.

    on_level(niveau, seuil) permet a l'interface d'afficher un vu-metre, ce
    qui rend un probleme de micro visible au lieu d'etre silencieux.
    """
    frames: list[np.ndarray] = []
    heard_speech = False
    silence_since: float | None = None

    with sd.InputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="float32",
        blocksize=BLOCK, device=device,
    ) as stream:
        noise = measure_noise(stream)
        threshold = speech_threshold(noise)
        started = time.time()

        while True:
            block, _ = stream.read(BLOCK)
            mono = block[:, 0]
            frames.append(mono.copy())

            level = rms(mono)
            now = time.time()
            if on_level:
                on_level(level, threshold)

            if level > threshold:
                heard_speech = True
                silence_since = None
            elif heard_speech:
                silence_since = silence_since or now
                if now - silence_since >= silence_stop:
                    break

            if now - started >= max_seconds:
                break
            if not heard_speech and now - started >= LEAD_IN:
                # Le detecteur de niveau n'a rien vu. On rend quand meme
                # l'audio : Whisper reconnait la parole bien mieux qu'un
                # seuil de volume, et sur un micro a faible gain c'est lui
                # qui a raison. On ne jette que le silence numerique.
                break

    if not frames:
        return np.zeros(0, dtype=np.float32)

    audio = np.concatenate(frames)
    if float(np.max(np.abs(audio))) < DEAD_PEAK:
        # Le peripherique ne capte reellement rien : inutile de faire
        # travailler Whisper pour rendre une chaine vide.
        return np.zeros(0, dtype=np.float32)
    return audio


class Recorder:
    """Enregistrement commande a la main : on demarre, on arrete.

    La detection automatique de fin de phrase ne peut pas etre fiable. Elle
    repose sur un seuil de volume, et un simple pic de bruit ambiant suffit a
    la declencher : mesure faite sur ce PC, l'enregistrement se declarait
    "parole detectee" a 2,3 s puis s'arretait a 6,2 s alors que personne
    n'avait parle. L'utilisateur voyait le vu-metre bouger et n'obtenait
    jamais sa phrase.

    Quand quelqu'un peut cliquer, il n'y a aucune raison de deviner.
    """

    def __init__(self, device: int | None = None, max_seconds: float = 60.0):
        self.device = device
        self.max_seconds = max_seconds
        self._frames: list[np.ndarray] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.level = 0.0
        self.threshold = MIN_THRESHOLD
        self.error = ""

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, on_level=None) -> bool:
        if self.running:
            return False
        self._frames = []
        self._stop.clear()
        self.error = ""

        def work():
            try:
                with sd.InputStream(
                    samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                    blocksize=BLOCK, device=self.device,
                ) as stream:
                    noise = measure_noise(stream)
                    self.threshold = speech_threshold(noise)
                    debut = time.time()
                    while not self._stop.is_set():
                        block, _ = stream.read(BLOCK)
                        mono = block[:, 0]
                        self._frames.append(mono.copy())
                        self.level = rms(mono)
                        if on_level:
                            on_level(self.level, self.threshold)
                        if time.time() - debut >= self.max_seconds:
                            break
            except Exception as exc:  # noqa: BLE001
                self.error = f"{type(exc).__name__}: {exc}"

        self._thread = threading.Thread(target=work, name="dictee", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> np.ndarray:
        """Arrete et rend l'audio capture."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        if not self._frames:
            return np.zeros(0, dtype=np.float32)
        audio = np.concatenate(self._frames)
        if float(np.max(np.abs(audio))) < DEAD_PEAK:
            return np.zeros(0, dtype=np.float32)
        return audio


def microphones() -> list[tuple[int, str]]:
    """Micros utilisables, doublons de pilotes ecartes."""
    seen = set()
    out = []
    for index, info in enumerate(sd.query_devices()):
        if info["max_input_channels"] < 1:
            continue
        name = info["name"].strip()
        if name in seen:
            continue
        seen.add(name)
        out.append((index, name))
    return out


def probe(device: int | None = None, seconds: float = 1.5) -> dict:
    """Ecoute breve d'un micro : sert a verifier qu'il rend du signal."""
    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                            dtype="float32", blocksize=BLOCK,
                            device=device) as stream:
            levels = []
            for _ in range(int(seconds * SAMPLE_RATE / BLOCK)):
                block, _ = stream.read(BLOCK)
                levels.append(rms(block[:, 0]))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "erreur": f"{type(exc).__name__}: {exc}"}

    noise = float(np.median(levels))
    return {
        "ok": True,
        "bruit_de_fond": round(noise, 5),
        "crete": round(float(max(levels)), 5),
        "seuil_calcule": round(speech_threshold(noise), 5),
    }


_vocab_prompt: str | None = None


def vocab_prompt() -> str:
    """Amorce Whisper avec le vocabulaire propre a cette machine.

    Sans cela, "Euro Truck Simulator 2" ressort en "au truc simulateur".
    Whisper accepte un texte d'amorce qui oriente son decodage : y mettre les
    titres reellement installes corrige la quasi-totalite de ces erreurs, et
    la liste se met a jour toute seule quand tu installes un jeu.
    """
    global _vocab_prompt
    if _vocab_prompt is not None:
        return _vocab_prompt

    titles = []
    try:
        from assistant.skills import games

        titles = [g.name for g in games.all_games()]
    except Exception:  # noqa: BLE001 - l'amorce est un confort, pas un prerequis
        titles = []

    verbs = "Lance, ouvre, ferme, cherche, diagnostique, nettoie, optimise."
    _vocab_prompt = f"{verbs} Jeux installes : {', '.join(titles)}." if titles else verbs
    return _vocab_prompt


def transcribe(audio: np.ndarray, language: str = "fr") -> str:
    """Transcrit un extrait audio deja en memoire."""
    if audio.size < SAMPLE_RATE // 4:   # moins de 250 ms
        return ""
    model, _ = load()
    segments, _info = model.transcribe(
        audio,
        language=language,
        beam_size=1,          # commande courte : le beam search n'apporte rien
        vad_filter=True,
        condition_on_previous_text=False,
        initial_prompt=vocab_prompt(),
    )
    return " ".join(seg.text.strip() for seg in segments).strip()


def listen(device: int | None = None) -> str:
    """Enregistre puis transcrit. Chaine complete d'un tour de parole."""
    audio = record_until_silence(device=device)
    if audio.size == 0:
        return ""
    return transcribe(audio)


def device_label() -> str:
    load()
    return _device_used
