// Enriquecimento estático estilo nutcracker: varre o APK ligado em busca de
// packers/ofuscadores/RASP conhecidos. Só leitura — o worker lê nomes de
// entradas do APK validado por SHA, nunca executa o app nem toca a rede.
(() => {
  const card = document.querySelector('#protectionScan');
  if (!card) return;
  const button = document.querySelector('#refreshProtections');
  const summary = document.querySelector('#protectionSummary');
  const list = document.querySelector('#protectionList');
  let busy = false;
  async function scan() {
    if (busy || devicePlatform !== 'android' || !activeLab.id) return;
    busy = true; button.disabled = true; summary.textContent = 'Varrendo o APK ligado…';
    const scope = activeLab.id;
    try {
      const response = await fetch('/api/reverse/protections?workspace=' + encodeURIComponent(activeLab.id), { cache: 'no-store' });
      const data = await response.json();
      if (scope !== activeLab.id) return;
      if (!response.ok || data.ok === false) throw new Error(data.reason || 'Varredura de proteções indisponível.');
      list.replaceChildren();
      if (!data.prepared) { summary.textContent = data.reason || 'Prepare a decompilação no Reverse antes de varrer.'; return; }
      summary.textContent = data.summary;
      for (const item of data.protections) {
        const row = document.createElement('li');
        const title = document.createElement('strong');
        title.textContent = item.name;
        const meta = document.createElement('span');
        meta.textContent = ' — ' + item.vendor + ' · ' + item.category;
        const evidence = document.createElement('small');
        evidence.textContent = item.evidence.join(', ');
        row.append(title, meta, document.createElement('br'), evidence);
        list.append(row);
      }
    } catch (error) { summary.textContent = error.message; notify(error.message); }
    finally { busy = false; button.disabled = false; }
  }
  button.addEventListener('click', scan);
})();
