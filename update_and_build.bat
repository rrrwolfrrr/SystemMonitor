@echo off
setlocal EnableExtensions

cd /d "%~dp0"
if errorlevel 1 goto :directory_error

where git.exe >nul 2>&1
if errorlevel 1 goto :git_not_found

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 goto :not_repository

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not defined BRANCH goto :branch_error
if /i not "%BRANCH%"=="main" goto :wrong_branch

set "HAS_CHANGES="
for /f "delims=" %%S in ('git status --porcelain --untracked-files=normal 2^>nul') do set "HAS_CHANGES=1"
if defined HAS_CHANGES goto :local_changes

echo Updating main from origin...
git pull --ff-only origin main
if errorlevel 1 goto :pull_error

if not exist "build.bat" goto :build_script_missing
echo.
echo Building the updated application...
call build.bat
if errorlevel 1 goto :build_error

echo.
echo Update and build completed successfully.
echo Output: "%CD%\dist\SystemMonitor\SystemMonitor.exe"
goto :finish

:directory_error
echo ERROR: Cannot change to the directory containing this script.
goto :failure

:git_not_found
echo ERROR: Git was not found in PATH. Install Git for Windows and try again.
goto :failure

:not_repository
echo ERROR: This script must be inside the SystemMonitor Git repository.
goto :failure

:branch_error
echo ERROR: Could not determine the current Git branch.
goto :failure

:wrong_branch
echo ERROR: This script only updates the main branch.
echo Current branch: %BRANCH%
echo Switch to main, then run this script again.
goto :failure

:local_changes
echo ERROR: The working tree has local or untracked changes.
echo Save or commit them before updating; this script will not overwrite them.
git status --short
goto :failure

:pull_error
echo ERROR: Git could not fast-forward main from origin.
echo Check the GitHub connection and resolve any branch divergence, then retry.
goto :failure

:build_script_missing
echo ERROR: build.bat was not found in the repository root.
goto :failure

:build_error
echo ERROR: The build failed. Review the build.bat output above.
goto :failure

:failure
echo.
echo No automatic reset or cleanup was performed.

:finish
echo.
pause
exit /b
