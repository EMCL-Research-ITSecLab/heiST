from .login_user_ui import login_user_ui, open_page


def delete_user_ui(page, username=None, password=None, login=False, prints=False):
    if not password:
        raise ValueError('Provide the disposable account password')
    if login:
        login_user_ui(page, username, password)
    open_page(page, '/profile')
    page.get_by_role('button', name='Delete my account').click()
    dialog = page.get_by_role('dialog')
    dialog.get_by_label('Current password').fill(password)
    dialog.get_by_role('button', name='Delete account', exact=True).click()
    page.wait_for_url('**/landing', timeout=120000)
