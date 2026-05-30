@echo off
REM Setup-and-run launcher for ytwrangler.
REM First run: creates the venv and installs requirements.
REM Later runs: just launches the app. Uses the script's own folder (%~dp0).
set "DIR=%~dp0"
set "VENV=%DIR%.venv"

if not exist "%VENV%\Scripts\activate.bat" (
    echo First run - creating virtual environment...
    python -m venv "%VENV%"
)

call "%VENV%\Scripts\activate.bat"

if not exist "%VENV%\.deps-installed" (
    echo Installing dependencies ^(one time^)...
    pip install -q -r "%DIR%requirements.txt"
    type nul > "%VENV%\.deps-installed"
)

python "%DIR%main.py" %*
