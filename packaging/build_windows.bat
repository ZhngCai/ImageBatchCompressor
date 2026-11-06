@echo off
setlocal
cd /d "%~dp0\.."

if "%PYTHON%"=="" set PYTHON=python

%PYTHON% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
  echo 需要 Python 3.11 或更高版本
  exit /b 1
)

%PYTHON% -m pip --version >nul 2>&1
if errorlevel 1 %PYTHON% -m ensurepip --upgrade

%PYTHON% -m pip install -e . pyinstaller
if errorlevel 1 exit /b 1

%PYTHON% -m PyInstaller --clean --noconfirm packaging\image-compress.spec
if errorlevel 1 exit /b 1

echo 构建完成：dist\image-compress\image-compress.exe
echo 运行：dist\image-compress\image-compress.exe --help
endlocal
