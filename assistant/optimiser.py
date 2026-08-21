"""Menu d'optimisation : cocher et decocher ce qui demarre avec Windows.

Une liste en texte ne suffit pas. L'utilisateur veut voir ce qui se lance,
comprendre a quoi ca sert, et le decocher sur place -- pas dicter une phrase
pour chaque programme.

Chaque bascule passe par assistant.skills.fixes, donc par le meme garde-fou
que le reste : la commande exacte est sauvegardee avant d'etre retiree du
registre, et l'action est journalisee.
"""
from __future__ import annotations

import threading
import tkinter as tk

from assistant import theme as t
from assistant.util import human_size
from assistant.widgets import ScrollArea

# Programmes de demarrage courants, et ce qu'on perd a les desactiver. Sans
# cette traduction, personne ne sait si "RzAppEngine" est important.
CONNUS = {
    "steam": ("Steam se lancera a la demande, quand tu ouvres un jeu.",
              "sans risque"),
    "discord": ("Discord ne s'ouvrira plus tout seul. Tu le lances quand tu "
                "en as besoin.", "sans risque"),
    "epic": ("Le launcher Epic se lancera avec tes jeux Epic.", "sans risque"),
    "eadm": ("L'application EA se lancera avec tes jeux EA.", "sans risque"),
    "riotclient": ("Le client Riot se lancera avec Valorant ou LoL.",
                   "sans risque"),
    "razer": ("Les profils d'eclairage et les macros Razer ne seront plus "
              "appliques au demarrage.", "a voir"),
    "rzapp": ("Les profils d'eclairage et les macros Razer ne seront plus "
              "appliques au demarrage.", "a voir"),
    "corsair": ("Les profils d'eclairage Corsair ne seront plus appliques.",
                "a voir"),
    "icue": ("Les profils d'eclairage Corsair ne seront plus appliques.",
             "a voir"),
    "nvidia": ("Les parametres NVIDIA restent actifs, seule l'interface ne "
               "se lance plus.", "sans risque"),
    "onedrive": ("La synchronisation OneDrive s'arretera jusqu'au prochain "
                 "lancement.", "attention"),
    "dropbox": ("La synchronisation Dropbox s'arretera jusqu'au prochain "
                "lancement.", "attention"),
    "edge": ("Edge ne prechargera plus au demarrage. Il s'ouvrira juste un "
             "peu moins vite.", "sans risque"),
    "teams": ("Teams ne s'ouvrira plus tout seul.", "sans risque"),
    "spotify": ("Spotify ne s'ouvrira plus tout seul.", "sans risque"),
    "claude": ("Claude ne s'ouvrira plus tout seul.", "sans risque"),
    "assistantlocal": ("Cet assistant ne s'ouvrira plus avec Windows.",
                       "a voir"),
    "unified remote": ("Le serveur Unified Remote ne demarrera plus : ton "
                       "telephone ne pourra plus piloter le PC.", "attention"),
}

COULEUR_RISQUE = {
    "sans risque": t.GREEN,
    "a voir": t.AMBER,
    "attention": t.RED,
}


def _conseil(nom: str, exe: str) -> tuple[str, str]:
    """Ce qu'on perd a desactiver ce programme, et le niveau de risque."""
    cible = f"{nom} {exe}".lower()
    for cle, (texte, risque) in CONNUS.items():
        if cle in cible:
            return texte, risque
    return ("Programme non reconnu. Desactive-le seulement si tu sais a quoi "
            "il sert.", "a voir")


