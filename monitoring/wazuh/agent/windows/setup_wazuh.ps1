<#
.SYNOPSIS
    Installs, registers, runs, and configures logging for the Wazuh agent.
#>

param(
    [string]$Manager = "",
    [string]$Name = $env:COMPUTERNAME,
    [string]$Password = "",
    [string]$WazuhVersion = "4.11.1",

    [bool]$UseSystemHealth = $true,
    [bool]$UsePowerShellLog = $true,
    [bool]$UseAdMonitoring,           # left unset -> auto-detect (DC = true, else false)

    [switch]$Install,
    [switch]$Register,
    [switch]$Run,
    [switch]$Reregister,
    [switch]$Yes,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

if ($Help) {
    Get-Help $MyInvocation.MyCommand.Path -Full
    exit 0
}

$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERROR: This script must be run as Administrator" -ForegroundColor Red
    exit 1
}

$LogDir            = "C:\ProgramData\WazuhSetup"
$LogFile           = Join-Path $LogDir "wazuh_setup.log"
$OssecDir          = "C:\Program Files (x86)\ossec-agent"
$OssecConfigPath   = Join-Path $OssecDir "ossec.conf"
$AgentAuthBin      = Join-Path $OssecDir "agent-auth.exe"
$ClientKeysPath    = Join-Path $OssecDir "client.keys"

if (-not (Test-Path $LogDir)) { New-Item -Path $LogDir -ItemType Directory -Force | Out-Null }

function print_info    { param([string]$msg) Write-Host "[Info]: $msg" -ForegroundColor Cyan;    Add-Content -Path $LogFile -Value "[Info]: $msg" }
function print_warning { param([string]$msg) Write-Host "[Warning]: $msg" -ForegroundColor Yellow; Add-Content -Path $LogFile -Value "[Warning]: $msg" }
function print_error   { param([string]$msg) Write-Host "[Error]: $msg" -ForegroundColor Red;     Add-Content -Path $LogFile -Value "[Error]: $msg" }

$Mode = "full"
if ($Install)    { $Mode = "install" }
if ($Register)    { $Mode = "register" }
if ($Run)        { $Mode = "run" }

if (($Mode -eq "register" -or $Reregister) -and (-not $Manager -or -not $Name)) {
    print_error "Registration requires -Manager and -Name"
    exit 1
}

function Get-PSMajorVersion {
    return $PSVersionTable.PSVersion.Major
}

function Test-IsDomainController {
    try {
        $domainRole = (Get-WmiObject Win32_ComputerSystem).DomainRole
        return ($domainRole -eq 4 -or $domainRole -eq 5)
    } catch {
        return $false
    }
}

$PSVersion = Get-PSMajorVersion
$IsDC = Test-IsDomainController

if (-not $PSBoundParameters.ContainsKey('UseAdMonitoring')) {
    $UseAdMonitoring = $IsDC
}

