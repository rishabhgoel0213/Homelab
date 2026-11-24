{ pkgs }:

pkgs.python3.withPackages (pythonPackages: [
  pythonPackages.ipykernel
  pythonPackages.jupyterlab
])
