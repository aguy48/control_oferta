/* Sistema de Cotización — ORIOL Consultores C.A.
 *
 * Frontend estático (sin build), mismo patrón que Control de Proyecto:
 * token Bearer en sessionStorage, refresco automático y los mismos pasos de
 * inicio de sesión que publica identity/ (cambiar_password → totp /
 * 2fa_setup → escenario → ok).
 */
(function(){
'use strict';

const API = String(window.COTIZACION_API_BASE || 'http://127.0.0.1:8100').replace(/\/$/, '');
const SESSION_KEY = 'cotizacion_sesion';

// Espejo de TRANSICIONES_OFERTA (Backend/app/kernel/models.py).
const TRANSICIONES = {
  borrador: ['enviada', 'anulada'],
  enviada: ['en_negociacion', 'ganada', 'perdida', 'anulada'],
  en_negociacion: ['ganada', 'perdida', 'anulada'],
  ganada: [], perdida: [], anulada: [],
};
const ETQ_ESTADO = {
  borrador: 'Borrador', enviada: 'Enviada', en_negociacion: 'En negociación',
  ganada: 'Ganada', perdida: 'Perdida', anulada: 'Anulada',
};
const CERRADOS = ['ganada', 'perdida', 'anulada'];
const EDITABLES_CERRADA = ['notas', 'cliente_contacto'];
const TIPOS_ANEXO = [
  ['oferta_proveedor', 'Oferta de proveedor'],
  ['factura_proveedor', 'Factura de proveedor'],
  ['informe_tecnico', 'Informe técnico / levantamiento'],
  ['oferta_comercial', 'Oferta comercial ORIOL'],
  ['rif', 'RIF'],
  ['audio', 'Audio / nota de voz'],
  ['whatsapp', 'Chat de WhatsApp'],
  ['imagen', 'Foto o captura'],
  ['otro', 'Otro'],
];
const ACCEPT_FUENTES = '.pdf,application/pdf,.doc,.docx,.odt,.rtf,.txt,.xls,.xlsx,.ods,.csv,.ppt,.pptx,.odp,audio/*,.mp3,.wav,.m4a,.ogg,.opus,.aac,.flac,.zip,image/*,.jpg,.jpeg,.png,.webp';
const ROLES_ESCRITURA = ['admin', 'analista'];

// Qué crea Control de Proyecto con cada modalidad (ING-COT-003 §4 / FOR-COT-002 §3).
const MODALIDADES = [
  {id: 'suministro', modalidad: 'suministro', facturacion: null, titulo: 'Suministro',
   texto: 'Solo materiales o equipos. Llega a Control de Proyecto como orden de compra con un único frente SUMINISTRO.'},
  {id: 'resumida', modalidad: 'ejecucion', facturacion: 'resumida', titulo: 'Ejecución resumida',
   texto: 'Obra con varias disciplinas, valuada en un solo frente GLOBAL.'},
  {id: 'detallada', modalidad: 'ejecucion', facturacion: 'detallada', titulo: 'Ejecución detallada',
   texto: 'Obra valuada por disciplina: un frente por cada disciplina de la oferta.'},
];

let auth = {accessToken: null, refreshToken: null, usuario: '', nombre: '', rol: '', escenario: null};
let pendienteCambio = null;   // {usuario, password} mientras se cambia la clave temporal
let ofertas = [];
let actual = null;            // oferta seleccionada (respuesta del API)
let partidasEdit = [];        // copia editable de las partidas
let partidasSucias = false;
let refreshTimer = null;
let mcpEstado = {configurado: false, ok: false, destinos: []};  // GET /mcp/estado

// ---------------------------------------------------------------- utilidades
const $ = (id) => document.getElementById(id);
function esc(v){
  return String(v == null ? '' : v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function dinero(n, moneda){
  const v = Number(n || 0).toLocaleString('es-VE', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  return (moneda ? moneda + ' ' : '') + v;
}
function fecha(v){
  if(!v) return '—';
  const d = new Date(String(v).endsWith('Z') || /[+-]\d\d:\d\d$/.test(v) ? v : v + 'Z');
  return isNaN(d) ? String(v) : d.toLocaleString('es-VE', {dateStyle: 'short', timeStyle: 'short'});
}
function r2(n){ return Math.round((Number(n) || 0) * 100) / 100; }
function toast(msg, malo){
  const t = $('toast');
  t.textContent = msg;
  t.className = 'toast' + (malo ? ' bad' : '');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add('hidden'), malo ? 7000 : 3500);
}
function detalleError(data, status){
  if(!data) return 'Error HTTP ' + status;
  if(typeof data.detail === 'string') return data.detail;
  if(data.detail && typeof data.detail === 'object' && data.detail.mensaje) return data.detail.mensaje;
  if(Array.isArray(data.detail)) return data.detail.map(x => (x.loc ? x.loc.slice(-1)[0] + ': ' : '') + x.msg).join('; ');
  return 'Error HTTP ' + status;
}
function puedeEscribir(){
  return ROLES_ESCRITURA.includes(auth.rol) && !(auth.escenario && auth.escenario.solo_lectura);
}

// ---------------------------------------------------------------- API
function persistir(){ try{ sessionStorage.setItem(SESSION_KEY, JSON.stringify(auth)); }catch(e){} }
function olvidar(){ try{ sessionStorage.removeItem(SESSION_KEY); }catch(e){} }

async function llamar(path, opts){
  try{ return await fetch(API + path, opts); }
  catch(e){ throw new Error('No se pudo contactar al servidor del Sistema de Cotización (' + API + ').'); }
}

async function api(path, opts, _reintento){
  opts = opts || {};
  const headers = Object.assign({}, opts.headers || {});
  if(opts.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  if(auth.accessToken) headers['Authorization'] = 'Bearer ' + auth.accessToken;
  const res = await llamar(path, Object.assign({}, opts, {headers}));
  if(res.status === 401 && !_reintento && auth.refreshToken){
    if(await refrescar()) return api(path, opts, true);
    salir(true);
    throw new Error('La sesión expiró. Inicia sesión de nuevo.');
  }
  return res;
}

async function apiJson(path, opts){
  const res = await api(path, opts);
  if(res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if(!res.ok) throw new Error(detalleError(data, res.status));
  return data;
}

async function apiUpload(path, file, extra){
  const fd = new FormData();
  fd.append('archivo', file);
  Object.entries(extra || {}).forEach(([k, v]) => { if(v != null) fd.append(k, v); });
  const headers = {};
  if(auth.accessToken) headers.Authorization = 'Bearer ' + auth.accessToken;
  const res = await llamar(path, {method: 'POST', headers, body: fd});
  const data = await res.json().catch(() => null);
  if(!res.ok) throw new Error(detalleError(data, res.status));
  return data;
}

async function apiUploadMany(path, files, extra){
  const fd = new FormData();
  Array.from(files || []).forEach(f => fd.append('archivos', f));
  Object.entries(extra || {}).forEach(([k, v]) => { if(v != null) fd.append(k, v); });
  const headers = {};
  if(auth.accessToken) headers.Authorization = 'Bearer ' + auth.accessToken;
  const res = await llamar(path, {method: 'POST', headers, body: fd});
  const data = await res.json().catch(() => null);
  if(!res.ok) throw new Error(detalleError(data, res.status));
  return data;
}

function inferirTipoAnexo(file, fallback){
  const n = String(file && file.name || '').toLowerCase();
  const t = String(file && file.type || '').toLowerCase();
  if(t.startsWith('audio/') || /\.(mp3|wav|m4a|ogg|opus|aac|flac|amr)$/.test(n)) return 'audio';
  if(/whatsapp|_chat\.txt/.test(n) || n.endsWith('.zip') || n.endsWith('.txt')) return 'whatsapp';
  if(t.startsWith('image/') || /\.(jpe?g|png|webp|heic)$/.test(n)) return 'imagen';
  if(n.endsWith('.pdf')) return fallback || 'oferta_proveedor';
  return fallback || 'otro';
}

function opcionesSbc(seleccionado){
  if(mcpEstado.configurado){
    const ops = [['', mcpEstado.ok ? '— Elige el SBC destino —' : '— MCP sin conexión —']]
      .concat((mcpEstado.destinos || []).map(d => [d.id, d.nombre + (d.sitio_nombre ? ' · ' + d.sitio_nombre : '') + (d.estado && d.estado !== 'en_linea' ? ' (' + d.estado + ')' : '')]));
    if(seleccionado && !ops.some(o => o[0] === seleccionado)) ops.push([seleccionado, seleccionado]);
    return ops;
  }
  return null;
}

function sbcInstancia(o){
  const id = (o && o.mcp_destino_id) || mcpEstado.destino_id || '';
  const d = (mcpEstado.destinos || []).find(x => x.id === id);
  const nombre = (d && d.nombre) || (o && o.sede_destino) || mcpEstado.sede_nombre || '';
  return {id, nombre};
}

function avisoSbcInstancia(o){
  const s = sbcInstancia(o);
  if(s.nombre) return 'SBC destino (único de esta instancia): ' + s.nombre + '. Lo cambia el administrador en 14 Generales.';
  if(mcpEstado.configurado) return 'Falta el SBC único: el administrador lo elige en 14 Generales.';
  return 'MCP y SBC se configuran en 14 Generales. Mientras tanto el traspaso es por descarga del archivo.';
}

async function refrescar(){
  if(!auth.refreshToken) return false;
  try{
    const res = await llamar('/auth/refresh', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({refresh_token: auth.refreshToken})});
    if(!res.ok) return false;
    const d = await res.json();
    auth.accessToken = d.access_token;
    auth.refreshToken = d.refresh_token;
    if(d.escenario) auth.escenario = d.escenario;
    persistir();
    return true;
  }catch(e){ return false; }
}

// ---------------------------------------------------------------- login
function mostrarPaso(id){
  ['f-login', 'f-cambio', 'f-2fa', 'p-escenario'].forEach(x => $(x).classList.toggle('hidden', x !== id));
  $('login-error').textContent = '';
}
function errorLogin(msg){ $('login-error').textContent = msg; }

function tomarTokens(d){
  if(d.access_token) auth.accessToken = d.access_token;
  if(d.refresh_token) auth.refreshToken = d.refresh_token;
  if(d.usuario) auth.usuario = d.usuario;
  if(d.nombre) auth.nombre = d.nombre;
  if(d.rol) auth.rol = d.rol;
  if(d.escenario) auth.escenario = d.escenario;
  persistir();
}

async function tras_autenticar(d){
  tomarTokens(d);
  if(d.paso === 'cambiar_password'){ mostrarPaso('f-cambio'); $('c-nueva').focus(); return; }
  if(d.paso === 'totp'){
    $('l-totp-wrap').classList.remove('hidden');
    $('l-usuario').readOnly = $('l-password').readOnly = true;
    $('l-btn').textContent = 'Verificar código';
    $('l-totp').focus();
    return;
  }
  if(d.paso === '2fa_setup' || d.requiere_2fa_setup){ await iniciar2fa(); return; }
  if(d.paso === 'escenario'){ await pedirEscenario(d.escenarios); return; }
  await entrar();
}

async function iniciar2fa(){
  const d = await apiJson('/auth/2fa/setup', {method: 'POST'});
  $('t-qr').src = d.qr_data_url || '';
  $('t-secret').textContent = d.secret;
  mostrarPaso('f-2fa');
  $('t-codigo').focus();
}

async function pedirEscenario(lista){
  if(!lista || !lista.length){
    const d = await apiJson('/auth/escenarios');
    lista = d.escenarios || [];
  }
  if(!lista.length){ errorLogin('No tienes escenarios asignados. Pide al administrador que te asigne uno.'); return; }
  lista = lista.slice().sort((a, b) => (b.por_defecto ? 1 : 0) - (a.por_defecto ? 1 : 0)
    || String(a.nombre || '').localeCompare(String(b.nombre || ''), 'es'));
  $('esc-lista').innerHTML = lista.map(e =>
    `<button type="button" data-id="${esc(e.id)}" class="${e.por_defecto ? 'sel' : ''}"><strong>${esc(e.nombre)}</strong><br>
     <span class="small muted">${esc(e.estado)}${e.solo_lectura ? ' · solo lectura' : ''}${e.por_defecto ? ' · seleccionado' : ''}</span></button>`).join('');
  $('esc-lista').querySelectorAll('button').forEach(b => b.addEventListener('click', () => elegirEscenario(b.dataset.id)));
  mostrarPaso('p-escenario');
}

async function elegirEscenario(id){
  try{
    const d = await apiJson('/auth/escenario', {method: 'POST', body: JSON.stringify({escenario_id: id})});
    tomarTokens(d);
    $('login').classList.add('hidden');
    await entrar();
  }catch(e){ errorLogin(e.message); }
}

async function abrirSelectorEscenarioSesion(){
  try{
    const d = await apiJson('/auth/escenarios');
    $('login').classList.remove('hidden');
    await pedirEscenario(d.escenarios || []);
  }catch(e){ toast(e.message, true); }
}

async function entrar(){
  $('login').classList.add('hidden');
  $('app').classList.remove('hidden');
  $('u-nombre').textContent = auth.nombre;
  $('u-rol').textContent = auth.rol;
  $('esc-actual').textContent = auth.escenario
    ? 'Escenario: ' + auth.escenario.nombre + (auth.escenario.solo_lectura ? ' (solo lectura)' : '') : '';
  $('b-nueva').classList.toggle('hidden', !puedeEscribir());
  clearInterval(refreshTimer);
  refreshTimer = setInterval(refrescar, 10 * 60 * 1000);
  if(window.PlataformaCotizacion){
    window.PlataformaCotizacion.aplicarPermisos();
    window.PlataformaCotizacion.mostrarVista('panel');
    if(window.PlataformaCotizacion.iniciarAsistenteTrasLogin){
      window.PlataformaCotizacion.iniciarAsistenteTrasLogin();
    }
  }
  await cargarMcp();
  await asegurarOnlyOfficeEstado(true);
  await cargarLista();
}

async function cargarMcp(){
  try{ mcpEstado = await apiJson('/mcp/estado'); }
  catch(e){ mcpEstado = {configurado: false, ok: false, destinos: [], detalle: e.message}; }
}

async function salir(silencioso){
  clearInterval(refreshTimer);
  if(!silencioso && auth.refreshToken){
    try{ await api('/auth/logout', {method: 'POST', body: JSON.stringify({refresh_token: auth.refreshToken})}); }catch(e){}
  }
  auth = {accessToken: null, refreshToken: null, usuario: '', nombre: '', rol: '', escenario: null};
  olvidar();
  actual = null; ofertas = []; partidasSucias = false;
  if(window.PlataformaCotizacion && window.PlataformaCotizacion.asistenteVisibleSegunSesion){
    window.PlataformaCotizacion.asistenteVisibleSegunSesion(false);
  }
  $('app').classList.add('hidden');
  $('login').classList.remove('hidden');
  $('f-login').reset();
  $('l-usuario').readOnly = $('l-password').readOnly = false;
  $('l-totp-wrap').classList.add('hidden');
  $('l-btn').textContent = 'Entrar';
  mostrarPaso('f-login');
}

function enlazarLogin(){
  $('f-login').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const usuario = $('l-usuario').value.trim(), password = $('l-password').value;
    const totp = $('l-totp').value.replace(/\D/g, '') || undefined;
    $('l-btn').disabled = true;
    try{
      const res = await llamar('/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({usuario, password, totp})});
      const d = await res.json().catch(() => null);
      if(!res.ok) throw new Error(detalleError(d, res.status));
      pendienteCambio = {usuario, password};
      await tras_autenticar(d);
    }catch(e){ errorLogin(e.message); }
    finally{ $('l-btn').disabled = false; }
  });
  $('f-cambio').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const nueva = $('c-nueva').value;
    if(nueva !== $('c-repite').value){ errorLogin('Las contraseñas no coinciden.'); return; }
    try{
      const res = await llamar('/auth/cambiar-password', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({usuario: pendienteCambio.usuario, password_actual: pendienteCambio.password, password_nueva: nueva})});
      const d = await res.json().catch(() => null);
      if(!res.ok) throw new Error(detalleError(d, res.status));
      pendienteCambio = null;
      await tras_autenticar(d);
    }catch(e){ errorLogin(e.message); }
  });
  $('f-2fa').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    try{
      const d = await apiJson('/auth/2fa/verify', {method: 'POST',
        body: JSON.stringify({codigo: $('t-codigo').value.replace(/\D/g, '')})});
      if(d && d.access_token){ tomarTokens(d); await entrar(); return; }
      await pedirEscenario(d && d.escenarios);
    }catch(e){ errorLogin(e.message); }
  });
  $('b-salir').addEventListener('click', () => {
    if(partidasSucias && !confirm('Hay cambios en las partidas sin guardar. ¿Salir de todos modos?')) return;
    salir(false);
  });
}

