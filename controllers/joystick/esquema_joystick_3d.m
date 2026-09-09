function rutas = esquema_joystick_3d(carpeta_salida, tema)
%ESQUEMA_JOYSTICK_3D Visualización volumétrica 3D del espacio de control del Joystick Marker.
%
%   esquema_joystick_3d() genera la gráfica espacial tridimensional inspirada
%   en la visualización del ecosistema Robotat con:
%     1. Prisma semi-transparente de Zona Muerta (Hover: +-12 deg, +-8 cm).
%     2. Envolvente exterior de saturación y rampa (28 deg, v_max = 0.12 m/s).
%     3. Sub-volumen inferior de Aterrizaje de seguridad (Delta z <= -10 cm, >= 0.5 s).
%     4. Representación física del Rigid Body ID 64 con esferas reflectivas.
%     5. Vectores 3D de comandos de vuelo (Adelante, Atrás, Izquierda, Derecha, Ascenso).
%     6. Leyenda flotante y anotaciones en formato de tesis UVG.
%
%   tema: 'oscuro' (por defecto, fondo oscuro de alto contraste) o 'claro' (fondo blanco).

if nargin < 1 || isempty(carpeta_salida)
    raiz = fileparts(fileparts(fileparts(mfilename('fullpath'))));
    hoy = char(datetime('today', 'Format', 'yyyy-MM-dd'));
    carpeta_salida = fullfile(raiz, 'results', 'graphs', 'joystick', hoy);
end
if nargin < 2 || isempty(tema)
    tema = 'oscuro';
end

raiz_proyecto = fileparts(fileparts(fileparts(mfilename('fullpath'))));
carpeta_tesis = fullfile(raiz_proyecto, 'thesis', 'figuras');

if ~isfolder(carpeta_salida), mkdir(carpeta_salida); end
if ~isfolder(carpeta_tesis), mkdir(carpeta_tesis); end

% --- Definición de paletas de color según el tema ---
es_oscuro = strcmpi(tema, 'oscuro');
if es_oscuro
    c_fondo       = [0.08 0.08 0.09];    % Fondo oscuro estilo terminal/render
    c_texto_tit   = [0.95 0.96 0.98];    % Blanco/hueso para texto principal
    c_texto_sec   = [0.75 0.80 0.85];    % Gris claro para subtítulos
    c_ejes        = [0.85 0.88 0.92];    % Ejes y números
    c_grid        = [0.28 0.32 0.38];    % Rejilla 3D
    c_wire_ext    = [0.85 0.88 0.92];    % Alambre de volumen exterior
    c_zm_face     = [0.15 0.52 0.88];    % Azul celeste volumétrico zona muerta
    c_zm_edge     = [0.40 0.80 1.00];    % Borde brillante zona muerta
    c_land_face   = [0.90 0.25 0.22];    % Rojo coral zona aterrizaje
    c_land_edge   = [1.00 0.45 0.40];    % Borde aterrizaje
    c_marker_body = [0.70 0.75 0.80];    % Estructura del marker
    c_marker_sph  = [1.00 0.45 0.45];    % Esferas reflectivas (salmón brillante)
    c_flecha_h    = [0.20 0.85 0.70];    % Flechas horizontales (turquesa)
    c_flecha_z    = [0.35 0.90 0.45];    % Flecha vertical ascenso (verde)
    c_leyenda_bg  = [0.12 0.13 0.15];    % Fondo de leyenda
    c_leyenda_bd  = [0.40 0.45 0.52];    % Borde de leyenda
else
    c_fondo       = [1.00 1.00 1.00];
    c_texto_tit   = [0.06 0.16 0.36];
    c_texto_sec   = [0.35 0.40 0.46];
    c_ejes        = [0.20 0.25 0.30];
    c_grid        = [0.82 0.85 0.90];
    c_wire_ext    = [0.45 0.50 0.56];
    c_zm_face     = [0.15 0.55 0.85];
    c_zm_edge     = [0.10 0.40 0.75];
    c_land_face   = [0.85 0.22 0.20];
    c_land_edge   = [0.70 0.15 0.15];
    c_marker_body = [0.25 0.28 0.32];
    c_marker_sph  = [0.85 0.25 0.25];
    c_flecha_h    = [0.08 0.60 0.54];
    c_flecha_z    = [0.15 0.65 0.30];
    c_leyenda_bg  = [0.96 0.97 0.98];
    c_leyenda_bd  = [0.75 0.78 0.82];
