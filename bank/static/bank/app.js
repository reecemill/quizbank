// QuizBank page behavior. Every page works without this file; it adds the
// sliding lens in the tab bar, the drop-down menus, the ⌘K command palette,
// the pointer spotlight on cards and rows, live search, remembered toggles,
// the upload drop zone, toasts that dismiss themselves, and, for quizzes given
// to students: the copy-link button, local times, and the progress count.
(() => {
  "use strict";

  const root = document.documentElement;

  // Entrance animations only play on the first load (see .settled in app.css).
  setTimeout(() => root.classList.add("settled"), 1200);

  // Tab bar: a glass lens sits under the current tab and glides to whichever
  // tab the pointer (or keyboard focus) is on, like the tab bars in iOS.
  document.querySelectorAll("[data-tabs]").forEach((tabs) => {
    const lens = tabs.querySelector("[data-lens]");
    const current = tabs.querySelector('[aria-current="page"]');
    let target = current;

    const moveTo = (tab, animate = true) => {
      target = tab;
      if (!tab) {
        lens.classList.remove("is-visible");
        return;
      }
      const place = () => {
        lens.style.setProperty("--lens-x", `${tab.offsetLeft}px`);
        lens.style.setProperty("--lens-w", `${tab.offsetWidth}px`);
      };
      // Appearing from nothing, or re-measuring: jump there, don't slide.
      if (!animate || !lens.classList.contains("is-visible")) {
        lens.classList.add("no-anim");
        place();
        void lens.offsetWidth;
        lens.classList.remove("no-anim");
      } else {
        place();
      }
      lens.classList.add("is-visible");
    };

    moveTo(current, false);
    tabs.querySelectorAll(".tab").forEach((tab) => {
      tab.addEventListener("pointerenter", () => moveTo(tab));
      tab.addEventListener("focus", () => moveTo(tab));
    });
    tabs.addEventListener("pointerleave", () => moveTo(current));
    tabs.addEventListener("focusout", (event) => {
      if (!tabs.contains(event.relatedTarget)) moveTo(current);
    });
    // Tabs change size when the font loads or the layout switches to phone.
    new ResizeObserver(() => moveTo(target, false)).observe(tabs);
    document.fonts?.ready.then(() => moveTo(target, false));
  });

  // Drop-down menus (<details>): one open at a time, and they close on an
  // outside click or Escape.
  const menus = [...document.querySelectorAll("details[data-menu]")];
  menus.forEach((menu) => menu.addEventListener("toggle", () => {
    if (menu.open) menus.forEach((other) => { if (other !== menu) other.open = false; });
  }));
  document.addEventListener("click", (event) => {
    menus.forEach((menu) => { if (menu.open && !menu.contains(event.target)) menu.open = false; });
  });

  // Command palette: search every question, or jump straight to a course.
  const palette = document.querySelector("[data-palette]");
  const paletteInput = palette?.querySelector("input[type=search]");
  const paletteCourses = palette ? [...palette.querySelectorAll("[data-palette-course]")] : [];
  const paletteEmpty = palette?.querySelector("[data-palette-empty]");

  const filterCourses = () => {
    const words = paletteInput.value.trim().toLowerCase();
    let shown = 0;
    paletteCourses.forEach((link) => {
      const match = !words || link.dataset.paletteCourse.includes(words);
      link.hidden = !match;
      if (match) shown += 1;
    });
    if (paletteEmpty) paletteEmpty.hidden = shown > 0;
  };

  const openPalette = () => {
    if (!palette || palette.open) return;
    menus.forEach((menu) => { menu.open = false; });
    palette.showModal();
    paletteInput.select();
    filterCourses();
  };

  if (palette) {
    paletteInput.addEventListener("input", filterCourses);
    // A click outside the sheet lands on the dialog itself (its backdrop).
    palette.addEventListener("click", (event) => { if (event.target === palette) palette.close(); });
    document.querySelectorAll("[data-open-palette]").forEach((trigger) =>
      trigger.addEventListener("click", (event) => {
        event.preventDefault();
        openPalette();
      }));
  }

  // Show the shortcut the way this keyboard labels it.
  if (!/mac|iphone|ipad/i.test(navigator.userAgentData?.platform || navigator.platform || "")) {
    document.querySelectorAll("[data-shortcut]").forEach((hint) => { hint.textContent = "Ctrl K"; });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      const open = menus.find((menu) => menu.open);
      if (open) {
        open.open = false;
        open.querySelector("summary")?.focus();
      }
      return;
    }

    // ⌘K / Ctrl+K: the palette, from anywhere.
    if (event.key === "k" && (event.metaKey || event.ctrlKey) && palette) {
      event.preventDefault();
      if (palette.open) palette.close();
      else openPalette();
      return;
    }

    // "/": the page's own search box when it has one, otherwise the palette.
    const typing = event.target.closest?.("input, textarea, select, [contenteditable]");
    if (event.key === "/" && !typing && !palette?.open) {
      const pageSearch = document.querySelector("[data-live-search] input[type=search]");
      event.preventDefault();
      if (pageSearch) pageSearch.select();
      else openPalette();
    }
  });

  // Spotlight: cards and rows glow where the pointer is. One listener for the
  // whole page, at most one update per frame.
  const spotlight = matchMedia("(hover: hover) and (prefers-reduced-motion: no-preference)");
  let frame = 0;
  let lastMove;
  document.addEventListener("pointermove", (event) => {
    if (!spotlight.matches || event.pointerType !== "mouse") return;
    lastMove = event;
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      const target = lastMove.target.closest?.("[data-spotlight]");
      if (!target) return;
      const box = target.getBoundingClientRect();
      target.style.setProperty("--mx", `${lastMove.clientX - box.left}px`);
      target.style.setProperty("--my", `${lastMove.clientY - box.top}px`);
    });
  }, { passive: true });

  // Live search: fetch the results as you type and swap them in.
  const searchForm = document.querySelector("[data-live-search]");
  if (searchForm) {
    let timer;
    let controller;

    const refresh = async () => {
      const url = new URL(location.pathname, location.href);
      for (const [key, value] of new FormData(searchForm)) {
        if (value) url.searchParams.set(key, value);
      }
      controller?.abort();
      controller = new AbortController();
      try {
        const response = await fetch(url, { signal: controller.signal });
        if (!response.ok) return;
        const page = new DOMParser().parseFromString(await response.text(), "text/html");
        const fresh = page.getElementById("results");
        const current = document.getElementById("results");
        if (!fresh || !current) return;
        current.replaceWith(fresh);
        history.replaceState(null, "", url);
      } catch (error) {
        if (error.name !== "AbortError") searchForm.submit();
      }
    };

    searchForm.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(refresh, 250);
    });
    searchForm.addEventListener("submit", (event) => {
      event.preventDefault();
      clearTimeout(timer);
      refresh();
    });
  }

  // Segmented controls that remember their choice, like the quiz's
  // Answer key / Student view switch.
  document.querySelectorAll("[data-remember]").forEach((group) => {
    const key = `quizbank:${group.dataset.remember}`;
    try {
      const saved = localStorage.getItem(key);
      const input = saved && group.querySelector(`input[value="${CSS.escape(saved)}"]`);
      if (input) input.checked = true;
    } catch {
      // Storage can be blocked (private windows); the default choice is fine.
    }
    group.addEventListener("change", (event) => {
      try {
        localStorage.setItem(key, event.target.value);
      } catch {
        // Not remembered this time.
      }
    });
  });

  // Upload drop zone: show the chosen file's name and a drag highlight.
  document.querySelectorAll("[data-dropzone]").forEach((zone) => {
    const input = zone.querySelector('input[type="file"]');
    const label = zone.querySelector("[data-dropzone-label]");
    const prompt = label.textContent;
    const show = () => {
      const file = input.files[0];
      zone.classList.toggle("has-file", Boolean(file));
      label.textContent = file ? file.name : prompt;
    };
    input.addEventListener("change", show);
    input.addEventListener("dragenter", () => zone.classList.add("is-dragover"));
    input.addEventListener("dragleave", () => zone.classList.remove("is-dragover"));
    input.addEventListener("drop", () => zone.classList.remove("is-dragover"));
    show();
  });

  // Share link: copy it with one click.
  document.querySelectorAll("[data-copy]").forEach((button) => {
    const source = document.querySelector("[data-copy-source]");
    const label = button.querySelector("[data-copy-label]");
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(source.value);
        label.textContent = "Copied";
        setTimeout(() => { label.textContent = "Copy link"; }, 2000);
      } catch {
        source.select();
      }
    });
  });

  // Times are sent in UTC; show them in the viewer's own time zone.
  document.querySelectorAll("time[data-local]").forEach((time) => {
    const date = new Date(time.dateTime);
    if (!Number.isNaN(date.getTime())) {
      time.textContent = date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
    }
  });

  // Taking a quiz: count answered questions, and check before submitting
  // with some left blank.
  document.querySelectorAll("[data-take]").forEach((form) => {
    const questions = [...form.querySelectorAll("[data-question]")];
    const progress = form.querySelector("[data-progress]");
    const answered = (question) =>
      [...question.querySelectorAll("input, textarea")].some((field) =>
        (field.type === "radio" || field.type === "checkbox") ? field.checked : field.value.trim() !== "");
    const blanks = () => questions.filter((question) => !answered(question)).length;
    const update = () => {
      progress.textContent = `${questions.length - blanks()} of ${questions.length} answered`;
    };
    form.addEventListener("input", update);
    form.addEventListener("change", update);
    update();

    let sent = false;
    form.addEventListener("submit", (event) => {
      const left = blanks();
      if (sent || (left && !confirm(`${left} question${left === 1 ? " is" : "s are"} blank. Submit anyway?`))) {
        event.preventDefault();
        return;
      }
      sent = true;
    });
  });

  // Chart tooltips: any element with data-tip shows it on hover and on
  // keyboard focus. The text goes in with textContent, never as HTML.
  const tip = document.createElement("div");
  tip.className = "tip";
  tip.setAttribute("role", "tooltip");
  tip.hidden = true;
  document.body.append(tip);
  const showTip = (event) => {
    const target = event.target.closest?.("[data-tip]");
    if (!target) return;
    tip.textContent = target.dataset.tip;
    const box = target.getBoundingClientRect();
    tip.style.left = `${Math.min(Math.max(box.left + box.width / 2, 150), innerWidth - 150)}px`;
    tip.style.top = `${Math.max(box.top, 60)}px`;
    tip.hidden = false;
  };
  const hideTip = (event) => {
    if (event.target.closest?.("[data-tip]")) tip.hidden = true;
  };
  document.addEventListener("pointerover", showTip);
  document.addEventListener("pointerout", hideTip);
  document.addEventListener("focusin", showTip);
  document.addEventListener("focusout", hideTip);
  addEventListener("scroll", () => { tip.hidden = true; }, { passive: true });

  // Toasts: close on click; confirmations fade away on their own.
  const dismiss = (banner) => {
    banner.classList.add("is-leaving");
    setTimeout(() => banner.remove(), 300);
  };
  document.querySelectorAll(".banner").forEach((banner) => {
    banner.querySelector("[data-banner-close]")?.addEventListener("click", () => dismiss(banner));
    if (banner.hasAttribute("data-autohide")) setTimeout(() => dismiss(banner), 6000);
  });
})();