// ---------------------------------------------------------------- lista
async function cargarLista(seleccionar){
  const estado = $('f-estado').value;
  try{
    ofertas = await apiJson('/ofertas' + (estado ? '?estado=' + encodeURIComponent(estado) : ''));
  }catch(e){ toast(e.message, true); ofertas = []; }
  pintarLista();
  const id = seleccionar || (actual && actual.id);
  if(id){
    const o = ofertas.find(x => x.id === id);
    if(o) seleccionarOferta(o, true);
  }
}

function pintarLista(){
  const ul = $('lista');
  if(!ofertas.length){ ul.innerHTML = '<li class="vacio" style="cursor:default">Sin ofertas en este escenario.</li>'; return; }
  ul.innerHTML = ofertas.map(o => `
    <li data-id="${esc(o.id)}" class="${actual && actual.id === o.id ? 'sel' : ''}">
      <div class="meta"><span class="cod">${esc(o.codigo)}</span><span class="estado ${esc(o.estado)}">${esc(ETQ_ESTADO[o.estado] || o.estado)}</span></div>
      <div class="tit">${esc(o.titulo)}</div>
      <div class="meta"><span>${esc(o.cliente_razon_social)}</span><span>${dinero(o.total_precio, o.moneda)}</span></div>
    </li>`).join('');
  ul.querySelectorAll('li[data-id]').forEach(li => li.addEventListener('click', () => {
    const o = ofertas.find(x => x.id === li.dataset.id);
    if(o) seleccionarOferta(o);
  }));
}

function seleccionarOferta(o, recarga){
  if(!recarga && partidasSucias && actual && actual.id !== o.id
     && !confirm('Hay cambios en las partidas sin guardar. ¿Descartarlos?')) return;
  actual = o;
  partidasEdit = (o.partidas || []).map(p => Object.assign({}, p));
  partidasSucias = false;
  pintarLista();
  pintarDetalle();
}

// ---------------------------------------------------------------- nueva oferta
function aplicarClienteEnForma(cli){
  if(!cli) return;
  const razon = $('n-razon'), rif = $('n-rif'), tipo = $('n-tipo');
  if(razon) razon.value = cli.razon_social || '';
  if(rif) rif.value = cli.rif || '';
  if(tipo && cli.tipo) tipo.value = cli.tipo;
}

