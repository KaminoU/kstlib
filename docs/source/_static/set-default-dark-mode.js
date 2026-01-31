(function () {
    "use strict";

    const storageKey = "theme";
    const prefersDark = "dark";

    // Only enforce the default for first-time visitors so manual toggles persist.
    if (!window.localStorage.getItem(storageKey)) {
        window.localStorage.setItem(storageKey, prefersDark);
    }

    if (window.localStorage.getItem(storageKey) === prefersDark) {
        document.documentElement.dataset.theme = prefersDark;
    }
})();
