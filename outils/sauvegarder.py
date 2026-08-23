"""Met les quatre copies du depot au meme point, en une commande.

    .venv\\Scripts\\python.exe outils\\sauvegarder.py

Il y a quatre exemplaires de l'historique, et ils protegent de choses
differentes :

  - le dossier de travail, ou l'on code ;
  - un depot nu sur H:, toujours frais mais dans le meme boitier ;
  - un bundle sur la cle USB, qui survit au vol et a l'incendie parce qu'il
    est debranche -- et qui vieillit des qu'on oublie de le refaire ;
  - GitHub, qui survit a la perte de la machine entiere, mais qui depend
    d'un tiers et d'une connexion.

Aucun des quatre ne couvre ce que les autres couvrent. C'est pour ca qu'ils
sont quatre, et pas un.

Ce script existe parce que la troisieme etape etait faite a la main, et
demandee a chaque fois. Six allers-retours pour le meme geste : c'est une
routine, pas une decision.

Le bundle est TOUJOURS restaure avant de remplacer l'ancien. Une sauvegarde
qu'on n'a jamais restauree n'est pas une sauvegarde, c'est un fichier dont on
espere quelque chose.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DISTANT = "sauvegarde"
EN_LIGNE = "origin"
CLE = Path("D:/")

# Le nom de la branche principale a change le 23/08/2026 : master -> main, en
# publiant sur GitHub dont c'est le defaut. Il etait ecrit en dur a cinq
# endroits ici, et le script serait tombe sur "unknown revision" a la premiere
# sauvegarde -- apres avoir annonce le contraire, puisque tete() ne verifie
# pas son code de retour.
BRANCHE = "main"


def git(*args, cwd: Path | None = None) -> tuple[int, str]:
    resultat = subprocess.run(
        ["git", *args], cwd=str(cwd or RACINE),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return resultat.returncode, (resultat.stdout or "") + (resultat.stderr or "")


def tete() -> str:
    _code, sortie = git("rev-parse", BRANCHE)
    return sortie.strip()


def pousser_sur_h() -> bool:
    code, sortie = git("push", DISTANT, BRANCHE)
    if code != 0:
        print(f"  H:  ECHEC du push\n{sortie.strip()}")
        return False

    # Constate, pas rapporte : on relit la tete du depot distant.
    code, distant = git("--git-dir=H:/Sauvegardes/Assistant.git",
                        "rev-parse", BRANCHE)
    if code != 0 or distant.strip() != tete():
        print("  H:  le depot distant ne porte pas la meme tete")
        return False
    print(f"  H:  a jour ({distant.strip()[:7]})")
    return True


def pousser_sur_github() -> bool | None:
    """Pousse sur le depot en ligne, et rend None s'il n'y en a pas.

    None et False ne disent pas la meme chose : pas de distant configure,
    c'est un depot clone ailleurs ou l'on ne publie pas -- rien a signaler.
    Un push refuse, en revanche, est un vrai probleme.

    Une panne de reseau ne doit pas faire echouer la sauvegarde : H: et la
    cle sont deja faits a ce stade, et ce sont eux qui protegent du plus
    probable. On le dit, on ne bloque pas.
    """
    code, _sortie = git("remote", "get-url", EN_LIGNE)
    if code != 0:
        return None

    code, sortie = git("push", EN_LIGNE, BRANCHE)
    if code != 0:
        print(f"  GitHub ECHEC du push\n{sortie.strip()}")
        return False

    # Constate, pas rapporte : on relit la tete du depot distant, comme pour
    # H:. Un push peut reussir sur une autre branche que celle qu'on croit.
    code, sortie = git("ls-remote", EN_LIGNE, BRANCHE)
    distant = sortie.split()[0] if code == 0 and sortie.split() else ""
    if distant != tete():
        print(f"  GitHub le depot en ligne ne porte pas la meme tete "
              f"({distant[:7] or 'introuvable'})")
        return False
    print(f"  GitHub a jour ({distant[:7]})")
    return True


def refaire_le_bundle() -> bool:
    if not CLE.is_dir():
        print("  USB non branchee -- bundle non refait. Rebranche la cle et "
              "relance ce script.")
        return False

    attendu = tete()
    provisoire = CLE / "Assistant-nouveau.bundle"

    code, sortie = git("bundle", "create", str(provisoire), "--all")
    if code != 0:
        print(f"  USB ECHEC de la creation\n{sortie.strip()}")
        return False

    # Restauration REELLE avant de toucher a l'ancien : c'est la seule preuve
    # que le fichier redonne le depot.
    with tempfile.TemporaryDirectory() as dossier:
        essai = Path(dossier) / "essai"
        code, sortie = git("clone", "--quiet", str(provisoire), str(essai))
        if code != 0:
            print(f"  USB le bundle ne se restaure PAS -- ancien conserve\n{sortie.strip()}")
            provisoire.unlink(missing_ok=True)
            return False
        _code, restaure = git("rev-parse", BRANCHE, cwd=essai)
        if restaure.strip() != attendu:
            print(f"  USB restauration incoherente : {restaure.strip()[:7]} "
                  f"au lieu de {attendu[:7]} -- ancien conserve")
            provisoire.unlink(missing_ok=True)
            return False

    anciens = sorted(CLE.glob("Assistant-*.bundle"))
    final = CLE / f"Assistant-{datetime.now():%Y-%m-%d_%Hh%M}.bundle"
    shutil.move(str(provisoire), str(final))
    for vieux in anciens:
        if vieux != final:
            vieux.unlink(missing_ok=True)

    taille = final.stat().st_size / 1024**2
    print(f"  USB a jour ({attendu[:7]}) -- {final.name}, {taille:.0f} Mo, "
          "restaure pour verification")
    return True


def main() -> int:
    code, sortie = git("status", "--porcelain")
    modifies = [l for l in sortie.splitlines() if l.strip()]
    if modifies:
        print("  L'arbre n'est pas propre -- commite d'abord :")
        for ligne in modifies[:10]:
            print(f"    {ligne}")
        return 1

    print(f"  {BRANCHE} : {tete()[:7]}")
    ok_h = pousser_sur_h()
    ok_usb = refaire_le_bundle()
    ok_ligne = pousser_sur_github()

    manquants = []
    if not ok_usb:
        manquants.append("la cle USB")
    if ok_ligne is False:
        manquants.append("GitHub")

    if ok_h and not manquants:
        combien = "quatre" if ok_ligne else "trois"
        print(f"\n  Les {combien} copies sont au meme point.")
        return 0
    if ok_h:
        print(f"\n  H: est a jour. Reste a refaire : {', '.join(manquants)}.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
