# Releve complet de la machine, en UN seul appel.
#
# Chaque interrogation WMI coute environ une demi-seconde. En faire quinze
# separement prendrait dix secondes au demarrage ; regroupees ici, elles
# tiennent en deux. Tout est en -ErrorAction SilentlyContinue : une classe
# WMI absente sur une machine ne doit jamais faire echouer le releve entier.

# Le resultat part dans un fichier UTF-8, pas sur la sortie standard.
# L'encodage d'un tuyau est fixe au lancement du processus : le regler depuis
# l'interieur du script arrive trop tard, et les messages du journal Windows
# (en francais) revenaient avec des accents detruits.
#
# param() doit rester la premiere instruction executable du script.
param([Parameter(Mandatory = $true)][string]$Destination)

$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'

function Safe($block) { try { & $block } catch { $null } }

$os    = Safe { Get-CimInstance Win32_OperatingSystem }
$cs    = Safe { Get-CimInstance Win32_ComputerSystem }
$cpu   = Safe { Get-CimInstance Win32_Processor | Select-Object -First 1 }
$bios  = Safe { Get-CimInstance Win32_BIOS }
$board = Safe { Get-CimInstance Win32_BaseBoard }

$ram = Safe {
  Get-CimInstance Win32_PhysicalMemory | ForEach-Object {
    [pscustomobject]@{
      slot         = $_.DeviceLocator
      capacity_gb  = [math]::Round($_.Capacity / 1GB, 1)
      speed_mhz    = $_.ConfiguredClockSpeed
      max_mhz      = $_.Speed
      manufacturer = $_.Manufacturer
      part         = $_.PartNumber.Trim()
    }
  }
}

$gpu = Safe {
  Get-CimInstance Win32_VideoController | ForEach-Object {
    [pscustomobject]@{
      name          = $_.Name
      driver        = $_.DriverVersion
      driver_date   = if ($_.DriverDate) { $_.DriverDate.ToString('yyyy-MM-dd') } else { $null }
      status        = $_.Status
    }
  }
}

# HealthStatus et MediaType ne viennent que du namespace Storage. C'est la
# seule source fiable pour savoir si un disque est en train de mourir.
$physical = Safe {
  Get-PhysicalDisk | ForEach-Object {
    [pscustomobject]@{
      # DeviceId est le numero que Windows donne au disque. L'ordre
      # d'enumeration ne le suit PAS : s'en servir pour rattacher les
      # partitions place les volumes sur le mauvais disque.
      numero       = [int]$_.DeviceId
      name         = $_.FriendlyName
      media        = $_.MediaType
      bus          = $_.BusType
      size_gb      = [math]::Round($_.Size / 1GB)
      health       = $_.HealthStatus
      operational  = ($_.OperationalStatus -join ', ')
      wear_percent = $_.Wear
      temperature  = $_.Temperature
    }
  }
}

$volumes = Safe {
  Get-Volume | Where-Object { $_.DriveLetter } | ForEach-Object {
    [pscustomobject]@{
      letter      = [string]$_.DriveLetter
      label       = $_.FileSystemLabel
      fs          = $_.FileSystem
      size_gb     = [math]::Round($_.Size / 1GB, 1)
      free_gb     = [math]::Round($_.SizeRemaining / 1GB, 1)
      health      = $_.HealthStatus
      drive_type  = $_.DriveType
    }
  }
}

# Peripheriques en erreur : ConfigManagerErrorCode non nul = pilote absent,
# en conflit, ou materiel qui ne demarre pas.
$bad_devices = Safe {
  Get-CimInstance Win32_PnPEntity |
    Where-Object { $_.ConfigManagerErrorCode -ne 0 -and $_.ConfigManagerErrorCode -ne $null } |
    Select-Object -First 20 | ForEach-Object {
      [pscustomobject]@{
        name  = $_.Name
        code  = $_.ConfigManagerErrorCode
        class = $_.PNPClass
      }
    }
}

