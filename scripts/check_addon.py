"""Controle van de add-on-bestanden (draait in CI). Gebruik: check_addon.py [--tag vX.Y.Z]"""
import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ADDON = ROOT / "goedkoop-tanken"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag")
    tag = ap.parse_args().tag
    errors = []
    cfg = yaml.safe_load((ADDON / "config.yaml").read_text(encoding="utf-8"))
    yaml.safe_load((ROOT / "repository.yaml").read_text(encoding="utf-8"))
    yaml.safe_load((ADDON / "translations" / "nl.yaml").read_text(encoding="utf-8"))
    for key in ("name", "version", "slug", "arch", "ingress", "ingress_port", "image"):
        if key not in cfg:
            errors.append(f"config.yaml mist '{key}'")
    if set(cfg.get("arch", [])) != {"aarch64", "amd64"}:
        errors.append("arch moet aarch64 en amd64 zijn")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(cfg.get("version", ""))):
        errors.append("version moet X.Y.Z zijn")
    if tag and tag.lstrip("v") != str(cfg.get("version")):
        errors.append(f"tag {tag} komt niet overeen met version {cfg.get('version')} in config.yaml")
    if tag and "GITHUB_GEBRUIKER" in (ADDON / "config.yaml").read_text(encoding="utf-8"):
        errors.append("vervang GITHUB_GEBRUIKER in config.yaml, repository.yaml en Dockerfile")
    for rel in ("rootfs/etc/services.d/goedkoop-tanken/run", "rootfs/etc/services.d/goedkoop-tanken/finish"):
        p = ADDON / rel
        if not p.exists():
            errors.append(f"{rel} ontbreekt")
        elif not p.read_text(encoding="utf-8").startswith("#!/command/with-contenv bashio"):
            errors.append(f"{rel} moet beginnen met #!/command/with-contenv bashio")
    for rel in ("icon.png", "logo.png"):
        if not (ADDON / rel).exists():
            errors.append(f"{rel} ontbreekt (pictogram en logo van de add-on)")
    if f"## {cfg.get('version')}" not in (ADDON / "CHANGELOG.md").read_text(encoding="utf-8"):
        errors.append("CHANGELOG.md heeft geen kop voor deze versie")
    for e in errors:
        print("FOUT:", e)
    print("Add-on-controle:", "mislukt" if errors else "in orde")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
