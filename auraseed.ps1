$ErrorActionPreference = "Stop"

$FoundPython = $null

function Test-ValidPython($ExePath) {
    if (-not $ExePath -or -not (Test-Path $ExePath)) { return $false }
    try {
        $item = Get-Item $ExePath -ErrorAction SilentlyContinue
        # Filter out 0-byte WindowsApps store redirection stubs
        if ($item.Length -eq 0) { return $false }
        # Check execution
        $res = & $ExePath -c "import sys; print(sys.version_info[0])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $res -match "^\d+") {
            return $true
        }
    } catch {}
    return $false
}

# 1. Try PATH
$PythonInPath = Get-Command "python.exe" -ErrorAction SilentlyContinue
if ($PythonInPath -and (Test-ValidPython $PythonInPath.Source)) {
    $FoundPython = $PythonInPath.Source
}

# 2. Try Registry PEP 514
if (-not $FoundPython) {
    $RegistryPaths = @(
        "HKCU:\Software\Python\PythonCore",
        "HKLM:\Software\Python\PythonCore"
    )
    
    foreach ($RegPath in $RegistryPaths) {
        if (Test-Path $RegPath) {
            $Versions = Get-ChildItem -Path $RegPath -ErrorAction SilentlyContinue
            foreach ($Version in $Versions) {
                $InstallPathKey = Join-Path -Path $Version.PSPath -ChildPath "InstallPath"
                if (Test-Path $InstallPathKey) {
                    $InstallPath = (Get-ItemProperty -Path $InstallPathKey).'(default)'
                    $ExePath = Join-Path -Path $InstallPath -ChildPath "python.exe"
                    if (Test-ValidPython $ExePath) {
                        $FoundPython = $ExePath
                        break
                    }
                }
            }
        }
        if ($FoundPython) { break }
    }
}

# 3. Check for previous bootstrapped Python in repo or fallback directories
$ConfigFile = if ($env:AURASEED_BOOTSTRAP_CONFIG) { $env:AURASEED_BOOTSTRAP_CONFIG } else { Join-Path $PSScriptRoot "bootstrap.json" }

if (-not $FoundPython -and (Test-Path $ConfigFile)) {
    try {
        $Config = Get-Content $ConfigFile -Raw | ConvertFrom-Json
        $TargetDirRel = if ($Config.target_dir) { $Config.target_dir } else { ".bootstrapped_python" }
        $RepoTargetDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot $TargetDirRel))
        
        $FallbackTargetDir = $null
        if ($Config.fallback_target_dirs -and $Config.fallback_target_dirs.windows) {
            $FallbackTargetDir = [System.Environment]::ExpandEnvironmentVariables($Config.fallback_target_dirs.windows)
        }

        # Check Repo dir first
        $CheckRepoExe = Join-Path $RepoTargetDir "python.exe"
        if (Test-ValidPython $CheckRepoExe) {
            $FoundPython = $CheckRepoExe
        } elseif ($FallbackTargetDir) {
            $CheckFallbackExe = Join-Path $FallbackTargetDir "python.exe"
            if (Test-ValidPython $CheckFallbackExe) {
                $FoundPython = $CheckFallbackExe
            }
        }
    } catch {}
}

