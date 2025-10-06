# vtrl_red_black_enhanced.py
# Space Aim - Red-on-Black Optimizer with macOS Controls
# Enhanced version with better organization and macOS-style window controls
#
# Requirements:
#   Python 3.9+, PyQt5
#   pip install pyqt5
#
# Safety: Creates backups before destructive actions. Use at your own risk.

import sys, os, json, subprocess, ctypes, tempfile, datetime, shutil, re
from pathlib import Path
from functools import partial

from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout, QHBoxLayout, QStackedWidget, QCheckBox, QMessageBox, QFileDialog,
    QTextEdit, QFrame, QSlider, QColorDialog, QGraphicsBlurEffect, QSizeGrip, QScrollArea
)
from PyQt5.QtCore import Qt, QPoint, QTimer
from PyQt5.QtGui import QPalette, QColor, QPixmap, QPainter, QBrush, QFont

# -----------------------------
# Windows-only guard
# -----------------------------
if os.name != "nt":
    print("This script is intended to run on Windows.")
    sys.exit(1)

try:
    import winreg
except Exception:
    winreg = None

# -----------------------------
# App directories & configuration
# -----------------------------
APP_DIR = Path.home() / ".vtrl_pro"
BACKUP_DIR = APP_DIR / "backups"
HISTORY_FILE = APP_DIR / "history.log"
SETTINGS_FILE = APP_DIR / "settings.json"
APP_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

def log(msg):
    """Log messages with timestamp"""
    ts = datetime.datetime.now().isoformat()
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")

