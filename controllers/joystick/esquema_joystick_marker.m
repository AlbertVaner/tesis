function rutas = esquema_joystick_marker(carpeta_salida)
%ESQUEMA_JOYSTICK_MARKER Genera lámina técnica en PDF y PNG del Joystick Marker Robotat.
%
%   esquema_joystick_marker() genera el diagrama vectorial con:
%     1. Principio de funcionamiento y arquitectura de control espacial.
%     2. Curva de transferencia y Zona Muerta Angular (Pitch/Roll -> v_x, v_y).
%     3. Zona Muerta Vertical y disparo del comando de Aterrizaje (Delta Z).
%     4. Plano de inclinación 2D (Roll vs. Pitch) y direcciones de vuelo.
%     5. Matriz de comandos, umbrales y límites de seguridad del firmware.
%
%   Guarda en results/graphs/joystick/<fecha>/ y en thesis/figuras/.

if nargin < 1 || isempty(carpeta_salida)
    raiz = fileparts(fileparts(fileparts(mfilename('fullpath'))));
    hoy = char(datetime('today', 'Format', 'yyyy-MM-dd'));
    carpeta_salida = fullfile(raiz, 'results', 'graphs', 'joystick', hoy);
end

raiz_proyecto = fileparts(fileparts(fileparts(mfilename('fullpath'))));
carpeta_tesis = fullfile(raiz_proyecto, 'thesis', 'figuras');

if ~isfolder(carpeta_salida), mkdir(carpeta_salida); end
if ~isfolder(carpeta_tesis), mkdir(carpeta_tesis); end

% --- Paleta de colores para publicación científica ---
c_azul_tit    = [0.06 0.16 0.36];    % Azul noche institucional
c_azul_eje    = [0.10 0.45 0.82];    % Curva activa y vectores principales
c_turquesa    = [0.08 0.60 0.54];    % Rampa proporcional / Roll
c_coral       = [0.85 0.22 0.20];    % Aterrizaje de seguridad y alertas
c_verde       = [0.15 0.62 0.30];    % Ascenso / Z positivo
c_gris_muerto = [0.90 0.92 0.95];    % Zona muerta (sombreado neutro)
c_gris_sat    = [0.94 0.96 0.98];    % Zona de saturación
c_gris_borde  = [0.72 0.76 0.82];    % Líneas de división y marcos
c_gris_texto  = [0.38 0.42 0.48];    % Texto secundario y notas
c_card_bg     = [0.975 0.982 0.990]; % Fondo de tarjetas
c_blanco      = [1.0 1.0 1.0];

% Dimensiones de la lámina (15.5 x 10.0 pulgadas, formato amplio)
W = 15.5;
H = 10.0;
f = figure('Visible', 'off', 'Color', c_blanco, 'Units', 'inches', ...
    'Position', [0 0 W H], 'PaperPositionMode', 'auto', 'InvertHardcopy', 'off');
limpieza = onCleanup(@() close(f));

% =========================================================================
% ENCABEZADO
% =========================================================================
annotation(f, 'textbox', [0.03 0.930 0.94 0.055], ...
    'String', 'Control de Drones Mediante Joystick Marker Robotat (Rigid Body ID 64)', ...
    'EdgeColor', 'none', 'HorizontalAlignment', 'center', 'VerticalAlignment', 'middle', ...
    'FontName', 'Arial', 'FontSize', 18, 'FontWeight', 'bold', 'Color', c_azul_tit, ...
    'Interpreter', 'none');

annotation(f, 'textbox', [0.03 0.892 0.94 0.032], ...
    'String', 'Arquitectura de Operación Espacial, Zonas Muertas (Angulares y Verticales) y Mapeo de Comandos al Firmware', ...
    'EdgeColor', 'none', 'HorizontalAlignment', 'center', 'VerticalAlignment', 'middle', ...
    'FontName', 'Arial', 'FontSize', 11, 'Color', c_gris_texto, ...
    'Interpreter', 'none');

% Línea divisoria superior
annotation(f, 'line', [0.03 0.97], [0.888 0.888], 'Color', c_gris_borde, 'LineWidth', 1.0);

