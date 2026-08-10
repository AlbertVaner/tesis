"""
propeller_test_crazyflie.py

Prueba oficial de hélices/motores del Crazyflie usando cflib.
Activa health.startPropTest y captura mensajes de consola HEALTH.

Autor: Albert + ChatGPT
"""

import logging
import time
from datetime import datetime

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.crazyflie.log import LogConfig
from cflib.crazyflie.syncLogger import SyncLogger


# ==========================
# CONFIGURACIÓN
# ==========================

URI = "radio://0/84/2M/E7E7E7E7E4"  # cambia esto si usas otro dron

LOG_FILE = "resultado_propeller_test.txt"

TEST_TIMEOUT_S = 25          # tiempo máximo de espera
CONSOLE_WAIT_AFTER_TEST = 3  # espera extra para recibir últimos mensajes


# ==========================
# VARIABLES GLOBALES
# ==========================

console_lines = []


def console_callback(text):
    """
    Captura mensajes de consola del Crazyflie.
    El Propeller Test imprime líneas tipo HEALTH.
    """
    global console_lines

    clean_text = text.strip()
    if clean_text:
        print(clean_text)
        console_lines.append(clean_text)


def wait_for_param_download(scf, timeout=10):
    """
    Espera a que se descargue la TOC de parámetros.
    """
    print("Esperando descarga de parámetros...")
    start = time.time()

    while not scf.cf.param.is_updated:
        if time.time() - start > timeout:
            raise TimeoutError("No se pudieron descargar los parámetros del Crazyflie.")
        time.sleep(0.1)

    print("Parámetros listos.")


def read_battery_voltage(scf):
    """
    Lee pm.vbat si está disponible.
    No es obligatorio para correr el test, solo sirve como referencia.
    """
    lg = LogConfig(name="Battery", period_in_ms=100)
    lg.add_variable("pm.vbat", "float")

    try:
        with SyncLogger(scf, lg) as logger:
            for entry in logger:
                data = entry[1]
                return data.get("pm.vbat", None)
    except Exception as e:
        print(f"No pude leer batería: {e}")
        return None


def run_propeller_test(scf):
    """
    Activa el Propeller Test oficial del firmware.
    """
    print("\n==============================================")
    print("INICIANDO PROPELLER TEST")
    print("==============================================")
    print("Coloca el Crazyflie en una mesa plana y dura.")
    print("No lo sostengas con la mano.")
    print("Mantén dedos/cables lejos de las hélices.\n")

    input("Presiona ENTER cuando esté listo...")

    console_lines.clear()

    # Esto activa el test interno del firmware
    print("Activando health.startPropTest = 1 ...")
    scf.cf.param.set_value("health.startPropTest", "1")

    print("\nEscuchando resultados de consola...\n")

    start_time = time.time()
    while time.time() - start_time < TEST_TIMEOUT_S:
        time.sleep(0.25)

        # Si ya vimos resultados de M4 o algún FAIL, esperamos un poco y salimos
        joined = "\n".join(console_lines)
        if "Motor M4 variance" in joined or "Propeller test on M4" in joined:
            time.sleep(CONSOLE_WAIT_AFTER_TEST)
            break

    print("\n==============================================")
    print("TEST FINALIZADO O TIMEOUT ALCANZADO")
    print("==============================================")


def analyze_results():
    """
    Análisis simple de texto.
    No reemplaza el criterio del cfclient, pero ayuda a resumir.
    """
    joined = "\n".join(console_lines)

    print("\nResumen rápido:")

    if not console_lines:
        print("- No se capturaron mensajes de consola.")
        print("- Prueba desde cfclient > Console > Propeller test.")
        return

    motors = ["M1", "M2", "M3", "M4"]

    found_any_motor = False
    for m in motors:
        motor_lines = [line for line in console_lines if m in line]
        if motor_lines:
            found_any_motor = True
            print(f"\n{m}:")
            for line in motor_lines:
                print(f"  {line}")

    if not found_any_motor:
        print("- No encontré líneas específicas de M1-M4.")
        print("- Revisa la consola completa guardada en el archivo.")

    if "[FAIL]" in joined:
        print("\nDiagnóstico:")
        print("- El test reportó al menos un FAIL.")
        print("- Primero cambia/balancea la hélice de ese motor.")
        print("- Si el FAIL se queda en el mismo motor con hélice nueva, sospecha motor/eje.")
    elif "variance" in joined:
        print("\nDiagnóstico:")
        print("- Se capturaron varianzas de vibración.")
        print("- Compara qué motor tiene varianza mucho mayor que los demás.")
        print("- El motor con varianza muy alta es el sospechoso.")
    else:
        print("\nDiagnóstico:")
        print("- No se detectó PASS/FAIL ni varianzas claras en la salida capturada.")


def save_results():
    """
    Guarda resultados en TXT.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("Resultado Propeller Test Crazyflie\n")
        f.write(f"Fecha: {now}\n")
        f.write(f"URI: {URI}\n")
        f.write("=" * 50 + "\n\n")

        if console_lines:
            for line in console_lines:
                f.write(line + "\n")
        else:
            f.write("No se capturaron mensajes de consola.\n")

    print(f"\nResultados guardados en: {LOG_FILE}")


def main():
    logging.basicConfig(level=logging.ERROR)

    print("Inicializando drivers Crazyradio...")
    cflib.crtp.init_drivers(enable_debug_driver=False)

    cf = Crazyflie(rw_cache="./cache")

    # Captura consola del firmware
    cf.console.receivedChar.add_callback(console_callback)

    print(f"Conectando a: {URI}")

    try:
        with SyncCrazyflie(URI, cf=cf) as scf:
            print("Conectado correctamente.")

            wait_for_param_download(scf)

            vbat = read_battery_voltage(scf)
            if vbat is not None:
                print(f"Batería aproximada: {vbat:.2f} V")
                if vbat < 3.75:
                    print("ADVERTENCIA: batería baja. Mejor carga antes de diagnosticar motores.")
                    continuar = input("¿Quieres continuar de todos modos? (s/n): ").strip().lower()
                    if continuar != "s":
                        print("Cancelado por seguridad.")
                        return

            run_propeller_test(scf)
            analyze_results()
            save_results()

    except KeyboardInterrupt:
        print("\nInterrumpido por usuario.")
        save_results()

    except Exception as e:
        print("\nERROR:")
        print(e)
        print("\nRevisa:")
        print("- Que el URI sea correcto.")
        print("- Que Crazyradio esté conectado.")
        print("- Que el Crazyflie esté encendido.")
        print("- Que cfclient no esté conectado al mismo tiempo.")
        save_results()


if __name__ == "__main__":
    main()