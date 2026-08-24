"""Les deux panneaux qui touchent au reseau : la ligne, et le telephone.

Ils sont ensemble parce qu'ils partagent la seule chose qui compte ici : ce
sont les deux endroits de l'application ou quelque chose sort de la machine,
ou y entre. Tout le reste travaille sur ce PC et n'en bouge pas.

Aucun des deux ne fait quoi que ce soit a l'ouverture. Un test de debit dure
une dizaine de secondes et contacte un tiers ; un serveur ouvre une porte sur
le reseau de la maison. Ni l'un ni l'autre ne doit partir parce qu'on a
clique sur une icone en cherchant autre chose.
"""
from __future__ import annotations

import threading
import tkinter as tk

from assistant import theme as t
from assistant.widgets import RoundButton, ScrollArea


class Connexion(tk.Frame):
    """Le panneau Connexion : mesurer la vitesse reelle de la ligne."""

    def __init__(self, parent, window):
        super().__init__(parent, bg=t.BG)
        self.window = window
        self.occupe = False

        self.zone = ScrollArea(self, bg=t.BG)
        self.zone.pack(fill="both", expand=True)
        corps = self.zone.inner

        tk.Label(corps, text=t.espacer("vitesse de la ligne"), bg=t.BG,
                 fg=t.ACCENT_DEEP, font=t.FONT_HUD, anchor="w").pack(
            fill="x", padx=t.PAD_L, pady=(t.PAD_L, 4))

        cadre = tk.Frame(corps, bg=t.SURFACE)
        cadre.pack(fill="x", padx=t.PAD_L)

        rangee = tk.Frame(cadre, bg=t.SURFACE)
        rangee.pack(fill="x", padx=t.PAD_L, pady=t.PAD)

        gauche = tk.Frame(rangee, bg=t.SURFACE)
        gauche.pack(side="left", fill="x", expand=True)
        tk.Label(gauche, text="Tester le debit", bg=t.SURFACE, fg=t.TEXT,
                 font=t.FONT_LABEL, anchor="w").pack(fill="x")
        tk.Label(gauche,
                 text="Mesure la latence et la vitesse reelle, en une "
                      "dizaine de secondes. C'est la SEULE fonction de "
                      "l'assistant qui sort de la machine : elle envoie des "
                      "octets nuls au point de mesure de Cloudflare, et rien "
                      "de personnel.",
                 bg=t.SURFACE, fg=t.TEXT_FAINT, font=t.FONT_UI_TINY,
                 anchor="w", justify="left", wraplength=520).pack(fill="x")

        self.bouton = RoundButton(rangee, "Tester", self._tester, width=104,
                                  bg=t.ACCENT, fg="#0b1220",
                                  hover_bg="#79b4ff")
        self.bouton.pack(side="right", padx=(t.PAD, 0))

        self.resultat = tk.Label(
            corps, text="", bg=t.BG, fg=t.TEXT_DIM, font=t.FONT_MONO,
            anchor="w", justify="left", wraplength=640)
        self.resultat.pack(fill="x", padx=t.PAD_L, pady=(t.PAD_L, t.PAD))
        self.recharger()

    def _tester(self) -> None:
        if self.occupe:
            return
        self.occupe = True
        self.resultat.configure(text="Mesure en cours, une dizaine de "
                                     "secondes ...", fg=t.AMBER)

        def fil():
            from assistant.skills import debit

            texte = debit.tester(ask=lambda _t: True)
            self.window.post("appel", lambda: (
                self.resultat.configure(text=texte, fg=t.TEXT_DIM),
                setattr(self, "occupe", False),
            ))

        threading.Thread(target=fil, daemon=True).start()

    def recharger(self) -> None:
        if self.occupe:
            return
        # Le trafic instantane, pas un test : ouvrir le panneau ne doit
        # declencher aucune sortie.
        from assistant import panels

        self.resultat.configure(text=panels.content("connexion", force=True))


