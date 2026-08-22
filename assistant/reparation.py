"""Atelier de reparation : ce qui ne va pas, et le bouton qui le repare.

Le panneau precedent listait ce que l'assistant SAIT faire -- desactiver un
programme, arreter un processus, vider un cache. C'est un catalogue, pas un
diagnostic : il ne disait pas si quelque chose allait mal en ce moment, et il
fallait retourner dans la conversation pour agir.

Ici, chaque ligne est un probleme REELLEMENT detecte sur cette machine, avec
le bouton qui le corrige. Un bouton "Tout reparer" enchaine celles qui sont
cochees.

Deux regles heritees du reste de l'application :

  - rien n'est irreversible. Les suppressions partent a la corbeille, les
    programmes de demarrage gardent leur commande, un processus arrete se
    relance ;
  - tout passe par assistant.skills.fixes et assistant.safety, donc tout est
    journalise. Le clic sur le bouton EST l'accord de l'utilisateur.

Ce qui est volontairement absent : les caches Unreal et les points de
restauration. Les premiers coutent des heures de recompilation de shaders,
les seconds sont un filet de securite. Ni l'un ni l'autre n'a sa place
derriere un bouton "Tout reparer".
"""
from __future__ import annotations

import threading
import tkinter as tk
from dataclasses import dataclass, field
from typing import Callable

from assistant import theme as t
from assistant.util import human_size
from assistant.widgets import RoundButton, ScrollArea

# Un correctif qui rend moins que ca ne vaut pas la peine d'etre propose :
# la ligne coute plus d'attention qu'elle ne fait gagner.
GAIN_MINIMAL = 200 * 1024**2


@dataclass
class Reparation:
    cle: str
    titre: str
    detail: str
    action: Callable[[], str]
    gain: int = 0            # octets recuperes, 0 si sans rapport
    risque: str = "sans risque"
    auto: bool = True        # incluse dans "Tout reparer"
    faite: bool = False
    resultat: str = ""


# --- Detecteurs -------------------------------------------------------------
#
# Chacun rend la liste des reparations qu'il a trouvees. Aucun n'agit.

def _detecter_menage() -> list[Reparation]:
    """Dossiers temporaires et residus de jeux : de la place a reprendre.

    On ne touche pas a l'index tant qu'il se construit. La base vit en
    memoire partagee : lire pendant que le scan ecrit fait echouer sa
    finalisation sur "database table is locked", et l'index reste incomplet
    sans que rien ne le signale.
    """
    from assistant.index import db
    from assistant.skills import cleanup

    if not db.is_ready():
        return []

    trouvees = []
    try:
        candidats = cleanup.candidates()
    except Exception:  # noqa: BLE001
        return []

    for index, candidat in enumerate(candidats, 1):
        if candidat.size < GAIN_MINIMAL:
            continue
        # Les caches Unreal portent un avertissement : ils se reconstruisent,
        # mais au prix de plusieurs heures de shaders. Jamais en automatique.
        avertissement = bool(getattr(candidat, "caution", ""))
        trouvees.append(Reparation(
            cle=f"menage_{index}",
            titre=candidat.label,
            detail=f"{candidat.why} ({human_size(candidat.size)})",
            action=lambda i=index: cleanup.clean([i], ask=lambda _t: True),
            gain=candidat.size,
            risque="a voir" if avertissement else "sans risque",
            auto=not avertissement,
        ))
    return trouvees


def _detecter_processus() -> list[Reparation]:
    """Processus qui monopolisent un coeur entier."""
    from assistant.skills import fixes, system

    trouvees = []
    try:
        gourmands = system.core_hogs()
    except Exception:  # noqa: BLE001
        return []

    for hog in gourmands:
        nom = hog["name"]
        if nom.lower() in fixes.NEVER_KILL:
            # audiodg, dwm et consorts : on ne les arrete pas, mais le remede
            # connu vaut d'etre rappele.
            if hog.get("known"):
                trouvees.append(Reparation(
                    cle=f"info_{nom}",
                    titre=f"{nom} occupe {hog['cores_equivalent']} coeur(s)",
                    detail=hog["known"],
                    action=lambda: "Ce processus ne peut pas etre arrete sans "
                                   "faire tomber la session. Applique le "
                                   "remede indique.",
                    risque="attention",
                    auto=False,
                ))
            continue

        trouvees.append(Reparation(
            cle=f"proc_{hog['pid']}",
            titre=f"Arreter {nom}",
            detail=f"Occupe {hog['cores_equivalent']} coeur(s) en continu "
                   f"({hog['cpu_of_one_core']} % d'un coeur). "
                   "Le programme peut etre relance normalement.",
            action=lambda n=nom: str(
                fixes.arreter_processus(n, ask=lambda _t: True)),
            risque="a voir",
            auto=False,   # arreter un programme ouvert n'est jamais anodin
        ))
    return trouvees


