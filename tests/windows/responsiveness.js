/* Numeric synthetic-page measurements; rAF opportunities are not displayed pixels. */
(() => {
  const gl = document.createElement('canvas').getContext('webgl2');
  const ext = gl?.getExtension('WEBGL_debug_renderer_info');
  window.__responseProbe = {
    done: false, viewport: {width: innerWidth, height: innerHeight, dpr: devicePixelRatio},
    hidden: document.hidden, focus: document.hasFocus(), theme: document.querySelector('.dashboard-sidebar')?.dataset.theme,
    nav: performance.getEntriesByType('navigation')[0]?.toJSON(),
    webgl: gl ? {vendor: ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR),
      renderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER)} : null
  };
  let first, last, frames=[], work=[], positions=[];
  const max=Math.max(0,document.documentElement.scrollHeight-innerHeight);
  function tick(now) {
    if(first===undefined)first=now;
    if(last!==undefined)frames.push(now-last);
    last=now;
    const begin=performance.now();
    const target=(Math.sin((now-first)/600-Math.PI/2)+1)/2*max;
    scrollTo({top:target,behavior:'instant'});
    positions.push(scrollY); work.push(performance.now()-begin);
    if(now-first<3000)requestAnimationFrame(tick);
    else {
      scrollTo({top:0,behavior:'instant'});
      Object.assign(window.__responseProbe,{done:true,elapsed:now-first,frames,work,
        maxScroll:max,scrollPositionsChanged:positions.some(x=>x>0),hiddenEnd:document.hidden});
    }
  }
  requestAnimationFrame(tick);
  return true;
})()
