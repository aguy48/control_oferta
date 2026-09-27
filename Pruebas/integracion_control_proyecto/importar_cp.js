/* Prueba cruzada, paso 2: importa el archivo de traspaso con el formulario
 * REAL de Control de Proyecto (Nuevo contrato → Importar respaldo de oferta)
 * y lista los frentes que quedan en Valuaciones.
 * Uso: node importar_cp.js <carpeta_de_preparar.py>   (Playwright) */
const { chromium } = require('playwright');
const fs = require('fs');
const DIR = process.argv[2];
const crypto = require('crypto');
function totp(secret){
  const alf='ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'; let bits='';
  for(const c of secret.replace(/=+$/,'')) bits+=alf.indexOf(c).toString(2).padStart(5,'0');
  const key=Buffer.from(bits.match(/.{8}/g).map(b=>parseInt(b,2)));
  const ctr=Buffer.alloc(8); ctr.writeBigUInt64BE(BigInt(Math.floor(Date.now()/30000)));
  const h=crypto.createHmac('sha1',key).update(ctr).digest(); const o=h[19]&15;
  return String(((h.readUInt32BE(o)&0x7fffffff)%1e6)).padStart(6,'0');
}
const est = JSON.parse(fs.readFileSync(DIR + '/estado.json'));
(async()=>{
  const b = await chromium.launch();
  const ctx = await b.newContext({viewport:{width:1400,height:950}});
  const page = await ctx.newPage();
  const errores=[]; page.on('pageerror',e=>errores.push(e.message));
  page.on('dialog', async d=>{ console.log('diálogo CP:', d.message().slice(0,140)); await d.accept(); });
  await page.goto(process.env.CP_WEB || 'http://127.0.0.1:8080/control_de_proyecto_app.html');
  await page.fill('#login-usuario','admin'); await page.fill('#login-password', est.cp_clave);
  await page.click('#login-submit-btn');
  await page.waitForSelector('#login-totp-wrap', {state:'visible'});
  await page.fill('#login-totp', totp(est.cp_sesion.totp_secret)); await page.click('#login-submit-btn');
  await page.waitForTimeout(2500);
  // si pide escenario, elegir el primero
  const escOv = await page.$('#escenario-overlay');
  if(escOv && await escOv.isVisible()){ await page.click('#escenario-lista button'); await page.waitForTimeout(2500); }
  await page.screenshot({path: DIR + '/cp_00_entrada.png'});
  await page.waitForFunction(id=>{ const s=document.getElementById('proy-select'); return s && [...s.options].some(o=>o.value===id); }, est.cp_proyecto, {timeout:30000});
  await page.evaluate(id=>{ const s=document.getElementById('proy-select'); s.value=id; s.dispatchEvent(new Event('change',{bubbles:true})); }, est.cp_proyecto);
  await page.waitForTimeout(1500);
  await page.evaluate(()=>document.getElementById('btn-add-contrato').click());
  await page.waitForSelector('#f-c-empresa', {timeout:15000});
  await page.selectOption('#f-c-empresa', est.cp_cliente);
  await page.fill('#f-c-numero', '4600012345');
  const mods = await page.$$eval('#f-c-modalidad option', os=>os.map(o=>o.value));
  console.log('modalidades del formulario CP:', mods.join(', '));
  if(mods.includes('contrato_obra')) await page.selectOption('#f-c-modalidad', 'contrato_obra');
  await page.setInputFiles('#f-c-oferta-respaldo', DIR + '/' + est.archivo);
  await page.screenshot({path: DIR + '/cp_01_formulario_contrato.png'});
  await page.click('#modal-save-btn');
  await page.waitForTimeout(4000);
  // pestaña de valuaciones: los frentes deben salir de la oferta importada
  const frentes = await page.$$eval('#val-frente-select option', os=>os.map(o=>o.textContent).filter(Boolean));
  console.log('frentes en Valuaciones de CP:', frentes.join(' | '));
  await page.screenshot({path: DIR + '/cp_02_tras_importar.png'});
  console.log('errores JS en CP:', errores.length ? errores.slice(0,3) : 'ninguno');
  await b.close();
})().catch(e=>{ console.error('FALLO:', e.message); process.exit(1); });
