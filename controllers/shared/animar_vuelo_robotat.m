function salida = animar_vuelo_robotat(archivo, varargin)
%ANIMAR_VUELO_ROBOTAT Video 3D de un vuelo del Robotat exportado con exportar_vuelo_matlab.py.
%
%   animar_vuelo_robotat('results/data/dron_robotat/<dia>/vuelo_<HHMMSS>.mat')
%   animar_vuelo_robotat(archivo, 'Desde', 30, 'Hasta', 90, 'Vista', 'arriba')
%
%   Dibuja cada dron (posicion del mocap, con su orientacion y su estela), el
%   punto al que se le manda ir, el marker 65 del operador, su esqueleto 3D
%   (si se reconstruyo con reconstruir_cuerpo.py) y, si el vuelo fue
%   por gestos, el gesto, el modo, lo que esta haciendo el dron (SEGUIR,
%   ORBITAR...) y la ultima orden. Exporta un MP4 junto al .mat.
%
%   Opciones (nombre, valor):
%     'Salida'     ruta del MP4 (por defecto, la del .mat con .mp4)
%     'Desde'      segundo donde empezar (0)
%     'Hasta'      segundo donde acabar (el final)
%     'Velocidad'  1 = tiempo real, 2 = el doble de rapido (1)
%     'Vista'      '3d' o 'arriba' ('3d')
%     'Estela'     segundos de estela detras de cada dron (4)
%     'SoloVuelo'  true: recorta al tramo en que algun dron esta en el aire (true)
%     'Mostrar'    false: no muestra la ventana, solo escribe el video (true)

p = inputParser;
addParameter(p, 'Salida', '');
addParameter(p, 'Desde', 0);
addParameter(p, 'Hasta', inf);
addParameter(p, 'Velocidad', 1);
addParameter(p, 'Vista', '3d');
addParameter(p, 'Estela', 4);
addParameter(p, 'SoloVuelo', true);
addParameter(p, 'Mostrar', true);
parse(p, varargin{:});
o = p.Results;

S = load(archivo);
r = S.vuelo.rejilla;
fps = double(S.vuelo.fps);
t = double(r.t(:));
nombres = cellstr(r.nombres);
K = numel(nombres);
pos = reshape(double(r.pos), numel(t), 3, K);
objetivo = reshape(double(r.objetivo), numel(t), 3, K);
yaw = reshape(double(r.yaw_deg), numel(t), K);
marker = reshape(double(r.marker), numel(t), 3);
gesto = celda(r.gesto, numel(t));
modo = celda(r.modo, numel(t));
comportamiento = celda(r.comportamiento, numel(t));
orden = celda(r.orden, numel(t));
evento = celda(r.evento, numel(t));
modo_dron = reshape(celda(r.modo_dron, numel(t) * K), numel(t), K);
% Esqueleto 3D del operador (reconstruir_cuerpo.py), si se exporto.
hay_cuerpo = isfield(r, 'cuerpo');
if hay_cuerpo
    cuerpo = reshape(double(r.cuerpo), numel(t), 33, 3);
    huesos = double(r.cuerpo_conexiones);
    huesos = huesos(all(huesos >= 12, 2), :);       % sin la cara: indices 1-11
end

% Tramo a dibujar.
i0 = find(t >= o.Desde, 1);
i1 = find(t <= o.Hasta, 1, 'last');
if o.SoloVuelo && isinf(o.Hasta) && o.Desde == 0
    alto = squeeze(pos(:, 3, :)) > 0.08;
    en_aire = any(reshape(alto, numel(t), K), 2);
    if any(en_aire)
        margen = round(3 * fps);
        i0 = max(1, find(en_aire, 1) - margen);
        i1 = min(numel(t), find(en_aire, 1, 'last') + margen);
    end
end
paso = max(1, round(o.Velocidad));
indices = i0:paso:i1;

