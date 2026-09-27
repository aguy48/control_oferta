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
const EDITABLES_CERRADA = ['sede_destino', 'notas', 'cliente_contacto'];
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
  if(lista.length === 1){ await elegirEscenario(lista[0].id); return; }
  $('esc-lista').innerHTML = lista.map(e =>
    `<button type="button" data-id="${esc(e.id)}"><strong>${esc(e.nombre)}</strong><br>
     <span class="small muted">${esc(e.estado)}${e.solo_lectura ? ' · solo lectura' : ''}</span></button>`).join('');
  $('esc-lista').querySelectorAll('button').forEach(b => b.addEventListener('click', () => elegirEscenario(b.dataset.id)));
  mostrarPaso('p-escenario');
}

async function elegirEscenario(id){
  try{
    const d = await apiJson('/auth/escenario', {method: 'POST', body: JSON.stringify({escenario_id: id})});
    tomarTokens(d);
    await entrar();
  }catch(e){ errorLogin(e.message); }
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
  await cargarMcp();
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
function formNueva(){
  if(partidasSucias && !confirm('Hay cambios en las partidas sin guardar. ¿Descartarlos?')) return;
  actual = null; partidasSucias = false; pintarLista();
  $('detalle').innerHTML = `
    <div class="card">
      <div class="card-head"><h2>Nueva oferta</h2></div>
      <form id="f-nueva" class="form-grid">
        <label class="span2">Título de la oferta<input name="titulo" minlength="3" required></label>
        <label>Cliente (razón social)<input name="cliente_razon_social" minlength="2" required></label>
        <label>RIF del cliente<input name="cliente_rif" placeholder="J-00000000-0"></label>
        <label>Tipo de cliente<select name="cliente_tipo"><option value="directo">Directo</option><option value="aliado">Aliado</option></select></label>
        <label>Moneda<input name="moneda" value="USD" maxlength="3" required></label>
        <div class="acciones span2"><button class="btn">Crear oferta</button>
          <span class="small muted">El código ORI-AAAA-MM-NNN se asigna al crearla.</span></div>
      </form>
    </div>`;
  $('f-nueva').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target), body = {};
    f.forEach((v, k) => { v = String(v).trim(); if(v) body[k] = v; });
    body.moneda = (body.moneda || 'USD').toUpperCase();
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
    tarjetaPartidas(o, escribir && !cerrada),
    '<div class="card"><div class="card-head"><h2>Bitácora de la oferta</h2></div><ul class="eventos" id="eventos"><li class="muted">Cargando…</li></ul></div>',
  ].join('');
  enlazarEncabezado(o);
  enlazarDatos(o, cerrada);
  enlazarModalidad(o);
  enlazarPartidas();
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
          <div class="small muted">${esc(o.cliente_razon_social)} · Analista: ${esc(o.analista_nombre || '—')}</div>
        </div>
        <div style="text-align:right">
          <div class="small muted">Total sin IVA</div>
          <div style="font-size:20px;font-weight:700;color:var(--morado)">${dinero(o.total_precio, o.moneda)}</div>
        </div>
      </div>
      ${botones ? `<div class="acciones">${botones}</div>` : ''}
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
      actual = await apiJson('/ofertas/' + o.id + '/estado', {method: 'POST', body: JSON.stringify({estado: e})});
      toast(e === 'ganada' ? 'Oferta ganada. Ya puedes descargar el traspaso.' : 'Estado actualizado.');
      await cargarLista(actual.id);
    }catch(err){ toast(err.message, true); }
  }));
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
      ${cerrada && escribir ? '<div class="aviso info small" style="margin-bottom:10px">Oferta cerrada: solo se pueden cambiar el contacto, la sede de destino y las notas.</div>' : ''}
      <form id="f-datos" class="form-grid" onsubmit="return false">
        ${campo('titulo', 'Título', o.titulo, ed('titulo'), {clase: 'span2'})}
        ${campo('cliente_razon_social', 'Cliente (razón social)', o.cliente_razon_social, ed('cliente_razon_social'))}
        ${campo('cliente_rif', 'RIF del cliente', o.cliente_rif, ed('cliente_rif'), {attrs: ' placeholder="J-00000000-0"'})}
        ${campo('cliente_tipo', 'Tipo de cliente', o.cliente_tipo, ed('cliente_tipo'), {opciones: [['directo', 'Directo'], ['aliado', 'Aliado']]})}
        ${campo('cliente_contacto', 'Contacto del cliente', o.cliente_contacto, ed('cliente_contacto'))}
        ${campo('moneda', 'Moneda', o.moneda, ed('moneda'), {attrs: ' maxlength="3"'})}
        ${campo('iva_pct', 'IVA (%)', o.iva_pct, ed('iva_pct'), {tipo: 'number', attrs: ' min="0" max="100"'})}
        ${campo('semanas_totales', 'Plazo total (semanas)', o.semanas_totales, ed('semanas_totales'), {tipo: 'number', attrs: ' min="1" placeholder="se calcula de las partidas"'})}
        ${mcpEstado.configurado
          ? campo('mcp_destino_id', 'SBC destino (por el MCP)', o.mcp_destino_id || '', ed('mcp_destino_id'),
              {opciones: [['', mcpEstado.ok ? '— Elige el SBC —' : '— MCP sin conexión —']]
                .concat((mcpEstado.destinos || []).map(d => [d.id, esc(d.nombre + (d.sitio_nombre ? ' · ' + d.sitio_nombre : '') + (d.estado && d.estado !== 'en_linea' ? ' (' + d.estado + ')' : ''))]))
                .concat(o.mcp_destino_id && !(mcpEstado.destinos || []).some(d => d.id === o.mcp_destino_id)
                  ? [[o.mcp_destino_id, esc(o.sede_destino || o.mcp_destino_id)]] : [])})
          : campo('sede_destino', 'Sede de Control de Proyecto (SBC)', o.sede_destino, ed('sede_destino'), {attrs: ' placeholder="SBC que opera el contrato"'})}
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
      else if(k === 'moneda') body[k] = v.toUpperCase();
      else body[k] = v === '' ? null : v;
    });
    if('mcp_destino_id' in body){
      const d = (mcpEstado.destinos || []).find(x => x.id === body.mcp_destino_id);
      body.sede_destino = d ? d.nombre : null;
    }
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
function tarjetaPartidas(o, editable){
  return `
    <div class="card">
      <div class="card-head"><h2>Partidas</h2>
        ${editable ? `<div class="acciones"><button class="btn ghost sm" id="b-add">+ Partida</button>
          <button class="btn sm" id="b-guardar-partidas" disabled>Guardar partidas</button></div>` : ''}</div>
      <div class="tabla-wrap"><table>
        <thead><tr>
          <th class="col-disc">Disciplina</th><th class="col-item">Ítem</th><th>Descripción</th><th class="col-und">Unidad</th>
          <th class="num col-n">Cantidad</th><th class="num col-n">P. unitario</th><th class="num col-n">Total</th>
          <th class="num col-s" title="Semana de inicio">Sem. ini.</th><th class="num col-s" title="Duración en semanas">Duración</th>
          ${editable ? '<th></th>' : ''}
        </tr></thead>
        <tbody id="tb-partidas"></tbody>
        <tfoot id="tf-partidas"></tfoot>
      </table></div>
      <p class="small muted" style="margin:8px 0 0">La disciplina se convierte en el frente de valuación en Control de Proyecto (facturación detallada). Semana de inicio y duración alimentan el cronograma.</p>
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
      <td><input class="desc" data-i="${i}" data-k="descripcion" value="${esc(p.descripcion)}"${ro}></td>
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
    marcarSucias();
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
      semana_inicio: null, duracion_semanas: null});
    marcarSucias();
    pintarPartidas();
    const ultimos = tb.querySelectorAll('input.desc');
    if(ultimos.length) ultimos[ultimos.length - 1].focus();
  });
  $('b-guardar-partidas').addEventListener('click', async () => {
    const vacias = partidasEdit.findIndex(p => !String(p.item || '').trim() || !String(p.descripcion || '').trim());
    if(vacias >= 0){ toast('La partida ' + (vacias + 1) + ' necesita ítem y descripción.', true); return; }
    const body = partidasEdit.map(p => ({
      disciplina: String(p.disciplina || 'GENERAL').trim() || 'GENERAL',
      item: String(p.item).trim(), descripcion: String(p.descripcion).trim(),
      unidad: String(p.unidad || 'UND').trim() || 'UND',
      cantidad: Number(p.cantidad) || 0, precio_unitario: Number(p.precio_unitario) || 0,
      semana_inicio: p.semana_inicio || null, duracion_semanas: p.duracion_semanas || null,
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
  const destino = (mcpEstado.destinos || []).find(d => d.id === o.mcp_destino_id);
  const nomDestino = (destino && destino.nombre) || o.sede_destino || '';
  const enviado = !!o.mcp_traspaso_id;
  const recibido = ['recibido', 'aceptado', 'rechazado'].includes(o.mcp_estado);
  return `
    <div class="card" style="border-color:var(--naranja)">
      <div class="card-head"><h2>Traspaso a Control de Proyecto por el MCP</h2>${chip}</div>
      ${!mcpEstado.ok ? `<div class="aviso warn small" style="margin-bottom:12px">Sin conexión con el MCP: ${esc(mcpEstado.detalle || '')}</div>` : ''}
      <ol class="pasos">
        <li class="${enviado && o.mcp_estado !== 'error_envio' ? 'hecho' : ''}"><div>
          <h3>Enviar al SBC${nomDestino ? ' «' + esc(nomDestino) + '»' : ''}</h3>
          ${!o.mcp_destino_id ? '<p class="small" style="margin:0 0 8px">Elige el <strong>SBC destino</strong> en «Datos de la oferta» y guarda.</p>' : ''}
          ${est ? `<div class="aviso ${est[2]} small" style="margin-bottom:8px"><strong>${esc(est[0])}</strong>${o.mcp_version > 1 ? ' · versión ' + esc(o.mcp_version) : ''} · ${fecha(o.mcp_actualizado_en)}
             ${est[1] ? '<br>' + esc(est[1]) : ''}${o.mcp_detalle ? '<br>' + esc(o.mcp_detalle) : ''}</div>` : ''}
          <div class="acciones">
            ${escribir && o.mcp_destino_id && o.mcp_estado !== 'aceptado'
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

// ---------------------------------------------------------------- arranque
async function arrancar(){
  enlazarLogin();
  $('b-nueva').addEventListener('click', formNueva);
  $('f-estado').addEventListener('change', () => cargarLista());
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
