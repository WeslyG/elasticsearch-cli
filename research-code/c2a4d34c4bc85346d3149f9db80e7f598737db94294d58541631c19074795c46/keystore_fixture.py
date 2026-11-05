"""Bounded keystore file fixture inside the single task-owned ES container."""

import json
import re
import subprocess
from pathlib import Path

STORE = "/usr/share/elasticsearch/config/elasticsearch.keystore"


def docker_command(*arguments):
    result = subprocess.run(
        ["docker", *arguments], capture_output=True, text=True, timeout=20, check=True
    )
    return result.stdout.strip()


class OwnedKeystore:
    def __init__(self, output, node, lab, *, command=docker_command):
        if not re.fullmatch(r"[0-9a-f]{64}", node or "") or not lab:
            raise ValueError("Explicit owned node and lab identity required")
        self.output = Path(output)
        self.node, self.lab, self.command = node, lab, command
        self.data = {
            "kind": "owned-keystore-read-error-recovery-not-credential-rotation",
            "lab_id": lab,
            "node_container_id": node,
            "keystore_path": STORE,
            "keystore_bytes_exported": False,
            "restored": False,
        }
        self.directory = None
        self.ready = False
        if not self.output.is_dir():
            raise ValueError("Existing evidence output directory required")

    def save(self):
        (self.output / "keystore-reload-fixture.json").write_text(
            json.dumps(self.data, indent=2) + "\n"
        )

    def execute(self, *arguments):
        return self.command("exec", "-u", "0", self.node, *arguments)

    def checksum(self, path):
        digest = self.execute("sha256sum", path).split()[0]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Unexpected keystore digest")
        return digest

    def __enter__(self):
        labels = json.loads(
            self.command("inspect", "--format", "{{json .Config.Labels}}", self.node)
        )
        if labels.get("io.es-cli.research") != self.lab:
            raise ValueError("Refusing non-owned node keystore mutation")
        mounts = json.loads(self.command("inspect", "--format", "{{json .Mounts}}", self.node))
        for mount in mounts:
            destination = mount["Destination"].rstrip("/")
            if mount["Type"] == "bind" and (
                destination in {"/usr/share/elasticsearch/config", STORE}
                or STORE.startswith(destination + "/")
            ):
                raise ValueError("Refusing host-bound config mutation")
        if self.execute("stat", "-c", "%F", STORE) != "regular file":
            raise ValueError("Keystore must be a regular container file")
        size = int(self.execute("stat", "-c", "%s", STORE))
        if not 0 < size <= 1_048_576:
            raise ValueError("Unexpected keystore fixture size")
        self.data.update(original_size=size, original_sha256=self.checksum(STORE))
        self.data["original_permissions"] = self.execute("stat", "-c", "%a:%u:%g", STORE)
        if not re.fullmatch(r"[0-7]{3,4}:[0-9]+:[0-9]+", self.data["original_permissions"]):
            raise ValueError("Unexpected keystore ownership/permissions")
        directory = self.execute("mktemp", "-d", "/tmp/es-cli-keystore.XXXXXXXX")
        if not re.fullmatch(r"/tmp/es-cli-keystore\.[A-Za-z0-9]+", directory):
            raise ValueError("Temporary keystore path escaped owned directory")
        self.directory = directory
        self.backup = directory + "/original"
        self.data["backup_directory"] = directory
        try:
            self.execute("cp", "-p", STORE, self.backup)
            self.data["backup_sha256"] = self.checksum(self.backup)
            if self.data["backup_sha256"] != self.data["original_sha256"]:
                raise ValueError("Keystore backup differs; no corruption attempted")
        except BaseException:
            self.execute("rm", "-f", directory + "/original")
            self.execute("rmdir", directory)
            self.save()
            raise
        self.ready = True
        self.save()
        return self

    def corrupt(self):
        if not self.ready:
            raise ValueError("Verified owned backup required before corruption")
        self.execute("/bin/sh", "-c", "printf '%s' 'es-cli-invalid-keystore' > " + STORE)
        self.data["corrupt_sha256"] = self.checksum(STORE)
        if self.data["corrupt_sha256"] == self.data["original_sha256"]:
            raise ValueError("Keystore corruption did not change bytes")
        self.data["corruption_applied"] = True
        self.save()

    def __exit__(self, exception_type, exception, traceback):
        try:
            self.execute("cp", "-p", self.backup, STORE)
            restored = self.checksum(STORE)
            self.data["restored_sha256"] = restored
            if restored != self.data["original_sha256"]:
                raise ValueError("Keystore restore digest differs; backup retained")
            permissions = self.execute("stat", "-c", "%a:%u:%g", STORE)
            self.data["restored_permissions"] = permissions
            if permissions != self.data["original_permissions"]:
                raise ValueError("Keystore restore permissions differ; backup retained")
            self.data["restored"] = True
            self.execute("rm", "-f", self.backup)
            self.execute("rmdir", self.directory)
            self.data["backup_removed"] = True
        except BaseException as error:
            self.data["restore_error"] = type(error).__name__ + ": " + str(error)[:400]
            raise
        finally:
            self.ready = False
            self.save()