% =========================================================================
% PANEL 1: PRINCIPIO DE FUNCIONAMIENTO Y FLUJO DEL CONTROLADOR
% =========================================================================
ax1 = axes(f, 'Units', 'inches', 'Position', [0.70 5.25 3.80 3.35], 'Color', c_blanco);
hold(ax1, 'on'); axis(ax1, 'equal'); axis(ax1, [-2.2 2.2 -1.7 2.1]); axis(ax1, 'off');
title(ax1, 'A. Funcionamiento y Orientación Espacial', 'FontName', 'Arial', ...
    'FontSize', 11.5, 'FontWeight', 'bold', 'Color', c_azul_tit, 'Interpreter', 'none');

% Base física del Marker Joystick (Rigid Body ID 64 en Robotat)
plot(ax1, [-1.1 1.1], [0 0], '-', 'Color', [0.28 0.32 0.38], 'LineWidth', 3.5);
plot(ax1, [0 0], [-0.85 0.85], '-', 'Color', [0.28 0.32 0.38], 'LineWidth', 3.5);

% Marcadores reflectivos pasivos (esferas OptiTrack)
pos_m = [-1.1 0; 1.1 0; 0 -0.85; 0.50 0.45];
for m = 1:size(pos_m, 1)
    plot(ax1, pos_m(m,1), pos_m(m,2), 'o', 'MarkerSize', 11, ...
        'MarkerFaceColor', [0.95 0.97 1.0], 'MarkerEdgeColor', c_azul_eje, 'LineWidth', 2.0);
end
plot(ax1, 0, 0, '+', 'MarkerSize', 8, 'Color', c_coral, 'LineWidth', 1.5);
text(ax1, 0.12, -0.16, 'Cero Referencia (Set Zero)', 'FontName', 'Arial', 'FontSize', 8, ...
    'FontWeight', 'bold', 'Color', c_gris_texto, 'Interpreter', 'none');

% Flechas de inclinación Roll y Pitch
dibujar_flecha_curva(ax1, 0, 1.35, 0.45, 25, 155, c_azul_eje, 'Pitch (\theta) \rightarrow v_x');
dibujar_flecha_curva(ax1, 1.40, 0, 0.45, -65, 65, c_turquesa, 'Roll (\phi) \rightarrow v_y');

% Cuadro de flujo de datos simplificado
annotation(f, 'rectangle', [0.70/W 5.25/H 3.80/W 0.92/H], ...
    'FaceColor', c_card_bg, 'EdgeColor', c_gris_borde, 'LineWidth', 0.8);
annotation(f, 'textbox', [0.74/W 5.26/H 3.72/W 0.88/H], ...
    'String', {
        'Flujo de Telemetría y Control:';
        '1. OptiTrack publica pose a 60 Hz por MQTT (mocap/all).';
        '2. marker_input.py filtra ID 64 y resta pose de calibración.';
        '3. Genera velocidad con rampa suave (actualización cada 250 ms).';
        '4. cruz_highlevel_backend.py comanda pasos al Crazyflie 2.1.'
    }, 'EdgeColor', 'none', 'FontName', 'Arial', 'FontSize', 7.8, ...
    'Color', c_azul_tit, 'Interpreter', 'none');

% =========================================================================
% PANEL 2: CURVA DE TRANSFERENCIA Y ZONA MUERTA ANGULAR
% =========================================================================
% Espacio ampliado para evitar solapes con panel C
ax2 = axes(f, 'Units', 'inches', 'Position', [5.05 5.45 4.10 3.05], 'Color', c_blanco);
hold(ax2, 'on'); box(ax2, 'on'); grid(ax2, 'on');
set(ax2, 'GridColor', [0.85 0.88 0.92], 'GridAlpha', 0.8, 'FontName', 'Arial', 'FontSize', 8.5);

ang = linspace(-35, 35, 300);
v_max = 0.12;     % m/s
theta_dz = 12.0;  % deg
theta_sat = 28.0; % deg

v_salida = zeros(size(ang));
for i = 1:numel(ang)
    a = ang(i);
    mag = abs(a);
    if mag <= theta_dz
        v_salida(i) = 0.0;
    else
        ramp = (mag - theta_dz) / (theta_sat - theta_dz);
        v_salida(i) = sign(a) * v_max * max(0.0, min(1.0, ramp));
    end
