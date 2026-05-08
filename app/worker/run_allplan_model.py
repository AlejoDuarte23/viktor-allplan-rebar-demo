import shutil
import subprocess
from pathlib import Path


ALLPLAN_EXE = Path(r"C:\Program Files\Allplan\Allplan 2026\Prg\Allplan_2026.exe")
ALLPLAN_LOCAL = Path.home() / "Documents" / "Nemetschek" / "Allplan" / "2026" / "Usr" / "Local"


def main():
    workdir = Path.cwd()
    inputs_path = workdir / "inputs.json"
    pyp_source = workdir / "RebarWorker.pyp"
    py_source = workdir / "RebarWorker.py"

    python_parts_dir = ALLPLAN_LOCAL / "PythonParts" / "ViktorWorker"
    python_scripts_dir = ALLPLAN_LOCAL / "PythonPartsScripts" / "ViktorWorker"
    python_parts_dir.mkdir(parents=True, exist_ok=True)
    python_scripts_dir.mkdir(parents=True, exist_ok=True)

    pyp_target = python_parts_dir / "RebarWorker.pyp"
    py_target = python_scripts_dir / "RebarWorker.py"
    inputs_target = python_scripts_dir / "inputs.json"

    shutil.copy2(pyp_source, pyp_target)
    shutil.copy2(py_source, py_target)
    shutil.copy2(inputs_path, inputs_target)

    subprocess.run(
        [
            "cmd.exe",
            "/c",
            f'start "" /wait "{ALLPLAN_EXE}" -o "@{pyp_target}" & exit /b %ERRORLEVEL%',
        ],
        cwd=str(workdir),
        check=True,
    )


if __name__ == "__main__":
    main()
