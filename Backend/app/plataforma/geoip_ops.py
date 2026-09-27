"""Geolocalización de IP (país) para el control de acceso por país.

Orden de resolución:
  1. Función inyectada (pruebas).
  2. Base MaxMind GeoLite2-Country si GEOIP_DB apunta a un .mmdb.
  3. Consulta HTTP/HTTPS con caché (ip-api.com u otra URL configurable).

IPs privadas, loopback o no parseables se tratan como red local (código LOCAL)
y no se consultan servicios externos.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import time
import urllib.request
from typing import Callable

from app.kernel.config import settings

logger = logging.getLogger("control_proyecto")

# Orden de continentes: América primero (VE encabeza el grupo).
_PAISES_POR_CONTINENTE: dict[str, tuple[tuple[str, str], ...]] = {
    "América": (
        ("VE", "Venezuela"),
        ("AG", "Antigua y Barbuda"),
        ("AR", "Argentina"),
        ("AW", "Aruba"),
        ("BS", "Bahamas"),
        ("BB", "Barbados"),
        ("BZ", "Belice"),
        ("BO", "Bolivia"),
        ("BR", "Brasil"),
        ("CA", "Canadá"),
        ("CL", "Chile"),
        ("CO", "Colombia"),
        ("CR", "Costa Rica"),
        ("CU", "Cuba"),
        ("CW", "Curazao"),
        ("DM", "Dominica"),
        ("EC", "Ecuador"),
        ("SV", "El Salvador"),
        ("US", "Estados Unidos"),
        ("GD", "Granada"),
        ("GL", "Groenlandia"),
        ("GP", "Guadalupe"),
        ("GT", "Guatemala"),
        ("GY", "Guyana"),
        ("GF", "Guayana Francesa"),
        ("HT", "Haití"),
        ("HN", "Honduras"),
        ("KY", "Islas Caimán"),
        ("JM", "Jamaica"),
        ("MQ", "Martinica"),
        ("MX", "México"),
        ("NI", "Nicaragua"),
        ("PA", "Panamá"),
        ("PY", "Paraguay"),
        ("PE", "Perú"),
        ("PR", "Puerto Rico"),
        ("DO", "República Dominicana"),
        ("KN", "San Cristóbal y Nieves"),
        ("LC", "Santa Lucía"),
        ("VC", "San Vicente y las Granadinas"),
        ("SX", "Sint Maarten"),
        ("SR", "Surinam"),
        ("TT", "Trinidad y Tobago"),
        ("UY", "Uruguay"),
        ("VI", "Islas Vírgenes de EE.UU."),
    ),
    "Europa": (
        ("AL", "Albania"),
        ("DE", "Alemania"),
        ("AD", "Andorra"),
        ("AT", "Austria"),
        ("BE", "Bélgica"),
        ("BY", "Bielorrusia"),
        ("BA", "Bosnia y Herzegovina"),
        ("BG", "Bulgaria"),
        ("CY", "Chipre"),
        ("VA", "Ciudad del Vaticano"),
        ("HR", "Croacia"),
        ("DK", "Dinamarca"),
        ("SK", "Eslovaquia"),
        ("SI", "Eslovenia"),
        ("ES", "España"),
        ("EE", "Estonia"),
        ("FI", "Finlandia"),
        ("FR", "Francia"),
        ("GI", "Gibraltar"),
        ("GR", "Grecia"),
        ("GG", "Guernsey"),
        ("HU", "Hungría"),
        ("IE", "Irlanda"),
        ("IS", "Islandia"),
        ("IM", "Isla de Man"),
        ("IT", "Italia"),
        ("JE", "Jersey"),
        ("XK", "Kosovo"),
        ("LV", "Letonia"),
        ("LI", "Liechtenstein"),
        ("LT", "Lituania"),
        ("LU", "Luxemburgo"),
        ("MK", "Macedonia del Norte"),
        ("MT", "Malta"),
        ("MD", "Moldavia"),
        ("MC", "Mónaco"),
        ("ME", "Montenegro"),
        ("NO", "Noruega"),
        ("NL", "Países Bajos"),
        ("PL", "Polonia"),
        ("PT", "Portugal"),
        ("GB", "Reino Unido"),
        ("CZ", "Chequia"),
        ("RO", "Rumania"),
        ("RU", "Rusia"),
        ("SM", "San Marino"),
        ("RS", "Serbia"),
        ("SE", "Suecia"),
        ("CH", "Suiza"),
        ("UA", "Ucrania"),
        ("FO", "Islas Feroe"),
        ("AX", "Åland"),
    ),
    "Asia": (
        ("AF", "Afganistán"),
        ("SA", "Arabia Saudí"),
        ("AM", "Armenia"),
        ("AZ", "Azerbaiyán"),
        ("BH", "Baréin"),
        ("BD", "Bangladés"),
        ("BN", "Brunéi"),
        ("BT", "Bután"),
        ("KH", "Camboya"),
        ("QA", "Catar"),
        ("CN", "China"),
        ("KP", "Corea del Norte"),
        ("KR", "Corea del Sur"),
        ("AE", "Emiratos Árabes Unidos"),
        ("PH", "Filipinas"),
        ("GE", "Georgia"),
        ("HK", "Hong Kong"),
        ("IN", "India"),
        ("ID", "Indonesia"),
        ("IQ", "Irak"),
        ("IR", "Irán"),
        ("IL", "Israel"),
        ("JP", "Japón"),
        ("JO", "Jordania"),
        ("KZ", "Kazajistán"),
        ("KG", "Kirguistán"),
        ("KW", "Kuwait"),
        ("LA", "Laos"),
        ("LB", "Líbano"),
        ("MO", "Macao"),
        ("MY", "Malasia"),
        ("MV", "Maldivas"),
        ("MN", "Mongolia"),
        ("MM", "Myanmar"),
        ("NP", "Nepal"),
        ("OM", "Omán"),
        ("PK", "Pakistán"),
        ("PS", "Palestina"),
        ("SG", "Singapur"),
        ("SY", "Siria"),
        ("LK", "Sri Lanka"),
        ("TH", "Tailandia"),
        ("TW", "Taiwán"),
        ("TJ", "Tayikistán"),
        ("TL", "Timor Oriental"),
        ("TM", "Turkmenistán"),
        ("TR", "Turquía"),
        ("UZ", "Uzbekistán"),
        ("VN", "Vietnam"),
        ("YE", "Yemen"),
    ),
    "África": (
        ("AO", "Angola"),
        ("DZ", "Argelia"),
        ("BJ", "Benín"),
        ("BW", "Botsuana"),
        ("BF", "Burkina Faso"),
        ("BI", "Burundi"),
        ("CV", "Cabo Verde"),
        ("CM", "Camerún"),
        ("TD", "Chad"),
        ("KM", "Comoras"),
        ("CG", "Congo"),
        ("CD", "Congo (RDC)"),
        ("CI", "Costa de Marfil"),
        ("EG", "Egipto"),
        ("ER", "Eritrea"),
        ("ET", "Etiopía"),
        ("GA", "Gabón"),
        ("GM", "Gambia"),
        ("GH", "Ghana"),
        ("GN", "Guinea"),
        ("GQ", "Guinea Ecuatorial"),
        ("GW", "Guinea-Bisáu"),
        ("KE", "Kenia"),
        ("LS", "Lesoto"),
        ("LR", "Liberia"),
        ("LY", "Libia"),
        ("MG", "Madagascar"),
        ("MW", "Malaui"),
        ("ML", "Malí"),
        ("MA", "Marruecos"),
        ("MU", "Mauricio"),
        ("MR", "Mauritania"),
        ("MZ", "Mozambique"),
        ("NA", "Namibia"),
        ("NE", "Níger"),
        ("NG", "Nigeria"),
        ("CF", "República Centroafricana"),
        ("RW", "Ruanda"),
        ("EH", "Sáhara Occidental"),
        ("ST", "Santo Tomé y Príncipe"),
        ("SN", "Senegal"),
        ("SC", "Seychelles"),
        ("SL", "Sierra Leona"),
        ("SO", "Somalia"),
        ("ZA", "Sudáfrica"),
        ("SD", "Sudán"),
        ("SS", "Sudán del Sur"),
        ("SZ", "Esuatini"),
        ("TZ", "Tanzania"),
        ("TG", "Togo"),
        ("TN", "Túnez"),
        ("UG", "Uganda"),
        ("DJ", "Yibuti"),
        ("ZM", "Zambia"),
        ("ZW", "Zimbabue"),
        ("RE", "Reunión"),
        ("YT", "Mayotte"),
    ),
    "Oceanía": (
        ("AU", "Australia"),
        ("FJ", "Fiyi"),
        ("GU", "Guam"),
        ("KI", "Kiribati"),
        ("MH", "Islas Marshall"),
        ("FM", "Micronesia"),
        ("NR", "Nauru"),
        ("NC", "Nueva Caledonia"),
        ("NZ", "Nueva Zelanda"),
        ("PW", "Palaos"),
        ("PG", "Papúa Nueva Guinea"),
        ("PF", "Polinesia Francesa"),
        ("WS", "Samoa"),
        ("AS", "Samoa Americana"),
        ("SB", "Islas Salomón"),
        ("TO", "Tonga"),
        ("TV", "Tuvalu"),
        ("VU", "Vanuatu"),
        ("CK", "Islas Cook"),
        ("MP", "Islas Marianas del Norte"),
    ),
}

PAISES = tuple(
    (codigo, nombre, continente)
    for continente, filas in _PAISES_POR_CONTINENTE.items()
    for codigo, nombre in filas
)

NOMBRE_PAIS = {c: n for c, n, _cont in PAISES}


def paises_catalogo() -> list[dict[str, str]]:
    """Catálogo del selector GeoIP: código ISO, nombre y continente."""
    return [{"codigo": c, "nombre": n, "continente": cont} for c, n, cont in PAISES]


_lookup_fn: Callable[[str], dict] | None = None
_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 6 * 3600
_reader = None
_reader_path: str | None = None


def set_lookup(fn: Callable[[str], dict] | None) -> None:
    """Inyectable en pruebas: fn(ip) -> {country_code, country_name, source}."""
    global _lookup_fn
    _lookup_fn = fn


def reset_cache_para_pruebas() -> None:
    _cache.clear()


def es_ip_publica(ip: str | None) -> bool:
    parsed = _parse_ip(ip)
    if parsed is None:
        return False
    return bool(parsed.is_global)


# Solo LAN propia (RFC1918), loopback y link-local. Tu NUC: 192.168.88.0/24.
_REDES_LOCALES = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def es_ip_local(ip: str | None) -> bool:
    """Loopback, RFC1918, link-local, o no parseable (p. ej. testclient)."""
    parsed = _parse_ip(ip)
    if parsed is None:
        return True
    return any(parsed in red for red in _REDES_LOCALES)


def _parse_ip(ip: str | None):
    raw = (ip or "").strip()
    if not raw or raw in ("desconocida", "testclient", "localhost"):
        return None
    if raw.startswith("::ffff:"):
        raw = raw[7:]
    try:
        return ipaddress.ip_address(raw)
    except ValueError:
        return None


def _local(ip: str, motivo: str) -> dict:
    return {
        "ip": ip,
        "country_code": "LOCAL",
        "country_name": "Red local",
        "source": motivo,
        "disponible": True,
    }


def _mmdb_reader():
    global _reader, _reader_path
    path = (settings.GEOIP_DB or "").strip()
    if not path:
        _reader = None
        _reader_path = None
        return None
    if _reader is not None and _reader_path == path:
        return _reader
    try:
        import maxminddb  # type: ignore
        _reader = maxminddb.open_database(path)
        _reader_path = path
        return _reader
    except Exception:
        logger.debug("GeoLite2 no disponible en %s", path, exc_info=True)
        _reader = None
        _reader_path = path
        return None


def _desde_mmdb(ip: str) -> dict | None:
    reader = _mmdb_reader()
    if reader is None:
        return None
    try:
        rec = reader.get(ip) or {}
    except Exception:
        return None
    country = rec.get("country") or rec.get("registered_country") or {}
    names = country.get("names") or {}
    code = (country.get("iso_code") or "").upper()
    if not code:
        return None
    nombre = names.get("es") or names.get("en") or NOMBRE_PAIS.get(code, code)
    return {
        "ip": ip,
        "country_code": code,
        "country_name": nombre,
        "source": "geolite2",
        "disponible": True,
    }


def _desde_http(ip: str) -> dict | None:
    plantilla = (settings.GEOIP_LOOKUP_URL or "").strip()
    if not plantilla or "{ip}" not in plantilla:
        return None
    url = plantilla.replace("{ip}", ip)
    timeout = max(0.5, float(settings.GEOIP_TIMEOUT_S or 2.5))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ControlDeProyecto/1.5"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw) if raw.lstrip().startswith("{") else {}
    except Exception:
        logger.info("Consulta GeoIP HTTP falló para %s", ip)
        return None
    status = (data.get("status") or "").lower()
    if status and status != "success":
        return None
    code = (data.get("countryCode") or data.get("country_code") or data.get("country") or "")
    if isinstance(code, str) and len(code) == 2:
        code = code.upper()
    else:
        code = ""
    nombre = data.get("country") if isinstance(data.get("country"), str) and len(data.get("country") or "") > 2 else ""
    nombre = nombre or data.get("country_name") or NOMBRE_PAIS.get(code, code)
    if not code:
        return None
    return {
        "ip": ip,
        "country_code": code,
        "country_name": nombre or code,
        "source": "http",
        "disponible": True,
    }


def lookup(ip: str | None) -> dict:
    """Devuelve country_code/name. disponible=False si no se pudo resolver una IP pública."""
    raw = (ip or "").strip() or "desconocida"
    parsed = _parse_ip(raw)
    if parsed is None:
        return _local(raw, "ip-no-parseable")
    if not es_ip_publica(raw):
        return _local(raw, "ip-privada")

    if _lookup_fn is not None:
        out = dict(_lookup_fn(raw) or {})
        out.setdefault("ip", raw)
        out.setdefault("disponible", True)
        out.setdefault("source", "inyectado")
        code = (out.get("country_code") or "").upper()
        out["country_code"] = code
        out.setdefault("country_name", NOMBRE_PAIS.get(code, code or "Desconocido"))
        return out

    ahora = time.monotonic()
    cached = _cache.get(raw)
    if cached and (ahora - cached[0]) < _CACHE_TTL:
        return dict(cached[1])

    result = _desde_mmdb(raw) or _desde_http(raw)
    if result is None:
        result = {
            "ip": raw,
            "country_code": "",
            "country_name": "Desconocido",
            "source": "no-disponible",
            "disponible": False,
        }
    _cache[raw] = (ahora, result)
    return dict(result)
