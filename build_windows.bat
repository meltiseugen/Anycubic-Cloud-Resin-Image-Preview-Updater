@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 goto :error
)
set "APP_PYTHON=%CD%\.venv\Scripts\python.exe"
"%APP_PYTHON%" -c "import sys; assert sys.version_info >= (3, 12), 'Python 3.12+ is required'"
if errorlevel 1 goto :error
"%APP_PYTHON%" -m pip --version >nul 2>&1
if errorlevel 1 "%APP_PYTHON%" -m ensurepip --upgrade
if errorlevel 1 goto :error
"%APP_PYTHON%" -m pip install -r requirements-build.lock -e ".[dev]"
if errorlevel 1 goto :error
"%APP_PYTHON%" tools\collect_licenses.py
if errorlevel 1 goto :error
"%APP_PYTHON%" -m pytest -q
if errorlevel 1 goto :error
"%APP_PYTHON%" -m PyInstaller --clean --noconfirm AnycubicFileUpdater.spec
if errorlevel 1 goto :error
set "APP_ISCC=%ISCC%"
if not defined APP_ISCC if exist ".tools\InnoSetup\ISCC.exe" set "APP_ISCC=%CD%\.tools\InnoSetup\ISCC.exe"
if not defined APP_ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "APP_ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined APP_ISCC if exist "%ProgramFiles%\Inno Setup 7\ISCC.exe" set "APP_ISCC=%ProgramFiles%\Inno Setup 7\ISCC.exe"
if not defined APP_ISCC for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do set "APP_ISCC=%%I"
if not defined APP_ISCC (
    echo Standalone EXE built: dist\AnycubicFileUpdater.exe
    echo Install Inno Setup or set ISCC to its ISCC.exe path, then run this script again.
    exit /b 2
)
"%APP_ISCC%" packaging\installer.iss
if errorlevel 1 goto :error
echo Built dist\AnycubicFileUpdater.exe and dist\AnycubicFileUpdater-Setup.exe
exit /b 0
:error
echo Build failed. See the error above.
exit /b 1
