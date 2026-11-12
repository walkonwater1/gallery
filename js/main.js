/* =========================================================
   拾光 SHIGUANG — shared interactions
   ========================================================= */

(function () {
  "use strict";

  const prefersReducedMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)"
  ).matches;

  /* -------------------------------------------------------
     Header state
     ------------------------------------------------------- */
  const header = document.querySelector(".site-header");

  function updateHeader() {
    if (!header) return;
    header.classList.toggle("is-scrolled", window.scrollY > 28);
  }

  updateHeader();
  window.addEventListener("scroll", updateHeader, { passive: true });

  /* -------------------------------------------------------
     Print / save as PDF
     ------------------------------------------------------- */
  document.querySelectorAll("[data-print]").forEach(function (button) {
    button.addEventListener("click", function () {
      window.print();
    });
  });

  /* -------------------------------------------------------
     Mobile navigation
     ------------------------------------------------------- */
  const menuToggle = document.querySelector(".menu-toggle");
  const siteNav = document.getElementById("site-nav");

  function setMenu(open) {
    if (!menuToggle || !siteNav) return;
    menuToggle.setAttribute("aria-expanded", String(open));
    siteNav.classList.toggle("is-open", open);
    document.body.classList.toggle("menu-open", open);
  }

  if (menuToggle && siteNav) {
    menuToggle.addEventListener("click", function () {
      setMenu(menuToggle.getAttribute("aria-expanded") !== "true");
    });

    siteNav.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        setMenu(false);
      });
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && menuToggle.getAttribute("aria-expanded") === "true") {
        setMenu(false);
        menuToggle.focus();
      }
    });

    window.addEventListener("resize", function () {
      if (window.innerWidth > 860) setMenu(false);
    });
  }

  /* -------------------------------------------------------
     Scroll reveals
     ------------------------------------------------------- */
  const revealItems = document.querySelectorAll(".reveal");

  if (prefersReducedMotion || !("IntersectionObserver" in window)) {
    revealItems.forEach(function (item) {
      item.classList.add("is-visible");
    });
  } else {
    const revealObserver = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-visible");
          revealObserver.unobserve(entry.target);
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -6% 0px" }
    );

    revealItems.forEach(function (item) {
      revealObserver.observe(item);
    });
  }

  /* -------------------------------------------------------
     Reading progress (album pages)
     ------------------------------------------------------- */
  const progressBar = document.querySelector(".reading-progress span");
  const albumArticle = document.querySelector(".album");

  if (progressBar && albumArticle) {
    let ticking = false;

    function updateProgress() {
      const start = albumArticle.offsetTop;
      const distance = albumArticle.offsetHeight - window.innerHeight;
      const progress = distance > 0 ? (window.scrollY - start) / distance : 0;
      progressBar.style.width =
        Math.max(0, Math.min(1, progress)) * 100 + "%";
      ticking = false;
    }

    window.addEventListener(
      "scroll",
      function () {
        if (ticking) return;
        ticking = true;
        window.requestAnimationFrame(updateProgress);
      },
      { passive: true }
    );

    window.addEventListener("resize", updateProgress);
    updateProgress();
  }

  /* -------------------------------------------------------
     Lightbox gallery
     ------------------------------------------------------- */
  const photoLinks = Array.prototype.slice.call(
    document.querySelectorAll(".photo-link[data-caption]")
  );

  if (photoLinks.length) {
    const lightbox = document.createElement("div");
    lightbox.className = "lightbox";
    lightbox.setAttribute("role", "dialog");
    lightbox.setAttribute("aria-modal", "true");
    lightbox.setAttribute("aria-label", "照片预览");
    lightbox.setAttribute("aria-hidden", "true");
    lightbox.innerHTML = [
      '<div class="lightbox-top">',
      '  <span class="lightbox-counter" aria-live="polite"></span>',
      '  <button class="lightbox-close" type="button" aria-label="关闭照片预览"></button>',
      "</div>",
      '<div class="lightbox-stage">',
      '  <figure class="lightbox-figure">',
      '    <img class="lightbox-img" alt="">',
      '    <figcaption class="lightbox-caption"></figcaption>',
      "  </figure>",
      '  <button class="lightbox-nav lightbox-prev" type="button" aria-label="上一张照片">',
      '    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" aria-hidden="true"><path d="M15 5 8 12l7 7"/></svg>',
      "  </button>",
      '  <button class="lightbox-nav lightbox-next" type="button" aria-label="下一张照片">',
      '    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg>',
      "  </button>",
      "</div>"
    ].join("");

    document.body.appendChild(lightbox);

    const lightboxImg = lightbox.querySelector(".lightbox-img");
    const caption = lightbox.querySelector(".lightbox-caption");
    const counter = lightbox.querySelector(".lightbox-counter");
    const closeButton = lightbox.querySelector(".lightbox-close");
    const prevButton = lightbox.querySelector(".lightbox-prev");
    const nextButton = lightbox.querySelector(".lightbox-next");
    const navButtons = [prevButton, nextButton];

    let currentIndex = 0;
    let lastFocused = null;
    let previousBodyOverflow = "";

    if (photoLinks.length < 2) {
      navButtons.forEach(function (button) {
        button.hidden = true;
      });
    }

    function pad(number) {
      return String(number).padStart(2, "0");
    }

    function preload(index) {
      const link = photoLinks[(index + photoLinks.length) % photoLinks.length];
      const source = link && link.getAttribute("href");
      if (!source) return;
      const image = new Image();
      image.src = source;
    }

    function preloadNeighbours(index) {
      if (photoLinks.length < 2) return;
      preload(index - 1);
      preload(index + 1);
    }

    function render(index) {
      const link = photoLinks[index];
      const image = link.querySelector("img");
      const location = link.getAttribute("data-location");
      const text = link.getAttribute("data-caption") || image.alt || "";
      const total = photoLinks.length;

      currentIndex = index;
      lightbox.classList.remove("is-ready");
      lightboxImg.src = link.getAttribute("href");
      lightboxImg.alt = image ? image.alt : text;
      caption.textContent = location ? text + " · " + location : text;
      counter.textContent = pad(index + 1) + " / " + pad(total);
      preloadNeighbours(index);

      if (lightboxImg.complete) {
        window.requestAnimationFrame(function () {
          lightbox.classList.add("is-ready");
        });
      } else {
        lightboxImg.addEventListener(
          "load",
          function () {
            lightbox.classList.add("is-ready");
          },
          { once: true }
        );
      }
    }

    function openLightbox(index, trigger) {
      lastFocused = trigger || document.activeElement;
      previousBodyOverflow = document.body.style.overflow;
      lightbox.setAttribute("aria-hidden", "false");
      document.body.classList.add("lightbox-open");
      render(index);

      window.requestAnimationFrame(function () {
        lightbox.classList.add("is-open");
        closeButton.focus();
      });
    }

    function closeLightbox() {
      lightbox.classList.remove("is-open", "is-ready");
      lightbox.setAttribute("aria-hidden", "true");
      document.body.classList.remove("lightbox-open");
      document.body.style.overflow = previousBodyOverflow;
      if (lastFocused && typeof lastFocused.focus === "function") {
        lastFocused.focus();
      }
    }

    function showRelative(direction) {
      const nextIndex =
        (currentIndex + direction + photoLinks.length) % photoLinks.length;
      render(nextIndex);
    }

    photoLinks.forEach(function (link, index) {
      link.addEventListener("click", function (event) {
        event.preventDefault();
        openLightbox(index, link);
      });
    });

    closeButton.addEventListener("click", closeLightbox);
    prevButton.addEventListener("click", function () {
      showRelative(-1);
    });
    nextButton.addEventListener("click", function () {
      showRelative(1);
    });

    lightbox.addEventListener("click", function (event) {
      if (event.target === lightbox) closeLightbox();
    });

    /* Swipe between photos on touch devices */
    let touchStartX = 0;
    let touchStartY = 0;
    let touchStartTime = 0;
    let trackingTouch = false;

    lightbox.addEventListener(
      "touchstart",
      function (event) {
        if (event.touches.length !== 1 || photoLinks.length < 2) return;
        const touch = event.touches[0];
        touchStartX = touch.clientX;
        touchStartY = touch.clientY;
        touchStartTime = Date.now();
        trackingTouch = true;
      },
      { passive: true }
    );

    lightbox.addEventListener(
      "touchend",
      function (event) {
        if (!trackingTouch) return;
        trackingTouch = false;

        const touch = event.changedTouches[0];
        if (!touch) return;

        const deltaX = touch.clientX - touchStartX;
        const deltaY = touch.clientY - touchStartY;
        const isHorizontal =
          Math.abs(deltaX) > 48 && Math.abs(deltaX) > Math.abs(deltaY) * 1.2;
        const isQuick = Date.now() - touchStartTime < 700;

        if (!isHorizontal || !isQuick) return;

        event.preventDefault();
        showRelative(deltaX < 0 ? 1 : -1);
      },
      { passive: false }
    );

    lightbox.addEventListener("touchcancel", function () {
      trackingTouch = false;
    });

    document.addEventListener("keydown", function (event) {
      if (!lightbox.classList.contains("is-open")) return;

      if (event.key === "Escape") {
        event.preventDefault();
        closeLightbox();
        return;
      }

      if (event.key === "ArrowLeft") {
        event.preventDefault();
        showRelative(-1);
        return;
      }

      if (event.key === "ArrowRight") {
        event.preventDefault();
        showRelative(1);
        return;
      }

      if (event.key === "Home") {
        event.preventDefault();
        render(0);
        return;
      }

      if (event.key === "End") {
        event.preventDefault();
        render(photoLinks.length - 1);
        return;
      }

      if (event.key !== "Tab") return;

      const focusable = [closeButton, prevButton, nextButton].filter(function (button) {
        return !button.hidden && button.offsetParent !== null;
      });
      if (!focusable.length) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
  }
})();
