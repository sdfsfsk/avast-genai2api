param(
    [int]$X,
    [int]$Y,
    [int]$SettleMs = 1500
)

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class M {
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
    [DllImport("user32.dll")] public static extern bool SetPhysicalCursorPos(int X, int Y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    public const uint LEFTDOWN = 0x0002, LEFTUP = 0x0004;
}
"@

$h = (Get-Process AvastUI | Where-Object { $_.MainWindowHandle -ne 0 }).MainWindowHandle
Write-Output ("main hwnd = " + $h)
if (-not $h) { exit 1 }

[M]::ShowWindow([IntPtr]$h, 9) | Out-Null        # SW_RESTORE
[M]::BringWindowToTop([IntPtr]$h) | Out-Null
[M]::SetForegroundWindow([IntPtr]$h) | Out-Null
Start-Sleep -Milliseconds $SettleMs
Write-Output ("foreground now = " + [M]::GetForegroundWindow())

[M]::SetPhysicalCursorPos($X, $Y) | Out-Null
Start-Sleep -Milliseconds 500
[M]::mouse_event([M]::LEFTDOWN, 0, 0, 0, [IntPtr]::Zero)
Start-Sleep -Milliseconds 90
[M]::mouse_event([M]::LEFTUP, 0, 0, 0, [IntPtr]::Zero)
Write-Output ("clicked $X,$Y")
