$ErrorActionPreference = "Stop"

$Python = $env:WEWORK_PYTHON
if ([string]::IsNullOrWhiteSpace($Python)) {
  $Python = "D:\conda_envs\wework\python.exe"
}

& $Python -V
& $Python -m pip show pyinstaller *> $null
if ($LASTEXITCODE -ne 0) {
  & $Python -m pip install --upgrade pyinstaller==6.11.0
}

& $Python -m pip show backports.tarfile *> $null
if ($LASTEXITCODE -ne 0) {
  & $Python -m pip install --upgrade backports.tarfile
}

& $Python (Join-Path $PSScriptRoot "build_release.py") --clean
