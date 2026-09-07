function rutas = esquema_gestos_mano(carpeta, excluir)
%ESQUEMA_GESTOS_MANO Lámina de los gestos de mano y del movimiento que ordenan al dron.
%
%   esquema_gestos_mano                 exporta PNG y PDF a results/graphs/gestos_mano/<hoy>/
%   esquema_gestos_mano(carpeta)        exporta a la carpeta indicada
%   esquema_gestos_mano(carpeta, excluir)
%       excluir: cellstr con las claves que NO se dibujan. Por defecto se
%       omiten STOP, SEGUIR_MARKER, DETENER_SEGUIMIENTO y REPOSO. Pasar {}
%       dibuja el vocabulario completo.
%
% Desde la raíz del repositorio:
%   addpath('external/gesture_detection/visualization');
%   esquema_gestos_mano;
%
% Cada celda muestra la postura de la mano (21 landmarks MediaPipe, en el
% orden 0:20 + 1) y, a su derecha, el dron visto desde arriba con la flecha
% del desplazamiento que produce el gesto.
%
% Las posturas siguen las reglas de hand_gesture_detector.py (qué dedos están
% extendidos y si la mano apunta arriba o abajo). El movimiento sigue la tabla
% gesto -> velocidad de control_camara_flowdeck_dron1.py. Las coordenadas de la
% mano son sintéticas: ilustran la regla, no son mediciones.
% No abre cámara, radio ni controladores. Sólo requiere MATLAB.

if nargin < 1 || isempty(carpeta)
    raiz = fileparts(fileparts(fileparts(fileparts(mfilename('fullpath')))));
    carpeta = fullfile(raiz, 'results', 'graphs', 'gestos_mano', ...
        char(datetime('today', 'Format', 'yyyy-MM-dd')));
end
if nargin < 2
    excluir = {'STOP', 'SEGUIR_MARKER', 'DETENER_SEGUIMIENTO', 'REPOSO'};
end
excluir = upper(cellstr(excluir));
if ~isfolder(carpeta), mkdir(carpeta); end

cat = catalogo();
claves = {cat.clave};
desconocidas = setdiff(excluir, claves);
if ~isempty(desconocidas)
    warning('esquema_gestos_mano:clave', ...
        'Claves desconocidas en excluir: %s. Válidas: %s', ...
        strjoin(desconocidas, ', '), strjoin(claves, ', '));
end
cat = cat(~ismember(claves, excluir));
n = numel(cat);
assert(n > 0, 'No queda ningún gesto por dibujar.');

% Paleta. Orden de dedos: pulgar, índice, medio, anular, meñique.
colores = [0.78 0.12 0.32; 0.49 0.31 0.70; 0.75 0.53 0.05; ...
    0.18 0.54 0.37; 0.12 0.44 0.73];
gris = [0.60 0.65 0.69];
tinta = [0.10 0.16 0.22];
acento = [0.85 0.33 0.10];

% Rejilla en pulgadas; la figura se dimensiona a partir de ella.
cols = min(4, n);
filas = ceil(n / cols);
cw = 3.55; ch = 3.45; sep = 0.2; margen = 0.3;
cabecera = 1.15; pie = 0.95;
W = 2*margen + cols*cw + (cols-1)*sep;
H = cabecera + filas*ch + (filas-1)*sep + pie;
nx = @(x) x / W;  ny = @(y) y / H;

f = figure('Visible','off','Color','white','Units','inches', ...
    'Position',[0 0 W H],'InvertHardcopy','off');
limpieza = onCleanup(@() close(f)); %#ok<NASGU>
annotation(f,'textbox',[0.05 ny(H-0.72) 0.90 ny(0.55)], ...
    'String','Gestos de mano y movimiento del dron','EdgeColor','none', ...
    'HorizontalAlignment','center','VerticalAlignment','middle', ...
    'FontName','Arial','FontSize',24,'FontWeight','bold','Color',tinta, ...
    'Interpreter','none');
annotation(f,'textbox',[0.05 ny(H-1.08) 0.90 ny(0.36)], ...
    'String','Postura detectada por MediaPipe Hands  ->  orden enviada al Crazyflie', ...
    'EdgeColor','none','HorizontalAlignment','center', ...
    'VerticalAlignment','middle','FontName','Arial','FontSize',12, ...
    'Color',[0.35 0.40 0.45],'Interpreter','none');

