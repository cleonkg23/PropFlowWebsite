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

    // If page loaded with a hash (anchor jump) or user prefers reduced motion,
    // skip the staged reveal — show everything immediately.
    var prefersReducedMotion = window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (window.location.hash || prefersReducedMotion) {
      reveals.forEach(function (el) { el.classList.add("is-visible"); });
    } else {
      var revealObs = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            var el = entry.target;
            var parent = el.parentElement;
            var siblings = parent ? Array.prototype.indexOf.call(parent.children, el) : 0;
            var delay = Math.min(siblings, 6) * 70;
            setTimeout(function () { el.classList.add("is-visible"); }, delay);
            revealObs.unobserve(el);
          }
        });
      }, { threshold: 0.12, rootMargin: "0px 0px -8% 0px" });

      reveals.forEach(function (el) { revealObs.observe(el); });
    }
  }
  // No IntersectionObserver fallback needed: CSS gates .reveal on .js,
  // and we still want content visible — so mark all visible immediately.
  if (!("IntersectionObserver" in window)) {
    document.querySelectorAll(".reveal").forEach(function (el) {
      el.classList.add("is-visible");
    });
  }

  // --- "What I do" cards: click-to-pin disclosure ---
  // (CSS handles hover-preview on desktop. JS only manages the persistent open state.)
  var acToggles = document.querySelectorAll(".ac-toggle");
  acToggles.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var card = btn.closest(".automate-card");
      if (!card) return;
      var bodyId = btn.getAttribute("aria-controls");
      var body = bodyId ? document.getElementById(bodyId) : null;
      var isOpen = btn.getAttribute("aria-expanded") === "true";
      btn.setAttribute("aria-expanded", isOpen ? "false" : "true");
      card.classList.toggle("is-open", !isOpen);
      if (body) {
        if (isOpen) body.setAttribute("hidden", "");
        else body.removeAttribute("hidden");
      }
    });
  });

  // --- Process strip: single-open accordion with shared panel ---
  var psSteps = document.querySelectorAll(".ps-step");
  var psWrap = document.querySelector(".process-wrap");
  var psPanel = document.getElementById("ps-detail");
  var psDetails = psPanel ? psPanel.querySelectorAll("[data-detail]") : [];

  function showPsDetail(stepNum) {
    psDetails.forEach(function (p) {
      if (p.getAttribute("data-detail") === stepNum) {
        p.removeAttribute("hidden");
      } else {
        p.setAttribute("hidden", "");
      }
    });
  }

  psSteps.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var step = btn.getAttribute("data-step");
      var isOpen = btn.getAttribute("aria-expanded") === "true";

      psSteps.forEach(function (b) { b.setAttribute("aria-expanded", "false"); });

      if (isOpen) {
        if (psWrap) psWrap.classList.remove("is-open");
      } else {
        btn.setAttribute("aria-expanded", "true");
        showPsDetail(step);
        if (psWrap) psWrap.classList.add("is-open");
      }
    });
  });

  // --- Footer year ---
  var year = document.getElementById("year");
  if (year) year.textContent = new Date().getFullYear();
})();
