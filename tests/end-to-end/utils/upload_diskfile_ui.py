from pathlib import Path
from .login_user_ui import login_user_ui, open_page
from tools.challenges.yaml_parser import retrieve_ova_data


def upload_diskfile_ui(page, file_path, username=None, password=None, login=False, prints=False, guest_os='linux'):
    if login:
        login_user_ui(page, username, password)
    open_page(page, '/upload-diskfile')
    page.get_by_label('OVA or OVF file').set_input_files(str(Path(file_path).resolve(strict=True)))
    page.get_by_label('Guest operating system').select_option(guest_os)
    page.get_by_role('button', name='Upload artifact').click()
    page.get_by_text('Artifact uploaded and validated.', exact=False).wait_for(timeout=20*60*1000)


def upload_all_diskfiles_ui(page, path_to_yaml, username=None, password=None, login=False, prints=False):
    if login:
        login_user_ui(page, username, password)
    for artifact in retrieve_ova_data(path_to_yaml):
        upload_diskfile_ui(page, artifact['path'], prints=prints)
