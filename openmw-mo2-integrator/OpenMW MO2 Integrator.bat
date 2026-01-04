@echo off
REM OpenMW MO2 Integrator Launcher
REM Double-click this file to start the application

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation
    pause
    exit /b 1
)

REM Launch the integrator
python "%~dp0integrator.py"

REM If there was an error, pause so user can see it
if errorlevel 1 (
    echo.
    echo An error occurred. Press any key to exit...
    pause >nul
)
