"""Lanzador de la interfaz individual para el Dron 2."""

from control_dron_individual_interfaz import main
from prueba_estabilidad_dos_drones_lowlevel import DEFAULT_TOPIC_2, DEFAULT_URI_2


if __name__ == "__main__":
    main("Dron 2", DEFAULT_URI_2, DEFAULT_TOPIC_2)
