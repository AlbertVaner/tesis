"""Identidad de las Crazyradio y de los Crazyflie del laboratorio.

Concentra seriales, canales y direcciones, y las tres formas de elegir antena
que usan los controladores:

* `select_uri`: un dron, una antena (con o sin serial pedido);
* `resolve_dual_uris`: dos drones a la vez, dos antenas distintas;
* `resolve_serial_uris`: traduce URIs por serial a índice USB, que es lo que
  cflib necesita cuando hay dos radios abiertas en el mismo proceso.

No abre radios: sólo consulta los seriales conectados.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

#: Seriales de las dos Crazyradio del laboratorio, en orden de preferencia.
KNOWN_RADIOS = ("2B1D933FCC", "9DD2507072")

#: (canal, tasa, dirección) de cada Crazyflie.
DRONE_1_LINK = (84, "2M", "E7E7E7E7E4")
DRONE_2_LINK = (90, "2M", "E7E7E7E7E5")
DRONE_LINKS = (DRONE_1_LINK, DRONE_2_LINK)


def make_uri(radio: str | int, link: tuple[int, str, str]) -> str:
    """URI cflib para una antena (serial o índice USB) y un enlace."""
    channel, rate, address = link
    return f"radio://{radio}/{channel}/{rate}/{address}"


# Usar el serial de cada Crazyradio es más seguro que los índices 0/1, que
# Windows puede intercambiar al reconectar los puertos USB.
DRONE_1_URI = make_uri(KNOWN_RADIOS[0], DRONE_1_LINK)
DRONE_2_URI = make_uri(KNOWN_RADIOS[1], DRONE_2_LINK)


def connected_radios() -> list[str]:
    """Seriales de las Crazyradio conectadas por USB, en mayúsculas."""
    from cflib.drivers.crazyradio import get_serials

    return [str(serial).upper() for serial in get_serials()]


def select_radio(
    requested: str | None,
    *,
    index: int = 0,
    radios: list[str] | None = None,
) -> str:
    """Elige una antena conectada.

    Con `requested` exige ese serial. Sin él toma la `index`-ésima antena
    conocida que esté conectada y, si no hay suficientes, la primera detectada.
    """
    radios = connected_radios() if radios is None else radios
    if not radios:
        raise RuntimeError("No se detecto ninguna Crazyradio conectada por USB.")
    if requested:
        serial = requested.upper()
        if serial not in radios:
            raise RuntimeError(
                f"La antena {serial} no esta conectada. Detectadas: {', '.join(radios)}"
            )
        return serial
    preferred = [serial for serial in KNOWN_RADIOS if serial in radios]
    return preferred[index] if index < len(preferred) else radios[0]


def select_uri(
    explicit_uri: str | None,
    requested_radio: str | None,
    link: tuple[int, str, str] = DRONE_1_LINK,
) -> str:
    """URI de un dron usando una antena disponible; `explicit_uri` manda."""
    if explicit_uri:
        return explicit_uri
    return make_uri(select_radio(requested_radio), link)


def resolve_dual_uris(uri1: str | None, uri2: str | None) -> tuple[str, str]:
    """URIs de los dos drones sobre dos antenas distintas."""
    if uri1 and uri2:
        return uri1, uri2
    radios = connected_radios()
    preferred = [serial for serial in KNOWN_RADIOS if serial in radios]
    if len(preferred) < 2:
        preferred.extend(serial for serial in radios if serial not in preferred)
    if len(preferred) < 2:
        raise RuntimeError("El control simultaneo necesita dos Crazyradio conectadas.")
    return (
        uri1 or make_uri(preferred[0], DRONE_1_LINK),
        uri2 or make_uri(preferred[1], DRONE_2_LINK),
    )


def resolve_serial_uris(
    uris: dict[str, str],
    *,
    names: dict[str, str] | None = None,
    log=print,
) -> dict[str, str]:
    """Traduce `radio://<serial>/...` a `radio://<indice USB>/...`.

    Las URIs que ya usan índice se devuelven tal cual. Si cflib no puede leer
    los seriales pero hay exactamente tantas radios como URIs por serial, se
    asignan por orden y se avisa. Dos claves nunca quedan sobre la misma radio.
    """
    names = names or {}
    serial_names = {
        key: urlsplit(uri).netloc.upper()
        for key, uri in uris.items()
        if not urlsplit(uri).netloc.isdigit()
    }
    serials: tuple[str, ...] = ()
    fallback_to_order = False
    if serial_names:
        from cflib.drivers.crazyradio import _find_devices, get_serials

        try:
            serials = tuple(serial.upper() for serial in get_serials())
        except Exception as exc:
            devices = tuple(_find_devices())
            if len(devices) == 2 and len(serial_names) == 2:
                fallback_to_order = True
                log(
                    "ADVERTENCIA USB: no se leyeron seriales; se usaran indices 0 y 1. "
                    f"Detalle: {exc}"
                )
            else:
                raise RuntimeError(
                    f"no se pudieron resolver las Crazyradio; detectadas={len(devices)}: {exc}"
                ) from exc
    resolved: dict[str, str] = {}
    for index, (key, uri) in enumerate(uris.items()):
        parts = urlsplit(uri)
        if parts.netloc.isdigit():
            resolved[key] = uri
            continue
        serial = serial_names[key]
        if fallback_to_order:
            usb_index = index
        elif serial in serials:
            usb_index = serials.index(serial)
        else:
            detected = ", ".join(serials) if serials else "ninguna"
            raise RuntimeError(f"Crazyradio {serial} no encontrada; detectadas={detected}")
        resolved[key] = urlunsplit(
            (parts.scheme, str(usb_index), parts.path, parts.query, parts.fragment)
        )
        log(f"{names.get(key, key)}: Crazyradio {serial} -> USB {usb_index}")
    if len(uris) == 2 and len({urlsplit(uri).netloc for uri in resolved.values()}) != 2:
        raise RuntimeError("ambos drones quedaron asignados a la misma Crazyradio")
    return resolved
