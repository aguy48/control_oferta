/* Opciones propias del Sistema de Cotización (el ciclo de obra vive en Control de Proyecto). */
(function(){
'use strict';

const ETQ_TAREA = {pendiente: 'Pendiente', en_curso: 'En curso', hecha: 'Hecha', cancelada: 'Cancelada'};
const AYUDA = {
  panel: '01 Panel: ofertas abiertas y ganadas, catálogo y si el MCP está enlazado (SBC en 16 Generales).',
  ofertas: '02 Ofertas: cliente (o alta en 05), Gemini, OnlyOffice, margen y traspaso al SBC único de Generales (16) al ganar.',
  informes: '03 Informes: levantamiento de campo. Gemini lee PDF, audio y WhatsApp y redacta el informe más la oferta.',
  reportes: '04 Reportes: imprimir oferta e informe técnico; abrir Word/Excel en OnlyOffice (16) y eliminar el informe.',
  clientes: '05 Clientes: ficha fiscal. El RIF viaja en el traspaso para que el SBC reconozca al cliente.',
  productos: '06 Productos y servicios: catálogo cotizable, top 10, garantía, entrega y serial al ganar.',
  proveedores: '07 Proveedores: quienes envían las ofertas que cargas en la cotización.',
  contactos: '08 Contactos: personas de cliente u organismo, vinculables a una ficha.',
  tareas: '09 Tareas: pendientes comerciales del escenario (visita, envío, negociación).',
  documentos: '10 Documentos: pliegos, planos o anexos (URL o nota). Los archivos de oferta se abren en 02.',
  usuarios: '11 Usuarios: cuentas de esta instancia. Telegram se vincula con el botón de la barra.',
  auditoria: '12 Auditoría: lo que hacen las personas. Los fallos de MCP, Telegram o disco van a Eventos (13).',
  eventos: '13 Eventos: visor de sistema (MCP, bloqueos, Telegram, disco). Distinto de Auditoría (12).',
  respaldo: '14 Respaldo: ZIP de datos (SQL + anexos) o de la aplicación. Restaurar pide «restaurar cotizacion».',
  escenarios: '15 Escenarios: periodos del SBC elegido en Generales (16). Aquí se asignan usuarios y el por defecto.',
  generales: '16 Generales: empresa, Gemini, MCP/SBC, Telegram y OnlyOffice en bloques. Cada uno se guarda aparte.',
};

function C(){ return window.COT || {}; }
function $(id){ return C().$ ? C().$(id) : document.getElementById(id); }

function filaAcciones(id, extra){
  return `<div class="acciones">${extra || ''}
    <button type="button" class="btn ghost sm" data-editar="${id}">Editar</button>
    <button type="button" class="btn peligro sm" data-borrar="${id}">Quitar</button></div>`;
}

function formCard(titulo, campos, submit){
  return `<div class="card-head"><h2>${titulo}</h2></div>
    <form id="f-mod" class="form-grid">${campos}
      <div class="acciones span2"><button class="btn">${submit}</button>
        <button type="button" class="btn ghost" id="b-cancelar">Cancelar</button></div>
    </form>`;
}

function host(){ return $('modulo-host'); }

async function renderPanel(){
  const vista = $('vista-panel');
  vista.innerHTML = '<div class="card vacio">Cargando panel…</div>';
  try{
    const p = await C().apiJson('/panel');
    const etq = {borrador:'Borrador', enviada:'Enviada', en_negociacion:'En negociación',
      ganada:'Ganada', perdida:'Perdida', anulada:'Anulada'};
    const kpis = [
      ['Abiertas $', C().dinero(p.total_abiertas)],
      ['Ganadas $', C().dinero(p.total_ganadas)],
      ['Clientes', p.n_clientes],
      ['Contactos', p.n_contactos],
      ['Tareas abiertas', p.n_tareas_abiertas],
      ['Documentos', p.n_documentos],
      ['Proveedores', p.n_proveedores],
      ['Productos', p.n_productos || 0],
      ['Informes', p.n_informes || 0],
      ['MCP', p.mcp && p.mcp.configurado ? (p.mcp.sede_nombre || 'Enlazado') : 'Manual'],
    ];
    vista.innerHTML = `
      <div class="kpi-grid">${kpis.map(([l,n]) => `<div class="kpi"><div class="n">${C().esc(n)}</div><div class="l">${l}</div></div>`).join('')}</div>
      <div class="card">
        <div class="card-head"><h2>Ofertas por estado</h2></div>
        <div class="acciones">${Object.keys(etq).map(k =>
          `<span class="chip">${etq[k]}: ${p.ofertas_por_estado[k] || 0}</span>`).join('')}</div>
      </div>
      <div class="card">
        <div class="card-head"><h2>Actividad reciente</h2></div>
        ${p.recientes.length ? `<div class="tabla-wrap"><table class="tabla-mod"><thead><tr><th>Código</th><th>Título</th><th>Cliente</th><th>Estado</th><th class="num">Total</th></tr></thead>
          <tbody>${p.recientes.map(o => `<tr data-ir="${C().esc(o.id)}"><td class="mono">${C().esc(o.codigo)}</td><td>${C().esc(o.titulo)}</td>
            <td>${C().esc(o.cliente)}</td><td>${C().esc(etq[o.estado]||o.estado)}</td>
            <td class="num">${C().dinero(o.total)}</td></tr>`).join('')}</tbody></table></div>`
          : '<p class="muted">Aún no hay ofertas en este escenario.</p>'}
      </div>
      ${(p.top_productos||[]).length ? `<div class="card">
        <div class="card-head"><h2>10 productos / servicios más cotizados</h2>
          <button type="button" class="btn ghost sm" id="b-ir-productos">Abrir 06</button></div>
        <div class="tabla-wrap"><table class="tabla-mod"><thead><tr>
          <th>#</th><th>Código</th><th>Nombre</th><th class="num">Veces</th><th class="num">Monto</th>
        </tr></thead><tbody>${p.top_productos.map((x,i)=>`<tr>
          <td>${i+1}</td><td class="mono">${C().esc(x.codigo)}</td><td>${C().esc(x.nombre)}</td>
          <td class="num">${x.n_cotizaciones}</td><td class="num">${C().dinero(x.monto)}</td></tr>`).join('')}</tbody></table></div>
      </div>` : ''}`;
    vista.querySelectorAll('tr[data-ir]').forEach(tr => tr.addEventListener('click', () => {
      mostrarVista('ofertas');
      C().abrirOferta && C().abrirOferta(tr.dataset.ir);
    }));
    const bp = $('b-ir-productos');
    if(bp) bp.addEventListener('click', () => mostrarVista('productos'));
  }catch(e){
    vista.innerHTML = `<div class="card aviso bad">${C().esc(e.message)}</div>`;
  }
}

function tabla(headers, rows){
  return `<div class="tabla-wrap"><table class="tabla-mod"><thead><tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr></thead>
    <tbody>${rows || '<tr><td colspan="'+headers.length+'" class="muted">Sin registros.</td></tr>'}</tbody></table></div>`;
}

async function crudLista(cfg){
  const h = host();
  h.innerHTML = `<div class="card-head"><h2>${cfg.titulo}</h2>
    ${C().puedeEscribir() ? `<button class="btn naranja sm" id="b-mod-nuevo">+ Nuevo</button>` : ''}</div>
    <p class="small muted">${cfg.ayuda || ''}</p>
    <p class="muted">Cargando…</p>`;
  let filas = [];
  try{ filas = await C().apiJson(cfg.path); }
  catch(e){ h.insertAdjacentHTML('beforeend', `<div class="aviso bad">${C().esc(e.message)}</div>`); return; }
  const cuerpo = filas.length ? filas.map(cfg.fila).join('') : '';
  h.innerHTML = `<div class="card-head"><h2>${cfg.titulo}</h2>
    ${C().puedeEscribir() ? `<button class="btn naranja sm" id="b-mod-nuevo">+ Nuevo</button>` : ''}</div>
    <p class="small muted">${cfg.ayuda || ''}</p>${tabla(cfg.headers, cuerpo)}`;
  const bn = $('b-mod-nuevo');
  if(bn) bn.addEventListener('click', () => cfg.form(null, filas));
  h.querySelectorAll('[data-editar]').forEach(b => b.addEventListener('click', () => {
    const rec = filas.find(x => x.id === b.dataset.editar);
    if(rec) cfg.form(rec, filas);
  }));
  h.querySelectorAll('[data-borrar]').forEach(b => b.addEventListener('click', async () => {
    if(!confirm('¿Quitar este registro?')) return;
    try{
      await C().apiJson(cfg.path + '/' + b.dataset.borrar, {method: 'DELETE'});
      C().toast('Eliminado.');
      crudLista(cfg);
    }catch(e){ C().toast(e.message, true); }
  }));
  if(cfg.abrirNuevo && C().puedeEscribir()) cfg.form(null, filas);
}

function bindForm(path, id, recargar, extra){
  extra = extra || {};
  const f = $('f-mod');
  if(!f) return;
  $('b-cancelar').addEventListener('click', extra.cancelar || recargar);
  f.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const fd = new FormData(f), body = {};
    fd.forEach((v, k) => {
      v = String(v).trim();
      if(v === '') body[k] = null;
      else if(v === 'true' || v === 'false') body[k] = v === 'true';
      else if(f.elements[k] && f.elements[k].type === 'number') body[k] = Number(v);
      else body[k] = v;
    });
    try{
      const r = id
        ? await C().apiJson(path + '/' + id, {method: 'PATCH', body: JSON.stringify(body)})
        : await C().apiJson(path, {method: 'POST', body: JSON.stringify(body)});
      C().toast(id ? 'Guardado.' : 'Creado.');
      recargar(r);
    }catch(e){ C().toast(e.message, true); }
  });
}

