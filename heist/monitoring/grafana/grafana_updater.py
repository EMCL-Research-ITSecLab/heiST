"""
Grafana Dashboard Update Script
Dynamically updates existing dashboards with new configurations
"""

import requests
import json
import os
import sys
import argparse
from heist.environment import load_installer_env as load_dotenv
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

# Configuration
GRAFANA_HOST_URL = os.getenv("MONITORING_HOST", "10.0.0.103")
GRAFANA_PORT = os.getenv("GRAFANA_PORT", "3000")
GRAFANA_URL = f"https://{GRAFANA_HOST_URL}:{GRAFANA_PORT}"
ADMIN_USER = os.getenv("GRAFANA_USER", "admin")
ADMIN_PASS = os.getenv("GRAFANA_PASSWORD", "SuperSecure123!")

MONITORING_FILES_DIR = os.getenv("MONITORING_FILES_DIR", "/root/heiST/heist/monitoring")
GRAFANA_FILES_SETUP_DIR = os.getenv("GRAFANA_FILES_SETUP_DIR", f"{MONITORING_FILES_DIR}/grafana")

# Dashboard files
CLICKHOUSE_DASHBOARD_VPN_FILE = f"{GRAFANA_FILES_SETUP_DIR}/config/clickhouse_dashboard_vpn.json"
CLICKHOUSE_DASHBOARD_DMZ_FILE = f"{GRAFANA_FILES_SETUP_DIR}/config/clickhouse_dashboard_dmz.json"
CLICKHOUSE_DASHBOARD_BACKEND_FILE = f"{GRAFANA_FILES_SETUP_DIR}/config/clickhouse_dashboard_backend.json"
CLICKHOUSE_DASHBOARD_ZEEK_FILE = f"{GRAFANA_FILES_SETUP_DIR}/config/clickhouse_dashboard_vpn_zeek.json"
WAZUH_DASHBOARD_FILE = f"{GRAFANA_FILES_SETUP_DIR}/config/wazuh_dashboard.json"
SYSTEMD_DASHBOARD_FILE = f"{GRAFANA_FILES_SETUP_DIR}/config/systemd_dashboard.json"

# SSL/TLS certificate paths
CERTS_DIR = os.getenv("SSL_TLS_CERTS_DIR", "/root/heiST/heist/installer/certs")
FULLCHAIN_FILE = f"{CERTS_DIR}/fullchain.pem"
PRIVKEY_FILE = f"{CERTS_DIR}/privkey.pem"

# ClickHouse configuration
CLICKHOUSE_IP = os.getenv("MONITORING_HOST", "10.0.0.103")
CLICKHOUSE_HTTPS_PORT = os.getenv("CLICKHOUSE_HTTPS_PORT", "8443")
CLICKHOUSE_NATIVE_PORT = os.getenv("CLICKHOUSE_NATIVE_PORT", "9440")
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "changeme")

# Wazuh configuration
WAZUH_MANAGER_IP = os.getenv("MONITORING_HOST", "10.0.0.103")
WAZUH_MANAGER_PORT = os.getenv("WAZUH_MANAGER_PORT", "9200")
WAZUH_USER = os.getenv("WAZUH_INDEXER_USER", "admin")
WAZUH_PASSWORD = os.getenv("WAZUH_INDEXER_PASSWORD", "SecretPassword")

DEBUG_MODE = False


def log_info(msg):
    print(f"[INFO] {msg}")

def log_success(msg):
    print(f"[SUCCESS] {msg}")

def log_error(msg):
    print(f"[ERROR] {msg}", file=sys.stderr)

def log_warning(msg):
    print(f"[WARNING] {msg}")

def log_debug(msg):
    if DEBUG_MODE:
        print(f"[DEBUG] {msg}")


def get_auth_headers():
    """Get authentication headers"""
    return {
        "Content-Type": "application/json"
    }


def get_session():
    """Create authenticated session"""
    session = requests.Session()
    session.auth = (ADMIN_USER, ADMIN_PASS)
    session.verify = False
    return session


