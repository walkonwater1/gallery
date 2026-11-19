/* =========================================================
   水上行走 SHIGUANG — shared interactions
   ========================================================= */

(function () {
  "use strict";

  const prefersReducedMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)"
  ).matches;

  /* -------------------------------------------------------
     Progressive covers — 先显示 480 缩略图，再后台换 1100 清晰图
     ------------------------------------------------------- */
  function upgradeCover(img) {
    const hi = img.getAttribute("data-hi");
    if (!hi) return Promise.resolve();
    img.removeAttribute("data-hi");
    return new Promise(function (resolve) {
      const loader = new Image();
      loader.onload = function () {
        img.src = hi;
        img.classList.add("is-hi");
        resolve();
      };
      loader.onerror = function () {
        /* 高清图加载失败时保留已显示的缩略图 */
        resolve();
      };
      loader.src = hi;
    });
  }

  const coverImgs = Array.prototype.slice.call(
    document.querySelectorAll(".archive-visual.is-progressive img[data-hi]")
  );
  if (coverImgs.length) {
    // 后台分批升级全部封面为高清，避免视口外的封面一直停在缩略图。
    // 每批 6 张，加载完一批再下一批，既快又不把链路打满。
    let cursor = 0;
    function pump() {
      const batch = coverImgs.slice(cursor, cursor + 6);
      cursor += batch.length;
      Promise.all(batch.map(upgradeCover)).then(function () {
        if (cursor < coverImgs.length) setTimeout(pump, 0);
      });
    }
    setTimeout(pump, 200);
  }

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
     Hidden photos — local preference only, originals untouched
     ------------------------------------------------------- */
  const HIDDEN_KEY = "shiguang-hidden-photos";

  function readHidden() {
    try {
      const stored = JSON.parse(window.localStorage.getItem(HIDDEN_KEY) || "[]");
      return Array.isArray(stored) ? stored : [];
    } catch (error) {
      return [];
    }
  }

  function writeHidden(names) {
    try {
      window.localStorage.setItem(HIDDEN_KEY, JSON.stringify(names));
    } catch (error) {
      /* private mode or storage disabled */
    }
  }

  function hideLink(link) {
    const box = link.closest("figure, .book-photo") || link;
    if (box.parentNode) box.parentNode.removeChild(box);
  }

  const hiddenOnLoad = readHidden();
  if (hiddenOnLoad.length) {
    const hiddenSet = new Set(hiddenOnLoad);
    document.querySelectorAll(".photo-link[data-photo-file]").forEach(function (link) {
      if (hiddenSet.has(link.getAttribute("data-photo-file"))) hideLink(link);
    });
  }

  /* -------------------------------------------------------
     Lightbox gallery
     ------------------------------------------------------- */
  let photoLinks = Array.prototype.slice.call(
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
      '  <div class="lightbox-tools" role="group" aria-label="照片工具">',
      '    <button class="lightbox-zoom-btn" type="button" data-zoom="out" aria-label="缩小">−</button>',
      '    <span class="lightbox-zoom-level" aria-live="polite">×1.0</span>',
      '    <button class="lightbox-zoom-btn" type="button" data-zoom="in" aria-label="放大">+</button>',
      '    <button class="lightbox-zoom-btn" type="button" data-zoom="native" aria-label="按原始像素查看">1:1</button>',
      '    <button class="lightbox-zoom-btn" type="button" data-zoom="reset" aria-label="适应屏幕">适应</button>',
      '    <button class="lightbox-zoom-btn lightbox-cover-btn" type="button" data-cover-set aria-label="把这张照片设为该册封面">设为封面</button>',
      '    <button class="lightbox-zoom-btn lightbox-book-btn" type="button" data-book-toggle aria-label="把这张照片加入画册" hidden>加入画册</button>',
      '    <button class="lightbox-zoom-btn lightbox-tag-btn" type="button" data-tag-set aria-label="给这张照片标注景点">标景点</button>',
      '    <button class="lightbox-zoom-btn lightbox-delete-btn" type="button" data-delete-set aria-label="从磁盘永久删除这张照片">删除照片</button>',
      "  </div>",
      '  <button class="lightbox-close" type="button" aria-label="关闭照片预览"></button>',
      "</div>",
      '<div class="lightbox-cover-hint" role="status" aria-live="polite" hidden></div>',
      '<div class="lightbox-stage">',
      '  <figure class="lightbox-figure">',
      '    <div class="lightbox-viewport">',
      '      <img class="lightbox-img" alt="">',
      "    </div>",
      '    <figcaption class="lightbox-caption"></figcaption>',
      "  </figure>",
      '  <button class="lightbox-nav lightbox-prev" type="button" aria-label="上一张照片">',
      '    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" aria-hidden="true"><path d="M15 5 8 12l7 7"/></svg>',
      "  </button>",
      '  <button class="lightbox-nav lightbox-next" type="button" aria-label="下一张照片">',
      '    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg>',
      "  </button>",
      "</div>",
      '<div class="lightbox-confirm" role="alertdialog" aria-modal="true" aria-labelledby="lightbox-confirm-title" hidden>',
      '  <div class="lightbox-confirm-box">',
      '    <p class="lightbox-confirm-eyebrow">Delete photo</p>',
      '    <h2 class="lightbox-confirm-title" id="lightbox-confirm-title">确定永久删除这张照片？</h2>',
      '    <p class="lightbox-confirm-file"></p>',
      '    <p class="lightbox-delete-note">警告：这张照片会从盒子磁盘上永久删除，无法恢复！请确认不再需要这张照片。</p>',
      '    <div class="lightbox-confirm-actions">',
      '      <button class="lightbox-confirm-cancel" type="button" data-confirm-cancel>取消</button>',
      '      <button class="lightbox-confirm-ok is-danger" type="button" data-confirm-ok>确认删除</button>',
      "    </div>",
      "  </div>",
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
    const viewport = lightbox.querySelector(".lightbox-viewport");
    const zoomLevel = lightbox.querySelector(".lightbox-zoom-level");
    const zoomButtons = Array.prototype.slice.call(
      lightbox.querySelectorAll(".lightbox-zoom-btn[data-zoom]")
    );
    const coverButton = lightbox.querySelector("[data-cover-set]");
    const deleteButton = lightbox.querySelector("[data-delete-set]");
    const tagButton = lightbox.querySelector("[data-tag-set]");
    const bookButton = lightbox.querySelector("[data-book-toggle]");
    const coverHint = lightbox.querySelector(".lightbox-cover-hint");
    const confirmLayer = lightbox.querySelector(".lightbox-confirm");
    const confirmFile = lightbox.querySelector(".lightbox-confirm-file");
    const confirmCancel = lightbox.querySelector("[data-confirm-cancel]");
    const confirmOk = lightbox.querySelector("[data-confirm-ok]");
    let coverHintTimer = 0;
    let pendingDelete = null;
    let bookFiles = new Set();
    let bookBusy = false;

    function copyCommand(text) {
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          return navigator.clipboard.writeText(text).then(
            function () { return true; },
            function () { return false; }
          );
        }
      } catch (error) {
        return Promise.resolve(false);
      }
      return new Promise(function (resolve) {
        const field = document.createElement("textarea");
        field.value = text;
        field.style.position = "fixed";
        field.style.opacity = "0";
        document.body.appendChild(field);
        field.select();
        let copied = false;
        try {
          copied = document.execCommand("copy");
        } catch (error) {
          copied = false;
        }
        document.body.removeChild(field);
        resolve(copied);
      });
    }

    function showHint(text, duration) {
      coverHint.textContent = text;
      coverHint.hidden = false;
      window.clearTimeout(coverHintTimer);
      coverHintTimer = window.setTimeout(function () {
        coverHint.hidden = true;
      }, duration || 12000);
    }

    function albumAction(action, payload) {
      return window.fetch("/api/" + action, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }).then(function (response) {
        return response.json().then(function (data) {
          if (!response.ok || !data.ok) {
            throw new Error(data.message || "请求失败");
          }
          return data;
        });
      });
    }

    function finishAction(message) {
      showHint(message + "，页面即将刷新显示最新结果…", 8000);
      window.setTimeout(function () {
        window.location.href = "index.html";
      }, 900);
    }

    function updateBookButton() {
      const link = photoLinks[currentIndex];
      const file = link && link.getAttribute("data-photo-file");
      const inside = !!file && bookFiles.has(file);
      bookButton.textContent = inside ? "移出画册" : "加入画册";
      bookButton.setAttribute(
        "aria-label",
        inside ? "把这张照片移出画册" : "把这张照片加入画册"
      );
    }

    function loadBookState() {
      return window.fetch("/api/book", { cache: "no-store" })
        .then(function (response) {
          return response.json().then(function (data) {
            if (!response.ok || !data.ok) throw new Error("book api failed");
            return data;
          });
        })
        .then(function (data) {
          bookFiles = new Set(data.photos || []);
          bookButton.hidden = false;
          updateBookButton();
        })
        .catch(function () {
          bookButton.hidden = true;
        });
    }

    bookButton.addEventListener("click", function () {
      if (bookBusy) return;
      const link = photoLinks[currentIndex];
      const file = link && link.getAttribute("data-photo-file");
      if (!file) {
        showHint("这张照片没有文件名信息，请运行一次 bash /root/start_sh/update-album.sh 重新生成。");
        return;
      }
      const action = bookFiles.has(file) ? "book-remove" : "book-add";
      bookBusy = true;
      bookButton.disabled = true;
      albumAction(action, { file: file })
        .then(function (data) {
          if (action === "book-add") bookFiles.add(file);
          else bookFiles.delete(file);
          updateBookButton();
          showHint((data.message || "画册已更新") + "。继续浏览照片，可把喜欢的逐张加入画册。", 6000);
        })
        .catch(function () {
          const command = "bash /root/start_sh/book-photo.sh " +
            (action === "book-add" ? "--add " : "--remove ") + file;
          showHint("画册管理服务暂不可用。在盒子上执行：" + command);
          copyCommand(command).then(function (copied) {
            if (copied && !coverHint.hidden && coverHint.firstChild) {
              coverHint.firstChild.textContent = "已复制命令：" + command;
            }
          });
        })
        .then(function () {
          bookBusy = false;
          bookButton.disabled = false;
        });
    });

    function fallbackCover(file) {
      const command = "bash /root/start_sh/set-cover.sh " + file;
      const config = '{"cover": "' + file + '"}';
      const suffix =
        " — 在盒子上执行一次即可；也可以把 " + config +
        " 写进该册目录的 album.json 后重新生成。";
      showHint("请在盒子上执行：" + command + suffix);
      copyCommand(command).then(function (copied) {
        if (copied && !coverHint.hidden) {
          coverHint.textContent = "已复制命令：" + command + suffix;
        }
      });
    }

    coverButton.addEventListener("click", function () {
      const link = photoLinks[currentIndex];
      const file = link && link.getAttribute("data-photo-file");
      if (!file) {
        showHint("这张照片没有文件名信息，请运行一次 bash /root/start_sh/update-album.sh 重新生成。");
        return;
      }
      showHint("正在设置封面，请稍候…");
      coverButton.disabled = true;
      albumAction("cover", { file: file })
        .then(function (data) { finishAction(data.message || "封面已设置"); })
        .catch(function () {
          coverButton.disabled = false;
          fallbackCover(file);
        });
    });

    function fallbackHide(file, link) {
      const names = readHidden();
      if (names.indexOf(file) < 0) {
        names.push(file);
        writeHidden(names);
      }
      hideLink(link);
      photoLinks.splice(currentIndex, 1);

      const command = "bash /root/start_sh/hide-photo.sh " + file;
      const showCommand = "bash /root/start_sh/hide-photo.sh --show " + file;
      const text =
        "已在本机隐藏 " + file +
        "。要在所有设备、刷新后都不再显示，请执行：" + command +
        " — 原文件不会被删除；恢复显示：" + showCommand;

      if (!photoLinks.length) {
        closeLightbox();
      } else {
        if (currentIndex >= photoLinks.length) currentIndex = photoLinks.length - 1;
        render(currentIndex);
        if (photoLinks.length < 2) {
          navButtons.forEach(function (button) { button.hidden = true; });
        }
      }

      showHint(text);
      const undo = document.createElement("button");
      undo.type = "button";
      undo.className = "lightbox-hint-undo";
      undo.textContent = "撤销本机隐藏";
      undo.addEventListener("click", function () {
        writeHidden(readHidden().filter(function (name) { return name !== file; }));
        window.location.reload();
      });
      coverHint.appendChild(undo);
      copyCommand(command).then(function (copied) {
        if (copied && !coverHint.hidden && coverHint.firstChild) {
          coverHint.firstChild.textContent = "已复制命令。" + text;
        }
      });
    }

    function openDeleteConfirm(file, path) {
      pendingDelete = { file: file, path: path || file };
      confirmFile.textContent = path || file;
      confirmLayer.hidden = false;
      confirmCancel.focus();
    }

    function closeDeleteConfirm() {
      pendingDelete = null;
      confirmLayer.hidden = true;
      deleteButton.disabled = false;
      deleteButton.focus();
    }

    function commitDelete() {
      if (!pendingDelete) return;
      const file = pendingDelete.file;
      const path = pendingDelete.path || file;
      confirmLayer.hidden = true;
      confirmFile.textContent = "";
      deleteButton.disabled = true;
      showHint("正在从盒子磁盘永久删除，请稍候…");
      albumAction("delete", { file: file, path: path })
        .then(function (data) {
          const link = photoLinks[currentIndex];
          if (link) hideLink(link);
          photoLinks.splice(currentIndex, 1);
          deleteButton.disabled = false;
          if (!photoLinks.length) {
            closeLightbox();
          } else {
            if (currentIndex >= photoLinks.length) currentIndex = photoLinks.length - 1;
            render(currentIndex);
          }
          showHint((data.message || "照片已删除") + "，已从本页移除；刷新后站点会自动更新。", 6000);
        })
        .catch(function (error) {
          deleteButton.disabled = false;
          showHint("删除失败：" + (error && error.message ? error.message : "请检查盒子 API"));
        });
      pendingDelete = null;
    }

    tagButton.addEventListener("click", function () {
      const link = photoLinks[currentIndex];
      const file = link && link.getAttribute("data-photo-file");
      if (!file) {
        showHint("这张照片没有文件名信息，请运行一次 bash /root/start_sh/update-album.sh 重新生成。");
        return;
      }
      const tag = window.prompt("给这张照片标注景点（留空取消）：", "");
      if (tag === null || !tag.trim()) return;
      const path = link.getAttribute("data-photo-path");
      tagButton.disabled = true;
      albumAction("tag", { file: file, path: path || file, tag: tag.trim() })
        .then(function (data) { showHint(data.message || "已标注景点", 5000); })
        .catch(function (error) {
          showHint("标注失败：" + (error && error.message ? error.message : "请检查盒子 API"));
        })
        .then(function () { tagButton.disabled = false; });
    });

    deleteButton.addEventListener("click", function () {
      const link = photoLinks[currentIndex];
      const file = link && link.getAttribute("data-photo-file");
      if (!file) {
        showHint("这张照片没有文件名信息，请运行一次 bash /root/start_sh/update-album.sh 重新生成。");
        return;
      }
      openDeleteConfirm(file, link.getAttribute("data-photo-path"));
    });

    confirmCancel.addEventListener("click", closeDeleteConfirm);
    confirmOk.addEventListener("click", commitDelete);
    confirmLayer.addEventListener("click", function (event) {
      if (event.target === confirmLayer) closeDeleteConfirm();
    });

    lightbox.addEventListener("click", function (event) {
      if (confirmLayer.hidden) return;
      if (!confirmLayer.contains(event.target)) {
        event.preventDefault();
        event.stopPropagation();
      }
    }, true);

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

    /* -----------------------------------------------------
       Zoom & pan — inspect the original photo up close
       ----------------------------------------------------- */
    const MIN_ZOOM = 1;
    const MAX_ZOOM = 10;
    let zoom = 1;
    let panX = 0;
    let panY = 0;
    let dragging = false;
    let dragPointerId = null;
    let dragStartX = 0;
    let dragStartY = 0;
    let panStartX = 0;
    let panStartY = 0;
    let lastPinchDistance = 0;
    let lastPinchX = 0;
    let lastPinchY = 0;
    let pinchActive = false;
    let touchPanStartX = 0;
    let touchPanStartY = 0;
    let touchMoved = false;
    let lastTapTime = 0;
    let lastTapX = 0;
    let lastTapY = 0;

    function clamp(value, min, max) {
      return Math.min(max, Math.max(min, value));
    }

    function viewportCenter() {
      const rect = viewport.getBoundingClientRect();
      return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    }

    function nativeZoom() {
      const shown = lightboxImg.offsetWidth;
      const natural = lightboxImg.naturalWidth;
      if (!shown || !natural) return 2;
      return clamp(natural / shown, MIN_ZOOM, MAX_ZOOM);
    }

    function clampPan() {
      const rect = viewport.getBoundingClientRect();
      const maxX = Math.max(0, (rect.width * (zoom - 1)) / 2);
      const maxY = Math.max(0, (rect.height * (zoom - 1)) / 2);
      panX = clamp(panX, -maxX, maxX);
      panY = clamp(panY, -maxY, maxY);
    }

    function applyZoom() {
      clampPan();
      lightboxImg.style.transform =
        "translate(" + panX + "px, " + panY + "px) scale(" + zoom + ")";
      zoomLevel.textContent = "×" + zoom.toFixed(1);
      viewport.classList.toggle("is-zoomed", zoom > 1.001);
      const isNative = Math.abs(zoom - nativeZoom()) < 0.05;
      zoomButtons.forEach(function (button) {
        const action = button.getAttribute("data-zoom");
        if (action === "out" || action === "reset") {
          button.disabled = zoom <= MIN_ZOOM + 0.001;
        } else if (action === "in") {
          button.disabled = zoom >= MAX_ZOOM - 0.001;
        } else if (action === "native") {
          button.classList.toggle("is-active", isNative);
        }
      });
    }

    function zoomAt(nextZoom, clientX, clientY) {
      const next = clamp(nextZoom, MIN_ZOOM, MAX_ZOOM);
      if (Math.abs(next - zoom) < 0.001) return;
      const rect = viewport.getBoundingClientRect();
      const anchorX = clientX - (rect.left + rect.width / 2);
      const anchorY = clientY - (rect.top + rect.height / 2);
      const ratio = next / zoom;
      panX = anchorX - (anchorX - panX) * ratio;
      panY = anchorY - (anchorY - panY) * ratio;
      zoom = next;
      if (zoom <= MIN_ZOOM + 0.001) {
        zoom = MIN_ZOOM;
        panX = 0;
        panY = 0;
      }
      applyZoom();
    }

    function resetZoom() {
      zoom = 1;
      panX = 0;
      panY = 0;
      dragging = false;
      viewport.classList.remove("is-dragging");
      applyZoom();
    }

    zoomButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        const action = button.getAttribute("data-zoom");
        const center = viewportCenter();
        if (action === "in") {
          zoomAt(zoom * 1.5, center.x, center.y);
        } else if (action === "out") {
          zoomAt(zoom / 1.5, center.x, center.y);
        } else if (action === "native") {
          const target = nativeZoom();
          zoomAt(Math.abs(zoom - target) < 0.05 ? MIN_ZOOM : target, center.x, center.y);
        } else {
          zoomAt(MIN_ZOOM, center.x, center.y);
        }
      });
    });

    viewport.addEventListener(
      "wheel",
      function (event) {
        event.preventDefault();
        const delta = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaY;
        zoomAt(zoom * Math.exp(-delta * 0.0015), event.clientX, event.clientY);
      },
      { passive: false }
    );

    viewport.addEventListener("dblclick", function (event) {
      event.preventDefault();
      zoomAt(zoom > 1.05 ? MIN_ZOOM : 2.5, event.clientX, event.clientY);
    });

    viewport.addEventListener("pointerdown", function (event) {
      if (event.pointerType === "touch") return;
      if (zoom <= 1.001 || (event.pointerType === "mouse" && event.button !== 0)) return;
      dragging = true;
      dragPointerId = event.pointerId;
      dragStartX = event.clientX;
      dragStartY = event.clientY;
      panStartX = panX;
      panStartY = panY;
      viewport.classList.add("is-dragging");
      try {
        if (viewport.setPointerCapture) viewport.setPointerCapture(event.pointerId);
      } catch (error) {
        /* pointer capture is best-effort */
      }
      event.preventDefault();
    });

    viewport.addEventListener("pointermove", function (event) {
      if (!dragging || event.pointerId !== dragPointerId) return;
      panX = panStartX + (event.clientX - dragStartX);
      panY = panStartY + (event.clientY - dragStartY);
      applyZoom();
    });

    function endDrag(event) {
      if (!dragging || (event && event.pointerId !== dragPointerId)) return;
      dragging = false;
      dragPointerId = null;
      viewport.classList.remove("is-dragging");
    }

    viewport.addEventListener("pointerup", endDrag);
    viewport.addEventListener("pointercancel", endDrag);

    function touchDistance(touches) {
      const dx = touches[0].clientX - touches[1].clientX;
      const dy = touches[0].clientY - touches[1].clientY;
      return Math.sqrt(dx * dx + dy * dy);
    }

    viewport.addEventListener(
      "touchstart",
      function (event) {
        if (event.touches.length === 2) {
          pinchActive = true;
          touchMoved = true;
          lastPinchDistance = touchDistance(event.touches);
          lastPinchX = (event.touches[0].clientX + event.touches[1].clientX) / 2;
          lastPinchY = (event.touches[0].clientY + event.touches[1].clientY) / 2;
          event.preventDefault();
        } else if (event.touches.length === 1) {
          touchPanStartX = event.touches[0].clientX;
          touchPanStartY = event.touches[0].clientY;
          panStartX = panX;
          panStartY = panY;
          touchMoved = false;
        }
      },
      { passive: false }
    );

    viewport.addEventListener(
      "touchmove",
      function (event) {
        if (event.touches.length === 2) {
          const distance = touchDistance(event.touches);
          const centerX = (event.touches[0].clientX + event.touches[1].clientX) / 2;
          const centerY = (event.touches[0].clientY + event.touches[1].clientY) / 2;
          if (lastPinchDistance > 0 && distance > 0) {
            zoomAt(zoom * (distance / lastPinchDistance), centerX, centerY);
          }
          panX += centerX - lastPinchX;
          panY += centerY - lastPinchY;
          applyZoom();
          lastPinchDistance = distance;
          lastPinchX = centerX;
          lastPinchY = centerY;
          touchMoved = true;
          event.preventDefault();
          return;
        }
        if (event.touches.length === 1 && zoom > 1.001) {
          const dx = event.touches[0].clientX - touchPanStartX;
          const dy = event.touches[0].clientY - touchPanStartY;
          if (Math.abs(dx) > 4 || Math.abs(dy) > 4) touchMoved = true;
          panX = panStartX + dx;
          panY = panStartY + dy;
          applyZoom();
          event.preventDefault();
        }
      },
      { passive: false }
    );

    viewport.addEventListener("touchend", function (event) {
      if (event.touches.length === 0) {
        lastPinchDistance = 0;
        if (pinchActive) {
          pinchActive = false;
          lastTapTime = 0;
          return;
        }
      }
      if (event.touches.length !== 0 || event.changedTouches.length !== 1) return;
      if (touchMoved) {
        lastTapTime = 0;
        return;
      }
      const touch = event.changedTouches[0];
      const now = Date.now();
      const isDoubleTap =
        now - lastTapTime < 320 &&
        Math.abs(touch.clientX - lastTapX) < 32 &&
        Math.abs(touch.clientY - lastTapY) < 32;
      if (isDoubleTap) {
        zoomAt(zoom > 1.05 ? MIN_ZOOM : 2.5, touch.clientX, touch.clientY);
        lastTapTime = 0;
      } else {
        lastTapTime = now;
        lastTapX = touch.clientX;
        lastTapY = touch.clientY;
      }
    });

    viewport.addEventListener("touchcancel", function () {
      lastPinchDistance = 0;
      pinchActive = false;
    });

    lightboxImg.addEventListener("load", function () {
      applyZoom();
    });

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
      resetZoom();
      coverHint.hidden = true;
      lightboxImg.src = link.getAttribute("href");
      lightboxImg.alt = image ? image.alt : text;
      caption.textContent = location ? text + " · " + location : text;
      counter.textContent = pad(index + 1) + " / " + pad(total);
      updateBookButton();
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
      if (!confirmLayer.hidden) {
        confirmLayer.hidden = true;
        pendingDelete = null;
      }
      resetZoom();
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

    function bindPhotoLinks() {
      photoLinks.forEach(function (link) {
        if (link.getAttribute("data-lightbox-bound") === "1") return;
        link.setAttribute("data-lightbox-bound", "1");
        link.addEventListener("click", function (event) {
          event.preventDefault();
          const index = photoLinks.indexOf(link);
          if (index >= 0) openLightbox(index, link);
        });
      });
    }

    function refreshLightbox() {
      photoLinks = Array.prototype.slice.call(
        document.querySelectorAll(".photo-link[data-caption]")
      );
      bindPhotoLinks();
      if (currentIndex >= photoLinks.length) currentIndex = 0;
      const single = photoLinks.length < 2;
      navButtons.forEach(function (button) { button.hidden = single; });
      if (lightbox.classList.contains("is-open")) closeLightbox();
    }

    window.SHIGUANG_LIGHTBOX = { refresh: refreshLightbox };
    bindPhotoLinks();
    loadBookState();

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
        if (!confirmLayer.hidden || event.touches.length !== 1 || photoLinks.length < 2 || zoom > 1.001) {
          trackingTouch = false;
          return;
        }
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

      if (!confirmLayer.hidden) {
        event.preventDefault();
        if (event.key === "Escape") closeDeleteConfirm();
        else if (event.key === "Enter") commitDelete();
        return;
      }

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

      if (
        event.key === "+" ||
        event.key === "=" ||
        event.key === "-" ||
        event.key === "_" ||
        event.key === "0"
      ) {
        event.preventDefault();
        const center = viewportCenter();
        if (event.key === "0") {
          resetZoom();
        } else if (event.key === "+" || event.key === "=") {
          zoomAt(zoom * 1.5, center.x, center.y);
        } else {
          zoomAt(zoom / 1.5, center.x, center.y);
        }
        return;
      }

      if (event.key !== "Tab") return;

      const focusable = zoomButtons
        .concat([coverButton, tagButton, deleteButton, closeButton, prevButton, nextButton])
        .filter(function (button) {
          return !button.hidden && !button.disabled && button.offsetParent !== null;
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