# 4. If still not found, download and install per bootstrap.json
if (-not $FoundPython -and (Test-Path $ConfigFile)) {
    Write-Host "[AuraSeed Bootstrapper] No base Python installation found on host."
    Write-Host "[AuraSeed Bootstrapper] Initiating zero-privilege bootstrap from $ConfigFile..."
    
    $Config = Get-Content $ConfigFile -Raw | ConvertFrom-Json
    $DistKey = if ($Config.default_distribution) { $Config.default_distribution } else { "miniconda" }
    $PlatformKey = "windows-x86_64"
    
    $DistConfig = $Config.distributions.$DistKey.$PlatformKey
    if (-not $DistConfig) {
        Write-Error "[AuraSeed Bootstrapper] Distribution configuration not found for '$DistKey' on '$PlatformKey'."
        exit 1
    }

    $Url = $DistConfig.url
    $PythonSubpath = if ($DistConfig.python_subpath) { $DistConfig.python_subpath } else { "python.exe" }
    
    # Try repository directory first, test write permission
    $TargetDirRel = if ($Config.target_dir) { $Config.target_dir } else { ".bootstrapped_python" }
    $InstallDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot $TargetDirRel))
    
    $CanWriteRepo = $true
    try {
        if (-not (Test-Path $InstallDir)) {
            New-Item -ItemType Directory -Path $InstallDir -Force -ErrorAction Stop | Out-Null
        }
        $TestFile = Join-Path $InstallDir ".perm_check"
        [System.IO.File]::WriteAllText($TestFile, "test")
        Remove-Item $TestFile -Force -ErrorAction SilentlyContinue
    } catch {
        $CanWriteRepo = $false
    }

    if (-not $CanWriteRepo) {
        Write-Host "[AuraSeed Bootstrapper] Insufficient permissions to install at $InstallDir. Falling back to user directory."
        if ($Config.fallback_target_dirs -and $Config.fallback_target_dirs.windows) {
            $InstallDir = [System.Environment]::ExpandEnvironmentVariables($Config.fallback_target_dirs.windows)
        } else {
            $InstallDir = Join-Path $env:LOCALAPPDATA "AuraSeed\base_python"
        }
        New-Item -ItemType Directory -Path $InstallDir -Force -ErrorAction Stop | Out-Null
    }

    $TempInstaller = Join-Path ([System.IO.Path]::GetTempPath()) ("auraseed_installer_" + [System.IO.Path]::GetFileName($Url))
    Write-Host "[AuraSeed Bootstrapper] Downloading $DistKey from $Url..."
    
    if (Get-Command "curl.exe" -ErrorAction SilentlyContinue) {
        & curl.exe -fL -o $TempInstaller $Url
    } else {
        Invoke-WebRequest -Uri $Url -OutFile $TempInstaller -UseBasicParsing
    }

    if (-not (Test-Path $TempInstaller)) {
        Write-Error "[AuraSeed Bootstrapper] Download failed: Installer not found at $TempInstaller."
        exit 1
    }

    Write-Host "[AuraSeed Bootstrapper] Installing to $InstallDir (non-admin, silent)..."
    
    # Format arguments replacing {INSTALL_DIR}
    $ArgList = @()
    foreach ($arg in $DistConfig.silent_args) {
        $ArgList += $arg.Replace("{INSTALL_DIR}", $InstallDir)
    }

    $Process = Start-Process -FilePath $TempInstaller -ArgumentList $ArgList -Wait -PassThru -NoNewWindow
    Remove-Item $TempInstaller -Force -ErrorAction SilentlyContinue

    if ($Process.ExitCode -ne 0) {
        Write-Error "[AuraSeed Bootstrapper] Installation failed with exit code $($Process.ExitCode)."
        exit 1
    }

    $InstalledExe = Join-Path $InstallDir $PythonSubpath
    if (-not (Test-ValidPython $InstalledExe)) {
        Write-Error "[AuraSeed Bootstrapper] Bootstrapping completed but could not verify $InstalledExe."
        exit 1
    }

    $FoundPython = $InstalledExe
    Write-Host "[AuraSeed Bootstrapper] Successfully provisioned base Python at: $FoundPython"

    # Register in PEP 514 under HKCU\Software\Python\PythonCore\AuraSeedBootstrapped
    try {
        $RegBase = "HKCU:\Software\Python\PythonCore\AuraSeedBootstrapped"
        if (-not (Test-Path $RegBase)) {
            New-Item -Path $RegBase -Force | Out-Null
        }
        $InstallKey = Join-Path $RegBase "InstallPath"
        if (-not (Test-Path $InstallKey)) {
            New-Item -Path $InstallKey -Force | Out-Null
        }
        Set-ItemProperty -Path $InstallKey -Name "(default)" -Value $InstallDir
        Set-ItemProperty -Path $InstallKey -Name "ExecutablePath" -Value $FoundPython
        Write-Host "[AuraSeed Bootstrapper] Registered bootstrapped Python in HKCU PEP 514 registry."
    } catch {
        Write-Warning "[AuraSeed Bootstrapper] Could not write PEP 514 registry entry: $_"
    }

    # Register in central environments.json
    try {
        $AppDataDir = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $env:USERPROFILE ".auraseed" }
        $RegDir = Join-Path $AppDataDir "auraseed"
        if (-not (Test-Path $RegDir)) {
            New-Item -ItemType Directory -Path $RegDir -Force | Out-Null
        }
        $ManifestPath = Join-Path $RegDir "environments.json"
        $Manifest = @{
            version = "1.0"
            environments = @{}
        }
        if (Test-Path $ManifestPath) {
            try {
                $Manifest = Get-Content $ManifestPath -Raw | ConvertFrom-Json
            } catch {}
        }
        $Manifest.environments["base_bootstrapped"] = @{
            name = "base_bootstrapped"
            executable = $FoundPython
            install_dir = $InstallDir
            distribution = $DistKey
            bootstrapped = $true
        }
        $Manifest | ConvertTo-Json -Depth 5 | Set-Content $ManifestPath -Encoding UTF8
        Write-Host "[AuraSeed Bootstrapper] Registered bootstrapped Python in $ManifestPath."
    } catch {
        Write-Warning "[AuraSeed Bootstrapper] Could not write central environments.json: $_"
    }
}

if (-not $FoundPython) {
    Write-Error "[AuraSeed Bootstrapper] Error: Could not locate or bootstrap a base Python executable."
    exit 1
}

# Ensure the auraseed repository root is on PYTHONPATH
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$PSScriptRoot;$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = "$PSScriptRoot"
}

# Execute the auraseed module
& $FoundPython -m auraseed $args
exit $LASTEXITCODE
