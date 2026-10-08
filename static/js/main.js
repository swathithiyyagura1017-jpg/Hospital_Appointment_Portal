/**
 * Hospital & Patient Appointment Management Portal
 * JavaScript ES6+ Frontend Logic
 */

document.addEventListener('DOMContentLoaded', () => {
    initDepartmentFilter();
    initSlotPicker();
    initDateRestrictions();
    initAlertAutoDismiss();
});

/**
 * 1. JavaScript Department Filtering for Doctor List
 */
function initDepartmentFilter() {
    const filterPills = document.querySelectorAll('.dept-pill');
    const doctorCards = document.querySelectorAll('.doctor-card-wrapper');
    const countDisplay = document.getElementById('visibleDoctorCount');
    const noResultsMsg = document.getElementById('noDoctorsMessage');

    if (!filterPills.length || !doctorCards.length) return;

    filterPills.forEach(pill => {
        pill.addEventListener('click', (e) => {
            e.preventDefault();
            const targetDept = pill.getAttribute('data-dept');

            // Update active pill state
            filterPills.forEach(p => p.classList.remove('active'));
            pill.classList.add('active');

            let visibleCount = 0;

            doctorCards.forEach(card => {
                const cardDept = card.getAttribute('data-department');
                if (targetDept === 'all' || cardDept === targetDept) {
                    card.classList.remove('d-none');
                    visibleCount++;
                } else {
                    card.classList.add('d-none');
                }
            });

            if (countDisplay) {
                countDisplay.textContent = visibleCount;
            }

            if (noResultsMsg) {
                if (visibleCount === 0) {
                    noResultsMsg.classList.remove('d-none');
                } else {
                    noResultsMsg.classList.add('d-none');
                }
            }
        });
    });
}

/**
 * 2. Dynamic Slot Availability Picker (ES6 fetch API)
 */
function initSlotPicker() {
    const doctorSelect = document.getElementById('id_doctor');
    const dateInput = document.getElementById('id_date');
    const slotSelect = document.getElementById('id_time_slot');
    const slotGridContainer = document.getElementById('slotGridContainer');
    const slotGrid = document.getElementById('slotGrid');
    const slotLoading = document.getElementById('slotLoading');
    const slotSelectedNotice = document.getElementById('slotSelectedNotice');

    if (!doctorSelect || !dateInput || !slotSelect || !slotGrid) return;

    async function fetchAndUpdateSlots() {
        const doctorId = doctorSelect.value;
        const selectedDate = dateInput.value;

        if (!doctorId || !selectedDate) {
            slotGridContainer.classList.add('d-none');
            return;
        }

        slotGridContainer.classList.remove('d-none');
        slotLoading.classList.remove('d-none');
        slotGrid.innerHTML = '';

        try {
            const response = await fetch(`/api/slots/?doctor_id=${encodeURIComponent(doctorId)}&date=${encodeURIComponent(selectedDate)}`);
            if (!response.ok) {
                throw new Error('Failed to fetch slot availability');
            }

            const data = await response.json();
            slotLoading.classList.add('d-none');
            renderSlotButtons(data.slots);
        } catch (error) {
            console.error('Error fetching slots:', error);
            slotLoading.classList.add('d-none');
            slotGrid.innerHTML = `<div class="col-12 text-danger small">Unable to load live availability. You can still select a time slot from the dropdown list.</div>`;
        }
    }

    function renderSlotButtons(slots) {
        slotGrid.innerHTML = '';
        const currentSelectedVal = slotSelect.value;

        slots.forEach(slot => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'slot-btn';
            btn.textContent = slot.label;
            btn.setAttribute('data-slot-code', slot.code);

            if (slot.is_booked) {
                btn.classList.add('booked');
                btn.disabled = true;
                btn.title = 'This slot has already been booked';
            } else if (slot.is_past) {
                btn.disabled = true;
                btn.title = 'Slot is in the past';
            } else {
                if (currentSelectedVal === slot.code) {
                    btn.classList.add('selected');
                }

                btn.addEventListener('click', () => {
                    // Remove selected state from all
                    document.querySelectorAll('.slot-btn').forEach(b => b.classList.remove('selected'));
                    btn.classList.add('selected');

                    // Update form select input
                    slotSelect.value = slot.code;
                    if (slotSelectedNotice) {
                        slotSelectedNotice.textContent = `Selected Slot: ${slot.label}`;
                        slotSelectedNotice.classList.remove('d-none');
                    }
                });
            }

            slotGrid.appendChild(btn);
        });
    }

    doctorSelect.addEventListener('change', fetchAndUpdateSlots);
    dateInput.addEventListener('change', fetchAndUpdateSlots);
    slotSelect.addEventListener('change', () => {
        const val = slotSelect.value;
        document.querySelectorAll('.slot-btn').forEach(b => {
            if (b.getAttribute('data-slot-code') === val) {
                b.classList.add('selected');
                if (slotSelectedNotice) {
                    slotSelectedNotice.textContent = `Selected Slot: ${b.textContent}`;
                    slotSelectedNotice.classList.remove('d-none');
                }
            } else {
                b.classList.remove('selected');
            }
        });
    });

    // Initial check if values are already populated
    if (doctorSelect.value && dateInput.value) {
        fetchAndUpdateSlots();
    }
}

/**
 * 3. Client-side Date Validation (Minimum date is today)
 */
function initDateRestrictions() {
    const dateInput = document.getElementById('id_date');
    if (!dateInput) return;

    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, '0');
    const dd = String(today.getDate()).padStart(2, '0');
    const minDateStr = `${yyyy}-${mm}-${dd}`;

    dateInput.setAttribute('min', minDateStr);
}

/**
 * 4. Auto-dismiss alerts after 5 seconds
 */
function initAlertAutoDismiss() {
    const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
    alerts.forEach(alert => {
        setTimeout(() => {
            try {
                const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
                if (bsAlert) bsAlert.close();
            } catch (err) {
                // bootstrap alert instance might not be available
            }
        }, 5000);
    });
}
