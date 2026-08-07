@ECHO OFF
REM ============================================================
REM  PalSchematics - add Palworld schematics to a save
REM  First run builds a local Python environment (needs internet
REM  and Python 3.10+). After that it just launches.
REM ============================================================
cd /D "%~dp0"

IF NOT EXIST ".venv\Scripts\python.exe" (
    ECHO First run - setting up. Please wait...
    py -3 --version >NUL 2>NUL
    IF %ERRORLEVEL%==0 ( py -3 -m venv .venv ) ELSE (
        python --version >NUL 2>NUL
        IF %ERRORLEVEL%==0 ( python -m venv .venv ) ELSE (
            ECHO Python was not found. Install Python 3.10+ from
            ECHO https://www.python.org/downloads/  ^(tick "Add Python to PATH"^)
            ECHO then run this again.
            PAUSE
            EXIT /B 1
        )
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    IF %ERRORLEVEL% NEQ 0 ( ECHO Dependency install failed. & PAUSE & EXIT /B 1 )
)

IF NOT EXIST "oo2core_9_win64.dll" (
    ECHO.
    ECHO  oo2core_9_win64.dll is missing.
    ECHO.
    ECHO  Palworld 1.0 saves are Oodle-compressed, so this program needs the
    ECHO  game's own decompression runtime. Copy that file here from:
    ECHO      Steam\steamapps\common\Palworld\Pal\Binaries\Win64\
    ECHO.
    PAUSE
)

".venv\Scripts\python.exe" "main.py"
IF %ERRORLEVEL% NEQ 0 PAUSE