end

% Área sombreada de Zona Muerta
patch(ax2, [-theta_dz theta_dz theta_dz -theta_dz], [-0.15 -0.15 0.15 0.15], ...
    c_gris_muerto, 'EdgeColor', 'none', 'FaceAlpha', 0.8);

% Área sombreada de Saturación
patch(ax2, [theta_sat 35 35 theta_sat], [0 0 0.15 0.15], ...
    c_gris_sat, 'EdgeColor', 'none', 'FaceAlpha', 0.7);
patch(ax2, [-35 -theta_sat -theta_sat -35], [-0.15 -0.15 0 0], ...
    c_gris_sat, 'EdgeColor', 'none', 'FaceAlpha', 0.7);

% Curva de velocidad comandada
plot(ax2, ang, v_salida, '-', 'Color', c_azul_eje, 'LineWidth', 2.6);

% Líneas guías de umbrales
plot(ax2, [-theta_dz -theta_dz], [-0.14 0.14], '--', 'Color', [0.55 0.60 0.68], 'LineWidth', 1.1);
plot(ax2, [theta_dz theta_dz], [-0.14 0.14], '--', 'Color', [0.55 0.60 0.68], 'LineWidth', 1.1);
plot(ax2, [-theta_sat -theta_sat], [-0.14 0.14], ':', 'Color', [0.55 0.60 0.68], 'LineWidth', 1.1);
plot(ax2, [theta_sat theta_sat], [-0.14 0.14], ':', 'Color', [0.55 0.60 0.68], 'LineWidth', 1.1);
plot(ax2, [-35 35], [0 0], '-', 'Color', [0.4 0.4 0.4], 'LineWidth', 0.8);

% Puntos de inflexión
plot(ax2, [-theta_sat -theta_dz theta_dz theta_sat], [-v_max 0 0 v_max], 'o', ...
    'MarkerSize', 5.5, 'MarkerFaceColor', c_blanco, 'MarkerEdgeColor', c_azul_tit, 'LineWidth', 1.8);

% Etiquetas de regiones
text(ax2, 0, 0.045, {'ZONA MUERTA', '\pm12^\circ', '(Hover: v = 0)'}, ...
    'FontName', 'Arial', 'FontSize', 8, 'FontWeight', 'bold', 'HorizontalAlignment', 'center', ...
    'Color', [0.30 0.35 0.42], 'Interpreter', 'tex');

text(ax2, 20, 0.065, {'Rampa Lineal', '(12^\circ \rightarrow 28^\circ)'}, ...
    'FontName', 'Arial', 'FontSize', 7.5, 'HorizontalAlignment', 'center', ...
    'Color', c_turquesa, 'Interpreter', 'tex');

text(ax2, 31.8, 0.105, {'Saturación', '+0.12 m/s'}, ...
    'FontName', 'Arial', 'FontSize', 7.5, 'HorizontalAlignment', 'center', ...
    'Color', c_azul_tit, 'Interpreter', 'none');

xlabel(ax2, 'Inclinación de la Mano: Roll (\phi) o Pitch (\theta) [^\circ]', ...
    'FontName', 'Arial', 'FontSize', 9, 'FontWeight', 'bold', 'Color', c_azul_tit, 'Interpreter', 'tex');
ylabel(ax2, 'Velocidad Comandada v_x, v_y [m/s]', ...
    'FontName', 'Arial', 'FontSize', 9, 'FontWeight', 'bold', 'Color', c_azul_tit, 'Interpreter', 'tex');
title(ax2, 'B. Mapeo Proporcional con Zona Muerta Angular', 'FontName', 'Arial', ...
    'FontSize', 11.5, 'FontWeight', 'bold', 'Color', c_azul_tit, 'Interpreter', 'none');
xlim(ax2, [-35 35]); ylim(ax2, [-0.145 0.145]);

% =========================================================================
% PANEL 3: CONTROL VERTICAL (\Delta Z) Y COMANDO DE ATERRIZAJE
% =========================================================================
% Posicionado a la derecha con margen amplio para su etiqueta de eje Y
ax3 = axes(f, 'Units', 'inches', 'Position', [10.45 5.45 4.35 3.05], 'Color', c_blanco);
hold(ax3, 'on'); box(ax3, 'on');
set(ax3, 'FontName', 'Arial', 'FontSize', 8.5);

