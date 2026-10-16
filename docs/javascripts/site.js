/*
 * Small behaviours of the docs site.
 *
 * - The site name in the header links to the home page, like the logo.
 *   Instant navigation replaces the logo on every page but not the site
 *   name, so the relative link is copied from the logo after each page load.
 * - A click anywhere on a card of a "grid cards" block opens the card's last
 *   link. Other links in the card, text selection and modifier clicks keep
 *   working.
 */
(function () {
  "use strict";

  var CARD = ".md-typeset .grid.cards > ul > li";
  var INTERACTIVE = "a, button, input, label, select, summary, textarea";

  function syncHomeLink() {
    var logo = document.querySelector(".md-header a.md-logo");
    var home = document.querySelector(".md-header .ope-header__home");
    if (logo && home) home.setAttribute("href", logo.getAttribute("href"));
  }

  function cardLink(card) {
    var links = card.querySelectorAll("a[href]");
    return links.length ? links[links.length - 1] : null;
  }

  function cardTarget(event) {
    if (!event.target.closest) return null;
    var card = event.target.closest(CARD);
    if (!card || event.target.closest(INTERACTIVE)) return null;
    var selection = window.getSelection();
    if (selection && !selection.isCollapsed && card.contains(selection.anchorNode)) {
      return null;
    }
    return cardLink(card);
  }

  document.addEventListener("click", function (event) {
    if (event.button !== 0) return;
    var link = cardTarget(event);
    if (!link) return;
    if (event.ctrlKey || event.metaKey || event.shiftKey) {
      window.open(link.href, "_blank", "noopener");
      return;
    }
    link.click();
  });

  document.addEventListener("auxclick", function (event) {
    if (event.button !== 1) return;
    var link = cardTarget(event);
    if (link) window.open(link.href, "_blank", "noopener");
  });

  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(syncHomeLink);
  } else {
    document.addEventListener("DOMContentLoaded", syncHomeLink);
  }
})();
