function rutas = area_trabajo_robotat(carpeta_salida)
%AREA_TRABAJO_ROBOTAT Volumen del Robotat, área segura de trabajo y cámaras OptiTrack.
%
%   area_trabajo_robotat() rehace la figura del área de operación del
%   documento. La versión anterior no tenía fuente en el repositorio y decía
%   dos cosas distintas: el título ponía 3 x 3 x 1.5 m y la caja azul, con su
%   rótulo, medía 2 x 2 x 1.5 m. Aquí las dos salen de las mismas variables.
%
%   Robotat: 4 x 5 x 2 m. Área de trabajo: 3 x 3 x 1.5 m, centrada en planta y
%   apoyada en el suelo. Las seis cámaras van en los dos lados largos, a
%   2.25 m, como en la figura original; sus posiciones son esquemáticas, no
%   las de la calibración del OptiTrack.
%
%   Salida: PDF vectorial y PNG a 300 ppp en
%   results/graphs/area_trabajo_robotat/<hoy>/.

if nargin < 1 || isempty(carpeta_salida)
    raiz = fileparts(fileparts(fileparts(mfilename('fullpath'))));
    hoy = char(datetime('today', 'Format', 'yyyy-MM-dd'));
    carpeta_salida = fullfile(raiz, 'results', 'graphs', 'area_trabajo_robotat', hoy);
end
if ~isfolder(carpeta_salida), mkdir(carpeta_salida); end

% --- Dimensiones [m] ---------------------------------------------------
robotat = [4 5 2];            % X, Y, Z
area    = [3 3 1.5];
x0 = (robotat(1) - area(1)) / 2;
y0 = (robotat(2) - area(2)) / 2;
% El suelo del área va 1 cm por encima del del Robotat: si coinciden, las dos
% caras transparentes se pelean al rasterizar y sale un dentado.
lim_area = [x0, x0 + area(1), y0, y0 + area(2), 0.01, area(3)];

camaras = [
    0 0.4 2.25;
    0 2.5 2.25;
    0 4.6 2.25;
    4 0.4 2.25;
    4 2.5 2.25;
    4 4.6 2.25
];
% Las cámaras miran al centro del área de trabajo.
objetivo = [mean(lim_area(1:2)), mean(lim_area(3:4)), area(3) / 2];

% --- Estilo ------------------------------------------------------------
fs_ejes = 13; fs_ticks = 11.5; fs_etq = 11.5; fs_ley = 11;
c_robotat_face = [0.93 0.93 0.93];
c_robotat_edge = [0.55 0.55 0.55];
c_area_face    = [0.36 0.58 0.88];
c_area_edge    = [0.10 0.42 0.85];
c_camara       = [0.90 0.25 0.22];
c_rayos        = lines(size(camaras, 1));

f = figure('Visible', 'off', 'Color', 'w', 'Units', 'inches', ...
    'Position', [0 0 8.0 5.6], 'PaperPositionMode', 'auto');
% R2025a en adelante abre con el tema del escritorio; el documento es claro.
if isprop(f, 'Theme'), f.Theme = 'light'; end
limpieza = onCleanup(@() close(f));
ax = axes(f, 'Units', 'normalized', 'Position', [0.10 0.08 0.80 0.84]);
hold(ax, 'on'); grid(ax, 'on'); box(ax, 'on');
set(ax, 'FontName', 'Arial', 'FontSize', fs_ticks, 'GridAlpha', 0.12);

h_robotat = caja(ax, [0 robotat(1) 0 robotat(2) 0 robotat(3)], ...
    c_robotat_face, 0.25, c_robotat_edge, 1.6);
h_area = caja(ax, lim_area, c_area_face, 0.40, c_area_edge, 1.6);

for k = 1:size(camaras, 1)
    plot3(ax, [camaras(k,1) objetivo(1)], [camaras(k,2) objetivo(2)], ...
        [camaras(k,3) objetivo(3)], '-', 'Color', c_rayos(k,:), 'LineWidth', 1.0);
end
h_cam = plot3(ax, camaras(:,1), camaras(:,2), camaras(:,3), 's', ...
    'MarkerSize', 8, 'MarkerFaceColor', c_camara, 'MarkerEdgeColor', [0.3 0.1 0.1]);
for k = 1:size(camaras, 1)
    text(ax, camaras(k,1), camaras(k,2), camaras(k,3) + 0.16, sprintf('Cam %d', k), ...
        'FontName', 'Arial', 'FontSize', fs_etq, 'HorizontalAlignment', 'center');
end

% En la cara frontal del área: encima de la caja chocaba con las cámaras.
text(ax, lim_area(2), objetivo(2), area(3) * 0.72, ...
    {'Área de trabajo', medidas(area)}, 'FontName', 'Arial', ...
    'FontSize', fs_etq, 'FontWeight', 'bold', 'HorizontalAlignment', 'center');
text(ax, robotat(1) * 0.55, robotat(2) * 0.95, robotat(3) + 0.10, ...
    sprintf('Robotat %s', medidas(robotat)), 'FontName', 'Arial', ...
    'FontSize', fs_etq, 'HorizontalAlignment', 'center');

xlabel(ax, 'X [m]', 'FontSize', fs_ejes);
ylabel(ax, 'Y [m]', 'FontSize', fs_ejes);
zlabel(ax, 'Z [m]', 'FontSize', fs_ejes);
axis(ax, 'equal');
xlim(ax, [-0.2 robotat(1) + 0.2]); ylim(ax, [-0.2 robotat(2) + 0.2]);
zlim(ax, [0 2.5]);
% La misma orientación que la figura original: X hacia el observador.
view(ax, 52.5, 26);

% Sin título: lo pone el pie de figura del documento.
legend(ax, [h_robotat h_area h_cam], ...
    {'Volumen total del Robotat', 'Área segura de trabajo', 'Cámaras OptiTrack'}, ...
    'Location', 'northeast', 'FontName', 'Arial', 'FontSize', fs_ley);

drawnow;
base = fullfile(carpeta_salida, 'area_trabajo_robotat');
rutas.pdf = [base '.pdf'];
rutas.png = [base '.png'];
exportgraphics(f, rutas.pdf, 'ContentType', 'vector', 'BackgroundColor', 'white');
exportgraphics(f, rutas.png, 'Resolution', 300, 'BackgroundColor', 'white');
fprintf('PDF: %s\nPNG: %s\n', rutas.pdf, rutas.png);
end

function s = medidas(v)
s = sprintf('%g × %g × %g m', v(1), v(2), v(3));
end

function h = caja(ax, L, c_face, a_face, c_edge, lw)
[x1, x2, y1, y2, z1, z2] = deal(L(1), L(2), L(3), L(4), L(5), L(6));
V = [x1 y1 z1; x2 y1 z1; x2 y2 z1; x1 y2 z1; x1 y1 z2; x2 y1 z2; x2 y2 z2; x1 y2 z2];
F = [1 2 3 4; 5 6 7 8; 1 2 6 5; 2 3 7 6; 3 4 8 7; 4 1 5 8];
h = patch(ax, 'Vertices', V, 'Faces', F, 'FaceColor', c_face, 'FaceAlpha', a_face, ...
    'EdgeColor', c_edge, 'LineWidth', lw);
end