% Barra vertical indicadora (gauge de altitud)
x_bar = -0.55;
w_bar = 0.45;

% Región Ascenso (> +8 cm)
patch(ax3, [x_bar-w_bar x_bar+w_bar x_bar+w_bar x_bar-w_bar], [8 8 20 20], ...
    [0.86 0.95 0.88], 'EdgeColor', 'none');
% Región Zona Muerta Vertical (-8 a +8 cm)
patch(ax3, [x_bar-w_bar x_bar+w_bar x_bar+w_bar x_bar-w_bar], [-8 -8 8 8], ...
    c_gris_muerto, 'EdgeColor', 'none');
% Región Descenso Normal (-10 a -8 cm)
patch(ax3, [x_bar-w_bar x_bar+w_bar x_bar+w_bar x_bar-w_bar], [-10 -10 -8 -8], ...
    [0.98 0.93 0.86], 'EdgeColor', 'none');
% Región Disparo de Aterrizaje (< -10 cm sostenido)
patch(ax3, [x_bar-w_bar x_bar+w_bar x_bar+w_bar x_bar-w_bar], [-22 -22 -10 -10], ...
    [0.98 0.86 0.85], 'EdgeColor', 'none');

% Contorno de la barra graduada
plot(ax3, [x_bar-w_bar x_bar+w_bar x_bar+w_bar x_bar-w_bar x_bar-w_bar], ...
    [-22 -22 20 20 -22], '-', 'Color', c_gris_borde, 'LineWidth', 1.2);

% Líneas de umbral
plot(ax3, [-1.1 0.1], [8 8], '--', 'Color', c_verde, 'LineWidth', 1.2);
plot(ax3, [-1.1 0.1], [0 0], '-', 'Color', [0.3 0.3 0.3], 'LineWidth', 1.0);
plot(ax3, [-1.1 0.1], [-8 -8], '--', 'Color', [0.4 0.5 0.6], 'LineWidth', 1.2);
plot(ax3, [-1.1 0.1], [-10 -10], '-', 'Color', c_coral, 'LineWidth', 1.8);

% Textos descriptivos de las zonas verticales sin errores de sintaxis
text(ax3, 0.25, 14, {'ASCENSO', '\Delta z \geq +8 cm', '(Paso vertical \leq +8 cm)'}, ...
    'FontName', 'Arial', 'FontSize', 8, 'FontWeight', 'bold', 'Color', [0.12 0.52 0.22], ...
    'Interpreter', 'tex');

text(ax3, 0.25, 0, {'ZONA MUERTA', '[-8 cm, +8 cm]', '\Delta z = 0 (Hover en Z)'}, ...
    'FontName', 'Arial', 'FontSize', 8, 'FontWeight', 'bold', 'Color', [0.35 0.40 0.45], ...
    'Interpreter', 'tex');

text(ax3, 0.25, -8.8, 'Descenso suave', ...
    'FontName', 'Arial', 'FontSize', 7.5, 'Color', [0.65 0.42 0.10], 'Interpreter', 'none');

text(ax3, 0.25, -16, {'COMANDO ATERRIZAR', '\Delta z \leq -10 cm (\geq 0.5 s sostenido)', '\rightarrow Orden: Command(''land'')'}, ...
    'FontName', 'Arial', 'FontSize', 8, 'FontWeight', 'bold', 'Color', c_coral, ...
    'Interpreter', 'tex');

xlim(ax3, [-1.2 3.2]); ylim(ax3, [-22 21]);
set(ax3, 'YTick', [-20 -10 -8 0 8 20], ...
    'YTickLabel', {'-20 cm', '-10 cm (Land)', '-8 cm', '0 (Cero)', '+8 cm', '+20 cm'});
set(ax3, 'XTick', []);
ylabel(ax3, 'Desplazamiento Vertical Relativo \Delta z [cm]', ...
    'FontName', 'Arial', 'FontSize', 9, 'FontWeight', 'bold', 'Color', c_azul_tit, 'Interpreter', 'tex');
