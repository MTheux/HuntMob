// Polling consciente de visibilidade. Envolve setInterval e PULA o tick quando
// a aba está em background (document.hidden), para não martelar adb/frida/proxy
// à toa — o timer continua registrado e volta a disparar assim que a aba fica
// visível de novo. doc e scheduler são injetáveis para teste isolado.
function everyVisible(fn, ms, doc, scheduler) {
  const view = doc || document;
  const schedule = scheduler || ((f, m) => window.setInterval(f, m));
  return schedule(() => { if (!view.hidden) fn(); }, ms);
}

// Dual CJS/browser: no navegador este bloco é ignorado (module é undefined) e
// everyVisible fica visível aos demais scripts pelo escopo léxico clássico;
// sob Node, os testes fazem require deste arquivo.
if (typeof module !== 'undefined') module.exports = { everyVisible };
