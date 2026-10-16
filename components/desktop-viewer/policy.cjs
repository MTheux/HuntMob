function workerUrl(value){
 if(typeof value!=='string'||value.length>2048)throw Error('URL inválida');
 const u=new URL(value),local=u.protocol==='http:'&&['127.0.0.1','localhost','[::1]'].includes(u.hostname),remote=u.protocol==='https:'&&/^[a-z0-9-]+\.[a-z0-9-]+\.ts\.net$/i.test(u.hostname);
 if(!(local||remote)||u.username||u.password||u.pathname!=='/'||u.hash)throw Error('Use a raiz do worker local ou HTTPS do Tailscale');
 const output=new URL(u.origin);output.searchParams.set('viewer','1');
 for(const [key,val] of u.searchParams){if(key==='platform'&&['android','ios'].includes(val))output.searchParams.set(key,val);else if(key==='device'&&/^[a-zA-Z0-9_-]{1,100}$/.test(val))output.searchParams.set(key,val);else if(key!=='viewer')throw Error('Parâmetro inválido');}
 return output.href;
}
function protocolUrl(value){const u=new URL(value);if(u.protocol!=='huntmob-viewer:'||u.hostname!=='open')throw Error('Protocolo inválido');return workerUrl(u.searchParams.get('url'));}
module.exports={workerUrl,protocolUrl};