title(ax3, 'C. Altura y Disparo de Aterrizaje', 'FontName', 'Arial', ...
    'FontSize', 11.5, 'FontWeight', 'bold', 'Color', c_azul_tit, 'Interpreter', 'none');

% =========================================================================
% PANEL 4: PLANO BIDIMENSIONAL ROLL vs PITCH Y COMANDOS DE DIRECCIÓN
% =========================================================================
ax4 = axes(f, 'Units', 'inches', 'Position', [0.80 0.70 4.10 3.65], 'Color', c_blanco);
hold(ax4, 'on'); box(ax4, 'on'); grid(ax4, 'on');
set(ax4, 'GridColor', [0.88 0.90 0.93], 'FontName', 'Arial', 'FontSize', 8.5);

% Zona Muerta Cartesiana Central (+-12 deg)
patch(ax4, [-12 12 12 -12], [-12 -12 12 12], c_gris_muerto, ...
    'EdgeColor', [0.65 0.70 0.76], 'LineWidth', 1.2, 'FaceAlpha', 0.85);

% Círculo / anillo de saturación (28 deg)
ang_circ = linspace(0, 2*pi, 120);
plot(ax4, 28*cos(ang_circ), 28*sin(ang_circ), ':', 'Color', [0.6 0.65 0.75], 'LineWidth', 1.1);

% Ejes principales de referencia
plot(ax4, [-38 38], [0 0], '-', 'Color', [0.55 0.55 0.55], 'LineWidth', 0.8);
plot(ax4, [0 0], [-38 38], '-', 'Color', [0.55 0.55 0.55], 'LineWidth', 0.8);

% Flechas y etiquetas direccionales
% Adelante (+Pitch)
dibujar_flecha_vector(ax4, 0, 14, 0, 28, c_azul_eje);
text(ax4, 0, 31.5, 'ADELANTE (+v_x)', 'FontName', 'Arial', 'FontSize', 8.5, ...
    'FontWeight', 'bold', 'Color', c_azul_eje, 'HorizontalAlignment', 'center', 'Interpreter', 'tex');

% Atrás (-Pitch)
dibujar_flecha_vector(ax4, 0, -14, 0, -28, c_azul_eje);
text(ax4, 0, -32.5, 'ATRÁS (-v_x)', 'FontName', 'Arial', 'FontSize', 8.5, ...
    'FontWeight', 'bold', 'Color', c_azul_eje, 'HorizontalAlignment', 'center', 'Interpreter', 'tex');

% Izquierda (+Roll)
dibujar_flecha_vector(ax4, 14, 0, 28, 0, c_turquesa);
text(ax4, 31.0, 0, 'IZQ (+v_y)', 'FontName', 'Arial', 'FontSize', 8.5, ...
    'FontWeight', 'bold', 'Color', c_turquesa, 'HorizontalAlignment', 'left', 'Interpreter', 'tex');

% Derecha (-Roll)
dibujar_flecha_vector(ax4, -14, 0, -28, 0, c_turquesa);
text(ax4, -30.5, 0, 'DER (-v_y)', 'FontName', 'Arial', 'FontSize', 8.5, ...
    'FontWeight', 'bold', 'Color', c_turquesa, 'HorizontalAlignment', 'right', 'Interpreter', 'tex');

% Diagonales compuestas
text(ax4, 17, 17, 'Adelante-Izq', 'FontName', 'Arial', 'FontSize', 7.5, 'Color', c_gris_texto, 'Interpreter', 'none');
text(ax4, -17, 17, 'Adelante-Der', 'FontName', 'Arial', 'FontSize', 7.5, 'Color', c_gris_texto, 'Interpreter', 'none');
text(ax4, 17, -17, 'Atrás-Izq', 'FontName', 'Arial', 'FontSize', 7.5, 'Color', c_gris_texto, 'Interpreter', 'none');
text(ax4, -17, -17, 'Atrás-Der', 'FontName', 'Arial', 'FontSize', 7.5, 'Color', c_gris_texto, 'Interpreter', 'none');

% Texto central en Hover
text(ax4, 0, 0, {'HOVER', '\pm12^\circ'}, 'FontName', 'Arial', 'FontSize', 8, ...
    'FontWeight', 'bold', 'Color', [0.25 0.30 0.38], 'HorizontalAlignment', 'center', 'Interpreter', 'tex');