end

% Dimensiones de la lámina (14 x 9.5 pulgadas)
W = 14.0;
H = 9.5;
f = figure('Visible', 'off', 'Color', c_fondo, 'Units', 'inches', ...
    'Position', [0 0 W H], 'PaperPositionMode', 'auto', 'InvertHardcopy', 'off');
limpieza = onCleanup(@() close(f));

% =========================================================================
% TÍTULO SUPERIOR (Estilo Tesis UVG)
% =========================================================================


annotation(f, 'textbox', [0.05 0.88 0.90 0.04], ...
    'String', 'Control espacial en Robotat con Rigid Body ID 64 | Zonas muertas angulares (\pm12^\circ) y vertical (\pm8 cm)', ...
    'EdgeColor', 'none', 'HorizontalAlignment', 'center', 'VerticalAlignment', 'middle', ...
    'FontName', 'Arial', 'FontSize', 11, 'FontWeight', 'bold', 'Color', c_texto_sec, ...
    'Interpreter', 'tex');

% =========================================================================
% EJES PRINCIPALES 3D
% =========================================================================
ax = axes(f, 'Units', 'inches', 'Position', [0.8 1.10 12.4 7.3], 'Color', c_fondo);
hold(ax, 'on'); box(ax, 'on'); grid(ax, 'on');
set(ax, 'GridColor', c_grid, 'GridAlpha', 0.5, 'GridLineStyle', ':', ...
    'FontName', 'Arial', 'FontSize', 9.5, 'XColor', c_ejes, 'YColor', c_ejes, 'ZColor', c_ejes);

% 1. DIBUJAR VOLUMEN EXTERIOR (Límite de saturación: +-28 deg en Roll/Pitch, +-18 cm en Z)
%    Similar al "Volumen total del Robotat" de la imagen de referencia.
x_sat = 28; y_sat = 28; z_max = 18;
dibujar_caja_3d(ax, -x_sat, x_sat, -y_sat, y_sat, -z_max, z_max, ...
    'none', 0, c_wire_ext, 1.4, '-');

% Texto sobre el volumen exterior
text(ax, -x_sat, y_sat*0.9, z_max*1.04, 'Envolvente de saturación: \pm28^\circ | v_{max} = 0.12 m/s', ...
    'FontName', 'Arial', 'FontSize', 8.5, 'FontWeight', 'bold', 'Color', c_texto_sec, ...
    'HorizontalAlignment', 'left', 'Interpreter', 'tex');

% 2. DIBUJAR VOLUMEN DE ZONA MUERTA (Hover central: +-12 deg en Roll/Pitch, +-8 cm en Z)
%    Similar al "Área segura de trabajo" en azul semi-transparente de la referencia.
x_zm = 12; y_zm = 12; z_zm = 8;
dibujar_caja_3d(ax, -x_zm, x_zm, -y_zm, y_zm, -z_zm, z_zm, ...
    c_zm_face, 0.40, c_zm_edge, 2.0, '-');

% Etiqueta volumétrica central en el prisma de zona muerta
text(ax, 0, 0, z_zm*1.12, 'Zona Muerta / Hover (\pm12^\circ, \pm8 cm)', ...
    'FontName', 'Arial', 'FontSize', 9.5, 'FontWeight', 'bold', 'Color', c_zm_edge, ...
    'HorizontalAlignment', 'center', 'Interpreter', 'tex');

% 3. DIBUJAR SUB-VOLUMEN INFERIOR DE DISPARO DE ATERRIZAJE (Delta z <= -10 cm)
%    Franja roja semi-transparente en el fondo del volumen
z_land_top = -10; z_land_bot = -20;
dibujar_caja_3d(ax, -x_sat, x_sat, -y_sat, y_sat, z_land_bot, z_land_top, ...
    c_land_face, 0.28, c_land_edge, 1.6, '-');

