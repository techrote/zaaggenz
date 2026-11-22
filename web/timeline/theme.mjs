// Palette definitions and expansion match authenticated app/web/static/app.js.
// Share its storage record so moving between Synth and Compose keeps appearance.
export const THEME_STORE='uptempo-ui-theme-v12';
export const UI_THEMES={
  earth:{label:'EARTH / NEUTRAL',bg:'#12100d',text:'#ddd6c8',accent:'#c8b47a',secondary:'#93a58d',tertiary:'#d08b5b',danger:'#d56b5e'},
  phosphor:{label:'PHOSPHOR',bg:'#090b0a',text:'#d4dbd1',accent:'#b7ff39',secondary:'#65e6d4',tertiary:'#ffb24c',danger:'#ff6262'},
  amber:{label:'AMBER CRT',bg:'#100b07',text:'#e6d3b3',accent:'#efa34a',secondary:'#ba8e63',tertiary:'#ffd07a',danger:'#dd6554'},
  ice:{label:'ICE / STEEL',bg:'#0b1014',text:'#d6e1e6',accent:'#8fb9c9',secondary:'#76c6c9',tertiary:'#d1a16b',danger:'#d66b72'},
  plum:{label:'PLUM / ASH',bg:'#120e13',text:'#dfd4df',accent:'#b99ab4',secondary:'#8da79f',tertiary:'#c59269',danger:'#d66d78'},
  mono:{label:'MONO',bg:'#101010',text:'#dedede',accent:'#bdbdbd',secondary:'#929292',tertiary:'#e2e2e2',danger:'#d06b6b'}
};
function hexRgb(h){h=String(h||'#000000').replace('#','');if(h.length===3)h=[...h].map(c=>c+c).join('');const n=parseInt(h,16);return [(n>>16)&255,(n>>8)&255,n&255];}
function rgbHex(rgb){return '#'+rgb.map(v=>Math.max(0,Math.min(255,Math.round(v))).toString(16).padStart(2,'0')).join('');}
function mixHex(a,b,t){const A=hexRgb(a),B=hexRgb(b);return rgbHex(A.map((v,i)=>v+(B[i]-v)*t));}
function luminance(h){const c=hexRgb(h).map(v=>{v/=255;return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4);});return .2126*c[0]+.7152*c[1]+.0722*c[2];}
export function expandTheme(t){const light=luminance(t.bg)>.42,ink=t.text;return {
  '--bg':t.bg,'--text':ink,'--phosphor':t.accent,'--cyan':t.secondary,'--amber':t.tertiary,'--danger':t.danger,
  '--panel':mixHex(t.bg,ink,.055),'--panel2':mixHex(t.bg,ink,.085),'--line':mixHex(t.bg,ink,.24),'--line2':mixHex(t.bg,ink,.13),'--muted':mixHex(t.bg,ink,.58),
  '--shadow':mixHex(t.bg,'#000000',.45),'--control':mixHex(t.bg,ink,.09),'--deep':mixHex(t.bg,'#000000',.18),'--deep2':mixHex(t.bg,'#000000',.35),'--inset':mixHex(t.bg,ink,.035),'--inset2':mixHex(t.bg,ink,.045),'--head':mixHex(t.bg,ink,.10),'--card':mixHex(t.bg,ink,.075),'--card2':mixHex(t.bg,ink,.06),'--popover-bg':mixHex(t.bg,ink,.045),'--hover':mixHex(t.bg,ink,.14),'--bar-bg':mixHex(t.bg,ink,.18),'--dotline':mixHex(t.bg,ink,.19),'--label':mixHex(t.bg,ink,.76),'--label2':mixHex(t.bg,ink,.82),'--faint':mixHex(t.bg,ink,.44),'--scope-bg':mixHex(t.bg,'#000000',.28),
  '--key-bg':mixHex(t.accent,ink,.48),'--key-text':light?'#111111':mixHex(t.bg,'#000000',.45),'--key-border':mixHex(t.bg,ink,.36),'--key-black-bg':mixHex(t.bg,ink,.13),'--key-black-text':mixHex(t.bg,ink,.90),'--key-black-border':mixHex(t.bg,ink,.34),'--accent-hover':mixHex(t.accent,ink,.30),'--on-accent':luminance(t.accent)>.46?'#17130d':'#f2eee7','--focus':mixHex(t.accent,ink,.35)
};}
const isColour=value=>typeof value==='string'&&/^#[0-9a-f]{6}$/i.test(value);
const hasPreset=name=>typeof name==='string'&&Object.hasOwn(UI_THEMES,name);
export function initTheme(onChange=()=>{}){
  const get=id=>document.getElementById(id);
  const picker=get('themePreset');
  if(!picker)return;
  let custom=null;
  const swatches=get('themeSwatches');
  function apply(name,persist=true){
    const chosen=name==='custom'&&custom?'custom':hasPreset(name)?name:'earth';
    const theme=chosen==='custom'?null:UI_THEMES[chosen];
    const vars=theme?expandTheme(theme):custom.vars;
    if(theme){
      custom=null;
      get('themeAccent').value=theme.accent;
      get('themeBackground').value=theme.bg;
    }
    for(const [key,value] of Object.entries(vars))document.documentElement.style.setProperty(key,value);
    document.documentElement.style.colorScheme=luminance(vars['--bg'])>.42?'light':'dark';
    document.documentElement.dataset.theme=chosen;
    picker.value=chosen;
    for(const button of swatches.children){
      const active=button.dataset.theme===chosen;
      button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));
    }
    if(persist){
      const record=chosen==='custom'?{name:'custom',...custom}:{name:chosen,vars:null};
      // Appearance is optional: blocked/full browser storage must not stop audio.
      try{localStorage.setItem(THEME_STORE,JSON.stringify(record));}catch{}
    }
    onChange();
    window.dispatchEvent(new CustomEvent('zaaggenz-theme-change',{detail:{name:chosen}}));
  }
  function restore(){
    let saved=null;try{saved=JSON.parse(localStorage.getItem(THEME_STORE)||'null');}catch{}
    if(saved?.name==='custom'&&saved.vars&&typeof saved.vars==='object'){
      const vars=expandTheme(UI_THEMES.earth);
      for(const key of Object.keys(vars))if(isColour(saved.vars[key]))vars[key]=saved.vars[key];
      custom={vars,accent:isColour(saved.accent)?saved.accent:vars['--phosphor'],bg:isColour(saved.bg)?saved.bg:vars['--bg']};
      get('themeAccent').value=custom.accent;get('themeBackground').value=custom.bg;
      apply('custom',false);
    }else apply(saved?.name||'earth',false);
  }
  function customise(){
    const base=UI_THEMES.earth,accent=get('themeAccent').value,bg=get('themeBackground').value;
    if(!isColour(accent)||!isColour(bg))return;
    custom={vars:expandTheme({...base,accent,bg,secondary:mixHex(accent,'#7ea296',.52),tertiary:mixHex(accent,'#d58f62',.58)}),accent,bg};
    apply('custom');
  }
  swatches.replaceChildren();
  for(const [name,theme] of Object.entries(UI_THEMES)){
    const button=document.createElement('button');button.type='button';button.className='theme-swatch';button.dataset.theme=name;
    button.title=theme.label;button.setAttribute('aria-label',theme.label);button.setAttribute('aria-pressed','false');
    button.style.setProperty('--sw-bg',theme.bg);button.style.setProperty('--sw-accent',theme.accent);button.style.setProperty('--sw-secondary',theme.secondary);
    button.addEventListener('click',()=>apply(name));swatches.append(button);
  }
  picker.addEventListener('change',()=>{
    // Selecting CUSTOM without a previous custom record starts from the two
    // displayed colours instead of silently reverting the dropdown to Earth.
    if(picker.value==='custom'&&!custom)customise();else apply(picker.value);
  });
  get('themeAccent').addEventListener('input',customise);
  get('themeBackground').addEventListener('input',customise);
  get('themeReset').addEventListener('click',()=>apply('earth'));
  window.addEventListener('storage',event=>{if(event.key===THEME_STORE||event.key===null)restore();});
  const panel=get('appearance-panel');
  document.addEventListener('pointerdown',event=>{if(panel.open&&!panel.contains(event.target))panel.open=false;});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&panel.open){panel.open=false;panel.querySelector('summary').focus();}});
  restore();
}