xlabel(ax4, 'Inclinación Lateral: Roll (\phi) [^\circ]', 'FontName', 'Arial', ...
    'FontSize', 9, 'FontWeight', 'bold', 'Color', c_azul_tit, 'Interpreter', 'tex');
ylabel(ax4, 'Inclinación Frontal: Pitch (\theta) [^\circ]', 'FontName', 'Arial', ...
    'FontSize', 9, 'FontWeight', 'bold', 'Color', c_azul_tit, 'Interpreter', 'tex');
title(ax4, 'D. Espacio de Inclinación 2D y Direcciones de Vuelo', 'FontName', 'Arial', ...
    'FontSize', 11.5, 'FontWeight', 'bold', 'Color', c_azul_tit, 'Interpreter', 'none');
xlim(ax4, [-38 38]); ylim(ax4, [-38 38]);

% =========================================================================
% PANEL 5: TABLA RESUMEN DE PARÁMETROS Y COMANDOS DEL JOYSTICK
% =========================================================================
ax5 = axes(f, 'Units', 'inches', 'Position', [5.30 0.70 9.50 3.65], 'Color', c_blanco);
hold(ax5, 'on'); axis(ax5, 'off'); axis(ax5, [0 1 0 1]);
title(ax5, 'E. Matriz de Comandos, Umbrales y Límites de Seguridad', 'FontName', 'Arial', ...
    'FontSize', 11.5, 'FontWeight', 'bold', 'Color', c_azul_tit, 'HorizontalAlignment', 'left', ...
    'Interpreter', 'none');

% Tarjeta de fondo
patch(ax5, [0 1 1 0], [0.02 0.02 0.96 0.96], c_card_bg, ...
    'EdgeColor', c_gris_borde, 'LineWidth', 1.0);

% Filas de la matriz de comandos con sintaxis TeX limpia
cabeceras = {'Acción / Comando', 'Variable de Entrada', 'Condición / Rango', 'Efecto sobre Crazyflie 2.1'};
filas = {
    'Hover / Reposo', 'Roll y Pitch (\phi, \theta)', 'abs(\phi) \leq 12^\circ  y  abs(\theta) \leq 12^\circ', 'v_x = 0, v_y = 0 m/s; mantiene posición fija';
    'Avance / Retroceso', 'Pitch (\theta)', '12^\circ a 28^\circ (rampa lineal)', 'v_x proporcional hasta \pm0.12 m/s (\pm3 cm/paso)';
    'Izquierda / Derecha', 'Roll (\phi)', '12^\circ a 28^\circ (rampa lineal)', 'v_y proporcional hasta \pm0.12 m/s (\pm3 cm/paso)';
    'Saturación Horizontal', 'Roll o Pitch', 'Inclinación \geq 28^\circ', 'Limita estrictamente a v_{max} = 0.12 m/s';
    'Hover Vertical', 'Desplazamiento Z (\Delta z)', 'abs(\Delta z) \leq 0.08 m (\pm8 cm)', 'Mantiene altitud de referencia fija';
    'Ascenso / Descenso', 'Desplazamiento Z (\Delta z)', 'abs(\Delta z) \geq 0.08 m  y  \Delta z \geq -0.10 m', 'Actualiza Z (paso vertical \leq 8 cm cada 250 ms)';
    'Comando ATERRIZAJE', 'Descenso sostenido (\Delta z)', '\Delta z \leq -0.10 m durante t \geq 0.5 s', 'Ejecuta Command(''land''); aterriza y corta motores';
    'Pérdida de Pose', 'Frescura señal OptiTrack', 'Sin actualización por t \geq 1.0 s', 'Alerta ''Marker perdido''; detiene movimiento seguro'
};

% Dibujar encabezado
y_t = 0.88;
x_cols = [0.025 0.235 0.445 0.720];
for c = 1:4
    text(ax5, x_cols(c), y_t, cabeceras{c}, 'FontName', 'Arial', 'FontSize', 8.5, ...
        'FontWeight', 'bold', 'Color', c_azul_tit, 'Interpreter', 'none');
