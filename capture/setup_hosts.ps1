# Temporary helper: gain write access to the hosts file and add capture entries.
$hosts = "$env:SystemRoot\System32\drivers\etc\hosts"
$aclBackup = "D:\avast-genai2api\capture\hosts-acl.txt"

Write-Output "=== current owner / ACL ==="
$f = Get-Item $hosts -Force
$acl = Get-Acl $hosts
Write-Output ("Owner: " + $acl.Owner)
$acl | Format-List | Out-String | Set-Content $aclBackup
Write-Output ("ACL backed up to " + $aclBackup)

if ($args -contains "-restore") {
    Write-Output "restore mode not implemented yet"
    exit 0
}

Write-Output "=== taking ownership ==="
takeown /f $hosts 2>&1 | Out-String | Write-Output
icacls $hosts /grant "Administrators:F" 2>&1 | Out-String | Write-Output

Write-Output "=== appending capture entries ==="
$lines = @(
  "",
  "# --- avast-genai2api capture (temporary) ---",
  "127.0.0.1 genai-rest.avast.com",
  "127.0.0.1 genai-ws.avast.com",
  "# --- end capture ---"
)
try {
    Add-Content -Path $hosts -Value $lines -ErrorAction Stop
    Write-Output "APPEND OK"
} catch {
    Write-Output ("APPEND FAILED: " + $_.Exception.Message)
}

Write-Output "=== tail of hosts ==="
Get-Content $hosts -Tail 7
