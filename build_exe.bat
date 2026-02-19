@echo off
echo ==========================================
echo    PawiScribe Build Script for Windows
echo ==========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.9+ from https://python.org
    pause
    exit /b 1
)

echo [1/5] Installing PyInstaller...
pip install pyinstaller

echo.
echo [2/5] Cleaning old builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist __pycache__ rmdir /s /q __pycache__

echo.
echo [3/5] Building executable...
echo This may take 5-15 minutes depending on your system...
echo.

pyinstaller pawiscribe.spec

if errorlevel 1 (
    echo.
    echo ERROR: Build failed!
    echo Check the error messages above.
    pause
    exit /b 1
)

echo.
echo [4/5] Checking build output...
if exist dist\PawiScribe.exe (
    echo SUCCESS: dist\PawiScribe.exe created!
    for %%I in (dist\PawiScribe.exe) do echo File size: %%~zI bytes
) else (
    echo ERROR: PawiScribe.exe not found in dist folder
    pause
    exit /b 1
)

echo.
echo [5/5] Copying additional files...
if exist config.json copy config.json dist\
if exist INSTALL.txt copy INSTALL.txt dist\

echo.
echo ==========================================
echo    BUILD COMPLETE!
echo ==========================================
echo.
echo Output: dist\PawiScribe.exe
echo.
echo To distribute:
echo   1. Zip the 'dist' folder contents
echo   2. Share PawiScribe.exe + INSTALL.txt
echo.
echo IMPORTANT: Test the executable on a clean Windows
echo            machine before distributing!
echo.
pause
