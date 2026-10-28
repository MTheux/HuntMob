// fetch + parse JSON com guarda de content-type. O gateway responde 502 em HTML
// quando nenhum worker nativo está pareado; sem esta guarda, o `.json()` cru
// estoura "Unexpected token '<'" ao tentar interpretar a página de erro. Em vez
// disso, lança uma mensagem acionável. Respostas de erro COM corpo JSON
// (ok:false) passam direto, para o chamador tratar `reason`/`error_code`.
// Defensivo: stubs de teste sem headers.get pulam a guarda e só fazem o parse.
async function guardedParse(input, init) {
  const response = await fetch(input, init);
  const headers = response.headers;
  const type = headers && typeof headers.get === 'function'
    ? (headers.get('content-type') || '')
    : 'application/json';
  if (!type.includes('application/json')) {
    throw new Error(response.status === 502
      ? 'Worker nativo não pareado. Rode `make native` no host para abrir o laboratório.'
      : `Resposta inesperada do servidor (${response.status}). Reconecte o worker e tente de novo.`);
  }
  return { response, body: await response.json() };
}

async function fetchJson(input, init) {
  return (await guardedParse(input, init)).body;
}

// Como fetchJson, mas também lança em !response.ok — para os sites que faziam
// `const p = await response.json(); if(!response.ok) throw p.reason`. Usa
// body.reason/error quando houver, senão `${label} ${status}`.
async function fetchJsonOk(input, init, label) {
  const { response, body } = await guardedParse(input, init);
  if (!response.ok) {
    throw new Error((body && (body.reason || body.error)) || `${label || 'Requisição'} ${response.status}`);
  }
  return body;
}

// Token CSRF da sessão: delega a guarda a fetchJson.
async function fetchSessionToken() {
  const session = await fetchJson('/api/session', { cache: 'no-store' });
  return session.csrf_token;
}