class Telephone(tk.Frame):
    """Le panneau Telephone : appairage, presse-papier partage, macros."""

    def __init__(self, parent, window):
        super().__init__(parent, bg=t.BG)
        self.window = window

        self.zone = ScrollArea(self, bg=t.BG)
        self.zone.pack(fill="both", expand=True)
        self._corps = self.zone.inner

        tk.Label(self._corps, text=t.espacer("liaison avec le telephone"),
                 bg=t.BG, fg=t.ACCENT_DEEP, font=t.FONT_HUD, anchor="w").pack(
            fill="x", padx=t.PAD_L, pady=(t.PAD_L, 4))

        cadre = tk.Frame(self._corps, bg=t.SURFACE)
        cadre.pack(fill="x", padx=t.PAD_L)

        tk.Label(cadre,
                 text="Copier un texte sur le telephone et le coller ici, "
                      "et declencher tes macros a distance. Le serveur "
                      "n'ecoute que sur le reseau local, il est eteint par "
                      "defaut, et il vit tant que cette fenetre reste "
                      "ouverte.",
                 bg=t.SURFACE, fg=t.TEXT_FAINT, font=t.FONT_UI_TINY,
                 anchor="w", justify="left", wraplength=600).pack(
            fill="x", padx=t.PAD_L, pady=(t.PAD, 4))

        boutons = tk.Frame(cadre, bg=t.SURFACE)
        boutons.pack(fill="x", padx=t.PAD_L, pady=(0, t.PAD))
        self.bouton_appairer = RoundButton(
            boutons, "Appairer", self._appairer, width=118,
            bg=t.ACCENT, fg="#0b1220", hover_bg="#79b4ff")
        self.bouton_appairer.pack(side="left")
        RoundButton(boutons, "Eteindre", self._eteindre, width=104,
                    bg=t.SURFACE_2, hover_bg=t.BORDER).pack(side="left",
                                                            padx=(t.PAD, 0))

        # L'avertissement est dans le panneau, pas seulement dans une reponse
        # de l'assistant : le QR s'affiche ici, et c'est ici qu'il faut savoir
        # ce qu'il contient.
        tk.Label(cadre,
                 text="Le QR code contient la cle d'acces. Qui le "
                      "photographie peut envoyer du texte et declencher tes "
                      "macros : ne le laisse pas affiche devant d'autres.",
                 bg=t.SURFACE, fg=t.AMBER, font=t.FONT_UI_TINY,
                 anchor="w", justify="left", wraplength=600).pack(
            fill="x", padx=t.PAD_L, pady=(0, t.PAD))

        self.etat = tk.Label(
            self._corps, text="", bg=t.BG, fg=t.TEXT_DIM, font=t.FONT_MONO,
            anchor="w", justify="left", wraplength=640)
        self.etat.pack(fill="x", padx=t.PAD_L, pady=(t.PAD_L, t.PAD))
        self.recharger()

    def _appairer(self) -> None:
        self.etat.configure(text="Allumage du serveur ...", fg=t.AMBER)

        def fil():
            from assistant import serveur

            texte = serveur.appairer()
            self.window.post("appel", lambda: self.etat.configure(
                text=texte, fg=t.TEXT_DIM))

        threading.Thread(target=fil, daemon=True).start()

    def _eteindre(self) -> None:
        from assistant import serveur

        self.etat.configure(text=serveur.arreter(), fg=t.TEXT_DIM)

    def recharger(self) -> None:
        from assistant import serveur

        lignes = [serveur.etat()]
        macros = serveur.macros()
        lignes.append("")
        if macros:
            lignes.append("Macros declenchables depuis le telephone :")
            lignes.extend(f"  {nom}  ({m.get('genre')} : {m.get('valeur')})"
                          for nom, m in sorted(macros.items()))
        else:
            lignes.append("Aucune macro. Demande-moi par exemple :")
            lignes.append("  \"enregistre une macro Sauvegarder qui fait "
                          "ctrl+s\"")
        self.etat.configure(text="\n".join(lignes))
