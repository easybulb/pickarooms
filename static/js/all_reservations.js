// All Reservations Page - JavaScript
// Handles pagination (25 per page) and bulk selection

document.addEventListener("DOMContentLoaded", function () {
    const rowsPerPage = 25; // Changed from 10 to 25
    let currentPage = 1;

    const tbody = document.getElementById("reservations-tbody");
    const rows = Array.from(document.querySelectorAll(".reservation-row"));
    const totalCount = document.getElementById("total-count");
    const showingInfo = document.getElementById("showing-info");
    const paginationControls = document.getElementById("pagination-controls");

    const totalRows = rows.length;
    const totalPages = Math.ceil(totalRows / rowsPerPage);

    // Display specific page
    function displayPage(page) {
        currentPage = page;

        // Hide all rows
        rows.forEach(row => row.style.display = "none");

        // Calculate range
        const start = (page - 1) * rowsPerPage;
        const end = Math.min(start + rowsPerPage, totalRows);

        // Show rows for current page
        for (let i = start; i < end; i++) {
            rows[i].style.display = "";
        }

        // Update showing info
        if (totalRows === 0) {
            showingInfo.textContent = "0";
        } else {
            showingInfo.textContent = `${start + 1}-${end} of ${totalRows}`;
        }

        // Update pagination controls
        renderPaginationControls();

        // Update checkbox states after page change
        updateSelectionUI();
    }

    // Render pagination controls
    function renderPaginationControls() {
        paginationControls.innerHTML = "";

        if (totalPages <= 1) {
            return; // No pagination needed
        }

        // Previous button
        const prevBtn = document.createElement("button");
        prevBtn.textContent = "← Previous";
        prevBtn.disabled = currentPage === 1;
        prevBtn.addEventListener("click", () => displayPage(currentPage - 1));
        paginationControls.appendChild(prevBtn);

        // Page numbers logic
        const maxVisiblePages = 7;
        let startPage = Math.max(1, currentPage - Math.floor(maxVisiblePages / 2));
        let endPage = Math.min(totalPages, startPage + maxVisiblePages - 1);

        if (endPage - startPage < maxVisiblePages - 1) {
            startPage = Math.max(1, endPage - maxVisiblePages + 1);
        }

        // First page
        if (startPage > 1) {
            const firstBtn = document.createElement("button");
            firstBtn.textContent = "1";
            firstBtn.addEventListener("click", () => displayPage(1));
            paginationControls.appendChild(firstBtn);

            if (startPage > 2) {
                const ellipsis = document.createElement("span");
                ellipsis.textContent = "...";
                paginationControls.appendChild(ellipsis);
            }
        }

        // Page number buttons
        for (let i = startPage; i <= endPage; i++) {
            const pageBtn = document.createElement("button");
            pageBtn.textContent = i;
            pageBtn.classList.toggle("active", i === currentPage);
            pageBtn.addEventListener("click", () => displayPage(i));
            paginationControls.appendChild(pageBtn);
        }

        // Last page
        if (endPage < totalPages) {
            if (endPage < totalPages - 1) {
                const ellipsis = document.createElement("span");
                ellipsis.textContent = "...";
                paginationControls.appendChild(ellipsis);
            }

            const lastBtn = document.createElement("button");
            lastBtn.textContent = totalPages;
            lastBtn.addEventListener("click", () => displayPage(totalPages));
            paginationControls.appendChild(lastBtn);
        }

        // Next button
        const nextBtn = document.createElement("button");
        nextBtn.textContent = "Next →";
        nextBtn.disabled = currentPage === totalPages;
        nextBtn.addEventListener("click", () => displayPage(currentPage + 1));
        paginationControls.appendChild(nextBtn);
    }

    // Initialize pagination
    if (totalRows > 0) {
        displayPage(1);
    } else {
        showingInfo.textContent = "0";
    }

    // ===== Bulk Delete Functionality =====
    const bulkActionsDiv = document.getElementById('bulk-actions');
    const selectedCountSpan = document.getElementById('selected-count');
    const bulkDeleteBtn = document.getElementById('bulk-delete-btn');
    const selectedIdsContainer = document.getElementById('selected-ids-container');
    const selectAllHeaderCheckbox = document.getElementById('select-all-header');
    const selectAllBtn = document.getElementById('select-all-btn');
    const deselectAllBtn = document.getElementById('deselect-all-btn');

    // Get all checkboxes
    function getAllCheckboxes() {
        return Array.from(document.querySelectorAll('.reservation-checkbox'));
    }

    // Get visible checkboxes on current page
    function getVisibleCheckboxes() {
        return getAllCheckboxes().filter(cb => {
            const row = cb.closest('tr');
            return row && row.style.display !== 'none';
        });
    }

    // Update selection UI
    function updateSelectionUI() {
        const allCheckboxes = getAllCheckboxes();
        const selectedCheckboxes = allCheckboxes.filter(cb => cb.checked);
        const count = selectedCheckboxes.length;

        // Update count
        selectedCountSpan.textContent = count;

        // Show/hide bulk actions
        if (count > 0) {
            bulkActionsDiv.style.display = 'flex';
            bulkDeleteBtn.disabled = false;
        } else {
            bulkActionsDiv.style.display = 'none';
            bulkDeleteBtn.disabled = true;
        }

        // Update header checkbox
        const visibleCheckboxes = getVisibleCheckboxes();
        const visibleChecked = visibleCheckboxes.filter(cb => cb.checked).length;
        
        if (visibleCheckboxes.length > 0) {
            selectAllHeaderCheckbox.checked = visibleChecked === visibleCheckboxes.length;
            selectAllHeaderCheckbox.indeterminate = visibleChecked > 0 && visibleChecked < visibleCheckboxes.length;
        } else {
            selectAllHeaderCheckbox.checked = false;
            selectAllHeaderCheckbox.indeterminate = false;
        }

        // Update hidden inputs
        selectedIdsContainer.innerHTML = '';
        selectedCheckboxes.forEach(cb => {
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'reservation_ids';
            input.value = cb.value;
            selectedIdsContainer.appendChild(input);
        });
    }

    // Individual checkbox change
    getAllCheckboxes().forEach(checkbox => {
        checkbox.addEventListener('change', updateSelectionUI);
    });

    // Header checkbox (select/deselect visible)
    selectAllHeaderCheckbox.addEventListener('change', function() {
        const visibleCheckboxes = getVisibleCheckboxes();
        visibleCheckboxes.forEach(cb => {
            cb.checked = this.checked;
        });
        updateSelectionUI();
    });

    // Select all button (all pages)
    selectAllBtn.addEventListener('click', function() {
        getAllCheckboxes().forEach(cb => cb.checked = true);
        updateSelectionUI();
    });

    // Deselect all button
    deselectAllBtn.addEventListener('click', function() {
        getAllCheckboxes().forEach(cb => cb.checked = false);
        updateSelectionUI();
    });

    // Initial update
    updateSelectionUI();
});

// Confirm bulk delete
function confirmBulkDelete() {
    const count = document.getElementById('selected-count').textContent;
    return confirm(`Are you sure you want to delete ${count} reservation(s)? This action cannot be undone.`);
}