function inp(name, label, value, extra){
  extra = extra || {};
  if(extra.tipo === 'select'){
    const ops = extra.ops.map(o => `<option value="${o[0]}" ${String(value)===String(o[0])?'selected':''}>${o[1]}</option>`).join('');
    return `<label>${label}<select name="${name}">${ops}</select></label>`;
  }
  if(extra.tipo === 'number'){
    return `<label${extra.span2?' class="span2"':''}>${label}<input name="${name}" type="number" step="${extra.step||'any'}" min="${extra.min||'0'}" value="${C().esc(value==null?'':value)}" ${extra.req?'required':''}></label>`;
  }
  if(extra.tipo === 'textarea'){
    return `<label class="span2">${label}<textarea name="${name}">${C().esc(value||'')}</textarea></label>`;
  }
  return `<label${extra.span2?' class="span2"':''}>${label}<input name="${name}" value="${C().esc(value||'')}" ${extra.req?'required':''} ${extra.ph?'placeholder="'+extra.ph+'"':''}></label>`;
}

function renderClientes(opts){
  opts = opts || {};
  return crudLista({
    titulo: 'Clientes', path: '/clientes',
    abrirNuevo: !!opts.abrirNuevo,
    ayuda: opts.abrirNuevo
      ? 'Ficha fiscal (opción 05). Al guardar, la oferta toma este cliente.'
      : 'El RIF identifica al cliente en Control de Proyecto al traspasar la oferta ganada.',
    headers: ['Razón social', 'RIF', 'Tipo', 'Teléfono', 'Ofertas', ''],
    fila: c => `<tr>
      <td><strong>${C().esc(c.razon_social)}</strong><div class="small muted">${C().esc(c.email||'')}</div></td>
      <td class="mono">${C().esc(c.rif||'—')}</td>
      <td>${c.tipo==='aliado'?'Aliado':'Directo'}</td>
      <td>${C().esc(c.telefono||'—')}</td>
      <td>${c.n_ofertas||0}</td>
      <td>${C().puedeEscribir()?filaAcciones(c.id):''}</td></tr>`,
    form(rec){
      host().innerHTML = formCard(rec?'Editar cliente':'Nuevo cliente', [
        inp('razon_social','Razón social', rec&&rec.razon_social, {req:true, span2:true}),
        inp('rif','RIF', rec&&rec.rif, {ph:'J-00000000-0'}),
        inp('tipo','Tipo', rec&&rec.tipo||'directo', {tipo:'select', ops:[['directo','Directo'],['aliado','Aliado']]}),
        inp('telefono','Teléfono', rec&&rec.telefono),
        inp('email','Correo', rec&&rec.email),
        inp('condicion_pago','Condición de pago', rec&&rec.condicion_pago),
        inp('direccion','Dirección', rec&&rec.direccion, {tipo:'textarea'}),
        inp('notas','Notas', rec&&rec.notas, {tipo:'textarea'}),
      ].join(''), 'Guardar');
      bindForm('/clientes', rec&&rec.id, (creado) => {
        if(!rec && opts.alCrear && creado && creado.id){
          opts.alCrear(creado);
          return;
        }
        renderClientes();
      }, {cancelar: opts.alCancelar || renderClientes});
    },
  });
}

function renderProductos(opts){
  opts = opts || {};
  const formProd = (rec) => {
    host().innerHTML = formCard(rec ? 'Editar producto / servicio' : 'Nuevo producto / servicio', [
      inp('tipo', 'Tipo', rec && rec.tipo || 'producto', {tipo:'select', ops:[['producto','Producto'],['servicio','Servicio']]}),
      inp('codigo', 'Código', rec && rec.codigo, {ph:'Vacío = se asigna PRD-001 / SRV-001'}),
      inp('nombre', 'Nombre', rec && rec.nombre, {req:true, span2:true}),
      inp('descripcion', 'Descripción', rec && rec.descripcion, {tipo:'textarea'}),
      inp('unidad', 'Unidad', rec && rec.unidad || 'UND'),
      inp('disciplina', 'Disciplina', rec && rec.disciplina, {ph:'GENERAL'}),
      inp('precio_ref', 'Precio de referencia', rec && rec.precio_ref, {tipo:'number', step:'0.01'}),
      inp('requiere_serial', '¿Requiere serial al vender?', rec && rec.requiere_serial ? 'true' : 'false', {
        tipo:'select', ops:[['false','No'],['true','Sí, pedir serial por unidad']],
      }),
      inp('garantia_semanas', 'Garantía (semanas)', rec && rec.garantia_semanas, {tipo:'number', min:'0'}),
      inp('tiempo_entrega_semanas', 'Tiempo de entrega (semanas)', rec && rec.tiempo_entrega_semanas, {tipo:'number', min:'0'}),
      inp('activo', 'Activo', rec && rec.activo === false ? 'false' : 'true', {
        tipo:'select', ops:[['true','Sí'],['false','No']],
      }),
    ].join(''), 'Guardar');
    bindForm('/productos', rec && rec.id, (creado) => {
      if(!rec && opts.alCrear && creado && creado.id){
        opts.alCrear(creado);
        return;
      }
      renderProductos();
    }, {cancelar: opts.alCancelar || renderProductos});
  };
  if(opts.abrirNuevo && C().puedeEscribir()){
    host().innerHTML = '<p class="muted">Cargando ficha…</p>';
    formProd(null);
    return;
  }
  return crudLista({
    titulo: 'Productos y servicios', path: '/productos',
    abrirNuevo: false,
    ayuda: 'Búsqueda en partidas o desde aquí. El serial se pide al marcar la oferta ganada, no al cotizar.',
    headers: ['Código', 'Nombre', 'Tipo', 'Serial', 'Garantía', 'Entrega', 'Cotizado', ''],
    fila: p => `<tr>
      <td class="mono">${C().esc(p.codigo)}</td>
      <td><strong>${C().esc(p.nombre)}</strong><div class="small muted">${C().esc(p.unidad||'UND')}${p.precio_ref!=null?' · '+C().dinero(p.precio_ref):''}</div></td>
      <td>${p.tipo==='servicio'?'Servicio':'Producto'}</td>
      <td>${p.requiere_serial?'Sí':'No'}</td>
      <td>${p.garantia_semanas!=null?p.garantia_semanas+' sem.':'—'}</td>
      <td>${p.tiempo_entrega_semanas!=null?p.tiempo_entrega_semanas+' sem.':'—'}</td>
      <td>${p.n_cotizaciones||0}</td>
      <td>${C().puedeEscribir()?filaAcciones(p.id, `<button type="button" class="btn ghost sm" data-hist="${p.id}">Historial</button>`):`<button type="button" class="btn ghost sm" data-hist="${p.id}">Historial</button>`}</td></tr>`,
    form: formProd,
  }).then(async () => {
    const h = host();
    const buscador = document.createElement('div');
    buscador.className = 'filtro';
    buscador.style.margin = '8px 0 12px';
    buscador.innerHTML = `<label>Buscar en el catálogo<input id="f-prod-q" type="search" placeholder="Nombre, código o descripción…"></label>`;
    const head = h.querySelector('.card-head');
    if(head) head.insertAdjacentElement('afterend', buscador);
    let top = [];
    try{ top = await C().apiJson('/productos/estadistica/top?limite=10'); }catch(e){}
    if(top.length){
      const card = document.createElement('div');
      card.className = 'card';
      card.style.marginBottom = '12px';
      card.innerHTML = `<div class="card-head"><h2>10 más cotizados</h2></div>
        <div class="tabla-wrap"><table class="tabla-mod"><thead><tr>
          <th>#</th><th>Código</th><th>Nombre</th><th>Tipo</th><th class="num">Veces</th><th class="num">Cantidad</th><th class="num">Monto</th>
        </tr></thead><tbody>${top.map((p,i)=>`<tr>
          <td>${i+1}</td><td class="mono">${C().esc(p.codigo)}</td><td>${C().esc(p.nombre)}</td>
          <td>${p.tipo==='servicio'?'Servicio':'Producto'}</td>
          <td class="num">${p.n_cotizaciones}</td><td class="num">${p.cantidad}</td>
          <td class="num">${C().dinero(p.monto)}</td></tr>`).join('')}</tbody></table></div>`;
      h.insertBefore(card, h.querySelector('.tabla-wrap'));
    }
    const q = $('f-prod-q');
    if(q){
      let t;
      q.addEventListener('input', () => {
        clearTimeout(t);
        t = setTimeout(async () => {
          const v = q.value.trim();
          const path = v ? '/productos?todos=true&q=' + encodeURIComponent(v) : '/productos?todos=true';
          try{
            const filas = await C().apiJson(path);
            const tb = h.querySelector('.tabla-mod tbody');
            if(!tb) return;
            const cfgFila = (p) => `<tr>
              <td class="mono">${C().esc(p.codigo)}</td>
              <td><strong>${C().esc(p.nombre)}</strong></td>
              <td>${p.tipo==='servicio'?'Servicio':'Producto'}</td>
              <td>${p.requiere_serial?'Sí':'No'}</td>
              <td>${p.garantia_semanas!=null?p.garantia_semanas+' sem.':'—'}</td>
              <td>${p.tiempo_entrega_semanas!=null?p.tiempo_entrega_semanas+' sem.':'—'}</td>
              <td>${p.n_cotizaciones||0}</td>
              <td>${C().puedeEscribir()?filaAcciones(p.id, `<button type="button" class="btn ghost sm" data-hist="${p.id}">Historial</button>`):''}</td></tr>`;
            tb.innerHTML = filas.length ? filas.map(cfgFila).join('') : '<tr><td colspan="8" class="muted">Sin coincidencias.</td></tr>';
            wireHist(filas);
          }catch(e){ C().toast(e.message, true); }
        }, 220);
      });
    }
    let filas = [];
    try{ filas = await C().apiJson('/productos?todos=true'); }catch(e){}
    function wireHist(lista){
      h.querySelectorAll('[data-hist]').forEach(b => b.addEventListener('click', async () => {
        const rec = (lista||filas).find(x => x.id === b.dataset.hist);
        if(!rec) return;
        try{
          const hist = await C().apiJson('/productos/' + rec.id + '/cotizaciones');
          host().innerHTML = `<div class="card-head"><h2>Cotizaciones de ${C().esc(rec.nombre)}</h2>
            <button type="button" class="btn ghost sm" id="b-hist-volver">Volver</button></div>
            <p class="small muted">A quién se cotizó, cuándo y el monto.</p>
            ${hist.length ? `<div class="tabla-wrap"><table class="tabla-mod"><thead><tr>
              <th>Oferta</th><th>Cliente</th><th>Fecha</th><th>Estado</th><th class="num">Cant.</th><th class="num">Monto</th>
            </tr></thead><tbody>${hist.map(x=>`<tr data-ir="${C().esc(x.oferta_id)}">
              <td class="mono">${C().esc(x.codigo)}</td><td>${C().esc(x.cliente)}</td>
              <td>${C().fecha(x.fecha)}</td><td>${C().esc(x.estado)}</td>
              <td class="num">${x.cantidad}</td><td class="num">${C().dinero(x.monto, x.moneda)}</td>
            </tr>`).join('')}</tbody></table></div>` : '<p class="muted">Aún no se ha cotizado este ítem.</p>'}`;
          $('b-hist-volver').addEventListener('click', renderProductos);
          host().querySelectorAll('tr[data-ir]').forEach(tr => tr.addEventListener('click', () => {
            mostrarVista('ofertas');
            C().abrirOferta && C().abrirOferta(tr.dataset.ir);
          }));
        }catch(e){ C().toast(e.message, true); }
      }));
    }
    wireHist(filas);
  });
}

