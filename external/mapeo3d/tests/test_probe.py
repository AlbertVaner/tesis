"""Sondeo RTSP, contra un servidor de mentira levantado en localhost.

Sin cámaras. Se monta un socket que responde como una cámara IP —incluido el
reto Digest— y se comprueba que el diagnóstico distingue los cuatro fallos que
importan: puerto cerrado, no es RTSP, credenciales mal y ruta mal.
"""

from __future__ import annotations

import socket
import sys
import threading
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from mapeo3d.capture.probe import (  # noqa: E402
    _digest,
    cabecera_autorizacion,
    describe,
    puerto_abierto,
    sondear,
)

REALM = "Login to 4E05F1PAG00001"
NONCE = "1234567890abcdef1234567890abcdef"


# --------------------------------------------------------------- Digest MD5


def test_digest_contra_el_vector_del_rfc_2617():
    """Si esto falla, ninguna cámara Amcrest va a autenticar.

    Se ancla a los **intermedios publicados** en el RFC 2617 §3.5 (HA1 y HA2),
    no sólo al resultado: así la prueba comprueba la fórmula y no se limita a
    congelar lo que devuelve la implementación de hoy.
    """
    import hashlib

    md5 = lambda s: hashlib.md5(s.encode()).hexdigest()  # noqa: E731

    ha1 = md5("Mufasa:testrealm@host.com:Circle Of Life")
    ha2 = md5("GET:/dir/index.html")
    assert ha1 == "939e7578ed9e3c518a452acee763bce9"      # RFC 2617
    assert ha2 == "39aff3a2bab6126f332b942af96d3366"      # RFC 2617

    nonce = "dcd98b7102dd2f0e8b11d0f600bfb0c093"
    # La variante CON qop del RFC, como comprobación cruzada de la cadena.
    assert (md5(f"{ha1}:{nonce}:00000001:0a4f113b:auth:{ha2}")
            == "6629fae49393a05397450978507c4ef1")        # RFC 2617

    # Las cámaras IP usan la variante SIN qop, que es la que implementamos.
    resp = _digest("Mufasa", "Circle Of Life", "GET", "/dir/index.html",
                   {"realm": "testrealm@host.com", "nonce": nonce})
    assert resp == md5(f"{ha1}:{nonce}:{ha2}")
    assert resp == "670fd8c2df070c60b045671b8b24ff02"


def test_la_cabecera_digest_lleva_todos_los_campos():
    reto = f'Digest realm="{REALM}", nonce="{NONCE}", stale="FALSE"'
    cab = cabecera_autorizacion("admin", "clave", "DESCRIBE",
                                "rtsp://h:554/x", reto)
    assert cab.startswith("Digest ")
    for campo in ("username=", "realm=", "nonce=", "uri=", "response="):
        assert campo in cab
    assert NONCE in cab


def test_soporta_basic_ademas_de_digest():
    cab = cabecera_autorizacion("admin", "clave", "DESCRIBE", "rtsp://h/x",
                                'Basic realm="cam"')
    assert cab == "Basic YWRtaW46Y2xhdmU="


def test_un_reto_desconocido_no_inventa_cabecera():
    assert cabecera_autorizacion("a", "b", "DESCRIBE", "u", "Negotiate") is None


# ------------------------------------------------- servidor RTSP de mentira


class CamaraFalsa:
    """Servidor mínimo que se comporta como una cámara IP.

    Reproduce lo que importa: reto Digest, 401 si la clave está mal, 404 si la
    ruta no existe, 200 si todo encaja.
    """

    def __init__(self, clave: str = "correcta", rutas=("/cam/realmonitor",),
                 habla_rtsp: bool = True):
        self.clave = clave
        self.rutas = rutas
        self.habla_rtsp = habla_rtsp
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.puerto = self.sock.getsockname()[1]
        self._parar = threading.Event()
        self.hilo = threading.Thread(target=self._servir, daemon=True)

    def __enter__(self):
        self.hilo.start()
        return self

    def __exit__(self, *_):
        self._parar.set()
        try:
            self.sock.close()
        except OSError:
            pass

    def _responder(self, peticion: str) -> str:
        if not self.habla_rtsp:
            return "HTTP/1.1 200 OK\r\nServer: cosa-rara\r\n\r\n"
        cabeceras = {}
        for ln in peticion.split("\r\n")[1:]:
            if ":" in ln:
                k, v = ln.split(":", 1)
                cabeceras[k.strip().lower()] = v.strip()
        primera = peticion.split("\r\n")[0]
        ruta = primera.split(" ")[1] if " " in primera else ""

        auth = cabeceras.get("authorization", "")
        if not auth:
            return (f"RTSP/1.0 401 Unauthorized\r\nCSeq: 1\r\n"
                    f"Server: CamaraFalsa/1.0\r\n"
                    f'WWW-Authenticate: Digest realm="{REALM}", '
                    f'nonce="{NONCE}"\r\n\r\n')

        esperado = _digest("admin", self.clave, "DESCRIBE", ruta,
                           {"realm": REALM, "nonce": NONCE})
        if f'response="{esperado}"' not in auth:
            return ("RTSP/1.0 401 Unauthorized\r\nCSeq: 2\r\n"
                    "Server: CamaraFalsa/1.0\r\n\r\n")
        if not any(ruta.endswith(r) or r in ruta for r in self.rutas):
            return ("RTSP/1.0 404 Not Found\r\nCSeq: 2\r\n"
                    "Server: CamaraFalsa/1.0\r\n\r\n")
        return ("RTSP/1.0 200 OK\r\nCSeq: 2\r\nServer: CamaraFalsa/1.0\r\n"
                "Content-Type: application/sdp\r\n\r\n")

    def _servir(self):
        while not self._parar.is_set():
            try:
                cli, _ = self.sock.accept()
            except OSError:
                return
            with cli:
                try:
                    while True:
                        datos = cli.recv(4096)
                        if not datos:
                            break
                        cli.sendall(
                            self._responder(datos.decode("utf-8", "replace"))
                            .encode()
                        )
                except OSError:
                    pass


