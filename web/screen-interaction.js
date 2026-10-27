// Screen input stays ordered; camera motion never changes native device coordinates.
(function(root){
  function keyboardAction(event,{platform='android',mode='unicode'}={}){
    if(event.ctrlKey||event.metaKey||event.altKey||event.isComposing)return;
    if(['Backspace','Enter','Tab','ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(event.key))return {action:'key',key:event.key};
    if(event.key==='Escape')return {action:platform==='ios'?'home':'back'};
    if(typeof event.key!=='string'||event.key.length!==1||event.key.charCodeAt(0)<32)return;
    if(mode==='ascii'&&!/^[\x20-\x7e]$/.test(event.key))return;
    if(mode==='adb'&&!/^[A-Za-z0-9 @._+:/-]$/.test(event.key))return;
    return {action:'text',text:event.key};
  }
  function inputQueue(send,isCurrent,onError){
    let tail=Promise.resolve(),pending=0;
    return {push(input,scope){
      if(pending>=128){onError(new Error('Fila de teclado cheia. Aguarde o aparelho responder.'));return tail;}
      pending++;
      tail=tail.then(()=>isCurrent(scope)?send(input):undefined).catch(onError).finally(()=>pending--);
      return tail;
    }};
  }
  function zoomPan(point,pan,scroll,oldZoom,newZoom,newScroll=scroll){
    return {x:point.x+newScroll.x-(point.x+scroll.x-pan.x)*newZoom/oldZoom,
            y:point.y+newScroll.y-(point.y+scroll.y-pan.y)*newZoom/oldZoom};
  }
  function fitPan(bounds,width,height,zoom){
    return {x:(width-(bounds.right-bounds.left)*zoom)/2-bounds.left*zoom,
            y:(height-(bounds.bottom-bounds.top)*zoom)/2-bounds.top*zoom};
  }
  const api={keyboardAction,inputQueue,zoomPan,fitPan};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.huntmobInteraction=api;
})(typeof window==='undefined'?this:window);
