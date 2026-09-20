%% Simulacion plana de backflip para Crazyflie 2.1 Brushless
% Modelo de cuerpo rigido y motor identificado por Graefe et al. (2026).
% Control hibrido: impulso vertical, giro con realimentacion de velocidad
% angular, frenado y recuperacion. No envia ordenes a hardware.
clear; close all; clc;

p.m = 0.044;                 % kg, con protectores
p.J = 3.6e-5;                % kg m^2, eje de pitch
p.arm = 0.0707/2;            % m, semiancho efectivo
p.motorT = 0.050;            % s
p.motorK = 2900;             % rad/s
p.g = 9.81;
p.sigma = 2900;
p.dt = 5e-4;
p.tf = 2.5;
p.z0 = 2.5;                  % m, margen para evaluar la maniobra sin contacto
p.omegaTarget = 1000*pi/180; % rad/s, valor reportado en backflip doble
p.kRate = 2.5e-4;            % N m por (rad/s)
p.kAngle = 3.0e-3;           % N m por rad
p.maxTorque = 0.0105;        % N m, limitado por los motores

nominal = run_case(p, ones(1,5), true);

% Robustez: rangos recomendados por el paper (+-10% masa, +-20% resto).
rng(260305944);
N = 300;
mc = zeros(N,7);
for k = 1:N
    scale = [1+0.20*(rand-0.5), 1+0.40*(rand-0.5), ...
             1+0.40*(rand-0.5), 1+0.40*(rand-0.5), 1+0.40*(rand-0.5)];
    s = run_case(p, scale, false);
    mc(k,:) = [s.success, s.rotations, s.minZ, s.maxZ, s.finalZ, ...
               s.finalAngleErrorDeg, s.maxRateDeg];
end

repoRoot=fileparts(fileparts(fileparts(fileparts(mfilename('fullpath')))));
outData = fullfile(repoRoot,'results','data','backflip','2026-09-18');
outGraph = fullfile(repoRoot,'results','graphs','backflip','2026-09-18');
if ~exist(outData,'dir'), mkdir(outData); end
if ~exist(outGraph,'dir'), mkdir(outGraph); end

T = table(nominal.t(:), nominal.x(:,1), nominal.x(:,2), nominal.x(:,3), ...
    nominal.x(:,4), nominal.x(:,5)*180/pi, nominal.x(:,6)*180/pi, ...
    nominal.F(:), nominal.tau(:), 'VariableNames', ...
    {'t_s','x_m','z_m','vx_mps','vz_mps','pitch_deg','pitch_rate_degps','thrust_N','torque_Nm'});
writetable(T, fullfile(outData,'trayectoria_nominal.csv'));
M = array2table(mc, 'VariableNames', {'exito','rotaciones','z_min_m','z_max_m', ...
    'z_final_m','error_angulo_final_deg','velocidad_angular_max_degps'});
writetable(M, fullfile(outData,'monte_carlo.csv'));

fig = figure('Color','w','Position',[100 100 1150 720]);
tiledlayout(2,2,'Padding','compact','TileSpacing','compact');
nexttile; plot(nominal.x(:,1),nominal.x(:,2),'LineWidth',1.8); grid on; axis equal;
xlabel('x [m]'); ylabel('z [m]'); title('Trayectoria nominal');
nexttile; plot(nominal.t,unwrap(nominal.x(:,5))*180/pi,'LineWidth',1.8); grid on;
yline(360,'--'); xlabel('Tiempo [s]'); ylabel('Pitch acumulado [deg]'); title('Rotacion');
nexttile; plot(nominal.t,nominal.x(:,6)*180/pi,'LineWidth',1.8); grid on;
yline(1000,'--'); xlabel('Tiempo [s]'); ylabel('q [deg/s]'); title('Velocidad angular');
nexttile; yyaxis left; plot(nominal.t,nominal.F,'LineWidth',1.4); ylabel('Empuje [N]');
yyaxis right; plot(nominal.t,nominal.tau,'LineWidth',1.4); ylabel('Torque [N m]');
grid on; xlabel('Tiempo [s]'); title('Entradas realizadas por motores');
exportgraphics(fig,fullfile(outGraph,'resultado_nominal.png'),'Resolution',180);

fig2 = figure('Color','w','Position',[100 100 1050 430]);
tiledlayout(1,2,'Padding','compact');
nexttile; histogram(mc(:,3),20); hold on; histogram(mc(:,4),20); grid on;
xlabel('Altura [m]'); ylabel('Casos'); legend('minima','maxima'); title('Envolvente vertical Monte Carlo');
nexttile; scatter(mc(:,2),mc(:,5),18,mc(:,1),'filled'); grid on;
xlabel('Rotaciones'); ylabel('Altura final [m]'); title('Resultado de 300 variaciones');
exportgraphics(fig2,fullfile(outGraph,'robustez_monte_carlo.png'),'Resolution',180);

