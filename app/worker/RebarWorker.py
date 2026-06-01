import json
import math
import os
import sys
import traceback
from pathlib import Path

try:
    import NemAll_Python_AllplanSettings as AllplanSettings
except ImportError:
    AllplanSettings = None

try:
    import NemAll_Python_IFW_ElementAdapter as AllplanIFWAdapter
except ImportError:
    AllplanIFWAdapter = None

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


DRAWING_FILE_NUMBER = 1


def worker_file(file_name: str) -> Path:
    return Path(__file__).with_name(file_name)


def log(message: str) -> None:
    with worker_file("worker_log.txt").open("a", encoding="utf-8") as file:
        file.write(f"{message}\n")


def write_error(error: BaseException) -> None:
    error_path = worker_file("worker_error.txt")
    error_path.write_text(
        "".join(traceback.format_exception(type(error), error, error.__traceback__)),
        encoding="utf-8",
    )


def check_allplan_version(build_ele, version: float) -> bool:
    return True


def load_inputs() -> dict:
    with worker_file("inputs.json").open("r", encoding="utf-8") as file:
        return json.load(file)


def normalize_path(value: str) -> str:
    if not value:
        return ""
    return os.path.normcase(os.path.normpath(str(value).strip().strip('"')))


def get_current_project_path(context: dict) -> str:
    if AllplanSettings is None:
        context["current_project_path_error"] = "NemAll_Python_AllplanSettings is not available."
        return ""

    try:
        return str(AllplanSettings.AllplanPaths.GetCurPrjPath())
    except BaseException as error:
        context["current_project_path_error"] = repr(error)
        return ""


def get_allplan_path(context: dict, output_key: str, method_name: str) -> str:
    if AllplanSettings is None:
        context[f"{output_key}_error"] = "NemAll_Python_AllplanSettings is not available."
        return ""

    try:
        return str(getattr(AllplanSettings.AllplanPaths, method_name)())
    except BaseException as error:
        context[f"{output_key}_error"] = repr(error)
        return ""


def get_active_drawing_file_number(context: dict) -> int | None:
    try:
        return AllplanBaseElements.DrawingFileService.GetActiveFileNumber()
    except BaseException as error:
        context["active_drawing_file_static_error"] = repr(error)

    try:
        drawing_service = AllplanBaseElements.DrawingFileService()
        return drawing_service.GetActiveFileNumber()
    except BaseException as error:
        context["active_drawing_file_instance_error"] = repr(error)
        return None


def get_drawing_file_name(context: dict, drawing_file_number: int | None) -> tuple[bool, str]:
    if drawing_file_number is None:
        return False, ""

    try:
        ok, name = AllplanBaseElements.DrawingFileService.GetDrawingFileName(drawing_file_number)
        return bool(ok), str(name)
    except BaseException as error:
        context["drawing_file_name_static_error"] = repr(error)

    try:
        drawing_service = AllplanBaseElements.DrawingFileService()
        ok, name = drawing_service.GetDrawingFileName(drawing_file_number)
        return bool(ok), str(name)
    except BaseException as error:
        context["drawing_file_name_instance_error"] = repr(error)
        return False, ""


def get_active_document_name(context: dict) -> str:
    if AllplanIFWAdapter is None:
        context["active_document_name_error"] = "NemAll_Python_IFW_ElementAdapter is not available."
        return ""

    try:
        return str(AllplanIFWAdapter.DocumentNameService.GetActiveDocumentName())
    except BaseException as error:
        context["active_document_name_error"] = repr(error)
        return ""