function inscribirClienteDesdeOferta(){
  if(!window.PlataformaCotizacion || !puedeEscribir()) return;
  const titulo = ($('n-titulo') && $('n-titulo').value) || '';
  window.PlataformaCotizacion.mostrarVista('clientes', {
    abrirNuevo: true,
    alCrear(cli){
      window.PlataformaCotizacion.mostrarVista('ofertas');
      formNueva({titulo, cliente: cli});
    },
    alCancelar(){
      window.PlataformaCotizacion.mostrarVista('ofertas');
      formNueva({titulo});
    },
  });
}

function cargarOpcionesCliente(sel, elegido){
  apiJson('/clientes').then(lista => {
    if(!sel) return;
    (lista || []).filter(c => c.activo !== false).forEach(c => {
      const o = document.createElement('option');
      o.value = c.id;
      o.textContent = c.razon_social + (c.rif ? ' · ' + c.rif : '');
      o.dataset.razon = c.razon_social;
      o.dataset.rif = c.rif || '';
      o.dataset.tipo = c.tipo || 'directo';
      if(elegido && elegido.id === c.id) o.selected = true;
      sel.appendChild(o);
    });
    if(elegido) aplicarClienteEnForma(elegido);
    sel.addEventListener('change', () => {
      if(sel.value === '__nuevo__'){
        sel.value = elegido && elegido.id || '';
        inscribirClienteDesdeOferta();
        return;
      }
      const opt = sel.selectedOptions[0];
      if(!opt || !opt.value) return;
      aplicarClienteEnForma({
        razon_social: opt.dataset.razon,
        rif: opt.dataset.rif,
        tipo: opt.dataset.tipo,
      });
    });
  }).catch(() => {});
}

function formNueva(pref){
  pref = pref || {};
  if(partidasSucias && !confirm('Hay cambios en las partidas sin guardar. ¿Descartarlos?')) return;
  actual = null; partidasSucias = false; pintarLista();
  const cli = pref.cliente || null;
  $('detalle').innerHTML = `
    <div class="card">
      <div class="card-head"><h2>Nueva oferta</h2></div>
      <form id="f-nueva" class="form-grid">
        <label class="span2">Título de la oferta<input name="titulo" id="n-titulo" minlength="3" required value="${esc(pref.titulo || '')}"></label>
        <label class="span2">Cliente (05 Clientes)
          <select id="sel-cliente">
            <option value="">— Elige el cliente —</option>
            ${puedeEscribir() ? '<option value="__nuevo__">+ Inscribir uno nuevo (abre 05 Clientes)</option>' : ''}
          </select>
        </label>
        ${puedeEscribir() ? `<div class="acciones span2" style="margin-top:-6px">
          <button type="button" class="btn ghost sm" id="b-inscribir-cliente">+ Inscribir uno nuevo</button>
          <span class="small muted">Abre la opción 05 y, al guardar, vuelve aquí con el cliente inscrito.</span>
        </div>` : ''}
        <label>Cliente (razón social)<input name="cliente_razon_social" id="n-razon" minlength="2" required value="${esc(cli && cli.razon_social || '')}"></label>
        <label>RIF del cliente<input name="cliente_rif" id="n-rif" placeholder="J-00000000-0" value="${esc(cli && cli.rif || '')}"></label>
        <label>Tipo de cliente<select name="cliente_tipo" id="n-tipo"><option value="directo"${!cli || cli.tipo!=='aliado'?' selected':''}>Directo</option><option value="aliado"${cli && cli.tipo==='aliado'?' selected':''}>Aliado</option></select></label>
        <label>Origen<select name="origen"><option value="comercial">Comercial</option><option value="tecnica">Técnica (informe de campo)</option></select></label>
        <label>Moneda<input name="moneda" value="USD" maxlength="3" required></label>
        <label>Margen de ganancia (%)<input name="margen_pct" type="number" min="0" max="500" step="0.1" value="25"></label>
        <p class="small muted span2">${esc(avisoSbcInstancia())}</p>
        <div class="acciones span2"><button class="btn">Crear oferta</button>
          <span class="small muted">El código ORI-AAAA-MM-NNN se asigna al crearla. El SBC destino es el de Generales.</span></div>
      </form>
    </div>`;
  cargarOpcionesCliente($('sel-cliente'), cli);
  const bIns = $('b-inscribir-cliente');
  if(bIns) bIns.addEventListener('click', inscribirClienteDesdeOferta);
  $('f-nueva').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target), body = {};
    f.forEach((v, k) => { v = String(v).trim(); if(v) body[k] = v; });
    body.moneda = (body.moneda || 'USD').toUpperCase();
    if(body.margen_pct != null) body.margen_pct = Number(body.margen_pct);
    try{
      const o = await apiJson('/ofertas', {method: 'POST', body: JSON.stringify(body)});
      toast('Oferta ' + o.codigo + ' creada.');
      $('f-estado').value = '';
      await cargarLista(o.id);
    }catch(e){ toast(e.message, true); }
  });
}

// ---------------------------------------------------------------- detalle
function pintarDetalle(){
  const o = actual;
  if(!o){ $('detalle').innerHTML = '<div class="card vacio">Selecciona una oferta o crea una nueva.</div>'; return; }
  const escribir = puedeEscribir();
  const cerrada = CERRADOS.includes(o.estado);
  $('detalle').innerHTML = [
    tarjetaEncabezado(o, escribir),
    o.estado === 'ganada' ? tarjetaTraspaso(o, escribir) : '',
    tarjetaDatos(o, escribir, cerrada),
    tarjetaModalidad(o, escribir && !cerrada),
    tarjetaAnexos(o, escribir && !cerrada),
    tarjetaPartidas(o, escribir && !cerrada),
    '<div class="card"><div class="card-head"><h2>Bitácora de la oferta</h2></div><ul class="eventos" id="eventos"><li class="muted">Cargando…</li></ul></div>',
  ].join('');
  enlazarEncabezado(o);
  enlazarDatos(o, cerrada);
  enlazarModalidad(o);
  enlazarAnexos(o, escribir && !cerrada);
  enlazarPartidas();
  const br = $('b-reporte-oferta');
  if(br) br.addEventListener('click', () => abrirHtml('/ofertas/' + o.id + '/reporte.html'));
  if(o.estado === 'ganada') enlazarTraspaso(o);
  cargarEventos(o);
}

function tarjetaEncabezado(o, escribir){
  const botones = escribir ? (TRANSICIONES[o.estado] || []).map(e =>
    `<button class="btn sm ${e === 'ganada' ? 'naranja' : (e === 'perdida' || e === 'anulada') ? 'peligro' : 'ghost'}" data-estado="${e}">
      ${e === 'ganada' ? 'Marcar ganada' : 'Pasar a ' + esc(ETQ_ESTADO[e]).toLowerCase()}</button>`).join('') : '';
  return `
    <div class="card">
      <div class="card-head">
        <div>
          <div class="acciones"><span class="mono" style="color:var(--morado);font-weight:700">${esc(o.codigo)}</span>
            <span class="estado ${esc(o.estado)}">${esc(ETQ_ESTADO[o.estado])}</span></div>
          <h2 style="margin-top:6px;color:var(--ink)">${esc(o.titulo)}</h2>
          <div class="small muted">${esc(o.cliente_razon_social)} · Analista: ${esc(o.analista_nombre || '—')}
            ${o.origen === 'tecnica' ? ' · Informe técnico' : ''} · Margen ${esc(o.margen_pct)}%</div>
        </div>
        <div style="text-align:right">
          <div class="small muted">Total sin IVA</div>
          <div style="font-size:20px;font-weight:700;color:var(--morado)">${dinero(o.total_precio, o.moneda)}</div>
        </div>
      </div>
      <div class="acciones">${botones}
        <button type="button" class="btn ghost sm" id="b-reporte-oferta">Imprimir oferta</button>
        ${escribir && o.estado === 'borrador' ? '<button type="button" class="btn peligro sm" id="b-eliminar-borrador">Eliminar borrador</button>' : ''}</div>
    </div>`;
}

function enlazarEncabezado(o){
  document.querySelectorAll('[data-estado]').forEach(b => b.addEventListener('click', async () => {
    const e = b.dataset.estado;
    if(partidasSucias){ toast('Guarda primero los cambios de las partidas.', true); return; }
    let msg = '¿Pasar la oferta ' + o.codigo + ' a «' + ETQ_ESTADO[e] + '»?';
    if(e === 'ganada') msg = '¿Marcar ' + o.codigo + ' como GANADA?\n\nLa oferta queda congelada (partidas, montos y modalidad) '
      + 'y se habilita el archivo de traspaso a Control de Proyecto.';
    if(e === 'perdida' || e === 'anulada') msg += '\n\nEs un estado final: no se puede deshacer.';
    if(!confirm(msg)) return;
    try{
      let seriales = [];
      if(e === 'ganada'){
        const req = await apiJson('/ofertas/' + o.id + '/seriales-requeridos');
        if(req.length){
          seriales = await pedirSerialesVenta(req);
          if(!seriales) return;
        }
      }
      actual = await apiJson('/ofertas/' + o.id + '/estado', {method: 'POST', body: JSON.stringify({estado: e, seriales})});
      toast(e === 'ganada' ? 'Oferta ganada. Ya puedes descargar el traspaso.' : 'Estado actualizado.');
      await cargarLista(actual.id);
    }catch(err){ toast(err.message, true); }
  }));
  const be = $('b-eliminar-borrador');
  if(be) be.addEventListener('click', async () => {
    if(!confirm('¿Eliminar el borrador ' + o.codigo + '?\n\nSe quitan también los PDF, audios y chats cargados. Esta acción no se puede deshacer.')) return;
    try{
      const res = await api('/ofertas/' + o.id, {method: 'DELETE'});
      if(!res.ok && res.status !== 204){
        const d = await res.json().catch(() => null);
        throw new Error(detalleError(d, res.status));
      }
      toast('Borrador ' + o.codigo + ' eliminado.');
      actual = null;
      await cargarLista();
      pintarDetalle();
    }catch(err){ toast(err.message, true); }
  });
}