function Install-WazuhAgent {
    param(
        [string]$ManagerIp,
        [string]$AgentName,
        [string]$EnrollPassword,
        [string]$Version
    )

    print_info "Installing Wazuh Agent $Version..."
    print_info "  Manager: $ManagerIp"
    print_info "  Agent Name: $AgentName"

    $installerUrl  = "https://packages.wazuh.com/4.x/windows/wazuh-agent-$Version-1.msi"
    $installerPath = "$env:TEMP\wazuh-agent.msi"
    $msiLogPath    = Join-Path $LogDir "wazuh_msi.log"

    try {
        print_info "  Downloading installer..."
        print_info "  URL: $installerUrl"

        if ($PSVersion -eq 2) {
            $webClient = New-Object System.Net.WebClient
            $webClient.DownloadFile($installerUrl, $installerPath)
        }
        else {
            Invoke-WebRequest `
                -Uri $installerUrl `
                -OutFile $installerPath `
                -UseBasicParsing
        }

        if (-not (Test-Path $installerPath)) {
            throw "Wazuh MSI was not downloaded to $installerPath"
        }

        print_info "  MSI downloaded successfully."

        $arguments = "/i `"$installerPath`" /qn /l*v `"$msiLogPath`""

        if ($ManagerIp) {
            $arguments += " WAZUH_MANAGER=`"$ManagerIp`""
        }

        if ($AgentName) {
            $arguments += " WAZUH_AGENT_NAME=`"$AgentName`""
        }

        if ($EnrollPassword -ne "") {
            $arguments += " WAZUH_REGISTRATION_PASSWORD=`"$EnrollPassword`""
            print_info "  Using enrollment password"
        }

        print_info "  Running installer..."
        print_info "  MSI log: $msiLogPath"

        $process = Start-Process `
            msiexec.exe `
            -ArgumentList $arguments `
            -Wait `
            -NoNewWindow `
            -PassThru

        $exitCode = $process.ExitCode

        print_info "  MSI exit code: $exitCode"

        if ($exitCode -ne 0) {
            throw "Wazuh MSI installation failed with exit code $exitCode. Check $msiLogPath"
        }

        print_info "  MSI installation completed successfully."

        Remove-Item $installerPath -Force -ErrorAction SilentlyContinue

        $agentExe = Join-Path $OssecDir "wazuh-agent.exe"

        if (-not (Test-Path $agentExe)) {
            throw "MSI completed successfully but wazuh-agent.exe was not found at $agentExe"
        }

        print_info "  Found wazuh-agent.exe"

        if (-not (Ensure-WazuhService)) {
            throw "Wazuh agent files were installed but WazuhSvc could not be registered."
        }

        print_info "Wazuh agent installation completed successfully."
        print_info "WazuhSvc is available."
    }
    catch {
        print_error "Failed to install Wazuh agent: $_"

        if (Test-Path $msiLogPath) {
            print_error "Detailed MSI log available at:"
            print_error "  $msiLogPath"
        }

        Remove-Item $installerPath -Force -ErrorAction SilentlyContinue

        throw
    }
}

function Ensure-WazuhService {
    print_info "Checking Wazuh Windows service..."

    $service = Get-Service -Name "WazuhSvc" -ErrorAction SilentlyContinue

    if ($service) {
        print_info "WazuhSvc already exists. Status: $($service.Status)"
        return $true
    }

    print_warning "WazuhSvc does not exist."
    print_info "Attempting to register Wazuh service using wazuh-agent.exe..."

    $agentExe = Join-Path $OssecDir "wazuh-agent.exe"

    if (-not (Test-Path $agentExe)) {
        print_error "Cannot register WazuhSvc because wazuh-agent.exe was not found:"
        print_error "  $agentExe"
        return $false
    }

    try {
        Push-Location $OssecDir

        print_info "Executing: wazuh-agent.exe install-service"

        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $installOutput = & $agentExe install-service 2>&1
        }
        finally {
            $ErrorActionPreference = $prevEAP
        }

        foreach ($line in $installOutput) {
            if ($line -ne $null -and $line.ToString().Trim() -ne "") {
                print_info "  $($line.ToString())"
            }
        }

        $exitCode = $LASTEXITCODE

        Pop-Location

        if ($exitCode -ne 0) {
            print_error "wazuh-agent.exe install-service failed with exit code $exitCode"
            return $false
        }

        Start-Sleep -Milliseconds 500

        $service = Get-Service -Name "WazuhSvc" -ErrorAction SilentlyContinue

        if (-not $service) {
            print_error "install-service completed but WazuhSvc was not found."
            return $false
        }

        print_info "WazuhSvc successfully registered."
        return $true
    }
    catch {
        Pop-Location -ErrorAction SilentlyContinue
        print_error "Failed to register WazuhSvc: $_"
        return $false
    }
}

function Add-LocalfileIfMissing {
    param(
        [xml]$Config,
        [string]$MatchProperty,
        [string]$MatchValue,
        [System.Collections.IDictionary]$Elements   # ordered element-name -> value pairs
    )
    $existing = $Config.ossec_config.localfile | Where-Object { $_.$MatchProperty -eq $MatchValue }
    if ($existing) { return $false }

    $localfile = $Config.CreateElement("localfile")
    foreach ($key in $Elements.Keys) {
        $el = $Config.CreateElement($key)
        $el.InnerText = $Elements[$key]
        $localfile.AppendChild($el) | Out-Null
    }
    $Config.ossec_config.AppendChild($localfile) | Out-Null
    return $true
}

function Update-OssecConfig {
    param([string]$NewManager)

    if (-not (Test-Path $OssecConfigPath)) {
        print_error "Config file $OssecConfigPath not found!"
        return $false
    }
    if ($NewManager) {
        print_info "Updating manager address in ossec.conf..."
        (Get-Content $OssecConfigPath -Raw) -replace '<address>.*</address>', "<address>$NewManager</address>" |
            Set-Content -Path $OssecConfigPath
        print_info "Updated manager address to: $NewManager"
    }
    return $true
}

function Enable-SystemHealthMonitoring {
    print_info "Configuring system health monitoring..."

    $metricsScriptPath = Join-Path $OssecDir "wazuh-system-health.ps1"
    if ($PSVersion -eq 2) {
        $metricsScript = @'
$cpu = (Get-WmiObject Win32_Processor).LoadPercentage
$mem = Get-WmiObject Win32_OperatingSystem
$memUsedPct = [math]::Round((($mem.TotalVisibleMemorySize - $mem.FreePhysicalMemory) / $mem.TotalVisibleMemorySize) * 100, 2)
$disk = Get-WmiObject Win32_LogicalDisk -Filter "DeviceID='C:'"
$diskUsedPct = [math]::Round((($disk.Size - $disk.FreeSpace) / $disk.Size) * 100, 2)
Write-Output "$([math]::Round($cpu,2)) $memUsedPct $diskUsedPct"
'@
    } else {
        $metricsScript = @'
$cpu = (Get-Counter '\Processor(_Total)\% Processor Time').CounterSamples.CookedValue
$mem = Get-WmiObject Win32_OperatingSystem
$memUsedPct = [math]::Round((($mem.TotalVisibleMemorySize - $mem.FreePhysicalMemory) / $mem.TotalVisibleMemorySize) * 100, 2)
$disk = Get-WmiObject Win32_LogicalDisk -Filter "DeviceID='C:'" | Select-Object @{Name='UsedPct';Expression={[math]::Round((($_.Size - $_.FreeSpace) / $_.Size) * 100, 2)}}
Write-Output "$([math]::Round($cpu,2)) $memUsedPct $($disk.UsedPct)"
'@
    }
    Set-Content -Path $metricsScriptPath -Value $metricsScript -Force
    print_info "  Created $metricsScriptPath"

    $activeUserScriptPath = Join-Path $OssecDir "wazuh-active-users.ps1"
    $activeUserScript = @'
try {
    $users = quser 2>&1
    if ($LASTEXITCODE -eq 0) {
        ($users | Select-Object -Skip 1 | Measure-Object).Count
    } else {
        0
    }
} catch {
    0
}
'@
    Set-Content -Path $activeUserScriptPath -Value $activeUserScript -Force
    print_info "  Created $activeUserScriptPath"

    $activeUserDetailScriptPath = Join-Path $OssecDir "wazuh-active-users-detail.ps1"
    $activeUserDetailScript = @'
$logFile = "C:\Progra~2\ossec-agent\active-users.log"

function Write-LogLine {
    param([string]$line)
    try {
        $stream = [System.IO.File]::Open($logFile, [System.IO.FileMode]::Append, [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
        $writer = New-Object System.IO.StreamWriter($stream, (New-Object System.Text.UTF8Encoding($false)))
        $writer.WriteLine($line)
        $writer.Flush()
        $writer.Close()
        $stream.Close()
    } catch {}
}

try {
    $quserOutput = quser 2>&1
    $lines = $quserOutput | ForEach-Object { $_.ToString().Trim() } | Where-Object { $_ -ne "" }
    if ($lines.Count -lt 2) { exit 0 }

    $header = $lines[0]
    $colUSERNAME = 0
    $colSESSION  = $header.IndexOf("SESSIONNAME")
    $colID       = $header.IndexOf("ID")
    $colSTATE    = $header.IndexOf("STATE")
    $colIDLE     = $header.IndexOf("IDLE TIME")
    $colLOGON    = $header.IndexOf("LOGON TIME")

    $lines | Select-Object -Skip 1 | ForEach-Object {
        $line = $_
        if ($line.Length -lt $colSTATE) { return }

        $user    = $line.Substring($colUSERNAME, $colSESSION - $colUSERNAME).Trim().TrimStart('>')
        $session = $line.Substring($colSESSION,  $colID      - $colSESSION ).Trim()
        $id      = $line.Substring($colID,        $colSTATE   - $colID      ).Trim()
        $state   = $line.Substring($colSTATE,     $colIDLE    - $colSTATE   ).Trim()
        $idle    = $line.Substring($colIDLE,      $colLOGON   - $colIDLE    ).Trim()
        $logon   = $line.Substring($colLOGON).Trim()

        if (-not $session) { $session = "none" }

        try {
            $formats = @("M/d/yyyy h:mm tt", "M/d/yyyy hh:mm tt", "dd.MM.yyyy HH:mm:ss", "M/d/yyyy H:mm")
            $logonDateTime = $null
            foreach ($fmt in $formats) {
                try {
                    $logonDateTime = [datetime]::ParseExact($logon, $fmt, [System.Globalization.CultureInfo]::InvariantCulture)
                    break
                } catch {}
            }
            $logonStr = if ($logonDateTime) { $logonDateTime.ToString("MM/dd/yyyy HH:mm:ss") } else { $logon }
        } catch {
            $logonStr = $logon
        }

        Write-LogLine "user=$user session=$session id=$id state=$state idle=$idle logon=$logonStr"
    }
} catch {
    exit 0
}
'@
    Set-Content -Path $activeUserDetailScriptPath -Value $activeUserDetailScript -Force
    print_info "  Created $activeUserDetailScriptPath"

    try {
        $taskArg = '-NonInteractive -ExecutionPolicy Bypass -File "C:\Progra~2\ossec-agent\wazuh-active-users-detail.ps1"'
        $result = schtasks.exe /create /tn "WazuhActiveUsersDetail" `
            /tr "powershell.exe $taskArg" `
            /sc MINUTE /mo 1 `
            /ru SYSTEM /rl HIGHEST /f 2>&1
        if ($LASTEXITCODE -ne 0) { throw "schtasks exited $LASTEXITCODE : $result" }
        New-Item -Path "C:\Progra~2\ossec-agent\active-users.log" -ItemType File -Force -ErrorAction SilentlyContinue | Out-Null
        print_info "  Registered WazuhActiveUsersDetail scheduled task"
    } catch {
        print_warning "  Failed to register scheduled task: $_"
    }

    if (-not (Test-Path $OssecConfigPath)) {
        print_error "  Config file not found at $OssecConfigPath"
        return
    }

    [xml]$config = Get-Content $OssecConfigPath

    Add-LocalfileIfMissing -Config $config -MatchProperty "alias" -MatchValue "general_health_metrics" -Elements ([ordered]@{
        log_format = "full_command"
        command    = 'powershell.exe -ExecutionPolicy Bypass -File "C:\Program Files (x86)\ossec-agent\wazuh-system-health.ps1"'
        alias      = "general_health_metrics"
        out_format = '$(timestamp) $(hostname) general_health_check: $(log)'
        frequency  = "30"
    }) | Out-Null

    Add-LocalfileIfMissing -Config $config -MatchProperty "alias" -MatchValue "memory_metrics" -Elements ([ordered]@{
        log_format = "full_command"
        command    = 'powershell.exe -NoProfile -Command "$mem = Get-WmiObject Win32_OperatingSystem; $used = ($mem.TotalVisibleMemorySize - $mem.FreePhysicalMemory) * 1024; $free = $mem.FreePhysicalMemory * 1024; Write-Output \"$used $free\""'
        alias      = "memory_metrics"
        out_format = '$(timestamp) $(hostname) memory_check: $(log)'
        frequency  = "30"
    }) | Out-Null

    Add-LocalfileIfMissing -Config $config -MatchProperty "alias" -MatchValue "disk_metrics" -Elements ([ordered]@{
        log_format = "full_command"
        command    = 'powershell.exe -NoProfile -Command "$disk = Get-WmiObject Win32_LogicalDisk -Filter \"DeviceID=''C:''\"; $used = $disk.Size - $disk.FreeSpace; $free = $disk.FreeSpace; Write-Output \"$used $free\""'
        alias      = "disk_metrics"
        out_format = '$(timestamp) $(hostname) disk_check: $(log)'
        frequency  = "30"
    }) | Out-Null

    Add-LocalfileIfMissing -Config $config -MatchProperty "alias" -MatchValue "current_active_user_number" -Elements ([ordered]@{
        log_format = "full_command"
        command    = 'powershell.exe -ExecutionPolicy Bypass -File "C:\Program Files (x86)\ossec-agent\wazuh-active-users.ps1"'
        alias      = "current_active_user_number"
        out_format = '$(timestamp) $(hostname) current_active_user_number: $(log)'
        frequency  = "30"
    }) | Out-Null

    Add-LocalfileIfMissing -Config $config -MatchProperty "location" -MatchValue "C:\Progra~2\ossec-agent\active-users.log" -Elements ([ordered]@{
        location        = "C:\Progra~2\ossec-agent\active-users.log"
        log_format      = "syslog"
        out_format      = "current_active_users_win: `$(log)"
        ignore_binaries = "yes"
    }) | Out-Null

    $config.Save($OssecConfigPath)
    print_info "System health monitoring configured"
}

Add-Type @"
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

public class RegFlush {
    [DllImport("advapi32.dll", SetLastError = true)]
    public static extern int RegFlushKey(SafeRegistryHandle hKey);
}
"@

function Flush-RegistryKey {
    param(
        [string]$Path
    )

    $key = Get-Item $Path -ErrorAction Stop
    [RegFlush]::RegFlushKey($key.Handle) | Out-Null
}

function Enable-PowerShellLogging {
    print_info "Configuring PowerShell / process creation logging (PS $PSVersion detected)..."

    if ($PSVersion -ge 3) {
        $moduleLoggingPath = "HKLM:\SOFTWARE\Wow6432Node\Policies\Microsoft\Windows\PowerShell\ModuleLogging"
        $moduleNamesPath = "$moduleLoggingPath\ModuleNames"
        if (-not (Test-Path $moduleLoggingPath)) { New-Item -Path $moduleLoggingPath -Force | Out-Null }
        if (-not (Test-Path $moduleNamesPath))  { New-Item -Path $moduleNamesPath -Force | Out-Null }
        Set-ItemProperty -Path $moduleLoggingPath -Name "EnableModuleLogging" -Value 1 -Type DWord
        Set-ItemProperty -Path $moduleNamesPath -Name "*" -Value "*" -Type String

        Flush-RegistryKey -Path $moduleLoggingPath
        Flush-RegistryKey -Path $moduleNamesPath

        print_info "  Module Logging enabled (4103)"
    } else {
        print_warning "  Module Logging not available in PS $PSVersion (requires PS3+)"
    }

    $transcriptDir = "C:\ProgramData\Wazuh\pstranscripts"

    if ($PSVersion -ge 5) {
        $scriptBlockPath = "HKLM:\SOFTWARE\Wow6432Node\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging"
        if (-not (Test-Path $scriptBlockPath)) { New-Item -Path $scriptBlockPath -Force | Out-Null }
        Set-ItemProperty -Path $scriptBlockPath -Name "EnableScriptBlockLogging" -Value 1 -Type DWord

        Flush-RegistryKey -Path $scriptBlockPath

        print_info "  Script Block Logging enabled (4104)"
    } else {
        print_info "  PS $PSVersion < 5: falling back to profile-based transcription..."

        if (-not (Test-Path $transcriptDir)) {
            New-Item -Path $transcriptDir -ItemType Directory -Force | Out-Null
        }
        try {
            $acl = Get-Acl $transcriptDir
            $acl.SetAccessRuleProtection($true, $false)
            $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
                "Users", "CreateFiles, AppendData, ReadAndExecute, Traverse, ListDirectory", "None", "None", "Allow")))
            $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
                "CREATOR OWNER", "FullControl", "ContainerInherit,ObjectInherit", "InheritOnly", "Allow")))
            $acl.SetAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
                "SYSTEM", "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")))
            $acl.SetAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
                "Administrators", "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")))
            Set-Acl $transcriptDir $acl
        } catch {
            print_warning "  Could not set transcript directory permissions: $_"
        }

        if ($PSVersion -eq 2) {
            $profileCode = Get-TranscriptionProfilePs2
        } else {
            $profileCode = Get-TranscriptionProfilePs3Plus
        }

        $profilePaths = @("$env:windir\System32\WindowsPowerShell\v1.0\profile.ps1")
        if (Test-Path "$env:windir\SysWOW64\WindowsPowerShell\v1.0") {
            $profilePaths += "$env:windir\SysWOW64\WindowsPowerShell\v1.0\profile.ps1"
        }

        foreach ($profilePath in $profilePaths) {
            $profileDir = Split-Path $profilePath -Parent
            if (-not (Test-Path $profileDir)) { New-Item -Path $profileDir -ItemType Directory -Force | Out-Null }

            if (Test-Path $profilePath) {
                $existingContent = Get-Content $profilePath -Raw -ErrorAction SilentlyContinue
                if ($existingContent -match "PowerShell Transcription Profile") {
                    print_info "  Already configured: $profilePath"
                    continue
                }
                $backupPath = "$profilePath.backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
                Copy-Item $profilePath $backupPath -Force
                Add-Content -Path $profilePath -Value "`n$profileCode"
                print_info "  Updated: $profilePath (backed up to $backupPath)"
            } else {
                $profileCode | Out-File -FilePath $profilePath -Encoding ASCII -Force
                print_info "  Created: $profilePath"
            }
        }
    }

    print_info "  Enabling Process Creation with Command Line (4688)..."
    $auditPath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit"
    if (-not (Test-Path $auditPath)) { New-Item -Path $auditPath -Force | Out-Null }
    Set-ItemProperty -Path $auditPath -Name "ProcessCreationIncludeCmdLine_Enabled" -Value 1 -Type DWord
    auditpol /set /subcategory:"Process Creation" /success:enable /failure:enable | Out-Null
    auditpol /set /subcategory:"Logon" /success:enable /failure:enable | Out-Null
    print_info "  Process creation auditing enabled"

    if (-not (Test-Path $OssecConfigPath)) {
        print_error "  Config file not found at $OssecConfigPath"
        return
    }

    [xml]$config = Get-Content $OssecConfigPath

    Add-LocalfileIfMissing -Config $config -MatchProperty "location" -MatchValue "Security" -Elements ([ordered]@{
        location   = "Security"
        log_format = "eventchannel"
    }) | Out-Null

    if ($PSVersion -ge 3) {
        Add-LocalfileIfMissing -Config $config -MatchProperty "location" -MatchValue "Microsoft-Windows-PowerShell/Operational" -Elements ([ordered]@{
            location   = "Microsoft-Windows-PowerShell/Operational"
            log_format = "eventchannel"
        }) | Out-Null
    }

    if ($PSVersion -lt 5) {
        Add-LocalfileIfMissing -Config $config -MatchProperty "location" -MatchValue "C:\ProgramData\Wazuh\pstranscripts\*.txt" -Elements ([ordered]@{
            location        = "C:\ProgramData\Wazuh\pstranscripts\*.txt"
            log_format      = "syslog"
            out_format      = "PSTRANS `$(log)"
            ignore_binaries = "yes"
        }) | Out-Null
    }

    $config.Save($OssecConfigPath)
    print_info "PowerShell / process creation logging configured"
}

