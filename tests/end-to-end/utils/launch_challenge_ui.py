from .login_user_ui import login_user_ui, open_page


def launch_challenge_ui(page, challenge_name, username=None, password=None, login=False, prints=False):
    if login:
        login_user_ui(page, username, password)
    open_page(page, '/explore')
    page.get_by_label('Search challenges').fill(challenge_name)
    page.get_by_role('button', name='Search', exact=True).click()
    page.get_by_role('link').filter(has=page.get_by_role('heading', name=challenge_name, exact=True)).click()
    page.get_by_role('button', name='Start investigation', exact=False).click()
    page.get_by_role('button', name='Stop this instance').wait_for(timeout=20*60*1000)
