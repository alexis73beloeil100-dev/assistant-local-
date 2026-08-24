"""Lire n'importe quel format video, et dire pourquoi Windows n'y arrive pas.

L'assistant n'est pas un lecteur video, et n'a aucune raison de le devenir :
il y en a un sur chaque machine. Ce qu'il peut faire, et qu'aucun lecteur ne
fait, c'est repondre a "pourquoi cette video ne s'ouvre pas".

Le symptome est toujours le meme et n'apprend rien : une fenetre noire, un
son sans image, ou "impossible de lire ce fichier". La cause tient en un mot
que personne ne voit -- le codec. Un .mp4 n'est pas un format, c'est une
boite : elle peut contenir du H.264 que Windows lit depuis toujours, ou de
l'AV1 qu'il ne lit pas sans extension. Le meme .mp4, la meme icone, et deux
resultats opposes.

PyAV est deja embarque, pour le decodage audio. Il apporte ffmpeg, donc 414
conteneurs et 557 codecs : l'assistant sait ouvrir et decrire des fichiers
que le lecteur de Windows refuse. C'est ce decalage qui permet de dire "ce
fichier est sain, c'est ton lecteur qui ne sait pas", au lieu de laisser
croire a un telechargement rate.

Ce qui manque a Windows se comble par une extension du Microsoft Store,
gratuite. On regarde CE QUI EST INSTALLE sur cette machine plutot que de
supposer : les extensions sont des paquets, et Windows sait les lister.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000

# Ce que Windows lit sans rien installer, depuis Windows 10.
#
# Cette liste est courte et stable : elle n'a pas bouge depuis dix ans, parce
# que ce sont les codecs dont les brevets sont couverts par la licence de
# Windows. Tout le reste dependant d'une extension, on VERIFIE sa presence au
# lieu de la deviner.
NATIFS = {"h264", "avc1", "mpeg4", "msmpeg4v3", "wmv3", "vc1", "mjpeg",
          "aac", "mp3", "ac3", "wmav2", "pcm_s16le", "flac"}

# Codec -> extension du Store qui le rend lisible. Le nom du paquet est celui
# que Windows declare, pas un nom commercial.
EXTENSIONS = {
    "hevc": ("Microsoft.HEVCVideoExtension", "Extensions video HEVC"),
    "vp9": ("Microsoft.VP9VideoExtensions", "Extensions video VP9"),
    "vp8": ("Microsoft.WebMediaExtensions", "Extensions Web Media"),
    "av01": ("Microsoft.AV1VideoExtension", "Extension video AV1"),
    "av1": ("Microsoft.AV1VideoExtension", "Extension video AV1"),
    "opus": ("Microsoft.WebMediaExtensions", "Extensions Web Media"),
    "vorbis": ("Microsoft.WebMediaExtensions", "Extensions Web Media"),
}


def _extensions_installees() -> set[str]:
    """Les extensions de codec presentes sur CETTE machine."""
    try:
        resultat = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "(Get-AppxPackage).Name"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, creationflags=CREATE_NO_WINDOW,
        )
    except (subprocess.SubprocessError, OSError):
        return set()
    if resultat.returncode != 0:
        return set()
    return {l.strip() for l in (resultat.stdout or "").splitlines() if l.strip()}


def informations(chemin: str) -> dict:
    """Ce que le fichier contient vraiment, lu par ffmpeg.

    L'extension du nom ne prouve rien : un .mkv renomme en .mp4 s'ouvre ici
    sans difficulte, et c'est justement le genre de fichier qui fait echouer
    un lecteur sans explication.
    """
    import av

    fichier = Path(chemin).expanduser()
    if not fichier.is_file():
        return {"erreur": f"Fichier introuvable : {fichier}"}

    try:
        with av.open(str(fichier)) as conteneur:
            videos = [f for f in conteneur.streams if f.type == "video"]
            audios = [f for f in conteneur.streams if f.type == "audio"]
            duree = (conteneur.duration / 1_000_000
                     if conteneur.duration else None)
            infos = {
                "fichier": fichier.name,
                "conteneur": conteneur.format.name,
                "conteneur_long": conteneur.format.long_name,
                "duree_s": duree,
                "poids": fichier.stat().st_size,
                "debit_kbps": (conteneur.bit_rate // 1000
                               if conteneur.bit_rate else None),
                "video": None,
                "audio": None,
            }
            if videos:
                flux = videos[0]
                infos["video"] = {
                    "codec": flux.codec_context.name,
                    "largeur": flux.codec_context.width,
                    "hauteur": flux.codec_context.height,
                    "images_s": (float(flux.average_rate)
                                 if flux.average_rate else None),
                }
            if audios:
                flux = audios[0]
                infos["audio"] = {
                    "codec": flux.codec_context.name,
                    "canaux": getattr(flux.codec_context, "channels", None),
                    "frequence": flux.codec_context.sample_rate,
                }
            return infos
    except Exception as exc:  # noqa: BLE001 - av leve des types varies
        return {"erreur": f"Illisible meme par ffmpeg : "
                          f"{type(exc).__name__}: {exc}"}


def _manquantes(infos: dict, installees: set[str]) -> list[tuple[str, str, str]]:
    """Les extensions qu'il faudrait, pour ce fichier, sur cette machine."""
    besoins = []
    for genre in ("video", "audio"):
        flux = infos.get(genre)
        if not flux:
            continue
        codec = str(flux.get("codec") or "").lower()
        if codec in NATIFS:
            continue
        paquet = EXTENSIONS.get(codec)
        if paquet and paquet[0] not in installees:
            besoins.append((codec, paquet[0], paquet[1]))
        elif not paquet:
            besoins.append((codec, "", ""))
    return besoins


