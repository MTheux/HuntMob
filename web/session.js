// Obtenção do token CSRF da sessão. Isola o tratamento de /api/session para que
// um worker ausente — o gateway responde 502 em HTML quando nenhum worker
// nativo está pareado — vire um erro legível em vez do "Unexpected token '<'"
// que o JSON.parse cru produzia ao tentar interpretar a página de erro.
async function fetchSessionToken() {
  const response = await fetch('/api/session', { cache: 'no-store' });
  if (!(response.headers.get('content-type') || '').includes('application/json')) {
    throw new Error(response.status === 502
      ? 'Worker nativo não pareado. Rode `make native` no host para abrir o laboratório.'
      : `Sessão indisponível (${response.status}). Reconecte o worker e tente de novo.`);
  }
  const session = await response.json();
  return session.csrf_token;
}
