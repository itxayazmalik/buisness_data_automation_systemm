// auth.js — behavior for the sign-in / register pages

document.addEventListener("DOMContentLoaded", () => {
    const toggle = (btn) => {
        const input = btn.closest(".input-group").querySelector("input");
        if (!input) return;
        const show = input.type === "password";
        input.type = show ? "text" : "password";
        btn.querySelector("i").className = show ? "bi bi-eye-slash" : "bi bi-eye";
    };

    document.querySelectorAll("[data-password-toggle]").forEach((btn) => {
        btn.addEventListener("click", () => toggle(btn));
    });

    const toggleBtn = document.getElementById("togglePassword");
    if (toggleBtn) {
        toggleBtn.addEventListener("click", () => toggle(toggleBtn));
    }
});
