@echo off
setlocal
set SCRIPT_DIR=%~dp0
set PYTHON_EXE=%SCRIPT_DIR%.venv\Scripts\python.exe
if exist "%PYTHON_EXE%" (
  "%PYTHON_EXE%" "%SCRIPT_DIR%qgraphic.py" %*
) else (
  python "%SCRIPT_DIR%qgraphic.py" %*
)
endlocal
