import json
import math
import traceback
from pathlib import Path

import NemAll_Python_BaseElements as AllplanBaseElements
import NemAll_Python_Geometry as AllplanGeo
import NemAll_Python_Reinforcement as AllplanReinf
import StdReinfShapeBuilder.GeneralReinfShapeBuilder as GeneralShapeBuilder
from CreateElementResult import CreateElementResult
from StdReinfShapeBuilder.ConcreteCoverProperties import ConcreteCoverProperties
from StdReinfShapeBuilder.ReinforcementShapeProperties import ReinforcementShapeProperties
from TypeCollections.ModelEleList import ModelEleList

try:
    from Utils.RotationUtil import RotationUtil
except ImportError:
    from Utils import RotationUtil as RotationUtilModule

    RotationUtil = getattr(RotationUtilModule, "RotationUtil", RotationUtilModule)


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
        _log("Pile cap native rebar PythonPart started.")
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
        _log("Creating pile cap, piles, and native reinforcement elements.")
        model_elements = create_model_elements(data)

        _log_model_elements(model_elements)

        result = build_result(data, run_id)
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        _log("result.json written.")

        done_marker.write_text("done", encoding="utf-8")
        _log("worker_done.txt written.")
        _log("Returning model elements through CreateElementResult with fixed origin placement.")

        return CreateElementResult(
            elements=model_elements,
            placement_point=AllplanGeo.Point3D(),
        )

    except BaseException as error:
        _log(f"Worker failed: {error}")
        _write_error(error)
        raise


def create_model_elements(data: dict) -> ModelEleList:
    elements = ModelEleList()
    add_concrete_context(elements, data)
    add_cap_rebar(elements, data)
    add_pile_rebar(elements, data)
    return elements


def _log_model_elements(model_elements: ModelEleList) -> None:
    try:
        _log(f"Prepared {len(model_elements)} model elements.")
    except Exception as error:
        _log(f"Could not read model element count: {error}")

    try:
        type_counts = {}
        for index, element in enumerate(model_elements):
            if element is None:
                raise RuntimeError(f"Invalid model element at index {index}: None")
            if isinstance(element, list):
                raise RuntimeError(f"Invalid model element at index {index}: nested Python list")

            element_type = type(element).__name__
            type_counts[element_type] = type_counts.get(element_type, 0) + 1

        _log(f"Model element types: {type_counts}")
    except TypeError as error:
        _log(f"Could not iterate model elements for type validation: {error}")


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
        append_vertical_cylinder(
            elements,
            data["pile_diameter"] / 2.0,
            -data["pile_depth"],
            data["pile_depth"],
            pile["x"],
            pile["y"],
        )


