def yaml_to_create_challenge_form_data(path_to_yaml, prints=False):
    import json
    import yaml
    from yaml import SafeLoader

    with open(path_to_yaml, "r", encoding="utf-8") as file:
        data = yaml.load(file, Loader=SafeLoader)['ctf']

    if prints:
        print("\tRetrieving basic challenge info")
    form_data = {
        "name": data.get("name", ""),
        "description": data.get("description", ""),
        "category": data.get("category", ""),
        "difficulty": data.get("difficulty", ""),
        "hint": data.get("hint", ""),
        "solution": data.get("solution", ""),
        "isActive": data.get("is_active", True),
        "vms": [],
        "subnets": [],
        "flags": [],
        "hints": []
    }

    if prints:
        print("\tProcessing VMs")
    for name, vm_data in data.get("vms", {}).items():
        vm_entry = {
            "name": name,
            "ova_name": vm_data.get("ova_name", ""),
            "cores": vm_data.get("cores", 1),
            "ram_gb": vm_data.get("ram_gb", 1),
            "domain_name": vm_data.get("domain_name", ""),
        }
        form_data["vms"].append(vm_entry)
    form_data["vms"] = json.dumps(form_data["vms"])
    
    if prints:
        print("\tProcessing Subnets")
    for name, subnet_data in data.get("subnets", {}).items():
        subnet_entry = {
            "name": name,
            "dmz": subnet_data.get("dmz", False),
            "accessible": subnet_data.get("accessible", False),
            "attached_vms": subnet_data.get("attached_vms", [])
        }
        form_data["subnets"].append(subnet_entry)
    form_data["subnets"] = json.dumps(form_data["subnets"])

    if prints:
        print("\tProcessing Flags")
    for flag_data in data.get("flags", []).values():
        flag_entry = {
            "flag": flag_data.get("flag", ""),
            "description": flag_data.get("description", ""),
            "points": flag_data.get("points", 0),
            "order_index": flag_data.get("order_index", 0),
            "user_specific": flag_data.get("user_specific", False),
            "vm_name": flag_data.get("vm_name", "")
        }
        form_data["flags"].append(flag_entry)
    form_data["flags"] = json.dumps(form_data["flags"])

    if prints:
        print("\tProcessing Hints")
    for hint_data in data.get("hints", []).values():
        hint_entry = {
            "hint_text": hint_data.get("hint_text", ""),
            "unlock_points": hint_data.get("unlock_points", 0),
            "order_index": hint_data.get("order_index", 0)
        }
        form_data["hints"].append(hint_entry)
    form_data["hints"] = json.dumps(form_data["hints"])

    if prints:
        print("\tFinished processing YAML data")
    return form_data


def yaml_to_dict(path_to_yaml, prints=False):
    form_data = yaml_to_create_challenge_form_data(path_to_yaml, prints=prints)
    import json
    form_data["vms"] = json.loads(form_data["vms"])
    form_data["subnets"] = json.loads(form_data["subnets"])
    form_data["flags"] = json.loads(form_data["flags"])
    form_data["hints"] = json.loads(form_data["hints"])

    return form_data




def retrieve_ova_data(path_to_yaml):
    import yaml
    from yaml import SafeLoader

    with open(path_to_yaml, "r", encoding="utf-8") as file:
        data = yaml.load(file, Loader=SafeLoader)['ctf']

    ova_files = []
    for vm_data in data.get("vms", {}).values():
        ova_name = vm_data.get("ova_name", "")
        ova_path = vm_data.get("ova_path", "")

        if ova_name and ova_path:
            ova_files.append({
                "name": ova_name,
                "path": ova_path
            })
        else:
            raise ValueError(f"VM entry missing 'ova_name' or 'ova_path': {vm_data}")

    return ova_files
