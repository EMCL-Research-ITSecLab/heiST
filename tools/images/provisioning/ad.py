import time

from .ssh_control import ssh_run, reboot_and_wait, get_adapter_ip


def _q(s: str) -> str:
    """Escape a value for use inside a PowerShell single-quoted string."""
    return s.replace("'", "''")


def _ps_ok(port, cmd, user, pw, what, timeout=120):
    """Run a PowerShell command and raise with the REAL error text if it fails."""
    code, out, err = ssh_run(port, cmd, user, pw, timeout=timeout)
    if out.strip():
        print(out.strip())
    if code != 0:
        raise RuntimeError(f"{what} failed (exit {code}):\n{err.strip() or out.strip()}")
    return out


_DC_DNS_CLEANUP = r"""
$ErrorActionPreference = 'Stop'
$ip = '@IP@'; $prefix = '@PREFIX@'; $zones = '@DOMAIN@', '_msdcs.@DOMAIN@'

Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -notlike "$prefix*" -and $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
  ForEach-Object { Set-DnsClient -InterfaceIndex $_.InterfaceIndex -RegisterThisConnectionsAddress $false }

dnscmd /ResetListenAddresses $ip | Out-Null
Restart-Service DNS -Force
Start-Sleep -Seconds 10

foreach ($z in $zones) {
  Get-DnsServerResourceRecord -ZoneName $z -RRType A |
    Where-Object { $_.RecordData.IPv4Address.IPAddressToString -notlike "$prefix*" } |
    Remove-DnsServerResourceRecord -ZoneName $z -Force
}

ipconfig /registerdns | Out-Null
nltest /dsregdns | Out-Null
Restart-Service Netlogon -WarningAction SilentlyContinue
Start-Sleep -Seconds 10
$bad = foreach ($z in $zones) {
  Get-DnsServerResourceRecord -ZoneName $z -RRType A |
    Where-Object { $_.RecordData.IPv4Address.IPAddressToString -notlike "$prefix*" } |
    ForEach-Object { "$z $($_.HostName) $($_.RecordData.IPv4Address)" }
}
if ($bad) { throw "Stray non-internal DNS records remain: $($bad -join '; ')" }
'DNS cleanup OK'
"""


def promote_dc(port, domain_name, domain_netbios, safe_mode_password, admin_username, admin_password,
               ip_prefix, timeout_reboot=1800):
    """Install AD DS, promote the box to a Domain Controller, and keep its NAT address out of DNS.

    Returns the DC's internal IP (ip_prefix*).
    """
    print("Promoting DC: installing AD-Domain-Services feature...")
    _ps_ok(port,
           "Install-WindowsFeature -Name AD-Domain-Services -IncludeManagementTools | Out-String",
           admin_username, admin_password, "Install AD-Domain-Services", timeout=300)

    print("Promoting DC: running Install-ADDSForest (this will reboot the VM)...")
    promote_cmd = (
        f"$ErrorActionPreference = 'Stop'; "
        f"$p = ConvertTo-SecureString '{_q(safe_mode_password)}' -AsPlainText -Force; "
        f"Install-ADDSForest -DomainName '{_q(domain_name)}' -DomainNetbiosName '{_q(domain_netbios)}' "
        f"-SafeModeAdministratorPassword $p -InstallDns -Force"
    )
    reboot_and_wait(port, admin_username, admin_password, promote_cmd,
                    timeout=timeout_reboot, disconnect_wait=900)

    print("Verifying AD DS is actually running...")
    deadline = time.time() + 1200
    while time.time() < deadline:
        try:
            code, out, _ = ssh_run(
                port, "(Get-Service NTDS -ErrorAction SilentlyContinue).Status",
                admin_username, admin_password, timeout=20,
            )
            if out.strip() == "Running":
                print("Domain Controller promotion confirmed (NTDS service running)")
                break
        except Exception as e:
            print(f"DC verification not ready yet: {e}")
        time.sleep(15)
    else:
        raise RuntimeError("Timed out waiting for NTDS service to come up after DC promotion")

    dc_ip = get_adapter_ip(port, ip_prefix, admin_username, admin_password)

    print(f"Cleaning DC DNS (keeping only {ip_prefix}* addresses)...")
    cleanup = (_DC_DNS_CLEANUP
               .replace("@IP@", dc_ip)
               .replace("@PREFIX@", ip_prefix)
               .replace("@DOMAIN@", domain_name))
    last_err = None
    for attempt in range(1, 6):
        try:
            _ps_ok(port, cleanup, admin_username, admin_password, "DC DNS cleanup", timeout=240)
            return dc_ip
        except Exception as e:
            last_err = e
            print(f"DNS cleanup attempt {attempt}/5 failed: {e}")
            time.sleep(20)
    raise RuntimeError(f"DC DNS cleanup kept failing: {last_err}")