function campo(nombre, etiqueta, valor, editable, extra){
  extra = extra || {};
  const ro = editable ? '' : ' readonly';
  if(extra.tipo === 'textarea') return `<label class="${extra.clase || ''}">${etiqueta}<textarea name="${nombre}"${ro}>${esc(valor)}</textarea></label>`;
  if(extra.opciones) return `<label class="${extra.clase || ''}">${etiqueta}<select name="${nombre}"${editable ? '' : ' disabled'}>`
    + extra.opciones.map(([v, t]) => `<option value="${v}" ${valor === v ? 'selected' : ''}>${t}</option>`).join('') + '</select></label>';
  return `<label class="${extra.clase || ''}">${etiqueta}<input name="${nombre}" value="${esc(valor)}"${ro}
    ${extra.tipo ? ' type="' + extra.tipo + '"' : ''}${extra.attrs || ''}></label>`;
}

function tarjetaDatos(o, escribir, cerrada){
  const ed = (n) => escribir && (!cerrada || EDITABLES_CERRADA.includes(n));
  return `
    <div class="card">
      <div class="card-head"><h2>Datos de la oferta</h2>
        ${escribir ? '<button class="btn sm" id="b-guardar-datos">Guardar datos</button>' : ''}</div>
      ${cerrada && escribir ? '<div class="aviso info small" style="margin-bottom:10px">Oferta cerrada: solo se pueden cambiar el contacto y las notas.</div>' : ''}
      <form id="f-datos" class="form-grid" onsubmit="return false">
        ${campo('titulo', 'Título', o.titulo, ed('titulo'), {clase: 'span2'})}
        ${campo('cliente_razon_social', 'Cliente (razón social)', o.cliente_razon_social, ed('cliente_razon_social'))}
        ${campo('cliente_rif', 'RIF del cliente', o.cliente_rif, ed('cliente_rif'), {attrs: ' placeholder="J-00000000-0"'})}
        ${campo('cliente_tipo', 'Tipo de cliente', o.cliente_tipo, ed('cliente_tipo'), {opciones: [['directo', 'Directo'], ['aliado', 'Aliado']]})}
        ${campo('cliente_contacto', 'Contacto del cliente', o.cliente_contacto, ed('cliente_contacto'))}
        ${campo('moneda', 'Moneda', o.moneda, ed('moneda'), {attrs: ' maxlength="3"'})}
        ${campo('iva_pct', 'IVA (%)', o.iva_pct, ed('iva_pct'), {tipo: 'number', attrs: ' min="0" max="100"'})}
        ${campo('margen_pct', 'Margen de ganancia (%)', o.margen_pct, ed('margen_pct'), {tipo: 'number', attrs: ' min="0" max="500" step="0.1"'})}
        ${campo('origen', 'Origen', o.origen || 'comercial', ed('origen'), {opciones: [['comercial', 'Comercial'], ['tecnica', 'Técnica (informe de campo)']]})}
        ${campo('semanas_totales', 'Plazo total (semanas)', o.semanas_totales, ed('semanas_totales'), {tipo: 'number', attrs: ' min="1" placeholder="se calcula de las partidas"'})}
        <p class="small muted span2">${esc(avisoSbcInstancia(o))}</p>
        ${campo('notas', 'Notas', o.notas, ed('notas'), {tipo: 'textarea', clase: 'span2'})}
      </form>
    </div>`;
}

function enlazarDatos(o, cerrada){
  const b = $('b-guardar-datos');
  if(!b) return;
  b.addEventListener('click', async () => {
    const f = new FormData($('f-datos')), body = {};
    f.forEach((v, k) => {
      if(cerrada && !EDITABLES_CERRADA.includes(k)) return;
      v = String(v).trim();
      const antes = o[k] == null ? '' : String(o[k]);
      if(v === antes) return;
      if(k === 'iva_pct' || k === 'semanas_totales') body[k] = v === '' ? null : parseInt(v, 10);
      else if(k === 'margen_pct') body[k] = v === '' ? null : Number(v);
      else if(k === 'moneda') body[k] = v.toUpperCase();
      else body[k] = v === '' ? null : v;
    });
    if(!Object.keys(body).length){ toast('No hay cambios que guardar.'); return; }
    try{
      actual = await apiJson('/ofertas/' + o.id, {method: 'PATCH', body: JSON.stringify(body)});
      toast('Datos guardados.');
      await cargarLista(actual.id);
    }catch(e){ toast(e.message, true); }
  });
}

function modalidadActual(o){
  if(o.modalidad === 'suministro') return 'suministro';
  if(o.modalidad === 'ejecucion') return o.facturacion || 'ejecucion';
  return '';
}

function tarjetaModalidad(o, editable){
  const sel = modalidadActual(o);
  return `
    <div class="card">
      <div class="card-head"><h2>Modalidad y facturación</h2></div>
      <p class="small muted" style="margin:0 0 10px">Define qué se crea en Control de Proyecto al ganar la oferta.
        ${sel === 'ejecucion' ? '<strong style="color:#8a4f00">Falta elegir la facturación (resumida o detallada).</strong>' : ''}</p>
      <div class="modalidades">
        ${MODALIDADES.map(m => `<button type="button" class="modalidad ${sel === m.id ? 'sel' : ''}" data-mod="${m.id}" ${editable ? '' : 'disabled'}>
          <strong>${m.titulo}</strong><span>${m.texto}</span></button>`).join('')}
      </div>
    </div>`;
}

function tarjetaAnexos(o, editable){
  return `
    <div class="card" id="card-anexos">
      <div class="card-head"><h2>Ofertas de proveedores e informes</h2></div>
      <p class="small muted" style="margin:0 0 10px">Carga PDF, Word, Excel, PowerPoint, audio (nota de voz / visita) o chat de WhatsApp (.txt o .zip).
        Gemini analiza las fuentes, redacta el informe técnico y arma la oferta con el margen.
        Si OnlyOffice está en Generales, «Abrir» edita el archivo sin salir.</p>
      ${editable ? `<div class="acciones" style="margin-bottom:10px">
        <select id="anexo-tipo">${TIPOS_ANEXO.map(([v,t]) => `<option value="${v}">${t}</option>`).join('')}</select>
        <input type="file" id="anexo-file" accept="${ACCEPT_FUENTES}" multiple>
        <button type="button" class="btn ghost sm" id="b-anexo-subir">Cargar</button>
        <button type="button" class="btn naranja sm" id="b-analizar-fuentes">Analizar y generar informe + oferta</button>
        <button type="button" class="btn ghost sm hidden" id="b-oo-word" data-oo-nuevo="word">+ Word</button>
        <button type="button" class="btn ghost sm hidden" id="b-oo-cell" data-oo-nuevo="cell">+ Excel</button>
        <button type="button" class="btn ghost sm hidden" id="b-oo-slide" data-oo-nuevo="slide">+ PowerPoint</button>
      </div>` : ''}
      <ul class="eventos" id="lista-anexos"><li class="muted">Cargando anexos…</li></ul>
    </div>`;
}

async function pintarAnexos(o){
  const ul = $('lista-anexos');
  if(!ul) return;
  try{
    const filas = await apiJson('/ofertas/' + o.id + '/anexos');
    if(!filas.length){ ul.innerHTML = '<li class="muted">Sin fuentes cargadas.</li>'; return; }
    const etq = Object.fromEntries(TIPOS_ANEXO);
    ul.innerHTML = filas.map(a => {
      const n = ((a.extraccion && a.extraccion.partidas) || []).length;
      const motor = a.extraccion && a.extraccion.motor ? a.extraccion.motor : 'sin OCR';
      const ooBtn = botonOnlyOffice('anexo', a.id, a.nombre);
      return `<li>
        <div><div class="acc">${esc(etq[a.tipo] || a.tipo)}</div>
          <div class="small muted">${esc(a.nombre)} · ${esc(motor)} · ${n} partidas</div></div>
        <div class="acciones">
          ${ooBtn}
          <button type="button" class="btn ghost sm" data-ver="${esc(a.id)}" data-nombre="${esc(a.nombre)}">Descargar</button>
          <button type="button" class="btn ghost sm" data-ocr="${esc(a.id)}">Analizar</button>
        </div>
      </li>`;
    }).join('');
    ul.querySelectorAll('[data-oo-origen]').forEach(b => b.addEventListener('click', () => {
      abrirOnlyOffice(b.dataset.ooOrigen, b.dataset.ooId, b.dataset.ooNombre);
    }));
    ul.querySelectorAll('[data-ver]').forEach(b => b.addEventListener('click', async () => {
      try{
        const res = await api('/anexos/' + b.dataset.ver + '/archivo');
        if(!res.ok) throw new Error('No se pudo abrir el archivo.');
        const blob = await res.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = b.dataset.nombre || 'anexo';
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(a.href), 2000);
      }catch(e){ toast(e.message, true); }
    }));
    ul.querySelectorAll('[data-ocr]').forEach(b => b.addEventListener('click', async () => {
      try{
        await apiJson('/anexos/' + b.dataset.ocr + '/ocr', {method: 'POST'});
        toast('Análisis actualizado.');
        pintarAnexos(o);
      }catch(e){ toast(e.message, true); }
    }));
  }catch(e){ ul.innerHTML = '<li class="muted">' + esc(e.message) + '</li>'; }
}

