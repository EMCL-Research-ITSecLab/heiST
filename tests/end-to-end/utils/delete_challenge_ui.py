from .login_user_ui import login_user_ui, open_page


def delete_challenge_ui(page, challenge_name, username=None, password=None, login=False, prints=False):
    if login:
        login_user_ui(page, username, password)
    open_page(page, '/manage-ctf')
    row = page.get_by_role('row').filter(has=page.get_by_role('link', name=challenge_name, exact=True))
    row.get_by_role('button', name='Delete', exact=True).click()
    page.get_by_role('dialog').get_by_role('button', name='Delete challenge and instances', exact=True).click()
    row.wait_for(state='detached', timeout=10*60*1000)