function Get-TranscriptionProfilePs2 {
    return @'
# PowerShell Transcription Profile
# Managed by Wazuh

if ($Host.Name -eq "ConsoleHost") {
    $machineAccount = "$env:COMPUTERNAME$"
    if ($env:USERNAME -eq $machineAccount) { return }

    $transcriptDir = "C:\ProgramData\Wazuh\pstranscripts"
    $maxTranscriptFiles = 10

    function Cleanup-TranscriptFiles {
        param([string]$dir, [int]$maxFiles)
        try {
            $currentUser = $env:USERNAME
            $files = Get-ChildItem -Path $dir -Filter "*_${currentUser}_*.txt" -ErrorAction SilentlyContinue |
                     Sort-Object LastWriteTime -Descending
            if ($files.Count -gt $maxFiles) {
                $files | Select-Object -Skip $maxFiles | ForEach-Object { Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue }
            }
        } catch {}
    }

    function Start-NewTranscript {
        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $transcriptFile = Join-Path $transcriptDir "${env:COMPUTERNAME}_${env:USERNAME}_${timestamp}_${PID}.txt"
        try {
            if (-not (Test-Path $transcriptDir)) { New-Item -Path $transcriptDir -ItemType Directory -Force -ErrorAction SilentlyContinue | Out-Null }
            Start-Transcript -Path $transcriptFile -Append -Force -ErrorAction SilentlyContinue | Out-Null
            $global:__CurrentTranscriptFile = $transcriptFile
            return $transcriptFile
        } catch { return $null }
    }

    function Stop-CurrentTranscript {
        try {
            $path = $global:__CurrentTranscriptFile
            Stop-Transcript -ErrorAction SilentlyContinue | Out-Null
            if ($path) { Convert-TranscriptToUtf8 -Path $path }
            $global:__CurrentTranscriptFile = $null
        } catch {}
    }

    function Convert-TranscriptToUtf8 {
        param([string]$Path)
        try {
            if (Test-Path $Path) {
                $content = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::Unicode)
                $content = [System.Text.RegularExpressions.Regex]::Replace($content, '(?m)^PS [^>\r\n]+>', "PS C:\Users\$($env:USERNAME)>")
                $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
                [System.IO.File]::WriteAllText($Path, $content, $utf8NoBom)
            }
        } catch {}
    }

    Start-NewTranscript | Out-Null
    Cleanup-TranscriptFiles -dir $transcriptDir -maxFiles $maxTranscriptFiles

    $global:__OriginalPrompt = $function:prompt
    $global:__CommandCount = 0

    function global:prompt {
        if ($global:__CommandCount -gt 0) {
            Stop-CurrentTranscript | Out-Null
            Start-NewTranscript | Out-Null
            Cleanup-TranscriptFiles -dir $transcriptDir -maxFiles $maxTranscriptFiles
        }
        $global:__CommandCount++
        if ($global:__OriginalPrompt) { & $global:__OriginalPrompt } else { "PS $($executionContext.SessionState.Path.CurrentLocation)$('>' * ($nestedPromptLevel + 1)) " }
    }
}
'@
}