for k = 1:n
    col = mod(k-1, cols);
    fila = floor((k-1) / cols);
    x0 = margen + col*(cw+sep);
    y0 = H - cabecera - (fila+1)*ch - fila*sep;
    g = cat(k);

    annotation(f,'rectangle',[nx(x0) ny(y0) nx(cw) ny(ch)], ...
        'Color',[0.85 0.88 0.90],'LineWidth',0.7);
    annotation(f,'textbox',[nx(x0+0.1) ny(y0+ch-0.4) nx(0.5) ny(0.3)], ...
        'String',sprintf('%02d',k),'EdgeColor','none','FontName','Arial', ...
        'FontSize',9,'FontWeight','bold','Color',[0.45 0.50 0.55]);

    % Mano: ocupa la mitad izquierda de la celda.
    ax = axes(f,'Units','inches','Position',[x0+0.10 y0+1.05 cw-1.45 ch-1.2]);
    hold(ax,'on');
    P = postura(g.dedos);
    if g.espejo
        P(:,1) = -P(:,1);
    end
    if g.invertido
        % Giro de 180 grados del conjunto, no cambio individual de dedos.
        P = -P + [0 3.25];
    end
    assert(isequal(size(P),[21 2]) && all(isfinite(P),'all'));
    dibujar_mano(ax,P,colores,gris);
    axis(ax,'equal'); xlim(ax,[-1.8 1.8]); ylim(ax,[-0.2 3.5]);
    axis(ax,'off');

    % Dron: esquina superior derecha de la celda.
    axd = axes(f,'Units','inches','Position',[x0+cw-1.30 y0+ch-1.45 1.2 1.2]);
    dibujar_dron(axd, g.mov, tinta, acento, gris);

    annotation(f,'textbox',[nx(x0+0.05) ny(y0+0.66) nx(cw-0.1) ny(0.36)], ...
        'String',g.nombre,'EdgeColor','none', ...
        'HorizontalAlignment','center','VerticalAlignment','middle', ...
        'FontName','Arial','FontSize',13,'FontWeight','bold','Color',tinta, ...
        'Interpreter','none');
    annotation(f,'textbox',[nx(x0+0.05) ny(y0+0.30) nx(cw-0.1) ny(0.36)], ...
        'String',strjoin(g.gesto, ', '),'EdgeColor','none', ...
        'HorizontalAlignment','center','VerticalAlignment','middle', ...
        'FontName','Arial','FontSize',10,'Color',[0.30 0.35 0.39], ...
        'Interpreter','none');
    annotation(f,'textbox',[nx(x0+0.05) ny(y0+0.04) nx(cw-0.1) ny(0.30)], ...
        'String',['Dron: ' g.accion],'EdgeColor','none', ...
        'HorizontalAlignment','center','VerticalAlignment','middle', ...
        'FontName','Arial','FontSize',10,'FontWeight','bold', ...
        'Color',acento*0.85,'Interpreter','tex');
end

% Pie: leyenda de dedos y clave del icono del dron.
leyenda = axes(f,'Units','inches','Position',[W/2-3.0 0.50 6.0 0.32]);
hold(leyenda,'on'); axis(leyenda,[0 5 0 1]); axis(leyenda,'off');
dedos = {'Pulgar','Índice','Medio','Anular','Meñique'};
for j = 1:5
    plot(leyenda,[j-0.95 j-0.75],[0.5 0.5],'-o','Color',colores(j,:), ...
        'LineWidth',1.8,'MarkerFaceColor','white','MarkerSize',4);
    text(leyenda,j-0.67,0.5,dedos{j},'FontName','Arial','FontSize',10, ...
        'Color',tinta,'VerticalAlignment','middle','Interpreter','none');
end


% Evitar sobrescribir exportaciones previas al volver a ejecutar.
base = fullfile(carpeta,'esquema_gestos_mano');
if isfile([base '.png']) || isfile([base '.pdf'])
    base = [base '_' char(datetime('now','Format','HHmmssSSS'))];
end
drawnow;
rutas.png = [base '.png'];
rutas.pdf = [base '.pdf'];
exportgraphics(f,rutas.png,'Resolution',300,'BackgroundColor','white');
exportgraphics(f,rutas.pdf,'ContentType','vector','BackgroundColor','white');
fprintf('PNG: %s\nPDF: %s\n',rutas.png,rutas.pdf);
end