# Erreurs critiques du journal systeme sur 7 jours, regroupees par source.
$events = Safe {
  $since = (Get-Date).AddDays(-7)
  Get-WinEvent -FilterHashtable @{LogName='System'; Level=1,2; StartTime=$since} -MaxEvents 400 |
    Group-Object ProviderName |
    Sort-Object Count -Descending |
    Select-Object -First 8 | ForEach-Object {
      [pscustomobject]@{
        source  = $_.Name
        count   = $_.Count
        last    = ($_.Group | Select-Object -First 1).TimeCreated.ToString('yyyy-MM-dd HH:mm')
        message = (($_.Group | Select-Object -First 1).Message -split "`n")[0]
      }
    }
}

# Un redemarrage en attente explique quantite de comportements bizarres.
$reboot_pending = Safe {
  $keys = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending',
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired',
    'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\PendingFileRenameOperations'
  )
  [bool]($keys | Where-Object { Test-Path $_ })
}

$defender = Safe {
  $s = Get-MpComputerStatus
  [pscustomobject]@{
    realtime      = $s.RealTimeProtectionEnabled
    antivirus     = $s.AntivirusEnabled
    signature_age = $s.AntivirusSignatureAge
  }
}

# --- Details supplementaires ------------------------------------------------
# Ce qu'on veut voir quand on demande "ma configuration" et qu'on attend une
# vraie fiche technique, pas trois lignes.

# Emplacements memoire : savoir qu'il reste deux slots libres change la
# reponse a "est-ce que je peux ajouter de la RAM ?".
$memory_slots = Safe {
  $tableau = Get-CimInstance Win32_PhysicalMemoryArray | Select-Object -First 1
  [pscustomobject]@{
    total    = $tableau.MemoryDevices
    utilises = @(Get-CimInstance Win32_PhysicalMemory).Count
    max_gb   = [math]::Round($tableau.MaxCapacityEx / 1MB)
  }
}