function renderProveedores(){
  return crudLista({
    titulo: 'Proveedores', path: '/proveedores',
    ayuda: 'Catálogo local. Las CxP del contrato se operan en Control de Proyecto.',
    headers: ['Razón social', 'RIF', 'Contacto', 'Teléfono', ''],
    fila: p => `<tr><td>${C().esc(p.razon_social)}</td><td class="mono">${C().esc(p.rif||'—')}</td>
      <td>${C().esc(p.contacto||'—')}</td><td>${C().esc(p.telefono||'—')}</td>
      <td>${C().puedeEscribir()?filaAcciones(p.id):''}</td></tr>`,
    form(rec){
      host().innerHTML = formCard(rec?'Editar proveedor':'Nuevo proveedor', [
        inp('razon_social','Razón social', rec&&rec.razon_social, {req:true, span2:true}),
        inp('rif','RIF', rec&&rec.rif),
        inp('contacto','Contacto', rec&&rec.contacto),
        inp('telefono','Teléfono', rec&&rec.telefono),
        inp('email','Correo', rec&&rec.email),
        inp('notas','Notas', rec&&rec.notas, {tipo:'textarea'}),
      ].join(''), 'Guardar');
      bindForm('/proveedores', rec&&rec.id, renderProveedores);
    },
  });
}

async function renderContactos(){
  let clientes = [];
  try{ clientes = await C().apiJson('/clientes'); }catch(e){}
  const opsCli = [['','— Sin cliente —']].concat(clientes.map(c => [c.id, c.razon_social]));
  return crudLista({
    titulo: 'Contactos', path: '/contactos',
    ayuda: 'Personas del cliente u organismo.',
    headers: ['Nombre', 'Cargo', 'Cliente', 'Correo', 'Teléfono', ''],
    fila: c => `<tr><td>${C().esc(c.nombre)}</td><td>${C().esc(c.cargo||'—')}</td>
      <td>${C().esc(c.cliente_razon||'—')}</td>
      <td>${c.email?`<a href="mailto:${C().esc(c.email)}">${C().esc(c.email)}</a>`:'—'}</td>
      <td>${C().esc(c.telefono||'—')}</td>
      <td>${C().puedeEscribir()?filaAcciones(c.id):''}</td></tr>`,
    form(rec){
      host().innerHTML = formCard(rec?'Editar contacto':'Nuevo contacto', [
        inp('nombre','Nombre', rec&&rec.nombre, {req:true}),
        inp('cargo','Cargo', rec&&rec.cargo),
        inp('email','Correo', rec&&rec.email),
        inp('telefono','Teléfono', rec&&rec.telefono),
        inp('tipo_responsable','Tipo de responsable', rec&&rec.tipo_responsable),
        inp('cliente_id','Cliente', rec&&rec.cliente_id||'', {tipo:'select', ops:opsCli}),
        inp('notas','Notas', rec&&rec.notas, {tipo:'textarea'}),
      ].join(''), 'Guardar');
      bindForm('/contactos', rec&&rec.id, renderContactos);
    },
  });
}

async function renderInformes(){
  host().innerHTML = `<div class="card-head"><h2>Informes técnicos</h2>
    ${C().puedeEscribir() ? '<button class="btn naranja sm" id="b-inf-nuevo">+ Informe</button>' : ''}</div>
    <p class="small muted">Levantamiento o actividades de campo. Del informe se genera la oferta comercial (además de este reporte).</p>
    <p class="muted">Cargando…</p>`;
  let filas = [];
  try{ filas = await C().apiJson('/informes'); }
  catch(e){ host().insertAdjacentHTML('beforeend', `<div class="aviso bad">${C().esc(e.message)}</div>`); return; }
    const cuerpo = filas.length ? filas.map(i => `<tr>
    <td>${C().esc(i.codigo||'—')}</td>
    <td><strong>${C().esc(i.titulo)}</strong><div class="small muted">${C().esc((i.resumen||'').slice(0,120))}${i.anexo_nombre?' · '+C().esc(i.anexo_nombre):''}</div></td>
    <td>${C().esc(i.cliente_razon_social||'—')}</td>
    <td class="acciones">${accionesInformeTecnico(i, {generar:true, editar:true})}</td></tr>`).join('') : '';
  host().innerHTML = `<div class="card-head"><h2>Informes técnicos</h2>
    ${C().puedeEscribir() ? '<button class="btn naranja sm" id="b-inf-nuevo">+ Informe</button>' : ''}</div>
    <p class="small muted">Carga PDF, audio de visita o chat de WhatsApp (.txt / .zip). Gemini redacta el informe y la oferta.</p>
    ${C().puedeEscribir() ? `<div class="acciones" style="margin-bottom:12px">
      <input type="file" id="inf-file" accept=".pdf,application/pdf,audio/*,.mp3,.wav,.m4a,.ogg,.opus,.txt,.zip,image/*" multiple>
      <button type="button" class="btn naranja sm" id="b-inf-pdf">Analizar y generar informe + oferta</button>
    </div>` : ''}
    ${tabla(['Código','Título','Cliente',''], cuerpo)}`;
  const bn = $('b-inf-nuevo');
  if(bn) bn.addEventListener('click', () => formInforme(null));
  const bp = $('b-inf-pdf');
  if(bp) bp.addEventListener('click', async () => {
    const files = $('inf-file') && $('inf-file').files;
    if(!files || !files.length){ C().toast('Elige PDF, audio o chat de WhatsApp.', true); return; }
    try{
      const r = await C().apiUploadMany('/analisis', files, {
        tipo: C().inferirTipoAnexo ? C().inferirTipoAnexo(files[0], 'informe_tecnico') : 'informe_tecnico',
        crear_informe: 'true', crear_oferta: 'true',
      });
      C().toast((r.informe ? 'Informe listo. ' : '') + (r.oferta ? 'Oferta ' + r.oferta.codigo + '.' : ''));
      if(r.oferta && C().abrirOferta){ C().abrirOferta(r.oferta.id); mostrarVista('ofertas'); return; }
      renderInformes();
    }catch(e){ C().toast(e.message, true); }
  });
  host().querySelectorAll('[data-rep]').forEach(b => b.addEventListener('click', () => {
    C().abrirHtml('/informes/' + b.dataset.rep + '/reporte.html');
  }));
  bindAccionesOfficeInforme(host());
  host().querySelectorAll('[data-borrar-inf]').forEach(b => b.addEventListener('click', () => eliminarInformeTecnico(b.dataset.borrarInf, renderInformes)));
  host().querySelectorAll('[data-of]').forEach(b => b.addEventListener('click', async () => {
    if(!confirm('¿Crear la oferta comercial a partir de este informe, con el margen de Generales?')) return;
    try{
      const o = await C().apiJson('/informes/' + b.dataset.of + '/generar-oferta', {method:'POST', body: JSON.stringify({})});
      C().toast('Oferta ' + o.codigo + ' creada.');
      C().abrirOferta && C().abrirOferta(o.id);
      mostrarVista('ofertas');
    }catch(e){ C().toast(e.message, true); }
  }));
  host().querySelectorAll('[data-editar]').forEach(b => {
    const rec = filas.find(x => x.id === b.dataset.editar);
    if(rec) formInforme(rec);
  });
}

function accionesInformeTecnico(i, extra){
  extra = extra || {};
  const oo = i.archivo_office && i.anexo_id && C().onlyOfficeActivo && C().onlyOfficeActivo();
  const etq = /\.xls/i.test(i.anexo_nombre||'') ? 'Abrir Excel' : 'Abrir Word';
  return `
    <button class="btn ghost sm" data-rep="${C().esc(i.id)}">Imprimir</button>
    ${oo ? `<button class="btn ghost sm" data-oo-origen="anexo" data-oo-id="${C().esc(i.anexo_id)}" data-oo-nombre="${C().esc(i.anexo_nombre||'informe')}">${etq}</button>` : ''}
    ${extra.generar && C().puedeEscribir() ? `<button class="btn sm" data-of="${C().esc(i.id)}">Generar oferta</button>` : ''}
    ${extra.editar && C().puedeEscribir() ? `<button class="btn ghost sm" data-editar="${C().esc(i.id)}">Editar ficha</button>` : ''}
    ${C().puedeEscribir() ? `<button class="btn peligro sm" data-borrar-inf="${C().esc(i.id)}">Eliminar</button>` : ''}`;
}

