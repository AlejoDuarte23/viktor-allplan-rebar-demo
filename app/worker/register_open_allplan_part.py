import json
import shutil
import time
from pathlib import Path


ALLPLAN_LOCAL = Path.home() / "Documents" / "Nemetschek" / "Allplan" / "2026" / "Usr" / "Local"


def log(log_path: Path, message: str) -> None:
    with log_path.open("a", encoding="utf-8") as file:
        file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


def main():
    workdir = Path.cwd()
    inputs_path = workdir / "inputs.json"
    pyp_source = workdir / "RebarWorker.pyp"
    py_source = workdir / "RebarWorker.py"
    log_path = workdir / "worker_log.txt"
    result_path = workdir / "registration_result.json"

    if log_path.exists():
        log_path.unlink()

    if result_path.exists():
        result_path.unlink()

    python_parts_dir = ALLPLAN_LOCAL / "PythonParts" / "ViktorOpenSession"
    python_scripts_dir = ALLPLAN_LOCAL / "PythonPartsScripts" / "ViktorOpenSession"
    python_parts_dir.mkdir(parents=True, exist_ok=True)
    python_scripts_dir.mkdir(parents=True, exist_ok=True)

    pyp_target = python_parts_dir / "RebarWorker.pyp"
    py_target = python_scripts_dir / "RebarWorker.py"
    inputs_target = python_scripts_dir / "inputs.json"

    shutil.copy2(pyp_source, pyp_target)
    shutil.copy2(py_source, py_target)
    shutil.copy2(inputs_path, inputs_target)

    data = json.loads(inputs_target.read_text(encoding="utf-8"))

    log(log_path, f"Registered PythonPart at {pyp_target}.")
    log(log_path, f"Registered script at {py_target}.")
    log(log_path, f"Wrote inputs at {inputs_target}.")
    log(log_path, "This worker does not start or close Allplan.")
    log(log_path, "Assumption: Allplan is already open with an empty project and active drawing file.")
    log(log_path, "Next step: execute 'VIKTOR Rebar Worker' from the PythonParts library in the open Allplan session.")

    result = {
        "run_id": data["run_id"],
        "pythonpart_name": "VIKTOR Rebar Worker",
        "pythonpart_path": str(pyp_target),
        "script_path": str(py_target),
        "inputs_path": str(inputs_target),
        "assumptions": [
            "Allplan is already open.",
            "An empty project is already open.",
            "An active drawing file is selected.",
            "The user will execute the PythonPart manually from the open Allplan session.",
        ],
    }
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
