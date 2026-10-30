"""Selectors shared by explicit, live exercise rehearsals against the React UI."""
import os

BASE_URL = os.environ.get('HEIST_URL', 'https://localhost').rstrip('/')


def login_user_ui(page, username, password, prints=False):
    if not username or not password:
        raise ValueError('Provide a dedicated rehearsal account')
    page.goto(BASE_URL + '/login')
    page.locator('input[name=username]').fill(username)
    page.locator('input[name=password]').fill(password)
    page.get_by_role('button', name='Sign in').click()
    page.wait_for_url('**/dashboard', timeout=30000)


def open_page(page, path):
    page.goto(BASE_URL + path)
    page.get_by_role('main').get_by_role('heading').first.wait_for()