def add_cap_rebar(elements: ModelEleList, data: dict) -> None:
    cover = data["cover"]
    x_min = -data["cap_length"] / 2.0 + cover
    x_max = data["cap_length"] / 2.0 - cover
    y_min = -data["cap_width"] / 2.0 + cover
    y_max = data["cap_width"] / 2.0 - cover
    z_bottom = cover
    z_top = data["cap_height"] - cover

    if x_max <= x_min or y_max <= y_min or z_top <= z_bottom:
        raise ValueError("No room left for cap mat reinforcement after concrete cover.")

    y_positions = positions_between(y_min, y_max, data["mat_spacing"])
    x_positions = positions_between(x_min, x_max, data["mat_spacing"])

    mat_hook_length = disabled_hook_length(data["mat_hook_length"])
    mat_hook_angle = float(data["mat_hook_angle"])

    _log(
        "Creating cap mat real rebar: "
        f"{2 * len(y_positions)} X bars, {2 * len(x_positions)} Y bars, "
        f"hook_length={data['mat_hook_length']:.2f}, hook_angle={mat_hook_angle:.2f}."
    )

    for index, y in enumerate(y_positions):
        append_single_straight_rebar(
            elements=elements,
            position_number=1000 + index,
            diameter=data["mat_bar_diameter"],
            start_point=AllplanGeo.Point3D(x_min, y, z_bottom),
            end_point=AllplanGeo.Point3D(x_max, y, z_bottom),
            start_hook_length=mat_hook_length,
            start_hook_angle=mat_hook_angle,
            end_hook_length=mat_hook_length,
            end_hook_angle=mat_hook_angle,
        )
        append_single_straight_rebar(
            elements=elements,
            position_number=2000 + index,
            diameter=data["mat_bar_diameter"],
            start_point=AllplanGeo.Point3D(x_min, y, z_top),
            end_point=AllplanGeo.Point3D(x_max, y, z_top),
            start_hook_length=mat_hook_length,
            start_hook_angle=mat_hook_angle,
            end_hook_length=mat_hook_length,
            end_hook_angle=mat_hook_angle,
        )

    for index, x in enumerate(x_positions):
        append_single_straight_rebar(
            elements=elements,
            position_number=3000 + index,
            diameter=data["mat_bar_diameter"],
            start_point=AllplanGeo.Point3D(x, y_min, z_bottom),
            end_point=AllplanGeo.Point3D(x, y_max, z_bottom),
            start_hook_length=mat_hook_length,
            start_hook_angle=mat_hook_angle,
            end_hook_length=mat_hook_length,
            end_hook_angle=mat_hook_angle,
        )
        append_single_straight_rebar(
            elements=elements,
            position_number=4000 + index,
            diameter=data["mat_bar_diameter"],
            start_point=AllplanGeo.Point3D(x, y_min, z_top),
            end_point=AllplanGeo.Point3D(x, y_max, z_top),
            start_hook_length=mat_hook_length,
            start_hook_angle=mat_hook_angle,
            end_hook_length=mat_hook_length,
            end_hook_angle=mat_hook_angle,
        )


def add_pile_rebar(elements: ModelEleList, data: dict) -> None:
    pile_radius = data["pile_diameter"] / 2.0
    cover = data["cover"]
    vertical_diameter = data["pile_vertical_diameter"]
    hoop_diameter = data["pile_hoop_diameter"]
    vertical_count = data["pile_vertical_count"]
    steel_grade = data.get("steel_grade", -1)
    concrete_grade = data.get("concrete_grade", -1)

    if vertical_count < 2:
        raise ValueError("Rotational pile vertical placement needs at least two bars.")

    vertical_axis_radius = pile_radius - cover - vertical_diameter / 2.0
    if vertical_axis_radius <= 0.0:
        raise ValueError("No room left for pile vertical bars after cover and diameter.")

    hoop_axis_radius = pile_radius - cover - hoop_diameter / 2.0
    if hoop_axis_radius <= 0.0:
        raise ValueError("No room left for pile hoops after cover and diameter.")

    if data["pile_hoop_spacing"] <= 0.0:
        raise ValueError("Pile hoop spacing must be positive.")

    z_bottom = -data["pile_depth"] + cover
    hoop_z_top = -cover
    vertical_z_top = data["cap_height"] - cover
    if (hoop_z_top - z_bottom) <= 0.001:
        raise ValueError("Pile reinforcement clear height is zero or negative.")

    top_hook_length = disabled_hook_length(data["pile_vertical_top_hook_length"])
    top_hook_angle = float(data["pile_vertical_top_hook_angle"])

    for pile_index, pile in enumerate(data["pile_centers"]):
        cx = pile["x"]
        cy = pile["y"]

        append_pile_vertical_rebar_set(
            elements=elements,
            position_number=5000 + pile_index,
            diameter=vertical_diameter,
            cx=cx,
            cy=cy,
            radius=vertical_axis_radius,
            z_bottom=z_bottom,
            z_top=vertical_z_top,
            bar_count=vertical_count,
            steel_grade=steel_grade,
            concrete_grade=concrete_grade,
            end_hook_length=top_hook_length,
            end_hook_angle=top_hook_angle,
        )

        append_vertical_circular_rebar_stack(
            elements=elements,
            position_number=6000 + pile_index,
            diameter=hoop_diameter,
            cx=cx,
            cy=cy,
            radius=hoop_axis_radius,
            z_start=z_bottom,
            z_end=hoop_z_top,
            spacing=data["pile_hoop_spacing"],
        )


