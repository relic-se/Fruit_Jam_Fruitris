# SPDX-FileCopyrightText: 2025 Cooper Dalrymple (@relic-se)
#
# SPDX-License-Identifier: GPLv3
from datetime import datetime
import os
import zipfile
import shutil
from pathlib import Path
from circup.commands import main as circup_cli

def main():

    # get the project root directory
    root_dir = Path(__file__).parent
    
    # set up paths
    bmp_dir = root_dir / "bitmaps"
    src_dir = root_dir / "src"
    output_dir = root_dir / "dist"

    # delete output dir if it exists
    if output_dir.exists():
        shutil.rmtree(output_dir)

    # create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # create output zip filename
    output_zip = output_dir / "fruitris.zip"
    
    # create a clean temporary directory for building the zip
    temp_dir = output_dir / "temp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)

    try:
        # copy bmp contents
        shutil.copytree(bmp_dir, temp_dir / "bitmaps", dirs_exist_ok=True)

        # copy src contents
        shutil.copytree(src_dir, temp_dir, dirs_exist_ok=True)
        
        # install required libs
        shutil.copyfile("mock_boot_out.txt", temp_dir / "boot_out.txt")
        circup_cli(["--path", temp_dir, "install", "--auto"],
                   standalone_mode=False)
        os.remove(temp_dir / "boot_out.txt")

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
