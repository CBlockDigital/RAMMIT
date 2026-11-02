"""Zip folders with forward-slash paths (PowerShell 5.1's Compress-Archive writes backslashes).

    python Tools/MakeZip.py <OutZip> <Folder> [<Folder> ...]
Each folder is stored under its own name at the top of the zip.
"""
import os
import sys
import zipfile


def Main(OutZip, Folders):
    with zipfile.ZipFile(OutZip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as Zip:
        for Folder in Folders:
            Parent = os.path.dirname(os.path.abspath(Folder))
            for Dir, _Subdirs, Files in os.walk(Folder):
                for Name in sorted(Files):
                    Full = os.path.join(Dir, Name)
                    Zip.write(Full, os.path.relpath(Full, Parent).replace(os.sep, "/"))
    with zipfile.ZipFile(OutZip) as Zip:
        Bad = Zip.testzip()
        if Bad:
            raise SystemExit(f"Corrupt entry in zip: {Bad}")
        print(f"{OutZip}: {len(Zip.namelist())} files, testzip OK")


if __name__ == "__main__":
    Main(sys.argv[1], sys.argv[2:])
