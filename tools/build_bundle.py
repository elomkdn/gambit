#!/usr/bin/env python3
"""Build the Flatpak bundle the way the manifest describes, without flatpak-builder.

Each module's build commands run in `flatpak build` against the Luma SDK: Stockfish
in its extracted, checksum-verified archive, Gambit in a fresh clone of the commit
the manifest pins (or in the given source tree while the manifest says "dir").

Usage: python3 -I tools/build_bundle.py SOURCE_TREE STOCKFISH_ARCHIVE WORK_DIR OUTPUT.flatpak
"""
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path


def run(*args, **kw):
    subprocess.run(args, check=True, **kw)


def main(source, archive, work, output):
    source, archive, work = Path(source).resolve(), Path(archive).resolve(), Path(work).resolve()
    manifest = json.loads((source / "flatpak" / "io.github.elomkdn.Gambit.json").read_text())
    app = work / "app"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    run("flatpak", "build-init", str(app), manifest["id"], f"{manifest['sdk']}//{manifest['runtime-version']}",
        f"{manifest['runtime']}//{manifest['runtime-version']}", stdout=subprocess.DEVNULL)
    for module in manifest["modules"]:
        src = module["sources"][0]
        if src["type"] == "archive":
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            if digest != src["sha256"]:
                raise SystemExit(f"{archive.name}: sha256 {digest} does not match the manifest")
            with tarfile.open(archive) as tar:
                tar.extractall(work / module["name"], filter="data")
            tree = next((work / module["name"]).iterdir())
        elif src["type"] == "git":
            tree = work / module["name"]
            run("git", "clone", "--quiet", src["url"], str(tree))
            run("git", "-C", str(tree), "checkout", "--quiet", "--detach", src["commit"])
        else:
            tree = source
        script = "set -e\n" + "\n".join(module["build-commands"]).replace("${FLATPAK_BUILDER_N_JOBS}", "4")
        run("flatpak", "build", f"--filesystem={tree}", f"--build-dir={tree}", str(app), "sh", "-ec", script)
    finish = [f for f in manifest["finish-args"]]
    run("flatpak", "build-finish", str(app), f"--command={manifest['command']}", *finish, stdout=subprocess.DEVNULL)
    run("flatpak", "build-export", str(work / "repo"), str(app), stdout=subprocess.DEVNULL)
    run("flatpak", "build-bundle", "--runtime-repo=https://dl.simplyluma.com/luma.flatpakrepo", str(work / "repo"),
        str(Path(output).resolve()), manifest["id"])
    print("bundle:", output)


if __name__ == "__main__":
    main(*sys.argv[1:5])
