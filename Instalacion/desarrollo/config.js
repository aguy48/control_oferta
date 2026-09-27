/* Sistema de Cotización: consola propia, API :8100 (Control de Proyecto usa :8000). */
(function () {
  var h = location.hostname;
  // Loopback y túneles locales (ProtonVPN 10.2.x): usar 127.0.0.1.
  var local =
    !h ||
    h === "127.0.0.1" ||
    h === "localhost" ||
    h === "::1" ||
    /^10\.2\./.test(h);
  if (local) {
    window.COTIZACION_API_BASE = "http://127.0.0.1:8100";
    return;
  }
  window.COTIZACION_API_BASE = location.protocol + "//" + h + ":8100";
})();
