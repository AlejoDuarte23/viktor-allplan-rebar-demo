VIKTOR demo app for a simple pile cap rebar workflow in Allplan.

The app keeps the flow small and easy to follow:

- Parametrize a rectangular pile cap on four piles.
- Configure concrete cover, cap mat bars, pile vertical bars, and pile hoops in VIKTOR.
- Review a clean 2D sketch and a simple quantity table.
- Send the same parameters to an Allplan PythonPart worker.
- Download an Allplan project with the pile cap, piles, and visible rebar layout.

The current version uses regular 3D geometry to show the rebar in Allplan. This keeps the demo stable and easy to run. Creating native Allplan reinforcement entities is still work in progress.

![VIKTOR app](assets/viktor-app.png)

![Allplan results](assets/allplan-results.png)
