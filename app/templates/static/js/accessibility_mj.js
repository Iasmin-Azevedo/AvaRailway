/**
 * AVA MJ — barra de acessibilidade: fonte, contraste, leitura (speech), painel de legendas.
 */
(function () {
  var STORAGE_FONT = 'mj_a11y_font_pct';
  var STORAGE_CONTRAST = 'mj_a11y_high_contrast';
  var MIN_PCT = 90;
  var MAX_PCT = 130;
  var STEP = 5;

  function getRoot() {
    return document.documentElement;
  }

  function getBody() {
    return document.body;
  }

  function applyFontPct(pct) {
    pct = Math.max(MIN_PCT, Math.min(MAX_PCT, pct));
    getRoot().style.fontSize = pct + '%';
    try {
      localStorage.setItem(STORAGE_FONT, String(pct));
    } catch (e) {}
  }

  function loadFont() {
    try {
      var s = localStorage.getItem(STORAGE_FONT);
      if (s) applyFontPct(parseInt(s, 10) || 100);
    } catch (e) {}
  }

  function toggleContrast(on) {
    var b = getBody();
    if (on) b.classList.add('a11y-high-contrast');
    else b.classList.remove('a11y-high-contrast');
    try {
      localStorage.setItem(STORAGE_CONTRAST, on ? '1' : '0');
    } catch (e) {}
  }

  function loadContrast() {
    try {
      if (localStorage.getItem(STORAGE_CONTRAST) === '1') toggleContrast(true);
    } catch (e) {}
  }

  function currentFontPct() {
    var fs = getRoot().style.fontSize;
    if (fs && fs.indexOf('%') !== -1) return parseInt(fs, 10) || 100;
    try {
      var s = localStorage.getItem(STORAGE_FONT);
      if (s) return parseInt(s, 10) || 100;
    } catch (e) {}
    return 100;
  }

  var speaking = false;
  function getReadableText() {
    var main = document.querySelector('main');
    if (main) return main.innerText || '';
    return (document.body && document.body.innerText) || '';
  }

  function toggleReadAloud() {
    if (!window.speechSynthesis) return;
    if (speaking) {
      window.speechSynthesis.cancel();
      speaking = false;
      return;
    }
    var text = getReadableText().replace(/\s+/g, ' ').trim().slice(0, 8000);
    if (!text) return;
    var u = new SpeechSynthesisUtterance(text);
    u.lang = 'pt-BR';
    u.onend = function () { speaking = false; };
    u.onerror = function () { speaking = false; };
    speaking = true;
    window.speechSynthesis.speak(u);
  }

  function updateCaptionPanel() {
    var panel = document.getElementById('a11y-caption-panel');
    var bodyEl = document.getElementById('a11y-caption-body');
    if (!panel || !bodyEl) return;
    var main = document.querySelector('main');
    var txt =
      (main && main.getAttribute('data-a11y-caption')) ||
      document.body.getAttribute('data-a11y-caption') ||
      '';
    txt = (txt || '').trim();
    bodyEl.textContent = txt || 'Não há legenda ou descrição cadastrada para esta página.';
  }

  function toggleCaptionsVisible() {
    var panel = document.getElementById('a11y-caption-panel');
    var btnCaption = document.getElementById('a11y-toggle-captions');
    if (!panel) return;
    updateCaptionPanel();
    var willShow = panel.classList.contains('d-none');
    panel.classList.toggle('d-none');
    if (btnCaption) {
      btnCaption.setAttribute('aria-expanded', willShow ? 'true' : 'false');
    }
    if (willShow) {
      var capBody = document.getElementById('a11y-caption-body');
      if (capBody) {
        try {
          capBody.focus({ preventScroll: true });
        } catch (e) {}
      }
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    loadFont();
    loadContrast();

    var btnPlus = document.getElementById('a11y-font-plus');
    var btnMinus = document.getElementById('a11y-font-minus');
    var btnContrast = document.getElementById('a11y-high-contrast');
    var btnRead = document.getElementById('a11y-read-aloud');
    var btnCaption = document.getElementById('a11y-toggle-captions');

    if (btnPlus) {
      btnPlus.addEventListener('click', function () {
        applyFontPct(currentFontPct() + STEP);
      });
    }
    if (btnMinus) {
      btnMinus.addEventListener('click', function () {
        applyFontPct(currentFontPct() - STEP);
      });
    }
    if (btnContrast) {
      btnContrast.addEventListener('click', function () {
        var b = getBody();
        toggleContrast(!b.classList.contains('a11y-high-contrast'));
      });
    }
    if (btnRead) {
      btnRead.addEventListener('click', toggleReadAloud);
    }
    if (btnCaption) {
      btnCaption.setAttribute('aria-expanded', 'false');
      btnCaption.setAttribute('aria-controls', 'a11y-caption-panel');
      btnCaption.addEventListener('click', toggleCaptionsVisible);
    }

    updateCaptionPanel();
  });
})();
