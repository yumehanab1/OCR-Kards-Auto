"""Package an explicit mobile-engine subset without a host input backend.

Run --refresh after reviewing a deliberate source update. The default --check
mode is read-only and rejects changed, missing, or extra packaged files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

PROJECT = Path(__file__).resolve().parents[2]
DESTINATION = PROJECT / "android-app/app/src/main/assets/mobile-core"
MANIFEST = DESTINATION / "manifest.json"
MODULES = (
    "actions", "board", "cv_io", "hq_hp", "kredits", "kredits_templates",
    "mobile_attack", "mobile_board", "mobile_combat_policy",
    "mobile_combat_vision", "mobile_end_button", "mobile_hand", "mobile_trace",
    "platformapi", "turn_engine_mobile", "ui_state", "unit_state",
)
TEMPLATE_STATES = (
    "main_menu", "deck_select", "queueing", "mulligan", "ingame",
    "victory", "defeat", "combat", "hq_aux",
)
FORBIDDEN_MODULES = (
    "platform_android.py", "platform_win.py", "win.py", "adb_local.py",
    "main_loop.py", "gui.py", "ondevice.py",
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inputs() -> list[str]:
    paths = {f"src/{name}.py" for name in MODULES}
    paths.update(("config/board_android.json", "config/states.json"))
    for state in TEMPLATE_STATES:
        relative = f"config/templates.android.{state}.json"
        paths.add(relative)
        config = json.loads((PROJECT / relative).read_text(encoding="utf-8"))
        for entry in config["templates"].values():
            path = Path(entry["path"])
            if path.is_absolute() or ".." in path.parts or path.parts[0] != "ui_templates":
                raise ValueError(f"Unexpected template source: {path}")
            paths.add(path.as_posix())
    paths.add("config/hq_hp_digits/BORROWED.txt")
    for digit in range(10):
        for path in sorted((PROJECT / f"config/hq_hp_digits/{digit}").glob("*.png")):
            paths.add(path.relative_to(PROJECT).as_posix())
    # These are the exact anchors consumed by kredits_templates.SAMPLE_TO_DIGIT.
    for sample in (0, 1, 2, 3, 4, 6, 7, 8, 9, 10):
        paths.add(f"shots/kredits/samples_r1/n_{sample:02d}_mask.png")
    return sorted(paths)


def inventory() -> dict:
    records = []
    for relative in inputs():
        source = (PROJECT / relative).resolve(strict=True)
        source.relative_to(PROJECT)
        data = source.read_bytes()
        records.append({"path": relative, "size": len(data), "sha256": digest(data)})
    canonical = json.dumps(records, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return {
        "schema_version": 1,
        "source": "Shared mobile production tree; copied without modification",
        "maintenance_line": "APK embedded mobile copy; PC source maintained independently",
        "runtime": {"python": "3.10", "numpy": "1.26.2", "opencv_python": "4.5.1.48"},
        "excluded_input_backends": list(FORBIDDEN_MODULES),
        "required_adapter": "APK registers its own win shim and platformapi platform before core imports",
        "content_sha256": digest(canonical),
        "files": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="copy reviewed source subset and manifest")
    parser.add_argument("--check", action="store_true", help="read-only integrity check (default)")
    parser.add_argument("--packaged-only", action="store_true", help="verify the self-contained reviewed payload without its original external source tree")
    args = parser.parse_args()
    if args.packaged_only and args.refresh:
        parser.error("--refresh requires the original reviewed source tree")
    expected = json.loads(MANIFEST.read_text(encoding="utf-8")) if args.packaged_only else inventory()
    records = expected["files"]
    canonical = json.dumps(records, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if expected.get("content_sha256") != digest(canonical):
        raise SystemExit("Manifest content hash mismatch")
    for record in records:
        path = Path(record["path"])
        if path.is_absolute() or ".." in path.parts or path.as_posix() == "manifest.json":
            raise SystemExit("Unsafe packaged payload path")
    if args.refresh:
        DESTINATION.mkdir(parents=True, exist_ok=True)
        for record in expected["files"]:
            target = DESTINATION / record["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PROJECT / record["path"], target)
        MANIFEST.write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    actual = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if actual != expected:
        raise SystemExit("Manifest/source mismatch: review changes, then use --refresh explicitly")
    permitted = {r["path"] for r in expected["files"]} | {"manifest.json"}
    existing = {p.relative_to(DESTINATION).as_posix() for p in DESTINATION.rglob("*") if p.is_file()}
    if existing != permitted:
        raise SystemExit(f"Packaged file set mismatch: extra={sorted(existing-permitted)}, missing={sorted(permitted-existing)}")
    for record in expected["files"]:
        data = (DESTINATION / record["path"]).read_bytes()
        if len(data) != record["size"] or digest(data) != record["sha256"]:
            raise SystemExit(f"Packaged hash mismatch: {record['path']}")
    if any((DESTINATION / "src" / name).exists() for name in FORBIDDEN_MODULES):
        raise SystemExit("Host backend was incorrectly packaged")
    print(json.dumps({"files": len(expected["files"]), "bytes": sum(r["size"] for r in expected["files"]),
                      "content_sha256": expected["content_sha256"], "check": "passed"}))


if __name__ == "__main__":
    main()
