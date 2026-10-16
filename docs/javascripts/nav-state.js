/*
 * Keep the expanded sections of the navigation open across page loads.
 *
 * Instant navigation renders the sidebar again on every page, with only the
 * section of the current page expanded. This script remembers which sections
 * are open (in sessionStorage, per browser tab) and opens them again after
 * every page load. The section of the current page is always open.
 *
 * Clicking a section name opens the section's index page and expands the
 * section. The chevron next to it expands or collapses without navigating.
 *
 * The same applies to the navigation drawer on narrow screens.
 */
(function () {
  "use strict";

  var KEY = "ope-nav-open";

  function load() {
    try {
      var value = JSON.parse(window.sessionStorage.getItem(KEY) || "[]");
      return Array.isArray(value) ? value : [];
    } catch (error) {
      return [];
    }
  }

  function save(ids) {
    try {
      window.sessionStorage.setItem(KEY, JSON.stringify(ids));
    } catch (error) {
      /* Storage is blocked: the state is simply not kept. */
    }
  }

  function toggles() {
    return document.querySelectorAll(
      ".md-sidebar--primary .md-nav__toggle[id^='__nav']"
    );
  }

  function setOpen(toggle, open) {
    toggle.checked = open;
    var nav = toggle.parentElement.querySelector(":scope > nav.md-nav");
    if (nav) nav.setAttribute("aria-expanded", String(open));
  }

  function remember() {
    var ids = [];
    toggles().forEach(function (toggle) {
      if (toggle.checked) ids.push(toggle.id);
    });
    save(ids);
  }

  function restore() {
    var open = load();
    toggles().forEach(function (toggle) {
      if (open.indexOf(toggle.id) !== -1) setOpen(toggle, true);
    });
    /* Also keep the section of this page open when the reader moves on. */
    remember();
  }

  document.addEventListener("change", function (event) {
    var toggle = event.target;
    if (!toggle.matches || !toggle.matches(".md-nav__toggle[id^='__nav']")) {
      return;
    }
    setOpen(toggle, toggle.checked);
    remember();
  });

  /* A click on the section name expands the section and opens its index page. */
  document.addEventListener("click", function (event) {
    if (!event.target.closest) return;
    var link = event.target.closest(".md-sidebar--primary .md-nav__container > a.md-nav__link");
    if (!link) return;
    var toggle = link.closest(".md-nav__item--nested").querySelector(":scope > .md-nav__toggle");
    if (toggle && !toggle.checked) {
      setOpen(toggle, true);
      remember();
    }
  });

  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(restore);
  } else {
    document.addEventListener("DOMContentLoaded", restore);
  }
})();
