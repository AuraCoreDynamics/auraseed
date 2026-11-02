@echo off
setlocal enabledelayedexpansion

set "FOUND_PYTHON="

:: 1. Attempt to find valid python in PATH (skip 0-byte stubs like WindowsApps)
for %%X in (python.exe) do (
    if exist "%%~$PATH:X" (
        for %%F in ("%%~$PATH:X") do (
            if %%~zF gtr 0 (
                "%%~$PATH:X" -c "import sys" >nul 2>&1
                if !errorlevel! equ 0 (
                    set "FOUND_PYTHON=%%~$PATH:X"
                    goto :RunAuraSeed
                )
            )
        )
    )
)

:: 2. Fallback standard locations
set FALLBACK_PATHS="%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" "%PROGRAMFILES%\Python312\python.exe" "%PROGRAMFILES%\Python311\python.exe" "%PROGRAMFILES%\Python310\python.exe"

for %%P in (%FALLBACK_PATHS%) do (
    if exist %%P (
        set "FOUND_PYTHON=%%~P"
        goto :RunAuraSeed
    )
)

:: 3. Check for previous bootstrapped Python in repo target or fallback
set "REPO_BOOTSTRAPPED=%~dp0.bootstrapped_python\python.exe"
if exist "%REPO_BOOTSTRAPPED%" (
    set "FOUND_PYTHON=%REPO_BOOTSTRAPPED%"
    goto :RunAuraSeed
)
set "USER_BOOTSTRAPPED=%LOCALAPPDATA%\AuraSeed\base_python\python.exe"
if exist "%USER_BOOTSTRAPPED%" (
    set "FOUND_PYTHON=%USER_BOOTSTRAPPED%"
    goto :RunAuraSeed
)

:: 4. If not found, delegate to auraseed.ps1 for zero-privilege download and bootstrapping
if exist "%~dp0auraseed.ps1" (
    echo [AuraSeed Bootstrapper] Invoking PowerShell bootstrapper for automated setup...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0auraseed.ps1" %*
    exit /b !errorlevel!
)

echo [AuraSeed Bootstrapper] Error: Could not locate a base Python executable to bootstrap discovery.
exit /b 1

:RunAuraSeed
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
:: Execute the auraseed module
"%FOUND_PYTHON%" -m auraseed %*
exit /b %ERRORLEVEL%
