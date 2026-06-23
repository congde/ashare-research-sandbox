# Reset stuck GitHub Desktop merge state for this repository.
# Safe to run: does not delete source files, only git merge metadata.
param(
    [string]$RepoRoot = (Split-Path $PSScriptRoot -Parent)
)

$ErrorActionPreference = 'Continue'
$RepoRoot = (Resolve-Path $RepoRoot).Path

Write-Host "Repository: $RepoRoot"

Get-Process GitHubDesktop -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2

$mergeArtifacts = @(
    'MERGE_HEAD', 'MERGE_MSG', 'MERGE_MODE', 'AUTO_MERGE',
    'CHERRY_PICK_HEAD', 'REBASE_HEAD', 'REVERT_HEAD'
)
foreach ($name in $mergeArtifacts) {
    $path = Join-Path $RepoRoot ".git\$name"
    if (Test-Path $path) {
        Remove-Item $path -Force
        Write-Host "Removed .git\$name"
    }
}

Push-Location $RepoRoot
git merge --abort 2>$null
git rebase --abort 2>$null
git cherry-pick --abort 2>$null
git fetch origin
git status -sb
git pull --ff-only origin main
Pop-Location

Write-Host ""
Write-Host "Git merge state is clean."
Write-Host "If GitHub Desktop still shows a merge banner:"
Write-Host "  1. File -> Remove Repository (do not delete files)"
Write-Host "  2. File -> Add Local Repository -> $RepoRoot"
