@echo off
setlocal

:: Attempt to find python in PATH
for %%X in (python.exe) do (set FOUND_PYTHON=%%~$PATH:X)

if defined FOUND_PYTHON (
    goto :RunAuraSeed
)

:: Fallback standard locations
set FALLBACK_PATHS="%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" "%PROGRAMFILES%\Python312\python.exe" "%PROGRAMFILES%\Python311\python.exe" "%PROGRAMFILES%\Python310\python.exe"

for %%P in (%FALLBACK_PATHS%) do (
    if exist %%P (
        set FOUND_PYTHON=%%P
        goto :RunAuraSeed
    )
)

echo [AuraSeed Bootstrapper] Error: Could not locate a base Python executable to bootstrap discovery.
exit /b 1

:RunAuraSeed
:: Execute the auraseed module
"%FOUND_PYTHON%" -m auraseed %*
exit /b %ERRORLEVEL%
