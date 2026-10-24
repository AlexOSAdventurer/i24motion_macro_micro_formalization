# I24 Black Box Micro-Macro Coupling Formalization Repo

Welcome to this repo! The purpose of this one is to establish the well posedness of the black-box micro-macro traffic model coupling formalization presented in "Moving-boundary coupling of black box microscopic models to macroscopic traffic models: Formalization, Well-posedness, and Verification." This is achieved via testing an instantiation of the coupling in a few simplified scenarios and showing that it exhibits similar performance to a pure macroscopic simulation of the same scenario.

# Instructions

## Initial Instructions
1. Use either Linux or MacOS.
2. Run `./build.container.sh`. This builds the docker container that manages all the dependencies for you.
3. Run `./launch_container.sh` to access the container itself.

# Analysis/Reproducibility Instructions
Inside the container, perform these commands:
```bash
cd simplified_scenario_tests
python3 simulation_dataset_verification.py
python3 sim_verification.py
python3 analysis_helpers.py
```
You will see two new folders: ```figures/``` and ```tables/```. These contain the relevant figures from the work.

# Demo Instructions
Inside the container, perform these commands:

```bash
python3 simulation_dataset.py
python3 sim_demo.py
```
