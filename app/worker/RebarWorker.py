import json
import math
import traceback
from pathlib import Path

import NemAll_Python_BaseElements as AllplanBaseElements
import NemAll_Python_Geometry as AllplanGeo
from CreateElementResult import CreateElementResult
from TypeCollections.ModelEleList import ModelEleList


PROJECT_NAME = "viktor-template"
DRAWING_FILE_NUMBER = 1


def _log(message: str) -> None:
    log_path = Path(__file__).with_name("worker_log.txt")
    with log_path.open("a", encoding="utf-8") as file:
        file.write(f"{message}\n")


def _write_error(error: BaseException) -> None:
    error_path = Path(__file__).with_name("worker_error.txt")
    error_path.write_text(
        "".join(traceback.format_exception(type(error), error, error.__traceback__)),
        encoding="utf-8",
    )


def check_allplan_version(build_ele, version: float) -> bool:
    return True


def _load_inputs() -> dict:
    with Path(__file__).with_name("inputs.json").open("r", encoding="utf-8") as file:
        return json.load(file)


def _open_project(doc) -> None:
    current_project_name, host_name = AllplanBaseElements.ProjectService.GetCurrentProjectNameAndHost()

    if current_project_name == PROJECT_NAME:
        _log(f"Project '{PROJECT_NAME}' is already active.")
        return

    open_result = AllplanBaseElements.ProjectService.OpenProject(
        doc,
        host_name,
        PROJECT_NAME,
    )

    _log(f"OpenProject returned: {open_result}")

    if open_result not in ("Project opened", "Active project", "project opened"):
        raise RuntimeError(
            f"Could not open Allplan project '{PROJECT_NAME}'. "
            f"Current project was '{current_project_name}'. "
            f"Allplan returned: '{open_result}'."
        )


def _load_drawing_file(doc) -> None:
    drawing_service = AllplanBaseElements.DrawingFileService()

    drawing_service.LoadFile(
        doc,
        DRAWING_FILE_NUMBER,
        AllplanBaseElements.DrawingFileLoadState.ActiveForeground,
    )


def create_element(build_ele, doc) -> CreateElementResult:
    try:
        _log("Rebar PythonPart started.")
        data = _load_inputs()
        run_id = data["run_id"]

        done_marker = Path(__file__).with_name("worker_done.txt")
        result_path = Path(__file__).with_name("result.json")

        _log(f"Run ID: {run_id}.")
        _log("Opening project.")
        _open_project(doc)

        _log("Project opened.")
        _log(f"Loading drawing file {DRAWING_FILE_NUMBER}.")
        _load_drawing_file(doc)

        _log("Drawing file loaded.")
        _log("Creating pile cap, piles, and visual rebar geometry.")
        model_elements = create_model_elements(data)

        _log("Writing model elements to Allplan document.")
        AllplanBaseElements.CreateElements(
            doc,
            AllplanGeo.Matrix3D(),
            model_elements,
            [],
            None,
        )

        _log("CreateElements finished.")

        result = build_result(data, run_id)
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        _log("result.json written.")

        done_marker.write_text("done", encoding="utf-8")
        _log("worker_done.txt written.")

        return CreateElementResult()

    except BaseException as error:
        _log(f"Worker failed: {error}")
        _write_error(error)
        raise


def create_model_elements(data: dict) -> ModelEleList:
    elements = ModelEleList()
    add_concrete_context(elements, data)
    add_cap_rebar_visual(elements, data)
    add_pile_rebar_visual(elements, data)
    return elements


def add_concrete_context(elements: ModelEleList, data: dict) -> None:
    cap_placement = AllplanGeo.AxisPlacement3D(
        AllplanGeo.Point3D(-data["cap_length"] / 2.0, -data["cap_width"] / 2.0, 0.0),
        AllplanGeo.Vector3D(1.0, 0.0, 0.0),
        AllplanGeo.Vector3D(0.0, 0.0, 1.0),
    )
    elements.append_geometry_3d(
        AllplanGeo.BRep3D.CreateCuboid(
            cap_placement,
            data["cap_length"],
            data["cap_width"],
            data["cap_height"],
        )
    )

    for pile in data["pile_centers"]:
        pile_placement = AllplanGeo.AxisPlacement3D(
            AllplanGeo.Point3D(pile["x"], pile["y"], -data["pile_depth"]),
            AllplanGeo.Vector3D(1.0, 0.0, 0.0),
            AllplanGeo.Vector3D(0.0, 0.0, 1.0),
        )
        elements.append_geometry_3d(
            AllplanGeo.BRep3D.CreateCylinder(
                pile_placement,
                data["pile_diameter"] / 2.0,
                data["pile_depth"],
            )
        )


def add_cap_rebar_visual(elements: ModelEleList, data: dict) -> None:
    cover = data["cover"]
    x_min = -data["cap_length"] / 2.0 + cover
    x_max = data["cap_length"] / 2.0 - cover
    y_min = -data["cap_width"] / 2.0 + cover
    y_max = data["cap_width"] / 2.0 - cover
    z_bottom = cover
    z_top = data["cap_height"] - cover

    y_positions = positions_between(y_min, y_max, data["mat_spacing"])
    x_positions = positions_between(x_min, x_max, data["mat_spacing"])
    radius = data["mat_bar_diameter"] / 2.0

    for y in sample_positions(y_positions):
        append_cylinder_x(elements, radius, x_min, x_max, y, z_bottom)
        append_cylinder_x(elements, radius, x_min, x_max, y, z_top)

    for x in sample_positions(x_positions):
        append_cylinder_y(elements, radius, x, y_min, y_max, z_bottom)
        append_cylinder_y(elements, radius, x, y_min, y_max, z_top)


