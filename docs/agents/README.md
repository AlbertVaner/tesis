# Mapa de documentación para agentes

Este directorio amplía el contrato breve de `AGENTS.md` sin duplicar detalles de cada controlador.

- [Arquitectura y dependencias](architecture.md): raíces canónicas, flujo de dependencias y deuda conocida.
- [Operación y seguridad](operations.md): ejecución, resultados, validaciones y restricciones de hardware.
- [Pipeline de gestos por visión](gesture_pipeline.md): contrato `GestureEvent`, ubicación de los módulos de reconocimiento y orden de implementación.

Documentación funcional existente:

- `../Guia_comandos_controladores_Crazyflie.docx`
- `../../controllers/two_drones/README_CONTROL_CRUZ_PYTHON.md`
- `../../controllers/joystick/README.md`
- `../../external/gesture_detection/README.md`

Cuando cambie una ruta canónica, actualizar primero `AGENTS.md`, este índice y luego los documentos especializados afectados.
