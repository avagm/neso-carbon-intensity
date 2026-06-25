# NESO Carbon Intensity Project - ELEC60014
Imperial College London | Group Project

Hourly carbon intensity of the GB electricity system for 2023, from PyPSA-GB
dispatch, validated against the NESO Carbon Intensity API.

## Layout

- `carbon_intensity_toolkit/`: the workflow (NESO pull, system and per-bus carbon
  intensity, copperplate, heatmap assembly). Self-contained, with its own README,
  requirements, docs, and 2023 results. Start here.
- `dashboard/`: interactive dashboard over the results. Run with
  `streamlit run dashboard/app.py`.
- `Legacy/`: earlier per-week scripts, results, data, docs, and the flyer.

PyPSA-GB, the dispatch model, is a separate dependency:
https://github.com/andrewlyden/PyPSA-GB