% Etiqueta del comando de aterrizaje
text(ax, 0, 0, (z_land_top + z_land_bot)/2, ...
    'Comando: ATERRIZAJE (\Delta z \leq -10 cm sostenido \geq 0.5 s \rightarrow Land)', ...
    'FontName', 'Arial', 'FontSize', 8.5, 'FontWeight', 'bold', 'Color', c_land_edge, ...
    'HorizontalAlignment', 'center', 'Interpreter', 'tex');

% 4. DIBUJAR MODELO FÍSICO DEL MARKER (Rigid Body ID 64) EN EL ORIGEN (0,0,0)
% Brazos del rigid body
plot3(ax, [-6 6], [0 0], [0 0], '-', 'Color', c_marker_body, 'LineWidth', 3.0);
plot3(ax, [0 0], [-5 5], [0 0], '-', 'Color', c_marker_body, 'LineWidth', 3.0);

% 4 Esferas reflectivas pasivas OptiTrack
pos_sph = [
    -6   0  0;
     6   0  0;
     0  -5  0;
     2.5 3  1.5
];
for s = 1:size(pos_sph, 1)
    plot3(ax, pos_sph(s,1), pos_sph(s,2), pos_sph(s,3), 's', 'MarkerSize', 8, ...
        'MarkerFaceColor', c_marker_sph, 'MarkerEdgeColor', 'white', 'LineWidth', 1.2);
end
plot3(ax, 0, 0, 0, '+', 'MarkerSize', 9, 'Color', 'yellow', 'LineWidth', 1.6);
text(ax, 0, -2, -1.8, 'Marker 64 (Cero)', 'FontName', 'Arial', 'FontSize', 7.5, ...
    'FontWeight', 'bold', 'Color', c_texto_sec, 'HorizontalAlignment', 'center');

% 5. FLECHAS 3D DE COMANDOS DE VUELO
% Salen desde la superficie de la zona muerta hacia los límites activos:
len_h = 15;
% Adelante (+Pitch)
quiver3(ax, x_zm, 0, 0, len_h, 0, 0, 0, 'Color', c_flecha_h, 'LineWidth', 2.5, 'MaxHeadSize', 0.6);
text(ax, x_zm + len_h + 1.5, 0, 0, 'ADELANTE (+v_x)', 'FontName', 'Arial', ...
    'FontSize', 8.5, 'FontWeight', 'bold', 'Color', c_flecha_h, 'HorizontalAlignment', 'left');

% Atrás (-Pitch)
quiver3(ax, -x_zm, 0, 0, -len_h, 0, 0, 0, 'Color', c_flecha_h, 'LineWidth', 2.5, 'MaxHeadSize', 0.6);
text(ax, -x_zm - len_h - 1.5, 0, 0, 'ATRÁS (-v_x)', 'FontName', 'Arial', ...
    'FontSize', 8.5, 'FontWeight', 'bold', 'Color', c_flecha_h, 'HorizontalAlignment', 'right');

% Derecha (+Roll / +vy)
quiver3(ax, 0, y_zm, 0, 0, len_h, 0, 0, 'Color', c_flecha_h, 'LineWidth', 2.5, 'MaxHeadSize', 0.6);
text(ax, 0, y_zm + len_h + 1.5, 0, 'DERECHA (+v_y)', 'FontName', 'Arial', ...
    'FontSize', 8.5, 'FontWeight', 'bold', 'Color', c_flecha_h, 'HorizontalAlignment', 'left');

% Izquierda (-Roll / -vy)
quiver3(ax, 0, -y_zm, 0, 0, -len_h, 0, 0, 'Color', c_flecha_h, 'LineWidth', 2.5, 'MaxHeadSize', 0.6);
text(ax, 0, -y_zm - len_h - 1.5, 0, 'IZQUIERDA (-v_y)', 'FontName', 'Arial', ...
    'FontSize', 8.5, 'FontWeight', 'bold', 'Color', c_flecha_h, 'HorizontalAlignment', 'right');

