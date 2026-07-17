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