def append_cylinder_x(elements: ModelEleList, radius: float, x_min: float, x_max: float, y: float, z: float) -> None:
    placement = AllplanGeo.AxisPlacement3D(
        AllplanGeo.Point3D(x_min, y, z),
        AllplanGeo.Vector3D(0.0, 1.0, 0.0),
        AllplanGeo.Vector3D(1.0, 0.0, 0.0),
    )
    elements.append_geometry_3d(AllplanGeo.BRep3D.CreateCylinder(placement, radius, x_max - x_min))


def append_cylinder_y(elements: ModelEleList, radius: float, x: float, y_min: float, y_max: float, z: float) -> None:
    placement = AllplanGeo.AxisPlacement3D(
        AllplanGeo.Point3D(x, y_min, z),
        AllplanGeo.Vector3D(1.0, 0.0, 0.0),
        AllplanGeo.Vector3D(0.0, 1.0, 0.0),
    )
    elements.append_geometry_3d(AllplanGeo.BRep3D.CreateCylinder(placement, radius, y_max - y_min))


def add_pile_rebar_visual(elements: ModelEleList, data: dict) -> None:
    radius = data["pile_diameter"] / 2.0 - data["cover"]
    z_min = -data["pile_depth"]
    z_max = data["cap_height"] - data["cover"]
    vertical_radius = data["pile_vertical_diameter"] / 2.0
    hoop_radius = data["pile_hoop_diameter"] / 2.0

    for pile in data["pile_centers"]:
        cx = pile["x"]
        cy = pile["y"]

        for index in range(data["pile_vertical_count"]):
            angle = 2.0 * math.pi * index / data["pile_vertical_count"]
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            append_cylinder_z(elements, vertical_radius, x, y, z_min, z_max)

        for z in positions_between(z_min, 0.0, data["pile_hoop_spacing"]):
            append_pile_hoop_visual(elements, hoop_radius, cx, cy, radius, z)


def append_cylinder_z(elements: ModelEleList, radius: float, x: float, y: float, z_min: float, z_max: float) -> None:
    placement = AllplanGeo.AxisPlacement3D(
        AllplanGeo.Point3D(x, y, z_min),
        AllplanGeo.Vector3D(1.0, 0.0, 0.0),
        AllplanGeo.Vector3D(0.0, 0.0, 1.0),
    )
    elements.append_geometry_3d(AllplanGeo.BRep3D.CreateCylinder(placement, radius, z_max - z_min))


def append_pile_hoop_visual(elements: ModelEleList, bar_radius: float, cx: float, cy: float, radius: float, z: float) -> None:
    segments = 20
    points = []
    for index in range(segments + 1):
        angle = 2.0 * math.pi * index / segments
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle), z))
    append_polyline_cylinders(elements, bar_radius, points)


def append_polyline_cylinders(elements: ModelEleList, radius: float, points: list[tuple[float, float, float]]) -> None:
    for start, end in zip(points, points[1:]):
        append_cylinder_between(elements, radius, start, end)


def append_cylinder_between(elements: ModelEleList, radius: float, start: tuple[float, float, float], end: tuple[float, float, float]) -> None:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dz = end[2] - start[2]
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length == 0:
        return

    axis = AllplanGeo.Vector3D(dx / length, dy / length, dz / length)
    reference = AllplanGeo.Vector3D(0.0, 0.0, 1.0)
    if abs(axis.Z) > 0.99:
        reference = AllplanGeo.Vector3D(1.0, 0.0, 0.0)

    placement = AllplanGeo.AxisPlacement3D(point(start), reference, axis)
    elements.append_geometry_3d(AllplanGeo.BRep3D.CreateCylinder(placement, radius, length))


def positions_between(start: float, end: float, spacing: float) -> list[float]:
    count = int((end - start) // spacing) + 1
    if count == 1:
        return [(start + end) / 2.0]
    return [start + index * (end - start) / (count - 1) for index in range(count)]


def sample_positions(values: list[float], max_count: int = 7) -> list[float]:
    if len(values) <= max_count:
        return values

    last_index = len(values) - 1
    return [values[round(index * last_index / (max_count - 1))] for index in range(max_count)]


def point(coords: tuple[float, float, float]):
    return AllplanGeo.Point3D(coords[0], coords[1], coords[2])


def build_result(data: dict, run_id: str) -> dict:
    y_bars = len(sample_positions(positions_between(-data["cap_width"] / 2.0 + data["cover"], data["cap_width"] / 2.0 - data["cover"], data["mat_spacing"])))
    x_bars = len(sample_positions(positions_between(-data["cap_length"] / 2.0 + data["cover"], data["cap_length"] / 2.0 - data["cover"], data["mat_spacing"])))
    pile_hoop_count = len(positions_between(-data["pile_depth"], 0.0, data["pile_hoop_spacing"]))

    return {
        "run_id": run_id,
        "project_name": PROJECT_NAME,
        "drawing_file_number": DRAWING_FILE_NUMBER,
        "created": {
            "pile_cap": 1,
            "piles": len(data["pile_centers"]),
            "cap_visual_mat_bars": 2 * y_bars + 2 * x_bars,
            "pile_visual_vertical_bars": len(data["pile_centers"]) * data["pile_vertical_count"],
            "pile_visual_hoops": len(data["pile_centers"]) * pile_hoop_count,
        },
        "inputs": data,
    }
