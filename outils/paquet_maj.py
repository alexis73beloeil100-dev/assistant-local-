"""Fabrique un paquet de mise a jour : uniquement ce qui a change.

L'installateur complet pese 1,15 Go. Livrer un correctif de trois lignes en
obligeant les gens a le retelecharger entier est le meilleur moyen qu'ils ne
le prennent jamais -- et 74 % de ce poids sont des bibliotheques CUDA qui
n'ont pas bouge depuis le premier jour.

Ce script compare le dossier livre au manifeste de la version deja publiee,
et compile un installateur qui ne contient que la difference. En pratique :
quelques dizaines de Mo au lieu de 1,15 Go.

    .venv\\Scripts\\python.exe outils\\paquet_maj.py 1.0.1

L'argument est la version DEJA PUBLIEE, celle dont on part. La version
d'arrivee est lue dans assistant/__init__.py.

Rien n'est envoye nulle part : le paquet se distribue comme le premier, a la
main. La promesse "aucune connexion sortante apres l'installation" reste
intacte -- c'est un argument central du projet, et un verificateur
automatique de mises a jour l'aurait annulee.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from outils import manifeste  # noqa: E402

LIVRE = RACINE / "dist" / "AssistantLocal"
SORTIE = RACINE / "installateur"
ISS = RACINE / "mise_a_jour.iss"

# Inno Setup s'installe en mode utilisateur ici : il n'est pas dans le PATH,
# et le chercher par "where" ne donne rien.
ISCC = (Path(os.environ.get("LOCALAPPDATA", ""))
        / "Programs" / "Inno Setup 6" / "ISCC.exe")

# Le meme que l'installateur complet : c'est ce qui fait reconnaitre la mise a
# jour comme une mise a jour, et non comme un second logiciel. Inno ajoute
# alors ses fichiers au journal de desinstallation existant, au lieu de le
# remplacer -- sans quoi desinstaller apres une mise a jour ne retirerait que
# les quelques fichiers du correctif, en laissant 2,5 Go derriere.
APP_ID = "8F3C1A62-4E7D-4B21-9C0E-2A5D6B7E9F14"


def entete(depuis: str, vers: str, ecart: dict) -> str:
    """Le bloc [Setup] du script genere."""
    quand = datetime.now().strftime("%d/%m/%Y a %H:%M")
    return f"""; Mise a jour {depuis} -> {vers} de l'Assistant local.
;
; FICHIER GENERE par outils/paquet_maj.py -- ne pas modifier a la main :
; la prochaine generation ecraserait la correction sans prevenir.
;
; Genere le {quand}
; {manifeste.resume(ecart)}

#define MonNom "Assistant local"
#define MonExe "AssistantLocal.exe"
#define MonEditeur "Assistant local"
#define MaVersion "{vers}"
#define VersionAttendue "{depuis}"

