// Motion, kept to one small system:
//   reveal      sections sharpen into focus once as they scroll into view
//   splitWords  a headline rises in word by word
//   cycleWords  a phrase swaps through a few alternatives, then settles
//   countUp     a number rolls up to its value the first time it is seen
// Everything plays once, lasts under a second, and is skipped entirely for
// visitors who ask their device to reduce motion.

export const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let observer = null;
const pending = new WeakMap();

function ensureObserver() {
  if (observer || !("IntersectionObserver" in window)) return observer;
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        observer.unobserve(entry.target);
        entry.target.classList.add("is-in");
        pending.get(entry.target)?.();
        pending.delete(entry.target);
      }
    },
    { rootMargin: "0px 0px -8% 0px", threshold: 0.12 },
  );
  return observer;
}

/** Run `callback` (and add .is-in) the first time `el` scrolls into view. */
export function whenVisible(el, callback) {
  if (reducedMotion() || !ensureObserver()) {
    el.classList.add("is-in");
    callback?.();
    return el;
  }
  if (callback) pending.set(el, callback);
  observer.observe(el);
  return el;
}

/** Mark an element to fade and sharpen in on scroll. `delay` staggers siblings. */
export function reveal(el, delay = 0) {
  el.classList.add("reveal");
  if (delay) el.style.setProperty("--reveal-delay", `${delay}ms`);
  return whenVisible(el);
}

/** Split an element's text into words that rise in one after another. */
export function splitWords(el, { delay = 0, step = 70 } = {}) {
  if (reducedMotion()) return el;
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const textNodes = [];
  while (walker.nextNode()) textNodes.push(walker.currentNode);
  let index = 0;
  for (const node of textNodes) {
    const fragment = document.createDocumentFragment();
    for (const part of node.textContent.split(/(\s+)/)) {
      if (!part) continue;
      if (/^\s+$/.test(part)) {
        fragment.append(part);
        continue;
      }
      const word = document.createElement("span");
      word.className = "word";
      const inner = document.createElement("span");
      inner.textContent = part;
      inner.style.animationDelay = `${delay + index * step}ms`;
      word.append(inner);
      fragment.append(word);
      index += 1;
    }
    node.replaceWith(fragment);
  }
  el.classList.add("split");
  return el;
}

/**
 * Swap an element's text through `phrases`, ending on the last one.
 * Used once in the hero to name the three things the product answers.
 */
export function cycleWords(el, phrases, { hold = 1500, start = 900 } = {}) {
  const final = phrases[phrases.length - 1];
  // Screen readers get the settled phrase only, not the animation.
  el.setAttribute("aria-label", final);
  if (reducedMotion() || phrases.length < 2) {
    el.textContent = final;
    return () => {};
  }
  let i = 0;
  let timer;
  const span = document.createElement("span");
  span.className = "cycle__word";
  span.setAttribute("aria-hidden", "true");
  span.textContent = phrases[0];
  el.replaceChildren(span);
  el.classList.add("cycle");
  // Phrases wrap differently on narrow screens. Hold the tallest one's height
  // for the whole cycle so nothing below the headline moves.
  const reserve = () => {
    el.style.minHeight = "";
    const shown = span.textContent;
    let tallest = 0;
    for (const phrase of phrases) {
      span.textContent = phrase;
      tallest = Math.max(tallest, el.offsetHeight);
    }
    span.textContent = shown;
    el.style.minHeight = `${tallest}px`;
  };
  reserve();
  window.addEventListener("resize", reserve);
  const next = () => {
    i += 1;
    span.classList.add("is-leaving");
    timer = setTimeout(() => {
      span.textContent = phrases[i];
      span.classList.remove("is-leaving");
      if (i < phrases.length - 1) timer = setTimeout(next, hold);
    }, 260);
  };
  timer = setTimeout(next, start + hold);
  return () => {
    clearTimeout(timer);
    window.removeEventListener("resize", reserve);
  };
}

/** Roll a number from zero to `to` when first visible. `format` renders each frame. */
export function countUp(el, to, format, { duration = 900 } = {}) {
  const final = format(to);
  if (reducedMotion() || !Number.isFinite(to)) {
    el.textContent = final;
    return el;
  }
  // Reserve the final width so neighbours do not shift while it counts.
  el.textContent = final;
  el.style.minWidth = `${el.offsetWidth}px`;
  el.style.display = "inline-block";
  el.textContent = format(0);
  whenVisible(el, () => {
    const started = performance.now();
    const tick = (now) => {
      const t = Math.min(1, (now - started) / duration);
      const eased = 1 - (1 - t) ** 3;
      el.textContent = t === 1 ? final : format(to * eased);
      if (t < 1) requestAnimationFrame(tick);
      else el.style.minWidth = "";
    };
    requestAnimationFrame(tick);
  });
  return el;
}

/** Cross-fade between pages where the browser supports view transitions. */
export function transition(update) {
  if (reducedMotion() || !document.startViewTransition) return update();
  const swap = document.startViewTransition(update);
  // Changing page again mid-fade skips this one. That is fine, and not an error.
  swap.ready.catch(() => {});
  return swap.finished.catch(() => {});
}