function enlazarAnexos(o, editable){
  pintarAnexos(o);
  if(!editable) return;
  ['b-oo-word','b-oo-cell','b-oo-slide'].forEach(id => {
    const b = $(id);
    if(b) b.classList.toggle('hidden', !onlyOfficeActivo());
  });
  document.querySelectorAll('#card-anexos [data-oo-nuevo]').forEach(b => {
    b.addEventListener('click', async () => {
      try{
        const r = await apiJson('/onlyoffice/nuevo', {
          method: 'POST',
          body: JSON.stringify({oferta_id: o.id, tipo: b.dataset.ooNuevo}),
        });
        toast('Documento creado.');
        await pintarAnexos(o);
        if(r && r.id) abrirOnlyOffice('anexo', r.id, r.nombre);
      }catch(e){ toast(e.message, true); }
    });
  });
  const inp = $('anexo-file');
  if(inp) inp.addEventListener('change', () => {
    const f = inp.files && inp.files[0];
    const sel = $('anexo-tipo');
    if(f && sel && (sel.value === 'otro' || sel.value === 'oferta_proveedor')) sel.value = inferirTipoAnexo(f, sel.value);
  });
  const bs = $('b-anexo-subir');
  if(bs) bs.addEventListener('click', async () => {
    const files = $('anexo-file') && $('anexo-file').files;
    if(!files || !files.length){ toast('Elige PDF, audio o chat de WhatsApp.', true); return; }
    bs.disabled = true;
    try{
      for(const file of files){
        const tipo = inferirTipoAnexo(file, $('anexo-tipo').value);
        await apiUpload('/ofertas/' + o.id + '/anexos', file, {tipo, ocr: 'true'});
      }
      toast('Fuentes cargadas. Puedes analizarlas juntas.');
      $('anexo-file').value = '';
      pintarAnexos(o);
    }catch(e){ toast(e.message, true); }
    finally{ bs.disabled = false; }
  });
  const bg = $('b-analizar-fuentes');
  if(bg) bg.addEventListener('click', async () => {
    const files = $('anexo-file') && $('anexo-file').files;
    bg.disabled = true;
    try{
      let r;
      if(files && files.length){
        r = await apiUploadMany('/analisis', files, {
          tipo: inferirTipoAnexo(files[0], $('anexo-tipo').value),
          margen_pct: o.margen_pct, oferta_id: o.id,
          crear_informe: 'true', crear_oferta: 'true',
        });
      }else{
        r = await apiJson('/ofertas/' + o.id + '/analizar-fuentes', {method: 'POST',
          body: JSON.stringify({margen_pct: o.margen_pct, crear_informe: true, reemplazar_partidas: true})});
      }
      toast('Informe y oferta generados' + (r.oferta ? ' · ' + r.oferta.codigo : '') + '.');
      if(r.oferta) await cargarLista(r.oferta.id);
      else pintarAnexos(o);
    }catch(e){ toast(e.message, true); }
    finally{ bg.disabled = false; }
  });
}

async function abrirHtml(path){
  try{
    const res = await api(path);
    if(!res.ok){ const d = await res.json().catch(() => null); throw new Error(detalleError(d, res.status)); }
    const html = await res.text();
    const w = window.open('', '_blank');
    if(!w){ toast('Permite ventanas emergentes para ver el reporte.', true); return; }
    w.document.write(html);
    w.document.close();
  }catch(e){ toast(e.message, true); }
}

function enlazarModalidad(o){
  document.querySelectorAll('[data-mod]').forEach(b => b.addEventListener('click', async () => {
    const m = MODALIDADES.find(x => x.id === b.dataset.mod);
    try{
      actual = await apiJson('/ofertas/' + o.id, {method: 'PATCH',
        body: JSON.stringify({modalidad: m.modalidad, facturacion: m.facturacion})});
      const sucias = partidasSucias, edit = partidasEdit;
      await cargarLista(actual.id);
      if(sucias){ partidasEdit = edit; partidasSucias = true; pintarDetalle(); }
    }catch(e){ toast(e.message, true); }
  }));
}

// ---------------------------------------------------------------- partidas
let buscaProdT = null;
function aplicarProductoEnPartida(i, prod){
  const p = partidasEdit[i];
  if(!p || !prod) return;
  p._eligeCatalogo = true;
  p.producto_id = prod.id;
  p.descripcion = prod.nombre;
  p.unidad = prod.unidad || p.unidad || 'UND';
  if(prod.disciplina) p.disciplina = prod.disciplina;
  if(prod.precio_ref != null && prod.precio_ref !== '') p.precio_unitario = prod.precio_ref;
  if(prod.tiempo_entrega_semanas && !p.duracion_semanas) p.duracion_semanas = prod.tiempo_entrega_semanas;
  p.requiere_serial = !!prod.requiere_serial;
  p.garantia_semanas = prod.garantia_semanas;
  marcarSucias();
  pintarPartidas();
}

function buscarProductoPartida(el, i){
  const box = document.querySelector('[data-sug="'+i+'"]');
  const q = (el.value || '').trim();
  if(box) box.classList.add('hidden');
  clearTimeout(buscaProdT);
  if(q.length < 2) return;
  buscaProdT = setTimeout(async () => {
    try{
      const lista = await apiJson('/productos?q=' + encodeURIComponent(q));
      if(!box) return;
      if(!lista.length){
        box.innerHTML = `<button type="button" class="sug-item" data-nuevo="1">+ Inscribir «${esc(q)}» en 06</button>`;
        box.classList.remove('hidden');
        box.querySelector('[data-nuevo]').addEventListener('click', () => inscribirProductoDesdePartida(q));
        return;
      }
      box.innerHTML = lista.slice(0, 8).map(p =>
        `<button type="button" class="sug-item" data-pid="${esc(p.id)}"><strong>${esc(p.codigo)}</strong> ${esc(p.nombre)}
          <span class="muted">${p.tipo==='servicio'?'Servicio':'Producto'}${p.requiere_serial?' · serial':''}</span></button>`
      ).join('') + `<button type="button" class="sug-item" data-nuevo="1">+ Inscribir uno nuevo (06)</button>`;
      box.classList.remove('hidden');
      box.querySelectorAll('[data-pid]').forEach(b => b.addEventListener('click', () => {
        const prod = lista.find(x => x.id === b.dataset.pid);
        aplicarProductoEnPartida(i, prod);
      }));
      box.querySelector('[data-nuevo]').addEventListener('click', () => inscribirProductoDesdePartida(q));
    }catch(e){}
  }, 220);
}

function inscribirProductoDesdePartida(nombreHint){
  if(!window.PlataformaCotizacion || !puedeEscribir() || !actual) return;
  const oid = actual.id;
  window.PlataformaCotizacion.mostrarVista('productos', {
    abrirNuevo: true,
    alCrear(prod){
      window.PlataformaCotizacion.mostrarVista('ofertas');
      cargarLista(oid).then(() => {
        const ult = partidasEdit[partidasEdit.length - 1];
        const disc = ult ? ult.disciplina : (prod.disciplina || 'GENERAL');
        const n = partidasEdit.filter(p => (p.disciplina || '').trim().toUpperCase() === String(disc).trim().toUpperCase()).length + 1;
        partidasEdit.push({disciplina: disc, item: String(n), descripcion: '', unidad: 'UND', cantidad: 1,
          precio_unitario: 0, semana_inicio: null, duracion_semanas: null, producto_id: null});
        aplicarProductoEnPartida(partidasEdit.length - 1, prod);
      });
    },
    alCancelar(){
      window.PlataformaCotizacion.mostrarVista('ofertas');
      cargarLista(oid);
    },
  });
  const nom = $('f-mod') && $('f-mod').elements.nombre;
  if(nom && typeof nombreHint === 'string' && nombreHint) nom.value = nombreHint;
}