def list_all_dashboards(session):
    """List all dashboards in Grafana"""
    try:
        resp = session.get(
            f"{GRAFANA_URL}/api/search",
            headers=get_auth_headers(),
            params={"type": "dash-db"}
        )
        if resp.status_code == 200:
            return resp.json()
        else:
            log_error(f"Failed to list dashboards: {resp.text}")
            return []
    except Exception as e:
        log_error(f"Error listing dashboards: {e}")
        return []


def get_dashboard_by_uid(session, uid):
    """Get a dashboard by UID"""
    try:
        resp = session.get(
            f"{GRAFANA_URL}/api/dashboards/uid/{uid}",
            headers=get_auth_headers()
        )
        if resp.status_code == 200:
            return resp.json()
        else:
            log_error(f"Failed to get dashboard {uid}: {resp.text}")
            return None
    except Exception as e:
        log_error(f"Error getting dashboard {uid}: {e}")
        return None


def search_dashboard_by_title(session, title):
    """Search for a dashboard by title"""
    dashboards = list_all_dashboards(session)
    for dash in dashboards:
        if dash.get("title", "").lower() == title.lower():
            return dash
    return None


def update_dashboard(session, dashboard_data, message="Updated via script"):
    """Update an existing dashboard"""
    try:
        # Prepare the update payload
        update_payload = {
            "dashboard": dashboard_data["dashboard"],
            "message": message,
            "overwrite": True
        }

        # If folderUid exists, include it
        if "meta" in dashboard_data and "folderUid" in dashboard_data["meta"]:
            update_payload["folderUid"] = dashboard_data["meta"]["folderUid"]

        resp = session.post(
            f"{GRAFANA_URL}/api/dashboards/db",
            headers=get_auth_headers(),
            json=update_payload
        )

        if resp.status_code in (200, 201):
            result = resp.json()
            log_success(f"Updated dashboard: {dashboard_data['dashboard'].get('title', 'Unknown')}")
            log_info(f"  UID: {result.get('uid')}")
            log_info(f"  URL: {result.get('url')}")
            return True
        else:
            log_error(f"Failed to update dashboard: {resp.text}")
            return False
    except Exception as e:
        log_error(f"Error updating dashboard: {e}")
        return False


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


def escape_json_string(value):
    """Escape a string for proper JSON insertion"""
    if value is None:
        return ""
    # Use json.dumps to properly escape the string for JSON
    escaped = json.dumps(str(value))
    return escaped[1:-1] if len(escaped) > 1 else ""


def replace_placeholders_in_content(content, replacements):
    """Replace placeholders in content with actual values"""
    for placeholder, value in replacements.items():
        # For PEM content, we need to properly escape it for JSON
        if placeholder in ['<fullchain_content>', '<privkey_content>']:
            escaped_value = json.dumps(value)[1:-1]  # Remove the surrounding quotes
            content = content.replace(placeholder, escaped_value)
        else:
            # For regular values, use string representation
            content = content.replace(placeholder, str(value))
    return content


