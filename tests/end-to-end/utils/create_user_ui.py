from .login_user_ui import open_page


def create_user_ui(page, username, email, password, prints=False):
    open_page(page, '/signup')
    page.locator('input[name=username]').fill(username)
    page.locator('input[name=email]').fill(email)
    page.locator('input[name=password]').fill(password)
    page.locator('input[name="confirm-password"]').fill(password)
    page.get_by_role('button', name='Create account').click()
    page.wait_for_url('**/dashboard', timeout=120000)
