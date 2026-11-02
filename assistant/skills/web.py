"""Chercher dans la communaute Unreal et lire une page web.

La recherche passe par des API publiques faites pour ca, pas par une page de
moteur de recherche lue en cachette :
  - le forum officiel d'Unreal (forums.unrealengine.com, API Discourse) ;
  - Stack Overflow (API Stack Exchange), etiquettes unreal-engine4 et 5.

Ce qui sort : la recherche tapee par le modele, et l'adresse de la page lue.
Jamais le contenu des fichiers de l'utilisateur. Chaque sortie est notee
dans le journal des actions.
"""
from __future__ import annotations

import html
import re

from assistant import safety

FORUM = "https://forums.unrealengine.com"
STACK = "https://api.stackexchange.com/2.3/search/advanced"
DELAI = 15
TAILLE_PAGE = 12000
AGENT = "AssistantLocal (outil de developpement local)"


def _texte(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def resultats_forum(donnees: dict, nombre: int = 6) -> list[tuple[str, str, str]]:
    extraits = {p.get("topic_id"): p.get("blurb", "")
                for p in donnees.get("posts", [])}
    return [(t.get("title", ""), f"{FORUM}/t/{t.get('slug', '')}/{t.get('id')}",
             _texte(extraits.get(t.get("id"), "")))
            for t in donnees.get("topics", [])][:nombre]


def resultats_stack(donnees: dict, nombre: int = 4) -> list[tuple[str, str, str]]:
    return [(html.unescape(i.get("title", "")), i.get("link", ""),
             f"{i.get('score', 0)} vote(s), "
             f"{'resolue' if i.get('is_answered') else 'sans reponse acceptee'}")
            for i in donnees.get("items", [])][:nombre]


def chercher(requete: str, session=None) -> str:
    import requests

    requete = (requete or "").strip()
    if not requete:
        return "Recherche vide."
    session = session or requests
    safety._audit(safety.Action(kind="reseau", summary=f"recherche : {requete}",
                                targets=[FORUM, STACK]), "auto:demande")
    lignes = [f"Resultats pour « {requete} » :"]
    trouve = False
    try:
        r = session.get(f"{FORUM}/search.json", params={"q": requete},
                        timeout=DELAI, headers={"Accept": "application/json",
                                                "User-Agent": AGENT})
        if r.status_code == 200:
            for titre, lien, extrait in resultats_forum(r.json()):
                trouve = True
                lignes += [f"- [forum] {titre}", f"  {lien}", f"  {extrait[:280]}"]
    except (requests.RequestException, ValueError):
        lignes.append("(forum Unreal injoignable)")
    for etiquette in ("unreal-engine5", "unreal-engine4"):
        try:
            r = session.get(STACK, timeout=DELAI, params={
                "q": requete, "tagged": etiquette, "site": "stackoverflow",
                "order": "desc", "sort": "relevance"})
            if r.status_code == 200:
                for titre, lien, info in resultats_stack(r.json(), 3):
                    trouve = True
                    lignes += [f"- [stackoverflow] {titre}", f"  {lien}", f"  {info}"]
        except (requests.RequestException, ValueError):
            continue
    if not trouve:
        return f"Aucun resultat pour « {requete} » sur le forum Unreal ni sur Stack Overflow."
    lignes.append("Lis une page avec lire_page pour le detail.")
    return "\n".join(lignes)


def texte_de_page(source: str) -> str:
    source = re.sub(r"(?is)<head\b.*?</head>", " ", source)
    source = re.sub(r"(?is)<(script|style|nav|footer|header|noscript)[^>]*>.*?</\1>",
                    " ", source)
    # Garder les blocs de code lisibles : ce sont eux qu'on vient chercher.
    source = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|pre|tr)>", "\n", source)
    texte = html.unescape(re.sub(r"<[^>]+>", "", source))
    lignes = [re.sub(r"[ \t]+", " ", l).strip() for l in texte.splitlines()]
    return "\n".join(l for l in lignes if l)


def lire_page(url: str, session=None) -> str:
    import requests

    url = (url or "").strip()
    if not url.startswith(("https://", "http://")):
        return "Adresse invalide : elle doit commencer par https://"
    session = session or requests
    safety._audit(safety.Action(kind="reseau", summary="lecture d'une page web",
                                targets=[url]), "auto:demande")
    try:
        r = session.get(url, timeout=DELAI, headers={"User-Agent": AGENT})
    except requests.RequestException:
        return "Page injoignable."
    if r.status_code != 200:
        return f"La page a repondu {r.status_code}."
    texte = texte_de_page(r.text)
    if url.startswith(FORUM + "/t/"):
        # Un sujet du forum : sa version JSON donne les messages sans le
        # decor de la page.
        try:
            j = session.get(url.split("?")[0].rstrip("/") + ".json",
                            timeout=DELAI, headers={"User-Agent": AGENT}).json()
            messages = j.get("post_stream", {}).get("posts", [])[:8]
            texte = j.get("title", "") + "\n\n" + "\n\n---\n\n".join(
                f"{m.get('username', '?')} :\n{texte_de_page(m.get('cooked', ''))}"
                for m in messages)
        except (requests.RequestException, ValueError):
            pass
    if len(texte) > TAILLE_PAGE:
        texte = texte[:TAILLE_PAGE] + "\n... (page coupee)"
    return f"{url}\n\n{texte}"


# --- Connaissances generales -----------------------------------------------------

WIKI = "https://{langue}.wikipedia.org/w/api.php"
AGENT_WIKI = ("AssistantLocal/1.0 "
              "(https://github.com/alexis73beloeil100-dev/assistant-local-)")


def chercher_encyclopedie(requete: str, langue: str = "fr", session=None) -> str:
    """Wikipedia, par son API publique : les articles et leur resume."""
    import requests

    requete = (requete or "").strip()
    if not requete:
        return "Recherche vide."
    langue = langue if re.fullmatch(r"[a-z]{2,3}", langue or "") else "fr"
    session = session or requests
    url = WIKI.format(langue=langue)
    safety._audit(safety.Action(kind="reseau", summary=f"encyclopedie : {requete}",
                                targets=[url]), "auto:demande")
    entetes = {"User-Agent": AGENT_WIKI}
    try:
        r = session.get(url, timeout=DELAI, headers=entetes, params={
            "action": "query", "list": "search", "srsearch": requete,
            "format": "json", "srlimit": 3})
        if r.status_code == 429:
            return "Wikipedia demande d'attendre un peu avant une nouvelle recherche."
        titres = [x["title"] for x in r.json()["query"]["search"]]
        if not titres:
            return f"Aucun article pour « {requete} » sur Wikipedia ({langue})."
        r = session.get(url, timeout=DELAI, headers=entetes, params={
            "action": "query", "prop": "extracts", "explaintext": 1,
            "exintro": 1, "titles": "|".join(titres), "format": "json"})
        pages = r.json()["query"]["pages"].values()
    except (requests.RequestException, ValueError, KeyError):
        return "Wikipedia injoignable."
    lignes = []
    for p in pages:
        extrait = (p.get("extract") or "").strip()
        lien = f"https://{langue}.wikipedia.org/wiki/{p.get('title', '').replace(' ', '_')}"
        lignes += [f"## {p.get('title')}", lien, extrait[:1500], ""]
    return "\n".join(lignes).strip()
