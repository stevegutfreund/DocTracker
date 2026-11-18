// Ask before submitting any form marked data-confirm (CSP forbids inline JS).
document.querySelectorAll("form[data-confirm]").forEach(form => {
  form.addEventListener("submit", e => {
    if (!confirm(form.dataset.confirm)) e.preventDefault();
  });
});

// Documents filters apply as soon as one changes; the Apply button is only
// needed without JS.
(() => {
  const form = document.getElementById("filters");
  if (!form) return;
  form.classList.add("auto");
  form.querySelectorAll("select").forEach(s =>
    s.addEventListener("change", () => form.requestSubmit ? form.requestSubmit() : form.submit()));
})();

// Document form: scan-link rows.
(() => {
  const form = document.getElementById("doc-form");
  if (!form) return;
  const rows = document.getElementById("link-rows");
  const typeSelect = document.getElementById("doc-type");
  const typeLinks = JSON.parse(form.dataset.typeLinks || "{}");
  const ROW = ".link-row:not(.link-head)";

  const addRow = (label = "") => {
    const row = rows.querySelector(ROW).cloneNode(true);
    const [labelInput, urlInput] = row.querySelectorAll("input");
    labelInput.value = label;
    urlInput.value = "";
    rows.appendChild(row);
    return row;
  };

  document.getElementById("add-link").addEventListener("click", () => {
    addRow().querySelector("input").focus();
  });

  // Switching type swaps the suggested labels on rows that have no link yet;
  // rows already holding a link are left alone.
  typeSelect.addEventListener("change", () => {
    const all = [...rows.querySelectorAll(ROW)];
    const filled = all.filter(r => r.querySelectorAll("input")[1].value.trim());
    const keep = filled.length ? filled : [all[0]];
    if (!filled.length) keep[0].querySelectorAll("input").forEach(i => (i.value = ""));
    all.filter(r => !keep.includes(r)).forEach(r => r.remove());

    const have = new Set(filled.map(r => r.querySelector("input").value.trim()));
    const wanted = (typeLinks[typeSelect.value] || []).filter(l => !have.has(l));
    if (!filled.length && wanted.length) keep[0].querySelector("input").value = wanted.shift();
    wanted.forEach(l => addRow(l));
    addRow();
  });
})();
