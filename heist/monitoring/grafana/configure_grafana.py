"""
Grafana Configuration Script
Automates Grafana setup with datasources, dashboards, and service accounts
"""

import requests
import json
import time
import os
import sys
import argparse
from heist.environment import load_installer_env as load_dotenv
import textwrap
sys.stdout.reconfigure(line_buffering=True)
import urllib3

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Monkey patch requests to always disable SSL verification
original_request = requests.Session.request

def no_ssl_verification_request(self, method, url, **kwargs):
    kwargs['verify'] = False
    kwargs.setdefault('timeout', 30)
    return original_request(self, method, url, **kwargs)

requests.Session.request = no_ssl_verification_request

# Load environment variables
load_dotenv()
from heist.monitoring.utils.script_helper import (
    log_info, log_debug, log_error, log_warning, log_success, log_section, scp_file,
    execute_remote_command, execute_remote_command_with_key, Timer, time_function, DEBUG_MODE
)

# ==== CONFIGURATION CONSTANTS ====
GRAFANA_HOST_URL = os.getenv("MONITORING_HOST", "10.0.0.103")
GRAFANA_PORT = os.getenv("GRAFANA_PORT", "3000")
GRAFANA_URL_HTTP = f"http://{GRAFANA_HOST_URL}:{GRAFANA_PORT}"
GRAFANA_URL = f"https://{GRAFANA_HOST_URL}:{GRAFANA_PORT}"
ADMIN_USER = os.getenv("GRAFANA_USER", "admin")
ADMIN_PASS = "admin"
NEW_ADMIN_PASS = os.getenv("GRAFANA_PASSWORD", "SuperSecure123!")
PROMETHEUS_PORT = os.getenv("PROMETHEUS_PORT", "9090")
PROMETHEUS_URL = f"http://{GRAFANA_HOST_URL}:{PROMETHEUS_PORT}"
GRAFANA_FILES_SETUP_DIR = os.getenv("GRAFANA_FILES_SETUP_DIR", "/root/heiST/heist/monitoring/grafana")
PROXMOX_SSH_KEYFILE = os.getenv("PROXMOX_SSH_KEYFILE", "/root/.ssh/id_rsa.pub")
GRAFANA_FILES_DIR = os.getenv("GRAFANA_FILES_DIR", "/etc/grafana")
GRAFANA_INI_PATH = f"{GRAFANA_FILES_DIR}/grafana.ini"

# Wazuh configuration
WAZUH_MANAGER_IP = os.getenv("MONITORING_HOST", "10.0.0.103")
WAZUH_MANAGER_PORT = os.getenv("WAZUH_MANAGER_PORT", "9200")
WAZUH_DASHBOARD_FILE = f"{GRAFANA_FILES_SETUP_DIR}/config/wazuh_dashboard.json"
WAZUH_DATASOURCE_FILE = f"{GRAFANA_FILES_SETUP_DIR}/config/wazuh_datasource.json"
WAZUH_USER = os.getenv("WAZUH_INDEXER_USER", "admin")
WAZUH_PASSWORD = os.getenv("WAZUH_INDEXER_PASSWORD", "SecretPassword")

# ClickHouse configuration
CLICKHOUSE_DASHBOARD_VPN_FILE = f"{GRAFANA_FILES_SETUP_DIR}/config/clickhouse_dashboard_vpn.json"
CLICKHOUSE_DASHBOARD_DMZ_FILE = f"{GRAFANA_FILES_SETUP_DIR}/config/clickhouse_dashboard_dmz.json"
CLICKHOUSE_DASHBOARD_BACKEND_FILE = f"{GRAFANA_FILES_SETUP_DIR}/config/clickhouse_dashboard_backend.json"
CLICKHOUSE_DASHBOARD_ZEEK_FILE = f"{GRAFANA_FILES_SETUP_DIR}/config/clickhouse_dashboard_vpn_zeek.json"
CLICKHOUSE_DATASOURCE_FILE = f"{GRAFANA_FILES_SETUP_DIR}/config/clickhouse_datasource.json"

CLICKHOUSE_IP = os.getenv("MONITORING_HOST", "10.0.0.103")
CLICKHOUSE_HTTPS_PORT = os.getenv("CLICKHOUSE_HTTPS_PORT", "8443")
CLICKHOUSE_NATIVE_PORT = os.getenv("CLICKHOUSE_NATIVE_PORT", "9440")
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "changeme")