def diagnostic(chemin: str) -> str:
    """Pourquoi cette video ne se lit pas -- ou pourquoi elle devrait."""
    infos = informations(chemin)
    if "erreur" in infos:
        return (f"{infos['erreur']}\n"
                "ffmpeg lit 414 conteneurs : s'il echoue lui aussi, le "
                "fichier est probablement incomplet ou abime, pas dans un "
                "format exotique.")

    lignes = [infos["fichier"], ""]
    lignes.append(f"  Conteneur   {infos['conteneur_long']} "
                  f"({infos['conteneur']})")
    if infos.get("duree_s"):
        minutes, secondes = divmod(int(infos["duree_s"]), 60)
        lignes.append(f"  Duree       {minutes} min {secondes:02d} s")
    if infos.get("video"):
        v = infos["video"]
        images = f", {v['images_s']:.0f} images/s" if v.get("images_s") else ""
        lignes.append(f"  Video       {v['codec']} "
                      f"{v['largeur']}x{v['hauteur']}{images}")
    if infos.get("audio"):
        a = infos["audio"]
        lignes.append(f"  Audio       {a['codec']}"
                      + (f", {a['frequence']} Hz" if a.get("frequence") else ""))

    installees = _extensions_installees()
    manque = _manquantes(infos, installees)

    lignes.append("")
    if not manque:
        lignes.append("  Windows sait lire ce fichier. S'il refuse quand meme,")
        lignes.append("  le probleme vient du lecteur, pas du format : essaie "
                      "de l'ouvrir")
        lignes.append("  avec un autre programme.")
        return "\n".join(lignes)

    lignes.append("  Ce que Windows ne sait pas lire ici :")
    for codec, paquet, libelle in manque:
        if paquet:
            lignes.append(f"    {codec} -- il manque \"{libelle}\", gratuite "
                          "dans le Microsoft Store")
        else:
            lignes.append(f"    {codec} -- aucune extension Microsoft ne le "
                          "couvre ; il faut un lecteur qui embarque ses "
                          "propres codecs")
    lignes.append("")
    lignes.append("  Le fichier lui-meme est sain : je viens de l'ouvrir et "
                  "de le decrire.")
    lignes.append("  Demande-moi d'ouvrir le Store sur l'extension qui "
                  "manque.")
    return "\n".join(lignes)


def installer_extension(codec: str) -> str:
    """Ouvre le Microsoft Store sur l'extension qui couvre ce codec.

    On ouvre, on n'installe pas : poser un logiciel sur la machine de
    quelqu'un sans qu'il voie ce qu'il accepte n'est pas a nous. Le Store
    affiche l'editeur, la taille et les autorisations -- c'est la page ou la
    decision se prend.
    """
    demande = str(codec).strip().lower()
    paquet = EXTENSIONS.get(demande)
    if not paquet:
        connus = ", ".join(sorted(set(EXTENSIONS)))
        return (f"Aucune extension Microsoft ne couvre \"{codec}\". "
                f"Celles que je connais : {connus}.")

    if paquet[0] in _extensions_installees():
        return (f"{paquet[1]} est deja installee. Si la video ne passe "
                "toujours pas, le probleme vient du lecteur.")

    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", f"ms-windows-store://pdp/?PFN={paquet[0]}"],
            creationflags=CREATE_NO_WINDOW)
    except OSError as exc:
        return f"Le Store n'a pas pu s'ouvrir : {exc}"
    return (f"Microsoft Store ouvert sur {paquet[1]}. Elle est gratuite ; "
            "c'est toi qui lances l'installation.")


def lire(chemin: str) -> str:
    """Ouvre la video avec le lecteur par defaut, apres l'avoir examinee.

    L'examen passe AVANT : lancer un lecteur qui va afficher un ecran noir,
    puis expliquer ensuite, c'est laisser l'utilisateur conclure que la video
    est morte avant d'avoir lu la reponse.
    """
    fichier = Path(chemin).expanduser()
    if not fichier.is_file():
        return f"Fichier introuvable : {fichier}"

    infos = informations(str(fichier))
    if "erreur" in infos:
        return diagnostic(str(fichier))

    manque = _manquantes(infos, _extensions_installees())
    if manque:
        return (diagnostic(str(fichier))
                + "\n\n  Je ne l'ouvre pas : le lecteur afficherait un ecran "
                  "noir sans dire pourquoi.")

    try:
        subprocess.Popen(["cmd", "/c", "start", "", str(fichier)],
                         creationflags=CREATE_NO_WINDOW)
    except OSError as exc:
        return f"Ouverture impossible : {exc}"
    return f"{fichier.name} ouvert avec le lecteur par defaut."
