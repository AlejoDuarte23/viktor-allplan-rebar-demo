import os
import shutil
import stat
import subprocess
import time
from pathlib import Path


ALLPLAN_EXE = Path(r"C:\Program Files\Allplan\Allplan 2026\Prg\Allplan_2026.exe")
ALLPLAN_LOCAL = Path.home() / "Documents" / "Nemetschek" / "Allplan" / "2026" / "Usr" / "Local"
ALLPLAN_CLOSE_TIMEOUT_SECONDS = 30
RESULT_PROJECT_DIR_NAME = "result_project.prj"


def log(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as file:
        file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


def make_writable(path: str) -> None:
    try:
        os.chmod(path, stat.S_IWRITE)
    except (FileNotFoundError, PermissionError):
        pass


def remove_readonly_and_retry(function, path, exc_info) -> None:
    make_writable(path)
    function(path)


def remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, onerror=remove_readonly_and_retry)


def stop_launched_allplan(process: subprocess.Popen, log_path: Path) -> None:
    if process.poll() is not None:
        log(log_path, f"Allplan process already exited with code {process.returncode}.")
        return

    log(log_path, f"Stopping launched Allplan process with PID {process.pid}.")
    process.terminate()

    try:
        process.wait(timeout=ALLPLAN_CLOSE_TIMEOUT_SECONDS)
        log(log_path, f"Allplan process exited with code {process.returncode}.")
    except subprocess.TimeoutExpired:
        log(log_path, "Allplan did not exit after terminate; killing process.")
        process.kill()
        process.wait(timeout=10)
        log(log_path, f"Allplan process killed with code {process.returncode}.")


def install_template_project(template_zip: Path, result_project_dir: Path, log_path: Path) -> Path:
    extract_dir = template_zip.parent / "_template_project_extract"
    remove_tree(extract_dir)
    remove_tree(result_project_dir)

    extract_dir.mkdir(parents=True, exist_ok=True)
    shutil.unpack_archive(str(template_zip), str(extract_dir), "zip")

    project_candidates = sorted(path for path in extract_dir.iterdir() if path.is_dir() and path.suffix == ".prj")
    if project_candidates:
        source_project_dir = project_candidates[0]
    elif (extract_dir / "Project1.Dat.xml").exists():
        source_project_dir = extract_dir
    else:
        raise RuntimeError(
            f"Template archive {template_zip} does not contain a .prj folder or Project1.Dat.xml."
        )

    shutil.copytree(source_project_dir, result_project_dir, copy_function=shutil.copy2)
    remove_tree(extract_dir)

    project_xml = result_project_dir / "Project1.Dat.xml"
    if not project_xml.exists():
        raise FileNotFoundError(f"Copied project is missing Project1.Dat.xml: {project_xml}")

    log(log_path, f"Installed template project at {result_project_dir}.")
    return project_xml


def main() -> None:
    workdir = Path.cwd()
    template_zip = workdir / "template_project.zip"
    result_project_dir = workdir / RESULT_PROJECT_DIR_NAME
    inputs_path = workdir / "inputs.json"
    pyp_source = workdir / "RebarWorker.pyp"
    py_source = workdir / "RebarWorker.py"
    output_zip = workdir / "result_project.zip"
    output_log = workdir / "worker_log.txt"

    if output_zip.exists():
        output_zip.unlink()

    if output_log.exists():
        output_log.unlink()

    log(output_log, "Worker started.")

    if not template_zip.exists():
        raise FileNotFoundError(f"Template project ZIP was not found: {template_zip}")

    log(output_log, f"Installing template project from {template_zip}.")
    result_project_xml = install_template_project(template_zip, result_project_dir, output_log)
    log(output_log, f"Template project ready at {result_project_xml}.")

    python_parts_dir = ALLPLAN_LOCAL / "PythonParts" / "ViktorWorker"
    python_scripts_dir = ALLPLAN_LOCAL / "PythonPartsScripts" / "ViktorWorker"
    python_parts_dir.mkdir(parents=True, exist_ok=True)
    python_scripts_dir.mkdir(parents=True, exist_ok=True)

    pyp_target = python_parts_dir / "RebarWorker.pyp"
    py_target = python_scripts_dir / "RebarWorker.py"
    inputs_target = python_scripts_dir / "inputs.json"
    done_marker = python_scripts_dir / "worker_done.txt"
    result_source = python_scripts_dir / "result.json"
    log_source = python_scripts_dir / "worker_log.txt"
    error_source = python_scripts_dir / "worker_error.txt"
    output_json = workdir / "result.json"

    for path in [done_marker, result_source, output_json, log_source, error_source]:
        if path.exists():
            path.unlink()

    shutil.copy2(pyp_source, pyp_target)
    shutil.copy2(py_source, py_target)
    shutil.copy2(inputs_path, inputs_target)
    log(output_log, f"Copied PythonPart to {pyp_target}.")
    log(output_log, f"Copied script and inputs to {python_scripts_dir}.")

    process = subprocess.Popen(
        [
            str(ALLPLAN_EXE),
            "/l",
            str(result_project_xml),
            "-o",
            f"@{pyp_target}",
        ],
        cwd=str(workdir),
    )
    log(output_log, f"Started Allplan with PID {process.pid} using project {result_project_xml}.")

    try:
        deadline = time.time() + 840
        while not done_marker.exists():
            if error_source.exists():
                error_text = error_source.read_text(encoding="utf-8")
                log(output_log, "worker_error.txt detected.")
                log(output_log, error_text)
                raise RuntimeError(f"Allplan worker failed:\n{error_text}")

            if process.poll() is not None:
                log(output_log, f"Allplan process ended before marker. Exit code: {process.returncode}.")
                time.sleep(5)
                if not done_marker.exists():
                    raise RuntimeError(f"Allplan closed before the worker finished. Exit code: {process.returncode}")
                break

            if time.time() > deadline:
                log(output_log, "Timeout waiting for worker_done.txt.")
                raise TimeoutError("Allplan worker did not finish within 840 seconds.")

            time.sleep(1)

        log(output_log, "worker_done.txt detected.")
        log(output_log, f"Allplan process state after marker: {process.poll()}.")
        time.sleep(5)
        log(output_log, "Waited 5 seconds for Allplan to finish creating returned reinforcement elements.")
        shutil.copy2(result_source, output_json)
        log(output_log, "Copied result.json back to worker output folder.")

        if log_source.exists():
            with output_log.open("a", encoding="utf-8") as file:
                file.write("\nPythonPart log:\n")
                file.write(log_source.read_text(encoding="utf-8"))

        shutil.make_archive(
            base_name=str(output_zip.with_suffix("")),
            format="zip",
            root_dir=str(result_project_dir.parent),
            base_dir=result_project_dir.name,
        )
        log(output_log, f"Created {output_zip}.")
    finally:
        stop_launched_allplan(process, output_log)


if __name__ == "__main__":
    main()