% Limites: todo lo que se mueve, con margen; el suelo siempre en z = 0.
todo = [reshape(permute(pos, [1 3 2]), [], 3); marker];
todo = todo(all(isfinite(todo), 2), :);
if isempty(todo), todo = [-1 -1 0; 1 1 1]; end
lim = [min(todo(:, 1)) - 0.5, max(todo(:, 1)) + 0.5, ...
       min(todo(:, 2)) - 0.5, max(todo(:, 2)) + 0.5, ...
       0, max(1.2, max(todo(:, 3)) + 0.4)];

colores = [0.00 0.45 0.74; 0.85 0.33 0.10; 0.47 0.67 0.19; 0.49 0.18 0.56];
visible = 'on';
if ~o.Mostrar, visible = 'off'; end
fig = figure('Color', 'w', 'Position', [100 100 1280 720], 'Visible', visible);
try
    theme(fig, 'light');    % con el tema oscuro de MATLAB las paredes salen negras
catch
end
ax = axes(fig, 'Position', [0.05 0.08 0.68 0.84], 'Color', 'w');
hold(ax, 'on'); grid(ax, 'on'); axis(ax, 'equal'); axis(ax, lim);
xlabel(ax, 'x (m)'); ylabel(ax, 'y (m)'); zlabel(ax, 'z (m)');
patch(ax, lim([1 2 2 1]), lim([3 3 4 4]), [0 0 0 0], [0.93 0.93 0.93], 'EdgeColor', 'none');
plot3(ax, [0 0.3], [0 0], [0 0], 'r-', 'LineWidth', 2);
plot3(ax, [0 0], [0 0.3], [0 0], 'g-', 'LineWidth', 2);
if strcmpi(o.Vista, 'arriba'), view(ax, 0, 90); else, view(ax, -35, 25); end

% Objetos que se actualizan en cada cuadro.
for k = 1:K
    c = colores(mod(k - 1, size(colores, 1)) + 1, :);
    h(k).estela = plot3(ax, nan, nan, nan, '-', 'Color', [c 0.5], 'LineWidth', 1.5); %#ok<AGROW>
    h(k).sombra = plot3(ax, nan, nan, nan, ':', 'Color', c);
    h(k).brazos = plot3(ax, nan, nan, nan, '-', 'Color', c, 'LineWidth', 3);
    h(k).cuerpo = plot3(ax, nan, nan, nan, 'o', 'MarkerSize', 9, 'MarkerFaceColor', c, 'MarkerEdgeColor', 'k');
    h(k).objetivo = plot3(ax, nan, nan, nan, 'x', 'Color', c, 'MarkerSize', 10, 'LineWidth', 1.5);
    h(k).nombre = text(ax, nan, nan, nan, nombres{k}, 'Color', c, 'FontWeight', 'bold', ...
                       'HorizontalAlignment', 'center', 'VerticalAlignment', 'bottom');
end
hm.cuerpo = plot3(ax, nan, nan, nan, 'p', 'MarkerSize', 16, 'MarkerFaceColor', [0.9 0.1 0.1], ...
                  'MarkerEdgeColor', 'k');
hm.sombra = plot3(ax, nan, nan, nan, ':', 'Color', [0.9 0.1 0.1]);
hc.huesos = plot3(ax, nan, nan, nan, '-', 'Color', [0.35 0.35 0.35], 'LineWidth', 3);
hc.cabeza = plot3(ax, nan, nan, nan, 'o', 'MarkerSize', 14, 'Color', [0.35 0.35 0.35], 'LineWidth', 2);
hc.articulaciones = plot3(ax, nan, nan, nan, '.', 'MarkerSize', 14, 'Color', [0.2 0.6 0.25]);
hm.nombre = text(ax, nan, nan, nan, 'marker 65', 'Color', [0.8 0.1 0.1], 'FontWeight', 'bold', ...
                 'HorizontalAlignment', 'center', 'VerticalAlignment', 'bottom');