function bindAccionesOfficeInforme(root){
  (root || document).querySelectorAll('[data-oo-origen]').forEach(b => {
    b.addEventListener('click', () => {
      if(C().abrirOnlyOffice) C().abrirOnlyOffice(b.dataset.ooOrigen, b.dataset.ooId, b.dataset.ooNombre);
    });
  });
}

async function eliminarInformeTecnico(id, recargar){
  if(!confirm('¿Eliminar este informe técnico?')) return;
  try{
    await C().apiJson('/informes/' + id, {method:'DELETE'});
    C().toast('Informe técnico eliminado.');
    recargar();
  }catch(e){ C().toast(e.message, true); }
}

function formInforme(rec){
  host().innerHTML = formCard(rec?'Editar informe':'Nuevo informe técnico', [
    inp('titulo','Título', rec&&rec.titulo, {req:true, span2:true}),
    inp('codigo','Código (p. ej. NS-ORI-26-05-001-AG)', rec&&rec.codigo),
    inp('cliente_razon_social','Cliente', rec&&rec.cliente_razon_social),
    inp('cliente_rif','RIF', rec&&rec.cliente_rif),
    inp('resumen','Resumen / cuerpo del informe', rec&&rec.resumen, {tipo:'textarea'}),
  ].join(''), 'Guardar');
  bindForm('/informes', rec&&rec.id, renderInformes);
}

async function renderReportes(){
  host().innerHTML = `<div class="card-head"><h2>Reportes</h2></div>
    <p class="small muted">Oferta comercial e informe técnico para imprimir o guardar en PDF. Algunas ofertas llevan ambos.</p>
    <p class="muted">Cargando…</p>`;
  try{
    const r = await C().apiJson('/reportes');
    const of = (r.ofertas||[]).map(o => `<tr>
      <td class="mono">${C().esc(o.codigo)}</td>
      <td>${C().esc(o.titulo)}<div class="small muted">${C().esc(o.cliente)} · margen ${C().esc(o.margen_pct)}%</div></td>
      <td>${o.origen==='tecnica'?'Técnica':'Comercial'}</td>
      <td class="num">${C().dinero(o.total)}</td>
      <td><button class="btn ghost sm" data-of="${C().esc(o.id)}">Imprimir oferta</button></td></tr>`).join('');
    const inf = (r.informes||[]).map(i => `<tr>
      <td class="mono">${C().esc(i.codigo||'—')}</td>
      <td>${C().esc(i.titulo)}<div class="small muted">${C().esc(i.cliente||'')}${i.anexo_nombre?' · '+C().esc(i.anexo_nombre):''}</div></td>
      <td class="acciones">${accionesInformeTecnico(i)}</td></tr>`).join('');
    host().innerHTML = `<div class="card-head"><h2>Reportes</h2></div>
      <p class="aviso info">La oferta comercial y el informe técnico se imprimen por separado.
        Si el informe es Word o Excel, ábrelo en OnlyOffice. También se puede eliminar.</p>
      <h3 style="margin:12px 0 6px">Ofertas comerciales</h3>
      ${tabla(['Código','Título','Origen','Total',''], of)}
      <h3 style="margin:18px 0 6px">Informes técnicos</h3>
      ${tabla(['Código','Título',''], inf)}`;
    host().querySelectorAll('[data-of]').forEach(b => b.addEventListener('click', () => C().abrirHtml('/ofertas/' + b.dataset.of + '/reporte.html')));
    host().querySelectorAll('[data-rep]').forEach(b => b.addEventListener('click', () => C().abrirHtml('/informes/' + b.dataset.rep + '/reporte.html')));
    bindAccionesOfficeInforme(host());
    host().querySelectorAll('[data-borrar-inf]').forEach(b => b.addEventListener('click', () => eliminarInformeTecnico(b.dataset.borrarInf, renderReportes)));
  }catch(e){ host().innerHTML = `<div class="aviso bad">${C().esc(e.message)}</div>`; }
}

function renderTareas(){
  return crudLista({
    titulo: 'Tareas', path: '/tareas',
    ayuda: 'Pendientes comerciales: visita, envío de oferta, negociación.',
    headers: ['Título', 'Estado', 'Vence', 'Asignado', ''],
    fila: t => `<tr><td>${C().esc(t.titulo)}<div class="small muted">${C().esc(t.descripcion||'')}</div></td>
      <td><span class="estado ${t.estado}">${ETQ_TAREA[t.estado]||t.estado}</span></td>
      <td>${C().esc(t.vencimiento||'—')}</td><td>${C().esc(t.asignado_a||'—')}</td>
      <td>${C().puedeEscribir()?filaAcciones(t.id):''}</td></tr>`,
    form(rec){
      host().innerHTML = formCard(rec?'Editar tarea':'Nueva tarea', [
        inp('titulo','Título', rec&&rec.titulo, {req:true, span2:true}),
        inp('estado','Estado', rec&&rec.estado||'pendiente', {tipo:'select', ops:Object.keys(ETQ_TAREA).map(k=>[k,ETQ_TAREA[k]])}),
        inp('vencimiento','Vencimiento', rec&&rec.vencimiento, {}),
        inp('asignado_a','Asignado a', rec&&rec.asignado_a),
        inp('descripcion','Descripción', rec&&rec.descripcion, {tipo:'textarea'}),
      ].join(''), 'Guardar');
      const v = host().querySelector('[name=vencimiento]');
      if(v) v.type = 'date';
      bindForm('/tareas', rec&&rec.id, renderTareas);
    },
  });
}

function renderDocumentos(){
  return crudLista({
    titulo: 'Documentos', path: '/documentos',
    ayuda: 'Referencias a pliegos, planos o anexos. Los archivos de la oferta se abren con OnlyOffice en Ofertas.',
    headers: ['Título', 'Tipo', 'Enlace', ''],
    fila: d => `<tr><td>${C().esc(d.titulo)}<div class="small muted">${C().esc(d.notas||'')}</div></td>
      <td>${C().esc(d.tipo)}</td>
      <td>${d.url?`<a href="${C().esc(d.url)}" target="_blank" rel="noopener">Abrir</a>`:'—'}</td>
      <td>${C().puedeEscribir()?filaAcciones(d.id):''}</td></tr>`,
    form(rec){
      host().innerHTML = formCard(rec?'Editar documento':'Nuevo documento', [
        inp('titulo','Título', rec&&rec.titulo, {req:true, span2:true}),
        inp('tipo','Tipo', rec&&rec.tipo||'general'),
        inp('url','URL o ruta', rec&&rec.url, {span2:true}),
        inp('notas','Notas', rec&&rec.notas, {tipo:'textarea'}),
      ].join(''), 'Guardar');
      bindForm('/documentos', rec&&rec.id, renderDocumentos);
    },
  });
}

async function renderUsuarios(){
  host().innerHTML = '<p class="muted">Cargando usuarios…</p>';
  let filas = [];
  try{ filas = await C().apiJson('/usuarios'); }
  catch(e){ host().innerHTML = `<div class="aviso bad">${C().esc(e.message)}</div>`; return; }
  const cuerpo = filas.map(u => `<tr>
    <td><strong>${C().esc(u.usuario)}</strong><div class="small muted">${C().esc(u.nombre)}</div></td>
    <td>${C().esc(u.rol)}</td>
    <td>${u.activo?'Activo':'Inactivo'}</td>
    <td>${u.totp_activo?'2FA':'Pendiente'}</td>
    <td>${u.telegram_vinculado ? (u.telegram_username ? '@'+C().esc(u.telegram_username) : 'Sí') : '—'}</td>
    <td>${C().esc(u.email||'—')}</td>
    <td class="acciones">
      <button class="btn ghost sm" data-editar="${u.id}">Editar</button>
      <button class="btn ghost sm" data-clave="${u.id}">Clave</button>
      ${u.telegram_vinculado ? `<button class="btn ghost sm" data-tg-unlink="${u.id}">Quitar Telegram</button>` : ''}
      <button class="btn peligro sm" data-borrar="${u.id}">Quitar</button>
    </td></tr>`).join('');
  host().innerHTML = `<div class="card-head"><h2>Usuarios</h2>
    <button class="btn naranja sm" id="b-mod-nuevo">+ Nuevo</button></div>
    <p class="small muted">Cuentas de ESTA instancia. No se comparten con Control de Proyecto. Telegram se vincula con el botón de la barra.</p>
    ${tabla(['Usuario','Rol','Estado','2FA','Telegram','Correo',''], cuerpo)}`;
  $('b-mod-nuevo').addEventListener('click', () => formUsuario(null));
  host().querySelectorAll('[data-editar]').forEach(b => {
    const rec = filas.find(x => x.id === b.dataset.editar);
    if(rec) formUsuario(rec);
  });
  host().querySelectorAll('[data-clave]').forEach(b => b.addEventListener('click', async () => {
    const clave = prompt('Nueva clave temporal (mínimo 8 caracteres):');
    if(!clave || clave.length < 8) return;
    try{
      await C().apiJson('/usuarios/' + b.dataset.clave + '/reset-password', {method:'POST', body: JSON.stringify({password: clave})});
      C().toast('Clave restablecida. El usuario deberá cambiarla al entrar.');
    }catch(e){ C().toast(e.message, true); }
  }));
  host().querySelectorAll('[data-borrar]').forEach(b => b.addEventListener('click', async () => {
    if(!confirm('¿Eliminar este usuario?')) return;
    try{ await C().apiJson('/usuarios/' + b.dataset.borrar, {method:'DELETE'}); C().toast('Usuario eliminado.'); renderUsuarios(); }
    catch(e){ C().toast(e.message, true); }
  }));
  host().querySelectorAll('[data-tg-unlink]').forEach(b => b.addEventListener('click', async () => {
    if(!confirm('¿Desvincular Telegram de este usuario? Dejará de recibir avisos.')) return;
    try{
      await C().apiJson('/telegram/vinculo/' + b.dataset.tgUnlink, {method:'DELETE'});
      C().toast('Telegram desvinculado.');
      renderUsuarios();
    }catch(e){ C().toast(e.message, true); }
  }));
}

