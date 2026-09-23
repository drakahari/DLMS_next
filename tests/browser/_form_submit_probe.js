// Test-only observation: never cancel events, change controls, or submit a form.
(() => {
  const button = document.querySelector('#pdfReviewForm button[type=submit]:not([formaction])');
  const form = button.form;
  const key = '__dlmsReviewSubmitProbe';
  const describe = node => node ? `${node.tagName}#${node.id}.${String(node.className)}` : null;
  const snapshot = () => {
    const rect = button.getBoundingClientRect();
    const x = (Math.max(0, rect.left) + Math.min(innerWidth, rect.right)) / 2;
    const y = (Math.max(0, rect.top) + Math.min(innerHeight, rect.bottom)) / 2;
    const style = getComputedStyle(button);
    return {
      time: performance.now(), url: location.href, rect: rect.toJSON(),
      disabled: button.disabled, effectivelyDisabled: button.matches(':disabled'),
      connected: button.isConnected, visibility: style.visibility, display: style.display,
      opacity: style.opacity, pointerEvents: style.pointerEvents,
      topmost: describe(document.elementFromPoint(x, y)),
      centerStack: document.elementsFromPoint(x, y).slice(0, 6).map(describe),
      focus: describe(document.activeElement), documentFocused: document.hasFocus(),
      action: form.action, method: form.method, buttonAction: button.getAttribute('formaction'),
      animations: document.getAnimations().map(animation => ({
        target: describe(animation.effect?.target), state: animation.playState,
        currentTime: animation.currentTime, pending: animation.pending,
        transform: animation.effect?.target ? getComputedStyle(animation.effect.target).transform : null,
      })),
      overlays: [...document.querySelectorAll('.open, [aria-modal=true], dialog[open]')].map(describe),
      images: [...form.querySelectorAll('img')].map(img => ({
        src: img.getAttribute('src'), complete: img.complete, naturalWidth: img.naturalWidth,
        loading: img.loading, rect: img.getBoundingClientRect().toJSON(),
      })),
    };
  };
  const trace = {initial: snapshot(), events: [], mutations: [], calls: []};
  const observed = [];
  const refreshCancellation = () => {
    for (const {event, entry} of observed) entry.defaultPrevented = event.defaultPrevented;
  };
  const save = () => {
    refreshCancellation();
    sessionStorage.setItem(key, JSON.stringify(trace));
  };
  const observe = event => {
    if (trace.events.length >= 30) return;
    const entry = {
      type: event.type, target: describe(event.target), submitter: describe(event.submitter),
      onButton: button.contains(event.target), onForm: event.target === form,
      trusted: event.isTrusted, x: event.clientX, y: event.clientY,
      defaultPrevented: event.defaultPrevented, state: snapshot(),
    };
    trace.events.push(entry);
    observed.push({event, entry});
    queueMicrotask(save);
  };
  for (const type of ['pointermove', 'pointerdown', 'pointerup', 'click', 'submit', 'invalid']) {
    document.addEventListener(type, observe, true);
    // Firefox may run microtasks between listeners. Capture alone is too early
    // to report cancellation by the form handler; also observe after bubbling.
    window.addEventListener(type, save);
  }
  // Delegation preserves native method behavior and records explicit calls only.
  for (const name of ['requestSubmit', 'submit']) {
    const original = form[name];
    form[name] = function (...args) {
      trace.calls.push({method: name, state: snapshot()});
      save();
      return Reflect.apply(original, this, args);
    };
  }
  new MutationObserver(records => {
    if (trace.mutations.length < 20) {
      trace.mutations.push({attributes: records.map(record => record.attributeName), state: snapshot()});
      save();
    }
  }).observe(button, {attributes: true});
  window.__dlmsReviewSubmitSnapshot = () => {
    refreshCancellation();
    return {...trace, current: snapshot()};
  };
  window.addEventListener('pagehide', save);
  save();
  return true;
})()
