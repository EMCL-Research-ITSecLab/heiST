def nth_subnet(subnet: str, n: int, start_subnet_mask, end_subnet_mask) -> str:
    """
    Calculate the nth subnet of a given subnet.
    """

    if "/" in subnet:
        if int(subnet.split("/")[1]) != start_subnet_mask:
            raise ValueError(f"Ambiguous subnet mask: {subnet}. Expected {start_subnet_mask} but found {subnet.split('/')[1]}")

        subnet = subnet.split("/")[0]

    def ip_to_binary(ip: str) -> str:
        """Convert an IP address to binary."""
        return ''.join(format(int(octet), '08b') for octet in ip.split('.'))

    def binary_to_ip(binary: str) -> str:
        """Convert binary to IP address."""
        return '.'.join(str(int(binary[i:i + 8], 2)) for i in range(0, 32, 8))

    ip_bin = ip_to_binary(subnet)
    n_bin = bin(n)[2:].zfill(end_subnet_mask - start_subnet_mask)

    network_bin = ip_bin[:start_subnet_mask] + n_bin + '0' * (32 - end_subnet_mask)

    return binary_to_ip(network_bin) + "/" + str(end_subnet_mask)


def nth_challenge_subnet(subnet: str, n: int) -> str:
    """
    Calculate the nth challenge subnet.
    """
    return nth_subnet(subnet, n, 9, 24)


def nth_network_subnet(subnet: str, n: int) -> str:
    """
    Calculate the nth network subnet.
    """
    return nth_subnet(subnet, n, 24, 28)


def nth_machine_ip(subnet: str, n: int, router_or_broadcast: bool = False) -> str:
    """
    Calculate the nth network subnet.
    """

    if (n <= 0 or n >= 15) and not router_or_broadcast:
        raise ValueError("n must be between 1 and 14 (inclusive)")

    return nth_subnet(subnet, n, 28, 32)[:-3]  # Remove the /32 from the end


def nth_vpn_static_ip(subnet: str, n: int) -> str:
    """
    Calculate the nth VPN static IP.
    """
    if n <= 1 or n >= 2**(32-10) - 1:
        raise ValueError("n must be between 2 and 2**(32-10) - 1 (inclusive)")

    return nth_subnet(subnet, n, 10, 32)[:-3]  # Remove the /32 from the end