def collect_project_context(data: dict, stage: str) -> dict:
    worker_context = data.get("_worker_context", {})
    context = {
        "stage": stage,
        "argv": sys.argv,
        "allplan_settings_available": AllplanSettings is not None,
        "expected_project_dir": worker_context.get("expected_project_dir", ""),
        "expected_project_xml": worker_context.get("expected_project_xml", ""),
        "expected_project_dir_name": worker_context.get("expected_project_dir_name", ""),
    }

    try:
        current_project_name, host_name = AllplanBaseElements.ProjectService.GetCurrentProjectNameAndHost()
        context["current_project_name"] = current_project_name
        context["host_name"] = host_name
    except BaseException as error:
        context["current_project_error"] = repr(error)
        context["current_project_name"] = ""
        context["host_name"] = ""

    context["current_project_path"] = get_current_project_path(context)
    context["tmp_path"] = get_allplan_path(context, "tmp_path", "GetTmpPath")
    context["usr_path"] = get_allplan_path(context, "usr_path", "GetUsrPath")

    active_drawing_file_number = get_active_drawing_file_number(context)
    context["active_drawing_file_number"] = active_drawing_file_number
    ok_drawing_file_name, drawing_file_name = get_drawing_file_name(context, active_drawing_file_number)
    context["active_drawing_file_name_ok"] = ok_drawing_file_name
    context["active_drawing_file_name"] = drawing_file_name
    context["active_document_name"] = get_active_document_name(context)

    worker_file("context_probe.json").write_text(
        json.dumps(context, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log(
        "Context probe "
        f"{stage}: project='{context.get('current_project_name', '')}', "
        f"path='{context.get('current_project_path', '')}'."
    )
    return context


def project_paths_match(context: dict) -> bool:
    expected_dir = normalize_path(context.get("expected_project_dir", ""))
    expected_xml = normalize_path(context.get("expected_project_xml", ""))
    current_path = normalize_path(context.get("current_project_path", ""))

    if not expected_dir or not current_path:
        return False

    return (
        current_path == expected_dir
        or current_path == expected_xml
        or current_path.startswith(expected_dir + os.sep)
    )


def assert_expected_project_context(context: dict) -> None:
    expected_dir = context.get("expected_project_dir", "")
    if not expected_dir:
        log("No expected project path was provided; skipping /l context validation.")
        return

    if project_paths_match(context):
        log(f"Validated active /l project: {context.get('current_project_path', '')}.")
        return

    raise RuntimeError(
        "Allplan is running the PythonPart in the wrong project. "
        f"Expected active project path '{expected_dir}', "
        f"but Allplan reported project '{context.get('current_project_name', '')}' "
        f"at path '{context.get('current_project_path', '')}'. "
        "Close every running Allplan instance and start the worker again so /l can own the startup project."
    )


def public_inputs(data: dict) -> dict:
    return {key: value for key, value in data.items() if not key.startswith("_")}


def load_drawing_file(doc) -> None:
    drawing_service = AllplanBaseElements.DrawingFileService()
    drawing_service.LoadFile(
        doc,
        DRAWING_FILE_NUMBER,
        AllplanBaseElements.DrawingFileLoadState.ActiveForeground,
    )


def create_element(build_ele, doc) -> CreateElementResult:
    try:
        log("Rebar PythonPart started.")
        data = load_inputs()
        run_id = data["run_id"]

        done_marker = worker_file("worker_done.txt")
        result_path = worker_file("result.json")

        log(f"Run ID: {run_id}.")
        context = collect_project_context(data, "before_load_drawing_file")
        assert_expected_project_context(context)

        log(f"Loading drawing file {DRAWING_FILE_NUMBER}.")
        load_drawing_file(doc)
        context = collect_project_context(data, "after_load_drawing_file")

        log("Creating concrete and reinforcement elements.")
        cap_with_piles = CapWithPiles(data)
        model_elements = cap_with_piles.build()

        result = build_result(data, run_id, context.get("current_project_name", ""))
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        log("result.json written.")

        done_marker.write_text("done", encoding="utf-8")
        log("worker_done.txt written.")

        return CreateElementResult(
            elements=model_elements,
            placement_point=AllplanGeo.Point3D(),
        )

    except BaseException as error:
        log(f"Worker failed: {error}")
        write_error(error)
        raise




class CapWithPiles:
    def __init__(self, data: dict):
        self.data = data
        self.elements = ModelEleList()

    def build(self) -> ModelEleList:
        self.add_concrete_geometry()
        self.add_cap_rebar()
        self.add_pile_rebar()
        return self.elements

    def add_concrete_geometry(self) -> None:
        # Cap
        cap_placement = AllplanGeo.AxisPlacement3D(
            AllplanGeo.Point3D(
                -self.data["cap_length"] / 2.0,
                -self.data["cap_width"] / 2.0,
                0.0
            ),
            AllplanGeo.Vector3D(1.0, 0.0, 0.0),
            AllplanGeo.Vector3D(0.0, 0.0, 1.0),
        )
        self.elements.append_geometry_3d(
            AllplanGeo.BRep3D.CreateCuboid(
                cap_placement,
                self.data["cap_length"],
                self.data["cap_width"],
                self.data["cap_height"],
            )
        )

        # Piles
        for pile in self.data["pile_centers"]:
            pile_placement = AllplanGeo.AxisPlacement3D(
                AllplanGeo.Point3D(pile["x"], pile["y"], -self.data["pile_depth"]),
                AllplanGeo.Vector3D(1.0, 0.0, 0.0),
                AllplanGeo.Vector3D(0.0, 0.0, 1.0),
            )
            self.elements.append_geometry_3d(
                AllplanGeo.BRep3D.CreateCylinder(
                    pile_placement,
                    self.data["pile_diameter"] / 2.0,
                    self.data["pile_depth"],
                )
            )

    def add_cap_rebar(self) -> None:
        cover = self.data["cover"]
        x_min = -self.data["cap_length"] / 2.0 + cover
        x_max = self.data["cap_length"] / 2.0 - cover
        y_min = -self.data["cap_width"] / 2.0 + cover
        y_max = self.data["cap_width"] / 2.0 - cover
        z_bottom = cover
        z_top = self.data["cap_height"] - cover

        y_positions = self.positions_between(y_min, y_max, self.data["mat_spacing"])
        x_positions = self.positions_between(x_min, x_max, self.data["mat_spacing"])

        hook_length = self.hook_length(self.data["mat_hook_length"])
        hook_angle = float(self.data["mat_hook_angle"])

        # X-direction bars
        for index, y in enumerate(y_positions):
            # Bottom layer
            self.add_straight_rebar(
                position_number=1000 + index,
                diameter=self.data["mat_bar_diameter"],
                start_point=AllplanGeo.Point3D(x_min, y, z_bottom),
                end_point=AllplanGeo.Point3D(x_max, y, z_bottom),
                start_hook_length=hook_length,
                start_hook_angle=hook_angle,
                end_hook_length=hook_length,
                end_hook_angle=hook_angle,
            )
            # Top layer
            self.add_straight_rebar(
                position_number=2000 + index,
                diameter=self.data["mat_bar_diameter"],
                start_point=AllplanGeo.Point3D(x_min, y, z_top),
                end_point=AllplanGeo.Point3D(x_max, y, z_top),
                start_hook_length=hook_length,
                start_hook_angle=-hook_angle,
                end_hook_length=hook_length,
                end_hook_angle=-hook_angle,
            )

        # Y-direction bars
        for index, x in enumerate(x_positions):
            # Bottom layer
            self.add_straight_rebar(
                position_number=3000 + index,
                diameter=self.data["mat_bar_diameter"],
                start_point=AllplanGeo.Point3D(x, y_min, z_bottom),
                end_point=AllplanGeo.Point3D(x, y_max, z_bottom),
                start_hook_length=hook_length,
                start_hook_angle=hook_angle,
                end_hook_length=hook_length,
                end_hook_angle=hook_angle,
            )
            # Top layer
            self.add_straight_rebar(
                position_number=4000 + index,
                diameter=self.data["mat_bar_diameter"],
                start_point=AllplanGeo.Point3D(x, y_min, z_top),
                end_point=AllplanGeo.Point3D(x, y_max, z_top),
                start_hook_length=hook_length,
                start_hook_angle=-hook_angle,
                end_hook_length=hook_length,
                end_hook_angle=-hook_angle,
            )

    def add_pile_rebar(self) -> None:
        pile_radius = self.data["pile_diameter"] / 2.0
        cover = self.data["cover"]
        vertical_diameter = self.data["pile_vertical_diameter"]
        hoop_diameter = self.data["pile_hoop_diameter"]
        vertical_count = self.data["pile_vertical_count"]
        steel_grade = self.data.get("steel_grade", -1)
        concrete_grade = self.data.get("concrete_grade", -1)

        vertical_axis_radius = pile_radius - cover - vertical_diameter / 2.0
        hoop_axis_radius = pile_radius - cover - hoop_diameter / 2.0

        z_bottom = -self.data["pile_depth"] + cover
        hoop_z_top = -cover
        vertical_z_top = self.data["cap_height"] / 2.0

        top_hook_length = self.hook_length(self.data["pile_vertical_top_hook_length"])
        top_hook_angle = float(self.data["pile_vertical_top_hook_angle"])

        for pile_index, pile in enumerate(self.data["pile_centers"]):
            cx = pile["x"]
            cy = pile["y"]

            # Vertical bars
            self.add_pile_vertical_bars(
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

            # Circular hoops
            self.add_circular_hoops(
                position_number=6000 + pile_index,
                diameter=hoop_diameter,
                cx=cx,
                cy=cy,
                radius=hoop_axis_radius,
                z_start=z_bottom,
                z_end=hoop_z_top,
                spacing=self.data["pile_hoop_spacing"],
            )

    def add_straight_rebar(
        self,
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
        bending_shape = self.create_straight_shape(
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
        self.elements.append(placement)

    def add_pile_vertical_bars(
        self,
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
        start_point = AllplanGeo.Point3D(cx + radius, cy, z_bottom)
        end_point = AllplanGeo.Point3D(cx + radius, cy, z_top)

        bending_shape = self.create_straight_shape(
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

        self.elements.append(placement)

    def add_circular_hoops(
        self,
        position_number: int,
        diameter: float,
        cx: float,
        cy: float,
        radius: float,
        z_start: float,
        z_end: float,
        spacing: float,
    ) -> None:
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
            0.0,
            360.0,
            0.0,
            360.0,
            0.0,
            0.0,
            0.0,
        )

        circular_area.SetBarProperties(
            spacing,
            18000.0,
            1000.0,
            0,
            18000.0,
            18000.0,
            0.0,
            10000.0,
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

        self.elements.append(circular_area)

    def create_straight_shape(
        self,
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
        dx = end_point.X - start_point.X
        dy = end_point.Y - start_point.Y
        dz = end_point.Z - start_point.Z
        length = math.sqrt(dx * dx + dy * dy + dz * dz)

        shape_properties = ReinforcementShapeProperties.rebar(
            diameter=diameter,
            bending_roller=-1,
            steel_grade=steel_grade,
            concrete_grade=concrete_grade,
            bending_shape_type=AllplanReinf.BendingShapeType.LongitudinalBar,
        )

        has_hook = start_hook_length >= 0.0 or end_hook_length >= 0.0
        if has_hook:
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

        already_aligned = (
            abs(target_x - 1.0) <= 0.000001
            and abs(target_y) <= 0.000001
            and abs(target_z) <= 0.000001
        )

        if not already_aligned:
            rotation_matrix = AllplanGeo.Matrix3D()
            rotation_matrix.SetRotation(
                AllplanGeo.Vector3D(1.0, 0.0, 0.0),
                AllplanGeo.Vector3D(target_x, target_y, target_z),
            )
            bending_shape.Transform(rotation_matrix)

        bending_shape.Move(
            AllplanGeo.Vector3D(start_point.X, start_point.Y, start_point.Z)
        )

        return bending_shape

    @staticmethod
    def hook_length(length: float) -> float:
        return -1.0 if length <= 0.0 else float(length)

    @staticmethod
    def positions_between(start: float, end: float, spacing: float) -> list[float]:
        if end < start:
            return []
        span = end - start
        count = int(span // spacing) + 1
        if count <= 1:
            return [(start + end) / 2.0]
        return [start + index * span / (count - 1) for index in range(count)]


def build_result(data: dict, run_id: str, project_name: str) -> dict:
    cover = data["cover"]
    x_positions = CapWithPiles.positions_between(
        -data["cap_length"] / 2.0 + cover,
        data["cap_length"] / 2.0 - cover,
        data["mat_spacing"],
    )
    y_positions = CapWithPiles.positions_between(
        -data["cap_width"] / 2.0 + cover,
        data["cap_width"] / 2.0 - cover,
        data["mat_spacing"],
    )
    pile_rebar_bottom_z = -data["pile_depth"] + cover
    pile_hoop_top_z = -cover
    pile_hoop_count = len(
        CapWithPiles.positions_between(
            pile_rebar_bottom_z, pile_hoop_top_z, data["pile_hoop_spacing"]
        )
    )

    return {
        "run_id": run_id,
        "project_name": project_name,
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
        "inputs": public_inputs(data),
    }
