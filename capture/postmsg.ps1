param(
    [int]$X,
    [int]$Y
)

Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class N {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr p, EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern IntPtr PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern IntPtr WindowFromPhysicalPoint(POINT p);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
  public const uint WM_MOUSEMOVE=0x0200, WM_LBUTTONDOWN=0x0201, WM_LBUTTONUP=0x0202;
  public const uint WM_PARENTNOTIFY=0x0210, WM_ACTIVATE=0x0006, WM_SETFOCUS=0x0007;

  public static List<string> Dump(IntPtr root) {
    var outp = new List<string>();
    EnumChildWindows(root, (h, l) => {
      var sb = new StringBuilder(256);
      GetClassNameW(h, sb, 256);
      RECT r; GetWindowRect(h, out r);
      uint pid; GetWindowThreadProcessId(h, out pid);
      bool vis = IsWindowVisible(h);
      outp.Add(string.Format("h={0} pid={1} vis={2} class='{3}' rect={4},{5},{6},{7}",
        h, pid, vis, sb.ToString(), r.L, r.T, r.R, r.B));
      return true;
    }, IntPtr.Zero);
    return outp;
  }
}
"@

$main = (Get-Process AvastUI | Where-Object { $_.MainWindowHandle -ne 0 }).MainWindowHandle
Write-Output ("main=" + $main)
Write-Output "=== children ==="
[N]::Dump([IntPtr]$main) | ForEach-Object { Write-Output $_ }

$pt = New-Object N+POINT
$pt.X = $X; $pt.Y = $Y
$hit = [N]::WindowFromPhysicalPoint($pt)
Write-Output ("window under ($X,$Y) = " + $hit)
$sb = New-Object System.Text.StringBuilder 256
[N]::GetClassNameW($hit, $sb, 256) | Out-Null
Write-Output ("  class = " + $sb.ToString())

# convert physical screen point to client coords of the hit window
$c = New-Object N+POINT
$c.X = $X; $c.Y = $Y
$origin = New-Object N+POINT
[N]::ClientToScreen($hit, [ref]$origin) | Out-Null
$cx = $X - $origin.X
$cy = $Y - $origin.Y
$lp = [IntPtr](($cy -shl 16) -bor ($cx -band 0xFFFF))
Write-Output ("client coords in hit window = $cx,$cy  lparam=$lp")

[N]::PostMessage($hit, [N]::WM_MOUSEMOVE, [IntPtr]::Zero, $lp) | Out-Null
Start-Sleep -Milliseconds 120
[N]::PostMessage($hit, [N]::WM_LBUTTONDOWN, [IntPtr]1, $lp) | Out-Null
Start-Sleep -Milliseconds 90
[N]::PostMessage($hit, [N]::WM_LBUTTONUP, [IntPtr]::Zero, $lp) | Out-Null
Write-Output "posted click messages"
