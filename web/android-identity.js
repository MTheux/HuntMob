// Troca o Android ID (Settings.Secure) do emulador como um controle reversível.
// Observa primeiro, guarda o valor original para "voltar ao anterior", e nunca
// manda texto livre ao device — o worker revalida 16 hex ou gera aleatório.
(() => {
  const card = document.querySelector('#androidIdentityCard');
  if (!card) return;
  const value = document.querySelector('#androidIdentityValue');
  const input = document.querySelector('#androidIdInput');
  const applyButton = document.querySelector('#applyAndroidId');
  const randomButton = document.querySelector('#randomAndroidId');
  const restoreButton = document.querySelector('#restoreAndroidId');
  const status = document.querySelector('#androidIdentityActionStatus');
  const hex16 = /^[0-9a-f]{16}$/i;
  let busy = false, original = '', originalScope = '';
  const androidOnline = () => devicePlatform === 'android' && runtimeDevice?.state === 'on' && !!activeLab.id;
  const labScope = () => activeLab.id || '';
  const post = payload => authorizedPost('/api/device/control', {...payload, expected_device_id: activeLab.id});
  function paint() {
    const on = androidOnline();
    applyButton.disabled = busy || !on;
    randomButton.disabled = busy || !on;
    const canRestore = on && hex16.test(original) && original !== value.dataset.current;
    restoreButton.hidden = !canRestore;
    restoreButton.disabled = busy || !on;
  }
  async function read() {
    if (busy) return;
    if (!androidOnline()) { value.textContent = 'Android desligado'; paint(); return; }
    const scope = labScope();
    try {
      const data = await post({action: 'device-identity-read'});
      if (scope !== labScope()) return;
      const id = (data.readback && data.readback.android_id || '').trim();
      value.textContent = id || 'Android ID indisponível';
      value.dataset.current = id;
      if (scope !== originalScope) { original = id; originalScope = scope; }
    } catch (error) { value.textContent = error.message; }
    paint();
  }
  async function apply(androidId, label) {
    if (busy || !androidOnline()) return;
    busy = true; status.textContent = 'Aplicando no Android…'; paint();
    const scope = labScope();
    try {
      const payload = {action: 'device-identity'};
      if (androidId) payload.android_id = androidId;
      const data = await post(payload);
      if (scope === labScope()) {
        const id = (data.readback && data.readback.android_id || '').trim();
        value.textContent = id || 'Android ID indisponível';
        value.dataset.current = id;
        input.value = '';
        status.textContent = data.message || (label + ' aplicado.');
      }
      notify(data.message || 'Android ID aplicado.');
    } catch (error) { status.textContent = error.message; notify(error.message); }
    finally { busy = false; paint(); }
  }
  applyButton.addEventListener('click', () => {
    const raw = input.value.trim();
    if (raw && !hex16.test(raw)) { notify('Android ID deve ter 16 dígitos hexadecimais.'); return; }
    apply(raw, 'Android ID');
  });
  randomButton.addEventListener('click', () => apply('', 'Android ID aleatório'));
  restoreButton.addEventListener('click', () => apply(original, 'Android ID anterior'));
  everyVisible(read, 4000);
  read();
})();