function pedirSerialesVenta(partidas){
  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.className = 'overlay';
    overlay.innerHTML = `<div class="login-box" style="max-width:560px;text-align:left">
      <h1>Seriales de la venta</h1>
      <p class="small muted">Cada unidad de producto que exige serial debe tener su número. La garantía del catálogo queda en la ficha.</p>
      ${partidas.map(p => `<div class="card" style="margin:10px 0">
        <strong>${esc(p.descripcion)}</strong>
        <div class="small muted">${p.n_seriales} unidad(es)${p.garantia_semanas!=null?' · garantía '+p.garantia_semanas+' sem.':''}</div>
        ${Array.from({length: p.n_seriales}, (_, i) =>
          `<label>Serial ${i+1}<input data-pid="${esc(p.partida_id)}" data-n="${i}" required></label>`).join('')}
      </div>`).join('')}
      <div class="acciones"><button type="button" class="btn" id="b-ser-ok">Guardar y marcar ganada</button>
        <button type="button" class="btn ghost" id="b-ser-cancel">Cancelar</button></div>
    </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector('#b-ser-cancel').addEventListener('click', () => { overlay.remove(); resolve(null); });
    overlay.querySelector('#b-ser-ok').addEventListener('click', () => {
      const seriales = [];
      let ok = true;
      overlay.querySelectorAll('input[data-pid]').forEach(inp => {
        const v = inp.value.trim();
        if(!v){ ok = false; inp.focus(); }
        seriales.push({partida_id: inp.dataset.pid, serial: v});
      });
      if(!ok){ toast('Completa todos los seriales.', true); return; }
      overlay.remove();
      resolve(seriales);
    });
  });
}

function tarjetaPartidas(o, editable){
  return `
    <div class="card">
      <div class="card-head"><h2>Partidas</h2>
        ${editable ? `<div class="acciones"><button class="btn ghost sm" id="b-add">+ Partida</button>
          <button class="btn ghost sm" id="b-add-prod">+ Del catálogo (06)</button>
          <button class="btn sm" id="b-guardar-partidas" disabled>Guardar partidas</button></div>` : ''}</div>
      <div class="tabla-wrap"><table>
        <thead><tr>
          <th class="col-disc">Disciplina</th><th class="col-item">Ítem</th><th>Descripción (busca en 06)</th><th class="col-und">Unidad</th>
          <th class="num col-n">Cantidad</th><th class="num col-n">P. unitario</th><th class="num col-n">Total</th>
          <th class="num col-s" title="Semana de inicio">Sem. ini.</th><th class="num col-s" title="Duración en semanas">Duración</th>
          ${editable ? '<th></th>' : ''}
        </tr></thead>
        <tbody id="tb-partidas"></tbody>
        <tfoot id="tf-partidas"></tfoot>
      </table></div>
      <p class="small muted" style="margin:8px 0 0">Escribe en la descripción para buscar el catálogo. Un producto con serial pedirá el número de serie al marcar la oferta ganada. La disciplina se convierte en frente de valuación en Control de Proyecto.</p>
    </div>`;
}

function pintarPartidas(){
  const tb = $('tb-partidas');
  if(!tb) return;
  const editable = !!$('b-guardar-partidas');
  const moneda = actual.moneda;
  if(!partidasEdit.length){
    tb.innerHTML = `<tr><td colspan="${editable ? 10 : 9}" class="vacio">Sin partidas.${editable ? ' Agrega la primera con «+ Partida».' : ''}</td></tr>`;
    return;
  }
  const ro = editable ? '' : ' readonly';
  const inp = (i, k, v, extra) => `<input data-i="${i}" data-k="${k}" value="${esc(v == null ? '' : v)}"${ro}${extra || ''}>`;
  const filas = [];
  partidasEdit.forEach((p, i) => {
    const tot = r2((Number(p.cantidad) || 0) * (Number(p.precio_unitario) || 0));
    filas.push(`<tr>
      <td>${inp(i, 'disciplina', p.disciplina)}</td>
      <td>${inp(i, 'item', p.item)}</td>
      <td class="prod-cell"><input class="desc" data-i="${i}" data-k="descripcion" value="${esc(p.descripcion)}"${ro} autocomplete="off">
        <div class="sug-prod hidden" data-sug="${i}"></div>
        ${p.producto_id ? `<div class="small muted">${p.requiere_serial ? 'Catálogo · pide serial' : 'Del catálogo 06'}${p.garantia_semanas!=null?' · garantía '+p.garantia_semanas+' sem.':''}</div>` : ''}</td>
      <td>${inp(i, 'unidad', p.unidad)}</td>
      <td class="num">${inp(i, 'cantidad', p.cantidad, ' type="number" step="any" min="0" style="text-align:right"')}</td>
      <td class="num">${inp(i, 'precio_unitario', p.precio_unitario, ' type="number" step="0.01" min="0" style="text-align:right"')}</td>
      <td class="num" data-total="${i}">${dinero(tot)}</td>
      <td class="num">${inp(i, 'semana_inicio', p.semana_inicio, ' type="number" min="1" style="text-align:right"')}</td>
      <td class="num">${inp(i, 'duracion_semanas', p.duracion_semanas, ' type="number" min="1" style="text-align:right"')}</td>
      ${editable ? `<td><button class="btn peligro sm" data-del="${i}" title="Quitar partida">✕</button></td>` : ''}
    </tr>`);
  });
  tb.innerHTML = filas.join('');
  pintarTotales();
}

// Subtotales por disciplina y totales en su propio <tfoot>: se actualizan
// mientras se escribe sin redibujar las filas (no se pierde el foco).
function pintarTotales(){
  const tf = $('tf-partidas');
  if(!tf) return;
  if(!partidasEdit.length){ tf.innerHTML = ''; return; }
  const editable = !!$('b-guardar-partidas');
  const moneda = actual.moneda;
  const porDisc = {};
  partidasEdit.forEach(p => {
    const d = (p.disciplina || 'GENERAL').trim().toUpperCase() || 'GENERAL';
    porDisc[d] = r2((porDisc[d] || 0) + (Number(p.cantidad) || 0) * (Number(p.precio_unitario) || 0));
  });
  const total = r2(Object.values(porDisc).reduce((a, b) => a + b, 0));
  const iva = r2(total * (Number(actual.iva_pct) || 0) / 100);
  const span = 6, cola = editable ? 3 : 2;
  const fila = (cls, etq, monto) =>
    `<tr class="${cls}"><td colspan="${span}">${etq}</td><td class="num">${monto}</td><td colspan="${cola}"></td></tr>`;
  tf.innerHTML = Object.keys(porDisc).map(d => fila('subtotal', 'Subtotal ' + esc(d), dinero(porDisc[d]))).join('')
    + fila('total', 'Total sin IVA', dinero(total, moneda))
    + fila('total', 'IVA ' + esc(actual.iva_pct) + '%', dinero(iva, moneda))
    + fila('total', 'Total general', dinero(total + iva, moneda));
}

function marcarSucias(){
  partidasSucias = true;
  const b = $('b-guardar-partidas');
  if(b){ b.disabled = false; b.textContent = 'Guardar partidas •'; }
}

function enlazarPartidas(){
  pintarPartidas();
  const tb = $('tb-partidas');
  if(!tb || !$('b-guardar-partidas')) return;
  if(partidasSucias) marcarSucias();
  tb.addEventListener('input', (ev) => {
    const el = ev.target;
    if(!el.dataset || el.dataset.i == null) return;
    const p = partidasEdit[+el.dataset.i], k = el.dataset.k;
    const num = ['cantidad', 'precio_unitario'].includes(k), ent = ['semana_inicio', 'duracion_semanas'].includes(k);
    p[k] = num ? (el.value === '' ? '' : Number(el.value)) : ent ? (el.value === '' ? null : parseInt(el.value, 10)) : el.value;
    if(k === 'descripcion' && !p._eligeCatalogo) p.producto_id = null;
    p._eligeCatalogo = false;
    marcarSucias();
    if(k === 'descripcion') buscarProductoPartida(el, +el.dataset.i);
    if(num){
      const td = tb.querySelector(`[data-total="${el.dataset.i}"]`);
      if(td) td.textContent = dinero(r2((Number(p.cantidad) || 0) * (Number(p.precio_unitario) || 0)));
    }
    if(num || k === 'disciplina') pintarTotales();
  });
  tb.addEventListener('click', (ev) => {
    const b = ev.target.closest('[data-del]');
    if(!b) return;
    partidasEdit.splice(+b.dataset.del, 1);
    marcarSucias();
    pintarPartidas();
  });
  $('b-add').addEventListener('click', () => {
    const ult = partidasEdit[partidasEdit.length - 1];
    const disc = ult ? ult.disciplina : 'GENERAL';
    const n = partidasEdit.filter(p => (p.disciplina || '').trim().toUpperCase() === String(disc).trim().toUpperCase()).length + 1;
    partidasEdit.push({disciplina: disc, item: String(n), descripcion: '', unidad: 'UND', cantidad: 1, precio_unitario: 0,
      semana_inicio: null, duracion_semanas: null, producto_id: null});
    marcarSucias();
    pintarPartidas();
    const ultimos = tb.querySelectorAll('input.desc');
    if(ultimos.length) ultimos[ultimos.length - 1].focus();
  });
  const bProd = $('b-add-prod');
  if(bProd) bProd.addEventListener('click', inscribirProductoDesdePartida);
  $('b-guardar-partidas').addEventListener('click', async () => {
    const vacias = partidasEdit.findIndex(p => !String(p.item || '').trim() || !String(p.descripcion || '').trim());
    if(vacias >= 0){ toast('La partida ' + (vacias + 1) + ' necesita ítem y descripción.', true); return; }
    const body = partidasEdit.map(p => ({
      disciplina: String(p.disciplina || 'GENERAL').trim() || 'GENERAL',
      item: String(p.item).trim(), descripcion: String(p.descripcion).trim(),
      unidad: String(p.unidad || 'UND').trim() || 'UND',
      cantidad: Number(p.cantidad) || 0, precio_unitario: Number(p.precio_unitario) || 0,
      semana_inicio: p.semana_inicio || null, duracion_semanas: p.duracion_semanas || null,
      producto_id: p.producto_id || null,
    }));
    try{
      actual = await apiJson('/ofertas/' + actual.id + '/partidas', {method: 'PUT', body: JSON.stringify(body)});
      partidasSucias = false;
      toast('Partidas guardadas.');
      await cargarLista(actual.id);
    }catch(e){ toast(e.message, true); }
  });
}

// ---------------------------------------------------------------- traspaso
// Estados del buzón del MCP (plataforma/traspaso_mcp_ops.py en Control de Proyecto).
const ETQ_MCP = {
  pendiente: ['En el MCP', 'Esperando el próximo latido del SBC destino.', 'info'],
  entregado: ['Entregado al SBC', 'El SBC la bajó; aún no confirma que está en su bandeja.', 'info'],
  recibido: ['En la bandeja del SBC', 'Espera que un analista cree el contrato con esta oferta.', 'warn'],
  aceptado: ['Aceptada en el SBC', 'El contrato quedó creado con la oferta importada.', 'ok'],
  rechazado: ['Rechazada por el SBC', '', 'bad'],
  error: ['Error en el SBC', '', 'bad'],
  error_envio: ['No se pudo enviar', '', 'bad'],
};

function tarjetaTraspaso(o, escribir){
  const mod = MODALIDADES.find(m => m.id === modalidadActual(o));
  const vinculada = !!o.proyecto_cp_id;
  const descargado = (o.traspasos_generados || 0) > 0;
  const chip = vinculada ? '<span class="chip" style="background:var(--good-tint);color:var(--good)">Vinculada</span>' : '';
  const manual = pasosManuales(o, escribir, mod, vinculada, descargado);
  if(!mcpEstado.configurado){
    return `<div class="card" style="border-color:var(--naranja)">
      <div class="card-head"><h2>Traspaso a Control de Proyecto</h2>${chip}</div>
      <div class="aviso warn small" style="margin-bottom:12px">El MCP no está configurado en esta instancia: el traspaso se hace descargando el archivo.</div>
      ${manual}</div>`;
  }
  const est = ETQ_MCP[o.mcp_estado] || null;
  const sbc = sbcInstancia(o);
  const nomDestino = sbc.nombre;
  const enviado = !!o.mcp_traspaso_id;
  const recibido = ['recibido', 'aceptado', 'rechazado'].includes(o.mcp_estado);
  return `
    <div class="card" style="border-color:var(--naranja)">
      <div class="card-head"><h2>Traspaso a Control de Proyecto por el MCP</h2>${chip}</div>
      ${!mcpEstado.ok ? `<div class="aviso warn small" style="margin-bottom:12px">Sin conexión con el MCP: ${esc(mcpEstado.detalle || '')}</div>` : ''}
      <ol class="pasos">
        <li class="${enviado && o.mcp_estado !== 'error_envio' ? 'hecho' : ''}"><div>
          <h3>Enviar al SBC${nomDestino ? ' «' + esc(nomDestino) + '»' : ''}</h3>
          ${!sbc.id ? '<p class="small" style="margin:0 0 8px">El administrador debe fijar el <strong>SBC destino</strong> en <strong>14 Generales</strong>.</p>' : ''}
          ${est ? `<div class="aviso ${est[2]} small" style="margin-bottom:8px"><strong>${esc(est[0])}</strong>${o.mcp_version > 1 ? ' · versión ' + esc(o.mcp_version) : ''} · ${fecha(o.mcp_actualizado_en)}
             ${est[1] ? '<br>' + esc(est[1]) : ''}${o.mcp_detalle ? '<br>' + esc(o.mcp_detalle) : ''}</div>` : ''}
          <div class="acciones">
            ${escribir && sbc.id && o.mcp_estado !== 'aceptado'
              ? `<button class="btn naranja sm" id="b-mcp-enviar">${enviado ? 'Reenviar por el MCP' : 'Enviar por el MCP'}</button>` : ''}
            ${enviado && o.mcp_estado !== 'aceptado' && o.mcp_estado !== 'rechazado' && escribir
              ? '<button class="btn ghost sm" id="b-mcp-sinc">Consultar acuse</button>' : ''}
          </div>
        </div></li>
        <li class="${recibido ? 'hecho' : ''}"><div>
          <h3>Recepción en el SBC</h3>
          <p class="small" style="margin:0">En el SBC, pestaña <strong>Contrato (04) → Ofertas recibidas del MCP</strong>: el analista pulsa
            <strong>Crear contrato</strong>, completa número, tipo y monto del documento firmado y guarda. La oferta se importa sola.</p>
        </div></li>
        <li class="${vinculada ? 'hecho' : ''}"><div>
          <h3>Vinculación</h3>
          ${vinculada ? `<div class="aviso ok small">Proyecto <strong class="mono">${esc(o.proyecto_cp_id)}</strong>
             ${o.contrato_cp_numero ? '· contrato <strong class="mono">' + esc(o.contrato_cp_numero) + '</strong>' : ''} · ${fecha(o.vinculado_en)}
             ${o.vinculado_por === 'MCP' ? ' · confirmado por el MCP' : ''}</div>`
            : '<p class="small muted" style="margin:0">Se completa sola cuando el SBC acepta la oferta.</p>'}
        </div></li>
      </ol>
      <details style="margin-top:14px">
        <summary class="small" style="cursor:pointer;color:var(--morado);font-weight:600">Contingencia: sin conexión con el MCP (descarga manual)</summary>
        <div style="margin-top:12px">${manual}</div>
      </details>
    </div>`;
}

function pasosManuales(o, escribir, mod, vinculada, descargado){
  return `
      <ol class="pasos">
        <li class="${descargado ? 'hecho' : ''}"><div>
          <h3>Descargar el archivo</h3>
          <p class="small" style="margin:0 0 8px">Formato FOR-COT-002: el respaldo de oferta que Control de Proyecto ya sabe importar.
            ${mod ? 'Modalidad: <strong>' + esc(mod.titulo) + '</strong>.' : ''}</p>
          ${escribir ? '<button class="btn naranja sm" id="b-descargar">Descargar traspaso</button>' : '<span class="small muted">Tu rol no descarga traspasos.</span>'}
          ${descargado ? `<span class="small muted" style="margin-left:8px">Descargado ${esc(o.traspasos_generados)} ${o.traspasos_generados === 1 ? 'vez' : 'veces'}.</span>` : ''}
        </div></li>
        <li class="${vinculada ? 'hecho' : ''}"><div>
          <h3>Importarlo en Control de Proyecto</h3>
          <ol>
            <li>Entra al <strong>SBC</strong> que operará el contrato${o.sede_destino ? ' (<strong>' + esc(o.sede_destino) + '</strong>)' : ''}. El MASTER no opera obra.</li>
            <li>En <strong>Clientes (12)</strong> verifica que exista <strong>${esc(o.cliente_razon_social)}</strong> con RIF <strong class="mono">${esc(o.cliente_rif || '—')}</strong>.</li>
            <li>Elige o crea el proyecto y pulsa <strong>Nuevo contrato</strong>:
              <strong>Empresa del contrato</strong> = ese cliente;
              <strong>Tipo de contrato</strong> = ${mod && mod.modalidad === 'suministro'
                ? '<em>Orden de compra (obra / valuación)</em>'
                : '<em>Contrato</em> → clase <em>Contrato de obra (valuación)</em>, o <em>Orden de compra (obra / valuación)</em> si el cliente emitió una OC'};
              <strong>Monto del contrato</strong> = el del documento firmado (referencia de la oferta: ${dinero(r2((o.total_precio || 0) * (1 + (o.iva_pct || 0) / 100)), o.moneda)} con IVA).</li>
            <li>En <strong>Importar respaldo de oferta → Archivo de oferta</strong> sube <span class="mono">${esc(o.codigo)}_traspaso_control_proyecto.json</span> y pulsa <strong>Crear contrato</strong>. En Valuaciones aparecerán los frentes de la oferta.</li>
          </ol>
        </div></li>
        <li class="${vinculada ? 'hecho' : ''}"><div>
          <h3>Registrar el resultado aquí</h3>
          ${vinculada ? `<div class="aviso ok small" style="margin-bottom:8px">Proyecto <strong class="mono">${esc(o.proyecto_cp_id)}</strong>
             ${o.contrato_cp_numero ? '· contrato <strong class="mono">' + esc(o.contrato_cp_numero) + '</strong>' : ''} · ${fecha(o.vinculado_en)}</div>` : ''}
          ${escribir ? `
          <form id="f-vinc" class="form-grid">
            <label>ID del proyecto en Control de Proyecto<input name="proyecto_cp_id" value="${esc(o.proyecto_cp_id)}" required></label>
            <label>N.º de contrato (opcional)<input name="contrato_cp_numero" value="${esc(o.contrato_cp_numero)}"></label>
            <div class="acciones span2">
              <button class="btn sm">${vinculada ? 'Actualizar vinculación' : 'Registrar vinculación'}</button>
              <button type="button" class="btn peligro sm" id="b-fallida">La importación falló</button>
            </div>
          </form>` : ''}
        </div></li>
      </ol>`;
}

function nombreDeDisposition(h, defecto){
  const m = /filename="?([^";]+)"?/i.exec(h || '');
  return m ? m[1] : defecto;
}

function enlazarTraspaso(o){
  const be = $('b-mcp-enviar');
  if(be) be.addEventListener('click', async () => {
    be.disabled = true;
    try{
      actual = await apiJson('/ofertas/' + o.id + '/mcp/enviar', {method: 'POST'});
      toast('Oferta enviada al MCP.');
    }catch(e){ toast(e.message, true); }
    await cargarLista(o.id);
  });
  const bs = $('b-mcp-sinc');
  if(bs) bs.addEventListener('click', async () => {
    bs.disabled = true;
    try{
      const r = await apiJson('/mcp/sincronizar', {method: 'POST'});
      toast(r.cambios ? 'Hay novedades del SBC.' : 'Sin cambios todavía.');
    }catch(e){ toast(e.message, true); }
    await cargarLista(o.id);
  });
  const bd = $('b-descargar');
  if(bd) bd.addEventListener('click', async () => {
    try{
      const res = await api('/ofertas/' + o.id + '/traspaso');
      if(!res.ok){ const d = await res.json().catch(() => null); throw new Error(detalleError(d, res.status)); }
      const blob = await res.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = nombreDeDisposition(res.headers.get('Content-Disposition'), o.codigo + '_traspaso_control_proyecto.json');
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
      toast('Archivo descargado. Súbelo en Control de Proyecto.');
      await cargarLista(o.id);
    }catch(e){ toast(e.message, true); }
  });
  const fv = $('f-vinc');
  if(fv) fv.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const f = new FormData(fv);
    const body = {proyecto_cp_id: String(f.get('proyecto_cp_id')).trim(),
                  contrato_cp_numero: String(f.get('contrato_cp_numero') || '').trim() || null};
    try{
      actual = await apiJson('/ofertas/' + o.id + '/vinculacion', {method: 'POST', body: JSON.stringify(body)});
      toast('Vinculación registrada.');
      await cargarLista(actual.id);
    }catch(e){ toast(e.message, true); }
  });
  const bf = $('b-fallida');
  if(bf) bf.addEventListener('click', async () => {
    const motivo = prompt('¿Qué error mostró Control de Proyecto al importar?');
    if(!motivo || motivo.trim().length < 3) return;
    try{
      await apiJson('/ofertas/' + o.id + '/importacion-fallida', {method: 'POST', body: JSON.stringify({motivo: motivo.trim()})});
      toast('Fallo de importación registrado en la bitácora.');
      cargarEventos(o);
    }catch(e){ toast(e.message, true); }
  });
}

// ---------------------------------------------------------------- bitácora
const ETQ_ACCION = {
  oferta_creada: 'Creada', oferta_actualizada: 'Datos', oferta_partidas: 'Partidas', oferta_estado: 'Estado',
  oferta_ganada: 'Ganada', traspaso_generado: 'Traspaso', proyecto_vinculado: 'Vinculada',
  proyecto_creacion_fallida: 'Import. fallida', traspaso_mcp_enviado: 'Enviada al MCP',
  traspaso_mcp_entregado: 'Entregada al SBC', traspaso_mcp_recibido: 'En bandeja SBC', traspaso_mcp_error: 'Error MCP',
};
async function cargarEventos(o){
  const ul = $('eventos');
  if(!ul) return;
  try{
    const ev = await apiJson('/ofertas/' + o.id + '/eventos');
    if(!actual || actual.id !== o.id) return;
    ul.innerHTML = ev.length ? ev.slice().reverse().map(e => `
      <li class="${e.conexion ? 'conexion' : ''} ${e.resultado === 'error' ? 'error' : ''}">
        <div><div class="acc">${esc(ETQ_ACCION[e.accion] || e.accion)}</div><div class="small muted">${fecha(e.timestamp)}</div></div>
        <div>${esc(e.detalle || '')}<div class="small muted">${esc(e.usuario || '')}</div></div>
      </li>`).join('') : '<li class="muted">Sin eventos.</li>';
  }catch(e){ ul.innerHTML = '<li class="muted">' + esc(e.message) + '</li>'; }
}

let _ooEstado = null;
let _ooEditor = null;
let _ooScriptUrl = '';
let _ooActual = null;
function extArchivoNombre(nombre){
  const m = String(nombre||'').toLowerCase().match(/\.([a-z0-9]+)$/);
  return m ? m[1] : '';
}
function sePuedeOnlyOfficeNombre(nombre){
  return /^(doc|docx|odt|rtf|txt|xls|xlsx|ods|csv|ppt|pptx|odp|pdf)$/.test(extArchivoNombre(nombre));
}
async function asegurarOnlyOfficeEstado(forzar){
  if(!forzar && _ooEstado) return _ooEstado;
  try{
    const r = await api('/onlyoffice/estado');
    const ct = (r.headers.get('content-type')||'');
    if(r.ok && ct.indexOf('json')>=0){
      _ooEstado = await r.json();
    } else {
      _ooEstado = _ooEstado || {habilitado:false};
    }
  }catch(_e){ _ooEstado = _ooEstado || {habilitado:false}; }
  return _ooEstado || {habilitado:false};
}
function onlyOfficeActivo(){
  return !!( _ooEstado && _ooEstado.habilitado );
}
function cargarDocsApi(dsScript){
  return new Promise((resolve, reject)=>{
    if(window.DocsAPI && window.DocsAPI.DocEditor){ resolve(); return; }
    if(!dsScript){ reject(new Error('Falta la URL de OnlyOffice')); return; }
    if(_ooScriptUrl === dsScript && document.querySelector('script[data-oo-api]')){
      const wait = ()=>{
        if(window.DocsAPI && window.DocsAPI.DocEditor) resolve();
        else setTimeout(wait, 80);
      };
      wait();
      return;
    }
    const prev = document.querySelector('script[data-oo-api]');
    if(prev) prev.remove();
    const s = document.createElement('script');
    s.src = dsScript;
    s.async = true;
    s.dataset.ooApi = '1';
    s.onload = ()=> resolve();
    s.onerror = ()=> reject(new Error('No se pudo cargar OnlyOffice. Revisa la URL en Generales (14).'));
    document.head.appendChild(s);
    _ooScriptUrl = dsScript;
  });
}
function cerrarOnlyOffice(){
  const bd = document.getElementById('oo-backdrop');
  if(_ooEditor){
    try{ _ooEditor.destroyEditor(); }catch(_e){}
    _ooEditor = null;
  }
  const ph = document.getElementById('oo-placeholder');
  if(ph) ph.innerHTML = '';
  if(bd){ bd.classList.remove('open'); bd.setAttribute('aria-hidden','true'); }
  _ooActual = null;
}
async function descargarOrigenOnlyOffice(origen, id, nombre){
  if(origen !== 'anexo' || !id){ toast('No hay documento para descargar.', true); return; }
  const r = await api('/anexos/' + encodeURIComponent(id) + '/archivo');
  if(!r.ok){ toast('No se pudo descargar el archivo.', true); return; }
  const blob = await r.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = nombre || 'documento';
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  setTimeout(()=> URL.revokeObjectURL(a.href), 2000);
}
async function abrirOnlyOffice(origen, id, nombre, modo){
  const est = await asegurarOnlyOfficeEstado();
  if(!est.habilitado){
    toast('OnlyOffice no está configurado. En Generales (14) indica la URL del Document Server.', true);
    return;
  }
  const r = await api('/onlyoffice/config', {
    method:'POST',
    body: JSON.stringify({origen, id, modo: modo || 'edit'})
  });
  const cfg = await r.json().catch(()=>({}));
  if(!r.ok){
    toast(typeof cfg.detail==='string' ? cfg.detail : 'No se pudo abrir el documento en OnlyOffice.', true);
    return;
  }
  try{
    await cargarDocsApi(cfg.ds_script || est.ds_script);
  }catch(err){
    toast(err.message || 'No se pudo cargar OnlyOffice.', true);
    return;
  }
  const bd = document.getElementById('oo-backdrop');
  const ph = document.getElementById('oo-placeholder');
  const tit = document.getElementById('oo-titulo');
  if(!bd || !ph){ toast('Falta el visor de OnlyOffice en la página.', true); return; }
  if(_ooEditor){ try{ _ooEditor.destroyEditor(); }catch(_e){} _ooEditor = null; }
  ph.innerHTML = '';
  if(tit) tit.textContent = cfg.titulo || nombre || 'Documento';
  _ooActual = {origen: origen, id: id, nombre: cfg.titulo || nombre || 'documento'};
  bd.classList.add('open');
  bd.setAttribute('aria-hidden','false');
  const cfgEditor = {
    documentType: cfg.documentType,
    document: cfg.document,
    editorConfig: cfg.editorConfig,
    type: cfg.type || 'desktop',
    width: '100%',
    height: '100%'
  };
  if(cfg.token) cfgEditor.token = cfg.token;
  try{
    _ooEditor = new window.DocsAPI.DocEditor('oo-placeholder', cfgEditor);
  }catch(err){
    cerrarOnlyOffice();
    toast('OnlyOffice no pudo iniciar el editor. '+((err && err.message)||''), true);
  }
}
function botonOnlyOffice(origen, id, nombre){
  if(!onlyOfficeActivo() || !id || !sePuedeOnlyOfficeNombre(nombre)) return '';
  const etq = /\.pdf$/i.test(nombre||'') ? 'Abrir PDF' : 'Abrir';
  return ` <button type="button" class="btn ghost sm" data-oo-origen="${esc(origen)}" data-oo-id="${esc(id)}" data-oo-nombre="${esc(nombre)}">${etq}</button>`;
}

window.COT = {
  get auth(){ return auth; },
  get apiBase(){ return API; },
  $, esc, toast, dinero, fecha, api, apiJson, apiUpload, apiUploadMany, inferirTipoAnexo, puedeEscribir, abrirHtml,
  abrirOferta: (id) => cargarLista(id), cargarMcp,
  asegurarOnlyOfficeEstado, onlyOfficeActivo, abrirOnlyOffice,
};

// ---------------------------------------------------------------- arranque
async function arrancar(){
  enlazarLogin();
  $('b-nueva').addEventListener('click', formNueva);
  $('f-estado').addEventListener('change', () => cargarLista());
  $('esc-actual').addEventListener('click', abrirSelectorEscenarioSesion);
  if(window.PlataformaCotizacion) window.PlataformaCotizacion.iniciar();
  const btnOoCerrar = $('oo-cerrar');
  if(btnOoCerrar) btnOoCerrar.addEventListener('click', cerrarOnlyOffice);
  const btnOoDesc = $('oo-descargar');
  if(btnOoDesc) btnOoDesc.addEventListener('click', () => {
    if(_ooActual) descargarOrigenOnlyOffice(_ooActual.origen, _ooActual.id, _ooActual.nombre);
  });
  window.addEventListener('keydown', (ev) => {
    if(ev.key === 'Escape' && $('oo-backdrop') && $('oo-backdrop').classList.contains('open')) cerrarOnlyOffice();
  });
  window.addEventListener('beforeunload', (ev) => { if(partidasSucias){ ev.preventDefault(); ev.returnValue = ''; } });
  try{
    const h = await (await llamar('/health')).json();
    $('login-version').textContent = 'v' + h.version;
  }catch(e){ errorLogin(e.message); }
  try{
    const guardada = JSON.parse(sessionStorage.getItem(SESSION_KEY) || 'null');
    if(guardada && guardada.accessToken && guardada.escenario){
      auth = guardada;
      const r = await api('/auth/me');
      if(r.ok){ await entrar(); return; }
    }
  }catch(e){}
  olvidar();
  mostrarPaso('f-login');
}

document.addEventListener('DOMContentLoaded', arrancar);
})();
