# Documentación

Documentación transversal del proyecto. Las instrucciones de uso de cada
controlador viven en el README de su carpeta.

- [Arquitectura y dependencias](architecture.md): carpetas, flujo de dependencias y deuda conocida.
- [Operación y seguridad](operations.md): ejecución, resultados, validaciones y restricciones de hardware.
- [Pipeline de gestos por visión](gesture_pipeline.md): contrato `GestureEvent`, ubicación de los módulos de reconocimiento y orden de implementación.
- [Refactorización de septiembre de 2026](refactor_2026-09.md): qué se eliminó, qué se fusionó y cómo queda el repositorio.
- [Comandos para probar](COMANDOS_PARA_PROBAR.md): recetario de comandos por controlador.
- [Plan de reconocimiento de gestos](plan_reconocimiento_gestos_robotat.md): plan original del subsistema de gestos.
- [Vídeo de presentación](video_3min.md): guion y cómo grabar y renderizar las sesiones en HD.
- [`reports/`](reports): estudios del backflip (revisión, simulación en MATLAB y plan).
- `Guia_comandos_controladores_Crazyflie.docx`: guía histórica, no se regenera.

Guías por subsistema:

- [Controlador sobre el Robotat](../controllers/single_drone/robotat/README.md)
- [Control por cámara de un dron](../controllers/single_drone/camera/README.md)
- [Control de la cruz con dos drones](../controllers/two_drones/README_CONTROL_CRUZ_PYTHON.md)
- [Joystick con marker](../controllers/joystick/README.md)
- [Detección de gestos](../external/gesture_detection/README.md)
- [Percepción 3D multicámara](../external/mapeo3d/README.md)
- [Panel web](../web/README.md)