function Get-TranscriptionProfilePs3Plus {
    return @'
# PowerShell Transcription Profile
# Managed by Wazuh

if ($Host.Name -eq "ConsoleHost") {
    $machineAccount = "$env:COMPUTERNAME$"
    if ($env:USERNAME -eq $machineAccount) { return }

    $transcriptDir = "C:\ProgramData\Wazuh\pstranscripts"
    $maxTranscriptFiles = 10

    function Cleanup-TranscriptFiles {
        param([string]$dir, [int]$maxFiles)
        try {
            $currentUser = $env:USERNAME
            $files = Get-ChildItem -Path $dir -Filter "*_${currentUser}_*.txt" -ErrorAction SilentlyContinue |
                     Sort-Object LastWriteTime -Descending
            if ($files.Count -gt $maxFiles) {
                $files | Select-Object -Skip $maxFiles | ForEach-Object { Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue }
            }
        } catch {}
    }

    function Start-NewTranscript {
        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
        $transcriptFile = Join-Path $transcriptDir "${env:COMPUTERNAME}_${env:USERNAME}_${timestamp}_${PID}.txt"
        try {
            if (-not (Test-Path $transcriptDir)) { New-Item -Path $transcriptDir -ItemType Directory -Force -ErrorAction SilentlyContinue | Out-Null }
            Start-Transcript -Path $transcriptFile -Append -Force -ErrorAction SilentlyContinue | Out-Null
            $global:__CurrentTranscriptFile = $transcriptFile
            return $transcriptFile
        } catch { return $null }
    }

    function Stop-CurrentTranscript {
        try {
            $path = $global:__CurrentTranscriptFile
            Stop-Transcript -ErrorAction SilentlyContinue | Out-Null
            if ($path) { Convert-TranscriptToUtf8 -Path $path }
            $global:__CurrentTranscriptFile = $null
        } catch {}
    }

    function Convert-TranscriptToUtf8 {
        param([string]$Path)
        try {
            if (Test-Path $Path) {
                $content = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::Unicode)
                $content = [System.Text.RegularExpressions.Regex]::Replace($content, '(?m)^PS [^>\r\n]+>', "PS C:\Users\$($env:USERNAME)>")
                [System.IO.File]::WriteAllText($Path, $content, [System.Text.UTF8Encoding]::new($false))
            }
        } catch {}
    }

    Start-NewTranscript | Out-Null
    Cleanup-TranscriptFiles -dir $transcriptDir -maxFiles $maxTranscriptFiles

    $global:__OriginalPrompt = $function:prompt
    $global:__CommandCount = 0

    function global:prompt {
        if ($global:__CommandCount -gt 0) {
            Stop-CurrentTranscript | Out-Null
            Start-NewTranscript | Out-Null
            Cleanup-TranscriptFiles -dir $transcriptDir -maxFiles $maxTranscriptFiles
        }
        $global:__CommandCount++
        if ($global:__OriginalPrompt) { & $global:__OriginalPrompt } else { "PS $($executionContext.SessionState.Path.CurrentLocation)$('>' * ($nestedPromptLevel + 1)) " }
    }

    Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
        try { Stop-Transcript -ErrorAction SilentlyContinue | Out-Null } catch {}
    } -ErrorAction SilentlyContinue | Out-Null
}
'@
}

