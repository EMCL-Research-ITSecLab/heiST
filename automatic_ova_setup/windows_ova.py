import sys
import time
import socket
import shutil
import random
import subprocess
from pathlib import Path

VM_ID = 200
VM_NAME = "windows-server-2016"
VM_PASSWORD = "Admin123"
VM_MEMORY = 4096
VM_CPUS = 2
VM_DISK_SIZE_MB = 32 * 1024

SSH_HOST_PORT = random.randint(20000, 60000)
WORKING_DIR = Path(__file__).resolve().parent / "vm-build"
ISO_DIR = WORKING_DIR / "iso"
VM_DIR = WORKING_DIR / VM_NAME
OVA_OUTPUT_DIR = WORKING_DIR / "ova"
OVA_PATH = OVA_OUTPUT_DIR / f"{VM_NAME}.ova"

WINDOWS_ISO_URL = "https://go.microsoft.com/fwlink/p/?LinkID=2195174&clcid=0x409&culture=en-us&country=US"
VIRTIO_ISO_URL = "https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/archive-virtio/virtio-win-0.1.285-1/virtio-win-0.1.285.iso"

WINDOWS_ISO_NAME = "windows_server_2016.iso"
VIRTIO_ISO_NAME = "virtio-win-0.1.285.iso"
AUTOUNATTEND_ISO_NAME = f"autounattend-{VM_ID}.iso"

WINDOWS_ISO = ISO_DIR / WINDOWS_ISO_NAME
VIRTIO_ISO = ISO_DIR / VIRTIO_ISO_NAME
AUTOUNATTEND_ISO = ISO_DIR / AUTOUNATTEND_ISO_NAME

DISK_PATH = VM_DIR / f"{VM_NAME}.vdi"

VBOXMANAGE = shutil.which("VBoxManage") or shutil.which("vboxmanage") or "VBoxManage"


def run_command(cmd, check=True, wait_time=0, capture=False):
    """Run a shell command, printing it first."""
    print(f"$ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, capture_output=capture, text=True)
    if wait_time:
        time.sleep(wait_time)
    if check and result.returncode != 0:
        stderr = result.stderr if capture else "(see output above)"
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(str(c) for c in cmd)}\n{stderr}")
    return result


