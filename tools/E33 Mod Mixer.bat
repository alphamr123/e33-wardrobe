@echo off
title E33 Mod Mixer
rem Starts the E33 Mod Mixer in your browser. Needs Python 3.8+ from python.org.
cd /d "%~dp0"
rem Run Python to test it: "where python" also finds the Microsoft Store placeholder.
py -3 -c "import sys; sys.exit(sys.version_info < (3, 8))" >nul 2>nul
if not errorlevel 1 (
    py -3 e33_mixer.py gui %*
    goto done
)
python -c "import sys; sys.exit(sys.version_info < (3, 8))" >nul 2>nul
if not errorlevel 1 (
    python e33_mixer.py gui %*
    goto done
)
echo Python 3.8 or newer was not found. Install it from https://www.python.org/downloads/
echo and run this file again.
:done
pause
