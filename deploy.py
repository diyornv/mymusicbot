"""
Deploy script — uploads files directly via SFTP, installs deps in a venv,
creates .env, and sets up a systemd service.
"""

import paramiko
import time
from pathlib import Path

HOST = "164.90.218.212"
USER = "root"
PASSWORD = "tEleg1am_Bot"
APP_DIR = "/opt/mymusicbot"
VENV_DIR = f"{APP_DIR}/venv"
PYTHON = f"{VENV_DIR}/bin/python3"

# Files to upload (relative to project root)
PROJECT_FILES = [
    "bot.py",
    "config.py",
    "metadata.py",
    "requirements.txt",
    "assets/channel_cover.png",
]

ENV_CONTENT = (
    "BOT_TOKEN=8648574943:AAFnVlG9D6Yx32b6zKxkfap7XnY8B7DPmN0\n"
    "CHANNEL_ID=-1001906240835\n"
    "COVER_IMAGE_PATH=assets/channel_cover.png\n"
)

SYSTEMD_UNIT = (
    "[Unit]\n"
    "Description=BASS_MIDAS Telegram Music Bot\n"
    "After=network.target\n"
    "\n"
    "[Service]\n"
    "Type=simple\n"
    f"WorkingDirectory={APP_DIR}\n"
    f"ExecStart={PYTHON} {APP_DIR}/bot.py\n"
    "Restart=always\n"
    "RestartSec=5\n"
    "StandardOutput=journal\n"
    "StandardError=journal\n"
    "\n"
    "[Install]\n"
    "WantedBy=multi-user.target\n"
)


def run(ssh, cmd, check=True):
    print(f"  $ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=120)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    code = stdout.channel.recv_exit_status()
    if out:
        for line in out.split("\n")[:20]:
            print(f"    {line}")
    if err and code != 0:
        for line in err.split("\n")[:10]:
            print(f"    [stderr] {line}")
    if check and code != 0:
        print(f"    !!! Exit code: {code}")
    return out, err, code


def main():
    project_root = Path(__file__).resolve().parent

    print(f"Connecting to {HOST}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=15)
    print("Connected!\n")

    # 1. Stop existing service if running
    print("Stopping existing service (if any)...")
    run(ssh, "systemctl stop musicbot.service 2>/dev/null || true", check=False)

    # 2. Create app directory
    print(f"\nCreating {APP_DIR}...")
    run(ssh, f"rm -rf {APP_DIR}")
    run(ssh, f"mkdir -p {APP_DIR}/assets {APP_DIR}/tmp")

    # 3. Upload files via SFTP
    print("\nUploading project files via SFTP...")
    sftp = ssh.open_sftp()
    for rel_path in PROJECT_FILES:
        local_path = project_root / rel_path
        remote_path = f"{APP_DIR}/{rel_path}"
        print(f"  -> {rel_path}")
        sftp.put(str(local_path), remote_path)

    # 4. Write .env directly
    print("  -> .env")
    with sftp.open(f"{APP_DIR}/.env", "w") as f:
        f.write(ENV_CONTENT)

    sftp.close()
    print("Upload complete!\n")

    # 5. Create venv and install deps (avoids system package conflicts)
    print("Creating virtual environment...")
    run(ssh, f"python3 -m venv {VENV_DIR}")
    print("Installing Python dependencies in venv...")
    run(ssh, f"{VENV_DIR}/bin/pip install -r {APP_DIR}/requirements.txt -q")

    # 6. Write systemd service
    print("\nSetting up systemd service...")
    sftp2 = ssh.open_sftp()
    with sftp2.open("/etc/systemd/system/musicbot.service", "w") as f:
        f.write(SYSTEMD_UNIT)
    sftp2.close()

    run(ssh, "systemctl daemon-reload")
    run(ssh, "systemctl enable musicbot.service")
    run(ssh, "systemctl restart musicbot.service")

    # 7. Verify
    time.sleep(3)
    print("\nChecking bot status...")
    run(ssh, "systemctl status musicbot.service --no-pager -l")

    print("\nRecent logs...")
    run(ssh, "journalctl -u musicbot.service -n 10 --no-pager")

    ssh.close()
    print("\nDeployment complete!")


if __name__ == "__main__":
    main()