$network = Safe {
  Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | ForEach-Object {
    $config = Get-NetIPAddress -InterfaceIndex $_.ifIndex -AddressFamily IPv4 `
              -ErrorAction SilentlyContinue | Select-Object -First 1
    [pscustomobject]@{
      nom      = $_.Name
      type     = $_.InterfaceDescription
      vitesse  = $_.LinkSpeed
      mac      = $_.MacAddress
      ip       = if ($config) { $config.IPAddress } else { $null }
    }
  }
}

$monitors = Safe {
  # Le nom commercial vit dans WmiMonitorID, la taille dans
  # WmiMonitorBasicDisplayParams. On construit une table des noms puis on la
  # joint : filtrer WmiMonitorID par InstanceName echoue, ce nom contient des
  # antislashs que -Filter interprete.
  $noms = @{}
  foreach ($id in (Get-CimInstance -Namespace root\wmi WmiMonitorID -ErrorAction SilentlyContinue)) {
    $texte = ''
    if ($id.UserFriendlyName) {
      $texte = (($id.UserFriendlyName | Where-Object { $_ -gt 0 }) |
                ForEach-Object { [char]$_ }) -join ''
    }
    $fabricant = ''
    if ($id.ManufacturerName) {
      $fabricant = (($id.ManufacturerName | Where-Object { $_ -gt 0 }) |
                    ForEach-Object { [char]$_ }) -join ''
    }
    $noms[$id.InstanceName] = (("$fabricant $texte").Trim())
  }

  Get-CimInstance -Namespace root\wmi WmiMonitorBasicDisplayParams |
    ForEach-Object {
      $nom = $noms[$_.InstanceName]
      if (-not $nom) { $nom = 'Ecran' }
      [pscustomobject]@{
        nom    = $nom
        pouces = [math]::Round([math]::Sqrt(
                   [math]::Pow($_.MaxHorizontalImageSize, 2) +
                   [math]::Pow($_.MaxVerticalImageSize, 2)) / 2.54, 1)
      }
    }
}

$resolutions = Safe {
  Get-CimInstance Win32_VideoController |
    Where-Object { $_.CurrentHorizontalResolution } | ForEach-Object {
      [pscustomobject]@{
        carte      = $_.Name
        resolution = "$($_.CurrentHorizontalResolution)x$($_.CurrentVerticalResolution)"
        hz         = $_.CurrentRefreshRate
      }
    }
}

# Les partitions de chaque disque physique : sans ce lien, on ne sait pas
# quel volume vit sur quel disque.
$disk_layout = Safe {
  Get-Partition | Where-Object { $_.DriveLetter } | ForEach-Object {
    [pscustomobject]@{
      lettre  = [string]$_.DriveLetter
      disque  = $_.DiskNumber
      taille  = [math]::Round($_.Size / 1GB, 1)
      type    = [string]$_.Type
    }
  }
}

$activation = Safe {
  $lic = Get-CimInstance SoftwareLicensingProduct `
         -Filter "ApplicationID='55c92734-d682-4d71-983e-d6ec3f16059f' AND PartialProductKey IS NOT NULL" |
         Select-Object -First 1
  if ($lic) {
    switch ($lic.LicenseStatus) {
      1 { 'Active' } 2 { 'Periode de grace' } 3 { 'Grace supplementaire' }
      4 { 'Grace hors tolerance' } 5 { 'Non conforme' } 6 { 'Grace etendue' }
      default { 'Inconnu' }
    }
  } else { 'Inconnu' }
}

$battery = Safe {
  Get-CimInstance Win32_Battery | Select-Object -First 1 | ForEach-Object {
    [pscustomobject]@{
      charge = $_.EstimatedChargeRemaining
      etat   = $_.BatteryStatus
    }
  }
}

$uptime_hours = Safe {
  [math]::Round(((Get-Date) - $os.LastBootUpTime).TotalHours, 1)
}

$result = [pscustomobject]@{
  os = [pscustomobject]@{
    caption      = $os.Caption
    version      = $os.Version
    build        = $os.BuildNumber
    architecture = $os.OSArchitecture
    installed    = if ($os.InstallDate) { $os.InstallDate.ToString('yyyy-MM-dd') } else { $null }
    last_boot    = if ($os.LastBootUpTime) { $os.LastBootUpTime.ToString('yyyy-MM-dd HH:mm') } else { $null }
    locale       = $os.Locale
  }
  machine = [pscustomobject]@{
    manufacturer = $cs.Manufacturer
    model        = $cs.Model
    ram_gb       = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
    board        = "$($board.Manufacturer) $($board.Product)"
    bios         = "$($bios.SMBIOSBIOSVersion)"
    bios_date    = if ($bios.ReleaseDate) { $bios.ReleaseDate.ToString('yyyy-MM-dd') } else { $null }
  }
  cpu = [pscustomobject]@{
    name         = $cpu.Name
    cores        = $cpu.NumberOfCores
    threads      = $cpu.NumberOfLogicalProcessors
    max_mhz      = $cpu.MaxClockSpeed
    current_mhz  = $cpu.CurrentClockSpeed
  }
  ram            = @($ram)
  gpu            = @($gpu)
  physical_disks = @($physical)
  volumes        = @($volumes)
  bad_devices    = @($bad_devices)
  events         = @($events)
  reboot_pending = $reboot_pending
  defender       = $defender
  memory_slots   = $memory_slots
  network        = @($network)
  monitors       = @($monitors)
  resolutions    = @($resolutions)
  disk_layout    = @($disk_layout)
  activation     = $activation
  battery        = $battery
  uptime_hours   = $uptime_hours
}

$json = $result | ConvertTo-Json -Depth 5 -Compress
[System.IO.File]::WriteAllText($Destination, $json, [System.Text.UTF8Encoding]::new($false))