def _detecter_demarrage() -> list[Reparation]:
    """Entree de demarrage Windows qui pointe sur une cible DISPARUE.

    Le defaut a reparer, c'est une entree qui ne lance plus rien : le dossier
    a ete deplace, l'exemplaire efface. Pas une entree qui designe un AUTRE
    exemplaire valide.

    La version precedente comparait a `startup.command()`, c'est-a-dire "moi".
    Sur une machine ou coexistent l'application installee et une version de
    developpement -- ce qui est le cas normal quand on la fabrique -- chacune
    voyait l'autre comme une erreur et proposait de prendre sa place. Ouvrir
    ce panneau depuis la mauvaise copie suffisait a defaire le choix de
    l'utilisateur, en lui annoncant qu'on reparait quelque chose.
    """
    import shlex
    from pathlib import Path

    from assistant import startup

    try:
        actif, inscrit = startup.status()
    except Exception:  # noqa: BLE001
        return []

    if not actif or not inscrit.strip():
        return []

    try:
        morceaux = shlex.split(inscrit, posix=False)
        cible = Path(morceaux[0].strip('"')) if morceaux else None
    except ValueError:
        cible = None

    if cible is not None and cible.exists():
        return []          # elle lance quelque chose : ce n'est pas un defaut

    return [Reparation(
        cle="demarrage",
        titre="Corriger le demarrage automatique",
        detail=f"L'entree inscrite dans Windows pointe sur un fichier qui "
               f"n'existe plus ({cible}). Elle ne lance donc rien du tout.",
        action=lambda: startup.enable(),
        risque="sans risque",
    )]


def _detecter_antivirus() -> list[Reparation]:
    """Signatures antivirus perimees."""
    from assistant.skills import hardware, shell

    try:
        donnees = hardware.collect()
    except Exception:  # noqa: BLE001
        return []

    defender = (donnees or {}).get("defender") or {}
    age = defender.get("signature_age")
    if not isinstance(age, (int, float)) or age <= 7:
        return []

    return [Reparation(
        cle="antivirus",
        titre="Mettre a jour la protection antivirus",
        detail=f"Les signatures datent de {age:.0f} jours. Une protection qui "
               "ne se met plus a jour ne reconnait pas les menaces recentes.",
        action=lambda: shell.run("Update-MpSignature",
                                 but="Mettre a jour les signatures antivirus",
                                 ask=lambda _t: True),
        risque="sans risque",
    )]


def _detecter_redemarrage() -> list[Reparation]:
    """Redemarrage en attente : rien a reparer, mais il faut le dire."""
    from assistant.skills import hardware

    try:
        donnees = hardware.collect()
    except Exception:  # noqa: BLE001
        return []

    if not (donnees or {}).get("reboot_pending"):
        return []

    return [Reparation(
        cle="redemarrage",
        titre="Un redemarrage est en attente",
        detail="Des mises a jour ne s'appliqueront qu'apres redemarrage. "
               "Cela explique quantite de comportements erratiques.",
        action=lambda: "A toi de choisir le moment : l'assistant ne redemarre "
                       "pas la machine sans qu'on le lui demande.",
        risque="a voir",
        auto=False,
    )]


DETECTEURS = (
    _detecter_demarrage,
    _detecter_antivirus,
    _detecter_menage,
    _detecter_processus,
    _detecter_redemarrage,
)


def detecter() -> list[Reparation]:
    """Passe tous les detecteurs. Un detecteur casse n'empeche pas les autres."""
    trouvees: list[Reparation] = []
    for detecteur in DETECTEURS:
        try:
            trouvees.extend(detecteur())
        except Exception:  # noqa: BLE001
            continue
    return trouvees


# --- Interface --------------------------------------------------------------

COULEUR_RISQUE = {
    "sans risque": t.GREEN,
    "a voir": t.AMBER,
    "attention": t.RED,
}


