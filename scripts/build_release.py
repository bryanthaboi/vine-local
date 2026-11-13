"""Build a manual-install archive from integration sources only."""

import hashlib
import json
import zipfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    component = root / "custom_components/vine_local"
    version = json.loads((component / "manifest.json").read_text())["version"]
    destination = root / "dist"
    destination.mkdir(exist_ok=True)
    archive_path = destination / f"vine_local-{version}.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(component.rglob("*")):
            if (
                path.is_file()
                and path.suffix in (".py", ".json", ".png", ".svg")
                and "__pycache__" not in path.parts
            ):
                archive.write(path, path.relative_to(root))
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    (destination / "SHA256SUMS").write_text(f"{digest}  {archive_path.name}\n")
    print(f"PASS built {archive_path.name}")


if __name__ == "__main__":
    main()
