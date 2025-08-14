# SPDX-FileCopyrightText: Copyright 2025 Cooper Dalrymple (@relic-se)
# SPDX-FileCopyrightText: 2025 Tim Cocks for Adafruit Industries
# SPDX-FileCopyrightText: Copyright 2024 Sam Blenny
#
# SPDX-License-Identifier: MIT
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

import requests
from circup.commands import main as circup_cli

ASSET_DIRS = (
    "bitmaps",
    "samples",
)

def run(cmd):
    result = subprocess.run(cmd, shell=True, check=True, capture_output=True)
    return result.stdout.decode('utf-8').strip()

def get_latest_repository_release_assets(name:str|dict) -> list:
    request_url = "https://api.github.com/repos/{}/releases/latest".format(name)
    release_response = requests.get(request_url, allow_redirects=True)
    release_data = release_response.json()
    return release_data["assets"]

def replace_tags(file:Path, data:dict) -> None:
    with open(file, "r") as f:
        contents = f.read()
    for key, value in data.items():
        contents = contents.replace("{{{}}}".format(key), value)
    with open(file, "w") as f:
        f.write(contents)

def main():

    # get github repository details
    git_remote = run("git config --get remote.origin.url")
    git_remote = re.sub(r'^git@github\.com:', "https://github.com/", git_remote)
    git_remote = re.sub(r'\.git$', "", git_remote)

    git_owner, git_name = re.findall(r'^https:\/\/github\.com\/([^\/]+)\/([^\/]+)$', git_remote)[0]

    try:
        git_commit = run('git rev-parse --short HEAD')
    except subprocess.CalledProcessError:
        git_commit = "NO_COMMIT"

    # read metadata
    with open("metadata.json", "r") as f:
        metadata = json.load(f)

    # get the project root directory
    root_dir = Path(__file__).parent

    # set up paths
    src_dir = root_dir / "src"
    output_dir = root_dir / "dist"
    asset_dirs = tuple([root_dir / x for x in ASSET_DIRS])

    # delete output dir if it exists
    if output_dir.exists():
        shutil.rmtree(output_dir)

    # create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # create output zip filename
    output_zip = str(output_dir / git_name) + "-{}.zip".format(git_commit)
    
    # create a clean temporary directory for building the zip
    temp_dir = output_dir / "temp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)

    temp_root_dir = temp_dir / git_name
    temp_root_dir.mkdir(parents=True)

    # copy and format bundle readme
    shutil.copyfile("README_bundle.txt", temp_root_dir / "README.txt")
    replace_tags(temp_root_dir / "README.txt", {
        "name": git_name,
        "guide_url": metadata["guide_url"],
        "git_remote": git_remote,
        "git_commit": git_commit,
    })

    try:
        for asset in get_latest_repository_release_assets("adafruit/Adafruit_CircuitPython_Bundle"):
            bundle_version = re.findall(r'^adafruit-circuitpython-bundle-(\d+.x)-mpy-\d{8}.zip$', asset["name"])
            if not len(bundle_version):
                continue
            bundle_version = bundle_version[0]

            # create output directory
            bundle_dir = temp_root_dir / f"CircuitPython {bundle_version}"
            bundle_dir.mkdir(parents=True, exist_ok=True)

            # copy asset contents
            for asset_dir in asset_dirs:
                shutil.copytree(asset_dir, bundle_dir / asset_dir.name, dirs_exist_ok=True)

            # copy src contents
            shutil.copytree(src_dir, bundle_dir, dirs_exist_ok=True)

            # install required libs
            shutil.copyfile("mock_boot_out.txt", bundle_dir / "boot_out.txt")
            replace_tags(bundle_dir / "boot_out.txt", {
                "version": bundle_version.replace('.x', '.0.0'),
                "date": datetime.today().strftime('%Y-%m-%d'),
            })
            circup_cli(
                ["--path", bundle_dir, "install", "--auto"],
                standalone_mode=False,
            )
            os.remove(bundle_dir / "boot_out.txt")

        # create the final zip file
        with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in temp_dir.rglob("*"):
                if file_path.is_file():
                    modification_time = datetime(2000, 1, 1, 0, 0, 0)
                    modification_timestamp = modification_time.timestamp()
                    os.utime(file_path, (modification_timestamp, modification_timestamp))
                    arcname = file_path.relative_to(temp_dir)
                    zf.write(file_path, arcname)

        print(f"Created {output_zip}")

    finally:
        # clean up temporary directory
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