% Ascenso (+Z)
quiver3(ax, 0, 0, z_zm, 0, 0, 9, 0, 'Color', c_flecha_z, 'LineWidth', 2.5, 'MaxHeadSize', 0.8);
text(ax, 0, 0, z_zm + 9.5, 'ASCENSO (+Z)', 'FontName', 'Arial', ...
    'FontSize', 8.5, 'FontWeight', 'bold', 'Color', c_flecha_z, 'HorizontalAlignment', 'center');

% Descenso suave (-Z)
quiver3(ax, 0, 0, -z_zm, 0, 0, -1.8, 0, 'Color', [0.9 0.6 0.2], 'LineWidth', 2.0, 'MaxHeadSize', 1.0);

% Rayos de proyección a vértices (estilo OptiTrack de la referencia)
lineas_ref = [
    x_sat  y_sat  z_max;
   -x_sat  y_sat  z_max;
   -x_sat -y_sat  z_max;
    x_sat -y_sat  z_max
];
for k = 1:size(lineas_ref, 1)
    plot3(ax, [0 lineas_ref(k,1)], [0 lineas_ref(k,2)], [0 lineas_ref(k,3)], ...
        ':', 'Color', [0.5 0.55 0.65], 'LineWidth', 0.8);
end

% Configuración de perspectiva y límites de ejes
xlim(ax, [-36 36]);
ylim(ax, [-36 36]);
zlim(ax, [-22 21]);

xlabel(ax, 'Inclinación Pitch (\theta) [grados]', 'FontName', 'Arial', ...
    'FontSize', 10, 'FontWeight', 'bold', 'Color', c_texto_tit, 'Interpreter', 'tex');
ylabel(ax, 'Inclinación Roll (\phi) [grados]', 'FontName', 'Arial', ...
    'FontSize', 10, 'FontWeight', 'bold', 'Color', c_texto_tit, 'Interpreter', 'tex');
zlabel(ax, 'Desplazamiento Vertical \Delta z [cm]', 'FontName', 'Arial', ...
    'FontSize', 10, 'FontWeight', 'bold', 'Color', c_texto_tit, 'Interpreter', 'tex');

% Perspectiva isométrica similar a la figura de Robotat
view(ax, -38, 26);

% =========================================================================
% LEYENDA TÉCNICA FLOTANTE (Idéntica a la esquina superior de la referencia)
% =========================================================================
annotation(f, 'rectangle', [0.73 0.70 0.23 0.17], ...
    'FaceColor', c_leyenda_bg, 'EdgeColor', c_leyenda_bd, 'LineWidth', 1.0);

% Elementos de la leyenda
y_leg = [0.84 0.805 0.77 0.735 0.70];
% 1. Alambre exterior
annotation(f, 'line', [0.74 0.76], [0.845 0.845], 'Color', c_wire_ext, 'LineWidth', 1.5);
annotation(f, 'textbox', [0.765 0.83 0.19 0.03], 'String', 'Envolvente de saturación (28°)', ...
    'EdgeColor', 'none', 'FontName', 'Arial', 'FontSize', 8, 'Color', c_texto_sec, 'Interpreter', 'none');

% 2. Prisma Zona Muerta
annotation(f, 'rectangle', [0.742 0.795 0.018 0.018], 'FaceColor', c_zm_face, ...
    'EdgeColor', c_zm_edge, 'LineWidth', 1.2);
annotation(f, 'textbox', [0.765 0.795 0.19 0.03], 'String', 'Zona Muerta / Hover (±12°, ±8 cm)', ...
    'EdgeColor', 'none', 'FontName', 'Arial', 'FontSize', 8, 'Color', c_texto_sec, 'Interpreter', 'none');

% 3. Sub-volumen Aterrizaje
annotation(f, 'rectangle', [0.742 0.760 0.018 0.018], 'FaceColor', c_land_face, ...
    'EdgeColor', c_land_edge, 'LineWidth', 1.2);
