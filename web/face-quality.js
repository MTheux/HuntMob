// Qualidade e agregação de embeddings faciais. Puro — sem DOM nem webcam — para
// o cadastro multi-amostra e os portões de qualidade ficarem testáveis isolados.
// Um cadastro de captura única é ruidoso; a média de várias amostras boas
// estabiliza o embedding e eleva a precisão da verificação. Antispoof e liveness
// já são calculados pelo motor; aqui eles passam a reprovar o cadastro.

// Média componente-a-componente de N embeddings de mesmo comprimento. Lança
// quando a lista está vazia ou os comprimentos divergem.
function averageEmbeddings(embeddings) {
  if (!Array.isArray(embeddings) || embeddings.length === 0) throw new Error('nenhuma amostra para agregar');
  const length = embeddings[0].length;
  if (!length) throw new Error('amostra sem embedding');
  const sum = new Array(length).fill(0);
  for (const embedding of embeddings) {
    if (!Array.isArray(embedding) || embedding.length !== length) throw new Error('amostras com dimensões diferentes');
    for (let i = 0; i < length; i++) sum[i] += embedding[i];
  }
  return sum.map((value) => value / embeddings.length);
}

// Portão de qualidade de UMA face detectada: exige confiança mínima e embedding
// presente e — quando o motor devolve antispoof (face.real) e liveness
// (face.live) — que a face seja real e viva. Devolve {ok, reason}; reason vazio
// quando aprovada. A verificação de rosto único fica no caller (depende do DOM).
function faceQuality(face, options = {}) {
  const { minConfidence = 0.7, requireReal = true, requireLive = true, realMin = 0.5, liveMin = 0.5 } = options;
  if (!face) return { ok: false, reason: 'nenhum rosto detectado' };
  const confidence = face.faceScore || face.boxScore || 0;
  if (confidence < minConfidence) return { ok: false, reason: 'rosto com baixa confiança · aproxime e melhore a iluminação' };
  if (!face.embedding || !face.embedding.length) return { ok: false, reason: 'não foi possível gerar o embedding' };
  if (requireReal && typeof face.real === 'number' && face.real < realMin) return { ok: false, reason: 'possível apresentação falsa (antispoof)' };
  if (requireLive && typeof face.live === 'number' && face.live < liveMin) return { ok: false, reason: 'liveness insuficiente · use um rosto ao vivo' };
  return { ok: true, reason: '' };
}

// Dual CJS/browser: no navegador os nomes ficam visíveis a app.js pelo escopo
// léxico de script clássico; sob Node, os testes fazem require deste arquivo.
if (typeof module !== 'undefined') module.exports = { averageEmbeddings, faceQuality };
