// Onboarding de primeiro uso: um modal de boas-vindas mostrado uma vez
// (marcado em localStorage) e reabrível pelo controle "?" na topbar.
// Autocontido e aditivo: não altera nenhum fluxo existente; o CTA apenas
// aciona o fluxo de "Novo lab" que já existe.
(function () {
  const dialog = document.querySelector('#welcomeDialog');
  if (!dialog) return;
  const KEY = 'huntmob.welcomeSeen';
  const seen = () => { try { return localStorage.getItem(KEY) === '1'; } catch { return false; } };
  const markSeen = () => { try { localStorage.setItem(KEY, '1'); } catch {} };
  const open = () => { if (!dialog.open) dialog.showModal(); };
  const close = () => { markSeen(); if (dialog.open) dialog.close(); };

  // Fechar sem perder a marca de "já visto".
  document.querySelector('#welcomeClose')?.addEventListener('click', close);
  document.querySelector('#welcomeExplore')?.addEventListener('click', close);
  dialog.addEventListener('cancel', (event) => { event.preventDefault(); close(); });

  // CTA primário: encerra o onboarding e abre o fluxo de criação de lab.
  document.querySelector('#welcomeCreateLab')?.addEventListener('click', () => {
    close();
    document.querySelector('#newLab')?.click();
  });

  // Reabrir a qualquer momento pelo "?" da topbar.
  document.querySelector('#openWelcome')?.addEventListener('click', open);

  // Primeira visita: mostra uma vez, sem disputar com o gate do operador
  // (se houver um modal já aberto, aguarda a próxima oportunidade ou o "?").
  if (!seen() && !document.querySelector('dialog[open]')) open();
})();
