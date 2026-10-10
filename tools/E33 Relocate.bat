@echo off
title E33 Wardrobe Relocator
rem Drag one or more mod folders from your library onto this file to relocate them for
rem in-game switching. Close the game first. Needs Python 3.8+, UE4SS and retoc.exe (see docs).
cd /d "%~dp0"
if "%~1"=="" (
    echo Drag one or more mod folders from your mod library onto this file,
    echo or run:  py -3 e33_relocate.py --mod "<library>\<mod folder>"
    goto done
)
set "ARGS="
:collect
if "%~1"=="" goto run
set "ARGS=%ARGS% --mod "%~1""
shift
goto collect
:run
py -3 -c "import sys; sys.exit(sys.version_info < (3, 8))" >nul 2>nul
if not errorlevel 1 (
    py -3 e33_relocate.py %ARGS%
    goto done
)
python -c "import sys; sys.exit(sys.version_info < (3, 8))" >nul 2>nul
if not errorlevel 1 (
    python e33_relocate.py %ARGS%
    goto done
)
echo Python 3.8 or newer was not found. Install it from https://www.python.org/downloads/
echo and run this file again.
:done
pause
