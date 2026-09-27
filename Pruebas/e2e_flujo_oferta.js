/* Prueba de punta a punta del frontend (Playwright).
 * Requiere: backend en :8100 con BD NUEVA (REQUIRE_2FA=true, INITIAL_ADMIN_USER=admin,
 * INITIAL_ADMIN_PASSWORD=AdminPass!2026) y el frontend servido en :8090
 * (cd Frontend && python3 -m http.server 8090).
 * Uso: node Pruebas/e2e_flujo_oferta.js <carpeta_capturas>
 * Recorre: cambio de clave temporal, alta de 2FA, oferta, partidas, modalidad,
 * enviada, ganada, descarga del traspaso, importación fallida, vinculación y bitácora. */
const { chromium } = require('playwright');
const crypto = require('crypto');
const OUT = process.argv[2] || '.';
const WEB = process.env.COT_WEB || 'http://localhost:8090/sistema_cotizacion.html';
function totp(secret){
  const alf='ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'; let bits='';
  for(const c of secret.replace(/=+$/,'')) bits+=alf.indexOf(c).toString(2).padStart(5,'0');
  const key=Buffer.from(bits.match(/.{8}/g).map(b=>parseInt(b,2)));
  const ctr=Buffer.alloc(8); ctr.writeBigUInt64BE(BigInt(Math.floor(Date.now()/30000)));
  const h=crypto.createHmac('sha1',key).update(ctr).digest(); const o=h[19]&15;
  return String(((h.readUInt32BE(o)&0x7fffffff)%1e6)).padStart(6,'0');
}
(async()=>{
  const browser = await chromium.launch();
  const page = await browser.newPage({viewport:{width:1360,height:900}, acceptDownloads:true});
  const errores=[]; page.on('pageerror',e=>errores.push(e.message)); page.on('console',m=>{if(m.type()==='error')errores.push(m.text())});
  page.on('dialog', async d => { console.log('diálogo:', d.message().split('\n')[0]); d.message().startsWith('¿Qué error') ? d.accept('Cliente no registrado en Clientes (12)') : d.accept(); });
  await page.goto(WEB);
  await page.waitForFunction(()=>document.getElementById('login-version').textContent.length>0);
  await page.screenshot({path:OUT+'/01_login.png'});
  await page.fill('#l-usuario','admin'); await page.fill('#l-password','AdminPass!2026'); await page.click('#l-btn');
  await page.waitForSelector('#f-cambio:not(.hidden)');
  await page.fill('#c-nueva','AdminNueva!2026'); await page.fill('#c-repite','AdminNueva!2026'); await page.click('#f-cambio button');
  await page.waitForSelector('#f-2fa:not(.hidden)'); await page.waitForFunction(()=>document.getElementById('t-secret').textContent.length>10);
  await page.screenshot({path:OUT+'/02_2fa.png'});
  const secret = await page.textContent('#t-secret');
  await page.fill('#t-codigo', totp(secret)); await page.click('#f-2fa button');
  await page.waitForSelector('#app:not(.hidden)');
  console.log('escenario:', await page.textContent('#esc-actual'));
  // nueva oferta
  await page.click('#b-nueva');
  await page.fill('[name=titulo]','Mantenimiento Mayor Grupos Electrógenos Centro Empresarial');
  await page.fill('[name=cliente_razon_social]','PDVSA'); await page.fill('[name=cliente_rif]','G-20000043-0');
  await page.click('#f-nueva button');
  await page.waitForSelector('#tb-partidas');
  const partidas=[['Electricidad','1','Mantenimiento de tablero de transferencia automática','UND','2','7658.13','1','4'],
                  ['Electricidad','2','Sustitución de cableado de control','ML','120','12.5','3','3'],
                  ['Mecánica','1','Limpieza y puesta a punto del grupo electrógeno','UNDS','2','11458.28','2','6']];
  for(const p of partidas){
    await page.click('#b-add');
    const rows = await page.$$('#tb-partidas tr:not(.subtotal):not(.total)'); const r = rows[rows.length-1];
    const ks=['disciplina','item','descripcion','unidad','cantidad','precio_unitario','semana_inicio','duracion_semanas'];
    for(let i=0;i<ks.length;i++){ const el=await r.$(`[data-k=${ks[i]}]`); await el.fill(p[i]); await el.dispatchEvent('change'); }
  }
  await page.click('#b-guardar-partidas'); await page.waitForFunction(()=>document.getElementById('toast').textContent.includes('Partidas guardadas'));
  await page.click('[data-mod=detallada]'); await page.waitForSelector('[data-mod=detallada].sel');
  await page.fill('[name=sede_destino]','SBC proyectos.oriol.support'); await page.click('#b-guardar-datos');
  await page.waitForFunction(()=>document.getElementById('toast').textContent.includes('Datos guardados'));
  await page.screenshot({path:OUT+'/03_oferta_borrador.png', fullPage:true});
  await page.click('[data-estado=enviada]'); await page.waitForSelector('[data-estado=ganada]');
  await page.click('[data-estado=ganada]'); await page.waitForSelector('#b-descargar');
  const [dl] = await Promise.all([page.waitForEvent('download'), page.click('#b-descargar')]);
  await dl.saveAs(OUT+'/'+dl.suggestedFilename()); console.log('descarga:', dl.suggestedFilename());
  await page.waitForFunction(()=>document.body.textContent.includes('Descargado 1 vez'));
  await page.click('#b-fallida'); await page.waitForFunction(()=>document.getElementById('toast').textContent.includes('Fallo de importación'));
  await page.fill('[name=proyecto_cp_id]','mant-centro-2026'); await page.fill('[name=contrato_cp_numero]','4600012345');
  await page.click('#f-vinc button'); await page.waitForSelector('.chip:has-text("Vinculada")');
  await page.waitForFunction(()=>document.querySelectorAll('#eventos li').length>5);
  await page.screenshot({path:OUT+'/04_oferta_ganada.png', fullPage:true});
  console.log('eventos:', (await page.$$eval('#eventos .acc', els=>els.map(e=>e.textContent))).join(' | '));
  // teléfono
  await page.setViewportSize({width:390,height:844}); await page.waitForTimeout(300);
  const anchos = await page.evaluate(()=>[document.documentElement.scrollWidth, window.innerWidth]);
  console.log('móvil scrollWidth/innerWidth:', anchos.join('/'));
  await page.screenshot({path:OUT+'/05_movil.png'});
  await page.evaluate(()=>document.querySelector('.tabla-wrap').scrollIntoView());
  await page.screenshot({path:OUT+'/06_movil_partidas.png'});
  console.log('errores JS:', errores.length ? errores : 'ninguno');
  await browser.close();
})().catch(e=>{console.error('FALLO:',e.message);process.exit(1)});
