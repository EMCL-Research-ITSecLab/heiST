from .login_user_ui import login_user_ui, open_page


def delete_diskfile_ui(page, display_name, username=None, password=None, login=False, prints=False):
    if login:
        login_user_ui(page, username, password)
    open_page(page, '/upload-diskfile')
    row = page.get_by_role('row').filter(has=page.get_by_text(display_name, exact=True))
    row.get_by_role('button', name='Delete', exact=True).click()
    page.get_by_role('dialog').get_by_role('button', name='Delete artifact', exact=True).click()
    row.wait_for(state='detached', timeout=120000)
