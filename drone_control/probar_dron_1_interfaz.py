"""Lanzador de la interfaz individual para el Dron 1."""

from control_dron_individual_interfaz import main
from prueba_estabilidad_dos_drones_lowlevel import DEFAULT_TOPIC_1, DEFAULT_URI_1


if __name__ == "__main__":
    main("Dron 1", DEFAULT_URI_1, DEFAULT_TOPIC_1)
