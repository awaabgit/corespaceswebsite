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

// ---- Animated Buy/Rent tab slider ----
(function () {
  var tabs = document.getElementById('searchTabs');
  if (!tabs) return;
  var slider = tabs.querySelector('.tab-slider');
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
  });
  tabs.addEventListener('mouseleave', function () { if (active) move(active); });
  window.addEventListener('resize', function () { if (active) move(active); });
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