def append_vertical_cylinder(elements: ModelEleList, radius: float, z_min: float, height: float, cx: float = 0.0, cy: float = 0.0) -> None:
    if radius <= 0.0 or height <= 0.0:
        return

    placement = AllplanGeo.AxisPlacement3D(
        AllplanGeo.Point3D(cx, cy, z_min),
        AllplanGeo.Vector3D(1.0, 0.0, 0.0),
        AllplanGeo.Vector3D(0.0, 0.0, 1.0),
    )
    elements.append_geometry_3d(AllplanGeo.BRep3D.CreateCylinder(placement, radius, height))


def append_single_straight_rebar(
    elements: ModelEleList,
    position_number: int,
    diameter: float,
    start_point: AllplanGeo.Point3D,
    end_point: AllplanGeo.Point3D,
    steel_grade: int = -1,
    concrete_grade: int = -1,
    start_hook_length: float = -1.0,
    start_hook_angle: float = 90.0,
    end_hook_length: float = -1.0,
    end_hook_angle: float = 90.0,
) -> None:
    bending_shape = create_straight_rebar_shape_from_points(
        diameter=diameter,
        start_point=start_point,
        end_point=end_point,
        steel_grade=steel_grade,
        concrete_grade=concrete_grade,
        start_hook_length=start_hook_length,
        start_hook_angle=start_hook_angle,
        end_hook_length=end_hook_length,
        end_hook_angle=end_hook_angle,
    )
    placement = AllplanReinf.BarPlacement(
        position_number,
        1,
        AllplanGeo.Vector3D(),
        AllplanGeo.Point3D(),
        AllplanGeo.Point3D(),
        bending_shape,
    )
    elements.append(placement)


def append_vertical_circular_rebar_stack(
    elements: ModelEleList,
    position_number: int,
    diameter: float,
    cx: float,
    cy: float,
    radius: float,
    z_start: float,
    z_end: float,
    spacing: float,
    start_angle: float = 0.0,
    end_angle: float = 360.0,
    max_bar_length: float = 18000.0,
    min_bar_length: float = 1000.0,
    max_bar_rise: float = 10000.0,
) -> None:
    if diameter <= 0.0 or radius <= 0.0 or spacing <= 0.0:
        return
    if z_end <= z_start:
        return

    contour = AllplanGeo.Polyline3D()
    contour += AllplanGeo.Point3D(cx + radius, cy, z_start)
    contour += AllplanGeo.Point3D(cx + radius, cy, z_end)
    rotation_axis = AllplanGeo.Line3D(
        AllplanGeo.Point3D(cx, cy, z_start),
        AllplanGeo.Point3D(cx, cy, z_start + 1.0),
    )
    circular_area = AllplanReinf.CircularAreaElement(
        position_number,
        diameter,
        -1,
        -1,
        rotation_axis,
        contour,
        start_angle,
        end_angle,
        start_angle,
        end_angle,
        0.0,
        0.0,
        0.0,
    )
    circular_area.SetBarProperties(
        spacing,
        max_bar_length,
        min_bar_length,
        0,
        max_bar_length,
        max_bar_length,
        0.0,
        max_bar_rise,
    )
    circular_area.SetOverlap(
        0.0,
        0.0,
        False,
        0.0,
        0.0,
        False,
        50.0 * diameter,
    )
    elements.append(circular_area)


