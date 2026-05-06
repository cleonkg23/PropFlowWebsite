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

    // --- Scroll reveal with stagger ---
    var reveals = document.querySelectorAll(".reveal");

    // Pre-compute stagger index for items inside a .grid parent.
    // Each grid child gets a --reveal-delay CSS custom property so CSS
    // can also apply transition-delay without extra JS callbacks.
    reveals.forEach(function (el) {
      var parent = el.parentElement;
      if (!parent) return;
      var isGridChild = parent.classList.contains("grid") ||
                        parent.classList.contains("intro-grid") ||
                        parent.classList.contains("proof-cards");
      if (isGridChild) {
        var revealSiblings = Array.prototype.filter.call(parent.children, function (c) {
          return c.classList.contains("reveal");
        });
        var idx = revealSiblings.indexOf(el);
        var delay = Math.min(idx, 5) * 60;
        el.style.setProperty("--reveal-delay", delay + "ms");
      }
    });

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
            var delay = parseInt(el.style.getPropertyValue("--reveal-delay") || "0", 10);
            if (!delay) {
              // Non-grid reveals: stagger by DOM order among visible siblings
              var parent = el.parentElement;
              var idx = parent ? Array.prototype.indexOf.call(parent.children, el) : 0;
              delay = Math.min(idx, 4) * 60;
            }
            setTimeout(function () { el.classList.add("is-visible"); }, delay);
            revealObs.unobserve(el);
          }
        });
      }, { threshold: 0.10, rootMargin: "0px 0px -8% 0px" });

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

  // --- Demo view tabs (Dashboard / Item detail) ---
  var demoTabs = document.querySelectorAll(".mock-tab[data-view]");
  if (demoTabs.length) {
    function switchDemoView(view) {
      demoTabs.forEach(function (t) {
        var isActive = t.getAttribute("data-view") === view;
        t.classList.toggle("is-active", isActive);
        t.setAttribute("aria-selected", isActive ? "true" : "false");
      });
      var dashboard = document.getElementById("demo-view-dashboard");
      var detail    = document.getElementById("demo-view-detail");
      if (dashboard && detail) {
        if (view === "dashboard") {
          dashboard.removeAttribute("hidden");
          detail.setAttribute("hidden", "");
        } else {
          detail.removeAttribute("hidden");
          dashboard.setAttribute("hidden", "");
        }
      }
    }

    demoTabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        switchDemoView(tab.getAttribute("data-view"));
      });
    });

    // Clicking the overdue row switches to detail view
    var detailTrigger = document.getElementById("mock-detail-trigger");
    if (detailTrigger) {
      detailTrigger.addEventListener("click", function () {
        switchDemoView("detail");
      });
      detailTrigger.style.cursor = "pointer";
    }

    // Back link in detail view returns to dashboard
    var backLink = document.getElementById("mock-back-link");
    if (backLink) {
      backLink.addEventListener("click", function () {
        switchDemoView("dashboard");
      });
    }
  }

  // --- Footer year ---
  var year = document.getElementById("year");
  if (year) year.textContent = new Date().getFullYear();
})();
