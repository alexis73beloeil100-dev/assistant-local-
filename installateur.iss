; Installateur de l'Assistant local.
;
; Produit un Setup.exe unique, distribuable, avec desinstallation propre.
; Se compile par :
;     "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installateur.iss
;
; Reconstruire dist/ AVANT (python reconstruire.py) : Inno empaquette ce
; qu'il trouve, sans verifier l'age. Un installateur compile sur un dist/
; perime s'obtient sans le moindre avertissement.
;
; Pour livrer un correctif sans faire retelecharger 1,15 Go, voir
; outils/paquet_maj.py : il ne transporte que ce qui a change.
;
; L'installation se fait dans le profil de l'utilisateur (pas Program Files) :
; l'application ecrit son journal et ses reglages a cote d'elle, ce que les
; droits de Program Files interdiraient sans elevation. Aucun droit
; administrateur n'est donc necessaire.

#define MonNom "Assistant local"
#define MonExe "AssistantLocal.exe"
#define MonEditeur "Assistant local"
; A tenir d'accord avec assistant/__init__.py : le test
; "test_les_deux_numeros_de_version_ne_divergent_pas" echoue sinon.
#define MaVersion "1.0.1"

[Setup]
AppId={{8F3C1A62-4E7D-4B21-9C0E-2A5D6B7E9F14}
AppName={#MonNom}
AppVersion={#MaVersion}
AppPublisher={#MonEditeur}
DefaultDirName={localappdata}\AssistantLocal
DefaultGroupName={#MonNom}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installateur
OutputBaseFilename=Installer_AssistantLocal
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 2,4 Go de contenu : sans cette marge, l'installation echoue en fin de course.
ExtraDiskSpaceRequired=0
UninstallDisplayName={#MonNom}
UninstallDisplayIcon={app}\{#MonExe}
; Fermer l'assistant s'il tourne pendant l'installation.
;
; C'est deja le defaut d'Inno Setup 6, et on l'ecrit quand meme : le
; comportement a ete constate en marche reelle le 22/08 -- une instance
; lancee depuis un AUTRE dossier a ete fermee par l'installation. Le
; Gestionnaire de redemarrage de Windows identifie les processus par leur
; module, pas par leur chemin, donc n'importe quel exemplaire de
; AssistantLocal.exe est concerne.
;
; C'est voulu : sans cela, une mise a jour ecraserait des fichiers en cours
; d'utilisation et echouerait en fin de course. Mais une personne qui lit ce
; fichier doit pouvoir l'apprendre ici plutot qu'en le decouvrant.
CloseApplications=yes
; Page d'explication avant l'installation : sans elle, la personne qui
; installe ne sait pas ce que fait le logiciel, ni pourquoi un second ecran
; s'ouvre a la fin pour telecharger des modeles.
; Page d'acceptation de la licence. Le texte dit ce qui est reellement
; distribue : le programme complet se transmet sous GPLv3, parce qu'il
; integre openrgb-python qui l'est. Annoncer MIT seul -- la licence du
; code ecrit pour ce projet -- aurait ete inexact pour l'assemblage.
LicenseFile=LICENCE-INSTALLATION.txt
InfoBeforeFile=installateur_infos.txt

[Languages]
Name: "francais"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "raccourcibureau"; Description: "Creer un raccourci sur le Bureau"; \
    GroupDescription: "Raccourcis :"
Name: "demarrage"; Description: "Lancer l'assistant au demarrage de Windows"; \
    GroupDescription: "Demarrage :"; Flags: unchecked

[Files]
Source: "dist\AssistantLocal\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MonNom}"; Filename: "{app}\{#MonExe}"
Name: "{group}\Composants et installation"; Filename: "{app}\{#MonExe}"; \
    Parameters: "--installer"
Name: "{group}\Desinstaller {#MonNom}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MonNom}"; Filename: "{app}\{#MonExe}"; \
    Tasks: raccourcibureau

[Registry]
; Demarrage avec la session, uniquement si la case est cochee. Sous HKCU,
; donc sans droits administrateur, et retire a la desinstallation.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "AssistantLocal"; \
    ValueData: """{app}\{#MonExe}"""; Flags: uninsdeletevalue; \
    Tasks: demarrage

[Run]
; A la fin de l'installation, on propose l'ecran des composants : le moteur
; d'IA et les modeles ne sont pas embarques (ils pesent plusieurs Go et
; dependent du materiel de la machine).
Filename: "{app}\{#MonExe}"; Parameters: "--installer"; \
    Description: "Choisir et telecharger les composants (moteur IA, voix)"; \
    Flags: postinstall skipifsilent
Filename: "{app}\{#MonExe}"; \
    Description: "Ouvrir l'assistant apres l'installation"; \
    Flags: postinstall nowait skipifsilent unchecked

[UninstallDelete]
; Fichiers crees par l'application dans son propre dossier : sans cela, le
; dossier resterait avec quelques orphelins apres la desinstallation.
;
; On n'efface QUE ce qui est jetable. Les reglages, le journal des actions et
; les notes vivent dans {userappdata}\AssistantLocal et sont volontairement
; CONSERVES : ils contiennent notamment la commande exacte des programmes
; desactives au demarrage. Les supprimer rendrait ces programmes
; irrecuperables autrement qu'en les reinstallant.
;
; L'ancien dossier {app}\data est encore nettoye : il ne contient plus que des
; copies rapatriees au premier lancement de la nouvelle version.
Type: filesandordirs; Name: "{app}\data"
Type: files; Name: "{app}\erreurs.log"

[Code]
procedure FermerApplication();
var
  CodeRetour: Integer;
begin
  { L'application peut tourner : ses fichiers seraient verrouilles et
    l'operation laisserait un dossier a moitie ecrit. On la ferme d'abord,
    ainsi que le moteur de calcul d'Ollama qui charge ses DLL. }
  Exec('taskkill.exe', '/IM AssistantLocal.exe /F', '', SW_HIDE,
       ewWaitUntilTerminated, CodeRetour);
  Exec('taskkill.exe', '/IM llama-server.exe /F', '', SW_HIDE,
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