# SSL/TLS certificate paths
CERTS_DIR = os.getenv("SSL_TLS_CERTS_DIR", "/root/heiST/heist/installer/certs")
FULLCHAIN_FILE = f"{CERTS_DIR}/fullchain.pem"
PRIVKEY_FILE = f"{CERTS_DIR}/privkey.pem"

DASHBOARD_IDS = {
    9628: "PostgreSQL Exporter",
    1860: "Node Exporter Full",
    3894: "Apache Exporter",
    10347: "Proxmox Exporter"
}

DATASOURCE_NAME = "Prometheus"
WAZUH_DATASOURCE_NAME = "Wazuh-2"
CLICKHOUSE_PLUGIN_ID = "grafana-clickhouse-datasource"

SSH_USER = os.getenv("MONITORING_VM_USER", "ubuntu")
SSH_PASSWORD = os.getenv("MONITORING_VM_PASSWORD", "meow1234")


def escape_json_string(value):
    """Escape a string for proper JSON insertion"""
    if value is None:
        return ""
    # Use json.dumps to properly escape the string for JSON
    escaped = json.dumps(str(value))
    return escaped[1:-1] if len(escaped) > 1 else ""


def read_pem_file(filename):
    """Read PEM file content and properly escape it for JSON"""
    try:
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            # Ensure proper Unix line endings and clean up
            content = content.replace('\r\n', '\n').replace('\r', '\n')
            # Remove any trailing whitespace from each line
            content = '\n'.join(line.rstrip() for line in content.split('\n'))
            log_debug(f"Read PEM file {filename} - Content length: {len(content)}")
            return content
        log_warning(f"PEM file {filename} does not exist")
        return ""
    except Exception as e:
        log_error(f"Error reading PEM file {filename}: {e}")
        return ""


def replace_placeholders_in_file(filename, replacements):
    """Replace placeholders in a JSON file with actual values"""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()

        for placeholder, value in replacements.items():
            if placeholder in ['<fullchain_content>', '<privkey_content>']:

                escaped_value = json.dumps(value)[1:-1]  # Remove the surrounding quotes
                content = content.replace(placeholder, escaped_value)
            else:
                # For regular values, use string representation
                content = content.replace(placeholder, str(value))

        # Validate the JSON before returning
        parsed_json = json.loads(content)
        return parsed_json

    except FileNotFoundError:
        log_error(f"File {filename} not found")
        return None
    except json.JSONDecodeError as e:
        log_error(f"Error parsing JSON from {filename}: {e}")
        error_pos = e.pos
        start = max(0, error_pos - 100)
        end = min(len(content), error_pos + 100)
        log_debug(f"Problematic content around position {error_pos}:")
        log_debug(f"...{content[start:end]}...")

        log_debug("Full content that failed to parse:")
        log_debug(content)
        return None

def get_datasource_uid(headers, datasource_name):
    """Get the UID of a datasource by name"""
    try:
        resp = requests.get(f"{GRAFANA_URL}/api/datasources/name/{datasource_name}", headers=headers)
        if resp.status_code == 200:
            return resp.json().get("uid")
        else:
            log_warning(f"Could not get UID for datasource {datasource_name}: {resp.text}")
            return None
    except Exception as e:
        log_error(f"Error getting datasource UID: {e}")
        return None


def is_plugin_installed(headers, plugin_id):
    """Check if a plugin is installed"""
    try:
        resp = requests.get(f"{GRAFANA_URL}/api/plugins", headers=headers)
        if resp.status_code == 200:
            plugins = resp.json()
            for plugin in plugins:
                if plugin.get("id") == plugin_id:
                    return True
            return False
        else:
            log_warning(f"Could not check plugins: {resp.text}")
            return False
    except Exception as e:
        log_error(f"Error checking plugins: {e}")
        return False


@time_function
def wait_for_grafana(grafana_url):
    """Wait for Grafana to be responsive"""
    max_attempts = 30
    for attempt in range(max_attempts):
        try:
            resp = requests.get(f"{grafana_url}/api/health", verify=False, timeout=10)
            if resp.status_code == 200:
                log_success("Grafana is responsive")
                return True
        except requests.exceptions.ConnectionError:
            pass

        if attempt < max_attempts - 1:
            log_info(f"Waiting for Grafana to start... ({attempt + 1}/{max_attempts})")
            time.sleep(2)

    log_error("Grafana did not become responsive in time")
    return False


