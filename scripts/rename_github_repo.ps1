# Rename GitHub repo congde/ashare-research-sandbox -> congde/web3-quant-sandbox
# Requires: gh auth login (run once)

$ErrorActionPreference = "Stop"
$newName = "web3-quant-sandbox"
$oldRepo = "congde/ashare-research-sandbox"

gh auth status | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "请先登录 GitHub CLI：gh auth login"
    exit 1
}

Write-Host "Renaming $oldRepo -> congde/$newName ..."
gh repo rename $newName --repo $oldRepo --yes
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

git remote set-url origin "git@github.com:congde/$newName.git"
git remote set-url --push origin "git@github.com:congde/$newName.git"
Write-Host "Done. Remote: git@github.com:congde/$newName.git"