# ------------------------------------------------------------- diagnósticos


def test_puerto_cerrado_se_detecta_rapido():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    puerto = s.getsockname()[1]
    s.close()                                   # nadie escucha ahí
    assert not puerto_abierto("127.0.0.1", puerto, timeout=0.5)


def test_conexion_correcta():
    with CamaraFalsa(clave="correcta") as cam:
        s = sondear("127.0.0.1", "admin", "correcta", cam.puerto, timeout=2.0)
        assert s.abierto and s.rtsp and s.autenticado
        assert s.conecta
        assert "Conecta correctamente" in s.diagnostico()
        assert s.servidor.startswith("CamaraFalsa")


def test_credenciales_malas_dan_401_y_lo_dice():
    with CamaraFalsa(clave="correcta") as cam:
        s = sondear("127.0.0.1", "admin", "equivocada", cam.puerto, timeout=2.0)
        assert s.abierto and s.rtsp
        assert not s.autenticado, "no detectó que la clave está mal"
        assert not s.conecta
        assert "rechaza las credenciales" in s.diagnostico()


def test_ruta_inexistente_da_404_y_se_distingue_del_401():
    """Es la distinción que más tiempo ahorra: cuenta mal vs modelo mal."""
    with CamaraFalsa(clave="correcta", rutas=("/ruta/rarisima",)) as cam:
        s = sondear("127.0.0.1", "admin", "correcta", cam.puerto, timeout=2.0)
        assert s.autenticado, "las credenciales eran buenas"
        assert not s.conecta
        assert "ninguna ruta RTSP conocida" in s.diagnostico()
        assert all(estado == 404 for _r, estado, _m in s.rutas_probadas)


def test_algo_que_no_habla_rtsp():
    with CamaraFalsa(habla_rtsp=False) as cam:
        s = sondear("127.0.0.1", "admin", "x", cam.puerto, timeout=2.0)
        assert s.abierto and not s.rtsp
        assert "no responde RTSP" in s.diagnostico()


def test_puerto_cerrado_da_el_consejo_de_activar_la_camara():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    puerto = s.getsockname()[1]
    s.close()
    d = sondear("127.0.0.1", "admin", "x", puerto, timeout=0.5).diagnostico()
    assert "no abre" in d
    assert "ACTIVARLAS" in d, "falta el aviso de activación de las Amcrest"


def test_describe_devuelve_el_reto_para_poder_diagnosticar_sin_usuario():
    """Sin credenciales, el 401 ya prueba que la cámara está viva."""
    with CamaraFalsa() as cam:
        estado, _motivo, cab = describe("127.0.0.1", "/x", "", "",
                                        cam.puerto, timeout=2.0)
        assert estado == 401
        assert REALM in cab["www-authenticate"]


def test_se_prueban_las_rutas_de_todos_los_modelos():
    """El fallo típico al estrenar una cámara es el 'model' equivocado."""
    with CamaraFalsa(clave="c", rutas=("/stream1",)) as cam:
        s = sondear("127.0.0.1", "admin", "c", cam.puerto, timeout=2.0)
        rutas = [r for r, _e, _m in s.rutas_probadas]
        assert "/stream1" in rutas
        assert any("realmonitor" in r for r in rutas)
        assert s.conecta, "encontró la ruta aunque el modelo declarado fuese otro"


def test_un_host_inalcanzable_no_cuelga():
    s = sondear("127.0.0.1", "admin", "x", 1, timeout=0.4)
    assert not s.abierto
    assert not s.conecta
