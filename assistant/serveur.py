"""Petit serveur local : le telephone parle au PC, sur le reseau de la maison.

C'est la piece la plus sensible de tout le projet, et il faut le dire avant
d'en decrire une ligne. Tout le reste de cet assistant AGIT quand quelqu'un
assis devant la machine le demande. Ici, un appareil exterieur envoie des
ordres -- dont des frappes clavier. Une porte mal fermee, et n'importe quel
appareil du reseau tape a votre place dans votre session ouverte : le
telephone d'un invite, un objet connecte compromis, un voisin sur un Wi-Fi
partage.

Cinq regles, aucune negociable.

  1. ETEINT par defaut. Ce serveur ne demarre jamais tout seul. Aucun reglage
     ne le rend permanent sans qu'on l'ait ecrit soi-meme.

  2. UN JETON sur chaque requete, compare en temps constant. Sans jeton, la
     requete est refusee avant meme d'etre lue. Le jeton est tire au hasard a
     la premiere activation et vit dans les reglages, pas dans le code.

  3. LE TELEPHONE NE DECRIT JAMAIS UNE ACTION. Il ne peut que NOMMER une macro
     deja enregistree sur le PC. C'est la difference entre une telecommande et
     une console d'administration a distance : accepter une suite de touches
     venue du reseau, c'est offrir un clavier a qui trouve le jeton.

  4. UNE SEULE INTERFACE ECOUTE. On se lie a l'adresse locale de la machine,
     jamais a 0.0.0.0 : lier tout, c'est aussi ecouter sur un VPN ou un
     partage de connexion sans l'avoir voulu.

  5. TROIS ECHECS ET LA PORTE SE FERME. Un jeton se devine par essais
     repetes ; on arrete de repondre bien avant que ca devienne realiste.

Ce qui n'est PAS protege, et qu'il faut savoir : le trafic circule en clair
sur le reseau local. Un chiffrement demanderait un certificat que le
telephone refuserait sans installation manuelle. Sur le reseau de la maison
c'est un compromis raisonnable ; sur un Wi-Fi public, ce serveur n'a rien a
faire allume.
"""
from __future__ import annotations

import json
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from assistant import settings

PORT_DEFAUT = 8765

# Au-dela, la porte se ferme pour tout le monde jusqu'a un redemarrage du
# serveur. Un jeton de 32 caracteres ne se devine pas en trois coups : trois
# echecs signifient qu'on essaie, pas qu'on s'est trompe.
ECHECS_TOLERES = 3

# Taille maximale d'un envoi. Le presse-papier accepte du texte, pas un
# fichier : sans plafond, une requete unique saturerait la memoire.
CORPS_MAX = 256 * 1024

_serveur: ThreadingHTTPServer | None = None
_fil: threading.Thread | None = None
_echecs = 0
_verrou = threading.Lock()
_journal: list[str] = []


def jeton() -> str:
    """Le jeton de cette machine, tire au hasard a la premiere demande."""
    existant = settings.get("serveur_jeton", "")
    if existant:
        return str(existant)
    nouveau = secrets.token_urlsafe(24)
    settings.set("serveur_jeton", nouveau)
    return nouveau


def renouveler_le_jeton() -> str:
    """Change le jeton : tous les appareils deja appaires perdent l'acces."""
    nouveau = secrets.token_urlsafe(24)
    settings.set("serveur_jeton", nouveau)
    return nouveau


def adresse_locale() -> str:
    """L'adresse de cette machine sur le reseau local.

    On la determine en ouvrant une prise vers une adresse externe SANS rien
    lui envoyer : c'est le systeme qui choisit alors l'interface par laquelle
    il sortirait, et donc celle que le telephone peut joindre. Lire la liste
    des interfaces rendrait aussi bien la carte VPN et le Bluetooth, et on ne
    saurait pas laquelle proposer.
    """
    prise = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        prise.connect(("10.255.255.255", 1))
        return prise.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        prise.close()


# --- Macros -----------------------------------------------------------------
#
# Une macro est enregistree SUR LE PC, et le telephone ne peut que la nommer.
# Le contenu ne voyage jamais dans l'autre sens.

# Les seuls genres de macro acceptes. Liste FERMEE : c'est elle qui empeche
# le jeton du serveur de valoir un acces administrateur a distance.
GENRES = ("texte", "touches", "clic")