function c = catalogo()
% Vocabulario completo de hand_gesture_detector.py, en el orden de la lámina.
%   dedos     [pulgar índice medio anular meñique], 1 = extendido
%   invertido mano apuntando hacia abajo (orientation == "down")
%   espejo    reflejar la mano para que el pulgar señale a la derecha
%   mov       clave del icono del dron (ver dibujar_dron)
d = @(clave,nombre,dedos,invertido,espejo,gesto,accion,mov) struct( ...
    'clave',clave,'nombre',nombre,'dedos',logical(dedos), ...
    'invertido',invertido,'espejo',espejo,'gesto',{gesto}, ...
    'accion',accion,'mov',mov);
c = [ ...
    d('DESPEGAR','DESPEGAR',[0 1 1 0 0],false,false, ...
        {'Índice y medio','mano hacia arriba'},'despega (sostener 1 s)','despegue')
    d('ATERRIZAR','ATERRIZAR',[0 1 1 0 0],true,false, ...
        {'Índice y medio','mano hacia abajo'},'aterriza (sostener 1 s)','aterrizaje')
    d('ARRIBA','ARRIBA',[0 1 0 0 0],false,false, ...
        {'Solo índice','mano hacia arriba'},'sube  (v_z > 0)','arriba')
    d('ABAJO','ABAJO',[0 1 0 0 0],true,false, ...
        {'Solo índice','mano hacia abajo'},'baja  (v_z < 0)','abajo')
    d('ADELANTE','ADELANTE',[1 1 0 0 0],false,false, ...
        {'Pulgar e índice','en «L»'},'avanza  (v_x > 0)','adelante')
    d('ATRAS','ATRÁS',[1 0 0 0 1],false,false, ...
        {'Pulgar y meñique','«shaka»'},'retrocede  (v_x < 0)','atras')
    d('IZQUIERDA','IZQUIERDA',[0 0 0 0 1],false,false, ...
        {'Solo meñique','mano hacia arriba'},'a la izquierda  (v_y > 0)','izquierda')
    d('DERECHA','DERECHA',[1 0 0 0 0],false,true, ...
        {'Solo pulgar','señalando a la derecha'},'a la derecha  (v_y < 0)','derecha')
    d('STOP','STOP',[0 0 0 0 0],false,false, ...
        {'Puño cerrado'},'se detiene (hover)','hover')
    d('SEGUIR_MARKER','SEGUIR MARKER',[0 0 1 0 0],false,false, ...
        {'Solo dedo medio'},'sigue al marker 65 a 0.45 m','seguir')
    d('DETENER_SEGUIMIENTO','DETENER SEGUIMIENTO',[0 1 0 0 1],false,false, ...
        {'Índice y meñique','«rock»'},'deja de seguir (hover)','hover')
    d('REPOSO','REPOSO',[1 1 1 1 1],false,false, ...
        {'Mano abierta'},'sin orden','ninguno')
    ];
end

function P = postura(abiertos)
% Vista palmar de mano derecha: pulgar a la izquierda de la figura.
% Posturas 2D deliberadamente idealizadas. Los dedos cerrados se representan
% mediante cadenas que se repliegan sobre la palma. No es un modelo biomecánico.
P = zeros(21,2);
P(1,:) = [0 0];
if abiertos(1)
    P(2:5,:) = [-0.43 0.36; -0.82 0.68; -1.16 0.87; -1.50 1.02];
else
    P(2:5,:) = [-0.43 0.36; -0.69 0.67; -0.38 0.91; 0.02 0.98];
end
bases = [-0.59 1.42; -0.14 1.59; 0.33 1.48; 0.74 1.25];
largos = [1.46 1.66 1.49 1.19];
apertura = [-0.13 0.00 0.16 0.38];
for d = 1:4
    b = bases(d,:);
    idx = 6+(d-1)*4;
    if abiertos(d+1)
        fraccion = [0;0.45;0.75;1];
        puntos = b+fraccion*[apertura(d) largos(d)];
    else
        % Proyección de articulaciones flexionadas; cada punto es distinto.
        puntos = b+[0 0; -0.045 0.31; 0.14 0.19; 0.11 -0.30];
    end
    P(idx:idx+3,:) = puntos;
end
end

function dibujar_mano(ax,P,colores,gris)
% Topología HAND_CONNECTIONS de MediaPipe, convertida a índices MATLAB.
palma = [1 6;6 10;10 14;14 18;18 1];
for e = 1:size(palma,1)
    idx = palma(e,:);
    plot(ax,P(idx,1),P(idx,2),'-','Color',gris,'LineWidth',1.35);
end
cadenas = {1:5,6:9,10:13,14:17,18:21};
for d = 1:5
    idx = cadenas{d};
    plot(ax,P(idx,1),P(idx,2),'-','Color',colores(d,:),'LineWidth',2.2);
