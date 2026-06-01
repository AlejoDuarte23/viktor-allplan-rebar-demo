VIKTOR demo app for a simple pile cap rebar workflow in Allplan.

The app keeps the flow small and easy to follow:

- Parametrize a rectangular pile cap on four piles.
- Configure concrete cover, cap mat bars, pile vertical bars, and pile hoops in VIKTOR.
- Review a clean 2D sketch and a simple quantity table.
- Send the same parameters to an Allplan PythonPart worker.
- Download an Allplan project with the pile cap, piles, and native Allplan reinforcement.

The Allplan worker creates real reinforcement entities for the cap mats, pile vertical bars, and pile hoops. Mat bars and pile vertical bars can include 90-degree hooks from the VIKTOR inputs.

The worker uses a clean project ZIP template for each run. It resets the registered Allplan project `viktor-template` under `C:\Data\Allplan\Allplan 2026\Prj\viktor-template.prj`, opens it with Allplan's `/l ...\Project1.Dat.xml` startup argument, runs the PythonPart with `-o`, and returns the modified project as `result_project.zip`. The project root and name can be overridden with `ALLPLAN_PROJECTS_DIR` and `ALLPLAN_PROJECT_NAME` on the worker machine.

## First-time Allplan setup

Before running the VIKTOR worker on a new Windows machine, create or import a registered Allplan project named `viktor-template`.

The default expected project folder is:

```text
C:\Data\Allplan\Allplan 2026\Prj\viktor-template.prj
```

The worker expects this file to exist:

```text
C:\Data\Allplan\Allplan 2026\Prj\viktor-template.prj\Project1.Dat.xml
```

In Allplan Project Management, confirm that `viktor-template` appears under `Local`. This project is used as a disposable worker target: the worker closes existing Allplan sessions, resets the project folder from `viktor-template.prj.zip`, runs the PythonPart, and returns the modified project ZIP. Do not use `viktor-template` for manual production work.

If the worker machine uses a different project root or project name, set these environment variables before starting the VIKTOR worker:

```powershell
$env:ALLPLAN_PROJECTS_DIR = "C:\Data\Allplan\Allplan 2026\Prj"
$env:ALLPLAN_PROJECT_NAME = "viktor-template"
```

![VIKTOR app](assets/viktor-app.png)

![Allplan results](assets/allplan-results.png)