def macros() -> dict:
    """Les macros enregistrees, relues sur le disque a chaque appel.

    Relues, et pas prises dans le cache des reglages : le serveur peut tourner
    dans un processus qui n'est pas celui qui enregistre. Le 24/08/2026, une
    macro ajoutee pendant que le serveur tournait est restee invisible au
    telephone, qui affichait une liste vide sans qu'aucune erreur ne soit
    levee -- on a cherche du cote du reseau.

    Le fichier fait quelques centaines d'octets : le relire a chaque appel
    coute moins qu'une liste fausse.
    """
    donnees = settings.recharger().get("macros", {})
    return dict(donnees) if isinstance(donnees, dict) else {}


def enregistrer_macro(nom: str, genre: str, valeur: str) -> str:
    """Enregistre une macro, depuis le PC uniquement.

    `genre` vaut "texte" (taper une suite de caracteres), "touches" (une
    combinaison, par exemple "ctrl+s") ou "clic" (des coordonnees, par
    exemple "1200,400" ou "1200,400 droit"). Rien d'autre n'est accepte :
    ouvrir ce champ a une commande arbitraire reviendrait a offrir un shell
    distant a qui connait le jeton.

    Le clic execute des COORDONNEES enregistrees par l'utilisateur, jamais
    une cible cherchee a l'ecran. Le telephone appuie sur un bouton dont le
    contenu a ete decide devant la machine.
    """
    nom = str(nom).strip()
    if not nom:
        return "Une macro a besoin d'un nom."
    if genre not in GENRES:
        return f"Genre inconnu : {', '.join(chr(34) + g + chr(34) for g in GENRES)}."
    if not str(valeur).strip():
        return "Une macro vide ne ferait rien."

    toutes = macros()
    toutes[nom] = {"genre": genre, "valeur": str(valeur)}
    settings.set("macros", toutes)
    return f"Macro \"{nom}\" enregistree ({genre})."


def oublier_macro(nom: str) -> str:
    toutes = macros()
    if nom not in toutes:
        return f"Aucune macro \"{nom}\"."
    del toutes[nom]
    settings.set("macros", toutes)
    return f"Macro \"{nom}\" supprimee."


def jouer_macro(nom: str) -> tuple[bool, str]:
    """Execute une macro enregistree. Rien d'autre n'est executable."""
    macro = macros().get(nom)
    if not macro:
        return False, f"Aucune macro \"{nom}\"."

    from assistant.skills import control

    genre, valeur = macro.get("genre"), macro.get("valeur", "")
    try:
        if genre == "texte":
            # ask : la macro a deja ete acceptee au moment ou on l'a
            # enregistree, sur le PC. Redemander a chaque appui rendrait la
            # telecommande inutilisable.
            control.taper(valeur, ask=lambda _t: True)
        elif genre == "touches":
            control.raccourci(valeur)
        elif genre == "clic":
            # "1200,400" ou "1200,400 droit" ou "1200,400 gauche double".
            morceaux = str(valeur).replace(",", " ").split()
            # Compter les morceaux ne suffit pas : "sans coordonnees" en fait
            # deux, passait la verification, et la macro s'annoncait jouee
            # alors qu'aucun clic n'etait parti. Un bouton du telephone qui
            # ne fait rien en disant que si est pire qu'un bouton en erreur.
            try:
                x, y = int(morceaux[0]), int(morceaux[1])
            except (IndexError, ValueError):
                return False, (f"La macro \"{nom}\" n'a pas de coordonnees "
                               f"lisibles : \"{valeur}\". Attendu par exemple "
                               "\"1200,400\" ou \"1200,400 droit\".")
            options = [m.lower() for m in morceaux[2:]]
            bouton = next((b for b in control.BOUTONS if b in options),
                          "gauche")
            control.cliquer(x, y, bouton=bouton, double="double" in options,
                            ask=lambda _t: True)
        else:
            return False, f"Genre de macro inconnu : {genre}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    return True, f"Macro \"{nom}\" jouee."


def journal(limite: int = 20) -> list[str]:
    """Ce que le serveur a recu, pour que rien ne se passe sans trace."""
    with _verrou:
        return list(_journal[-limite:])