annotation(f, 'textbox', [0.765 0.760 0.19 0.03], 'String', 'Umbral de Aterrizaje (Δz ≤ -10 cm)', ...
    'EdgeColor', 'none', 'FontName', 'Arial', 'FontSize', 8, 'Color', c_texto_sec, 'Interpreter', 'none');

% 4. Marcadores
annotation(f, 'rectangle', [0.744 0.727 0.014 0.014], 'FaceColor', c_marker_sph, ...
    'EdgeColor', 'white', 'LineWidth', 0.8);
annotation(f, 'textbox', [0.765 0.725 0.19 0.03], 'String', 'Marcadores Rigid Body ID 64', ...
    'EdgeColor', 'none', 'FontName', 'Arial', 'FontSize', 8, 'Color', c_texto_sec, 'Interpreter', 'none');

% =========================================================================
% NOTA AL PIE (Estilo Tesis UVG)
% =========================================================================


% =========================================================================
% EXPORTACIÓN EN PDF VECTORIAL Y PNG
% =========================================================================
drawnow;
sufijo = '';
if ~es_oscuro, sufijo = '_claro'; end

base_res = fullfile(carpeta_salida, ['joystick_marker_espacio_3d' sufijo]);
base_tes = fullfile(carpeta_tesis,  ['joystick_marker_espacio_3d' sufijo]);

rutas.pdf = [base_res '.pdf'];
rutas.png = [base_res '.png'];
rutas.tesis_pdf = [base_tes '.pdf'];
rutas.tesis_png = [base_tes '.png'];

exportgraphics(f, rutas.pdf, 'ContentType', 'vector', 'BackgroundColor', c_fondo);
exportgraphics(f, rutas.png, 'Resolution', 300, 'BackgroundColor', c_fondo);

exportgraphics(f, rutas.tesis_pdf, 'ContentType', 'vector', 'BackgroundColor', c_fondo);
exportgraphics(f, rutas.tesis_png, 'Resolution', 300, 'BackgroundColor', c_fondo);

fprintf('\n[OK] Gráfica 3D generada exitosamente (tema: %s):\n', tema);
fprintf(' - PDF: %s\n', rutas.pdf);
fprintf(' - PNG: %s\n\n', rutas.png);
end

% =========================================================================
% FUNCIÓN AUXILIAR: DIBUJAR CAJA/PRISMA 3D
% =========================================================================
function dibujar_caja_3d(ax, x1, x2, y1, y2, z1, z2, c_face, a_face, c_edge, lw_edge, ls_edge)
V = [
    x1 y1 z1; % 1
    x2 y1 z1; % 2
    x2 y2 z1; % 3
    x1 y2 z1; % 4
    x1 y1 z2; % 5
    x2 y1 z2; % 6
    x2 y2 z2; % 7
    x1 y2 z2  % 8
];
F = [
    1 2 3 4; % base inferior
    5 6 7 8; % base superior
    1 2 6 5; % cara frontal
    2 3 7 6; % cara lateral derecha
    3 4 8 7; % cara posterior
    4 1 5 8  % cara lateral izquierda
];

if strcmpi(c_face, 'none')
    % Solo aristas (wireframe)
    aristas = [
        1 2; 2 3; 3 4; 4 1; ... % base inf
        5 6; 6 7; 7 8; 8 5; ... % base sup
        1 5; 2 6; 3 7; 4 8      % pilares
    ];
    for e = 1:size(aristas, 1)
        p1 = V(aristas(e,1), :);
        p2 = V(aristas(e,2), :);
        plot3(ax, [p1(1) p2(1)], [p1(2) p2(2)], [p1(3) p2(3)], ...
            'Color', c_edge, 'LineWidth', lw_edge, 'LineStyle', ls_edge);
    end
else
    patch(ax, 'Vertices', V, 'Faces', F, ...
        'FaceColor', c_face, 'FaceAlpha', a_face, ...
        'EdgeColor', c_edge, 'LineWidth', lw_edge, 'LineStyle', ls_edge);
end
end