% Panel de texto a la derecha.
panel = axes(fig, 'Position', [0.75 0.08 0.23 0.84], 'Visible', 'off');
xlim(panel, [0 1]); ylim(panel, [0 1]);
txt.tiempo = text(panel, 0, 0.97, '', 'FontSize', 14, 'FontWeight', 'bold');
text(panel, 0, 0.88, 'GESTO', 'FontSize', 10, 'Color', [0.5 0.5 0.5]);
txt.gesto = text(panel, 0, 0.82, '', 'FontSize', 20, 'FontWeight', 'bold');
text(panel, 0, 0.73, 'MODO', 'FontSize', 10, 'Color', [0.5 0.5 0.5]);
txt.modo = text(panel, 0, 0.68, '', 'FontSize', 13);
text(panel, 0, 0.61, 'HACIENDO', 'FontSize', 10, 'Color', [0.5 0.5 0.5]);
txt.comportamiento = text(panel, 0, 0.56, '', 'FontSize', 13, 'FontWeight', 'bold');
text(panel, 0, 0.48, 'ORDEN', 'FontSize', 10, 'Color', [0.5 0.5 0.5]);
txt.orden = text(panel, 0, 0.43, '', 'FontSize', 11, 'Color', [0.1 0.55 0.1], 'Interpreter', 'none');
text(panel, 0, 0.35, 'DRONES', 'FontSize', 10, 'Color', [0.5 0.5 0.5]);
for k = 1:K
    c = colores(mod(k - 1, size(colores, 1)) + 1, :);
    txt.dron(k) = text(panel, 0, 0.30 - 0.05 * (k - 1), '', 'FontSize', 11, 'Color', c, ...
                       'Interpreter', 'none');
end
txt.evento = text(panel, 0, 0.05, '', 'FontSize', 10, 'Color', [0.4 0.4 0.4], 'Interpreter', 'none');

if isempty(o.Salida)
    [carpeta, base] = fileparts(archivo);
    o.Salida = fullfile(carpeta, [base '.mp4']);
end
video = VideoWriter(o.Salida, 'MPEG-4');
video.FrameRate = fps;
video.Quality = 95;
open(video);
limpio = onCleanup(@() close(video));

