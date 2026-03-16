@echo off
chcp 65001 > nul

set PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
set SCRIPT=%~dp0main.py

%PYTHON% "%SCRIPT%"

if %ERRORLEVEL% neq 0 (
    echo.
    echo Exit code: %ERRORLEVEL%
)

pause