function formUsuario(rec){
  host().innerHTML = formCard(rec?'Editar usuario':'Nuevo usuario', [
    rec ? `<label>Usuario<input value="${C().esc(rec.usuario)}" disabled></label>` : inp('usuario','Usuario', '', {req:true}),
    inp('nombre','Nombre', rec&&rec.nombre, {req:true}),
    inp('rol','Rol', rec&&rec.rol||'analista', {tipo:'select', ops:[['admin','admin'],['analista','analista'],['auditor','auditor'],['tecnico','tecnico']]}),
    rec ? inp('activo','Activo', rec.activo ? 'true' : 'false', {tipo:'select', ops:[['true','Activo'],['false','Inactivo']]}) : '',
    rec ? '' : inp('password','Clave temporal', '', {req:true}),
    inp('email','Correo', rec&&rec.email),
  ].join(''), 'Guardar');
  if(rec){
    const f = $('f-mod');
    $('b-cancelar').addEventListener('click', renderUsuarios);
    f.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const fd = new FormData(f);
      const body = {nombre: fd.get('nombre'), rol: fd.get('rol'), activo: fd.get('activo')==='true', email: fd.get('email')||null};
      try{ await C().apiJson('/usuarios/' + rec.id, {method:'PATCH', body: JSON.stringify(body)}); C().toast('Usuario actualizado.'); renderUsuarios(); }
      catch(e){ C().toast(e.message, true); }
    });
  }else{
    bindForm('/usuarios', null, renderUsuarios);
  }
}

async function renderAuditoria(){
  host().innerHTML = '<p class="muted">Cargando bitácora…</p>';
  try{
    const ev = await C().apiJson('/auditoria?limit=120');
    const cuerpo = ev.map(e => `<tr>
      <td>${C().fecha(e.timestamp)}</td>
      <td>${C().esc(e.usuario_nombre||'—')}</td>
      <td>${C().esc(e.accion)}</td>
      <td>${C().esc(e.entidad||'')} ${C().esc(e.entidad_id||'')}</td>
      <td>${C().esc(e.resultado)}</td>
      <td>${C().esc(e.detalle||'')}</td></tr>`).join('');
    host().innerHTML = `<div class="card-head"><h2>Auditoría</h2></div>
      <p class="small muted">Actividad de personas (login, ofertas, fichas). Los errores de MCP, Telegram o disco están en Eventos (13).</p>
      ${tabla(['Cuando','Quién','Acción','Entidad','Resultado','Detalle'], cuerpo)}`;
  }catch(e){ host().innerHTML = `<div class="aviso bad">${C().esc(e.message)}</div>`; }
}

function fmtBytes(n){
  const x = Number(n || 0);
  if(x < 1024) return x + ' B';
  if(x < 1048576) return (x / 1024).toFixed(1) + ' KB';
  if(x < 1073741824) return (x / 1048576).toFixed(1) + ' MB';
  return (x / 1073741824).toFixed(1) + ' GB';
}

async function renderEventos(){
  host().innerHTML = '<p class="muted">Cargando eventos…</p>';
  try{
    const [res, ev] = await Promise.all([
      C().apiJson('/eventos/resumen'),
      C().apiJson('/eventos?limit=150'),
    ]);
    const disco = res.disco || {};
    const pct = disco.usado_pct;
    const kpiCls = (n, umbral) => (Number(n) >= umbral ? 'kpi bad' : 'kpi');
    const kpis = [
      ['Errores 24 h', res.errores_24h || 0, kpiCls(res.errores_24h, 1)],
      ['Alertas MCP 24 h', res.alertas_mcp_24h || 0, kpiCls(res.alertas_mcp_24h, 1)],
      ['Telegram vinculados', res.telegram_vinculados || 0, 'kpi'],
      ['Disco usado', pct == null ? '—' : (pct + '%'), Number(pct) >= 85 ? 'kpi naranja' : 'kpi'],
    ];
    const tg = (res.telegram && res.telegram.usuarios) || [];
    const cuerpoTg = tg.map(u => `<tr>
      <td>${C().esc(u.nombre || u.usuario)}</td>
      <td>${C().esc(u.rol)}</td>
      <td>${u.telegram_username ? '@'+C().esc(u.telegram_username) : '—'}</td>
      <td>${C().fecha(u.vinculado_en)}</td></tr>`).join('');
    const cuerpo = ev.map(e => `<tr class="${e.resultado==='error'||e.resultado==='denegado'?'error':''}">
      <td>${C().fecha(e.timestamp)}</td>
      <td>${C().esc(e.accion)}</td>
      <td>${C().esc(e.resultado)}</td>
      <td>${C().esc(e.usuario_nombre||'—')}</td>
      <td>${C().esc(e.entidad||'')} ${C().esc(e.entidad_id||'')}</td>
      <td>${C().esc(e.detalle||'')}</td></tr>`).join('');
    const libre = disco.libre != null ? 'Libre ' + fmtBytes(disco.libre) : '';
    host().innerHTML = `<div class="card-head"><h2>Eventos</h2>
      <button type="button" class="btn ghost sm" id="b-ev-ref">Actualizar</button></div>
      <p class="small muted">Sucesos de esta instancia (MCP, bloqueos, Telegram, disco). La actividad de personas está en Auditoría (12).</p>
      <div class="kpi-grid">${kpis.map(([l,n,cls]) => `<div class="${cls}"><div class="n">${C().esc(n)}</div><div class="l">${l}</div></div>`).join('')}</div>
      ${libre ? `<p class="small muted">${C().esc(libre)}${disco.total ? ' de ' + fmtBytes(disco.total) : ''}</p>` : ''}
      <h3>Telegram vinculados</h3>
      ${tg.length ? tabla(['Nombre','Rol','Usuario','Desde'], cuerpoTg) : '<p class="muted">Nadie vinculado aún. El token se pega en Generales (16).</p>'}
      <h3>Bitácora de sistema</h3>
      ${tabla(['Cuando','Acción','Resultado','Quién','Entidad','Detalle'], cuerpo)}`;
    $('b-ev-ref').addEventListener('click', renderEventos);
  }catch(e){ host().innerHTML = `<div class="aviso bad">${C().esc(e.message)}</div>`; }
}

async function descargarRespaldo(nombre){
  const res = await C().api('/respaldos/' + encodeURIComponent(nombre));
  if(!res.ok){
    const data = await res.json().catch(() => null);
    throw new Error((data && data.detail) || ('HTTP ' + res.status));
  }
  const blob = await res.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = nombre;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2500);
}

async function renderRespaldos(){
  host().innerHTML = '<p class="muted">Cargando respaldos…</p>';
  const admin = C().auth && C().auth.rol === 'admin';
  try{
    const data = await C().apiJson('/respaldos');
    const filas = data.archivos || [];
    const cuerpo = filas.map(a => `<tr>
      <td class="mono">${C().esc(a.nombre)}</td>
      <td>${C().esc(a.tipo)}</td>
      <td>${C().esc(a.tamano)}</td>
      <td>${C().fecha(a.creado_en)}</td>
      <td class="acciones">
        <button type="button" class="btn ghost sm" data-dl="${C().esc(a.nombre)}">Descargar</button>
        ${admin && a.tipo === 'datos' ? `<button type="button" class="btn peligro sm" data-rs="${C().esc(a.nombre)}">Restaurar</button>` : ''}
      </td></tr>`).join('');
    host().innerHTML = `<div class="card-head"><h2>Respaldo</h2>
      ${admin ? `<div class="acciones">
        <button type="button" class="btn naranja sm" id="b-rb-datos">Generar datos</button>
        <button type="button" class="btn ghost sm" id="b-rb-app">Generar aplicación</button>
      </div>` : ''}</div>
      <p class="small muted">${C().esc(data.nota_restauracion || 'ZIP de datos (SQL + anexos) o de la aplicación (sin .env).')}</p>
      ${tabla(['Archivo','Tipo','Tamaño','Creado',''], cuerpo)}`;
    const gen = async (tipo) => {
      try{
        const info = await C().apiJson('/respaldos', {method:'POST', body: JSON.stringify({tipo})});
        C().toast('Respaldo ' + (info.nombre || tipo) + ' listo.');
        renderRespaldos();
      }catch(e){ C().toast(e.message, true); }
    };
    const bd = $('b-rb-datos');
    if(bd) bd.addEventListener('click', () => gen('datos'));
    const ba = $('b-rb-app');
    if(ba) ba.addEventListener('click', () => gen('aplicacion'));
    host().querySelectorAll('[data-dl]').forEach(b => b.addEventListener('click', async () => {
      try{ await descargarRespaldo(b.dataset.dl); }
      catch(e){ C().toast(e.message, true); }
    }));
    host().querySelectorAll('[data-rs]').forEach(b => b.addEventListener('click', async () => {
      if(!confirm('Se sustituyen los datos actuales de esta instancia. ¿Continuar?')) return;
      const frase = prompt('Escribe exactamente: restaurar cotizacion');
      if(frase == null) return;
      try{
        await C().apiJson('/respaldos/' + encodeURIComponent(b.dataset.rs) + '/restaurar', {
          method: 'POST',
          body: JSON.stringify({confirmar: frase, entendido: true}),
        });
        C().toast('Datos restaurados. Recarga la página.');
      }catch(e){ C().toast(e.message, true); }
    }));
  }catch(e){ host().innerHTML = `<div class="aviso bad">${C().esc(e.message)}</div>`; }
}