@time_function
def enable_grafana_https():
    """
    Activates HTTPS for Grafana and sets custom Port
    """

    scp_file(FULLCHAIN_FILE, "/tmp/fullchain.pem", GRAFANA_HOST_URL, SSH_USER, SSH_PASSWORD)
    scp_file(PRIVKEY_FILE, "/tmp/privkey.pem", GRAFANA_HOST_URL, SSH_USER, SSH_PASSWORD)

    commands = f"""
sudo mkdir -p {GRAFANA_FILES_DIR}/certs && \\
sudo mv /tmp/fullchain.pem {GRAFANA_FILES_DIR}/certs/fullchain.pem && \\
sudo mv /tmp/privkey.pem {GRAFANA_FILES_DIR}/certs/privkey.pem && \\
sudo chown -R grafana:grafana {GRAFANA_FILES_DIR}/certs && \\
sudo chmod 640 {GRAFANA_FILES_DIR}/certs/*.pem && \\
sudo sed -i.bak '/^protocol = https/d; /^cert_file =/d; /^key_file =/d; /^cert_key =/d; /^http_port = {GRAFANA_PORT}/d' {GRAFANA_INI_PATH} && \\
sudo sed -i '/^\\[server\\]/a\\
protocol = https\\
http_port = {GRAFANA_PORT}\\
cert_file = {GRAFANA_FILES_DIR}/certs/fullchain.pem\\
cert_key = {GRAFANA_FILES_DIR}/certs/privkey.pem' {GRAFANA_INI_PATH} && \\
sudo systemctl restart grafana-server
""".strip()

    execute_remote_command_with_key(
        GRAFANA_HOST_URL,
        commands,
        SSH_USER,
        ssh_key_path=PROXMOX_SSH_KEYFILE
    )

    if not wait_for_grafana(GRAFANA_URL):
        raise SystemExit("Grafana HTTPS is not available")


@time_function
def create_service_account(headers):
    """Create service account and return token"""
    log_section("Creating Service Account")

    sa_payload = {
        "name": "setup-script-service-account",
        "role": "Admin",
        "isDisabled": False
    }

    sa_resp = requests.post(
        f"{GRAFANA_URL}/api/serviceaccounts",
        auth=(ADMIN_USER, ADMIN_PASS),
        headers={"Content-Type": "application/json"},
        json=sa_payload
    )

    if sa_resp.status_code not in (200, 201):
        if sa_resp.status_code == 400 and "serviceaccounts.ErrAlreadyExists" in sa_resp.text:
            log_info("Service account already exists, fetching existing ID")
            sa_list_resp = requests.get(f"{GRAFANA_URL}/api/serviceaccounts", auth=(ADMIN_USER, ADMIN_PASS))
            if sa_list_resp.status_code == 200:
                existing = next((sa for sa in sa_list_resp.json() if sa["name"] == "setup-script-service-account"),
                                None)
                if existing:
                    sa_id = existing["id"]
                    log_info(f"Found existing service account with ID {sa_id}")
                else:
                    raise SystemExit("Could not find existing service account after duplicate error")
            else:
                raise SystemExit(f"Failed to list service accounts: {sa_list_resp.text}")
        else:
            raise SystemExit(f"Failed to create service account: {sa_resp.text}")
    else:
        sa_id = sa_resp.json()["id"]
        log_info(f"Service account created (ID: {sa_id})")

    # Create token for service account
    token_payload = {"name": "setup-script-token"}
    token_resp = requests.post(
        f"{GRAFANA_URL}/api/serviceaccounts/{sa_id}/tokens",
        auth=(ADMIN_USER, ADMIN_PASS),
        headers={"Content-Type": "application/json"},
        json=token_payload
    )

    if token_resp.status_code not in (200, 201):
        raise SystemExit(f"Failed to create token: {token_resp.text}")

    api_token = token_resp.json()["key"]
    log_success("Token created for service account")

    return api_token


@time_function
def change_admin_password():
    """Change admin password"""
    log_section("Changing Admin Password")

    password_payload = {
        "oldPassword": ADMIN_PASS,
        "newPassword": NEW_ADMIN_PASS,
        "confirmNew": NEW_ADMIN_PASS
    }
    pass_resp = requests.put(
        f"{GRAFANA_URL}/api/user/password",
        auth=(ADMIN_USER, ADMIN_PASS),
        headers={"Content-Type": "application/json"},
        json=password_payload
    )
    if pass_resp.status_code == 200:
        log_success("Admin password changed")
    else:
        log_warning(f"Could not change admin password: {pass_resp.text}")


