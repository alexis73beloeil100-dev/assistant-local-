"""Test de debit Internet : latence, descendant, montant.

LA SEULE FONCTION DE L'ASSISTANT QUI CONTACTE UN TIERS DE SON PLEIN GRE.

Tout le reste travaille sur cette machine et n'en sort pas. Mesurer un debit
Internet sans Internet n'a aucun sens : il faut un serveur en face, et il faut
lui envoyer et lui reprendre des octets. Ajoute le 24/08/2026 a la demande
explicite de l'utilisateur, qui a choisi le debit REEL apres qu'on lui a
oppose l'alternative purement locale (latence vers la passerelle, vitesse de
la carte reseau) -- laquelle ne mesure pas la vitesse de la ligne.

Ce qui sort d'ici, exactement : des octets nuls, et rien d'autre. Aucun nom de
machine, aucun identifiant, aucun contenu de fichier. Le serveur voit ce que
voit n'importe quel site visite -- une adresse IP et une requete HTTP.

Le serveur est celui de Cloudflare, pour trois raisons : ses points de mesure
sont publics et sans compte, ils sont largement repartis donc rarement le
goulot, et l'adresse est lisible dans le code plutot que cachee derriere un
service tiers.

Ce que la mesure ne dit PAS, et que le rapport doit rappeler : le debit d'une
ligne se partage. Un telechargement en cours, une console qui met a jour un
jeu, un autre appareil en visio -- chacun tire le chiffre vers le bas sans
qu'il y ait la moindre panne. Un test de debit est une photographie, pas un
verdict.
"""
from __future__ import annotations

import time

# Point de mesure, ecrit en clair : on doit pouvoir lire ou vont les octets.
HOTE = "https://speed.cloudflare.com"
DESCENDANT = HOTE + "/__down?bytes={octets}"
MONTANT = HOTE + "/__up"

# Budget de temps, en secondes. Un test qui dure une minute ne sera plus
# jamais demande, et la reponse doit tenir dans une conversation.
DELAI = 20
MESURES_LATENCE = 5

# Tailles d'essai, croissantes. On commence petit : sur une ligne lente, un
# fichier de 100 Mo ferait attendre plusieurs minutes pour un chiffre qu'un
# fichier de 1 Mo donnait deja. On s'arrete des que la mesure dure assez
# longtemps pour etre fiable.
PALIERS = (1_000_000, 10_000_000, 25_000_000, 100_000_000)
DUREE_SUFFISANTE = 2.0


def _session():
    import requests

    session = requests.Session()
    # Pas de cache, pas de compression : un serveur qui renverrait des zeros
    # compresses donnerait un debit fantaisiste, dix fois trop eleve.
    session.headers.update({
        "Cache-Control": "no-cache",
        "Accept-Encoding": "identity",
    })
    return session


