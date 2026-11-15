// One shared tooltip. All text goes in through textContent, never innerHTML, because names
// come from stored data.

export function createTooltip() {
  const el = document.createElement("div");
  el.className = "tooltip";
  el.setAttribute("role", "tooltip");
  el.hidden = true;
  document.body.append(el);

  function fill({ title, rows }) {
    el.replaceChildren();
    const head = document.createElement("div");
    head.className = "t-title";
    head.textContent = title;
    el.append(head);
    for (const [label, value, tone] of rows) {
      const row = document.createElement("div");
      row.className = "t-row";
      if (tone) row.dataset.tone = tone;
      const a = document.createElement("span");
      a.textContent = label;
      const b = document.createElement("span");
      b.textContent = value;
      row.append(a, b);
      el.append(row);
    }
  }

  function place(x, y) {
    el.hidden = false;
    const pad = 14;
    const { width, height } = el.getBoundingClientRect();
    const left = x + pad + width > window.innerWidth ? x - pad - width : x + pad;
    const top = y + pad + height > window.innerHeight ? y - pad - height : y + pad;
    el.style.left = `${Math.max(4, left)}px`;
    el.style.top = `${Math.max(4, top)}px`;
  }

  return {
    showAt(x, y, content) {
      fill(content);
      place(x, y);
    },
    showFor(element, content) {
      fill(content);
      const box = element.getBoundingClientRect();
      place(box.left + box.width / 2, box.top);
    },
    hide() {
      el.hidden = true;
    },
  };
}
