// ---- Hero image carousel ----
(function () {
  var slides = document.querySelectorAll('#heroSlides .hero-slide');
  if (slides.length > 1) {
    var i = 0;
    setInterval(function () {
      slides[i].classList.remove('is-active');
      i = (i + 1) % slides.length;
      slides[i].classList.add('is-active');
    }, 5000);
  }
})();

// ---- Hero Buy/Rent tabs: switch the search type, keep what's been typed ----
// These used to be plain links, so choosing Buy/Rent navigated away and threw
// out whatever was in the search box. Now they set the form's hidden `type`.
(function () {
  var tabs = document.getElementById('searchTabs');
  if (!tabs) return;
  var slider = tabs.querySelector('.tab-slider');
  var field = document.getElementById('searchType');
  var links = tabs.querySelectorAll('a');
  function move(el) {
    if (!slider) return;
    slider.style.width = el.offsetWidth + 'px';
    slider.style.transform = 'translateX(' + el.offsetLeft + 'px)';
  }
  var active = tabs.querySelector('a.on') || links[0];
  if (active) move(active);

  links.forEach(function (l) {
    l.addEventListener('mouseenter', function () { move(l); });
    l.addEventListener('click', function (ev) {
      if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button > 0) return; // let new-tab work
      ev.preventDefault();
      links.forEach(function (x) { x.classList.remove('on'); });
      l.classList.add('on');
      active = l;
      move(l);
      if (field) field.value = l.getAttribute('data-type') || '';
    });
  });
  tabs.addEventListener('mouseleave', function () { if (active) move(active); });
  window.addEventListener('resize', function () { if (active) move(active); });
})();

// ---- Listings filter tabs: re-submit with the new type, keep every filter ----
(function () {
  var tabs = document.getElementById('typeTabs');
  var form = document.getElementById('filterForm');
  var field = document.getElementById('typeField');
  if (!tabs || !form || !field) return;
  tabs.querySelectorAll('a').forEach(function (l) {
    l.addEventListener('click', function (ev) {
      if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button > 0) return;
      ev.preventDefault();
      field.value = l.getAttribute('data-type') || '';
      form.submit();
    });
  });
})();

// ---- Drop empty filter fields so the URL stays readable ----
(function () {
  var touched = [];
  document.querySelectorAll('form[method="get"]').forEach(function (form) {
    form.addEventListener('submit', function () {
      form.querySelectorAll('input, select').forEach(function (el) {
        if (!el.value && !el.disabled) {     // disabled fields aren't submitted
          el.disabled = true;
          touched.push(el);
        }
      });
    });
  });
  // Coming back via the back button can restore the page mid-submit, with those
  // fields still disabled and the form unusable. Undo it on restore.
  function restore() {
    touched.forEach(function (el) { el.disabled = false; });
    touched = [];
  }
  window.addEventListener('pageshow', restore);
  window.addEventListener('pagehide', restore);
})();

// ---- Mobile navigation ----
(function () {
  var btn = document.getElementById('navToggle');
  var nav = document.getElementById('siteNav');
  if (!btn || !nav) return;
  btn.addEventListener('click', function () {
    var open = nav.classList.toggle('open');
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  nav.querySelectorAll('a').forEach(function (a) {
    a.addEventListener('click', function () {
      nav.classList.remove('open');
      btn.setAttribute('aria-expanded', 'false');
    });
  });
})();

// ---- Scroll reveal ----
(function () {
  var els = document.querySelectorAll('.reveal');
  if (!('IntersectionObserver' in window) || !els.length) {
    els.forEach(function (e) { e.classList.add('in'); });
    return;
  }
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (en) {
      if (en.isIntersecting) { en.target.classList.add('in'); io.unobserve(en.target); }
    });
  }, { threshold: 0.12 });
  els.forEach(function (e) { io.observe(e); });
})();

// ---- Share button (native share sheet on phones, copy link on desktop) ----
(function () {
  document.querySelectorAll('[data-share]').forEach(function (btn) {
    btn.addEventListener('click', async function () {
      var url = window.location.href;
      var title = btn.getAttribute('data-title') || document.title;
      var text = btn.getAttribute('data-text') || title;
      if (navigator.share) {
        try { await navigator.share({ title: title, text: text, url: url }); return; }
        catch (e) { if (e && e.name === 'AbortError') return; }
      }
      try {
        await navigator.clipboard.writeText(url);
        var original = btn.innerHTML;
        btn.classList.add('copied');
        btn.textContent = 'Link copied';
        setTimeout(function () { btn.classList.remove('copied'); btn.innerHTML = original; }, 1800);
      } catch (e) {
        window.prompt('Copy this link:', url);
      }
    });
  });
})();

// ---- Hero video: show it only once it can actually play ----
(function () {
  var v = document.getElementById('heroVideo');
  if (!v) return;
  // skip on small screens, slow links or data-saver — images look better there
  var conn = navigator.connection || {};
  var lowData = conn.saveData === true ||
                (conn.effectiveType && /2g/.test(conn.effectiveType));
  if (window.innerWidth < 700 || lowData) { v.remove(); return; }

  var shown = false;
  function show() {
    if (shown || !v.videoWidth) return;
    shown = true;
    v.classList.add('on');
    var play = v.play();
    if (play && play.catch) play.catch(function () {});
  }
  ['loadeddata', 'canplay', 'canplaythrough', 'playing'].forEach(function (ev) {
    v.addEventListener(ev, show);
  });
  v.addEventListener('error', function () { v.remove(); });
  // some browsers report readiness without firing an event
  setTimeout(function () { if (!shown && v.readyState >= 2) show(); }, 1200);
  setTimeout(function () { if (!shown) v.remove(); }, 6000);  // give up -> images
  v.load();
})();
