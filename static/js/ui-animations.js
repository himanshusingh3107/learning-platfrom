document.addEventListener("DOMContentLoaded", () => {
    const interactiveElements = document.querySelectorAll(
        "button, .btn, .rail-button, .icon-button, .notification-button, .theme-button"
    );

    interactiveElements.forEach((element) => {
        element.addEventListener("click", (event) => {
            if (element.disabled || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

            const bounds = element.getBoundingClientRect();
            const ripple = document.createElement("span");
            const size = Math.max(bounds.width, bounds.height);

            ripple.className = "button-ripple";
            ripple.style.width = `${size}px`;
            ripple.style.height = `${size}px`;
            ripple.style.left = `${event.clientX - bounds.left - size / 2}px`;
            ripple.style.top = `${event.clientY - bounds.top - size / 2}px`;

            element.classList.remove("is-pressed");
            void element.offsetWidth;
            element.classList.add("is-pressed");
            element.appendChild(ripple);
            ripple.addEventListener("animationend", () => ripple.remove());
            element.addEventListener("animationend", () => element.classList.remove("is-pressed"), { once: true });
        });
    });
});
