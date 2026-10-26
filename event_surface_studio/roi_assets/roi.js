/** Streamlit Component v2: draw a pixel-accurate ROI without third-party JS. */
export default function(component) {
  const {data, parentElement, setStateValue} = component;
  const root = parentElement.querySelector('.roi-picker');
  if (!root) return;
  const image = root.querySelector('.roi-image');
  const svg = root.querySelector('.roi-layer');
  const shadow = root.querySelector('.roi-dimmer');
  const outline = root.querySelector('.roi-outline');
  const handles = [...root.querySelectorAll('[data-roi-handle]')];
  const W = Number(data.width), H = Number(data.height);
  if (!Number.isInteger(W) || !Number.isInteger(H) || W < 1 || H < 1) return;
  if (image.src !== data.image) image.src = data.image;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('preserveAspectRatio', 'none');

  function clamp(v, min, max) { return Math.max(min, Math.min(max, v)); }
  function validBox(box) {
    return Array.isArray(box) && box.length === 4 && box.every(Number.isFinite);
  }
  const incoming = validBox(data.selection) ? data.selection : [0,0,W,H];
  function norm(box) {
    const x=clamp(Math.round(box[0]),0,W-1), y=clamp(Math.round(box[1]),0,H-1);
    return [x,y,clamp(Math.round(box[2]),1,W-x),clamp(Math.round(box[3]),1,H-y)];
  }
  let selection = norm(incoming);
  let down = null;
  function draw(box) {
    const [x,y,w,h] = box;
    shadow.setAttribute('d', `M0 0H${W}V${H}H0Z M${x} ${y}H${x+w}V${y+h}H${x}Z`);
    outline.setAttribute('x', x);
    outline.setAttribute('y', y);
    outline.setAttribute('width', w);
    outline.setAttribute('height', h);
    const centers = [[x,y],[x+w,y],[x,y+h],[x+w,y+h]];
    handles.forEach((handle,i) => {
      handle.setAttribute('cx',centers[i][0]);
      handle.setAttribute('cy',centers[i][1]);
    });
  }
  function point(event) {
    const bounds=svg.getBoundingClientRect();
    return {
      x:clamp(Math.round((event.clientX-bounds.left)*W/bounds.width),0,W),
      y:clamp(Math.round((event.clientY-bounds.top)*H/bounds.height),0,H)
    };
  }
  function fromPoints(a,b) {
    const x=clamp(Math.min(a.x,b.x),0,W-1), y=clamp(Math.min(a.y,b.y),0,H-1);
    const w=clamp(Math.abs(b.x-a.x),1,W-x), h=clamp(Math.abs(b.y-a.y),1,H-y);
    return [x,y,w,h];
  }
  draw(selection);
  svg.onpointerdown = event => {
    if (event.button !== 0) return;
    event.preventDefault();
    down=point(event);
    svg.setPointerCapture(event.pointerId);
    draw(fromPoints(down,down));
  };
  svg.onpointermove = event => {
    if (!down) return;
    draw(fromPoints(down,point(event)));
  };
  svg.onpointerup = event => {
    if (!down) return;
    const end=point(event);
    const moved=Math.abs(end.x-down.x)>=2 && Math.abs(end.y-down.y)>=2;
    if (moved) {
      selection=norm(fromPoints(down,end));
      setStateValue('selection',selection); // rerun only after mouse release
    }
    down=null;
    draw(selection);
    if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
  };
  svg.onpointercancel = event => {
    down=null;
    draw(selection);
  };
}
