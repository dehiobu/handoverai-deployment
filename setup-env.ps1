# -----------------------------------------
# Project Environment Bootstrap Script
# Uses Python 3.12 explicitly
# Creates venv only if missing
# Installs Pandas if not already installed
# Activates environment
# -----------------------------------------

$projectPath = "C:\Projects\gp-triage-poc"
$venvPath = "$projectPath\venv"

Set-Location $projectPath

# Create venv if it doesn't exist
if (!(Test-Path $venvPath)) {
    Write-Host "Creating virtual environment with Python 3.12..."
    py -3.12 -m venv venv

    # Optional: upgrade pip (commented out by default)
    # python -m pip install --upgrade pip

    Write-Host "Initial environment setup complete."
}
else {
    Write-Host "Virtual environment already exists."
}

# Activate environment
Write-Host "Activating environment..."
& "$venvPath\Scripts\Activate.ps1"

# Install Pandas if missing
Write-Host "Ensuring Pandas is installed..."
pip show pandas > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Pandas not found. Installing..."
    pip install pandas
} else {
    Write-Host "Pandas already installed."
}

Write-Host "Environment ready."
