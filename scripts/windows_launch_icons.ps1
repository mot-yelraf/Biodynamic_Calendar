# Shared by the installer and uninstaller; never launches the application.
function Get-CalendarShortcutDirectories {
    @(
        [Environment]::GetFolderPath("DesktopDirectory")
        (Join-Path ([Environment]::GetFolderPath("Programs")) "Biodynamic Calendar")
    )
}

function Update-CalendarLaunchIcons {
    param(
        [Parameter(Mandatory = $true)][string]$RuntimeDir,
        [switch]$Remove,
        [string[]]$ShortcutDirectories = (Get-CalendarShortcutDirectories)
    )

    $RuntimeDir = [IO.Path]::GetFullPath($RuntimeDir)
    $Launcher = Join-Path $RuntimeDir "run_bd_calendar_gui.ps1"
    $Target = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $Launcher + '"'
    $Description = "Launch Biodynamic Calendar desktop app"
    $Icon = Join-Path $RuntimeDir "static\bd-calendar-icon.ico"
    if (-not $Remove) {
        foreach ($Required in @($Launcher, $Icon)) {
            if (-not (Test-Path -LiteralPath $Required -PathType Leaf)) {
                throw "Launcher resource is missing: $Required"
            }
        }
    }
    $Shell = New-Object -ComObject WScript.Shell
    foreach ($Directory in $ShortcutDirectories) {
        $ShortcutPath = Join-Path $Directory "Biodynamic Calendar.lnk"
        $Exists = Test-Path -LiteralPath $ShortcutPath -PathType Leaf
        if ($Remove -and -not $Exists) { continue }
        $Shortcut = $Shell.CreateShortcut($ShortcutPath)
        if ($Remove) {
            if ($Shortcut.Description -eq $Description -and
                $Shortcut.TargetPath -eq $Target -and $Shortcut.Arguments -eq $Arguments) {
                Remove-Item -LiteralPath $ShortcutPath -Force
                Write-Host "Removed $ShortcutPath."
            }
            continue
        }
        if ($Exists -and $Shortcut.Description -ne $Description) {
            throw "Refusing to overwrite another shortcut: $ShortcutPath"
        }
        New-Item -ItemType Directory -Path $Directory -Force | Out-Null
        $Shortcut.TargetPath = $Target
        $Shortcut.Arguments = $Arguments
        $Shortcut.WorkingDirectory = $RuntimeDir
        $Shortcut.IconLocation = $Icon + ",0"
        $Shortcut.Description = $Description
        $Shortcut.WindowStyle = 7
        $Shortcut.Save()
        Write-Host "Click-to-launch icon: $ShortcutPath"
    }
}
