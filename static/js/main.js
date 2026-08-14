// main.js — UI behavior for the BizData dashboard

document.addEventListener("DOMContentLoaded", () => {
    // Fade out and remove the page loader overlay.
    const pageLoader = document.getElementById("pageLoader");
    if (pageLoader) {
        const hide = () => {
            pageLoader.classList.add("loader-hidden");
            setTimeout(() => pageLoader.remove(), 500);
        };
        window.addEventListener("load", () => setTimeout(hide, 300));
        setTimeout(hide, 1200); // fallback if the window load event fires early
    }

    // Close the offcanvas sidebar automatically after clicking a link on mobile.
    const offcanvas = document.getElementById("sidebar");
    if (offcanvas) {
        offcanvas.querySelectorAll(".sidebar-link:not(.disabled)").forEach((link) => {
            link.addEventListener("click", () => {
                const instance = bootstrap.Offcanvas.getInstance(offcanvas);
                if (instance && window.innerWidth < 992) {
                    instance.hide();
                }
            });
        });
    }

    // Enable Bootstrap tooltips.
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
        new bootstrap.Tooltip(el);
    });

    // Wire up the delete confirmation modal (used on customers pages).
    const deleteModal = document.getElementById("deleteModal");
    if (deleteModal) {
        deleteModal.addEventListener("show.bs.modal", (event) => {
            const button = event.relatedTarget;
            const form = document.getElementById("deleteForm");
            const nameEl = document.getElementById("deleteCustomerName");
            if (button && form && nameEl) {
                form.action = `/customers/${button.dataset.customerId}/delete`;
                nameEl.textContent = button.dataset.customerName;
            }
        });
    }

    // Show the selected file name on the CSV import page.
    const fileInput = document.getElementById("csvFile");
    const fileHint = document.getElementById("fileHint");
    if (fileInput && fileHint) {
        fileInput.addEventListener("change", () => {
            fileHint.textContent = fileInput.files.length
                ? fileInput.files[0].name
                : "No file selected";
        });
    }

    // Auto-dismiss flash alerts after a few seconds.
    document.querySelectorAll(".alert").forEach((alertEl) => {
        setTimeout(() => {
            bootstrap.Alert.getOrCreateInstance(alertEl).close();
        }, 5000);
    });
});
