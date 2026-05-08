
No. Do **not** save an empty Allplan file in `~/Documents/allplan-test`.

Use the folder only as your **local runner folder**:

```text
C:\Users\<you>\Documents\allplan-test
```

It should contain:

```text
allplan-test/
├─ inputs.json
├─ run_allplan_model.py
├─ CreateAllplanFrame.pyp
├─ CreateAllplanFrame.py
└─ output.json          # created after the run
```

The actual empty project should already exist **inside Allplan**. From your screenshot, the project appears to be named `test`, so use that project name in `inputs.json`.

Allplan can run a PythonPart from the command line with `Allplan_2026.exe -o "@path\PythonPart.pyp"`, and the `.pyp` path must be absolute and prefixed with `@`. Extra CLI arguments are passed into `sys.argv` in reversed order. ([Python Parts][1])

Create the folder:

```powershell
mkdir "$HOME\Documents\allplan-test"
cd "$HOME\Documents\allplan-test"
```

Create `inputs.json`:

```json
{
  "project_name": "test",
  "host_name": "",
  "drawing_file": 100,
  "clear_drawing_file": true,
  "node_marker_size": 150.0,
  "nodes": [
    {"id": "N1", "x": 0.0, "y": 0.0, "z": 0.0},
    {"id": "N2", "x": 6000.0, "y": 0.0, "z": 0.0},
    {"id": "N3", "x": 0.0, "y": 0.0, "z": 3000.0},
    {"id": "N4", "x": 6000.0, "y": 0.0, "z": 3000.0}
  ],
  "lines": [
    {"id": "C1", "from": "N1", "to": "N3"},
    {"id": "C2", "from": "N2", "to": "N4"},
    {"id": "B1", "from": "N3", "to": "N4"}
  ]
}
```

Create `CreateAllplanFrame.pyp`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Element>
    <Script>
        <Name>ViktorWorker\CreateAllplanFrame.py</Name>
        <Title>Create Allplan Frame from Local Test</Title>
        <Version>1.0</Version>
    </Script>

    <Page>
        <Name>Page1</Name>
        <Text>Local Test</Text>
    </Page>
</Element>
```

Create `run_allplan_model.py`:

```python
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path


ALLPLAN_EXE = Path(r"C:\Program Files\Allplan\2026\Prg\Allplan_2026.exe")

TEST_DIR = Path.home() / "Documents" / "allplan-test"

ALLPLAN_SCRIPT_DIR = Path(
    r"C:\ProgramData\Nemetschek\Allplan\2026\Usr\Local\PythonPartsScripts\ViktorWorker"
)

TIMEOUT_SECONDS = 600


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main() -> int:
    inputs_path = TEST_DIR / "inputs.json"
    output_path = TEST_DIR / "output.json"
    pyp_path = TEST_DIR / "CreateAllplanFrame.pyp"
    py_path = TEST_DIR / "CreateAllplanFrame.py"

    try:
        if output_path.exists():
            output_path.unlink()

        if not ALLPLAN_EXE.is_file():
            raise FileNotFoundError(f"Allplan executable not found: {ALLPLAN_EXE}")

        if not inputs_path.is_file():
            raise FileNotFoundError(f"Missing file: {inputs_path}")

        if not pyp_path.is_file():
            raise FileNotFoundError(f"Missing file: {pyp_path}")

        if not py_path.is_file():
            raise FileNotFoundError(f"Missing file: {py_path}")

        ALLPLAN_SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(py_path, ALLPLAN_SCRIPT_DIR / "CreateAllplanFrame.py")

        command = [
            str(ALLPLAN_EXE),
            "-o",
            f"@{pyp_path}",
            str(inputs_path),
            str(output_path),
        ]

        process = subprocess.Popen(command, cwd=str(TEST_DIR))

        deadline = time.time() + TIMEOUT_SECONDS

        while time.time() < deadline:
            if output_path.is_file():
                json.loads(output_path.read_text(encoding="utf-8"))
                return 0

            if process.poll() is not None:
                raise RuntimeError(
                    f"Allplan closed before output.json was created. "
                    f"Return code: {process.returncode}"
                )

            time.sleep(1)

        raise TimeoutError("Allplan did not create output.json before timeout.")

    except Exception as exc:
        write_json(
            output_path,
            {
                "status": "error",
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
```

The missing file now is `CreateAllplanFrame.py`. That is the actual PythonPart script. Save it in the same folder, and the runner will copy it to Allplan’s `PythonPartsScripts` folder before starting Allplan.

For the first test, use your existing Allplan project `test` and drawing file `100`. The PythonPart can load a drawing file by number, and Allplan’s API has `LoadFile`, `UnloadAll`, and `DeleteDocument` for clearing the active document content. ([Python Parts][2])

So the answer is:

```text
No empty external Allplan file needed.
Create an empty Allplan project inside Allplan.
Use ~/Documents/allplan-test only for inputs, scripts, .pyp, and output.json.
```

Once this local folder works, the VIKTOR worker CWD will have the same contents:

```text
inputs.json
run_allplan_model.py
CreateAllplanFrame.pyp
CreateAllplanFrame.py
```

Then VIKTOR will run the same CLI pattern from the worker directory.

[1]: https://pythonparts.allplan.com/2026/manual/features/miscellaneous/ "Miscellaneous - Python API Documentation"
[2]: https://pythonparts.allplan.com/2026/api_reference/InterfaceStubs/NemAll_Python_BaseElements/DrawingFileService/ "Drawing File Service - Python API Documentation"