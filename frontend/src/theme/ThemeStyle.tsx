import { paletteCss } from "./palette";

/**
 * Emits the token layer into the document head, server-side, so the palette is
 * present in the very first byte of HTML — no flash, no hydration gap.
 */
export function ThemeStyle() {
  return <style id="remas-tokens" dangerouslySetInnerHTML={{ __html: paletteCss() }} />;
}

/**
 * Restores the visitor's stored language and theme before first paint.
 * Without this the page would render Arabic/RTL for a frame and then snap to
 * English/LTR, which is exactly the flicker a language switch must not have.
 */
export function BootScript() {
  const script = `
(function(){
  try{
    var root=document.documentElement;
    var t=localStorage.getItem('remas.theme');
    if(t==='dark'||t==='light')root.setAttribute('data-theme',t);
    var l=localStorage.getItem('remas.locale');
    if(l==='ar'||l==='en'){root.lang=l;root.dir=(l==='ar'?'rtl':'ltr');root.dataset.locale=l;}
  }catch(e){}
})();`;
  return <script dangerouslySetInnerHTML={{ __html: script }} />;
}
