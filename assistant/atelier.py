"""Panneau Reparer Windows : les outils de Microsoft, derriere trois boutons.

sfc et DISM existent depuis vingt ans et personne ne les lance, parce qu'il
faut savoir qu'ils existent, connaitre leur nom exact, ouvrir une invite
ADMINISTRATEUR et taper la ligne sans se tromper. Ce panneau ne fait rien que
la ligne de commande ne fasse : il rend visible ce qui l'etait deja pour qui
savait ou regarder.

L'ordre entre les deux est affiche, parce que c'est la seule chose qui compte
et que rien dans Windows ne la dit : quand sfc annonce qu'il n'a pas pu
reparer, le relancer ne sert a rien. C'est sa source qui est abimee, et c'est
DISM qui la refait.

Chaque bouton ouvre une fenetre administrateur visible et rend la main. Ces
commandes durent de cinq a trente minutes : les attendre figerait la fenetre,
et les cacher ferait qu'on les interrompe.
"""
from __future__ import annotations

import threading
import tkinter as tk

from assistant import theme as t
from assistant.widgets import RoundButton, ScrollArea


class Atelier(tk.Frame):
    """Le panneau Reparer Windows, en widgets."""

    def __init__(self, parent, window):
        super().__init__(parent, bg=t.BG)
        self.window = window
        self.occupe = False

        self.zone = ScrollArea(self, bg=t.BG)
        self.zone.pack(fill="both", expand=True)
        self._corps = self.zone.inner

        self._construire()
        self.recharger()

    def _section(self, titre: str) -> tk.Frame:
        tk.Label(self._corps, text=t.espacer(titre), bg=t.BG,
                 fg=t.ACCENT_DEEP, font=t.FONT_HUD, anchor="w").pack(
            fill="x", padx=t.PAD_L, pady=(t.PAD_L, 4))
        cadre = tk.Frame(self._corps, bg=t.SURFACE)
        cadre.pack(fill="x", padx=t.PAD_L)
        return cadre

    def _ligne(self, cadre, titre: str, explication: str, bouton: str,
               action) -> None:
        rangee = tk.Frame(cadre, bg=t.SURFACE)
        rangee.pack(fill="x", padx=t.PAD_L, pady=t.PAD)

        gauche = tk.Frame(rangee, bg=t.SURFACE)
        gauche.pack(side="left", fill="x", expand=True)
        tk.Label(gauche, text=titre, bg=t.SURFACE, fg=t.TEXT,
                 font=t.FONT_LABEL, anchor="w").pack(fill="x")
        tk.Label(gauche, text=explication, bg=t.SURFACE, fg=t.TEXT_FAINT,
                 font=t.FONT_UI_TINY, anchor="w", justify="left",
                 wraplength=520).pack(fill="x")

        RoundButton(rangee, bouton, action, width=104,
                    bg=t.SURFACE_2, hover_bg=t.BORDER).pack(side="right",
                                                            padx=(t.PAD, 0))

    def _construire(self) -> None:
        cadre = self._section("fichiers de windows")
        self._ligne(
            cadre, "Verifier les fichiers systeme",
            "Compare chaque fichier de Windows a sa version d'origine et "
            "remplace ceux qui sont abimes. 5 a 15 minutes.",
            "Verifier", self._sfc)
        self._ligne(
            cadre, "Reparer l'image de Windows",
            "A lancer SEULEMENT si la verification dit qu'elle n'a pas pu "
            "reparer : c'est sa source qui est abimee, et la relancer ne "
            "sert a rien. 10 a 30 minutes, utilise Internet.",
            "Reparer", self._dism)

        cadre = self._section("antivirus")
        self._ligne(
            cadre, "Analyser les menaces",
            "Met a jour les signatures, puis examine la machine avec "
            "Defender. Un examen mene avec de vieilles signatures rassure a "
            "tort.",
            "Analyser", self._scan)

        self.etat = tk.Label(
            self._corps, text="lecture de la protection ...", bg=t.BG,
            fg=t.TEXT_FAINT, font=t.FONT_UI_TINY, anchor="w",
            justify="left", wraplength=640)
        self.etat.pack(fill="x", padx=t.PAD_L, pady=(t.PAD_L, t.PAD))

    # --- actions ------------------------------------------------------------

    def _lancer(self, libelle: str, travail) -> None:
        """Execute dans un fil, et n'accepte qu'une chose a la fois.

        Deux reparations lancees ensemble se disputeraient le magasin de
        composants, et Windows en refuserait une sans dire laquelle.
        """
        if self.occupe:
            self.etat.configure(text="Une operation est deja en cours.",
                                fg=t.AMBER)
            return
        self.occupe = True
        self.etat.configure(text=f"{libelle} ...", fg=t.AMBER)

        def fil():
            message = travail()
            self.window.post("appel", lambda: (
                self.etat.configure(text=str(message), fg=t.TEXT_DIM),
                setattr(self, "occupe", False),
            ))

        threading.Thread(target=fil, daemon=True).start()

    def _sfc(self) -> None:
        from assistant.skills import fixes

        self._lancer("Verification des fichiers systeme",
                     lambda: str(fixes.verifier_fichiers_systeme(
                         ask=self.window._demander_accord)))

    def _dism(self) -> None:
        from assistant.skills import fixes

        self._lancer("Reparation de l'image",
                     lambda: str(fixes.reparer_image_windows(
                         ask=self.window._demander_accord)))

    def _scan(self) -> None:
        from assistant.skills import fixes

        self._lancer("Examen antivirus",
                     lambda: str(fixes.analyser_menaces(
                         ask=self.window._demander_accord)))

    # --- rafraichissement ---------------------------------------------------

    def recharger(self) -> None:
        if self.occupe:
            return

        def fil():
            from assistant.skills import fixes

            texte = fixes.menaces()
            self.window.post("appel", lambda: self.etat.configure(
                text=texte, fg=t.TEXT_DIM))

        threading.Thread(target=fil, daemon=True).start()