def load_dashboard_file(filepath, replacements=None):
    """Load and optionally replace placeholders in dashboard file"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        if replacements:
            content = replace_placeholders_in_content(content, replacements)

        # Validate the JSON before returning
        parsed_json = json.loads(content)
        return parsed_json

    except FileNotFoundError:
        log_error(f"File not found: {filepath}")
        return None
    except json.JSONDecodeError as e:
        log_error(f"Invalid JSON in {filepath}: {e}")
        # Log more context about the error
        error_pos = e.pos
        start = max(0, error_pos - 100)
        end = min(len(content), error_pos + 100)
        log_debug(f"Problematic content around position {error_pos}:")
        log_debug(f"...{content[start:end]}...")
        return None
    except Exception as e:
        log_error(f"Error loading file {filepath}: {e}")
        return None


def get_datasource_uid_by_name(session, datasource_name):
    """Get datasource UID by name"""
    try:
        resp = session.get(
            f"{GRAFANA_URL}/api/datasources/name/{datasource_name}",
            headers=get_auth_headers()
        )
        if resp.status_code == 200:
            return resp.json().get("uid")
        else:
            log_warning(f"Could not find datasource: {datasource_name}")
            return None
    except Exception as e:
        log_error(f"Error getting datasource: {e}")
        return None


def replace_datasource_references(dashboard_data, old_ref, new_uid):
    """Replace datasource references in dashboard JSON"""
    dashboard_str = json.dumps(dashboard_data)
    dashboard_str = dashboard_str.replace(old_ref, new_uid)
    return json.loads(dashboard_str)


def update_clickhouse_dashboards(session, datasource_uid=None):
    """Update all ClickHouse dashboards"""
    log_info("Updating ClickHouse dashboards...")

    # Get ClickHouse datasource UID if not provided
    if not datasource_uid:
        datasource_uid = get_datasource_uid_by_name(session, "ClickHouse")
        if not datasource_uid:
            log_error("Could not find ClickHouse datasource. Please provide UID manually.")
            return False

    log_info(f"Using ClickHouse datasource UID: {datasource_uid}")

    # Prepare replacements for placeholders
    replacements = {
        "<clickhouse_ip>": CLICKHOUSE_IP,
        "<clickhouse_https_port>": CLICKHOUSE_HTTPS_PORT,
        "<clickhouse_native_port>": CLICKHOUSE_NATIVE_PORT,
        "<clickhouse_password>": CLICKHOUSE_PASSWORD,
        "<clickhouse_user>": CLICKHOUSE_USER,
    }

    # Add PEM files if they exist
    fullchain_content = read_pem_file(FULLCHAIN_FILE)
    privkey_content = read_pem_file(PRIVKEY_FILE)
    if fullchain_content:
        replacements["<fullchain_content>"] = fullchain_content
    if privkey_content:
        replacements["<privkey_content>"] = privkey_content

    dashboards = [
        ("VPN Network Traffic", CLICKHOUSE_DASHBOARD_VPN_FILE),
        ("DMZ Network Traffic", CLICKHOUSE_DASHBOARD_DMZ_FILE),
        ("Backend Network Traffic", CLICKHOUSE_DASHBOARD_BACKEND_FILE),
        ("VPN Zeek Logs", CLICKHOUSE_DASHBOARD_ZEEK_FILE)
    ]

    success_count = 0
    for title, filepath in dashboards:
        if not os.path.exists(filepath):
            log_warning(f"Dashboard file not found: {filepath}")
            continue

        log_info(f"Processing: {title}")
        dashboard_data = load_dashboard_file(filepath, replacements)

        if not dashboard_data:
            continue

        # Debug: Check what placeholders exist
        dashboard_str = json.dumps(dashboard_data)
        if "${DS_CLICKHOUSE}" in dashboard_str:
            log_debug("Found ${DS_CLICKHOUSE} placeholder")
        elif "$DS_CLICKHOUSE" in dashboard_str:
            log_debug("Found $DS_CLICKHOUSE placeholder")
        else:
            log_warning("No DS_CLICKHOUSE placeholder found in dashboard!")

        # Replace datasource references - handle both formats
        dashboard_data = replace_datasource_references(
            dashboard_data,
            "${DS_CLICKHOUSE}",
            datasource_uid
        )
        # Also replace without curly braces in case that's the format
        dashboard_data = replace_datasource_references(
            dashboard_data,
            "$DS_CLICKHOUSE",
            datasource_uid
        )

        # Verify replacement happened
        dashboard_str_after = json.dumps(dashboard_data)
        if "${DS_CLICKHOUSE}" in dashboard_str_after or "$DS_CLICKHOUSE" in dashboard_str_after:
            log_error("Datasource placeholder still exists after replacement!")
        else:
            log_debug(f"Successfully replaced datasource with UID: {datasource_uid}")

        # Extract just the dashboard object if it's wrapped
        if "dashboard" in dashboard_data:
            actual_dashboard = dashboard_data["dashboard"]
        else:
            actual_dashboard = dashboard_data

        # Get the dashboard title from the JSON
        dashboard_title = actual_dashboard.get("title", title)

        # Search for existing dashboard by title
        log_debug(f"Searching for existing dashboard: {dashboard_title}")
        existing = search_dashboard_by_title(session, dashboard_title)

        if existing:
            log_info(f"Found existing dashboard '{dashboard_title}' with UID: {existing['uid']}")
            # Preserve the existing UID and version
            actual_dashboard["uid"] = existing["uid"]
            # Get the full dashboard to preserve version
            full_existing = get_dashboard_by_uid(session, existing["uid"])
            if full_existing and "dashboard" in full_existing:
                actual_dashboard["version"] = full_existing["dashboard"].get("version", 0)
        else:
            log_info(f"No existing dashboard found for '{dashboard_title}', will create new")
            # Remove uid if present to let Grafana generate one
            if "uid" in actual_dashboard:
                del actual_dashboard["uid"]

        # Wrap it properly for the update
        wrapped_dashboard = {"dashboard": actual_dashboard}

        if update_dashboard(session, wrapped_dashboard, f"Updated {title}"):
            success_count += 1

    log_info(f"Successfully updated {success_count}/{len(dashboards)} ClickHouse dashboards")
    return success_count > 0


def update_wazuh_dashboard(session, datasource_uid=None):
    """Update Wazuh dashboard"""
    log_info("Updating Wazuh dashboard...")

    # Get Wazuh datasource UID if not provided
    if not datasource_uid:
        datasource_uid = get_datasource_uid_by_name(session, "Wazuh-2")
        if not datasource_uid:
            log_error("Could not find Wazuh datasource. Please provide UID manually.")
            return False

    log_info(f"Using Wazuh datasource UID: {datasource_uid}")

    if not os.path.exists(WAZUH_DASHBOARD_FILE):
        log_error(f"Wazuh dashboard file not found: {WAZUH_DASHBOARD_FILE}")
        return False

    # Prepare replacements for placeholders
    replacements = {
        "<wazuh_manager_ip>": WAZUH_MANAGER_IP,
        "<wazuh_manager_port>": WAZUH_MANAGER_PORT,
        "<wazuh_user>": WAZUH_USER,
        "<wazuh_password>": WAZUH_PASSWORD,
    }

    dashboard_data = load_dashboard_file(WAZUH_DASHBOARD_FILE, replacements)

    if not dashboard_data:
        return False

    # Replace datasource references - handle both formats
    dashboard_data = replace_datasource_references(
        dashboard_data,
        "${DS_WAZUH-2}",
        datasource_uid
    )
    dashboard_data = replace_datasource_references(
        dashboard_data,
        "$DS_WAZUH-2",
        datasource_uid
    )

    # Extract just the dashboard object if it's wrapped
    if "dashboard" in dashboard_data:
        actual_dashboard = dashboard_data["dashboard"]
    else:
        actual_dashboard = dashboard_data

    # Get the dashboard title
    dashboard_title = actual_dashboard.get("title", "Wazuh System Monitoring")

    # Search for existing dashboard by title
    log_debug(f"Searching for existing dashboard: {dashboard_title}")
    existing = search_dashboard_by_title(session, dashboard_title)

    if existing:
        log_info(f"Found existing dashboard '{dashboard_title}' with UID: {existing['uid']}")
        # Preserve the existing UID and version
        actual_dashboard["uid"] = existing["uid"]
        # Get the full dashboard to preserve version
        full_existing = get_dashboard_by_uid(session, existing["uid"])
        if full_existing and "dashboard" in full_existing:
            actual_dashboard["version"] = full_existing["dashboard"].get("version", 0)
    else:
        log_info(f"No existing dashboard found for '{dashboard_title}', will create new")
        # Remove uid if present to let Grafana generate one
        if "uid" in actual_dashboard:
            del actual_dashboard["uid"]

    # Wrap it properly
    wrapped_dashboard = {"dashboard": actual_dashboard}

    return update_dashboard(session, wrapped_dashboard, "Updated Wazuh dashboard")


def update_systemd_dashboard(session, datasource_uid=None):
    """Update Systemd Services dashboard"""
    log_info("Updating Systemd Services dashboard...")

    # Get Prometheus datasource UID if not provided
    if not datasource_uid:
        datasource_uid = get_datasource_uid_by_name(session, "Prometheus")
        if not datasource_uid:
            log_error("Could not find Prometheus datasource. Please provide UID manually.")
            return False

    log_info(f"Using Prometheus datasource UID: {datasource_uid}")

    if not os.path.exists(SYSTEMD_DASHBOARD_FILE):
        log_error(f"Systemd dashboard file not found: {SYSTEMD_DASHBOARD_FILE}")
        return False

    dashboard_data = load_dashboard_file(SYSTEMD_DASHBOARD_FILE)

    if not dashboard_data:
        return False

    # Replace datasource references - handle both formats
    dashboard_data = replace_datasource_references(
        dashboard_data,
        "${DS_PROMETHEUS}",
        datasource_uid
    )
    dashboard_data = replace_datasource_references(
        dashboard_data,
        "$DS_PROMETHEUS",
        datasource_uid
    )

    # Extract just the dashboard object if it's wrapped
    if "dashboard" in dashboard_data:
        actual_dashboard = dashboard_data["dashboard"]
    else:
        actual_dashboard = dashboard_data

    # Get the dashboard title
    dashboard_title = actual_dashboard.get("title", "Systemd Services Monitoring")

    # Search for existing dashboard by title
    log_debug(f"Searching for existing dashboard: {dashboard_title}")
    existing = search_dashboard_by_title(session, dashboard_title)

    if existing:
        log_info(f"Found existing dashboard '{dashboard_title}' with UID: {existing['uid']}")
        # Preserve the existing UID and version
        actual_dashboard["uid"] = existing["uid"]
        # Get the full dashboard to preserve version
        full_existing = get_dashboard_by_uid(session, existing["uid"])
        if full_existing and "dashboard" in full_existing:
            actual_dashboard["version"] = full_existing["dashboard"].get("version", 0)
    else:
        log_info(f"No existing dashboard found for '{dashboard_title}', will create new")
        # Remove uid if present to let Grafana generate one
        if "uid" in actual_dashboard:
            del actual_dashboard["uid"]

    # Wrap it properly
    wrapped_dashboard = {"dashboard": actual_dashboard}

    return update_dashboard(session, wrapped_dashboard, "Updated Systemd Services dashboard")


def update_specific_dashboard(session, uid_or_title, filepath, datasource_uid=None, datasource_placeholder=None):
    """Update a specific dashboard by UID or title"""
    log_info(f"Updating dashboard: {uid_or_title}")

    # Load the dashboard file
    dashboard_data = load_dashboard_file(filepath)
    if not dashboard_data:
        return False

    # Replace datasource if provided
    if datasource_uid and datasource_placeholder:
        dashboard_data = replace_datasource_references(
            dashboard_data,
            datasource_placeholder,
            datasource_uid
        )

    # Try to find existing dashboard
    existing = None
    if len(uid_or_title) <= 40:  # Likely a UID
        existing = get_dashboard_by_uid(session, uid_or_title)

    if not existing:
        # Search by title
        existing = search_dashboard_by_title(session, uid_or_title)

    if existing:
        log_info(f"Found existing dashboard with UID: {existing['dashboard']['uid']}")
        # Preserve the UID and version
        dashboard_data["dashboard"]["uid"] = existing["dashboard"]["uid"]
        dashboard_data["dashboard"]["version"] = existing["dashboard"].get("version", 0)

    return update_dashboard(session, dashboard_data, f"Updated {uid_or_title}")


def interactive_mode(session):
    """Interactive mode to select and update dashboards"""
    print("\n=== Grafana Dashboard Updater ===\n")

    dashboards = list_all_dashboards(session)
    if not dashboards:
        log_error("No dashboards found or failed to retrieve dashboards")
        return

    print("Available dashboards:")
    for i, dash in enumerate(dashboards, 1):
        print(f"{i}. {dash['title']} (UID: {dash['uid']})")

    print("\nOptions:")
    print("  1. Update all ClickHouse dashboards")
    print("  2. Update Wazuh dashboard")
    print("  3. Update Systemd Services dashboard")
    print("  4. Update specific dashboard by number")
    print("  5. List datasources")
    print("  6. Exit")

    choice = input("\nSelect option: ").strip()

    if choice == "1":
        update_clickhouse_dashboards(session)
    elif choice == "2":
        update_wazuh_dashboard(session)
    elif choice == "3":
        update_systemd_dashboard(session)
    elif choice == "4":
        dash_num = input("Enter dashboard number: ").strip()
        try:
            idx = int(dash_num) - 1
            if 0 <= idx < len(dashboards):
                selected = dashboards[idx]
                print(f"\nSelected: {selected['title']}")
                filepath = input("Enter path to dashboard JSON file: ").strip()
                update_specific_dashboard(session, selected['uid'], filepath)
            else:
                log_error("Invalid dashboard number")
        except ValueError:
            log_error("Invalid input")
    elif choice == "5":
        list_datasources(session)
    elif choice == "6":
        return
    else:
        log_error("Invalid choice")


def list_datasources(session):
    """List all datasources"""
    try:
        resp = session.get(f"{GRAFANA_URL}/api/datasources", headers=get_auth_headers())
        if resp.status_code == 200:
            datasources = resp.json()
            print("\nAvailable datasources:")
            for ds in datasources:
                print(f"  - {ds['name']} (Type: {ds['type']}, UID: {ds['uid']})")
        else:
            log_error(f"Failed to list datasources: {resp.text}")
    except Exception as e:
        log_error(f"Error listing datasources: {e}")


def main():
    """Main execution function"""
    global DEBUG_MODE

    parser = argparse.ArgumentParser(
        description="Grafana Dashboard Update Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode
  python update_dashboards.py -i
  
  # Update all ClickHouse dashboards
  python update_dashboards.py --clickhouse
  
  # Update Wazuh dashboard
  python update_dashboards.py --wazuh
  
  # Update Systemd dashboard
  python update_dashboards.py --systemd
  
  # Update specific dashboard
  python update_dashboards.py --dashboard "VPN Network Traffic" --file /path/to/dashboard.json
  
  # List all dashboards
  python update_dashboards.py --list
        """
    )

    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug output")
    parser.add_argument("-i", "--interactive", action="store_true", help="Interactive mode")
    parser.add_argument("--clickhouse", action="store_true", help="Update all ClickHouse dashboards")
    parser.add_argument("--wazuh", action="store_true", help="Update Wazuh dashboard")
    parser.add_argument("--systemd", action="store_true", help="Update Systemd Services dashboard")
    parser.add_argument("--list", action="store_true", help="List all dashboards")
    parser.add_argument("--list-datasources", action="store_true", help="List all datasources")
    parser.add_argument("--dashboard", help="Dashboard UID or title to update")
    parser.add_argument("--file", help="Path to dashboard JSON file")
    parser.add_argument("--datasource-uid", help="Datasource UID to use")
    parser.add_argument("--datasource-placeholder", help="Placeholder to replace (e.g., ${DS_CLICKHOUSE})")

    args = parser.parse_args()
    DEBUG_MODE = args.debug

    # Create session
    session = get_session()

    # Test connection
    try:
        resp = session.get(f"{GRAFANA_URL}/api/health", headers=get_auth_headers())
        if resp.status_code != 200:
            log_error("Cannot connect to Grafana. Check URL and credentials.")
            sys.exit(1)
        log_success("Connected to Grafana")
    except Exception as e:
        log_error(f"Failed to connect to Grafana: {e}")
        sys.exit(1)

    if args.interactive:
        interactive_mode(session)
    elif args.list:
        dashboards = list_all_dashboards(session)
        print("\nDashboards:")
        for dash in dashboards:
            print(f"  - {dash['title']} (UID: {dash['uid']}, Folder: {dash.get('folderTitle', 'General')})")
    elif args.list_datasources:
        list_datasources(session)
    elif args.clickhouse:
        update_clickhouse_dashboards(session, args.datasource_uid)
    elif args.wazuh:
        update_wazuh_dashboard(session, args.datasource_uid)
    elif args.systemd:
        update_systemd_dashboard(session, args.datasource_uid)
    elif args.dashboard and args.file:
        update_specific_dashboard(
            session,
            args.dashboard,
            args.file,
            args.datasource_uid,
            args.datasource_placeholder
        )
    else:
        parser.print_help()
        print("\nNo action specified. Use -i for interactive mode or see examples above.")


if __name__ == "__main__":
    main()