def append_pile_vertical_rebar_set(
    elements: ModelEleList,
    position_number: int,
    diameter: float,
    cx: float,
    cy: float,
    radius: float,
    z_bottom: float,
    z_top: float,
    bar_count: int,
    steel_grade: int = -1,
    concrete_grade: int = -1,
    start_hook_length: float = -1.0,
    start_hook_angle: float = 90.0,
    end_hook_length: float = -1.0,
    end_hook_angle: float = 90.0,
) -> None:
    if diameter <= 0.0:
        return

    if bar_count < 2:
        raise ValueError("Rotational pile vertical placement needs at least two bars.")

    if radius <= 0.0:
        raise ValueError("Pile vertical bar axis radius must be positive.")

    if z_top <= z_bottom:
        raise ValueError("Pile vertical bar clear height must be positive.")

    start_point = AllplanGeo.Point3D(cx + radius, cy, z_bottom)
    end_point = AllplanGeo.Point3D(cx + radius, cy, z_top)

    bending_shape = create_straight_rebar_shape_from_points(
        diameter=diameter,
        start_point=start_point,
        end_point=end_point,
        steel_grade=steel_grade,
        concrete_grade=concrete_grade,
        start_hook_length=start_hook_length,
        start_hook_angle=start_hook_angle,
        end_hook_length=end_hook_length,
        end_hook_angle=end_hook_angle,
    )

    rotation_axis = AllplanGeo.Line3D(
        AllplanGeo.Point3D(cx, cy, z_bottom),
        AllplanGeo.Point3D(cx, cy, z_bottom + 1.0),
    )
    rotation_angle = AllplanGeo.Angle.FromDeg(360.0 / float(bar_count))

    placement = AllplanReinf.BarPlacement(
        position_number,
        bar_count,
        rotation_axis,
        rotation_angle,
        bending_shape,
    )

    elements.append(placement)


def create_straight_rebar_shape_from_points(
    diameter: float,
    start_point: AllplanGeo.Point3D,
    end_point: AllplanGeo.Point3D,
    steel_grade: int = -1,
    concrete_grade: int = -1,
    start_hook_length: float = -1.0,
    start_hook_angle: float = 90.0,
    end_hook_length: float = -1.0,
    end_hook_angle: float = 90.0,
):
    return create_oriented_straight_rebar_shape(
        diameter=diameter,
        start_point=start_point,
        end_point=end_point,
        steel_grade=steel_grade,
        concrete_grade=concrete_grade,
        start_hook_length=start_hook_length,
        start_hook_angle=start_hook_angle,
        end_hook_length=end_hook_length,
        end_hook_angle=end_hook_angle,
    )


