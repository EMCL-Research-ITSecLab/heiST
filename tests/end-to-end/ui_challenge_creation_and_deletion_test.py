import os
from playwright.sync_api import sync_playwright
from utils.setup_challenge_ui import setup_challenge_ui
from utils.delete_challenge_ui import delete_challenge_ui


def ui_challenge_creation_and_deletion(username, password, path_to_yaml, upload_ova_files=False, prints=False):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        if prints:
            print("Testing Challenge Creation via UI")
        challenge_name = setup_challenge_ui(page, path_to_yaml, username, password, login=True, upload_ova_files=upload_ova_files, prints=prints)

        if prints:
            print("\nTesting Challenge Deletion via UI")
        delete_challenge_ui(page, challenge_name, username, password, login=True, prints=prints)

        context.close()
        browser.close()


if __name__ == "__main__":
    username = os.getenv("ADMIN_USER", "admin")
    password = os.getenv("ADMIN_PASSWORD")

    YAML_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../tools/challenges"))
    CONFIG_PATH = os.path.join(YAML_DIR, "ctf-config.yaml")

    ui_challenge_creation_and_deletion(username, password, CONFIG_PATH, upload_ova_files=False, prints=True)