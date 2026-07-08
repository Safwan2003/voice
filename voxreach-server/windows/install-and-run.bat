@echo off
setlocal enabledelayedexpansion

:: ============================================================================
:: Voxreach - Windows one-click setup and run
:: ============================================================================
:: Bootstraps WSL2 (Windows Subsystem for Linux) + Ubuntu, installs the
:: voxreach-server system inside it, and runs it there. vLLM has no solid
:: native Windows support, so this uses WSL2 - Windows' own supported way to
:: run a real Linux environment with NVIDIA GPU passthrough - rather than
:: reimplementing the whole pipeline in batch/PowerShell.
::
:: Requirements:
::   - Windows 10 (build 19041+) or Windows 11
::   - An NVIDIA GPU with the latest Windows NVIDIA driver already installed
::     (get it from nvidia.com - WSL2 GPU support uses that driver directly,
::     you do NOT install a separate driver inside Linux)
::   - Administrator rights (needed once, to enable WSL2)
::
:: IMPORTANT: on a machine with nothing installed yet, this will need at
:: least one restart partway through (WSL2 itself requires it the first time
:: it's enabled). This script tells you exactly when to restart and re-run.
:: ============================================================================

echo ============================================================
echo  Voxreach - Windows Setup
echo ============================================================
echo.

:: --- Step 0: must run as Administrator (required to enable WSL2) ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo This script must run as Administrator.
    echo Right-click install-and-run.bat and choose "Run as administrator".
    pause
    exit /b 1
)

:: --- Step 1: is WSL2 installed at all? ---
wsl --status >nul 2>&1
if %errorlevel% neq 0 (
    echo [1/5] WSL2 not found. Installing WSL2 + Ubuntu...
    wsl --install -d Ubuntu
    echo.
    echo ============================================================
    echo  WSL2 is installing. This requires a RESTART.
    echo  1. Restart your computer now.
    echo  2. After restarting, double-click this file again.
    echo ============================================================
    pause
    exit /b 0
)
echo [1/5] WSL2 is installed.

:: --- Step 2: is Ubuntu installed AND ready to use? ---
:: Deliberately not parsing "wsl -l" text output here: wsl.exe pipes output
:: as UTF-16LE, which silently breaks findstr matching even when the name
:: is visibly right there. Instead, just try to actually run something in
:: the distro and trust the exit code - that's a more direct signal anyway
:: (it also catches "installed but never had its first-run user created"
:: as a single case, rather than two separate checks).
wsl -d Ubuntu -- true >nul 2>&1
if %errorlevel% equ 0 (
    echo [2/5] Ubuntu is installed and ready.
    goto :ubuntu_ready
)

echo [2/5] Ubuntu not found or not finished setting up. Installing/launching...
wsl --install -d Ubuntu
echo.
echo ============================================================
echo  If a window opened asking you to create a Linux username and
echo  password, do that now, then close that window.
echo  Once done, double-click this file again.
echo ============================================================
pause
exit /b 0

:ubuntu_ready

:: --- Step 3: check GPU is visible inside WSL2 (warn, don't block) ---
echo [3/5] Checking GPU visibility inside WSL2...
wsl -d Ubuntu -- bash -c "nvidia-smi" >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo WARNING: nvidia-smi did not run successfully inside WSL2.
    echo Make sure the latest NVIDIA Windows driver is installed from
    echo nvidia.com - WSL2 GPU support uses it directly, no separate
    echo Linux driver needed. Continuing anyway, but vLLM will fail
    echo later if the GPU truly isn't visible.
    echo.
)

:: --- Step 4: install prerequisites + clone/update the repo inside WSL2 ---
:: Done via a tracked bootstrap.sh (fetched from the repo) rather than a
:: long inline command here, so it's not fighting cmd.exe's quoting rules.
echo [4/5] Making sure curl is available inside WSL2...
wsl -d Ubuntu -- sudo apt-get update -y
wsl -d Ubuntu -- sudo apt-get install -y curl

echo [4/5] Running the setup script inside WSL2 (this can take several
echo       minutes the first time - Python packages, vLLM, etc.)...
echo.
wsl -d Ubuntu -- bash -c "curl -fsSL https://raw.githubusercontent.com/Safwan2003/voice/main/voxreach-server/windows/bootstrap.sh | bash"

if %errorlevel% neq 0 (
    echo.
    echo Setup failed - see the output above for the specific error.
    pause
    exit /b 1
)
echo [4/5] Setup complete.

:: --- Step 5: run it ---
echo [5/5] Starting Voxreach (vLLM + livekit-server + worker + UI)...
echo       This may take a while the first time - vLLM has to load the
echo       model, and Whisper/OmniVoice models download on first use.
echo.
echo ============================================================
echo  Once you see a "ready-to-click link", open it in your browser.
echo  Press Ctrl+C in this window to stop everything.
echo ============================================================
echo.

wsl -d Ubuntu -- bash -c "cd ~/voice/voxreach-server && . .venv/bin/activate && ./start.sh office.env"

pause