def is_admin():
    """Check if running with administrator privileges"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def run_cmd(cmd, shell=False, timeout=600):
    """Execute command and return result"""
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=shell, creationflags=subprocess.CREATE_NO_WINDOW)
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out.strip(), err.strip()
    except subprocess.TimeoutExpired:
        proc.kill()
        return 1, "", "Command timed out"
    except Exception as e:
        return 1, "", str(e)

def run_powershell(cmd, timeout=600):
    """Execute PowerShell command"""
    ps = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd]
    return run_cmd(ps, timeout=timeout)

def relaunch_as_admin():
    """Relaunch script with admin privileges"""
    if is_admin():
        return True
    params = " ".join([f'"{arg}"' for arg in sys.argv[1:]])
    executable = sys.executable
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, f'"{os.path.abspath(sys.argv[0])}" {params}', None, 0)
        sys.exit(0)
    except Exception as e:
        log(f"Elevation failed: {e}")
        return False

# -----------------------------
# Backup utilities
# -----------------------------

def save_registry_snapshot(keys_list, prefix="reg_backup"):
    """Save registry snapshot before modifications"""
    snapshot = {"timestamp": datetime.datetime.now().isoformat(), "items": []}
    for hive_str, path in keys_list:
        try:
            root = getattr(winreg, hive_str)
            key = winreg.OpenKey(root, path, 0, winreg.KEY_READ)
            i = 0
            while True:
                try:
                    name, val, typ = winreg.EnumValue(key, i)
                    snapshot["items"].append({"hive": hive_str, "path": path, "name": name, "value": val, "type": int(typ)})
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(key)
        except Exception:
            pass
    fn = BACKUP_DIR / f"{prefix}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.json"
    fn.write_text(json.dumps(snapshot, default=str, indent=2), encoding="utf-8")
    log(f"Saved registry snapshot: {fn}")
    return str(fn)

def save_appx_list(pattern, prefix="appx_backup"):
    """Save list of AppX packages before removal"""
    cmd = f'Get-AppxPackage -AllUsers | Where-Object {{$_.Name -like "*{pattern}*"}} | Select-Object PackageFullName | ConvertTo-Json'
    rc, out, err = run_powershell(cmd)
    if rc != 0:
        log(f"Failed getting Appx list: {err}")
        return None
    try:
        arr = json.loads(out) if out else []
        if isinstance(arr, dict):
            arr = [arr]
    except Exception:
        arr = []
    fn = BACKUP_DIR / f"{prefix}_{pattern}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.json"
    fn.write_text(json.dumps({"timestamp": datetime.datetime.now().isoformat(), "packages": arr}, indent=2), encoding="utf-8")
    log(f"Saved Appx backup: {fn}")
    return str(fn)

def set_reg_value(hive, path, name, value, value_type=winreg.REG_DWORD):
    """Safe registry value setter with logging"""
    try:
        root = getattr(winreg, hive)
        key = winreg.CreateKeyEx(root, path, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, name, 0, value_type, value)
        winreg.CloseKey(key)
        log(f"Registry: {hive}\\{path}\\{name} = {value}")
        return True, f"Set {name}"
    except Exception as e:
        log(f"Registry error: {e}")
        return False, str(e)

# -----------------------------
# System Tweaks
# -----------------------------

def tweak_disable_telemetry():
    set_reg_value("HKEY_LOCAL_MACHINE", r"SOFTWARE\Policies\Microsoft\Windows\DataCollection", "AllowTelemetry", 0)
    set_reg_value("HKEY_CURRENT_USER", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "SystemPaneSuggestionsEnabled", 0)
    return True, "Telemetry reduced (conservative approach)"

def tweak_disable_sysmain():
    run_cmd(["sc", "config", "SysMain", "start=", "disabled"])
    run_cmd(["sc", "stop", "SysMain"])
    return True, "SysMain (Superfetch) disabled"

def tweak_disable_search_index():
    run_cmd(["sc", "config", "WSearch", "start=", "disabled"])
    run_cmd(["sc", "stop", "WSearch"])
    return True, "Windows Search indexer disabled"

def tweak_disable_background_apps():
    set_reg_value("HKEY_LOCAL_MACHINE", r"SOFTWARE\Policies\Microsoft\Windows\AppPrivacy", "LetAppsRunInBackground", 2)
    return True, "Background apps blocked (may require restart)"

def tweak_disable_gamedvr():
    set_reg_value("HKEY_CURRENT_USER", r"SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled", 0)
    set_reg_value("HKEY_CURRENT_USER", r"SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR", "AllowGameDVR", 0)
    return True, "Game DVR disabled"

def tweak_disable_hibernation():
    rc, out, err = run_cmd(["powercfg", "-h", "off"])
    return (rc == 0), out if rc == 0 else err

def tweak_disable_windows_animations():
    """Disable Windows animations for better FPS"""
    set_reg_value("HKEY_CURRENT_USER", r"Control Panel\Desktop\WindowMetrics", "MinAnimate", 0, winreg.REG_SZ)
    set_reg_value("HKEY_CURRENT_USER", r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects", "VisualFXSetting", 2)
    return True, "Windows animations disabled"

def tweak_gpu_hardware_scheduling():
    """Enable GPU hardware scheduling for reduced latency"""
    set_reg_value("HKEY_LOCAL_MACHINE", r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode", 2)
    return True, "GPU hardware scheduling enabled (restart required)"

def tweak_game_mode():
    """Enable Windows Game Mode"""
    set_reg_value("HKEY_CURRENT_USER", r"Software\Microsoft\GameBar", "AutoGameModeEnabled", 1)
    return True, "Game Mode enabled"

def tweak_disable_fullscreen_optimization():
    """Disable fullscreen optimizations"""
    set_reg_value("HKEY_CURRENT_USER", r"System\GameConfigStore", "GameDVR_DXGIHonorFSEWindowsCompatible", 1)
    set_reg_value("HKEY_CURRENT_USER", r"System\GameConfigStore", "GameDVR_FSEBehaviorMode", 2)
    return True, "Fullscreen optimizations disabled"

def tweak_timer_resolution():
    """Set Windows timer resolution for lower latency"""
    set_reg_value("HKEY_LOCAL_MACHINE", r"SYSTEM\CurrentControlSet\Control\Session Manager\kernel", "GlobalTimerResolutionRequests", 1)
    return True, "Timer resolution optimized"

def tweak_disable_cortana():
    """Disable Cortana"""
    set_reg_value("HKEY_LOCAL_MACHINE", r"SOFTWARE\Policies\Microsoft\Windows\Windows Search", "AllowCortana", 0)
    return True, "Cortana disabled"

def tweak_disable_windows_tips():
    """Disable Windows tips and suggestions"""
    set_reg_value("HKEY_CURRENT_USER", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "SubscribedContent-338389Enabled", 0)
    set_reg_value("HKEY_CURRENT_USER", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "SoftLandingEnabled", 0)
    return True, "Windows tips disabled"

def tweak_priority_separation():
    """Optimize CPU priority for programs"""
    set_reg_value("HKEY_LOCAL_MACHINE", r"SYSTEM\CurrentControlSet\Control\PriorityControl", "Win32PrioritySeparation", 38)
    return True, "CPU priority optimized for programs"

def tweak_reduce_menu_delay():
    """Reduce menu show delay"""
    set_reg_value("HKEY_CURRENT_USER", r"Control Panel\Desktop", "MenuShowDelay", 0, winreg.REG_SZ)
    return True, "Menu delay reduced"

def tweak_disable_sticky_keys():
    """Disable sticky keys"""
    set_reg_value("HKEY_CURRENT_USER", r"Control Panel\Accessibility\StickyKeys", "Flags", 506, winreg.REG_SZ)
    return True, "Sticky keys disabled"

def tweak_optimize_ssd():
    """Optimize SSD performance"""
    set_reg_value("HKEY_LOCAL_MACHINE", r"SYSTEM\CurrentControlSet\Control\FileSystem", "NtfsDisableLastAccessUpdate", 1)
    set_reg_value("HKEY_LOCAL_MACHINE", r"SYSTEM\CurrentControlSet\Control\FileSystem", "NtfsDisable8dot3NameCreation", 1)
    return True, "SSD optimizations applied"

def tweak_bcdedit_tweaks():
    """Apply BCDEdit performance tweaks"""
    run_cmd(["bcdedit", "/set", "disabledynamictick", "yes"])
    run_cmd(["bcdedit", "/set", "useplatformclock", "no"])
    run_cmd(["bcdedit", "/deletevalue", "useplatformtick"])
    return True, "BCDEdit tweaks applied (restart required)"

# -----------------------------
# Network Tweaks
# -----------------------------

def tweak_tcp_ack_frequency():
    set_reg_value("HKEY_LOCAL_MACHINE", r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters", "TcpAckFrequency", 1)
    return True, "TCP ACK Frequency optimized"

def tweak_disable_nagle():
    set_reg_value("HKEY_LOCAL_MACHINE", r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters", "TcpNoDelay", 1)
    return True, "Nagle algorithm disabled"

def tweak_disable_autotuning():
    rc, out, err = run_cmd(["netsh", "int", "tcp", "set", "global", "autotuninglevel=disabled"])
    return (rc == 0), "Autotuning disabled" if rc == 0 else err

def tweak_flush_dns():
    rc, out, err = run_cmd(["ipconfig", "/flushdns"])
    return (rc == 0), "DNS cache flushed" if rc == 0 else err

def tweak_reset_winsock():
    rc, out, err = run_cmd(["netsh", "winsock", "reset"])
    return (rc == 0), "Winsock reset (restart recommended)" if rc == 0 else err

def tweak_disable_delivery_optimization():
    set_reg_value("HKEY_LOCAL_MACHINE", r"SOFTWARE\Policies\Microsoft\Windows\DeliveryOptimization", "DODownloadMode", 0)
    return True, "Delivery Optimization disabled"

def tweak_network_throttling():
    """Disable network throttling"""
    set_reg_value("HKEY_LOCAL_MACHINE", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile", "NetworkThrottlingIndex", 0xffffffff)
    return True, "Network throttling disabled"

def tweak_tcp_offloading():
    """Configure TCP offloading for gaming"""
    run_cmd(["netsh", "int", "tcp", "set", "global", "chimney=disabled"])
    run_cmd(["netsh", "int", "tcp", "set", "global", "rss=enabled"])
    run_cmd(["netsh", "int", "tcp", "set", "global", "netdma=enabled"])
    return True, "TCP offloading optimized"

# -----------------------------
# Power Tweaks
# -----------------------------

def tweak_set_power_high_performance():
    rc, out, err = run_cmd(["powercfg", "/L"])
    if rc != 0:
        return False, "Failed to list power plans"
    for line in out.splitlines():
        if "high" in line.lower() or "ultimate" in line.lower():
            parts = line.split()
            for i, part in enumerate(parts):
                if len(part) == 36 and part.count('-') == 4:
                    run_cmd(["powercfg", "/setactive", part])
                    return True, f"High performance plan activated"
    return False, "No high performance plan found"

def tweak_disable_usb_selective_suspend():
    set_reg_value("HKEY_LOCAL_MACHINE", r"SYSTEM\CurrentControlSet\Services\USB", "DisableSelectiveSuspend", 1)
    return True, "USB selective suspend disabled"

def tweak_disable_sleep():
    rc, out, err = run_cmd(["powercfg", "-change", "-standby-timeout-ac", "0"])
    return (rc == 0), "Sleep disabled on AC power" if rc == 0 else err

def tweak_disable_core_parking():
    """Disable CPU core parking for maximum performance"""
    set_reg_value("HKEY_LOCAL_MACHINE", r"SYSTEM\CurrentControlSet\Control\Power\PowerSettings\54533251-82be-4824-96c1-47b60b740d00\0cc5b647-c1df-4637-891a-dec35c318583", "ValueMax", 0)
    return True, "CPU core parking disabled"

def tweak_multimedia_priority():
    """Set multimedia/gaming thread priority"""
    set_reg_value("HKEY_LOCAL_MACHINE", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "GPU Priority", 8)
    set_reg_value("HKEY_LOCAL_MACHINE", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "Priority", 6)
    set_reg_value("HKEY_LOCAL_MACHINE", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "Scheduling Category", "High", winreg.REG_SZ)
    return True, "Multimedia/gaming priority optimized"

# -----------------------------
# Debloat Functions
# -----------------------------

def remove_appx(pattern):
    backup = save_appx_list(pattern)
    cmd = f'Get-AppxPackage -AllUsers | Where-Object {{$_.Name -like "*{pattern}*"}} | ForEach-Object {{Remove-AppxPackage -Package $_.PackageFullName -ErrorAction SilentlyContinue}}'
    rc, out, err = run_powershell(cmd)
    log(f"Removed AppX: {pattern} (rc={rc})")
    return (rc == 0), f"Removed packages matching '{pattern}'\nBackup: {backup}"

def uninstall_onedrive():
    paths = [
        os.path.join(os.environ.get("SystemRoot", r"C:\\Windows"), "SysWOW64", "OneDriveSetup.exe"),
        os.path.join(os.environ.get("SystemRoot", r"C:\\Windows"), "System32", "OneDriveSetup.exe"),
    ]
    for p in paths:
        if os.path.exists(p):
            rc, out, err = run_cmd([p, "/uninstall"])
            return (rc == 0), f"OneDrive uninstalled: {out}"
    return False, "OneDrive setup not found"

# -----------------------------
# Security Functions
# -----------------------------

def _parse_version_key(path: Path):
    """Parse digits from a folder name to a sortable tuple; fallback to mtime."""
    nums = re.findall(r"\d+", path.name)
    if nums:
        try:
            return tuple(int(n) for n in nums)
        except Exception:
            pass
    try:
        return (int(path.stat().st_mtime),)
    except Exception:
        return (0,)

def find_mpcmdrun():
    """Find Windows Defender's MpCmdRun.exe (new Platform path first)."""
    # Newer Defender locations under ProgramData Platform with versioned folders
    pd = Path(os.environ.get("ProgramData", r"C:\\ProgramData"))
    platform_root = pd / "Microsoft" / "Windows Defender" / "Platform"
    exe_candidates = []
    try:
        if platform_root.exists():
            for sub in platform_root.iterdir():
                if sub.is_dir():
                    exe_path = sub / "MpCmdRun.exe"
                    if exe_path.exists():
                        exe_candidates.append(exe_path)
    except Exception:
        pass
    if exe_candidates:
        try:
            exe_candidates.sort(key=lambda p: _parse_version_key(p.parent), reverse=True)
        except Exception:
            exe_candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return str(exe_candidates[0])

    # Legacy locations as fallback
    candidates = [
        r"C:\\Program Files\\Windows Defender\\MpCmdRun.exe",
        r"C:\\Program Files (x86)\\Windows Defender\\MpCmdRun.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

def find_mrt():
    """Locate Microsoft's Malicious Software Removal Tool (MRT.exe)."""
    system_root = Path(os.environ.get("SystemRoot", r"C:\\Windows"))
    candidates = [
        system_root / "System32" / "MRT.exe",
        system_root / "SysWOW64" / "MRT.exe",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None

def mrt_quick():
    """Run MRT in quiet mode (Quick Scan)."""
    exe = find_mrt()
    if not exe:
        return False, "MRT not found"
    log("Starting MRT quick scan (/Q)")
    # Quiet mode typically performs a quick scan
    rc, out, err = run_cmd([exe, "/Q"], timeout=5400)
    if rc == 0:
        log("MRT quick scan completed")
        return True, "Quick scan completed (MRT)"
    return False, f"MRT quick scan failed: {err or out}"

def mrt_full():
    """Run MRT full scan quietly."""
    exe = find_mrt()
    if not exe:
        return False, "MRT not found"
    log("Starting MRT full scan (/F:Y)")
    # /F requests full scan; :Y auto-clean if needed
    rc, out, err = run_cmd([exe, "/F:Y"], timeout=10800)
    if rc == 0:
        log("MRT full scan completed")
        return True, "Full scan completed (MRT)"
    return False, f"MRT full scan failed: {err or out}"

def defender_quick():
    """Run Defender quick scan; fall back to MRT quick if Defender unavailable/fails."""
    exe = find_mpcmdrun()
    if exe:
        rc, out, err = run_cmd([exe, "-Scan", "-ScanType", "1"], timeout=1800)
        if rc == 0:
            return True, "Quick scan completed (Defender)"
        log(f"Defender quick scan failed (rc={rc}): {err or out}")
    # Fallback to MRT
    ok, msg = mrt_quick()
    if ok:
        return True, "Quick scan completed (MRT fallback)"
    return False, f"Scan failed: {msg}"

def defender_full():
    """Run Defender full scan; fall back to MRT full if Defender unavailable/fails."""
    exe = find_mpcmdrun()
    if exe:
        rc, out, err = run_cmd([exe, "-Scan", "-ScanType", "2"], timeout=7200)
        if rc == 0:
            return True, "Full scan completed (Defender)"
        log(f"Defender full scan failed (rc={rc}): {err or out}")
    # Fallback to MRT
    ok, msg = mrt_full()
    if ok:
        return True, "Full scan completed (MRT fallback)"
    return False, f"Scan failed: {msg}"

defender_scan_help = """
Scanning uses Windows Defender when available. If Defender is missing or returns an error,
this tool automatically falls back to Microsoft's Malicious Software Removal Tool (MRT).
- Quick Scan: Defender -ScanType 1 or MRT /Q
- Full Scan: Defender -ScanType 2 or MRT /F:Y
""".strip()

def defender_update_signatures():
    exe = find_mpcmdrun()
    if not exe:
        return False, "Windows Defender not found"
    rc, out, err = run_cmd([exe, "-SignatureUpdate"])
    return (rc == 0), "Signatures updated" if rc == 0 else f"Update failed: {err or out}"

# -----------------------------
# Maintenance Functions
# -----------------------------

def create_restore_point(name="Space_Aim_Restore"):
    cmd = f'Checkpoint-Computer -Description "{name}" -RestorePointType "MODIFY_SETTINGS"'
    rc, out, err = run_powershell(cmd, timeout=300)
    return (rc == 0), "Restore point created" if rc == 0 else f"Failed: {err}"

def cleanup_temp_files():
    tmp = Path(tempfile.gettempdir())
    count = 0
    for item in tmp.glob("*"):
        try:
            if item.is_file():
                item.unlink()
                count += 1
            elif item.is_dir():
                shutil.rmtree(item)
                count += 1
        except Exception:
            pass
    return True, f"Cleaned {count} temporary items"

def cleanup_prefetch():
    pre = Path(r"C:\\Windows\\Prefetch")
    if not pre.exists():
        return False, "Prefetch folder not accessible"
    removed = 0
    for f in pre.glob("*"):
        try:
            f.unlink()
            removed += 1
        except Exception:
            pass
    return True, f"Cleared {removed} prefetch files"

def clear_windows_update_cache():
    run_cmd(["net", "stop", "wuauserv"])
    sd = Path(r"C:\\Windows\\SoftwareDistribution")
    target = BACKUP_DIR / f"SoftwareDistribution_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    if sd.exists():
        shutil.move(str(sd), str(target))
    run_cmd(["net", "start", "wuauserv"])
    return True, f"Update cache cleared (backed up to {target.name})"

# -----------------------------
# Enhanced UI Components
# -----------------------------
BASE_QSS = """
QWidget {
    background-color: rgba(0,0,0,0);
    color: #f5f5f5;
    font-family: "Segoe UI", Arial;
    font-size: 13px;
}
#main_frame {
    background: rgba(12,12,12,0.75);
    border-radius: 16px;
}
#titlebar {
    background: rgba(20,20,20,0.9);
    border-top-left-radius: 16px;
    border-top-right-radius: 16px;
}
#sidebar {
    background: rgba(10,10,10,0.6);
    border-right: 1px solid rgba(255,0,0,0.1);
    border-bottom-left-radius: 16px;
}
QListWidget {
    background: transparent;
    border: none;
    color: #fff;
    font-weight: 600;
    padding: 8px;
    outline: none;
}
QListWidget::item {
    padding: 14px 16px;
    margin: 4px 8px;
    border-radius: 10px;
    outline: none;
    border: none;
}
QListWidget::item:selected {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8f0e0e, stop:1 #ff3838);
    color: white;
    font-weight: 700;
    outline: none;
    border: none;
}
QListWidget::item:hover:!selected {
    background: rgba(255,255,255,0.05);
}
QListWidget::item:focus {
    outline: none;
    border: none;
}
QScrollBar:vertical {
    width: 0px;
}
QScrollBar:horizontal {
    height: 0px;
}
QScrollArea {
    border: none;
    background: transparent;
}
#card {
    background: rgba(18,18,18,0.8);
    border-radius: 12px;
    padding: 16px;
    border: 1px solid rgba(255,0,0,0.08);
    margin: 8px;
}
QPushButton {
    background: rgba(255,50,50,0.15);
    border: 1px solid rgba(255,80,80,0.3);
    padding: 10px 16px;
    border-radius: 8px;
    color: #fff;
    font-weight: 600;
    outline: none;
}
QPushButton:hover {
    background: rgba(255,50,50,0.25);
    border-color: rgba(255,100,100,0.5);
}
QPushButton:pressed {
    background: rgba(255,50,50,0.35);
}
QPushButton:focus {
    outline: none;
}
QCheckBox {
    spacing: 10px;
    padding: 8px;
    outline: none;
}
QCheckBox::indicator {
    width: 20px;
    height: 20px;
    border-radius: 6px;
    background: rgba(255,255,255,0.08);
    border: 2px solid rgba(255,255,255,0.2);
}
QCheckBox::indicator:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ff5252, stop:1 #ff1744);
    border-color: #ff5252;
}
QCheckBox:focus {
    outline: none;
}
QLabel#title {
    font-size: 18px;
    font-weight: 800;
    color: #fff;
    padding: 4px 0;
}
QLabel#subtitle {
    color: rgba(245,245,245,0.7);
    font-size: 12px;
}
QTextEdit {
    background: rgba(10,10,10,0.7);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 8px;
    padding: 8px;
    color: #f0f0f0;
    outline: none;
}
QTextEdit:focus {
    outline: none;
    border: 1px solid rgba(255,255,255,0.1);
}
QSlider::groove:horizontal {
    background: rgba(255,255,255,0.1);
    height: 6px;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ff5252, stop:1 #ff1744);
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 9px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff5252, stop:1 #ff1744);
    border-radius: 3px;
}
QSlider:focus {
    outline: none;
}
"""

class MacOSTitleBar(QWidget):
    """macOS-style title bar with traffic light buttons"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("titlebar")
        self.setFixedHeight(44)
        self.parent_window = parent
        self.drag_position = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)

        # Logo on the left
        logo_label = QLabel()
        logo_pixmap = QPixmap()
        try:
            import urllib.request
            logo_url = "https://payhip.com/cdn-cgi/image/format=auto/https://pe56d.s3.amazonaws.com/o_1ivhiuq7qpr3fqksg61v978fmr.png"
            logo_data = urllib.request.urlopen(logo_url).read()
            logo_pixmap.loadFromData(logo_data)
            logo_pixmap = logo_pixmap.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_label.setPixmap(logo_pixmap)
        except:
            logo_label.setText("SA")
            logo_label.setStyleSheet("font-size: 16px; font-weight: 800; color: #ff5252;")

        layout.addWidget(logo_label)

        # Title in center
        self.title_label = QLabel("Space Aim")
        self.title_label.setStyleSheet("font-size: 14px; font-weight: 700; color: #fff;")
        layout.addWidget(self.title_label)
        layout.addStretch()

        # Traffic light buttons on the right
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)

        self.minimize_btn = self.create_traffic_button("#ffbd2e", "#dea123")
        self.maximize_btn = self.create_traffic_button("#28c940", "#1aab29")
        self.close_btn = self.create_traffic_button("#ff5f57", "#e0443e")

        self.close_btn.clicked.connect(parent.close)
        self.minimize_btn.clicked.connect(parent.showMinimized)
        self.maximize_btn.clicked.connect(self.toggle_maximize)

        button_layout.addWidget(self.minimize_btn)
        button_layout.addWidget(self.maximize_btn)
        button_layout.addWidget(self.close_btn)

        layout.addLayout(button_layout)

    def create_traffic_button(self, color, hover_color):
        btn = QPushButton()
        btn.setFixedSize(14, 14)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {color};
                border: 1px solid rgba(0,0,0,0.3);
                border-radius: 7px;
            }}
            QPushButton:hover {{
                background: {hover_color};
            }}
        """)
        return btn

    def toggle_maximize(self):
        if self.parent_window.isMaximized():
            self.parent_window.showNormal()
        else:
            self.parent_window.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.parent_window.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_position:
            self.parent_window.move(event.globalPos() - self.drag_position)

    def mouseDoubleClickEvent(self, event):
        self.toggle_maximize()

class BlurBackground(QWidget):
    """Widget with blurred background image"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pix = None
        self.blurred_label = QLabel(self)
        self.blurred_label.setScaledContents(True)
        self.blur_effect = QGraphicsBlurEffect()
        self.blur_effect.setBlurRadius(20)
        self.blurred_label.setGraphicsEffect(self.blur_effect)
        self.tint_color = QColor(180, 0, 0, 70)

    def set_background(self, path, blur_radius=20, tint_rgba=(180,0,0,70)):
        if not path or not os.path.exists(path):
            self.pix = None
            self.update()
            return
        self.pix = QPixmap(path)
        if self.pix.isNull():
            self.pix = None
            return
        self.blur_effect.setBlurRadius(blur_radius)
        self.tint_color = QColor(*tint_rgba)
        self.refresh_pixmap()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.refresh_pixmap()

    def refresh_pixmap(self):
        if not self.pix:
            self.blurred_label.hide()
            return
        scaled = self.pix.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self.blurred_label.setPixmap(scaled)
        self.blurred_label.setGeometry(self.rect())
        self.blurred_label.show()

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if self.pix:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(QBrush(self.tint_color))
            painter.setPen(Qt.NoPen)
            painter.drawRect(self.rect())

class Card(QFrame):
    """Styled card container"""
    def __init__(self, title="", subtitle=""):
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        if title:
            title_label = QLabel(title)
            title_label.setObjectName("title")
            layout.addWidget(title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("subtitle")
            layout.addWidget(subtitle_label)

        self.content_layout = QVBoxLayout()
        layout.addLayout(self.content_layout)

# -----------------------------
# Main Application Window
# -----------------------------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(1280, 820)
        self.setWindowTitle("Space Aim - Enhanced")
        self.setStyleSheet(BASE_QSS)

        self.settings = self.load_settings()
        self.init_ui()

        if self.settings.get("background_path"):
            self.background_widget.set_background(
                self.settings["background_path"],
                blur_radius=self.settings.get("blur_radius", 20),
                tint_rgba=tuple(self.settings.get("tint_rgba", (180,0,0,70)))
            )

        QTimer.singleShot(100, self.background_widget.refresh_pixmap)

    def load_settings(self):
        if SETTINGS_FILE.exists():
            try:
                return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def save_settings(self):
        SETTINGS_FILE.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")

    def init_ui(self):
        self.background_widget = BlurBackground(self)
        self.background_widget.setGeometry(self.rect())

        main_container = QVBoxLayout(self)
        main_container.setContentsMargins(0, 0, 0, 0)
        main_container.setSpacing(0)

        self.titlebar = MacOSTitleBar(self)
        main_container.addWidget(self.titlebar)

        content_frame = QFrame()
        content_frame.setObjectName("main_frame")
        content_layout = QHBoxLayout(content_frame)
        content_layout.setContentsMargins(0, 0, 0, 0)

        sidebar = self.create_sidebar()
        content_layout.addWidget(sidebar)

        self.stack = QStackedWidget()
        self.create_pages()
        content_layout.addWidget(self.stack, 1)

        main_container.addWidget(content_frame)

        self.side_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.side_list.setCurrentRow(0)

        self.size_grip = QSizeGrip(self)
        self.size_grip.setStyleSheet("QSizeGrip { width: 16px; height: 16px; }")

    def create_sidebar(self):
        sidebar_frame = QFrame()
        sidebar_frame.setObjectName("sidebar")
        sidebar_frame.setFixedWidth(240)
        sidebar_layout = QVBoxLayout(sidebar_frame)
        sidebar_layout.setContentsMargins(0, 16, 0, 16)

        header = QLabel("Space Aim")
        header.setStyleSheet("font-size: 22px; font-weight: 900; color: #ff5252; padding: 16px;")
        sidebar_layout.addWidget(header)

        self.side_list = QListWidget()
        self.side_list.setSpacing(2)
        self.side_list.setFocusPolicy(Qt.NoFocus)
        self.side_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.side_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        menu_items = [
            ("🏠  Dashboard", 0),
            ("🖥️  System", 1),
            ("🌐  Network", 2),
            ("⚡  Power", 3),
            ("🧹  Debloat", 4),
            ("🛡️  Security", 5),
            ("🧰  Maintenance", 6),
            ("📜  History", 7),
            ("⚙️  Settings", 8)
        ]

        for text, _ in menu_items:
            item = QListWidgetItem(text)
            self.side_list.addItem(item)

        sidebar_layout.addWidget(self.side_list)
        sidebar_layout.addStretch()

        bg_btn = QPushButton("📷 Background")
        bg_btn.clicked.connect(self.pick_background)
        sidebar_layout.addWidget(bg_btn)

        if not is_admin():
            admin_btn = QPushButton("🔐 Run as Admin")
            admin_btn.clicked.connect(lambda: relaunch_as_admin())
            sidebar_layout.addWidget(admin_btn)

        return sidebar_frame

    def create_pages(self):
        """Create all application pages"""
        self.stack.addWidget(self.create_dashboard())
        self.stack.addWidget(self.create_system_page())
        self.stack.addWidget(self.create_network_page())
        self.stack.addWidget(self.create_power_page())
        self.stack.addWidget(self.create_debloat_page())
        self.stack.addWidget(self.create_security_page())
        self.stack.addWidget(self.create_maintenance_page())
        self.stack.addWidget(self.create_history_page())
        self.stack.addWidget(self.create_settings_page())

    def create_scrollable_page(self, content_widget):
        """Wrap content in a scroll area that fills the right side"""
        scroll = QScrollArea()
        scroll.setWidget(content_widget)
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        return scroll

    def create_dashboard(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Welcome to Space Aim")
        title.setStyleSheet("font-size: 32px; font-weight: 900; color: #fff; margin-bottom: 8px;")
        layout.addWidget(title)

        subtitle = QLabel("Advanced Windows Optimization • Low Latency • FPS Boost • Automatic Backups")
        subtitle.setStyleSheet("font-size: 14px; color: rgba(255,255,255,0.7); margin-bottom: 24px;")
        layout.addWidget(subtitle)

        actions_layout = QHBoxLayout()

        card1 = Card("Quick Actions", "Essential maintenance tasks")
        btn_restore = QPushButton("Create Restore Point")
        btn_restore.clicked.connect(self.create_restore_ui)
        btn_scan = QPushButton("Defender Quick Scan")
        btn_scan.clicked.connect(self.defender_quick_ui)
        card1.content_layout.addWidget(btn_restore)
        card1.content_layout.addWidget(btn_scan)
        actions_layout.addWidget(card1)

        card2 = Card("Appearance", "Customize interface")
        btn_bg = QPushButton("Change Background")
        btn_bg.clicked.connect(self.pick_background)
        card2.content_layout.addWidget(btn_bg)
        actions_layout.addWidget(card2)

        layout.addLayout(actions_layout)

        status_card = Card("System Status", "")
        status_text = f"Administrator: {'Yes' if is_admin() else 'No'}\n"
        status_text += f"Backups stored: {BACKUP_DIR}\n"
        status_text += f"History log: {HISTORY_FILE}"
        status_label = QLabel(status_text)
        status_label.setStyleSheet("color: rgba(255,255,255,0.8); font-family: 'Consolas', monospace;")
        status_card.content_layout.addWidget(status_label)
        layout.addWidget(status_card)

        layout.addStretch()
        return self.create_scrollable_page(page)

    def create_system_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)

        card = Card("System Optimizations", "Performance, FPS boost, and latency reduction tweaks")

        self.sys_checks = [
            QCheckBox("Disable Telemetry (Conservative)"),
            QCheckBox("Disable SysMain (Superfetch)"),
            QCheckBox("Disable Windows Search Indexer"),
            QCheckBox("Disable Background Apps"),
            QCheckBox("Disable Game DVR"),
            QCheckBox("Disable Hibernation"),
            QCheckBox("Disable Windows Animations (FPS Boost)"),
            QCheckBox("Enable GPU Hardware Scheduling (Lower Latency)"),
            QCheckBox("Enable Windows Game Mode"),
            QCheckBox("Disable Fullscreen Optimizations"),
            QCheckBox("Optimize Timer Resolution (Lower Latency)"),
            QCheckBox("Disable Cortana"),
            QCheckBox("Disable Windows Tips"),
            QCheckBox("Optimize CPU Priority for Programs"),
            QCheckBox("Reduce Menu Show Delay"),
            QCheckBox("Disable Sticky Keys"),
            QCheckBox("Optimize SSD Performance"),
            QCheckBox("Apply BCDEdit Tweaks (Requires Restart)"),
        ]

        for cb in self.sys_checks:
            card.content_layout.addWidget(cb)

        layout.addWidget(card)

        btn = QPushButton("Apply Selected Tweaks")
        btn.clicked.connect(partial(self.apply_tweaks, [
            (self.sys_checks[0], tweak_disable_telemetry),
            (self.sys_checks[1], tweak_disable_sysmain),
            (self.sys_checks[2], tweak_disable_search_index),
            (self.sys_checks[3], tweak_disable_background_apps),
            (self.sys_checks[4], tweak_disable_gamedvr),
            (self.sys_checks[5], tweak_disable_hibernation),
            (self.sys_checks[6], tweak_disable_windows_animations),
            (self.sys_checks[7], tweak_gpu_hardware_scheduling),
            (self.sys_checks[8], tweak_game_mode),
            (self.sys_checks[9], tweak_disable_fullscreen_optimization),
            (self.sys_checks[10], tweak_timer_resolution),
            (self.sys_checks[11], tweak_disable_cortana),
            (self.sys_checks[12], tweak_disable_windows_tips),
            (self.sys_checks[13], tweak_priority_separation),
            (self.sys_checks[14], tweak_reduce_menu_delay),
            (self.sys_checks[15], tweak_disable_sticky_keys),
            (self.sys_checks[16], tweak_optimize_ssd),
            (self.sys_checks[17], tweak_bcdedit_tweaks),
        ]))
        layout.addWidget(btn)
        layout.addStretch()

        return self.create_scrollable_page(page)

    def create_network_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)

        card = Card("Network Optimizations", "TCP/IP, latency, and network performance tweaks")

        self.net_checks = [
            QCheckBox("Optimize TCP ACK Frequency"),
            QCheckBox("Disable Nagle Algorithm (Lower Latency)"),
            QCheckBox("Disable TCP Autotuning"),
            QCheckBox("Flush DNS Cache"),
            QCheckBox("Reset Winsock"),
            QCheckBox("Disable Delivery Optimization"),
            QCheckBox("Disable Network Throttling (Gaming)"),
            QCheckBox("Optimize TCP Offloading"),
        ]

        for cb in self.net_checks:
            card.content_layout.addWidget(cb)

        layout.addWidget(card)

        btn = QPushButton("Apply Selected Tweaks")
        btn.clicked.connect(partial(self.apply_tweaks, [
            (self.net_checks[0], tweak_tcp_ack_frequency),
            (self.net_checks[1], tweak_disable_nagle),
            (self.net_checks[2], tweak_disable_autotuning),
            (self.net_checks[3], tweak_flush_dns),
            (self.net_checks[4], tweak_reset_winsock),
            (self.net_checks[5], tweak_disable_delivery_optimization),
            (self.net_checks[6], tweak_network_throttling),
            (self.net_checks[7], tweak_tcp_offloading),
        ]))
        layout.addWidget(btn)
        layout.addStretch()

        return self.create_scrollable_page(page)

    def create_power_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)

        card = Card("Power Management", "Maximum performance power settings")

        self.power_checks = [
            QCheckBox("Enable High Performance Power Plan"),
            QCheckBox("Disable USB Selective Suspend"),
            QCheckBox("Disable Sleep Mode (AC Power)"),
            QCheckBox("Disable CPU Core Parking (Max Performance)"),
            QCheckBox("Optimize Multimedia/Gaming Thread Priority"),
        ]

        for cb in self.power_checks:
            card.content_layout.addWidget(cb)

        layout.addWidget(card)

        btn = QPushButton("Apply Selected Tweaks")
        btn.clicked.connect(partial(self.apply_tweaks, [
            (self.power_checks[0], tweak_set_power_high_performance),
            (self.power_checks[1], tweak_disable_usb_selective_suspend),
            (self.power_checks[2], tweak_disable_sleep),
            (self.power_checks[3], tweak_disable_core_parking),
            (self.power_checks[4], tweak_multimedia_priority),
        ]))
        layout.addWidget(btn)
        layout.addStretch()

        return self.create_scrollable_page(page)

    def create_debloat_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)

        card = Card("Remove Bloatware", "Safely remove unwanted Windows apps (creates backups)")

        self.debloat_checks = [
            QCheckBox("Remove Xbox Packages"),
            QCheckBox("Remove Candy Crush & Games"),
            QCheckBox("Remove Microsoft Solitaire"),
            QCheckBox("Uninstall OneDrive"),
            QCheckBox("Remove Mixed Reality Apps")
        ]

        for cb in self.debloat_checks:
            card.content_layout.addWidget(cb)

        layout.addWidget(card)

        btn = QPushButton("Remove Selected Apps")
        btn.clicked.connect(partial(self.apply_debloat, [
            (self.debloat_checks[0], lambda: remove_appx("Xbox")),
            (self.debloat_checks[1], lambda: remove_appx("Candy")),
            (self.debloat_checks[2], lambda: remove_appx("MicrosoftSolitaireCollection")),
            (self.debloat_checks[3], uninstall_onedrive),
            (self.debloat_checks[4], lambda: remove_appx("MixedReality")),
        ]))
        layout.addWidget(btn)
        layout.addStretch()

        return self.create_scrollable_page(page)

    def create_security_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)

        card = Card("Security Tools", "Windows Defender with MRT fallback")

        self.sec_checks = [
            QCheckBox("Quick Scan"),
            QCheckBox("Full Scan (takes longer)"),
            QCheckBox("Update Definitions")
        ]

        for cb in self.sec_checks:
            card.content_layout.addWidget(cb)

        # Info note about fallback behavior
        note = QLabel(defender_scan_help)
        note.setStyleSheet("color: rgba(245,245,245,0.6); font-size: 12px;")
        card.content_layout.addWidget(note)

        layout.addWidget(card)

        btn = QPushButton("Run Selected Actions")
        btn.clicked.connect(partial(self.apply_tweaks, [
            (self.sec_checks[0], defender_quick),
            (self.sec_checks[1], defender_full),
            (self.sec_checks[2], defender_update_signatures),
        ]))
        layout.addWidget(btn)
        layout.addStretch()

        return self.create_scrollable_page(page)

    def create_maintenance_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)

        card = Card("System Maintenance", "Cleanup and optimization")

        self.maint_checks = [
            QCheckBox("Create Restore Point"),
            QCheckBox("Clean Temporary Files"),
            QCheckBox("Clear Prefetch"),
            QCheckBox("Clear Windows Update Cache")
        ]

        for cb in self.maint_checks:
            card.content_layout.addWidget(cb)

        layout.addWidget(card)

        btn = QPushButton("Run Selected Tasks")
        btn.clicked.connect(partial(self.apply_tweaks, [
            (self.maint_checks[0], create_restore_point),
            (self.maint_checks[1], cleanup_temp_files),
            (self.maint_checks[2], cleanup_prefetch),
            (self.maint_checks[3], clear_windows_update_cache),
        ]))
        layout.addWidget(btn)
        layout.addStretch()

        return self.create_scrollable_page(page)

    def create_history_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Action History")
        title.setObjectName("title")
        layout.addWidget(title)

        self.history_text = QTextEdit()
        self.history_text.setReadOnly(True)
        layout.addWidget(self.history_text)

        btn = QPushButton("Refresh History")
        btn.clicked.connect(self.reload_history)
        layout.addWidget(btn)

        self.reload_history()

        return self.create_scrollable_page(page)

    def create_settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)

        card = Card("Appearance Settings", "Customize background and blur")

        blur_label = QLabel(f"Background Blur: {self.settings.get('blur_radius', 20)}")
        card.content_layout.addWidget(blur_label)

        blur_slider = QSlider(Qt.Horizontal)
        blur_slider.setMinimum(0)
        blur_slider.setMaximum(50)
        blur_slider.setValue(self.settings.get("blur_radius", 20))
        blur_slider.valueChanged.connect(lambda v: self.update_blur(v, blur_label))
        card.content_layout.addWidget(blur_slider)

        tint_btn = QPushButton("Choose Tint Color")
        tint_btn.clicked.connect(self.pick_tint)
        card.content_layout.addWidget(tint_btn)

        layout.addWidget(card)

        info_card = Card("About", "Space Aim Enhanced Edition")
        info_text = QLabel(
            f"Version: 2.0\n"
            f"App Directory: {APP_DIR}\n"
            f"Backup Directory: {BACKUP_DIR}\n\n"
            f"Features:\n"
            f"• macOS-style controls\n"
            f"• Automatic backups\n"
            f"• Safe system tweaks\n"
            f"• Windows Defender integration (with MRT fallback)\n"
            f"• FPS boost & latency reduction\n"
            f"• Gaming optimizations"
        )
        info_text.setStyleSheet("color: rgba(255,255,255,0.8); line-height: 1.6;")
        info_card.content_layout.addWidget(info_text)
        layout.addWidget(info_card)

        layout.addStretch()

        return self.create_scrollable_page(page)

    def pick_background(self):
        fn, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Background Image",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if fn:
            self.settings["background_path"] = fn
            self.settings.setdefault("blur_radius", 20)
            self.settings.setdefault("tint_rgba", (180,0,0,70))
            self.background_widget.set_background(
                fn,
                blur_radius=self.settings["blur_radius"],
                tint_rgba=tuple(self.settings["tint_rgba"])
            )
            self.save_settings()
            QMessageBox.information(self, "Success", "Background applied!")

    def pick_tint(self):
        current = QColor(*self.settings.get("tint_rgba", (180,0,0,70)))
        color = QColorDialog.getColor(current, self, "Choose Tint Color")
        if color.isValid():
            rgba = (color.red(), color.green(), color.blue(), color.alpha())
            self.settings["tint_rgba"] = rgba
            self.background_widget.tint_color = QColor(*rgba)
            self.background_widget.update()
            self.save_settings()

    def update_blur(self, value, label):
        label.setText(f"Background Blur: {value}")
        self.settings["blur_radius"] = value
        self.background_widget.blur_effect.setBlurRadius(value)
        self.background_widget.refresh_pixmap()
        self.save_settings()

    def reload_history(self):
        if HISTORY_FILE.exists():
            text = HISTORY_FILE.read_text(encoding="utf-8")
        else:
            text = "No history yet."
        self.history_text.setPlainText(text)

    def create_restore_ui(self):
        if not is_admin():
            QMessageBox.warning(self, "Admin Required", "Administrator privileges needed.")
            return
        ok, msg = create_restore_point()
        QMessageBox.information(self, "Restore Point", msg)
        self.reload_history()

    def defender_quick_ui(self):
        if not is_admin():
            QMessageBox.warning(self, "Admin Required", "Administrator privileges needed.")
            return
        ok, msg = defender_quick()
        QMessageBox.information(self, "Defender Scan", msg)
        self.reload_history()

    def apply_tweaks(self, pairs):
        if not is_admin():
            reply = QMessageBox.question(
                self,
                "Admin Required",
                "Administrator privileges needed. Relaunch as admin?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                relaunch_as_admin()
            return

        results = []
        for cb, fn in pairs:
            if cb.isChecked():
                try:
                    ok, msg = fn()
                    results.append(f"{'✓' if ok else '✗'} {msg}")
                except Exception as e:
                    results.append(f"✗ Error: {str(e)}")

        if results:
            QMessageBox.information(self, "Results", "\n".join(results))
        else:
            QMessageBox.information(self, "Info", "No items selected")

        self.reload_history()

    def apply_debloat(self, pairs):
        if not is_admin():
            reply = QMessageBox.question(
                self,
                "Admin Required",
                "Debloat requires Administrator. Relaunch as admin?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                relaunch_as_admin()
            return

        confirm = QMessageBox.question(
            self,
            "Confirm",
            "Remove selected apps? Backups will be created automatically.",
            QMessageBox.Yes | QMessageBox.No
        )

        if confirm != QMessageBox.Yes:
            return

        results = []
        for cb, fn in pairs:
            if cb.isChecked():
                try:
                    ok, msg = fn()
                    results.append(f"{'✓' if ok else '✗'} {msg}")
                except Exception as e:
                    results.append(f"✗ Error: {str(e)}")

        if results:
            QMessageBox.information(self, "Debloat Results", "\n".join(results))
        else:
            QMessageBox.information(self, "Info", "No items selected")

        self.reload_history()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.background_widget.setGeometry(self.rect())
        self.size_grip.move(self.width() - 16, self.height() - 16)

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(12, 12, 12))
    palette.setColor(QPalette.WindowText, QColor(245, 245, 245))
    app.setPalette(palette)

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