def join_domain(port, dc_internal_ip, domain_name, domain_netbios, ip_prefix,
                admin_username, admin_password, domain_admin_password, timeout_reboot=1800):
    """Point DNS at the DC just long enough to join, then reset to automatic so nothing static survives into the OVA."""
    print(f"Pointing member DNS (all up adapters) at DC ({dc_internal_ip})...")
    _ps_ok(port,
           f"$ErrorActionPreference = 'Stop'; "
           f"Get-NetAdapter | Where-Object Status -eq 'Up' | "
           f"Set-DnsClientServerAddress -ServerAddresses {dc_internal_ip}; "
           f"Clear-DnsClientCache",
           admin_username, admin_password, "Set DNS for domain join", timeout=60)

    print(f"Preflight: locating DC for {domain_name}...")
    preflight = (
        f"$o = nltest /dsgetdc:{domain_name} | Out-String; $o; "
        f"if ($LASTEXITCODE -ne 0) {{ exit 1 }}; "
        f"if ($o -notmatch [regex]::Escape('{dc_internal_ip}')) {{ "
        f"Write-Error 'DC located at the wrong address (stale DNS record?)'; exit 2 }}"
    )
    last = ""
    for attempt in range(1, 13):
        code, out, err = ssh_run(port, preflight, admin_username, admin_password, timeout=60)
        if code == 0:
            print(out.strip())
            break
        last = f"exit {code}: {err.strip() or out.strip()}"
        print(f"DC not locatable yet ({attempt}/12): {last}")
        time.sleep(10)
    else:
        raise RuntimeError(f"Member cannot locate the DC via DNS {dc_internal_ip}: {last}")

    print(f"Joining domain {domain_name}...")
    _ps_ok(port,
           f"$ErrorActionPreference = 'Stop'; "
           f"$p = ConvertTo-SecureString '{_q(domain_admin_password)}' -AsPlainText -Force; "
           f"$c = New-Object System.Management.Automation.PSCredential('{_q(domain_netbios)}\\Administrator', $p); "
           f"Add-Computer -DomainName '{_q(domain_name)}' -Credential $c -Force; "
           f"'Join OK'",
           admin_username, admin_password, "Add-Computer", timeout=180)

    print("Rebooting member to finish the join...")
    reboot_and_wait(port, admin_username, admin_password, "Restart-Computer -Force",
                    timeout=timeout_reboot)

    print("Verifying domain join...")
    deadline = time.time() + 300
    joined = False
    while time.time() < deadline:
        try:
            code, out, _ = ssh_run(
                port, "(Get-CimInstance Win32_ComputerSystem).PartOfDomain",
                admin_username, admin_password, timeout=20,
            )
            if out.strip().lower() == "true":
                joined = True
                break
        except Exception as e:
            print(f"Domain-join verification not ready yet: {e}")
        time.sleep(15)

    if not joined:
        raise RuntimeError("Member did not report PartOfDomain=True after join")

    print("Domain join confirmed. Resetting DNS back to automatic (DHCP)...")
    code, out, err = ssh_run(
        port,
        "Get-NetAdapter | Where-Object Status -eq 'Up' | Set-DnsClientServerAddress -ResetServerAddresses",
        admin_username, admin_password, timeout=60,
    )
    if code != 0:
        print(f"[Warning] Failed to reset DNS back to automatic: {err}")