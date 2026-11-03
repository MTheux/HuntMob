// Compatibility path for older cached index.html pages. Local and Tailscale
// access are governed by their respective server gateways; the browser never
// asks for an operator URL or token.
(function(){
  window.huntmobOperator={
    async mediaUrl(path){
      const url=new URL(path,location.origin);
      if(url.origin!==location.origin||!url.pathname.startsWith('/api/'))
        throw new Error('Endereço de mídia inválido.');
      return url.href;
    }
  };
})();