function Enable-AdMonitoring {
    if (-not $IsDC) {
        print_warning "AD monitoring requested but this host is not a Domain Controller - skipping"
        return
    }

    print_info "Configuring AD monitoring (Domain Controller detected)..."
    try {
        Import-Module ActiveDirectory -ErrorAction Stop

        $adSubcategories = @(
            "User Account Management",      # 4720, 4722, 4725, 4726, 4740, 4767
            "Computer Account Management",  # 4741, 4743
            "Security Group Management",    # 4728, 4729, 4732, 4733, 4756, 4757
            "Directory Service Changes",    # 5136, 5137, 5141
            "Directory Service Access"
        )
        foreach ($sub in $adSubcategories) {
            $result = auditpol /set /subcategory:"$sub" /success:enable /failure:enable 2>&1
            if ($LASTEXITCODE -eq 0) { print_info "  [OK] $sub" } else { print_warning "  [WARN] $sub - $result" }
        }

        $domainDN = (Get-ADDomain).DistinguishedName
        $policiesPath = "AD:\CN=Policies,CN=System,$domainDN"
        $domainPath = "AD:\$domainDN"
        $everyone = [System.Security.Principal.SecurityIdentifier]"S-1-1-0"

        print_info "  Applying SACL to CN=Policies (GPO events)..."
        $acl = Get-Acl -Path $policiesPath -Audit
        $acl.AddAuditRule((New-Object System.DirectoryServices.ActiveDirectoryAuditRule(
            $everyone, [System.DirectoryServices.ActiveDirectoryRights]"CreateChild",
            [System.Security.AccessControl.AuditFlags]"Success", [System.DirectoryServices.ActiveDirectorySecurityInheritance]"All")))
        $acl.AddAuditRule((New-Object System.DirectoryServices.ActiveDirectoryAuditRule(
            $everyone, [System.DirectoryServices.ActiveDirectoryRights]"WriteProperty",
            [System.Security.AccessControl.AuditFlags]"Success", [System.DirectoryServices.ActiveDirectorySecurityInheritance]"Descendents")))
        $acl.AddAuditRule((New-Object System.DirectoryServices.ActiveDirectoryAuditRule(
            $everyone, [System.DirectoryServices.ActiveDirectoryRights]"Delete, DeleteTree",
            [System.Security.AccessControl.AuditFlags]"Success", [System.DirectoryServices.ActiveDirectorySecurityInheritance]"Children")))
        Set-Acl -Path $policiesPath -AclObject $acl
        print_info "  [OK] CN=Policies SACL applied (5136/5137/5141 for GPOs)"

        print_info "  Applying SACL to domain root (OU/object events)..."
        $acl = Get-Acl -Path $domainPath -Audit
        $acl.AddAuditRule((New-Object System.DirectoryServices.ActiveDirectoryAuditRule(
            $everyone, [System.DirectoryServices.ActiveDirectoryRights]"CreateChild, WriteProperty, DeleteChild",
            [System.Security.AccessControl.AuditFlags]"Success", [System.DirectoryServices.ActiveDirectorySecurityInheritance]"All")))
        $acl.AddAuditRule((New-Object System.DirectoryServices.ActiveDirectoryAuditRule(
            $everyone, [System.DirectoryServices.ActiveDirectoryRights]"Delete, DeleteTree",
            [System.Security.AccessControl.AuditFlags]"Success", [System.DirectoryServices.ActiveDirectorySecurityInheritance]"Children")))
        Set-Acl -Path $domainPath -AclObject $acl
        print_info "  [OK] Domain root SACL applied (5136/5137/5141 for OUs/objects)"

        gpupdate /force | Out-Null
        print_info "  [OK] Group Policy refreshed"
    }
    catch {
        print_error "  AD monitoring setup failed: $_"
        print_warning "  Continuing with rest of installation..."
    }
}