estela_n = round(o.Estela * fps);
brazo = 0.09;
for i = indices
    for k = 1:K
        q = pos(i, :, k);
        a = max(i0, i - estela_n);
        set(h(k).estela, 'XData', pos(a:i, 1, k), 'YData', pos(a:i, 2, k), 'ZData', pos(a:i, 3, k));
        if all(isfinite(q))
            psi = deg2rad(yaw(i, k));
            if ~isfinite(psi), psi = 0; end
            % Una X con un brazo mas largo hacia la nariz: se ve hacia donde mira.
            d1 = brazo * [cos(psi + pi/4) sin(psi + pi/4)];
            d2 = brazo * [cos(psi - pi/4) sin(psi - pi/4)];
            nariz = 1.8 * brazo * [cos(psi) sin(psi)];
            bx = [q(1)-d1(1) q(1)+d1(1) nan q(1)-d2(1) q(1)+d2(1) nan q(1) q(1)+nariz(1)];
            by = [q(2)-d1(2) q(2)+d1(2) nan q(2)-d2(2) q(2)+d2(2) nan q(2) q(2)+nariz(2)];
            set(h(k).brazos, 'XData', bx, 'YData', by, 'ZData', q(3) * ones(1, 8));
            set(h(k).cuerpo, 'XData', q(1), 'YData', q(2), 'ZData', q(3));
            set(h(k).sombra, 'XData', [q(1) q(1)], 'YData', [q(2) q(2)], 'ZData', [0 q(3)]);
            set(h(k).nombre, 'Position', q + [0 0 0.08]);
        else
            set([h(k).brazos h(k).cuerpo h(k).sombra], 'XData', nan, 'YData', nan, 'ZData', nan);
            set(h(k).nombre, 'Position', [nan nan nan]);
        end
        g = objetivo(i, :, k);
        set(h(k).objetivo, 'XData', g(1), 'YData', g(2), 'ZData', g(3));
        set(txt.dron(k), 'String', sprintf('%s  %s  z=%.2f m', nombres{k}, modo_dron{i, k}, q(3)));
    end
    if hay_cuerpo
        c = squeeze(cuerpo(i, :, :));
        if all(isfinite(c(12, :)))
            n = size(huesos, 1);
            X = [c(huesos(:, 1), 1) c(huesos(:, 2), 1) nan(n, 1)]';
            Y = [c(huesos(:, 1), 2) c(huesos(:, 2), 2) nan(n, 1)]';
            Z = [c(huesos(:, 1), 3) c(huesos(:, 2), 3) nan(n, 1)]';
            set(hc.huesos, 'XData', X(:), 'YData', Y(:), 'ZData', Z(:));
            set(hc.articulaciones, 'XData', c(12:33, 1), 'YData', c(12:33, 2), 'ZData', c(12:33, 3));
            set(hc.cabeza, 'XData', c(1, 1), 'YData', c(1, 2), 'ZData', c(1, 3) + 0.08);
        else
            set([hc.huesos hc.articulaciones hc.cabeza], 'XData', nan, 'YData', nan, 'ZData', nan);
        end
    end
    m = marker(i, :);
    if all(isfinite(m))
        set(hm.cuerpo, 'XData', m(1), 'YData', m(2), 'ZData', m(3));
        set(hm.sombra, 'XData', [m(1) m(1)], 'YData', [m(2) m(2)], 'ZData', [0 m(3)]);
        set(hm.nombre, 'Position', m + [0 0 0.1]);
    else
        set([hm.cuerpo hm.sombra], 'XData', nan, 'YData', nan, 'ZData', nan);
        set(hm.nombre, 'Position', [nan nan nan]);
    end

    set(txt.tiempo, 'String', sprintf('t = %.1f s', t(i)));
    g = gesto{i};
    if isempty(g) || strcmp(g, 'NO_GESTURE'), g = '-'; end
    color = [0.1 0.55 0.1];
    if endsWith(g, '?'), color = [0.85 0.55 0]; g = g(1:end-1); end
    set(txt.gesto, 'String', g, 'Color', color);
    set(txt.modo, 'String', vacio(upper(modo{i})));
    set(txt.comportamiento, 'String', vacio(comportamiento{i}));
    set(txt.orden, 'String', vacio(orden{i}));
    set(txt.evento, 'String', evento{i});

    drawnow limitrate;
    % getframe puede devolver un pixel de mas o de menos de un cuadro a otro;
    % VideoWriter exige el mismo tamano siempre: se ajusta al del primero.
    im = frame2im(getframe(fig));
    if ~exist('tamano', 'var'), tamano = size(im); end
    im = ajustar(im, tamano);
    writeVideo(video, im);
end
clear limpio
salida = o.Salida;
fprintf('Video: %s (%.1f s)\n', salida, numel(indices) / fps);
end


function c = celda(x, n)
%CELDA Texto exportado por scipy (cell, char o vacio) como cell de n elementos.
if iscell(x)
    c = cellfun(@(s) char(strtrim(string(s))), x(:), 'UniformOutput', false);
elseif ischar(x)
    c = cellstr(x);
else
    c = repmat({''}, n, 1);
end
if numel(c) ~= n
    c = repmat({''}, n, 1);
end
end


function s = vacio(s)
if isempty(s), s = '-'; end
end


function im = ajustar(im, tamano)
%AJUSTAR Recorta o rellena (en blanco) `im` hasta `tamano` sin reescalar.
alto = min(size(im, 1), tamano(1));
ancho = min(size(im, 2), tamano(2));
lienzo = 255 * ones(tamano, 'uint8');
lienzo(1:alto, 1:ancho, :) = im(1:alto, 1:ancho, :);
im = lienzo;
end
