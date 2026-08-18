[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:USERPROFILE "Biodynamic_Calendar")
)

$ErrorActionPreference = "Stop"

$SourceDir = Split-Path -Parent $PSScriptRoot
$AppDir = $InstallDir
$VenvDir = Join-Path $AppDir ".venv"
$InstallLog = Join-Path $AppDir "install.log"
$script:TranscriptStarted = $false

if ([string]::IsNullOrWhiteSpace($AppDir) -or
    [System.IO.Path]::GetFullPath($AppDir) -eq [System.IO.Path]::GetPathRoot($AppDir) -or
    [System.IO.Path]::GetFullPath($AppDir) -eq [System.IO.Path]::GetFullPath($env:USERPROFILE)) {
    throw "InstallDir must name a dedicated application directory."
}

foreach ($Directory in @("src", "static", "templates", "scripts")) {
    New-Item -ItemType Directory -Path (Join-Path $AppDir $Directory) -Force | Out-Null
}
if ([System.IO.Path]::GetFullPath($SourceDir) -ne [System.IO.Path]::GetFullPath($AppDir)) {
    foreach ($File in @("Biodynamic_Calendar.py", "pyproject.toml", "README.md", "LICENSE", "run_bd_calendar_gui.ps1", "run_bd_calendar_server.ps1", "run_bd_calendar_gui.cmd", "run_bd_calendar_server.cmd", "run_bd_calendar_gui.sh", "run_bd_calendar_server.sh")) {
        Copy-Item (Join-Path $SourceDir $File) (Join-Path $AppDir $File) -Force
    }
    foreach ($Directory in @("src", "static", "templates", "scripts")) {
        Copy-Item (Join-Path $SourceDir "$Directory\*") (Join-Path $AppDir $Directory) -Recurse -Force
    }
}

if (Test-Path $InstallLog) {
    Clear-Content -Path $InstallLog
} else {
    New-Item -ItemType File -Path $InstallLog -Force | Out-Null
}

function Write-LogLine {
    param([string]$Message = "")

    Write-Host $Message
    Add-Content -Path $InstallLog -Value $Message
}