def download_file(url, dest: Path, label: str):
    if dest.exists():
        print(f"{label} already downloaded: {dest}")
        return
    print(f"Downloading {label} -> {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    run_command(["curl", "-L", "--fail", "-o", str(tmp), url])
    tmp.rename(dest)
    print(f"Downloaded {label}")


def create_iso(src_dir: Path, iso_path: Path):
    """Build a small ISO (autounattend + setup.ps1) using genisoimage/xorriso."""
    tool = shutil.which("genisoimage") or shutil.which("mkisofs") or shutil.which("xorriso")
    if tool is None:
        raise RuntimeError(
            "Need genisoimage, mkisofs, or xorriso installed on the host "
            "(e.g. `apt install genisoimage`) to build the autounattend ISO."
        )
    if "xorriso" in tool:
        cmd = [tool, "-as", "genisoimage", "-J", "-R", "-o", str(iso_path), str(src_dir)]
    else:
        cmd = [tool, "-J", "-R", "-o", str(iso_path), str(src_dir)]
    run_command(cmd)


def generate_setup_script():
    """Generate PowerShell setup script for first boot configuration."""
    script_content = """$LogFile = "C:\\Windows\\Temp\\setup.log"
$ErrorActionPreference = "Continue"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] [$Level] $Message"
    Write-Host $logMessage
    Add-Content -Path $LogFile -Value $logMessage
}

Write-Log "Windows Server 2016 Setup START" "INFO"

Start-Sleep -Seconds 10

Write-Log "Testing network connectivity..." "INFO"
$retries = 0
$maxRetries = 10
$connected = $false

while ($retries -lt $maxRetries) {
    try {
        $testConnection = Test-NetConnection -ComputerName github.com -Port 443 -InformationLevel Quiet -WarningAction SilentlyContinue
        if ($testConnection) {
            Write-Log "Network connectivity confirmed" "INFO"
            $connected = $true
            break
        }
    } catch {
        Write-Log "Connection test failed: $_" "WARN"
    }

    $retries++
    Write-Log "Network not ready, retry $retries/$maxRetries" "WARN"
    Start-Sleep -Seconds 5
}

if (-not $connected) {
    Write-Log "Failed to establish network connectivity after $maxRetries attempts" "ERROR"
}

Write-Log "Enabling TLS 1.2" "INFO"
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Write-Log "TLS 1.2 enabled" "INFO"
} catch {
    Write-Log "Failed to enable TLS 1.2: $_" "ERROR"
}

Write-Log "Creating temp directory" "INFO"
try {
    $tempPath = "C:\\temp"
    if (-not (Test-Path $tempPath)) {
        New-Item -Path $tempPath -ItemType Directory -Force | Out-Null
    }
    Write-Log "Created C:\\temp" "INFO"
} catch {
    Write-Log "Failed to create C:\\temp: $_" "ERROR"
}

Write-Log "Installing OpenSSH" "INFO"
try {
    Set-Location "C:\\temp"

    Write-Log "Downloading OpenSSH" "INFO"
    $opensshUrl = "https://github.com/PowerShell/Win32-OpenSSH/releases/download/v9.5.0.0p1-Beta/OpenSSH-Win64.zip"
    $opensshZip = "C:\\temp\\OpenSSH-Win64.zip"
    Invoke-WebRequest -Uri $opensshUrl -OutFile $opensshZip -UseBasicParsing
    Write-Log "OpenSSH downloaded" "INFO"

    Write-Log "Extracting OpenSSH" "INFO"
    $opensshDest = "C:\\Program Files\\OpenSSH"
    if (Get-Command Expand-Archive -ErrorAction SilentlyContinue) {
        Expand-Archive -Path $opensshZip -DestinationPath $opensshDest -Force
    } else {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        if (Test-Path $opensshDest) {
            Remove-Item $opensshDest -Recurse -Force
        }
        [System.IO.Compression.ZipFile]::ExtractToDirectory(
            $opensshZip,
            $opensshDest
        )
    }
    Write-Log "OpenSSH extracted" "INFO"

    Write-Log "Installing OpenSSH service" "INFO"
    $opensshPath = "C:\\Program Files\\OpenSSH\\OpenSSH-Win64"
    Set-Location $opensshPath
    & ".\\install-sshd.ps1"
    Write-Log "OpenSSH service installed" "INFO"

    Write-Log "Starting OpenSSH service" "INFO"
    Set-Service -Name sshd -StartupType Automatic
    Start-Service sshd
    Write-Log "OpenSSH service started" "INFO"

    Write-Log "Configuring firewall for SSH" "INFO"
    New-NetFirewallRule -Name sshd -DisplayName "OpenSSH Server (sshd)" -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 -ErrorAction SilentlyContinue
    Write-Log "Firewall rule created" "INFO"

} catch {
    Write-Log "OpenSSH installation failed: $_" "ERROR"
    Write-Log "Exception: $($_.Exception.Message)" "ERROR"
}

Write-Log "Configuring TLS 1.2 in registry" "INFO"
try {
    reg add "HKLM\\SYSTEM\\CurrentControlSet\\Control\\SecurityProviders\\SCHANNEL\\Protocols\\TLS 1.2\\Server" /v Enabled /t REG_DWORD /d 1 /f | Out-Null
    reg add "HKLM\\SYSTEM\\CurrentControlSet\\Control\\SecurityProviders\\SCHANNEL\\Protocols\\TLS 1.2\\Server" /v DisabledByDefault /t REG_DWORD /d 0 /f | Out-Null
    reg add "HKLM\\SYSTEM\\CurrentControlSet\\Control\\SecurityProviders\\SCHANNEL\\Protocols\\TLS 1.2\\Client" /v Enabled /t REG_DWORD /d 1 /f | Out-Null
    reg add "HKLM\\SYSTEM\\CurrentControlSet\\Control\\SecurityProviders\\SCHANNEL\\Protocols\\TLS 1.2\\Client" /v DisabledByDefault /t REG_DWORD /d 0 /f | Out-Null
    reg add "HKLM\\SOFTWARE\\Microsoft\\.NETFramework\\v4.0.30319" /v SchUseStrongCrypto /t REG_DWORD /d 1 /f | Out-Null
    reg add "HKLM\\SOFTWARE\\Wow6432Node\\Microsoft\\.NETFramework\\v4.0.30319" /v SchUseStrongCrypto /t REG_DWORD /d 1 /f | Out-Null
    Write-Log "TLS 1.2 registry configured" "INFO"
} catch {
    Write-Log "Failed to configure TLS 1.2 registry: $_" "ERROR"
}

Write-Log "Configuring PowerShell alias" "INFO"
try {
    reg add "HKCU\\Software\\Microsoft\\Command Processor" /v AutoRun /t REG_SZ /d "doskey ps=powershell `$*" /f | Out-Null
    reg add "HKLM\\Software\\Microsoft\\Command Processor" /v AutoRun /t REG_SZ /d "doskey ps=powershell `$*" /f | Out-Null
    Write-Log "PowerShell alias configured" "INFO"
} catch {
    Write-Log "PowerShell alias configuration failed" "ERROR"
}

Write-Log "SETUP COMPLETE" "INFO"
Write-Log "Full log available at: $LogFile" "INFO"
"""

    setup_script_path = VM_DIR / "setup.ps1"
    with open(setup_script_path, 'w', encoding='utf-8') as f:
        f.write(script_content)

    print(f"Generated setup script: {setup_script_path}")
    return setup_script_path


def generate_autounattend_xml():
    """Generate Windows unattended installation configuration file."""
    xml_content = f"""<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend">
    <settings pass="windowsPE">
        <component name="Microsoft-Windows-International-Core-WinPE" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
            <SetupUILanguage>
                <UILanguage>en-US</UILanguage>
            </SetupUILanguage>
            <InputLocale>0407:00000407</InputLocale>
            <SystemLocale>en-US</SystemLocale>
            <UILanguage>en-US</UILanguage>
            <UILanguageFallback>en-US</UILanguageFallback>
            <UserLocale>en-US</UserLocale>
        </component>
	    <component name="Microsoft-Windows-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
            <DiskConfiguration>
                <Disk wcm:action="add">
                    <CreatePartitions>
                        <CreatePartition wcm:action="add">
                            <Order>1</Order>
                            <Size>500</Size>
                            <Type>Primary</Type>
                        </CreatePartition>
                        <CreatePartition wcm:action="add">
                            <Order>2</Order>
                            <Extend>true</Extend>
                            <Type>Primary</Type>
                        </CreatePartition>
                    </CreatePartitions>
                    <ModifyPartitions>
                        <ModifyPartition wcm:action="add">
                            <Order>1</Order>
                            <PartitionID>1</PartitionID>
                            <Active>true</Active>
                            <Format>NTFS</Format>
                            <Label>System Reserved</Label>
                        </ModifyPartition>
                        <ModifyPartition wcm:action="add">
                            <Order>2</Order>
                            <PartitionID>2</PartitionID>
                            <Format>NTFS</Format>
                            <Label>Windows</Label>
                        </ModifyPartition>
                    </ModifyPartitions>
                    <DiskID>0</DiskID>
                    <WillWipeDisk>true</WillWipeDisk>
                </Disk>
            </DiskConfiguration>
            <ImageInstall>
                <OSImage>
                    <InstallFrom>
                        <MetaData wcm:action="add">
                            <Key>/IMAGE/NAME</Key>
                            <Value>Windows Server 2016 SERVERSTANDARDCORE</Value>
                        </MetaData>
                    </InstallFrom>
                    <InstallTo>
                        <DiskID>0</DiskID>
                        <PartitionID>2</PartitionID>
                    </InstallTo>
                    <WillShowUI>OnError</WillShowUI>
                </OSImage>
            </ImageInstall>
            <UserData>
                <AcceptEula>true</AcceptEula>
            </UserData>
        </component>
        <component name="Microsoft-Windows-PnpCustomizationsWinPE" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
            <DriverPaths>
                <PathAndCredentials wcm:action="add" wcm:keyValue="1">
                    <Path>D:\\viostor\\2k16\\amd64</Path>
                </PathAndCredentials>
                <PathAndCredentials wcm:action="add" wcm:keyValue="2">
                    <Path>D:\\NetKVM\\2k16\\amd64</Path>
                </PathAndCredentials>
                <PathAndCredentials wcm:action="add" wcm:keyValue="3">
                    <Path>D:\\vioscsi\\2k16\\amd64</Path>
                </PathAndCredentials>
                <PathAndCredentials wcm:action="add" wcm:keyValue="4">
                    <Path>D:\\amd64\\2k16</Path>
                </PathAndCredentials>
            </DriverPaths>
        </component>
    </settings>
    <settings pass="oobeSystem">
        <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
            <AutoLogon>
                <Password>
                    <Value>QQBkAG0AaQBuADEAMgAzAFAAYQBzAHMAdwBvAHIAZAA=</Value>
                    <PlainText>false</PlainText>
                </Password>
                <Enabled>true</Enabled>
                <Username>ctf_admin</Username>
            </AutoLogon>
            <UserAccounts>
                <AdministratorPassword>
                    <Value>QQBkAG0AaQBuADEAMgAzAEEAZABtAGkAbgBpAHMAdAByAGEAdABvAHIAUABhAHMAcwB3AG8AcgBkAA==</Value>
                    <PlainText>false</PlainText>
                </AdministratorPassword>
                <LocalAccounts>
                    <LocalAccount wcm:action="add">
                        <Password>
                            <Value>QQBkAG0AaQBuADEAMgAzAFAAYQBzAHMAdwBvAHIAZAA=</Value>
                            <PlainText>false</PlainText>
                        </Password>
                        <Group>Administrators</Group>
                        <Name>ctf_admin</Name>
                    </LocalAccount>
                </LocalAccounts>
            </UserAccounts>
            <OOBE>
                <HideEULAPage>true</HideEULAPage>
                <HideLocalAccountScreen>true</HideLocalAccountScreen>
                <HideOEMRegistrationScreen>true</HideOEMRegistrationScreen>
                <HideOnlineAccountScreens>true</HideOnlineAccountScreens>
                <HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>
                <ProtectYourPC>3</ProtectYourPC>
            </OOBE>
            <FirstLogonCommands>
                <SynchronousCommand wcm:action="add">
                    <Order>1</Order>
                    <CommandLine>cmd.exe /c for %D in (D E F G) do if exist %D:\\virtio-win-guest-tools.exe %D:\\virtio-win-guest-tools.exe /quiet /norestart</CommandLine>
                    <Description>Install VirtIO Guest Tools (drivers + qemu-ga)</Description>
                    <RequiresUserInput>false</RequiresUserInput>
                </SynchronousCommand>
                <SynchronousCommand wcm:action="add">
                    <Order>2</Order>
                    <CommandLine>powershell.exe -ExecutionPolicy Bypass -Command &quot;Start-Sleep -Seconds 15&quot;</CommandLine>
                    <Description>Wait for VirtIO tools</Description>
                    <RequiresUserInput>false</RequiresUserInput>
                </SynchronousCommand>
                <SynchronousCommand wcm:action="add">
                    <Order>3</Order>
                    <CommandLine>cmd.exe /c for %D in (D E F G) do if exist %D:\\setup.ps1 powershell.exe -ExecutionPolicy Bypass -File %D:\\setup.ps1</CommandLine>
                    <Description>Run setup script</Description>
                    <RequiresUserInput>false</RequiresUserInput>
                </SynchronousCommand>
            </FirstLogonCommands>
        </component>
    </settings>
    <settings pass="specialize">
        <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
            <ComputerName>windows-2016</ComputerName>
        </component>
    </settings>
</unattend>
"""

    autounattend_path = VM_DIR / "autounattend.xml"
    with open(autounattend_path, 'w', encoding='utf-8') as f:
        f.write(xml_content)

    print(f"Generated autounattend.xml: {autounattend_path}")
    return autounattend_path


def create_autounattend_iso(autounattend_path, setup_script_path):
    """Create bootable-data ISO with autounattend.xml and setup script."""
    if AUTOUNATTEND_ISO.exists():
        AUTOUNATTEND_ISO.unlink()

    temp_dir = VM_DIR / "iso_temp"
    temp_dir.mkdir(exist_ok=True)

    shutil.copy(autounattend_path, temp_dir / "autounattend.xml")
    shutil.copy(setup_script_path, temp_dir / "setup.ps1")

    try:
        create_iso(temp_dir, AUTOUNATTEND_ISO)
        print(f"Created autounattend ISO: {AUTOUNATTEND_ISO}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def vbox_vm_exists(name):
    result = run_command([VBOXMANAGE, "list", "vms"], capture=True, check=False)
    return f'"{name}"' in result.stdout


def vbox_vm_state(name):
    result = run_command([VBOXMANAGE, "showvminfo", name, "--machinereadable"], capture=True, check=False)
    for line in result.stdout.splitlines():
        if line.startswith("VMState="):
            return line.split("=", 1)[1].strip('"')
    return "unknown"


def vbox_delete_vm(name):
    print(f"VM {name} already exists. Deleting...")
    run_command([VBOXMANAGE, "controlvm", name, "poweroff"], check=False)
    time.sleep(3)
    run_command([VBOXMANAGE, "unregistervm", name, "--delete"], check=False)


def create_virtualbox_vm():
    """Create and configure the VirtualBox VM used to run the install."""
    print("Creating VirtualBox VM...")

    if vbox_vm_exists(VM_NAME):
        vbox_delete_vm(VM_NAME)

    VM_DIR.mkdir(parents=True, exist_ok=True)

    run_command([
        VBOXMANAGE, "createvm",
        "--name", VM_NAME,
        "--ostype", "Windows2016_64",
        "--basefolder", str(WORKING_DIR),
        "--register",
    ])

    run_command([
        VBOXMANAGE, "modifyvm", VM_NAME,
        "--memory", str(VM_MEMORY),
        "--cpus", str(VM_CPUS),
        "--nic1", "nat",
        "--graphicscontroller", "vboxsvga",
        "--audio-driver", "none",
        "--boot1", "dvd",
        "--boot2", "disk",
        "--boot3", "none",
        "--boot4", "none",
    ])

    run_command([
        VBOXMANAGE, "modifyvm", VM_NAME,
        "--natpf1", f"guestssh,tcp,,{SSH_HOST_PORT},,22",
    ])

    run_command([
        VBOXMANAGE, "createmedium", "disk",
        "--filename", str(DISK_PATH),
        "--size", str(VM_DISK_SIZE_MB),
        "--format", "VDI",
    ])

    run_command([
        VBOXMANAGE, "storagectl", VM_NAME,
        "--name", "SATA Controller",
        "--add", "sata",
        "--controller", "IntelAhci",
        "--portcount", "4",
        "--bootable", "on",
    ])

    run_command([
        VBOXMANAGE, "storageattach", VM_NAME,
        "--storagectl", "SATA Controller",
        "--port", "0", "--device", "0",
        "--type", "hdd",
        "--medium", str(DISK_PATH),
    ])

    run_command([
        VBOXMANAGE, "storageattach", VM_NAME,
        "--storagectl", "SATA Controller",
        "--port", "1", "--device", "0",
        "--type", "dvddrive",
        "--medium", str(WINDOWS_ISO),
    ])

    run_command([
        VBOXMANAGE, "storageattach", VM_NAME,
        "--storagectl", "SATA Controller",
        "--port", "2", "--device", "0",
        "--type", "dvddrive",
        "--medium", str(VIRTIO_ISO),
    ])

    run_command([
        VBOXMANAGE, "storageattach", VM_NAME,
        "--storagectl", "SATA Controller",
        "--port", "3", "--device", "0",
        "--type", "dvddrive",
        "--medium", str(AUTOUNATTEND_ISO),
    ])

    print("VM configuration complete")


def start_vm_headless():
    print("Starting VM (headless)...")
    run_command([VBOXMANAGE, "startvm", VM_NAME, "--type", "headless"])


def wait_for_ssh(ip, port=22, timeout=3600, interval=10):
    print(f"Waiting for SSH on {ip}:{port} (timeout {timeout}s)...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((ip, port), timeout=5):
                print("SSH port is open")
                return True
        except OSError:
            time.sleep(interval)
    return False


def wait_for_setup_complete(ip, username, password, port=22, timeout=1800, interval=15):
    """
    Poll the guest over SSH for the 'SETUP COMPLETE' marker in setup.log."""
    try:
        import paramiko
    except ImportError:
        print("paramiko not installed - skipping active log check, "
              "sleeping a fixed 10 minutes as a grace period instead.")
        time.sleep(600)
        return True

    print("Polling setup.log over SSH for completion marker...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(ip, port=port, username=username, password=password, timeout=10)
            _, stdout, _ = client.exec_command(
                'powershell -Command "Get-Content C:\\Windows\\Temp\\setup.log -ErrorAction SilentlyContinue"'
            )
            log_content = stdout.read().decode(errors="ignore")
            client.close()
            if "SETUP COMPLETE" in log_content:
                print("Setup script reported completion")
                return True
        except Exception as e:
            print(f"SSH check not ready yet: {e}")
        time.sleep(interval)

    print("WARNING: timed out waiting for SETUP COMPLETE marker")
    return False


def shutdown_vm(name, timeout=300):
    print("Shutting down VM (ACPI power button)...")
    run_command([VBOXMANAGE, "controlvm", name, "acpipowerbutton"], check=False)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if vbox_vm_state(name) == "poweroff":
            print("VM powered off")
            return
        time.sleep(5)
    print("VM didn't shut down gracefully in time, forcing power off...")
    run_command([VBOXMANAGE, "controlvm", name, "poweroff"], check=False)
    time.sleep(5)


def detach_isos(name):
    """Detach the DVDs before export so the OVA doesn't carry the install ISOs."""
    for port in ("1", "2", "3"):
        run_command([
            VBOXMANAGE, "storageattach", name,
            "--storagectl", "SATA Controller",
            "--port", port, "--device", "0",
            "--type", "dvddrive",
            "--medium", "none",
        ], check=False)


def export_ova(name, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    print(f"Exporting {name} -> {output_path}")
    run_command([
        VBOXMANAGE, "export", name,
        "--output", str(output_path),
        "--ovf10",
        "--options", "nomacs",
    ])
    print(f"Export complete: {output_path}")


def main():
    if shutil.which(VBOXMANAGE) is None:
        print("ERROR: VBoxManage not found. Install VirtualBox on this host first.")
        sys.exit(1)

    print("=" * 60)
    print("Windows Server 2016 - Automated Setup (VirtualBox -> OVA)")
    print("=" * 60)
    print(f"VM name: {VM_NAME}")
    print(f"Password: {VM_PASSWORD}")
    print(f"SSH forwarded port (127.0.0.1): {SSH_HOST_PORT}")
    print(f"Output OVA: {OVA_PATH}")
    print("=" * 60)

    VM_DIR.mkdir(parents=True, exist_ok=True)
    ISO_DIR.mkdir(parents=True, exist_ok=True)

    download_file(WINDOWS_ISO_URL, WINDOWS_ISO, "Windows Server 2016 ISO")
    download_file(VIRTIO_ISO_URL, VIRTIO_ISO, "VirtIO drivers ISO")

    setup_script_path = generate_setup_script()
    autounattend_path = generate_autounattend_xml()
    create_autounattend_iso(autounattend_path, setup_script_path)

    create_virtualbox_vm()
    start_vm_headless()

    if not wait_for_ssh("127.0.0.1", port=SSH_HOST_PORT):
        print("ERROR: SSH never came up - check the install (e.g. VBoxManage --type gui, "
              "or screenshot via VBoxManage controlvm ... screenshotpng).")
        sys.exit(1)

    wait_for_setup_complete("127.0.0.1", "ctf_admin", VM_PASSWORD, port=SSH_HOST_PORT)

    shutdown_vm(VM_NAME)
    detach_isos(VM_NAME)
    export_ova(VM_NAME, OVA_PATH)

    print("\n" + "=" * 60)
    print("Setup Complete")
    print("=" * 60)
    print(f"OVA ready at: {OVA_PATH}")
    print(f"Username: Administrator / ctf_admin")
    print(f"Password: {VM_PASSWORD}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)