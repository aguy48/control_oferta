/* Prueba integrada del traspaso por el MCP, paso 2 (navegador, Playwright).
 * Control de Proyecto: Contrato → Ofertas recibidas del MCP → Buscar ahora →
 * Crear contrato (proyecto nuevo, cliente registrado por RIF, formulario
 * prellenado) → Crear contrato. Luego verifica en Cotización que la oferta
 * quedó vinculada sola, con el acuse que devolvió el MCP.
 * Uso: node flujo_mcp.js <carpeta_de_preparar.py> */
const { chromium } = require('playwright');
const crypto = require('crypto'); const fs = require('fs');
const DIR = process.argv[2];
const est = JSON.parse(fs.readFileSync(DIR + '/estado.json'));
const CP_WEB = process.env.CP_WEB || 'http://127.0.0.1:8080/control_de_proyecto_app.html';
const COT_WEB = process.env.COT_WEB || 'http://127.0.0.1:8090/sistema_cotizacion.html';
function totp(secret){
  const alf='ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'; let bits='';
  for(const c of secret.replace(/=+$/,'')) bits+=alf.indexOf(c).toString(2).padStart(5,'0');
  const key=Buffer.from(bits.match(/.{8}/g).map(b=>parseInt(b,2)));
  const ctr=Buffer.alloc(8); ctr.writeBigUInt64BE(BigInt(Math.floor(Date.now()/30000)));
  const h=crypto.createHmac('sha1',key).update(ctr).digest(); const o=h[19]&15;
  return String(((h.readUInt32BE(o)&0x7fffffff)%1e6)).padStart(6,'0');
}
(async()=>{
  const b = await chromium.launch();
  // ---------------- Control de Proyecto (SBC)
  const cp = await b.newPage({viewport:{width:1400,height:950}});
  const err=[]; cp.on('pageerror',e=>err.push('CP: '+e.message));
  const dialogos=[];
  cp.on('dialog', async d=>{
    const m = d.message(); dialogos.push(m.split('\n')[0]);
    if(/en el proyecto actual/.test(m)) return d.dismiss();          // → proyecto nuevo
    if(d.type()==='prompt') return d.accept(d.defaultValue());        // nombre del proyecto
    return d.accept();                                                // registrar cliente, avisos
  });
  await cp.goto(CP_WEB);
  await cp.fill('#login-usuario','admin'); await cp.fill('#login-password', est.cp_clave); await cp.click('#login-submit-btn');
  await cp.waitForSelector('#login-totp-wrap', {state:'visible'});
  await cp.fill('#login-totp', totp(est.cp_totp)); await cp.click('#login-submit-btn');
  await cp.waitForTimeout(2500);
  const escOv = await cp.$('#escenario-overlay');
  if(escOv && await escOv.isVisible()){ await cp.click('#escenario-lista button'); await cp.waitForTimeout(2500); }
  await cp.evaluate(()=>{ const b=document.querySelector('#control-subnav .subtab-btn[data-sub="contrato"]'); if(b) b.click(); });
  await cp.waitForSelector('#btn-ofertas-mcp', {state:'visible'});
  await cp.click('#btn-ofertas-mcp');
  await cp.waitForSelector('#mcp-sincronizar');
  await cp.click('#mcp-sincronizar');                                  // latido ya → baja la oferta
  await cp.waitForSelector('[data-mcp-aceptar]', {timeout:20000});
  await cp.screenshot({path: DIR + '/cp_bandeja_mcp.png'});
  await cp.click('[data-mcp-aceptar]');
  await cp.waitForSelector('#f-c-oferta-mcp-nota', {timeout:30000});
  await cp.fill('#f-c-numero', '4600012345');
  await cp.fill('#f-c-monto', '46090.07');
  const pre = await cp.evaluate(()=>({
    empresa: document.getElementById('f-c-empresa').selectedOptions[0].textContent,
    tipo: document.getElementById('f-c-modalidad').value, clase: (document.getElementById('f-c-clase')||{}).value,
    plazo: document.getElementById('f-c-plazo').value, nota: document.getElementById('f-c-oferta-mcp-nota').textContent }));
  console.log('formulario prellenado:', JSON.stringify(pre));
  await cp.screenshot({path: DIR + '/cp_contrato_desde_mcp.png'});
  await cp.click('#modal-save-btn');
  await cp.waitForFunction(()=>true); await cp.waitForTimeout(5000);
  const frentes = await cp.$$eval('#val-frente-select option', os=>os.map(o=>o.textContent).filter(Boolean));
  console.log('frentes en Valuaciones de CP:', frentes.join(' | '));
  console.log('diálogos CP:', dialogos.join(' ⟶ '));
  // ---------------- Sistema de Cotización
  const cot = await b.newPage({viewport:{width:1360,height:900}});
  cot.on('pageerror',e=>err.push('COT: '+e.message));
  await cot.goto(COT_WEB);
  await cot.fill('#l-usuario','admin'); await cot.fill('#l-password', est.cot_clave); await cot.click('#l-btn');
  await cot.waitForSelector('#l-totp-wrap:not(.hidden)'); await cot.fill('#l-totp', totp(est.cot_totp)); await cot.click('#l-btn');
  await cot.waitForSelector('#app:not(.hidden)');
  await cot.click('#lista li[data-id]');
  await cot.waitForSelector('#b-mcp-sinc, .chip:has-text("Vinculada")');
  if(await cot.$('#b-mcp-sinc')){ await cot.click('#b-mcp-sinc'); }
  await cot.waitForSelector('.chip:has-text("Vinculada")', {timeout:20000});
  const card = await cot.$('.card[style*="naranja"]'); await card.screenshot({path: DIR + '/cot_vinculada_por_mcp.png'});
  console.log('Cotización:', (await cot.textContent('.pasos li:last-child .aviso')).replace(/\s+/g,' ').trim());
  console.log('errores JS:', err.length ? err : 'ninguno');
  await b.close();
})().catch(e=>{ console.error('FALLO:', e.message); process.exit(1); });