async function renderEscenarios(){
  host().innerHTML = '<p class="muted">Cargando escenarios…</p>';
  let filas = [], users = [];
  let origen = 'Catálogo local. Elige el SBC en Generales (16) para tomar sus periodos de contratación.';
  let puedeCrear = true;
  try{
    const est = await C().apiJson('/mcp/estado');
    if(est.destino_id){
      puedeCrear = false;
      const sede = est.sede_nombre || est.destino_id;
      try{
        const sync = await C().apiJson('/mcp/escenarios/sincronizar', {method:'POST'});
        if(sync.ok && (sync.escenarios || []).some(e => e.del_sbc)){
          origen = 'Del SBC <b>' + C().esc(sync.sede || sede) + '</b>. Los periodos los publica ese nodo; aquí se asignan usuarios y el escenario por defecto.';
        }else if(sync.ok){
          origen = 'SBC <b>' + C().esc(sync.sede || sede) + '</b> aún no reporta escenarios. Cuando latee al MCP, pulsa Actualizar.';
        }else{
          origen = 'SBC <b>' + C().esc(sede) + '</b>. ' + C().esc(sync.motivo || 'No se pudo sincronizar.');
        }
      }catch(e){
        origen = 'SBC <b>' + C().esc(sede) + '</b>. ' + C().esc(e.message);
      }
    }
  }catch(_e){ /* MCP no configurado: se queda el catálogo local */ }
  try{
    filas = await C().apiJson('/escenarios');
    users = await C().apiJson('/usuarios');
  }catch(e){ host().innerHTML = `<div class="aviso bad">${C().esc(e.message)}</div>`; return; }
  const cuerpo = filas.map(e => `<tr>
    <td><strong>${C().esc(e.nombre)}</strong>${e.por_defecto?' <span class="chip">por defecto</span>':''}</td>
    <td>${C().esc(e.estado)}</td>
    <td>${e.n_proyectos} ofertas · ${e.n_usuarios} usuarios</td>
    <td>${C().esc(e.fecha_inicio||'')} → ${C().esc(e.fecha_fin||'')}</td>
    <td class="acciones">
      <button class="btn ghost sm" data-asig="${e.id}">Asignar</button>
      ${e.por_defecto?'':`<button class="btn ghost sm" data-def="${e.id}">Por defecto</button>`}
    </td></tr>`).join('');
  const accionesHead = puedeCrear
    ? '<button class="btn naranja sm" id="b-mod-nuevo">+ Nuevo</button>'
    : '<button class="btn ghost sm" id="b-sync-esc">Actualizar desde SBC</button>';
  host().innerHTML = `<div class="card-head"><h2>Escenarios</h2>
    ${accionesHead}</div>
    <p class="small muted">${origen}</p>
    ${tabla(['Escenario','Estado','Uso','Vigencia',''], cuerpo || '<tr><td colspan="5">No hay escenarios.</td></tr>')}`;
  const syncBtn = $('b-sync-esc');
  if(syncBtn){
    syncBtn.addEventListener('click', async () => {
      try{
        const r = await C().apiJson('/mcp/escenarios/sincronizar', {method:'POST'});
        C().toast(r.ok ? ('Sincronizado' + (r.sede ? ' desde ' + r.sede : '') + '.') : (r.motivo || 'Sin catálogo'));
        renderEscenarios();
      }catch(e){ C().toast(e.message, true); }
    });
  }
  const nuevo = $('b-mod-nuevo');
  if(nuevo) nuevo.addEventListener('click', () => {
    host().innerHTML = formCard('Nuevo escenario', [
      inp('razon_social','Razón social', 'ORIOL CONSULTORES', {req:true}),
      inp('periodo_contratacion','Periodo', '2026-2027', {req:true}),
      inp('fecha_inicio','Inicio', '', {req:true}),
      inp('fecha_fin','Fin', '', {req:true}),
    ].join(''), 'Crear');
    host().querySelector('[name=fecha_inicio]').type = 'date';
    host().querySelector('[name=fecha_fin]').type = 'date';
    bindForm('/escenarios', null, renderEscenarios);
  });
  host().querySelectorAll('[data-def]').forEach(b => b.addEventListener('click', async () => {
    try{ await C().apiJson('/escenarios/' + b.dataset.def, {method:'PATCH', body: JSON.stringify({por_defecto:true})}); C().toast('Marcado por defecto.'); renderEscenarios(); }
    catch(e){ C().toast(e.message, true); }
  }));
  host().querySelectorAll('[data-asig]').forEach(b => b.addEventListener('click', async () => {
    const id = b.dataset.asig;
    let asign = [];
    try{ asign = await C().apiJson('/escenarios/' + id + '/asignaciones'); }
    catch(e){ C().toast(e.message, true); return; }
    const map = Object.fromEntries(asign.map(a => [a.usuario_id, a.acceso]));
    host().innerHTML = `<div class="card-head"><h2>Asignaciones</h2></div>
      <form id="f-asig">${users.map(u => `<label style="flex-direction:row;align-items:center;gap:8px">
        <input type="checkbox" name="u" value="${u.id}" ${map[u.id]?'checked':''}>
        <span>${C().esc(u.nombre)} (${C().esc(u.usuario)})</span>
        <select name="a-${u.id}"><option value="lectura_escritura" ${map[u.id]==='lectura_escritura'?'selected':''}>Lectura y escritura</option>
        <option value="lectura" ${map[u.id]==='lectura'?'selected':''}>Solo lectura</option></select>
      </label>`).join('')}
      <div class="acciones"><button class="btn">Guardar</button>
        <button type="button" class="btn ghost" id="b-cancelar">Volver</button></div></form>`;
    $('b-cancelar').addEventListener('click', renderEscenarios);
    $('f-asig').addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const asignaciones = Array.from(host().querySelectorAll('input[name=u]:checked')).map(chk => ({
        usuario_id: chk.value, acceso: host().querySelector('[name="a-'+chk.value+'"]').value,
      }));
      try{
        await C().apiJson('/escenarios/' + id + '/asignaciones', {method:'PUT', body: JSON.stringify({asignaciones})});
        C().toast('Asignaciones guardadas.');
        renderEscenarios();
      }catch(e){ C().toast(e.message, true); }
    });
  }));
}

function camposFormulario(form){
  const fd = new FormData(form);
  const out = {};
  const secretos = ['gemini_api_key', 'mcp_token', 'telegram_bot_token', 'telegram_webhook_secret', 'onlyoffice_jwt_secret'];
  const nums = ['iva_pct', 'margen_pct', 'telegram_poll_seconds', 'telegram_emparejar_ttl_min'];
  fd.forEach((v, k) => {
    const raw = String(v);
    if(secretos.indexOf(k) >= 0 && !raw.trim()) return;
    if(nums.indexOf(k) >= 0){ out[k] = Number(raw); return; }
    out[k] = raw.trim() || null;
  });
  return out;
}

function genSec(titulo, nota, campos, extraAcciones){
  return `<section class="gen-sec">
    <div class="card-head"><h3>${titulo}</h3></div>
    <p class="small muted">${nota}</p>
    <form class="form-grid gen-form" data-bloque="${titulo}">${campos}
      <div class="acciones span2">
        <button class="btn" type="submit">Guardar</button>
        ${extraAcciones || ''}
      </div>
    </form>
  </section>`;
}