@time_function
def create_prometheus_datasource(headers):
    """Create Prometheus datasource"""
    log_section("Creating Prometheus Datasource")

    datasource_payload = {
        "name": DATASOURCE_NAME,
        "type": "prometheus",
        "access": "proxy",
        "url": PROMETHEUS_URL,
        "basicAuth": False
    }

    ds_resp = requests.post(f"{GRAFANA_URL}/api/datasources", headers=headers, json=datasource_payload)
    if ds_resp.status_code == 200:
        log_success(f"Datasource '{DATASOURCE_NAME}' created")
    elif ds_resp.status_code == 409:
        log_info(f"Datasource '{DATASOURCE_NAME}' already exists")
    else:
        raise SystemExit(f"Failed to create datasource: {ds_resp.text}")


@time_function
def setup_wazuh(headers):
    """Setup Wazuh datasource and dashboard"""
    log_section("Setting up Wazuh")

    wazuh_replacements = {
        "<wazuh_manager_ip>": WAZUH_MANAGER_IP,
        "<wazuh_manager_port>": WAZUH_MANAGER_PORT,
        "<wazuh_user>": WAZUH_USER,
        "<wazuh_password>": WAZUH_PASSWORD,
    }

    wazuh_datasource = replace_placeholders_in_file(WAZUH_DATASOURCE_FILE, wazuh_replacements)

    if not wazuh_datasource:
        log_warning("Skipping Wazuh datasource creation due to file error")
        return None

    ds_resp = requests.post(f"{GRAFANA_URL}/api/datasources", headers=headers, json=wazuh_datasource)
    if ds_resp.status_code == 200:
        log_success("Wazuh datasource created")
        wazuh_datasource_uid = get_datasource_uid(headers, WAZUH_DATASOURCE_NAME)
        if wazuh_datasource_uid:
            log_info(f"Wazuh datasource UID: {wazuh_datasource_uid}")
        else:
            log_warning("Could not retrieve Wazuh datasource UID")
    elif ds_resp.status_code == 409:
        log_info("Wazuh datasource already exists")
        wazuh_datasource_uid = get_datasource_uid(headers, WAZUH_DATASOURCE_NAME)
        if wazuh_datasource_uid:
            log_info(f"Found existing Wazuh datasource UID: {wazuh_datasource_uid}")
        else:
            log_warning("Could not retrieve existing Wazuh datasource UID")
    else:
        log_error(f"Failed to create Wazuh datasource: {ds_resp.text}")
        return None

    # Import Wazuh dashboard
    if wazuh_datasource_uid:
        log_info("Importing Wazuh dashboard")
        wazuh_dashboard_data = replace_placeholders_in_file(WAZUH_DASHBOARD_FILE, {})

        if wazuh_dashboard_data:
            wazuh_dashboard = wazuh_dashboard_data.get("dashboard", {})
            if not wazuh_dashboard:
                log_warning("No dashboard object found in Wazuh dashboard file, using entire structure")
                wazuh_dashboard = wazuh_dashboard_data

            dashboard_str = json.dumps(wazuh_dashboard)
            dashboard_str = dashboard_str.replace("${DS_WAZUH-2}", wazuh_datasource_uid)
            updated_dashboard = json.loads(dashboard_str)

            if "title" not in updated_dashboard or not updated_dashboard["title"]:
                updated_dashboard["title"] = "Wazuh System Monitoring"

            import_payload = {
                "dashboard": updated_dashboard,
                "overwrite": True
            }

            imp_resp = requests.post(f"{GRAFANA_URL}/api/dashboards/db", headers=headers, json=import_payload)
            if imp_resp.status_code in (200, 201):
                log_success("Imported: Wazuh Dashboard")
            else:
                log_error(f"Failed to import Wazuh dashboard: {imp_resp.text}")
        else:
            log_error("Failed to load Wazuh dashboard file")

    return wazuh_datasource_uid