[Setup]
AppId={{{{{APP_ID}}}
AppName={{#MonNom}}
AppVersion={{#MaVersion}}
AppPublisher={{#MonEditeur}}
DefaultDirName={{localappdata}}\\AssistantLocal
; La mise a jour va la ou l'application est deja : Inno relit le dossier dans
; la base de registres. On n'ouvre donc pas la page du dossier, qui laisserait
; quelqu'un installer le correctif a cote de l'application au lieu de dedans.
UsePreviousAppDir=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
; Inno resout les chemins relatifs depuis le dossier du SCRIPT, pas depuis le
; repertoire courant. Sans cette ligne, deplacer le script genere -- ou le
; compiler depuis ailleurs -- fait chercher dist/ a cote de lui, et la
; compilation echoue sur un "source file does not exist" qui ne dit pas
; pourquoi. Le chemin est absolu : ce fichier est genere, jamais versionne.
SourceDir={RACINE}
OutputDir=installateur
OutputBaseFilename=MiseAJour_AssistantLocal_{vers}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={{#MonNom}}
UninstallDisplayIcon={{app}}\\{{#MonExe}}

[Languages]
Name: "francais"; MessagesFile: "compiler:Languages\\French.isl"
"""


def bloc_fichiers(a_livrer: list[str]) -> str:
    """Une ligne par fichier, avec son sous-dossier d'arrivee.

    ignoreversion est indispensable : sans lui, Inno compare les numeros de
    version des DLL et refuse d'ecraser un fichier dont la version n'a pas
    change alors que son contenu, lui, a change. C'est exactement le cas d'une
    bibliotheque recompilee sans changement de version.
    """
    lignes = ["", "[Files]"]
    for relatif in a_livrer:
        chemin = Path(relatif)
        source = "dist\\AssistantLocal\\" + str(chemin).replace("/", "\\")
        parent = str(chemin.parent).replace("/", "\\")
        destination = "{app}" if parent == "." else "{app}\\" + parent
        lignes.append(f'Source: "{source}"; DestDir: "{destination}"; '
                      f"Flags: ignoreversion")
    return "\n".join(lignes) + "\n"


def bloc_suppressions(supprimes: list[str]) -> str:
    """Retire ce qui a quitte le bundle.

    Un module supprime mais laisse sur place reste importable : Python le
    trouverait et chargerait du code de l'ancienne version. Une mise a jour
    qui n'efface rien finit par livrer un melange de deux versions.
    """
    if not supprimes:
        return "\n; Aucun fichier retire du bundle dans cette version.\n"
    lignes = ["", "[InstallDelete]"]
    for relatif in supprimes:
        chemin = str(Path(relatif)).replace("/", "\\")
        lignes.append(f'Type: files; Name: "{{app}}\\{chemin}"')
    return "\n".join(lignes) + "\n"


RUN = """
[Run]
Filename: "{app}\\{#MonExe}"; \\
    Description: "Ouvrir l'assistant"; \\
    Flags: postinstall nowait skipifsilent
"""


CODE = r"""
[Code]
const
  { L'identifiant est ecrit en toutes lettres, et non lu par
    SetupSetting("AppId") : cette fonction rend la valeur TELLE QU'ELLE EST
    ECRITE dans [Setup], accolade doublee comprise. La cle cherchee aurait
    porte une accolade de trop, RegQueryStringValue n'aurait jamais rien
    trouve, et la mise a jour aurait refuse de s'installer sur une machine ou
    l'application etait pourtant bien presente.

    Dans une chaine Pascal, les accolades ne sont pas des commentaires : la
    valeur ci-dessous est litterale. }
  CleDesinstall =
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{@APP_ID@}_is1';

function VersionInstallee(var Version: String): Boolean;
begin
  { L'installateur complet tourne sans elevation et ecrit donc sous HKCU.
    On regarde quand meme HKLM : une installation faite en administrateur,
    ou heritee d'une machine partagee, s'y trouverait. }
  Result := RegQueryStringValue(HKCU, CleDesinstall, 'DisplayVersion', Version)
         or RegQueryStringValue(HKLM, CleDesinstall, 'DisplayVersion', Version);
end;

function InitializeSetup(): Boolean;
var
  Presente: String;
  Installee, Apportee: Int64;
begin
  Result := True;

  { Sans cette garde, le correctif s'installerait sur une machine vierge et
    produirait une application amputee : quelques dizaines de fichiers, sans
    les 2,5 Go de bibliotheques. Elle ne demarrerait pas, et le message
    d'erreur ne dirait rien de la vraie cause. }
  if not VersionInstallee(Presente) then
  begin
    MsgBox('L''Assistant local n''est pas installe sur cette machine.'#13#10#13#10
         + 'Ceci est une mise a jour : elle ne contient que ce qui a change, '
         + 'pas l''application entiere. Installez d''abord la version '
         + 'complete (Installer_AssistantLocal.exe), puis relancez cette '
         + 'mise a jour.', mbCriticalError, MB_OK);
    Result := False;
    Exit;
  end;

  StrToVersion(Presente, Installee);
  StrToVersion('{#MaVersion}', Apportee);

  if ComparePackedVersion(Installee, Apportee) >= 0 then
  begin
    if MsgBox('La version installee est la ' + Presente + ', celle-ci apporte '
            + 'la {#MaVersion}.'#13#10#13#10
            + 'Il n''y a rien a mettre a jour. Continuer quand meme ?',
              mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
    Exit;
  end;

  { La version d'arrivee est calculee a partir d'une version de depart
    precise. Appliquee sur une autre, elle livre les fichiers qui different
    de CELLE-LA, et laisse en place ceux qui differaient de l'autre. }
  if CompareText(Presente, '{#VersionAttendue}') <> 0 then
  begin
    if MsgBox('Cette mise a jour est calculee depuis la version '
            + '{#VersionAttendue}, or la version installee est la '
            + Presente + '.'#13#10#13#10
            + 'L''appliquer peut laisser des fichiers d''une version '
            + 'intermediaire. Reinstaller la version complete est plus sur.'
            + #13#10#13#10 + 'Continuer quand meme ?',
              mbError, MB_YESNO) = IDNO then
      Result := False;
  end;
end;

procedure FermerApplication();
var
  CodeRetour: Integer;
begin
  { Les fichiers d'une application qui tourne sont verrouilles : la mise a
    jour s'arreterait au milieu, en ayant remplace une partie des fichiers. }
  Exec('taskkill.exe', '/IM AssistantLocal.exe /F', '', SW_HIDE,
       ewWaitUntilTerminated, CodeRetour);
  Exec('taskkill.exe', '/IM llama-server.exe /F', '', SW_HIDE,
       ewWaitUntilTerminated, CodeRetour);
  Exec('taskkill.exe', '/IM OpenRGB.exe /F', '', SW_HIDE,
       ewWaitUntilTerminated, CodeRetour);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  FermerApplication();
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    FermerApplication();
end;
"""


def script(depuis: str, vers: str, ecart: dict) -> str:
    """Le script Inno complet, assemble."""
    a_livrer = ecart["ajoutes"] + ecart["modifies"]
    return (entete(depuis, vers, ecart)
            + bloc_fichiers(a_livrer)
            + bloc_suppressions(ecart["supprimes"])
            + RUN
            + CODE.replace("@APP_ID@", APP_ID))


def construire(depuis: str) -> int:
    from assistant import __version__ as vers

    reference = manifeste.MANIFESTES / f"{depuis}.json"
    if not reference.exists():
        print(f"  ECHEC : aucun manifeste pour la version {depuis}.")
        print(f"  Attendu : {reference}")
        print("  Il se genere par outils/manifeste.py, AVANT de publier une")
        print("  version. Sans lui, impossible de savoir ce qui a change")
        print("  depuis ce que les gens ont reellement installe.")
        return 1

    if vers == depuis:
        print(f"  ECHEC : la version du code est toujours la {vers}.")
        print("  Une mise a jour va d'une version a une autre : incremente")
        print("  __version__ dans assistant/__init__.py ET MaVersion dans")
        print("  installateur.iss, puis reconstruis dist/.")
        return 1

    print(f"  Empreinte du dossier livre ({vers}) ...")
    actuel = manifeste.construire(version=vers)
    ecart = manifeste.differences(manifeste.lire(reference), actuel)
    print(f"  {manifeste.resume(ecart)}")

    if not ecart["ajoutes"] and not ecart["modifies"] \
            and not ecart["supprimes"]:
        print(f"  ECHEC : rien n'a change depuis la version {depuis}.")
        print("  Le dossier dist/ n'a peut-etre pas ete reconstruit.")
        return 1

    ISS.write_text(script(depuis, vers, ecart), encoding="utf-8")
    print(f"  Script genere : {ISS}")

    if not ISCC.exists():
        print(f"  Inno Setup introuvable : {ISCC}")
        print("  Le script est pret, il reste a le compiler.")
        return 1

    print("  Compilation ...")
    resultat = subprocess.run(
        [str(ISCC), str(ISS)], capture_output=True, text=True,
        encoding="utf-8", errors="replace", cwd=str(RACINE))
    if resultat.returncode != 0:
        print("  ECHEC de la compilation :")
        for ligne in (resultat.stdout + resultat.stderr).splitlines()[-15:]:
            print("   ", ligne)
        return 1

    paquet = SORTIE / f"MiseAJour_AssistantLocal_{vers}.exe"
    if not paquet.exists():
        print("  ECHEC : aucun paquet produit.")
        return 1

    poids = paquet.stat().st_size / 1048576
    print(f"  Paquet : {paquet}")
    complet = SORTIE / "Installer_AssistantLocal.exe"
    if complet.exists():
        entier = complet.stat().st_size / 1048576
        print(f"  {poids:.1f} Mo, contre {entier:.0f} Mo pour l'installateur "
              f"complet ({100 * poids / entier:.1f} %)")
    else:
        print(f"  {poids:.1f} Mo")

    # Le manifeste de la nouvelle version devient la reference de la suivante.
    print(f"  Manifeste de la nouvelle version : {manifeste.ecrire(actuel)}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        disponibles = (sorted(p.stem for p in manifeste.MANIFESTES.glob("*.json"))
                       if manifeste.MANIFESTES.is_dir() else [])
        print(f"  Manifestes disponibles : {', '.join(disponibles) or 'aucun'}")
        return 2
    return construire(argv[1])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