function Register-WazuhAgent {
    param([string]$ManagerIp, [string]$AgentName, [string]$EnrollPassword)

    if (-not (Test-Path $AgentAuthBin)) {
        print_error "agent-auth.exe not found at $AgentAuthBin"
        return $false
    }

    print_info "Registering agent with manager..."
    print_info "Executing: agent-auth.exe -m $ManagerIp -A $AgentName"

    if ($EnrollPassword -ne "") {
        & $AgentAuthBin -m $ManagerIp -A $AgentName -P $EnrollPassword
    } else {
        & $AgentAuthBin -m $ManagerIp -A $AgentName
    }

    if ($LASTEXITCODE -eq 0) {
        print_info "Agent successfully registered!"
        return $true
    } else {
        print_error "Agent registration failed!"
        print_info "Troubleshooting:"
        print_info "  - Check if manager is reachable: Test-NetConnection $ManagerIp -Port 1515"
        print_info "  - Check manager logs: /var/ossec/logs/ossec.log (on the manager)"
        return $false
    }
}

function Reregister-WazuhAgent {
    param([string]$ManagerIp, [string]$AgentName, [string]$EnrollPassword)

    print_warning "Re-registering agent (removing old keys)..."

    try { Stop-Service WazuhSvc -ErrorAction SilentlyContinue } catch {}

    if (Test-Path $ClientKeysPath) {
        $backupPath = "$ClientKeysPath.backup.$(Get-Date -Format 'yyyyMMdd_HHmmss')"
        Copy-Item $ClientKeysPath $backupPath -Force
        Remove-Item $ClientKeysPath -Force
        print_info "Old client.keys backed up to $backupPath and removed"
    }

    return (Register-WazuhAgent -ManagerIp $ManagerIp -AgentName $AgentName -EnrollPassword $EnrollPassword)
}

