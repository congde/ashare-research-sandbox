# Rename GitHub repo congde/codexDemo -> congde/ashare-research-sandbox
# Requires: gh auth login (run once)

$ErrorActionPreference = "Stop"
$newName = "ashare-research-sandbox"
$oldRepo = "congde/codexDemo"

gh auth status | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "请先登录 GitHub CLI：gh auth login"
    exit 1
}

Write-Host "Renaming $oldRepo -> congde/$newName ..."
gh repo rename $newName --repo $oldRepo --yes
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

git remote set-url origin "https://github.com/congde/$newName.git"
Write-Host "Done. Remote: https://github.com/congde/$newName.git"