@time_function
def setup_clickhouse(headers):
    """Setup ClickHouse plugin, datasource and dashboards"""
    log_section("Setting up ClickHouse")

    # Check if ClickHouse plugin is installed
    if not is_plugin_installed(headers, CLICKHOUSE_PLUGIN_ID):
        log_info("ClickHouse plugin not installed, installing...")
        execute_remote_command_with_key(GRAFANA_HOST_URL, f"sudo grafana cli --homepath /usr/share/grafana plugins install {CLICKHOUSE_PLUGIN_ID}", SSH_USER, ssh_key_path=PROXMOX_SSH_KEYFILE, shell=True)
        execute_remote_command_with_key(GRAFANA_HOST_URL, "sudo systemctl restart grafana-server", SSH_USER, ssh_key_path=PROXMOX_SSH_KEYFILE)

        time.sleep(10)
        if not wait_for_grafana(GRAFANA_URL):
            raise SystemExit("Grafana did not come back online after restart")
    log_info("ClickHouse plugin is installed")

    log_info("Creating ClickHouse datasource with HTTPS")

    fullchain_content = read_pem_file(FULLCHAIN_FILE)
    privkey_content = read_pem_file(PRIVKEY_FILE)

    clickhouse_replacements = {
        "<clickhouse_ip>": CLICKHOUSE_IP,
        "<clickhouse_https_port>": CLICKHOUSE_HTTPS_PORT,
        "<clickhouse_native_port>": CLICKHOUSE_NATIVE_PORT,
        "<clickhouse_password>": CLICKHOUSE_PASSWORD,
        "<clickhouse_user>": CLICKHOUSE_USER,
        "<fullchain_content>": fullchain_content,
        "<privkey_content>": privkey_content
    }

    clickhouse_datasource = replace_placeholders_in_file(CLICKHOUSE_DATASOURCE_FILE, clickhouse_replacements)

    if not clickhouse_datasource:
        log_warning("Skipping ClickHouse datasource creation due to file error")
        return None

    log_debug("Final datasource JSON being sent:")
    log_debug(json.dumps(clickhouse_datasource, indent=2))

    # Clean up secureJsonData
    secure_data = clickhouse_datasource.get("secureJsonData", {})
    for key in list(secure_data.keys()):
        if secure_data[key] is None:
            secure_data[key] = ""

    if CLICKHOUSE_PASSWORD and "password" in secure_data:
        secure_data["password"] = CLICKHOUSE_PASSWORD

    ds_resp = requests.post(f"{GRAFANA_URL}/api/datasources", headers=headers, json=clickhouse_datasource)

    if ds_resp.status_code == 200:
        log_success("ClickHouse HTTPS datasource created")
        clickhouse_datasource_name = clickhouse_datasource.get("name", "ClickHouse")
        clickhouse_datasource_uid = get_datasource_uid(headers, clickhouse_datasource_name)
        if clickhouse_datasource_uid:
            log_info(f"ClickHouse datasource UID: {clickhouse_datasource_uid}")
        else:
            log_warning("Could not retrieve ClickHouse datasource UID")
    elif ds_resp.status_code == 409:
        log_info("ClickHouse datasource already exists")
        clickhouse_datasource_name = clickhouse_datasource.get("name", "ClickHouse")
        clickhouse_datasource_uid = get_datasource_uid(headers, clickhouse_datasource_name)
        if clickhouse_datasource_uid:
            log_info(f"Found existing ClickHouse datasource UID: {clickhouse_datasource_uid}")
        else:
            log_warning("Could not retrieve existing ClickHouse datasource UID")
    else:
        log_error(f"Failed to create ClickHouse datasource: {ds_resp.text}")
        return None

    # Import ClickHouse dashboards
    if clickhouse_datasource_uid:
        log_info("Importing ClickHouse dashboards")
        dashboards = [
            CLICKHOUSE_DASHBOARD_VPN_FILE,
            CLICKHOUSE_DASHBOARD_BACKEND_FILE,
            CLICKHOUSE_DASHBOARD_DMZ_FILE,
            CLICKHOUSE_DASHBOARD_ZEEK_FILE
        ]

        for dashboard_file in dashboards:
            clickhouse_dashboard = replace_placeholders_in_file(dashboard_file, {})
            if clickhouse_dashboard:
                dashboard_str = json.dumps(clickhouse_dashboard)
                dashboard_str = dashboard_str.replace("${DS_CLICKHOUSE}", clickhouse_datasource_uid)
                updated_dashboard = json.loads(dashboard_str)

                import_payload = {
                    "dashboard": updated_dashboard["dashboard"],
                    "folderUid": updated_dashboard.get("folderUid"),
                    "overwrite": updated_dashboard.get("overwrite", True),
                    "inputs": updated_dashboard.get("inputs", [])
                }

                imp_resp = requests.post(f"{GRAFANA_URL}/api/dashboards/db", headers=headers, json=import_payload)
                if imp_resp.status_code in (200, 201):
                    log_success(f"Imported: ClickHouse Dashboard from {os.path.basename(dashboard_file)}")
                else:
                    log_error(f"Failed to import ClickHouse dashboard: {imp_resp.text}")
            else:
                log_error(f"Failed to load ClickHouse dashboard file: {dashboard_file}")

    return clickhouse_datasource_uid