async function renderGenerales(){
  host().innerHTML = '<p class="muted">Cargando…</p>';
  try{
    const g = await C().apiJson('/generales');
    let destinos = [];
    let mcpOk = false;
    let mcpDetalle = '';
    try{
      const est = await C().apiJson('/mcp/estado');
      destinos = est.destinos || [];
      mcpOk = !!est.ok;
      mcpDetalle = est.detalle || '';
      if(window.COT && window.COT.cargarMcp) await window.COT.cargarMcp();
    }catch(e){ mcpDetalle = e.message; }
    const fuente = g.mcp_fuente === 'generales' ? 'Guardado en Generales'
      : (g.mcp_fuente === 'entorno' ? 'Tomado del entorno (.env); muévelo a Generales' : 'Sin configurar');
    const opsSbc = [['', destinos.length ? '— Elige el SBC de esta instancia —' : '— Guarda el MCP y carga los nodos —']]
      .concat(destinos.map(d => [d.id, d.nombre + (d.sitio_nombre ? ' · ' + d.sitio_nombre : '') + (d.estado && d.estado !== 'en_linea' ? ' (' + d.estado + ')' : '')]));
    if(g.mcp_destino_id && !opsSbc.some(o => o[0] === g.mcp_destino_id)){
      opsSbc.push([g.mcp_destino_id, g.mcp_sede_nombre || g.mcp_destino_id]);
    }
    const oo = g.onlyoffice || {};
    const srcOo = oo.fuente==='generales' ? 'Guardado en Generales' : (oo.fuente==='entorno' ? 'Tomado del entorno (.env)' : 'Sin configurar');
    const estOo = (oo.configurado?'Editor activo. ':'Editor inactivo. ') + srcOo
      + (oo.url ? ' · ' + oo.url : '')
      + (oo.tiene_jwt ? ' · JWT presente' : ' · sin JWT');
    host().innerHTML = `<div class="card-head"><h2>Generales</h2></div>
      <p class="small muted">Cada bloque se guarda por su cuenta: al pulsar Guardar en Empresa no se tocan MCP, Telegram ni OnlyOffice.</p>
      <div class="gen-stack">
        ${genSec('Empresa', 'Razón social, IVA y margen por defecto de las ofertas nuevas.', [
          inp('razon_social','Razón social', g.razon_social),
          inp('rif','RIF', g.rif),
          inp('telefono','Teléfono', g.telefono),
          inp('email','Correo', g.email),
          inp('iva_pct','IVA %', g.iva_pct, {tipo:'number'}),
          inp('moneda','Moneda', g.moneda),
          inp('margen_pct','Margen de ganancia por defecto (%)', g.margen_pct, {tipo:'number'}),
          inp('direccion','Dirección', g.direccion, {tipo:'textarea'}),
          inp('notas','Notas', g.notas, {tipo:'textarea'}),
        ].join(''))}
        ${genSec('Gemini', 'Clave de Google AI Studio. No se vuelve a mostrar. Sirve al OCR y a la oferta comercial.', [
          inp('gemini_model','Modelo Gemini', g.gemini_model || 'gemini-2.5-flash', {span2:true}),
          `<label class="span2">Clave Gemini ${g.gemini_configurado?'<span class="chip">configurada</span>':'(vacío = no cambiar)'}
            <input name="gemini_api_key" type="password" autocomplete="off" placeholder="${g.gemini_configurado?'••••••••':''}"></label>`,
        ].join(''))}
        ${genSec('MCP y SBC', 'Esta instancia cotiza contra <strong>un solo</strong> nodo SBC. De ese nodo salen los escenarios (15).', [
          inp('mcp_url','URL del MCP', g.mcp_url, {span2:true}),
          `<label class="span2">Token del nodo cotización ${g.mcp_token_configurado?'<span class="chip">configurado</span>':'(vacío = no cambiar)'}
            <input name="mcp_token" type="password" autocomplete="off" placeholder="${g.mcp_token_configurado?'••••••••':''}"></label>`,
          `<p class="small muted span2" style="margin:0">${C().esc(fuente)}${mcpOk ? ' · MCP en línea' : (mcpDetalle ? ' · ' + C().esc(mcpDetalle) : '')}</p>`,
          `<label class="span2">SBC destino (único)
            <select name="mcp_destino_id" id="g-sbc">${opsSbc.map(([v,t]) =>
              `<option value="${C().esc(v)}" ${v === (g.mcp_destino_id||'') ? 'selected' : ''}>${C().esc(t)}</option>`).join('')}</select></label>`,
        ].join(''))}
        ${genSec('Telegram', 'Bot de esta instancia (distinto del de Control de Proyecto). Cada usuario se vincula con el botón de la barra.', [
          `<label class="span2">Token del bot ${g.telegram_configurado?'<span class="chip">configurado</span>':'(vacío = no cambiar)'}
            <input name="telegram_bot_token" type="password" autocomplete="off" placeholder="${g.telegram_configurado?'••••••••':''}"></label>`,
          inp('telegram_bot_username','Username del bot (sin @)', g.telegram_bot_username || ''),
          inp('telegram_mode','Modo', g.telegram_mode || 'polling', {tipo:'select', ops:[['polling','Polling (local)'],['webhook','Webhook']]}),
          inp('telegram_poll_seconds','Polling (segundos)', g.telegram_poll_seconds || 3, {tipo:'number', min:2}),
          inp('telegram_emparejar_ttl_min','Caducidad del código (min)', g.telegram_emparejar_ttl_min || 15, {tipo:'number', min:5}),
          `<label class="span2">Secreto del webhook (vacío = no cambiar)
            <input name="telegram_webhook_secret" type="password" autocomplete="off"></label>`,
        ].join(''), '<button type="button" class="btn ghost" id="g-tg-probar">Probar bot</button>')}
        ${genSec('OnlyOffice', 'El mismo Document Server del NUC (puerto 8082). La URL de la API es la de <strong>esta</strong> instancia (:8100).', [
          `<p class="small muted span2" id="g-oo-estado" style="margin:0">${C().esc(estOo)}</p>`,
          inp('onlyoffice_url','URL del Document Server', oo.url || '', {span2:true}),
          inp('onlyoffice_app_url','URL de esta API (vista por OnlyOffice)', oo.app_url || '', {span2:true}),
          `<label class="span2">Secreto JWT ${oo.tiene_jwt?'<span class="chip">configurado</span>':'(vacío = no cambiar)'}
            <input name="onlyoffice_jwt_secret" type="password" autocomplete="new-password" placeholder="${oo.tiene_jwt?'••••••••':''}"></label>`,
        ].join(''), '<button type="button" class="btn ghost" id="g-oo-quitar">Quitar JWT</button>')}
      </div>`;
    const probar = $('g-tg-probar');
    if(probar) probar.addEventListener('click', async () => {
      const tok = (host().querySelector('[name=telegram_bot_token]') || {}).value || '';
      const body = tok.trim() ? {telegram_bot_token: tok.trim()} : {};
      try{
        const r = await C().apiJson('/generales/telegram/probar', {method:'POST', body: JSON.stringify(body)});
        C().toast('Bot @' + (r.username || '—') + ' listo.');
      }catch(e){ C().toast(e.message, true); }
    });
    const quitarJwt = $('g-oo-quitar');
    if(quitarJwt) quitarJwt.addEventListener('click', async () => {
      try{
        await C().apiJson('/generales/onlyoffice', {method:'PUT', body: JSON.stringify({onlyoffice_quitar_jwt: true})});
        C().toast('Secreto JWT de OnlyOffice eliminado.');
        if(window.COT && window.COT.asegurarOnlyOfficeEstado) await window.COT.asegurarOnlyOfficeEstado(true);
        renderGenerales();
      }catch(e){ C().toast(e.message, true); }
    });
    host().querySelectorAll('form.gen-form').forEach(form => {
      form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const bloque = form.dataset.bloque;
        const body = camposFormulario(form);
        try{
          if(bloque === 'OnlyOffice'){
            if(!body.onlyoffice_jwt_secret) delete body.onlyoffice_jwt_secret;
            await C().apiJson('/generales/onlyoffice', {method:'PUT', body: JSON.stringify(body)});
            if(window.COT && window.COT.asegurarOnlyOfficeEstado) await window.COT.asegurarOnlyOfficeEstado(true);
          }else{
            if(bloque === 'MCP y SBC'){
              const sel = form.querySelector('#g-sbc');
              if(sel && sel.value){
                const d = destinos.find(x => x.id === sel.value);
                body.mcp_sede_nombre = d ? d.nombre : (g.mcp_sede_nombre || sel.options[sel.selectedIndex].text);
              }else{
                body.mcp_destino_id = null;
                body.mcp_sede_nombre = null;
              }
            }
            await C().apiJson('/generales', {method:'PUT', body: JSON.stringify(body)});
          }
          C().toast(bloque + ' guardado.');
          renderGenerales();
        }catch(e){ C().toast(e.message, true); }
      });
    });
  }catch(e){ host().innerHTML = `<div class="aviso bad">${C().esc(e.message)}</div>`; }
}

function mostrarVista(sub, opts){
  document.querySelectorAll('.subtab-btn').forEach(b => b.classList.toggle('active', b.dataset.sub === sub));
  $('vista-panel').classList.toggle('hidden', sub !== 'panel');
  $('vista-ofertas').classList.toggle('hidden', sub !== 'ofertas');
  $('vista-modulo').classList.toggle('hidden', sub === 'panel' || sub === 'ofertas');
  const ay = $('paso-ayuda');
  if(ay) ay.textContent = AYUDA[sub] || '';
  actualizarBarraAyudaPaso();
  if(sub === 'panel') return renderPanel();
  if(sub === 'ofertas') return;
  if(sub === 'informes') return renderInformes();
  if(sub === 'reportes') return renderReportes();
  if(sub === 'clientes') return renderClientes(opts);
  if(sub === 'productos') return renderProductos(opts);
  if(sub === 'proveedores') return renderProveedores();
  if(sub === 'contactos') return renderContactos();
  if(sub === 'tareas') return renderTareas();
  if(sub === 'documentos') return renderDocumentos();
  if(sub === 'usuarios') return renderUsuarios();
  if(sub === 'auditoria') return renderAuditoria();
  if(sub === 'eventos') return renderEventos();
  if(sub === 'respaldo') return renderRespaldos();
  if(sub === 'escenarios') return renderEscenarios();
  if(sub === 'generales') return renderGenerales();
}

function aplicarPermisos(){
  const rol = C().auth && C().auth.rol;
  const admin = rol === 'admin';
  const verEventos = admin || rol === 'auditor' || rol === 'TECNICO_NOC_SOC';
  const verRespaldo = admin || rol === 'auditor';
  document.querySelectorAll('.admin-only').forEach(b => {
    const sub = b.dataset.sub;
    let ver = admin;
    if(sub === 'auditoria' || sub === 'eventos') ver = verEventos;
    else if(sub === 'respaldo') ver = verRespaldo;
    b.hidden = !ver;
  });
}

function iniciar(){
  document.querySelectorAll('#control-subnav .subtab-btn').forEach(btn => {
    btn.addEventListener('click', () => mostrarVista(btn.dataset.sub));
  });
  bindAsistenteUI();
  bindTelegramUI();
}

const asistenteState = { abierto:false, modo:'ayuda', enviando:false };

function asistenteVisibleSegunSesion(mostrar){
  const w = $('asistente-widget');
  const p = $('asistente-panel');
  if(w) w.hidden = !mostrar;
  if(!mostrar){
    asistenteState.abierto = false;
    if(p) p.hidden = true;
  }
  const modos = $('asistente-modos');
  const rol = C().auth && C().auth.rol;
  if(modos) modos.hidden = !(mostrar && rol === 'admin');
  const bar = $('paso-ayuda-bar');
  if(bar) bar.hidden = !mostrar;
  if(mostrar) actualizarBarraAyudaPaso();
}

