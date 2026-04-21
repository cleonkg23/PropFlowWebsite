/* =========================================================
   Property Workflow Co. — site script
   Lightweight vanilla JS. Site works without it.
   ========================================================= */
(function () {
  "use strict";

  // --- Mobile nav ---
  var toggle = document.getElementById("menu-toggle");
  var nav = document.getElementById("primary-nav");
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var isOpen = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
      toggle.setAttribute("aria-label", isOpen ? "Close menu" : "Open menu");
    });
    nav.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        if (nav.classList.contains("open")) {
          nav.classList.remove("open");
          toggle.setAttribute("aria-expanded", "false");
          toggle.setAttribute("aria-label", "Open menu");
        }
      });
    });
  }

  // --- Sticky header background ---
  var header = document.getElementById("site-header");
  if (header) {
    var onScroll = function () {
      header.classList.toggle("scrolled", window.scrollY > 8);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  // --- Active nav state ---
  if ("IntersectionObserver" in window) {
    var navLinks = document.querySelectorAll(".primary-nav a[href^='#']");
    var sectionMap = {};
    navLinks.forEach(function (link) {
      var id = link.getAttribute("href").slice(1);
      var section = document.getElementById(id);
      if (section) sectionMap[id] = link;
    });

    var navObs = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          var link = sectionMap[entry.target.id];
          if (!link) return;
          if (entry.isIntersecting) {
            navLinks.forEach(function (l) { l.classList.remove("active"); });
            link.classList.add("active");
          }
        });
      },
      { rootMargin: "-40% 0px -55% 0px", threshold: 0 }
    );

    Object.keys(sectionMap).forEach(function (id) {
      var s = document.getElementById(id);
      if (s) navObs.observe(s);
    });

    // --- Scroll reveal with light stagger ---
    var reveals = document.querySelectorAll(".reveal");
    var revealObs = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry, idx) {
        if (entry.isIntersecting) {
          var el = entry.target;
          // light stagger using parent index
          var parent = el.parentElement;
          var siblings = parent ? Array.prototype.indexOf.call(parent.children, el) : 0;
          var delay = Math.min(siblings, 6) * 70;
          setTimeout(function () { el.classList.add("is-visible"); }, delay);
          revealObs.unobserve(el);
        }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -8% 0px" });

    reveals.forEach(function (el) { revealObs.observe(el); });
  } else {
    // Fallback: just show everything
    document.querySelectorAll(".reveal").forEach(function (el) {
      el.classList.add("is-visible");
    });
  }

  // --- Footer year ---
  var year = document.getElementById("year");
  if (year) year.textContent = new Date().getFullYear();
})();
