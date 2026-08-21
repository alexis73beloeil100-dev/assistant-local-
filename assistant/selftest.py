"""Autotest : verifie que l'assistant fonctionne sur CETTE machine.

Sert a deux moments : apres une installation sur un PC inconnu, et quand
quelque chose ne marche pas sans qu'on sache quoi. Chaque verification dit ce
qu'elle teste, ce qu'elle trouve, et quoi faire si ca echoue.

Aucune verification ne modifie la machine. C'est un examen, pas une reparation.
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass

OK = "OK"
ABSENT = "ABSENT"
ECHEC = "ECHEC"
PARTIEL = "PARTIEL"


@dataclass
class Check:
    nom: str
    etat: str
    detail: str
    remede: str = ""
    duree: float = 0.0
    essentiel: bool = True


def _timed(fn):
    debut = time.time()
    try:
        etat, detail, remede = fn()
    except Exception as exc:  # noqa: BLE001
        etat, detail, remede = ECHEC, f"{type(exc).__name__}: {exc}", ""
    return etat, detail, remede, time.time() - debut


# --- Verifications ----------------------------------------------------------

def check_environnement():
    from assistant import __version__

    gele = getattr(sys, "frozen", False)
    return OK, (f"version {__version__}, "
                f"Python {sys.version_info.major}.{sys.version_info.minor}, "
                f"{'executable packagee' if gele else 'sources'}"), ""


def check_ecriture():
    from assistant import config

    try:
        temoin = config.DATA_DIR / ".test_ecriture"
        temoin.write_text("ok", encoding="utf-8")
        temoin.unlink()
    except OSError as exc:
        return ECHEC, f"{config.DATA_DIR} : {exc}", (
            "L'application ne peut pas ecrire ses reglages. Installe-la "
            "ailleurs que dans Program Files."
        )
    return OK, f"{config.DATA_DIR}", ""


def check_disques():
    from assistant import config

    disques = config.SCAN_ROOTS
    if not disques:
        return ECHEC, "aucun disque fixe detecte", (
            "Verifie qu'au moins un disque de plus de 20 Go est monte."
        )
    return OK, f"{len(disques)} disque(s) : {', '.join(disques)}", ""


def check_releve_materiel():
    from assistant.skills import hardware

    data = hardware.collect()
    if not data:
        return ECHEC, hardware._error or "releve vide", (
            "PowerShell est indispensable au relevé materiel. "
            "Verifie qu'il n'est pas bloque par une strategie de groupe."
        )
    cpu = str(data.get("cpu", {}).get("name") or "?").strip()
    disques = len(data.get("physical_disks") or [])
    return OK, f"{cpu}, {disques} disque(s) physique(s)", ""


def check_moteur():
    from assistant import backend

    exe = backend.find_ollama()
    if exe is None:
        return ABSENT, "Ollama n'est pas installe", (
            "Sans lui, l'assistant repond pour le materiel, les fichiers et "
            "les jeux, mais pas en langage naturel. Ecran Composants."
        )
    ok, message = backend.start()
    if not ok:
        return ECHEC, message, "Ouvre Ollama manuellement pour voir l'erreur."
    return OK, f"{exe.name} actif", ""


def check_modele():
    from assistant import backend, config

    presents = backend.models()
    if not presents:
        return ABSENT, "aucun modele installe", (
            "Ecran Composants : choisis un modele adapte a ta carte."
        )
    if config.LLM_MODEL not in presents:
        return PARTIEL, (f"{config.LLM_MODEL} absent ; presents : "
                         f"{', '.join(presents)}"), (
            "Ecran Composants, ou change LLM_MODEL dans les reglages."
        )
    return OK, config.LLM_MODEL, ""


def check_transcription():
    try:
        from assistant.voice import stt

        _modele, appareil = stt.load()
    except Exception as exc:  # noqa: BLE001
        return ABSENT, f"{type(exc).__name__}: {str(exc)[:90]}", (
            "Ecran Composants : installe la reconnaissance vocale."
        )
    if appareil.startswith("cpu"):
        return PARTIEL, f"{appareil} (le GPU n'a pas pu etre utilise)", (
            "Fonctionne, mais plus lentement. Sur carte NVIDIA, verifie les "
            "pilotes et les bibliotheques CUDA."
        )
    return OK, appareil, ""


def check_micro():
    try:
        from assistant.voice import stt

        micros = stt.microphones()
    except Exception as exc:  # noqa: BLE001
        return ECHEC, f"{type(exc).__name__}: {exc}", ""
    if not micros:
        return ABSENT, "aucun micro detecte", (
            "Le bouton Parler et le mot-cle ne fonctionneront pas."
        )
    sonde = stt.probe(None, 1.0)
    if not sonde.get("ok"):
        return PARTIEL, f"{len(micros)} micro(s), sonde en echec", (
            "Choisis un autre micro dans la barre laterale."
        )
    if sonde.get("crete", 0) < 1e-5:
        return PARTIEL, f"{len(micros)} micro(s), celui par defaut est muet", (
            "Choisis un autre micro dans la barre laterale."
        )
    return OK, (f"{len(micros)} micro(s), bruit de fond "
                f"{sonde.get('bruit_de_fond')}"), ""


def check_lecture_image():
    try:
        from assistant.skills import vision

        vision._engine()
    except Exception as exc:  # noqa: BLE001
        return ABSENT, f"{type(exc).__name__}: {str(exc)[:90]}", (
            "La lecture des captures d'ecran ne fonctionnera pas."
        )
    modele = None
    try:
        from assistant.skills import vision as v

        modele = v.vision_model()
    except Exception:  # noqa: BLE001
        pass
    if modele:
        return OK, f"texte + comprehension visuelle ({modele})", ""
    return PARTIEL, "texte seulement", (
        "Ecran Composants : le modele de vision permet de comprendre la "
        "disposition d'une capture, pas seulement son texte."
    )


def check_synthese_vocale():
    try:
        from assistant.voice import tts

        voix = tts.voices()
    except Exception as exc:  # noqa: BLE001
        return ABSENT, f"{type(exc).__name__}: {str(exc)[:80]}", ""
    francaises = [v for v in voix if "french" in v.lower() or "fr" in v.lower()]
    if not francaises:
        return PARTIEL, f"{len(voix)} voix, aucune en francais", (
            "Parametres Windows > Heure et langue > Voix : ajoute une voix "
            "francaise."
        )
    return OK, francaises[0], ""


def check_applications():
    """Le catalogue voit-il les applications du Microsoft Store ?

    C'est le controle qui manquait. Enumerer le Store passe par COM, donc par
    pywin32, importe A L'INTERIEUR des fonctions : l'analyse statique de
    PyInstaller ne le voit pas. L'executable se construisait sans erreur, puis
    ne trouvait plus ni Xbox, ni YouTube Music, ni Netflix -- et repondait
    qu'elles n'etaient pas installees.
    """
    from assistant.skills import apps

    catalogue = apps.catalogue(refresh=True)
    if not catalogue:
        return ECHEC, "aucune application detectee", (
            "Le menu Demarrer et le Store sont tous deux illisibles."
        )
    store = [a for a in catalogue if a.source == "microsoft store"]
    if not store:
        return PARTIEL, (f"{len(catalogue)} applications, aucune du Store"), (
            "pywin32 est absent ou COM est indisponible : les applications "
            "du Microsoft Store seront introuvables."
        )
    return OK, f"{len(catalogue)} applications, dont {len(store)} du Store", ""


def check_inventaire():
    """Le script d'inventaire est-il bien embarque ?

    inventaire.ps1 n'est pas du Python : sans une ligne dans le .spec,
    PyInstaller l'ignore, l'executable se construit sans erreur et
    l'inventaire logiciel echoue en silence -- plus de services, plus de
    logiciels, plus de pilotes.
    """
    from assistant.skills import inventaire

    if not inventaire.SCRIPT.exists():
        return ECHEC, f"introuvable : {inventaire.SCRIPT}", (
            "Ajoute inventaire.ps1 aux datas de AssistantLocal.spec."
        )
    return OK, f"script present ({inventaire.SCRIPT.name})", ""


def check_rgb():
    """L'outil d'eclairage est-il bien embarque, et voit-il le materiel ?

    Il est livre DANS l'application, dans outils/. Comme inventaire.ps1, ce
    n'est pas du Python : s'il manque au .spec, l'executable se construit sans
    erreur et la fonction disparait en silence.
    """
    from assistant.skills import rgb

    if not rgb.disponible():
        return ABSENT, "OpenRGB absent du paquet", (
            "Depose-le dans outils/OpenRGB/ : le .spec l'embarquera."
        )

    trouves, erreur = rgb.peripheriques()
    if erreur:
        return PARTIEL, f"present ({rgb.source()}), aucun peripherique", (
            "L'acces au bus SMBus demande les droits administrateur : "
            "clic droit sur le raccourci, \"Executer en tant "
            "qu'administrateur\". Et ferme le logiciel du fabricant."
        )
    return OK, f"{len(trouves)} peripherique(s) RGB ({rgb.source()})", ""


def check_jeux():
    from assistant.skills import games

    trouves = games.all_games()
    if not trouves:
        return PARTIEL, "aucun jeu detecte", (
            "Normal si aucun launcher n'est installe."
        )
    return OK, f"{len(trouves)} jeu(x)", ""


VERIFICATIONS = [
    ("Environnement", check_environnement, True),
    ("Ecriture des reglages", check_ecriture, True),
    ("Disques", check_disques, True),
    ("Releve materiel", check_releve_materiel, True),
    ("Moteur d'IA", check_moteur, False),
    ("Modele de langage", check_modele, False),
    ("Transcription vocale", check_transcription, False),
    ("Micro", check_micro, False),
    ("Lecture d'images", check_lecture_image, False),
    ("Synthese vocale", check_synthese_vocale, False),
    ("Detection des jeux", check_jeux, False),
    # Essentiels : ces deux-la echouent SILENCIEUSEMENT une fois packages, et
    # c'est precisement ce qu'un autotest doit attraper.
    ("Applications", check_applications, True),
    ("Inventaire logiciel", check_inventaire, True),
    ("Eclairage RGB", check_rgb, False),
]


def run(on_result=None) -> list[Check]:
    resultats = []
    for nom, fonction, essentiel in VERIFICATIONS:
        etat, detail, remede, duree = _timed(fonction)
        verif = Check(nom, etat, detail, remede, duree, essentiel)
        resultats.append(verif)
        if on_result:
            on_result(verif)
    return resultats


def report() -> str:
    resultats = run()

    lignes = ["AUTOTEST DE L'ASSISTANT", ""]
    for verif in resultats:
        marque = {OK: "[ok]", PARTIEL: "[~ ]", ABSENT: "[--]", ECHEC: "[!!]"}
        lignes.append(f"  {marque.get(verif.etat, '[??]')} {verif.nom:<24} "
                      f"{verif.detail}")
        if verif.remede:
            lignes.append(f"       -> {verif.remede}")

    bloquants = [v for v in resultats if v.essentiel and v.etat == ECHEC]
    manquants = [v for v in resultats if not v.essentiel
                 and v.etat in (ABSENT, ECHEC)]

    lignes.append("")
    if bloquants:
        lignes.append(f"{len(bloquants)} probleme(s) BLOQUANT(S) : "
                      + ", ".join(v.nom for v in bloquants))
    elif manquants:
        lignes.append(
            "L'assistant fonctionne. Composants optionnels absents : "
            + ", ".join(v.nom for v in manquants)
        )
    else:
        lignes.append("Tout fonctionne.")
    return "\n".join(lignes)


def main() -> int:
    print(report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