def latence(session=None) -> tuple[float | None, float | None]:
    """Latence mediane et gigue, en millisecondes.

    Mediane et non moyenne : une seule requete malchanceuse -- un paquet
    perdu, un reveil de carte Wi-Fi -- deplacerait la moyenne de cinquante
    millisecondes et ferait conclure a une ligne malade.

    La premiere requete est jetee, et ce n'est pas un detail de confort. Elle
    porte la resolution DNS et la poignee de main TLS, qui n'ont rien a voir
    avec la latence de la ligne. Mesuree le 24/08/2026 sur une connexion
    saine : mediane 41 ms, et une gigue annoncee a 239 ms -- l'assistant
    concluait a un "Wi-Fi encombre ou lointain" en se fondant sur le cout
    d'ouverture de sa propre connexion.
    """
    import requests

    session = session or _session()

    # Mise en route : c'est elle qui paie le DNS et le TLS. Son resultat ne
    # sert a rien, et son echec ne dit rien non plus -- la boucle qui suit
    # tranchera.
    try:
        session.get(DESCENDANT.format(octets=0), timeout=5).content
    except requests.RequestException:
        pass

    mesures = []
    for _ in range(MESURES_LATENCE):
        depart = time.perf_counter()
        try:
            reponse = session.get(DESCENDANT.format(octets=0), timeout=5)
            reponse.content
        except requests.RequestException:
            continue
        mesures.append((time.perf_counter() - depart) * 1000)

    if not mesures:
        return None, None
    mesures.sort()
    mediane = mesures[len(mesures) // 2]
    return mediane, max(mesures) - min(mesures)


def descendant(session=None) -> tuple[float | None, int]:
    """Debit descendant en Mbit/s, et le nombre d'octets reellement recus."""
    import requests

    session = session or _session()
    for octets in PALIERS:
        depart = time.perf_counter()
        recus = 0
        try:
            reponse = session.get(DESCENDANT.format(octets=octets),
                                  stream=True, timeout=DELAI)
            for bloc in reponse.iter_content(chunk_size=65536):
                recus += len(bloc)
                if time.perf_counter() - depart > DELAI:
                    break
        except requests.RequestException:
            return None, 0

        duree = time.perf_counter() - depart
        if duree <= 0 or not recus:
            continue
        # Assez long pour etre fiable, ou bien c'etait le dernier palier.
        if duree >= DUREE_SUFFISANTE or octets == PALIERS[-1]:
            return (recus * 8) / duree / 1_000_000, recus
    return None, 0


def montant(session=None, octets: int = 10_000_000) -> float | None:
    """Debit montant en Mbit/s.

    Ce qui est envoye : des octets nuls, fabriques ici. Rien de la machine ne
    part -- c'est la difference entre mesurer une ligne et televerser un
    fichier.
    """
    import requests

    session = session or _session()
    charge = b"\0" * octets
    depart = time.perf_counter()
    try:
        session.post(MONTANT, data=charge, timeout=DELAI)
    except requests.RequestException:
        return None
    duree = time.perf_counter() - depart
    if duree <= 0:
        return None
    return (octets * 8) / duree / 1_000_000


def _qualite(mbps: float) -> str:
    """Ce que ce chiffre permet vraiment de faire."""
    if mbps >= 500:
        return "fibre rapide"
    if mbps >= 100:
        return "confortable, 4K et gros telechargements"
    if mbps >= 25:
        return "suffisant pour la 4K sur un ecran"
    if mbps >= 5:
        return "visio et HD, sans plus"
    return "juste, la video va sauter"


def tester(ask=None) -> str:
    """Mesure la ligne et rend un rapport lisible.

    Passe par le garde-fou, sans poser de question mais en laissant une trace
    dans le journal des actions. C'est un geste ordinaire qu'on refait dix
    fois quand la connexion rame -- une fenetre a chaque fois le rendrait
    inutilisable a la voix. Mais c'est aussi la seule chose que l'assistant
    envoie a l'exterieur, et cela ne doit pas se faire sans trace.
    """
    from assistant import safety

    action = safety.Action(
        kind="reseau",
        summary="Mesurer le debit Internet",
        targets=[HOTE],
        reversible=True,
        details=("Envoie et recoit des octets nuls vers le point de mesure de "
                 "Cloudflare. Aucune donnee de la machine ne part : ni nom, "
                 "ni identifiant, ni contenu de fichier."),
        routine=True,
    )
    try:
        safety.guard(action, ask=ask)
    except safety.Refused as exc:
        return str(exc)

    session = _session()
    ping, gigue = latence(session)
    if ping is None:
        return ("Le point de mesure est injoignable. Soit la connexion est "
                "coupee, soit un pare-feu bloque la sortie. La suite du test "
                "n'aurait rien mesure.")

    bas, recus = descendant(session)
    haut = montant(session)

    lignes = ["DEBIT INTERNET", ""]
    lignes.append(f"  Latence      {ping:.0f} ms"
                  + (f"   (gigue {gigue:.0f} ms)" if gigue is not None else ""))
    if bas is not None:
        lignes.append(f"  Descendant   {bas:.1f} Mbit/s   ({_qualite(bas)})")
    else:
        lignes.append("  Descendant   mesure impossible")
    if haut is not None:
        lignes.append(f"  Montant      {haut:.1f} Mbit/s")
    else:
        lignes.append("  Montant      mesure impossible")

    lignes.append("")
    if ping > 100:
        lignes.append("  La latence est elevee : c'est elle qui gene en jeu "
                      "et en visio, pas le debit.")
    if gigue is not None and gigue > 50:
        lignes.append("  La gigue est forte : la ligne est irreguliere, "
                      "typique d'un Wi-Fi encombre ou lointain.")

    lignes.append("  Mesure faite a l'instant, vers Cloudflare. Un "
                  "telechargement en cours ou un autre appareil sur la meme "
                  "ligne")
    lignes.append("  fait baisser ce chiffre sans qu'il y ait de panne.")
    return "\n".join(lignes)
