/**
 * preciopollo.pe — Despertador del workflow de GitHub.
 * Cada 30 min (lun–sáb, 7:00–20:00 Lima) pide a GitHub que revise gob.pe,
 * salvo que la imagen del día ya exista o haya una corrida en curso.
 */
const REPO = 'elqvixote/precios-pollo-pe';
const WORKFLOW = 'actualizar.yml';
const TZ = 'America/Lima';

function revisar() {
  const ahora = new Date();
  const dia = Number(Utilities.formatDate(ahora, TZ, 'u'));   // 1 = lunes … 7 = domingo
  const hora = Number(Utilities.formatDate(ahora, TZ, 'H'));
  const hoy = Utilities.formatDate(ahora, TZ, 'yyyy-MM-dd');

  if (dia === 7 || hora < 7 || hora >= 20) return;            // fuera de horario

  if (gh_('/contents/imagenes/' + hoy + '.png').getResponseCode() === 200) {
    console.log('El boletín de ' + hoy + ' ya fue procesado.');
    return;
  }

  const enCurso = ['queued', 'in_progress'].some(function (estado) {
    const r = gh_('/actions/workflows/' + WORKFLOW + '/runs?status=' + estado + '&per_page=1');
    return r.getResponseCode() === 200 && JSON.parse(r.getContentText()).total_count > 0;
  });
  if (enCurso) { console.log('Ya hay una corrida en curso.'); return; }

  const r = gh_('/actions/workflows/' + WORKFLOW + '/dispatches', { ref: 'main' });
  if (r.getResponseCode() === 204) console.log('Revisión lanzada (' + hoy + ' ' + hora + 'h).');
  else throw new Error('GitHub respondió ' + r.getResponseCode() + ': ' + r.getContentText());
}

/** Ejecutar UNA vez para crear el disparador cada 30 minutos. */
function crearDisparador() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'revisar') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('revisar').timeBased().everyMinutes(30).create();
  console.log('Disparador creado: revisar() cada 30 minutos.');
}

/** Prueba: lanza una revisión ahora mismo, sin mirar horario ni imagen. */
function probar() {
  const r = gh_('/actions/workflows/' + WORKFLOW + '/dispatches', { ref: 'main' });
  console.log(r.getResponseCode() === 204 ? 'OK: GitHub aceptó la revisión.'
                                          : 'Error ' + r.getResponseCode() + ': ' + r.getContentText());
}

function gh_(ruta, cuerpo) {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('Falta la propiedad GITHUB_TOKEN en Configuración del proyecto.');
  const opciones = {
    method: cuerpo ? 'post' : 'get',
    headers: {
      Authorization: 'Bearer ' + token,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28'
    },
    muteHttpExceptions: true
  };
  if (cuerpo) { opciones.contentType = 'application/json'; opciones.payload = JSON.stringify(cuerpo); }
  return UrlFetchApp.fetch('https://api.github.com/repos/' + REPO + ruta, opciones);
}