function navBtnPasoActivo(){
  return document.querySelector('#control-subnav .subtab-btn.active');
}
function etiquetaDeNavPaso(btn){
  const lbl = (((btn && btn.querySelector('.subtab-lbl')) || {}).textContent || '').trim();
  const raw = (btn && btn.dataset.paso) || '';
  const paso = raw ? String(raw).padStart(2,'0') : '';
  return { lbl: lbl, paso: paso };
}
function mensajeAyudaDePaso(info){
  if(info.paso && info.lbl) return 'paso '+info.paso+' '+info.lbl;
  return info.lbl || (info.paso ? ('paso '+info.paso) : '');
}
function actualizarBarraAyudaPaso(){
  const txt = $('paso-ayuda-txt');
  const btnAyuda = $('btn-ayuda-paso');
  const nav = navBtnPasoActivo();
  const info = etiquetaDeNavPaso(nav);
  const nombre = info.lbl || 'esta opción';
  if(txt){
    txt.textContent = (info.paso ? ('Paso '+info.paso+' · ') : '') + nombre +
      '. Pulsa el botón para abrir la ayuda de esta opción en el chatbot.';
  }
  if(btnAyuda) btnAyuda.textContent = 'Ayuda de '+nombre;
}
async function abrirAyudaPasoActual(){
  const nav = navBtnPasoActivo();
  if(!nav) return;
  const info = etiquetaDeNavPaso(nav);
  const panel = $('asistente-panel');
  asistenteState.abierto = true;
  asistenteState.modo = 'ayuda';
  if(panel) panel.hidden = false;
  document.querySelectorAll('#asistente-modos button').forEach(b => {
    b.classList.toggle('active', b.dataset.modo === 'ayuda');
  });
  let n = 0;
  while(asistenteState.enviando && n < 50){
    await new Promise(r => setTimeout(r, 100));
    n++;
  }
  const msg = mensajeAyudaDePaso(info);
  if(msg) await enviarAsistente(msg, true);
}

function irAOpcionSistema(destino){
  if(!destino) return;
  mostrarVista(destino);
}

function pintarChipsAsistente(sugerencias){
  const wrap = $('asistente-chips');
  if(!wrap) return;
  wrap.innerHTML = '';
  let fuente = (sugerencias && sugerencias.length) ? sugerencias : null;
  if(!fuente){
    fuente = Array.from(document.querySelectorAll('#control-subnav .subtab-btn'))
      .filter(b => !b.hidden)
      .map(b => ({
        paso: Number(b.dataset.paso || 0),
        num: ((b.querySelector('.subtab-num') || {}).textContent || '').trim(),
        etiqueta: (b.querySelector('.subtab-lbl') || {}).textContent || '',
        id: b.dataset.sub,
        mensaje: (b.querySelector('.subtab-lbl') || {}).textContent || '',
        destino: b.dataset.sub,
      }));
  }
  fuente.forEach(s => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'asistente-chip';
    const num = s.num || (s.paso ? String(s.paso).padStart(2,'0') : '');
    chip.innerHTML = (num ? '<span class="asistente-chip-num">'+num+'</span>' : '') +
      '<span>'+C().esc(s.etiqueta || s.id || '')+'</span>';
    chip.title = num ? ('Paso '+num+' · '+(s.etiqueta||'')) : (s.etiqueta||'');
    chip.addEventListener('click', () => {
      irAOpcionSistema(s.destino);
      enviarAsistente(s.mensaje || s.etiqueta || '', false);
    });
    wrap.appendChild(chip);
  });
}

function appendAsistenteMsg(rol, texto){
  const box = $('asistente-mensajes');
  if(!box) return;
  const div = document.createElement('div');
  div.className = 'asistente-msg '+rol;
  div.textContent = texto || '';
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

async function enviarAsistente(texto, pintarUsuario){
  if(asistenteState.enviando) return;
  const msg = (texto || '').trim();
  if(pintarUsuario && msg) appendAsistenteMsg('user', msg);
  asistenteState.enviando = true;
  try{
    const data = await C().apiJson('/asistente/consultar', {
      method: 'POST',
      body: JSON.stringify({mensaje: msg, modo: asistenteState.modo}),
    });
    appendAsistenteMsg('bot', data.respuesta || '');
    pintarChipsAsistente(data.sugerencias);
    if(data.destino && pintarUsuario) irAOpcionSistema(data.destino);
  }catch(err){
    appendAsistenteMsg('bot', err.message || 'Sin conexión con el asistente.');
  }finally{
    asistenteState.enviando = false;
  }
}

function iniciarAsistenteTrasLogin(){
  asistenteVisibleSegunSesion(true);
  asistenteState.modo = 'ayuda';
  asistenteState.abierto = false;
  const box = $('asistente-mensajes');
  if(box) box.innerHTML = '';
  const panel = $('asistente-panel');
  if(panel) panel.hidden = true;
  document.querySelectorAll('#asistente-modos button').forEach(b => {
    b.classList.toggle('active', b.dataset.modo === 'ayuda');
  });
  pintarChipsAsistente(null);
  actualizarBarraAyudaPaso();
}

function bindAsistenteUI(){
  const toggle = $('asistente-toggle');
  const panel = $('asistente-panel');
  const close = $('asistente-close');
  const form = $('asistente-form');
  const input = $('asistente-input');
  if(toggle) toggle.addEventListener('click', async () => {
    asistenteState.abierto = !asistenteState.abierto;
    if(panel) panel.hidden = !asistenteState.abierto;
    if(asistenteState.abierto){
      const box = $('asistente-mensajes');
      if(box && !box.childElementCount) await enviarAsistente('', false);
    }
  });
  if(close) close.addEventListener('click', () => {
    asistenteState.abierto = false;
    if(panel) panel.hidden = true;
  });
  if(form) form.addEventListener('submit', e => {
    e.preventDefault();
    const t = (input && input.value) || '';
    if(input) input.value = '';
    enviarAsistente(t, true);
  });
  const modos = $('asistente-modos');
  if(modos) modos.addEventListener('click', e => {
    const b = e.target.closest('button[data-modo]');
    if(!b) return;
    asistenteState.modo = b.dataset.modo;
    modos.querySelectorAll('button').forEach(x => x.classList.toggle('active', x === b));
    const box = $('asistente-mensajes');
    if(box) box.innerHTML = '';
    enviarAsistente('', false);
  });
  const btnAyudaPaso = $('btn-ayuda-paso');
  if(btnAyudaPaso) btnAyudaPaso.addEventListener('click', () => abrirAyudaPasoActual());
}

function cerrarModalTelegram(){
  const bd = $('modal-backdrop');
  if(bd) bd.classList.add('hidden');
  const c = $('modal-content');
  if(c) c.innerHTML = '';
}
function abrirHtmlModal(titulo, html){
  const bd = $('modal-backdrop');
  const c = $('modal-content');
  if(!bd || !c) return;
  c.innerHTML = '<h2>'+titulo+'</h2>'+html;
  bd.classList.remove('hidden');
  const cerrar = $('modal-cancel-btn');
  if(cerrar) cerrar.addEventListener('click', cerrarModalTelegram);
  bd.onclick = (ev) => { if(ev.target === bd) cerrarModalTelegram(); };
}

async function abrirModalTelegram(){
  let est;
  try{ est = await C().apiJson('/telegram/estado'); }
  catch(err){
    C().toast('No se pudo consultar Telegram: '+(err.message||err), true);
    return;
  }
  if(!est.habilitado){
    abrirHtmlModal('Avisos por Telegram',
      '<p class="small muted">El administrador aún no pegó el token de @BotFather en <b>16 Generales</b>. Cuando exista, este botón genera un enlace de un solo uso para recibir avisos (seguridad y guía 01–16) en un chat privado.</p>'+
      '<div class="acciones"><button class="btn ghost" id="modal-cancel-btn" type="button">Cerrar</button></div>');
    return;
  }
  if(est.vinculado){
    const quien = est.telegram_username ? '@'+est.telegram_username : 'este chat';
    abrirHtmlModal('Avisos por Telegram',
      '<p class="small muted">Vinculado a <b>'+C().esc(quien)+'</b>. Recibirás avisos de seguridad si eres administrador. En el chat, cada botón (01…16) pide la guía de ese paso. <b>/status</b> es el resumen. Ayuda es esta guía.</p>'+
      '<div class="acciones"><button class="btn ghost" id="modal-cancel-btn" type="button">Cerrar</button>'+
      '<button class="btn peligro sm" id="tg-desvincular" type="button">Desvincular</button></div>');
    const dv = $('tg-desvincular');
    if(dv) dv.addEventListener('click', async () => {
      if(!confirm('¿Dejar de recibir avisos en Telegram?')) return;
      try{
        await C().apiJson('/telegram/vinculo', {method:'DELETE'});
        C().toast('Telegram desvinculado.');
        cerrarModalTelegram();
      }catch(e){ C().toast(e.message, true); }
    });
    return;
  }
  let data;
  try{ data = await C().apiJson('/telegram/emparejar', {method:'POST'}); }
  catch(e){ C().toast(e.message, true); return; }
  const enlace = data.enlace
    ? '<p><a href="'+C().esc(data.enlace)+'" target="_blank" rel="noopener">Abrir Telegram e Iniciar</a></p>'
    : '';
  abrirHtmlModal('Vincular Telegram',
    '<p class="small muted">'+C().esc(data.instruccion||'')+'</p>'+enlace+
    '<p class="mono-cell">/start '+C().esc(data.token||'')+'</p>'+
    '<div class="acciones"><button class="btn ghost" id="modal-cancel-btn" type="button">Cerrar</button></div>');
}
function bindTelegramUI(){
  const btn = $('btn-telegram');
  if(btn) btn.addEventListener('click', () => abrirModalTelegram());
}

window.PlataformaCotizacion = {
  mostrarVista, aplicarPermisos, iniciar, AYUDA,
  iniciarAsistenteTrasLogin, asistenteVisibleSegunSesion,
};
})();