def create_oriented_straight_rebar_shape(
    diameter: float,
    start_point: AllplanGeo.Point3D,
    end_point: AllplanGeo.Point3D,
    steel_grade: int = -1,
    concrete_grade: int = -1,
    start_hook_length: float = -1.0,
    start_hook_angle: float = 90.0,
    end_hook_length: float = -1.0,
    end_hook_angle: float = 90.0,
):
    if diameter <= 0.0:
        raise RuntimeError("Rebar diameter must be greater than zero.")

    dx = end_point.X - start_point.X
    dy = end_point.Y - start_point.Y
    dz = end_point.Z - start_point.Z

    length = math.sqrt(dx * dx + dy * dy + dz * dz)

    if length <= 0.001:
        raise RuntimeError("Cannot create rebar with zero length.")

    shape_properties = ReinforcementShapeProperties.rebar(
        diameter=diameter,
        bending_roller=-1,
        steel_grade=steel_grade,
        concrete_grade=concrete_grade,
        bending_shape_type=AllplanReinf.BendingShapeType.LongitudinalBar,
    )

    has_hook = start_hook_length >= 0.0 or end_hook_length >= 0.0
    if has_hook:
        # Local X is the bar axis. Rotating local Y into global Z keeps
        # 90-degree horizontal-bar hooks vertical before final alignment.
        bending_shape = GeneralShapeBuilder.create_longitudinal_shape_with_user_hooks(
            length=length,
            model_angles=RotationUtil(90.0, 0.0, 0.0),
            shape_props=shape_properties,
            concrete_cover_props=ConcreteCoverProperties.all(0.0),
            start_hook=start_hook_length,
            end_hook=end_hook_length,
            start_hook_angle=start_hook_angle,
            end_hook_angle=end_hook_angle,
            hook_type_start=-1,
            hook_type_end=-1,
        )
    else:
        bending_shape = GeneralShapeBuilder.create_longitudinal_shape_with_anchorage(
            from_point=AllplanGeo.Point3D(0.0, 0.0, 0.0),
            to_point=AllplanGeo.Point3D(length, 0.0, 0.0),
            shape_props=shape_properties,
            concrete_cover_props=ConcreteCoverProperties.all(0.0),
            start_anchorage=0.0,
            end_anchorage=0.0,
        )

    target_x = dx / length
    target_y = dy / length
    target_z = dz / length

    already_local_x = (
        abs(target_x - 1.0) <= 0.000001
        and abs(target_y) <= 0.000001
        and abs(target_z) <= 0.000001
    )

    if not already_local_x:
        target_direction = AllplanGeo.Vector3D(
            target_x,
            target_y,
            target_z,
        )

        rotation_matrix = AllplanGeo.Matrix3D()
        rotation_ok = rotation_matrix.SetRotation(
            AllplanGeo.Vector3D(1.0, 0.0, 0.0),
            target_direction,
        )

        if not rotation_ok:
            raise RuntimeError(
                "Could not rotate rebar shape from local X axis to target direction."
            )

        bending_shape.Transform(rotation_matrix)

    bending_shape.Move(
        AllplanGeo.Vector3D(
            start_point.X,
            start_point.Y,
            start_point.Z,
        )
    )

    try:
        if not bending_shape.IsValid():
            raise RuntimeError("Created rebar bending shape is invalid.")
    except AttributeError:
        pass

    return bending_shape


def disabled_hook_length(length: float) -> float:
    return -1.0 if length <= 0.0 else float(length)


def positions_between(start: float, end: float, spacing: float) -> list[float]:
    if end < start:
        return []

    span = end - start
    count = int(span // spacing) + 1
    if count <= 1:
        return [(start + end) / 2.0]
    return [start + index * span / (count - 1) for index in range(count)]


def build_result(data: dict, run_id: str) -> dict:
    cover = data["cover"]
    x_positions = positions_between(
        -data["cap_length"] / 2.0 + cover,
        data["cap_length"] / 2.0 - cover,
        data["mat_spacing"],
    )
    y_positions = positions_between(
        -data["cap_width"] / 2.0 + cover,
        data["cap_width"] / 2.0 - cover,
        data["mat_spacing"],
    )
    pile_rebar_bottom_z = -data["pile_depth"] + cover
    pile_hoop_top_z = -cover
    pile_hoop_count = len(positions_between(pile_rebar_bottom_z, pile_hoop_top_z, data["pile_hoop_spacing"]))

    return {
        "run_id": run_id,
        "project_name": PROJECT_NAME,
        "drawing_file_number": DRAWING_FILE_NUMBER,
        "created": {
            "pile_cap": 1,
            "piles": len(data["pile_centers"]),
            "native_cap_mat_x_bars": 2 * len(y_positions),
            "native_cap_mat_y_bars": 2 * len(x_positions),
            "mat_bar_end_hook_length": data["mat_hook_length"],
            "mat_bar_end_hook_angle": data["mat_hook_angle"],
            "native_pile_vertical_bar_placements": len(data["pile_centers"]),
            "native_pile_vertical_bars": len(data["pile_centers"]) * data["pile_vertical_count"],
            "pile_vertical_top_hook_length": data["pile_vertical_top_hook_length"],
            "pile_vertical_top_hook_angle": data["pile_vertical_top_hook_angle"],
            "native_pile_hoop_stacks": len(data["pile_centers"]),
            "native_pile_hoops": len(data["pile_centers"]) * pile_hoop_count,
        },
        "inputs": data,
    }