def _noter(ligne: str) -> None:
    with _verrou:
        _journal.append(f"{time.strftime('%H:%M:%S')}  {ligne}")
        del _journal[:-200]


class _Poignee(BaseHTTPRequestHandler):
    server_version = "AssistantLocal"
    sys_version = ""

    def log_message(self, *_args) -> None:
        """Silence : la sortie par defaut part sur stderr et pollue le journal."""

    # --- garde-fous ---------------------------------------------------------

    def _autorise(self) -> bool:
        global _echecs

        with _verrou:
            if _echecs >= ECHECS_TOLERES:
                self._repondre(423, {"erreur": "trop d'echecs, serveur ferme"})
                return False

        fourni = (self.headers.get("X-Jeton")
                  or self._parametre("jeton") or "")
        if secrets.compare_digest(str(fourni), jeton()):
            return True

        with _verrou:
            _echecs += 1
            restants = ECHECS_TOLERES - _echecs
        _noter(f"REFUS depuis {self.client_address[0]} "
               f"({max(restants, 0)} essais restants)")
        self._repondre(401, {"erreur": "jeton invalide"})
        return False

    def _parametre(self, nom: str) -> str:
        from urllib.parse import parse_qs, urlparse

        return (parse_qs(urlparse(self.path).query).get(nom) or [""])[0]

    def _chemin(self) -> str:
        from urllib.parse import urlparse

        return urlparse(self.path).path.rstrip("/") or "/"

    def _corps(self) -> dict:
        try:
            taille = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if taille <= 0 or taille > CORPS_MAX:
            return {}
        try:
            return json.loads(self.rfile.read(taille).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _repondre(self, code: int, donnees: dict) -> None:
        charge = json.dumps(donnees, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(charge)))
        # Aucune page d'un autre site ne doit pouvoir appeler ce serveur
        # depuis le navigateur du telephone.
        self.send_header("Access-Control-Allow-Origin", "null")
        self.end_headers()
        self.wfile.write(charge)

    def _page(self, html: str) -> None:
        charge = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(charge)))
        self.end_headers()
        self.wfile.write(charge)

    # --- routes -------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - impose par BaseHTTPRequestHandler
        chemin = self._chemin()

        if chemin == "/":
            # La page elle-meme ne demande pas de jeton : elle n'affiche rien
            # tant qu'elle n'en a pas, et chacun de ses appels passe le
            # garde-fou.
            self._page(PAGE_MOBILE)
            return

        if not self._autorise():
            return

        if chemin == "/api/presse-papier":
            from assistant.skills import desk

            _noter(f"presse-papier lu par {self.client_address[0]}")
            self._repondre(200, {"texte": desk.lire_presse_papier()})
            return

        if chemin == "/api/macros":
            self._repondre(200, {"macros": [
                {"nom": nom, "genre": m.get("genre")}
                for nom, m in sorted(macros().items())
            ]})
            return

        self._repondre(404, {"erreur": "route inconnue"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._autorise():
            return
        chemin = self._chemin()
        corps = self._corps()

        if chemin == "/api/presse-papier":
            from assistant.skills import desk

            texte = str(corps.get("texte") or "")
            if not texte:
                self._repondre(400, {"erreur": "texte vide"})
                return
            desk.ecrire_presse_papier(texte)
            _noter(f"presse-papier ecrit depuis {self.client_address[0]} "
                   f"({len(texte)} caracteres)")
            self._repondre(200, {"ok": True})
            return

        if chemin == "/api/macros/jouer":
            nom = str(corps.get("nom") or "")
            ok, message = jouer_macro(nom)
            _noter(f"macro \"{nom}\" demandee par {self.client_address[0]} : "
                   f"{'jouee' if ok else message}")
            self._repondre(200 if ok else 400,
                           {"ok": ok, "message": message})
            return

        self._repondre(404, {"erreur": "route inconnue"})


PAGE_MOBILE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Assistant local</title>
<style>
 body{font-family:system-ui,sans-serif;background:#0b1220;color:#e6edf7;
      margin:0;padding:18px}
 h1{font-size:19px;margin:0 0 16px}
 textarea{width:100%;height:130px;background:#111a2b;color:#e6edf7;
          border:1px solid #24344d;border-radius:10px;padding:10px;
          font-size:16px;box-sizing:border-box}
 button{background:#5aa2ff;color:#06101f;border:0;border-radius:10px;
        padding:13px 16px;font-size:16px;font-weight:600;margin:6px 6px 0 0}
 .macro{background:#111a2b;color:#e6edf7;border:1px solid #24344d;
        display:block;width:100%;text-align:left;margin-top:8px}
 #etat{margin-top:14px;color:#93a4bf;font-size:14px;min-height:20px}
</style></head><body>
<h1>Assistant local</h1>
<textarea id="zone" placeholder="Texte a envoyer vers le PC"></textarea>
<div>
 <button onclick="envoyer()">Envoyer au PC</button>
 <button onclick="recevoir()">Lire le PC</button>
</div>
<h1 style="margin-top:22px">Macros</h1>
<div id="macros"></div>
<div id="etat"></div>
<script>
// Le jeton arrive une seule fois dans l'adresse, puis il est range et
// EFFACE de la barre : sans cela il resterait dans l'historique du
// navigateur et dans tout partage de lien.
const p = new URLSearchParams(location.search);
if (p.get('jeton')) {
  localStorage.setItem('jeton', p.get('jeton'));
  history.replaceState({}, '', location.pathname);
}
const J = () => localStorage.getItem('jeton') || '';
const dire = (m) => document.getElementById('etat').textContent = m;

async function api(route, options = {}) {
  options.headers = Object.assign({'X-Jeton': J(),
    'Content-Type': 'application/json'}, options.headers || {});
  const r = await fetch(route, options);
  if (r.status === 401) { dire('Jeton refuse. Rescanne le QR code.'); return null; }
  if (r.status === 423) { dire('Serveur ferme apres trop d essais.'); return null; }
  return r.json();
}
async function envoyer() {
  const t = document.getElementById('zone').value;
  if (!t) { dire('Rien a envoyer.'); return; }
  const r = await api('/api/presse-papier',
    {method: 'POST', body: JSON.stringify({texte: t})});
  if (r) dire('Copie dans le presse-papier du PC.');
}
async function recevoir() {
  const r = await api('/api/presse-papier');
  if (r) { document.getElementById('zone').value = r.texte; dire('Recu du PC.'); }
}
async function charger() {
  if (!J()) { dire('Aucun jeton : scanne le QR code affiche sur le PC.'); return; }
  const r = await api('/api/macros');
  if (!r) return;
  const d = document.getElementById('macros');
  d.innerHTML = '';
  if (!r.macros.length) { d.textContent = 'Aucune macro enregistree sur le PC.'; return; }
  for (const m of r.macros) {
    const b = document.createElement('button');
    b.className = 'macro';
    b.textContent = m.nom;
    b.onclick = async () => {
      const x = await api('/api/macros/jouer',
        {method: 'POST', body: JSON.stringify({nom: m.nom})});
      if (x) dire(x.message);
    };
    d.appendChild(b);
  }
}
charger();
</script></body></html>"""


def demarrer(port: int = PORT_DEFAUT) -> str:
    """Allume le serveur. Rend l'adresse a ouvrir sur le telephone."""
    global _serveur, _fil, _echecs

    if _serveur is not None:
        return f"Deja allume : {url(port)}"

    hote = adresse_locale()
    try:
        # On se lie a l'adresse locale et a elle seule. 0.0.0.0 ecouterait
        # aussi sur un VPN ou un partage de connexion, sans qu'on l'ait voulu.
        _serveur = ThreadingHTTPServer((hote, port), _Poignee)
    except OSError as exc:
        return f"Impossible d'ouvrir le port {port} sur {hote} : {exc}"

    with _verrou:
        _echecs = 0
        _journal.clear()
    # Fil DAEMON, volontairement : la fenetre de l'assistant doit pouvoir se
    # fermer sans qu'un serveur oublie retienne le processus en vie. La
    # contrepartie est que le serveur meurt avec son processus -- voir servir()
    # pour l'usage hors interface.
    _fil = threading.Thread(target=_serveur.serve_forever,
                            name="serveur-local", daemon=True)
    _fil.start()
    _noter(f"serveur allume sur {hote}:{port}")
    return url(port, hote)


def servir(port: int = PORT_DEFAUT) -> None:
    """Allume le serveur et BLOQUE tant qu'il tourne.

    Pour tout ce qui n'est pas l'interface graphique : un script, la ligne de
    commande, une tache. Sans cela, le serveur s'eteint a la fin du script qui
    l'a lance -- le 24/08/2026, un appairage a affiche son QR code alors que
    plus rien n'ecoutait deja, et il a fallu regarder les ports pour s'en
    apercevoir. Le message annoncait "serveur allume", ce qui etait vrai
    pendant quelques millisecondes.
    """
    adresse = demarrer(port)
    if adresse.startswith("Impossible"):
        print(adresse)
        return
    print(f"Serveur local sur {adresse_locale()}:{port}. Ctrl+C pour arreter.")
    try:
        while allume():
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n" + arreter())


def arreter() -> str:
    global _serveur, _fil

    if _serveur is None:
        return "Le serveur n'etait pas allume."
    _serveur.shutdown()
    _serveur.server_close()
    _serveur, _fil = None, None
    return "Serveur eteint. Le telephone ne peut plus rien envoyer."


def allume() -> bool:
    return _serveur is not None


def url(port: int = PORT_DEFAUT, hote: str = "") -> str:
    return f"http://{hote or adresse_locale()}:{port}/?jeton={jeton()}"


def appairer(port: int = PORT_DEFAUT) -> str:
    """Allume le serveur et affiche le QR code a scanner avec le telephone.

    Le QR plutot que l'adresse ecrite : le jeton fait trente-deux caracteres,
    et le recopier sur un clavier de telephone se solde par une faute de
    frappe qu'on prend ensuite pour une panne du serveur.

    Le QR contient le jeton. Il ouvre donc la porte a qui le photographie :
    c'est dit dans la reponse, parce qu'un code affiche a l'ecran pendant une
    reunion en visio est exactement le genre de detail auquel personne ne
    pense.
    """
    import tempfile
    from pathlib import Path

    adresse = demarrer(port)
    if adresse.startswith("Impossible"):
        return adresse

    try:
        import segno

        image = Path(tempfile.gettempdir()) / "assistant_appairage.png"
        segno.make(adresse, error="m").save(
            str(image), scale=8, border=3, dark="#000000", light="#ffffff")
        import subprocess

        subprocess.Popen(["cmd", "/c", "start", "", str(image)],
                         creationflags=0x08000000)
        ouvert = f"\n  QR code ouvert : {image}"
    except Exception as exc:  # noqa: BLE001 - l'adresse reste utilisable sans lui
        ouvert = (f"\n  (QR code indisponible : {type(exc).__name__}) "
                  "recopie l'adresse a la main.")

    return (
        f"Serveur allume sur {adresse_locale()}:{port}.{ouvert}\n"
        "  Scanne le QR avec l'appareil photo du telephone, sur le MEME "
        "reseau Wi-Fi.\n\n"
        "  IL VIT TANT QUE CETTE APPLICATION RESTE OUVERTE. La fermer coupe "
        "la liaison :\n"
        "  ce n'est pas une panne, et le telephone retrouvera le serveur au "
        "prochain lancement.\n\n"
        "  Ce code contient la cle d'acces : qui le photographie peut "
        "envoyer du texte\n"
        "  et declencher tes macros. Ne le laisse pas affiche a l'ecran "
        "devant d'autres.\n"
        "  Demande-moi d'eteindre le serveur quand tu n'en as plus besoin."
    )


def etat(port: int = PORT_DEFAUT) -> str:
    """Ce que le serveur fait, en clair."""
    if not allume():
        return ("Serveur local ETEINT. Rien n'ecoute sur le reseau.\n"
                "  Demande-moi de l'allumer pour utiliser le presse-papier "
                "partage et les macros depuis le telephone.")

    lignes = [f"Serveur local ALLUME sur {adresse_locale()}:{port}", ""]
    lignes.append(f"  {len(macros())} macros enregistrees")
    with _verrou:
        restants = ECHECS_TOLERES - _echecs
    if restants < ECHECS_TOLERES:
        lignes.append(f"  {restants} essais de jeton restants avant fermeture")
    recent = journal(8)
    if recent:
        lignes.append("")
        lignes.append("  Dernieres requetes :")
        lignes.extend(f"    {l}" for l in recent)
    lignes.append("")
    lignes.append("  Le trafic circule en clair sur le reseau local : a "
                  "n'allumer que chez soi.")
    return "\n".join(lignes)