class Reparateur(tk.Frame):
    """Liste des reparations trouvees, avec un bouton par ligne et un global."""

    def __init__(self, parent, window):
        super().__init__(parent, bg=t.BG)
        self.window = window
        self.reparations: list[Reparation] = []
        self.cases: dict[str, tk.BooleanVar] = {}
        self.messages: dict[str, tk.Label] = {}
        self.boutons: dict[str, RoundButton] = {}
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

        gauche = tk.Frame(haut, bg=t.BG)
        gauche.pack(side="left", fill="x", expand=True)

        self.resume = tk.Label(
            gauche, text="Recherche de ce qui peut etre repare ...", bg=t.BG,
            fg=t.TEXT_DIM, font=t.FONT_UI_SMALL, anchor="w", justify="left")
        self.resume.pack(anchor="w")

        self.gain_total = tk.Label(gauche, text="", bg=t.BG, fg=t.ACCENT,
                                   font=t.FONT_UI_SMALL, anchor="w")
        self.gain_total.pack(anchor="w")

        self.bouton_tout = RoundButton(
            haut, "Tout reparer", self.tout_reparer, width=150,
            bg=t.ACCENT, fg="#06222A", hover_bg="#7BE4F2")
        self.bouton_tout.pack(side="right")
        self.bouton_tout.set_enabled(False)

        tk.Label(
            self,
            text="Chaque ligne est un probleme reellement detecte sur cette "
                 "machine. Rien n'est irreversible : les suppressions partent "
                 "a la corbeille, les programmes gardent leur commande, un "
                 "processus arrete se relance. \"Tout reparer\" n'execute que "
                 "les lignes cochees.",
            bg=t.BG, fg=t.TEXT_FAINT, font=t.FONT_UI_TINY,
            anchor="w", justify="left", wraplength=800,
        ).pack(fill="x", padx=t.PAD_XL, pady=(0, t.PAD))

    def recharger(self) -> None:
        for enfant in self.zone.inner.winfo_children():
            enfant.destroy()
        self.cases.clear()
        self.messages.clear()
        self.boutons.clear()
        self.resume.configure(text="Recherche de ce qui peut etre repare ...")
        self.gain_total.configure(text="")
        self.bouton_tout.set_enabled(False)

        def travail():
            trouvees = detecter()
            self.window.post("appel", lambda: self._afficher(trouvees))

        threading.Thread(target=travail, daemon=True).start()

    def _afficher(self, trouvees: list[Reparation]) -> None:
        from assistant.index import db

        self.reparations = trouvees

        # Sans cette mention, un panneau ouvert pendant le scan des disques
        # affiche une liste courte sans que rien n'explique ce qui manque.
        if not db.is_ready():
            tk.Label(
                self.zone.inner,
                text="Le scan des disques est encore en cours. Les gains "
                     "d'espace -- residus de jeux, dossiers temporaires, "
                     "caches -- apparaitront quand il sera fini.\n"
                     "Clique Actualiser dans une minute.",
                bg=t.SURFACE_2, fg=t.AMBER, font=t.FONT_UI_SMALL,
                anchor="w", justify="left", wraplength=760,
                padx=t.PAD_L, pady=t.PAD,
            ).pack(fill="x", pady=(0, t.PAD))

        if not trouvees:
            self.resume.configure(
                text="Rien a reparer. Aucun probleme corrigeable detecte.")
            tk.Label(
                self.zone.inner,
                text="Les disques, la memoire et Windows sont sains.\n\n"
                     "Ce panneau ne liste que ce qui peut etre corrige ici. "
                     "Pour l'etat complet de la machine, ouvre \"Problemes "
                     "detectes\".",
                bg=t.BG, fg=t.TEXT_DIM, font=t.FONT_UI_SMALL,
                justify="left", anchor="w",
            ).pack(fill="x", padx=t.PAD, pady=t.PAD_L)
            return

        automatiques = [r for r in trouvees if r.auto]
        gain = sum(r.gain for r in automatiques)
        self.resume.configure(
            text=f"{len(trouvees)} point(s) reparable(s), "
                 f"dont {len(automatiques)} coche(s) par defaut")
        if gain:
            self.gain_total.configure(
                text=f"{human_size(gain)} a recuperer")
        self.bouton_tout.set_enabled(bool(automatiques))

        for reparation in trouvees:
            self._ligne(reparation)

    def _ligne(self, reparation: Reparation) -> None:
        cadre = tk.Frame(self.zone.inner, bg=t.SURFACE)
        cadre.pack(fill="x", pady=3)

        haut = tk.Frame(cadre, bg=t.SURFACE)
        haut.pack(fill="x", padx=t.PAD_L, pady=(t.PAD, 2))

        var = tk.BooleanVar(value=reparation.auto)
        self.cases[reparation.cle] = var
        tk.Checkbutton(
            haut, variable=var, bg=t.SURFACE, activebackground=t.SURFACE,
            selectcolor=t.SURFACE_2, highlightthickness=0, bd=0,
            cursor="hand2", command=self._recalculer_gain,
        ).pack(side="left")

        tk.Label(haut, text=reparation.titre, bg=t.SURFACE, fg=t.TEXT,
                 font=t.FONT_LABEL, anchor="w").pack(side="left", padx=(4, 8))

        bouton = RoundButton(
            haut, "Reparer", lambda r=reparation: self.reparer(r),
            width=92, bg=t.SURFACE_2, hover_bg=t.BORDER)
        bouton.pack(side="right")
        self.boutons[reparation.cle] = bouton

        tk.Label(haut, text=reparation.risque, bg=t.SURFACE,
                 fg=COULEUR_RISQUE.get(reparation.risque, t.TEXT_FAINT),
                 font=t.FONT_UI_TINY).pack(side="right", padx=t.PAD_L)

        if reparation.gain:
            tk.Label(haut, text=human_size(reparation.gain), bg=t.SURFACE,
                     fg=t.ACCENT, font=t.FONT_UI_TINY).pack(side="right")

        tk.Label(
            cadre, text=reparation.detail, bg=t.SURFACE, fg=t.TEXT_DIM,
            font=t.FONT_UI_TINY, anchor="w", justify="left", wraplength=720,
        ).pack(fill="x", padx=(t.PAD_L + 22, t.PAD_L))

        message = tk.Label(cadre, text="", bg=t.SURFACE, fg=t.TEXT_FAINT,
                           font=t.FONT_UI_TINY, anchor="w", justify="left",
                           wraplength=720)
        message.pack(fill="x", padx=(t.PAD_L + 22, t.PAD_L), pady=(0, t.PAD))
        self.messages[reparation.cle] = message

    def _recalculer_gain(self) -> None:
        gain = sum(r.gain for r in self.reparations
                   if self.cases.get(r.cle) and self.cases[r.cle].get()
                   and not r.faite)
        self.gain_total.configure(
            text=f"{human_size(gain)} a recuperer" if gain else "")

    # --- action ------------------------------------------------------------

    def reparer(self, reparation: Reparation) -> None:
        """Execute une reparation."""
        if self.occupe or reparation.faite:
            return
        self._executer([reparation])

    def tout_reparer(self) -> None:
        """Execute toutes les reparations cochees, dans l'ordre affiche."""
        if self.occupe:
            return
        choisies = [r for r in self.reparations
                    if not r.faite and self.cases[r.cle].get()]
        if not choisies:
            self.resume.configure(text="Aucune ligne cochee.")
            return
        self._executer(choisies)

    def _executer(self, liste: list[Reparation]) -> None:
        self.occupe = True
        self.bouton_tout.set_enabled(False)
        self.bouton_tout.set_text("En cours")
        for reparation in liste:
            self.messages[reparation.cle].configure(text="en attente ...",
                                                    fg=t.TEXT_FAINT)
            self.boutons[reparation.cle].set_enabled(False)

        def travail():
            reussies = 0
            for reparation in liste:
                self.window.post("appel", lambda r=reparation: self.messages[
                    r.cle].configure(text="en cours ...", fg=t.AMBER))
                try:
                    resultat = reparation.action()
                    ok = True
                except Exception as exc:  # noqa: BLE001
                    resultat, ok = f"{type(exc).__name__}: {exc}", False

                # Les fonctions de correction rendent du texte : un echec s'y
                # annonce en mots, pas par une exception.
                minuscule = str(resultat).lower()
                if any(mot in minuscule for mot in
                       ("echec", "impossible", "refuse", "annulee",
                        "introuvable", "insuffisant")):
                    ok = False

                reparation.faite = ok
                reparation.resultat = str(resultat)
                reussies += ok

                self.window.post("appel", lambda r=reparation, o=ok: (
                    self.messages[r.cle].configure(
                        text=r.resultat[:200],
                        fg=t.GREEN if o else t.RED),
                    self.boutons[r.cle].set_enabled(not o),
                    self.boutons[r.cle].set_text("Fait" if o else "Reessayer"),
                ))

            def fini():
                self.occupe = False
                self.bouton_tout.set_text("Tout reparer")
                restantes = [r for r in self.reparations if not r.faite]
                self.bouton_tout.set_enabled(bool(restantes))
                self.resume.configure(
                    text=f"{reussies} reparation(s) effectuee(s) sur "
                         f"{len(liste)}. {len(restantes)} point(s) restant(s).")
                self._recalculer_gain()

            self.window.post("appel", fini)

        threading.Thread(target=travail, daemon=True).start()
