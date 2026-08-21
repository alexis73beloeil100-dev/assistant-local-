# Inventaire logiciel de la machine, en UN seul appel.
#
# Meme raison que pour probe.ps1 : chaque interrogation coute une demi-seconde
# ou plus, et les faire separement ferait attendre le demarrage. Tout est en
# -ErrorAction SilentlyContinue -- une classe absente ne doit jamais faire
# echouer l'inventaire entier.
#
# Ce qu'on NE collecte pas, volontairement : aucun contenu de fichier, aucune
# valeur de registre autre que les noms et editeurs de logiciels, aucun
# identifiant de session. L'inventaire dit ce qui est installe, pas ce que
# l'utilisateur en fait.

param([Parameter(Mandatory = $true)][string]$Destination)

$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'

function Safe($block) { try { & $block } catch { $null } }

# --- Logiciels installes -----------------------------------------------------
# On lit le registre plutot que Win32_Product : cette classe WMI declenche une
# reverification MSI de chaque paquet, ce qui prend des minutes et peut
# reparer des installations au passage.
$logiciels = Safe {
  $racines = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
  )
  Get-ItemProperty $racines |
    Where-Object { $_.DisplayName -and -not $_.SystemComponent } |
    Sort-Object DisplayName -Unique |
    ForEach-Object {
      [pscustomobject]@{
        nom       = $_.DisplayName
        version   = $_.DisplayVersion
        editeur   = $_.Publisher
        taille_mo = if ($_.EstimatedSize) { [math]::Round($_.EstimatedSize / 1024) } else { $null }
        installe  = $_.InstallDate
        dossier   = $_.InstallLocation
        # La commande que Windows lui-meme utilise pour desinstaller. C'est
        # la seule voie fiable pour les logiciels hors launcher : deviner un
        # chemin d'uninstaller casse a chaque mise a jour.
        desinstalle = $_.UninstallString
      }
    }
}

# --- Services ----------------------------------------------------------------
$services = Safe {
  Get-CimInstance Win32_Service |
    Select-Object Name, DisplayName, State, StartMode, PathName |
    ForEach-Object {
      [pscustomobject]@{
        nom      = $_.Name
        libelle  = $_.DisplayName
        etat     = $_.State
        demarre  = $_.StartMode
      }
    }
}

# --- Taches planifiees -------------------------------------------------------
# Seules celles que quelqu'un a ajoutees : le dossier \Microsoft\ contient des
# centaines de taches systeme sans interet, qui noieraient tout le reste.
$taches = Safe {
  Get-ScheduledTask |
    Where-Object { $_.TaskPath -notlike '\Microsoft\*' -and $_.State -ne 'Disabled' } |
    ForEach-Object {
      [pscustomobject]@{
        nom     = $_.TaskName
        chemin  = $_.TaskPath
        etat    = [string]$_.State
        auteur  = $_.Author
      }
    }
}

# --- Pilotes tiers -----------------------------------------------------------
# Les pilotes Microsoft sont ecartes : ce qui casse une machine, c'est presque
# toujours un pilote tiers vieux ou en double.
$pilotes = Safe {
  Get-CimInstance Win32_PnPSignedDriver |
    Where-Object { $_.DeviceName -and $_.Manufacturer -notlike '*Microsoft*' } |
    Select-Object -First 120 |
    ForEach-Object {
      [pscustomobject]@{
        appareil = $_.DeviceName
        editeur  = $_.Manufacturer
        version  = $_.DriverVersion
        date     = if ($_.DriverDate) { $_.DriverDate.ToString('yyyy-MM-dd') } else { $null }
      }
    }
}

# --- Fonctionnalites Windows et navigateurs ---------------------------------
$navigateurs = Safe {
  $cles = @(
    'HKLM:\SOFTWARE\Clients\StartMenuInternet\*'
  )
  Get-ItemProperty $cles | ForEach-Object {
    [pscustomobject]@{ nom = $_.'(default)' ; cle = $_.PSChildName }
  }
}

$resultat = [pscustomobject]@{
  logiciels   = @($logiciels)
  services    = @($services)
  taches      = @($taches)
  pilotes     = @($pilotes)
  navigateurs = @($navigateurs)
}

$json = $resultat | ConvertTo-Json -Depth 5 -Compress
[System.IO.File]::WriteAllText($Destination, $json, [System.Text.UTF8Encoding]::new($false))