fid=fopen(fullfile(outData,'resumen.txt'),'w');
fprintf(fid,'Nominal: exito=%d, rotaciones=%.4f, zmin=%.3f m, zmax=%.3f m, zfinal=%.3f m, error angular=%.2f deg, qmax=%.1f deg/s\n', ...
    nominal.success,nominal.rotations,nominal.minZ,nominal.maxZ,nominal.finalZ,nominal.finalAngleErrorDeg,nominal.maxRateDeg);
fprintf(fid,'Monte Carlo: %d/%d exitos (%.1f%%), zmin global=%.3f m, mediana zfinal=%.3f m\n', ...
    sum(mc(:,1)),N,100*mean(mc(:,1)),min(mc(:,3)),median(mc(:,5)));
fclose(fid);
disp(fileread(fullfile(outData,'resumen.txt')));

function out = run_case(p, scale, keepTrace)
    m=p.m*scale(1); J=p.J*scale(2); motorT=p.motorT*scale(3);
    thrustScale=scale(4); torqueScale=scale(5);
    n=round(p.tf/p.dt)+1; X=zeros(n,10); Flog=zeros(n,1); Tlog=zeros(n,1);
    % [x z vx vz theta q motorOmega(1:4)]
    X(1,2)=p.z0; hoverOmega=invert_thrust(m*p.g/4,p,thrustScale);
    X(1,7:10)=hoverOmega;
    mode=1; flipStart=nan;
    for i=1:n-1
        t=(i-1)*p.dt; s=X(i,:); theta=s(5); q=s(6);
        if mode==1 && t>=0.28, mode=2; flipStart=theta; end
        if mode==2 && theta-flipStart>=1.20*pi, mode=3; end
        if mode==3 && abs(theta-flipStart-2*pi)<0.10 && abs(q)<1.5, mode=4; end
        switch mode
            case 1, Fdes=1.75*m*p.g; taudes=0;
            case 2, Fdes=0.18*m*p.g; taudes=p.kRate*(p.omegaTarget-q);
            case 3
                Fdes=0.30*m*p.g;
                taudes=p.kAngle*(flipStart+2*pi-theta)-p.kRate*1.8*q;
            otherwise
                angErr=wrap_pi(theta-2*pi); Fdes=m*(p.g+5*(p.z0-s(2))-3*s(4));
                taudes=-p.kAngle*angErr-p.kRate*1.2*q;
        end
        taudes=max(-p.maxTorque,min(p.maxTorque,taudes)); Fdes=max(0,min(4*max_motor_thrust(p,thrustScale),Fdes));
        % Motores 1+4 contra 2+3 para torque de pitch.
        fp=max(0,min(max_motor_thrust(p,thrustScale),Fdes/4+taudes/(4*p.arm*torqueScale)));
        fm=max(0,min(max_motor_thrust(p,thrustScale),Fdes/4-taudes/(4*p.arm*torqueScale)));
        omegaCmd=[invert_thrust(fp,p,thrustScale),invert_thrust(fm,p,thrustScale), ...
                  invert_thrust(fm,p,thrustScale),invert_thrust(fp,p,thrustScale)];
        om=s(7:10); omDot=(omegaCmd-om)/motorT; fi=thrust_fun(om,p)*thrustScale;
        F=sum(fi); tau=p.arm*(fi(1)+fi(4)-fi(2)-fi(3))*torqueScale;
        aX=-(F/m)*sin(theta); aZ=(F/m)*cos(theta)-p.g;
        X(i+1,:)=s+p.dt*[s(3),s(4),aX,aZ,q,tau/J,omDot];
        Flog(i)=F; Tlog(i)=tau;
    end
    Flog(end)=Flog(end-1); Tlog(end)=Tlog(end-1);
    rot=(max(X(:,5))-X(1,5))/(2*pi); err=abs(wrap_pi(X(end,5)))*180/pi;
    out.success=rot>=0.98 && min(X(:,2))>0.05 && err<15 && abs(X(end,6))*180/pi<80;
    out.rotations=rot; out.minZ=min(X(:,2)); out.maxZ=max(X(:,2)); out.finalZ=X(end,2);
    out.finalAngleErrorDeg=err; out.maxRateDeg=max(abs(X(:,6)))*180/pi;
    if keepTrace, out.t=(0:n-1)'*p.dt; out.x=X; out.F=Flog; out.tau=Tlog; end
end

function f=thrust_fun(omega,p)
    r=max(0,omega/p.sigma); f=max(0,-0.23*r.^3+0.562*r.^2-0.043*r);
end
function f=max_motor_thrust(p,scale), f=thrust_fun(p.motorK,p)*scale; end
function om=invert_thrust(f,p,scale)
    f=max(0,min(max_motor_thrust(p,scale),f)); lo=0; hi=p.motorK;
    for j=1:28, mid=(lo+hi)/2; if thrust_fun(mid,p)*scale<f, lo=mid; else, hi=mid; end, end
    om=(lo+hi)/2;
end
function y=wrap_pi(x), y=atan2(sin(x),cos(x)); end