end
% Los nodos se dibujan al final para quedar visibles sobre las conexiones.
for d = 1:5
    idx = cadenas{d};
    if d == 1, idx = idx(2:end); end
    plot(ax,P(idx,1),P(idx,2),'o','LineStyle','none', ...
        'MarkerSize',5.1,'MarkerEdgeColor',colores(d,:), ...
        'MarkerFaceColor','white','LineWidth',1.35);
end
plot(ax,P(1,1),P(1,2),'o','MarkerSize',5.6, ...
    'MarkerFaceColor','white','MarkerEdgeColor',gris,'LineWidth',1.5);
end

function dibujar_dron(ax, mov, tinta, acento, gris)
% Dron visto desde arriba y flecha del desplazamiento que ordena el gesto.
% Ejes del icono: horizontal = izquierda/derecha, vertical = arriba/abajo,
% diagonal = adelante/atrás (profundidad).
hold(ax,'on'); axis(ax,'equal'); axis(ax,[-1.7 1.7 -1.7 1.7]); axis(ax,'off');
centro = [0 0];
prof = [0.78 0.62];  % dirección "adelante" en el plano del icono
switch mov
    case 'despegue'
        centro = [0 -0.55]; suelo(ax,-1.0,gris);
        flecha(ax,centro+[0 0.45],centro+[0 1.55],acento);
    case 'aterrizaje'
        centro = [0 0.65]; suelo(ax,-1.0,gris);
        flecha(ax,centro+[0 -0.45],centro+[0 -1.45],acento);
    case 'arriba',    flecha(ax,[0 0.45],[0 1.55],acento);
    case 'abajo',     flecha(ax,[0 -0.45],[0 -1.55],acento);
    case 'derecha',   flecha(ax,[0.85 0],[1.65 0],acento);
    case 'izquierda', flecha(ax,[-0.85 0],[-1.65 0],acento);
    case 'adelante',  flecha(ax,0.75*prof,1.9*prof,acento);
    case 'atras',     flecha(ax,-0.75*prof,-1.9*prof,acento);
    case 'hover'
        t = linspace(0,2*pi,80);
        plot(ax,1.2*cos(t),1.2*sin(t),'--','Color',acento,'LineWidth',1.4);
    case 'seguir'
        marca = [1.25 0.55];
        plot(ax,[0.45 marca(1)-0.2],[0.2 marca(2)-0.1],'--','Color',acento,'LineWidth',1.2);
        plot(ax,marca(1),marca(2),'d','MarkerSize',7,'MarkerFaceColor',acento, ...
            'MarkerEdgeColor',acento);
    otherwise
        % 'ninguno': sólo el dron.
end
glifo_dron(ax,centro,tinta);
end

function suelo(ax,y,gris)
plot(ax,[-1.4 1.4],[y y],'-','Color',gris,'LineWidth',1.4);
for x = -1.2:0.4:1.2
    plot(ax,[x x-0.18],[y y-0.18],'-','Color',gris,'LineWidth',0.9);
end
end

function glifo_dron(ax,c,tinta)
% Cuadricóptero en vista cenital ligeramente aplanada.
brazos = [0.55 0.30; -0.55 0.30; -0.55 -0.30; 0.55 -0.30];
t = linspace(0,2*pi,40);
for k = 1:4
    plot(ax,c(1)+[0 brazos(k,1)],c(2)+[0 brazos(k,2)],'-','Color',tinta,'LineWidth',2);
end
for k = 1:4
    patch(ax,c(1)+brazos(k,1)+0.21*cos(t),c(2)+brazos(k,2)+0.12*sin(t), ...
        [1 1 1],'EdgeColor',tinta,'LineWidth',1.2);
end
patch(ax,c(1)+0.18*cos(t),c(2)+0.11*sin(t),tinta,'EdgeColor','none');
end

function flecha(ax,p1,p2,color)
% Flecha rellena de p1 a p2, en unidades del icono.
d = p2-p1; L = norm(d); u = d/L; nrm = [-u(2) u(1)];
hl = min(0.34,0.45*L); hw = 0.20; sw = 0.07;
b = p2-hl*u;
poly = [p1+sw*nrm; b+sw*nrm; b+hw*nrm; p2; b-hw*nrm; b-sw*nrm; p1-sw*nrm];
patch(ax,poly(:,1),poly(:,2),color,'EdgeColor','none');
end
