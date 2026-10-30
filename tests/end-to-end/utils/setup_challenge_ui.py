"""Create only disposable exercise definitions supplied by the rehearsal operator."""
from .login_user_ui import login_user_ui, open_page
from .upload_diskfile_ui import upload_all_diskfiles_ui
from tools.challenges.yaml_parser import yaml_to_dict


def setup_challenge_ui(page, path_to_yaml, username=None, password=None, login=False, upload_ova_files=False, prints=False):
    if login:
        login_user_ui(page, username, password)
    if upload_ova_files:
        upload_all_diskfiles_ui(page, path_to_yaml)
    definition = yaml_to_dict(path_to_yaml)
    open_page(page, '/create-ctf')
    page.locator('input[name=name]').fill(definition['name'])
    page.locator('textarea[name=description]').fill(definition['description'])
    page.locator('select[name=category]').select_option(definition['category'])
    page.locator('select[name=difficulty]').select_option(definition['difficulty'])
    page.locator('textarea[name=hint]').fill(definition['hint'])
    page.locator('textarea[name=solution]').fill(definition['solution'])
    page.locator('input[name=isActive]').set_checked(bool(definition['isActive']))
    for index, vm in enumerate(definition['vms'], 1):
        page.get_by_role('button', name='Add machine').click()
        group = page.get_by_role('group', name=f'Machine {index}', exact=True)
        group.get_by_label('Machine name').fill(vm['name'])
        group.get_by_label('OVA artifact').select_option(vm['ova_name'])
        group.get_by_label('CPU cores').fill(str(vm['cores']))
        group.get_by_label('Memory (GiB)').fill(str(vm['ram_gb']))
        group.get_by_label('Domain name').fill(vm['domain_name'])
        group.get_by_label('Directory role').select_option(vm.get('ad_role', 'none'))
    for index, network in enumerate(definition['subnets'], 1):
        page.get_by_role('button', name='Add network').click()
        group = page.get_by_role('group', name=f'Network {index}', exact=True)
        group.get_by_label('Network name').fill(network['name'])
        group.get_by_label('Student accessible').set_checked(bool(network['accessible']))
        group.get_by_label('DMZ', exact=True).set_checked(bool(network['dmz']))
        for name in network['attached_vms']:
            group.get_by_label(name, exact=True).check()
    for index, flag in enumerate(sorted(definition['flags'], key=lambda f: f['order_index']), 1):
        page.get_by_role('button', name='Add flag').click()
        group = page.get_by_role('group', name=f'Flag {index}', exact=True)
        group.get_by_label('Flag value').fill(flag['flag'])
        group.get_by_label('Flag description').fill(flag['description'])
        group.get_by_label('Points', exact=True).fill(str(flag['points']))
        if flag.get('vm_name'):
            group.get_by_label('Machine', exact=True).select_option(label=flag['vm_name'])
        group.get_by_label('Generate a student-specific flag').set_checked(bool(flag['user_specific']))
    for index, hint in enumerate(sorted(definition['hints'], key=lambda h: h['order_index']), 1):
        page.get_by_role('button', name='Add hint').click()
        group = page.get_by_role('group', name=f'Hint {index}', exact=True)
        group.get_by_label('Hint text').fill(hint['hint_text'])
        group.get_by_label('Unlock after points earned').fill(str(hint['unlock_points']))
    page.get_by_role('button', name='Create challenge', exact=False).click()
    page.wait_for_url('**/manage-ctf', timeout=20*60*1000)
    return definition['name']
