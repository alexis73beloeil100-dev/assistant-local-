@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo   Activation du demarrage automatique de l Assistant local
echo   ---------------------------------------------------------
echo.
.venv\Scripts\python.exe -m assistant.cli demarrage-auto on
echo.
echo   Appuie sur une touche pour fermer.
pause >nul
