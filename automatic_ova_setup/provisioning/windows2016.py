import base64
import shutil
from pathlib import Path

from .download import create_iso


def _unattend_password_value(password: str, suffix: str) -> str:
    """Windows unattend.xml wants passwords as base64(UTF-16LE(password + suffix))."""
    return base64.b64encode((password + suffix).encode("utf-16-le")).decode("ascii")


def generate_setup_script(vm_dir: Path):
    """First-boot script"""
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

    setup_script_path = vm_dir / "setup.ps1"
    with open(setup_script_path, 'w', encoding='utf-8') as f:
        f.write(script_content)

    print(f"Generated setup script: {setup_script_path}")
    return setup_script_path


def generate_autounattend_xml(vm_dir: Path, computer_name: str, admin_username: str, admin_password: str):
    """Generate Windows unattended installation configuration file."""
    autologon_password_value = _unattend_password_value(admin_password, "Password")
    administrator_password_value = _unattend_password_value(admin_password, "AdministratorPassword")

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
                    <Value>{autologon_password_value}</Value>
                    <PlainText>false</PlainText>
                </Password>
                <Enabled>true</Enabled>
                <Username>{admin_username}</Username>
            </AutoLogon>
            <UserAccounts>
                <AdministratorPassword>
                    <Value>{administrator_password_value}</Value>
                    <PlainText>false</PlainText>
                </AdministratorPassword>
                <LocalAccounts>
                    <LocalAccount wcm:action="add">
                        <Password>
                            <Value>{autologon_password_value}</Value>
                            <PlainText>false</PlainText>
                        </Password>
                        <Group>Administrators</Group>
                        <Name>{admin_username}</Name>
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
            <ComputerName>{computer_name}</ComputerName>
        </component>
    </settings>
</unattend>
"""

    autounattend_path = vm_dir / "autounattend.xml"
    with open(autounattend_path, 'w', encoding='utf-8') as f:
        f.write(xml_content)

    print(f"Generated autounattend.xml: {autounattend_path}")
    return autounattend_path


def create_autounattend_iso(vm_dir: Path, iso_path: Path, autounattend_path: Path, setup_script_path: Path):
    """Create bootable-data ISO with autounattend.xml and setup script."""
    if iso_path.exists():
        iso_path.unlink()

    temp_dir = vm_dir / "iso_temp"
    temp_dir.mkdir(exist_ok=True)

    shutil.copy(autounattend_path, temp_dir / "autounattend.xml")
    shutil.copy(setup_script_path, temp_dir / "setup.ps1")

    try:
        create_iso(temp_dir, iso_path)
        print(f"Created autounattend ISO: {iso_path}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
