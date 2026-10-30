"""Operator-selected CPU baseline for newly imported challenge templates."""
import os
import re


def challenge_cpu_type(environment=None):
    environment = os.environ if environment is None else environment
    value = environment.get('CHALLENGE_VM_CPU_TYPE', 'kvm64')
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', value):
        raise ValueError('CHALLENGE_VM_CPU_TYPE must name a Proxmox CPU model, for example host or x86-64-v2-AES')
    return value
