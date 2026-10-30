# 🐳➡️ Converting a Docker Image into a Virtual Machine

This guide walks you through converting a Docker image into a virtual machine (VM), preparing the environment manually by setting up environment variables, networking, DNS, and an init service.

---

## 1. ✅ Set Environment Variables via `/etc/environment`

Edit the file `/etc/environment` to define persistent environment variables for all users:

```bash
sudo nano /etc/environment
```

Add your variables in the format:

```bash
MY_VAR=value
ANOTHER_VAR=123
```

Changes take effect at the next login or reboot.

---

## 2. 🌐 Configure Networking with Netplan

Modify your Netplan config, usually found under `/etc/netplan/`. Edit or create a YAML file, e.g., `/etc/netplan/01-netcfg.yaml`:

```bash
sudo nano /etc/netplan/01-netcfg.yaml
```

Example static IP config:

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    en-all:
      match:
        name: "en*"
      dhcp4: true
      dhcp4-overrides:
        use-dns: true
```

Apply the config:

```bash
sudo netplan apply
```

---

## 3. 🔗 Fix DNS Resolution

Ensure `/etc/resolv.conf` is correctly linked to `systemd-resolved`.

### Step-by-step:

```bash
sudo rm -f /etc/resolv.conf
sudo ln -s /run/systemd/resolve/resolv.conf /etc/resolv.conf
```

Restart `systemd-resolved`:

```bash
sudo systemctl restart systemd-resolved
```

You can verify it with:

```bash
cat /etc/resolv.conf
```

---

## 4. 🛠️ Set Up an Init Service with systemd

Create a systemd service to initialize your app or container environment at boot.

### Example: `/etc/systemd/system/init.service`

```ini
[Unit]
Description=My Custom Startup Command
After=network.target

[Service]
Type=simple
ExecStart=/path/to/binary argument1 argument2
Restart=on-failure
WorkingDirectory=/home/someuser/
User=someuser

[Install]
WantedBy=multi-user.target
```

Enable the service:

```bash
sudo systemctl enable init.service
sudo systemctl start init.service
```

---

## 💡 Notes

- You should copy the Docker image’s contents into the VM filesystem before following these steps.
- If you're using QEMU to run your VM, ensure correct disk and network interfaces are attached.
- To copy volume data from Docker, you can use `docker cp` or mount the volumes manually.
