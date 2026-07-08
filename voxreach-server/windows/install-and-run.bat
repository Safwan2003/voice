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
    echo [1/6] WSL2 not found. Installing WSL2 + Ubuntu...
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
echo [1/6] WSL2 is installed.

:: --- Step 2: is the Ubuntu distro registered? ---
wsl -l -q | findstr /i "Ubuntu" >nul 2>&1
if %errorlevel% neq 0 (
    echo [2/6] Installing Ubuntu in WSL2...
    wsl --install -d Ubuntu
    echo.
    echo ============================================================
    echo  Ubuntu is installing. A window may open asking you to create
    echo  a Linux username and password - do that now.
    echo  Once it finishes, double-click this file again.
    echo ============================================================
    pause
    exit /b 0
)
echo [2/6] Ubuntu is installed in WSL2.

:: --- Step 3: has Ubuntu completed its first-run user setup? ---
wsl -d Ubuntu -- true >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ============================================================
    echo  Ubuntu needs its one-time first launch to finish setup.
    echo  1. Open a new window and run: wsl -d Ubuntu
    echo  2. Follow the prompts to create a Linux username/password.
    echo  3. Once you see a Linux command prompt, close that window
    echo     and double-click this file again.
    echo ============================================================
    pause
    exit /b 0
)
echo [3/6] Ubuntu is ready.

:: --- Step 4: check GPU is visible inside WSL2 (warn, don't block) ---
echo [4/6] Checking GPU visibility inside WSL2...
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

:: --- Step 5: install prerequisites + clone/update the repo inside WSL2 ---
:: Done via a tracked bootstrap.sh (fetched from the repo) rather than a
:: long inline command here, so it's not fighting cmd.exe's quoting rules.
echo [5/6] Making sure curl is available inside WSL2...
wsl -d Ubuntu -- sudo apt-get update -y
wsl -d Ubuntu -- sudo apt-get install -y curl

echo [5/6] Running the setup script inside WSL2 (this can take several
echo       minutes the first time - Python packages, vLLM, etc.)...
echo.
wsl -d Ubuntu -- bash -c "curl -fsSL https://raw.githubusercontent.com/Safwan2003/voice/main/voxreach-server/windows/bootstrap.sh | bash"

if %errorlevel% neq 0 (
    echo.
    echo Setup failed - see the output above for the specific error.
    pause
    exit /b 1
)
echo [5/6] Setup complete.

:: --- Step 6: run it ---
echo [6/6] Starting Voxreach (vLLM + livekit-server + worker + UI)...
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