class StartupOptimizer(tk.Frame):
    """Liste cochable des programmes lances avec Windows."""

    def __init__(self, parent, window):
        super().__init__(parent, bg=t.BG)
        self.window = window
        self.vars: dict[str, tk.BooleanVar] = {}
        self.lignes: dict[str, tk.Label] = {}
        self.occupe = False

        self._entete()
        self.zone = ScrollArea(self, bg=t.BG)
        self.zone.pack(fill="both", expand=True, padx=t.PAD_XL,
                       pady=(0, t.PAD_L))
        self.recharger()

    # --- construction ------------------------------------------------------

    def _entete(self) -> None:
        haut = tk.Frame(self, bg=t.BG)
        haut.pack(fill="x", padx=t.PAD_XL, pady=(t.PAD_L, t.PAD))

        self.resume = tk.Label(
            haut, text="Lecture des programmes de demarrage ...", bg=t.BG,
            fg=t.TEXT_DIM, font=t.FONT_UI_SMALL, anchor="w", justify="left",
        )
        self.resume.pack(side="left")

        self.etat = tk.Label(haut, text="", bg=t.BG, fg=t.TEXT_FAINT,
                             font=t.FONT_UI_TINY, anchor="e")
        self.etat.pack(side="right")

        explication = tk.Label(
            self,
            text="Decoche un programme pour l'empecher de se lancer avec "
                 "Windows. Recoche-le pour le remettre : la commande exacte "
                 "est conservee, rien n'est perdu.",
            bg=t.BG, fg=t.TEXT_FAINT, font=t.FONT_UI_TINY,
            anchor="w", justify="left", wraplength=760,
        )
        explication.pack(fill="x", padx=t.PAD_XL, pady=(0, t.PAD))

    def recharger(self) -> None:
        for enfant in self.zone.inner.winfo_children():
            enfant.destroy()
        self.vars.clear()
        self.lignes.clear()

        def travail():
            from assistant.skills import fixes, system

            items = system.startup_items()
            desactives = dict(fixes.desactivations_brutes())
            self.window.post("appel",
                             lambda: self._afficher(items, desactives))

        threading.Thread(target=travail, daemon=True).start()

    def _afficher(self, items: list[dict], desactives: dict) -> None:
        actifs = len(items)
        total = actifs + len(desactives)
        self.resume.configure(
            text=f"{total} programmes connus  -  {actifs} actifs, "
                 f"{len(desactives)} desactives")

        for item in items:
            self._ligne(item["name"], item, actif=True)

        for nom, commande in desactives.items():
            self._ligne(nom, {"name": nom, "command": commande,
                              "exe": "", "source": "desactive"}, actif=False)

        # La molette doit continuer a fonctionner au-dessus des cases.
        self.zone.bind_wheel_recursive()

    def _ligne(self, nom: str, item: dict, actif: bool) -> None:
        cadre = tk.Frame(self.zone.inner, bg=t.SURFACE)
        cadre.pack(fill="x", pady=3)

        haut = tk.Frame(cadre, bg=t.SURFACE)
        haut.pack(fill="x", padx=t.PAD_L, pady=(t.PAD, 2))

        var = tk.BooleanVar(value=actif)
        self.vars[nom] = var

        case = tk.Checkbutton(
            haut, variable=var, bg=t.SURFACE, activebackground=t.SURFACE,
            selectcolor=t.SURFACE_2, highlightthickness=0, bd=0,
            cursor="hand2", command=lambda n=nom: self._basculer(n),
        )
        case.pack(side="left")

        tk.Label(haut, text=nom, bg=t.SURFACE,
                 fg=t.TEXT if actif else t.TEXT_FAINT,
                 font=t.FONT_LABEL, anchor="w").pack(side="left", padx=(4, 8))

        if item.get("running"):
            tk.Label(haut, text="en cours", bg=t.SURFACE, fg=t.GREEN,
                     font=t.FONT_UI_TINY).pack(side="left")

        if item.get("size"):
            tk.Label(haut, text=human_size(item["size"]), bg=t.SURFACE,
                     fg=t.TEXT_FAINT, font=t.FONT_UI_TINY).pack(side="right")

        conseil, risque = _conseil(nom, item.get("exe", ""))
        tk.Label(haut, text=risque, bg=t.SURFACE,
                 fg=COULEUR_RISQUE.get(risque, t.TEXT_FAINT),
                 font=t.FONT_UI_TINY).pack(side="right", padx=(0, t.PAD_L))

        detail = tk.Label(
            cadre, text=conseil, bg=t.SURFACE, fg=t.TEXT_DIM,
            font=t.FONT_UI_TINY, anchor="w", justify="left", wraplength=700,
        )
        detail.pack(fill="x", padx=(t.PAD_L + 22, t.PAD_L))

        if item.get("publisher") or item.get("exe"):
            source = " - ".join(x for x in (item.get("publisher"),
                                            item.get("exe")) if x)
            tk.Label(cadre, text=source[:130], bg=t.SURFACE, fg=t.TEXT_FAINT,
                     font=t.FONT_MONO, anchor="w").pack(
                fill="x", padx=(t.PAD_L + 22, t.PAD_L))

        message = tk.Label(cadre, text="", bg=t.SURFACE, fg=t.TEXT_FAINT,
                           font=t.FONT_UI_TINY, anchor="w")
        message.pack(fill="x", padx=(t.PAD_L + 22, t.PAD_L), pady=(0, t.PAD))
        self.lignes[nom] = message

    # --- action ------------------------------------------------------------

    def _basculer(self, nom: str) -> None:
        if self.occupe:
            return
        self.occupe = True
        veut_actif = self.vars[nom].get()
        self.lignes[nom].configure(text="en cours ...", fg=t.AMBER)

        def travail():
            from assistant.skills import fixes

            # Le garde-fou reste en place : on repond oui ici parce que le
            # clic sur la case EST l'accord de l'utilisateur, et l'action
            # reste journalisee et reversible.
            oui = lambda _texte: True
            if veut_actif:
                resultat = fixes.reactiver_demarrage(nom, ask=oui)
            else:
                resultat = fixes.desactiver_demarrage(nom, ask=oui)

            def fini():
                self.lignes[nom].configure(
                    text=resultat.message[:110],
                    fg=t.GREEN if resultat.ok else t.RED)
                if not resultat.ok:
                    self.vars[nom].set(not veut_actif)
                self.occupe = False

            self.window.post("appel", fini)

        threading.Thread(target=travail, daemon=True).start()