function Write-Step {
    param([string]$Message)

    Write-Host ""
    Write-Host ("==> [{0}] {1}" -f (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ"), $Message)
}

function Get-FirstOutputLine {
    param(
        [string]$Command,
        [string[]]$Arguments = @()
    )

    try {
        $output = & $Command @Arguments 2>&1
        foreach ($line in $output) {
            $text = "$line".Trim()
            if ($text.Length -gt 0) {
                return $text
            }
        }
        return "available at $((Get-Command $Command).Source)"
    } catch {
        return "version check failed: $($_.Exception.Message)"
    }
}

function Write-ToolVersion {
    param(
        [string]$Label,
        [string]$Command,
        [string[]]$Arguments = @()
    )

    if (Get-Command $Command -ErrorAction SilentlyContinue) {
        Write-LogLine "$($Label): $(Get-FirstOutputLine -Command $Command -Arguments $Arguments)"
    } else {
        Write-LogLine "$($Label): not found"
    }
}

function Get-CimValue {
    param(
        [string]$ClassName,
        [string]$PropertyName
    )

    try {
        $instance = Get-CimInstance -ClassName $ClassName -ErrorAction Stop | Select-Object -First 1
        if ($null -ne $instance -and $null -ne $instance.$PropertyName) {
            return $instance.$PropertyName
        }
    } catch {
        return $null
    }
    return $null
}

function Format-ByteCount {
    param([Nullable[UInt64]]$Bytes)

    if ($null -eq $Bytes -or $Bytes -eq 0) {
        return "unknown"
    }
    return ("{0:N1} GiB ({1} bytes)" -f ($Bytes / 1GB), $Bytes)
}

function Get-FreeDiskSummary {
    try {
        $root = [System.IO.Path]::GetPathRoot($AppDir)
        $driveName = $root.TrimEnd("\").TrimEnd(":")
        $drive = Get-PSDrive -Name $driveName -ErrorAction Stop
        return ("{0:N1} GiB free on {1}" -f ($drive.Free / 1GB), $root)
    } catch {
        return "unknown"
    }
}

function Get-GitOutput {
    param([string[]]$Arguments)

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        return $null
    }

    try {
        $output = & git @Arguments 2>$null
        if ($LASTEXITCODE -eq 0) {
            return $output
        }
    } catch {
        return $null
    }
    return $null
}

function Write-GitContext {
    $insideWorktree = Get-GitOutput -Arguments @("-C", $AppDir, "rev-parse", "--is-inside-work-tree")
    if ($insideWorktree -ne "true") {
        Write-LogLine "Source repo: not a git worktree"
        Write-LogLine "Branch: unknown"
        Write-LogLine "Revision: unknown"
        Write-LogLine "Worktree state: unknown"
        return
    }

    $branch = Get-GitOutput -Arguments @("-C", $AppDir, "branch", "--show-current")
    $revision = Get-GitOutput -Arguments @("-C", $AppDir, "rev-parse", "--short", "HEAD")
    $status = Get-GitOutput -Arguments @("-C", $AppDir, "status", "--short")

    if (-not $branch) {
        $branch = "detached"
    }
    if (-not $revision) {
        $revision = "unknown"
    }

    Write-LogLine "Branch: $branch"
    Write-LogLine "Revision: $revision"
    if ($status) {
        Write-LogLine "Worktree state:"
        foreach ($line in $status) {
            Write-LogLine "$line"
        }
    } else {
        Write-LogLine "Worktree state: clean"
    }
}

function Write-InstallHeader {
    $sourceRepo = Get-GitOutput -Arguments @("-C", $AppDir, "config", "--get", "remote.origin.url")
    if (-not $sourceRepo) {
        $sourceRepo = $AppDir
    }

    $osCaption = Get-CimValue -ClassName "Win32_OperatingSystem" -PropertyName "Caption"
    $osVersion = Get-CimValue -ClassName "Win32_OperatingSystem" -PropertyName "Version"
    $model = Get-CimValue -ClassName "Win32_ComputerSystem" -PropertyName "Model"
    $memory = Get-CimValue -ClassName "Win32_ComputerSystem" -PropertyName "TotalPhysicalMemory"
    $cpu = Get-CimValue -ClassName "Win32_Processor" -PropertyName "Name"
    if (-not $osCaption) {
        $osCaption = [System.Runtime.InteropServices.RuntimeInformation]::OSDescription
    }
    if (-not $osVersion) {
        $osVersion = [System.Environment]::OSVersion.VersionString
    }
    if (-not $model) {
        $model = "unknown"
    }
    if (-not $cpu) {
        $cpu = "unknown"
    }

    Write-LogLine "BD Calendar install log"
    Write-LogLine "Generated: $((Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ"))"
    Write-LogLine "Install log: $InstallLog"
    Write-LogLine ""
    Write-LogLine "System context"
    Write-LogLine "Hostname: $env:COMPUTERNAME"
    Write-LogLine "User: $env:USERNAME"
    Write-LogLine "Working dir: $((Get-Location).Path)"
    Write-LogLine "OS name/version: $osCaption $osVersion"
    Write-LogLine "Kernel: $([System.Environment]::OSVersion.VersionString)"
    Write-LogLine "Platform/arch: $([System.Runtime.InteropServices.RuntimeInformation]::OSDescription)/$([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture)"
    Write-LogLine "Hardware model: $model"
    Write-LogLine "CPU: $cpu"
    Write-LogLine "Memory: $(Format-ByteCount -Bytes $memory)"
    Write-LogLine "Free disk space: $(Get-FreeDiskSummary)"
    Write-LogLine ""
    Write-LogLine "Installer context"
    Write-LogLine "Source repo: $sourceRepo"
    Write-LogLine "Target PROJECT_DIR: $AppDir"
    Write-LogLine "Venv: $VenvDir"
    Write-LogLine "Requirements: pyproject.toml project dependencies plus .[dev]"
    Write-LogLine "Selected options: none"
    Write-LogLine ""
    Write-LogLine "Git branch/revision/worktree state"
    Write-GitContext
    Write-LogLine ""
    Write-LogLine "Key tool versions"
    Write-ToolVersion -Label "Python" -Command "python" -Arguments @("--version")
    Write-ToolVersion -Label "pip" -Command "python" -Arguments @("-m", "pip", "--version")
    Write-ToolVersion -Label "uv" -Command "uv" -Arguments @("--version")
    Write-ToolVersion -Label "git" -Command "git" -Arguments @("--version")
    Write-ToolVersion -Label "rsync" -Command "rsync" -Arguments @("--version")
    Write-ToolVersion -Label "apt" -Command "apt" -Arguments @("--version")
    Write-ToolVersion -Label "brew" -Command "brew" -Arguments @("--version")
    Write-ToolVersion -Label "systemctl" -Command "systemctl" -Arguments @("--version")
    Write-ToolVersion -Label "mosquitto" -Command "mosquitto" -Arguments @("-h")
}

function Invoke-NativeStep {
    param(
        [string]$Description,
        [string]$FilePath,
        [string[]]$Arguments
    )

    Write-Step $Description
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

Write-InstallHeader
Start-Transcript -Path $InstallLog -Append -Force | Out-Null
$script:TranscriptStarted = $true

try {
    Write-Step "Changing to project directory: $AppDir"
    Set-Location $AppDir

    Invoke-NativeStep -Description "Creating virtual environment: $VenvDir" -FilePath "python" -Arguments @("-m", "venv", $VenvDir)
    Write-Step "Activating virtual environment: $VenvDir"
    . (Join-Path $VenvDir "Scripts\Activate.ps1")
    Invoke-NativeStep -Description "Upgrading pip, setuptools, and wheel" -FilePath "python" -Arguments @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel")
    Invoke-NativeStep -Description "Installing project dependencies into $VenvDir" -FilePath "python" -Arguments @("-m", "pip", "install", "-e", ".[dev]")
    Invoke-NativeStep -Description "Verifying pywebview desktop runtime" -FilePath "python" -Arguments @("-c", "import webview; from biodynamic_calendar_app.desktop import main")

    Write-Host @"
Ready.

Start the Biodynamic Calendar desktop app:
  $AppDir\run_bd_calendar_gui.cmd

Start only the LAN server:
  $AppDir\run_bd_calendar_server.cmd

Browse on this PC:
  http://127.0.0.1:8765

Browse from another device on this network:
  open http://<this-PC-IP>:8765
  find this PC's IP with: ipconfig
"@
} catch {
    Write-Step "Install failed: $($_.Exception.Message)"
    throw
} finally {
    if ($script:TranscriptStarted) {
        Stop-Transcript | Out-Null
    }
}