print_info "Mode: $Mode"
if ($Reregister) { print_info "Reregister: enabled" }

if ($Mode -ne "install" -and $Mode -ne "run") {
    print_info "Agent Name: $Name"
    print_info "Manager IP: $Manager"
}
if ($Mode -eq "full" -or $Mode -eq "install") {
    print_info "PowerShell Version: $PSVersion"
    print_info "Domain Controller: $IsDC"
    print_info "System Health Monitoring: $UseSystemHealth"
    print_info "PowerShell/Process Logging: $UsePowerShellLog"
    print_info "AD Monitoring: $UseAdMonitoring"
}

if (-not $Yes) {
    $confirm = Read-Host "Proceed with setup? [y/yes]"
    if ($confirm -ne "y" -and $confirm -ne "yes") {
        print_info "Setup aborted"
        exit 0
    }
}

# INSTALL
if ($Mode -eq "full" -or $Mode -eq "install") {
    Install-WazuhAgent -ManagerIp $Manager -AgentName $Name -EnrollPassword $Password -Version $WazuhVersion

    if ($UseSystemHealth)  { Enable-SystemHealthMonitoring }
    if ($UsePowerShellLog) { Enable-PowerShellLogging }
    if ($UseAdMonitoring)  { Enable-AdMonitoring }

    if (-not $UseSystemHealth -and -not $UsePowerShellLog -and -not $UseAdMonitoring) {
        print_info "Nothing additional to set up."
    }
}