@time_function
def import_external_dashboards(headers):
    """Import external dashboards from Grafana.com"""
    log_section("Importing External Dashboards")

    for dash_id, name in DASHBOARD_IDS.items():
        log_info(f"Importing dashboard: {name} (ID {dash_id})")
        dash_resp = requests.get(f"https://grafana.com/api/dashboards/{dash_id}/revisions/latest/download")
        if dash_resp.status_code != 200:
            log_error(f"Failed to fetch {name}: {dash_resp.text}")
            continue

        dashboard_json = dash_resp.json()

        # Patch datasource inputs
        inputs = []
        if "__inputs" in dashboard_json:
            for inp in dashboard_json["__inputs"]:
                if inp["type"] == "datasource":
                    inp["value"] = DATASOURCE_NAME
                inputs.append(inp)
        else:
            inputs = [
                {"name": "DS_PROMETHEUS", "type": "datasource", "pluginId": "prometheus", "value": DATASOURCE_NAME}
            ]

        import_payload = {
            "dashboard": dashboard_json,
            "overwrite": True,
            "inputs": inputs
        }

        imp_resp = requests.post(f"{GRAFANA_URL}/api/dashboards/import", headers=headers, json=import_payload)
        if imp_resp.status_code in (200, 201):
            log_success(f"Imported: {name}")
        else:
            log_error(f"Failed to import {name}: {imp_resp.text}")


@time_function
def import_systemd_dashboard(headers):
    """Import systemd services dashboard"""
    log_section("Importing Systemd Services Dashboard")

    systemd_dashboard_file = f"{GRAFANA_FILES_SETUP_DIR}/config/systemd_dashboard.json"

    try:
        systemd_dashboard_data = replace_placeholders_in_file(systemd_dashboard_file, {})

        if not systemd_dashboard_data:
            log_error("Failed to load systemd dashboard file")
            return

        prometheus_uid = get_datasource_uid(headers, DATASOURCE_NAME)
        if not prometheus_uid:
            log_error("Could not find Prometheus datasource UID")
            return

        dashboard_str = json.dumps(systemd_dashboard_data)
        dashboard_str = dashboard_str.replace("${DS_PROMETHEUS}", prometheus_uid)
        updated_dashboard = json.loads(dashboard_str)

        import_payload = {
            "dashboard": updated_dashboard["dashboard"],
            "overwrite": updated_dashboard.get("overwrite", True),
            "inputs": updated_dashboard.get("inputs", [])
        }

        imp_resp = requests.post(f"{GRAFANA_URL}/api/dashboards/db", headers=headers, json=import_payload)
        if imp_resp.status_code in (200, 201):
            log_success("Imported: Systemd Services Dashboard")
        else:
            log_error(f"Failed to import systemd dashboard: {imp_resp.text}")

    except Exception as e:
        log_error(f"Error importing systemd dashboard: {e}")


@time_function
def main():
    """Main execution function"""
    global DEBUG_MODE

    parser = argparse.ArgumentParser(description="Grafana Configuration Script")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug output")
    args = parser.parse_args()

    DEBUG_MODE = args.debug

    log_section("Starting Grafana Configuration")

    try:
        with Timer():
            if not wait_for_grafana(GRAFANA_URL_HTTP):
                raise SystemExit("Grafana is not available")

            enable_grafana_https()

            api_token = create_service_account({})

            headers = {
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json"
            }

            change_admin_password()

            create_prometheus_datasource(headers)

            setup_wazuh(headers)

            setup_clickhouse(headers)

            import_external_dashboards(headers)

            import_systemd_dashboard(headers)

        log_success("All Grafana operations completed successfully")

    except Exception as e:
        log_error(f"Grafana configuration failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()