end
plot(ax5, [0.015 0.985], [y_t-0.035 y_t-0.035], '-', 'Color', c_azul_eje, 'LineWidth', 1.5);

% Dibujar filas con sombreado alterno
y_fila = y_t - 0.10;
for r = 1:size(filas, 1)
    if mod(r, 2) == 0
        patch(ax5, [0.015 0.985 0.985 0.015], ...
            [y_fila-0.035 y_fila-0.035 y_fila+0.055 y_fila+0.055], ...
            [0.94 0.96 0.98], 'EdgeColor', 'none');
    end
    if r == 7
        col_txt = c_coral;
        peso = 'bold';
    else
        col_txt = [0.18 0.22 0.28];
        peso = 'normal';
    end
    for c = 1:4
        text(ax5, x_cols(c), y_fila, filas{r,c}, 'FontName', 'Arial', 'FontSize', 7.6, ...
            'FontWeight', peso, 'Color', col_txt, 'Interpreter', 'tex');
    end
    plot(ax5, [0.015 0.985], [y_fila-0.035 y_fila-0.035], '-', 'Color', [0.88 0.91 0.94], 'LineWidth', 0.5);
    y_fila = y_fila - 0.095;
end

% Pie de página con créditos
annotation(f, 'textbox', [0.03 0.015 0.94 0.03], ...
    'String', 'Fuente: controllers/joystick/marker_input.py y controllers/two_drones/experiment_session.py | Tesis de Licenciatura en Ingeniería Mecatrónica - UVG', ...
    'EdgeColor', 'none', 'HorizontalAlignment', 'center', 'FontName', 'Arial', 'FontSize', 8, ...
    'Color', c_gris_texto, 'Interpreter', 'none');

% =========================================================================
% EXPORTACIÓN EN PDF VECTORIAL Y PNG 300 DPI
% =========================================================================
drawnow;
base_res = fullfile(carpeta_salida, 'esquema_joystick_marker');
base_tes = fullfile(carpeta_tesis, 'joystick_marker_funcionamiento');

rutas.pdf = [base_res '.pdf'];
rutas.png = [base_res '.png'];
rutas.tesis_pdf = [base_tes '.pdf'];
rutas.tesis_png = [base_tes '.png'];

% Exportar a results/
exportgraphics(f, rutas.pdf, 'ContentType', 'vector', 'BackgroundColor', 'white');
exportgraphics(f, rutas.png, 'Resolution', 300, 'BackgroundColor', 'white');

% Exportar a thesis/figuras/
exportgraphics(f, rutas.tesis_pdf, 'ContentType', 'vector', 'BackgroundColor', 'white');
exportgraphics(f, rutas.tesis_png, 'Resolution', 300, 'BackgroundColor', 'white');

fprintf('\n[OK] Gráficas generadas exitosamente sin advertencias:\n');
fprintf(' - PDF vectorial: %s\n', rutas.pdf);
fprintf(' - PNG 300 DPI:   %s\n', rutas.png);
fprintf(' - Copia tesis:   %s\n\n', rutas.tesis_pdf);
end

% =========================================================================
% FUNCIONES AUXILIARES DE DIBUJO
% =========================================================================
function dibujar_flecha_vector(ax, x1, y1, x2, y2, color)
dx = x2 - x1; dy = y2 - y1;
quiver(ax, x1, y1, dx, dy, 0, 'Color', color, 'LineWidth', 2.0, ...
    'MaxHeadSize', 0.45);
end

function dibujar_flecha_curva(ax, xc, yc, r, ang1, ang2, color, texto)
t = linspace(deg2rad(ang1), deg2rad(ang2), 40);
x = xc + r*cos(t);
y = yc + r*sin(t);
plot(ax, x, y, '-', 'Color', color, 'LineWidth', 2.0);
quiver(ax, x(end-1), y(end-1), x(end)-x(end-1), y(end)-y(end-1), 0, ...
    'Color', color, 'LineWidth', 2.0, 'MaxHeadSize', 1.5);
text(ax, mean(x), mean(y)+0.22, texto, 'FontName', 'Arial', 'FontSize', 8, ...
    'FontWeight', 'bold', 'Color', color, 'HorizontalAlignment', 'center', 'Interpreter', 'tex');
end
