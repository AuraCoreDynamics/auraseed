$ErrorActionPreference = "Stop"

$FoundPython = $null

# 1. Try PATH
$PythonInPath = Get-Command "python.exe" -ErrorAction SilentlyContinue
if ($PythonInPath) {
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
                    if (Test-Path $ExePath) {
                        $FoundPython = $ExePath
                        break
                    }
                }
            }
        }
        if ($FoundPython) { break }
    }
}

if (-not $FoundPython) {
    Write-Error "[AuraSeed Bootstrapper] Error: Could not locate a base Python executable to bootstrap discovery."
    exit 1
}

# Execute the auraseed module
& $FoundPython -m auraseed $args
exit $LASTEXITCODE
