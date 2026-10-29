const {test}=require('node:test'),assert=require('node:assert/strict');
// face-quality.js é dual CJS/browser: require no mesmo realm expõe
// averageEmbeddings/faceQuality.
function load(){delete require.cache[require.resolve('../web/face-quality.js')];return require('../web/face-quality.js');}

test('averageEmbeddings tira a média componente-a-componente das amostras',()=>{
 const {averageEmbeddings}=load();
 assert.deepEqual(averageEmbeddings([[0,2,4],[2,4,8]]),[1,3,6]);
 assert.deepEqual(averageEmbeddings([[1,1,1]]),[1,1,1]);
});
test('averageEmbeddings rejeita lista vazia e dimensões divergentes',()=>{
 const {averageEmbeddings}=load();
 assert.throws(()=>averageEmbeddings([]),/nenhuma amostra/);
 assert.throws(()=>averageEmbeddings([[1,2],[1,2,3]]),/dimensões/);
});
test('faceQuality aprova rosto único, confiante, real e vivo',()=>{
 const {faceQuality}=load();
 assert.deepEqual(faceQuality({faceScore:0.9,embedding:[1,2,3],real:0.9,live:0.9}),{ok:true,reason:''});
});
test('faceQuality reprova baixa confiança, sem embedding, spoof e sem liveness',()=>{
 const {faceQuality}=load();
 assert.equal(faceQuality(null).ok,false);
 assert.match(faceQuality({faceScore:0.4,embedding:[1]}).reason,/confiança/);
 assert.match(faceQuality({faceScore:0.9,embedding:[]}).reason,/embedding/);
 assert.match(faceQuality({faceScore:0.9,embedding:[1],real:0.1,live:0.9}).reason,/antispoof/);
 assert.match(faceQuality({faceScore:0.9,embedding:[1],real:0.9,live:0.1}).reason,/liveness/);
});
test('faceQuality ignora antispoof/liveness quando o motor não os devolve',()=>{
 const {faceQuality}=load();
 // sem os campos real/live, a face não é reprovada por eles
 assert.equal(faceQuality({faceScore:0.9,embedding:[1,2,3]}).ok,true);
});
