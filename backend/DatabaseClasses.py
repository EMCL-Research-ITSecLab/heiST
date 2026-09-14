from backend.subnet_calculations import nth_machine_ip


class ChallengeTemplate:
    def __init__(self, challenge_template_id):
        self.id = challenge_template_id
        self.machine_templates = {}
        self.network_templates = {}
        self.connection_templates = {}
        self.domain_templates = {}
        self.challenge_subnet = None
        self.flags = []

    def add_machine_template(self, machine_template):
        self.machine_templates[machine_template.id] = machine_template

    def add_network_template(self, network_template):
        self.network_templates[network_template.id] = network_template

    def add_connection_template(self, connection_template):
        self.connection_templates[(connection_template.machine_template.id, connection_template.network_template.id)] \
            = connection_template

    def add_domain_template(self, domain_template):
        self.domain_templates[(domain_template.machine_template.id, domain_template.domain)] = domain_template

    def set_challenge_subnet(self, challenge_subnet):
        self.challenge_subnet = challenge_subnet


class MachineTemplate:
    def __init__(self, machine_template_id, challenge_template):
        self.id = machine_template_id
        self.challenge_template = challenge_template
        self.connected_networks = {}
        self.domain_templates = {}
        self.child = None
        self.disk_file_path = None
        self.cores = 1
        self.ram = 1024
        self.guest_os = 'linux'

    def add_connected_network(self, network):
        self.connected_networks[network.id] = network

    def set_child(self, child):
        self.child = child

    def add_domain_template(self, domain_template):
        self.domain_templates[(domain_template.machine_template.id, domain_template.domain)] = domain_template

    def set_disk_file_path(self, disk_file_path):
        self.disk_file_path = disk_file_path

    def set_cores(self, cores):
        self.cores = cores

    def set_ram(self, ram):
        self.ram = ram

    def set_guest_os(self, guest_os):
        self.guest_os = guest_os


class NetworkTemplate:
    def __init__(self, network_template_id, accessible):
        self.id = network_template_id
        self.accessible = accessible
        self.connected_machines = {}
        self.is_dmz = False

    def add_connected_machine(self, machine):
        self.connected_machines[machine.id] = machine

    def set_is_dmz(self, is_dmz):
        self.is_dmz = is_dmz


class ConnectionTemplate:
    def __init__(self, machine_template, network_template):
        self.machine_template = machine_template
        self.network_template = network_template

    def set_machine_template(self, machine_template):
        self.machine_template = machine_template

    def set_network_template(self, network_template):
        self.network_template = network_template


class DomainTemplate:
    def __init__(self, machine_template, domain):
        self.machine_template = machine_template
        self.domain = domain


class Challenge:
    def __init__(self, challenge_id, template, subnet):
        self.id = challenge_id
        self.template = template
        self.subnet = subnet
        self.subnet_ip = subnet[:-3]
        self.subnet_mask = subnet[-2:]

        self.machines = {}
        self.networks = {}
        self.connections = {}
        self.domains = {}
        self.challenge_subnet = None

    def add_machine(self, machine):
        self.machines[machine.id] = machine

    def add_network(self, network):
        self.networks[network.id] = network

    def add_connection(self, connection):
        self.connections[(connection.machine.id, connection.network.id)] = connection

    def add_domain(self, domain):
        self.domains[(domain.machine.id, domain.domain)] = domain

    def set_challenge_subnet(self, challenge_subnet):
        self.challenge_subnet = challenge_subnet


class Machine:
    def __init__(self, machine_id, template, challenge):
        self.id = machine_id
        self.template = template
        self.challenge = challenge

        self.connections = {}
        self.domains = []

    def add_connection(self, connection):
        self.connections[(connection.machine.id, connection.network.id)] = connection

    def add_domain(self, domain):
        self.domains.append(domain.domain)


class Network:
    def __init__(self, network_id, template, subnet, host_device, accessible):
        self.id = network_id
        self.template = template
        self.subnet = subnet
        self.host_device = host_device
        self.accessible = accessible

        self.subnet_ip, self.subnet_mask = self.subnet.split("/")
        self.connections = {}

        self.router_ip = nth_machine_ip(self.subnet_ip, 1, True)
        self.available_start_ip = nth_machine_ip(self.subnet_ip, 2)
        self.available_end_ip = nth_machine_ip(self.subnet_ip, 2**4 - 2)

        self.is_dmz = False

    def add_connection(self, connection):
        self.connections[(connection.machine.id, connection.network.id)] = connection

    def set_is_dmz(self, is_dmz):
        self.is_dmz = is_dmz


class Connection:
    def __init__(self, machine, network, client_mac, client_ip):
        self.machine = machine
        self.network = network
        self.client_mac = client_mac
        self.client_ip = client_ip


class Domain:
    def __init__(self, machine, domain):
        self.machine = machine
        self.domain = domain


class ChallengeSubnet:
    def __init__(self, subnet):
        self.subnet = subnet