# REGISTRATION
if ($Mode -eq "full" -or $Mode -eq "register" -or $Reregister) {
    Update-OssecConfig -NewManager $Manager | Out-Null

    if ($Reregister) {
        $ok = Reregister-WazuhAgent -ManagerIp $Manager -AgentName $Name -EnrollPassword $Password
    } else {
        $ok = Register-WazuhAgent -ManagerIp $Manager -AgentName $Name -EnrollPassword $Password
    }

    if (-not $ok) { print_error "Registration failed. Please check the messages above." }
    if ($Mode -eq "register") { print_info "Agent registered. Starting service..." }
}

# START
if ($Mode -eq "full" -or $Mode -eq "run" -or $Mode -eq "register" -or $Reregister) {
    print_info "Starting Wazuh service..."

    try {
        if (-not (Ensure-WazuhService)) {
            throw "WazuhSvc does not exist and could not be re-registered."
        }

        $service = Get-Service -Name "WazuhSvc" -ErrorAction Stop

        print_info "WazuhSvc found. Current status: $($service.Status)"

        if ($service.Status -ne "Running") {
            Start-Service -Name "WazuhSvc"
        }

        Set-Service -Name "WazuhSvc" -StartupType Automatic

        $service = Get-Service -Name "WazuhSvc" -ErrorAction Stop

        if ($service.Status -eq "Running") {
            print_info "Wazuh Agent is now running!"
            print_info "WazuhSvc startup type: Automatic"
        }
        else {
            print_error "WazuhSvc exists but is not running."
            print_error "Current status: $($service.Status)"
        }
    }
    catch {
        print_error "Failed to start WazuhSvc: $_"
    }
}


print_info "Wazuh Agent setup finished! (Mode: $Mode)"
New-Item -Path "C:\ProgramData\WazuhSetup\wazuh-setup-complete.flag" -ItemType File -Force | Out-Null