"""Pure ownership labels shared by provisioning and checkpointed migration."""

def ownership_marker(identifier, *, template=False):
    if type(identifier) is not int or identifier<=0:
        raise ValueError('Invalid managed VM identifier')
    return 'Managed by heiST; '+('machine-template=' if template else 'machine=')+str(identifier)


def ownership_tags(identifier,existing=''):
    ownership_marker(identifier)
    tags={value for value in existing.split(';') if value and not value.startswith('heist-vm-')}
    tags.update(('heist-managed','heist-vm-'+str(identifier)))
    return ';'.join(sorted(tags))


