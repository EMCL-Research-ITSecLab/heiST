import os
from login_user_ui import login_user_ui
from automatic_challenge_import.yaml_parser import retrieve_ova_data


def upload_diskfile_ui(page, file_path=None, username=None, password=None, login=False, prints=False, guest_os='linux'):
    if guest_os not in ('linux', 'windows'):
        raise ValueError('guest_os must be linux or windows')
    if login:
        if prints:
            print(f"\tLogging in user {username} via UI")
        login_user_ui(page, username, password, prints=prints)

    if prints:
        print(f"\tNavigating to Disk Files page")
    menu_button = page.get_by_role("button", name="Menu")
    menu_button.click()
    diskfiles_link = page.get_by_role("link", name="Upload Diskfile")
    diskfiles_link.click()

    if prints:
        print(f"\tWaiting for Disk Files page to load")
    page.wait_for_load_state("networkidle")

    if prints:
        print(f"\tFilling upload form with file {file_path}")
    page.set_input_files('input[type="file"]', file_path)

    if prints:
        print(f"\tSubmitting upload form")
    page.click('button:has-text("Upload")')

    # Upload waits for an OS choice before sending any data. Without this step
    # the helper remains blocked behind the modal until its success timeout.
    page.locator(f'.os-option[data-os="{guest_os}"]').click()
    page.locator('#os-next-btn').click()

    if prints:
        print(f"\tWaiting for upload to complete")
    page.wait_for_selector('text=File uploaded successfully', timeout=1000 * 60 * 10)

    if prints:
        print(f"\tFile {file_path} uploaded successfully via UI")


def upload_all_diskfiles_ui(page, path_to_yaml, username=None, password=None, login=False, prints=False):
    if prints:
        print(f"\tParsing YAML file {path_to_yaml} for disk file data")
    form_data = retrieve_ova_data(path_to_yaml)

    ova_files = form_data.get("diskfiles", [])
    for ova_file in ova_files:
        file_path = ova_file.get("ova_path")
        if not file_path or not os.path.isfile(file_path):
            if prints:
                print(f"\tDisk file path {file_path} is invalid or does not exist, skipping upload")
            continue

        if prints:
            print(f"\tUploading disk file {file_path} via UI")
        upload_diskfile_ui(page, file_path, username, password, login=login, prints=prints)
        login = False  # Only login once at the start
