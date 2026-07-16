(function () {
  "use strict";

  function textFor(pre) {
    return pre.getAttribute("data-copy-text") || pre.textContent || "";
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } catch (e) {}
    document.body.removeChild(ta);
    return Promise.resolve();
  }

  function enhance(pre) {
    if (pre.dataset.copyEnhanced === "true") return;
    pre.dataset.copyEnhanced = "true";

    var wrap = pre.parentElement;
    if (!wrap || !wrap.classList.contains("copyable")) {
      wrap = document.createElement("div");
      wrap.className = "copyable";
      pre.parentNode.insertBefore(wrap, pre);
      wrap.appendChild(pre);
    }

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "copy-button";
    btn.textContent = pre.getAttribute("data-copy-label") || "Copy";
    btn.setAttribute("aria-label", "Copy code to clipboard");
    wrap.appendChild(btn);

    var timer = null;
    btn.addEventListener("click", function () {
      copyText(textFor(pre)).then(function () {
        btn.textContent = "Copied";
        btn.dataset.copied = "true";
        clearTimeout(timer);
        timer = setTimeout(function () {
          btn.textContent = pre.getAttribute("data-copy-label") || "Copy";
          btn.dataset.copied = "false";
        }, 1200);
      });
    });
  }

  function init() {
    document.querySelectorAll("pre[data-copy], .code-block[data-copy]").forEach(enhance);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
