/**
 * Asynchronous interactive controls for COVID-19 Tracker Dashboard.
 * Handles AJAX requests for filter modifications, Plotly rendering, and ETL trigger.
 */

document.addEventListener('DOMContentLoaded', () => {
    // DOM Cache
    const countrySelect = document.getElementById('country-select');
    const metricSelect = document.getElementById('metric-select');
    const startDateInput = document.getElementById('start-date');
    const endDateInput = document.getElementById('end-date');
    const refreshBtn = document.getElementById('refresh-pipeline-btn');
    const refreshSpinner = document.getElementById('refresh-spinner');
    
    // --- Toast Alerts ---
    function showToast(message, type = 'info') {
        let toast = document.getElementById('custom-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'custom-toast';
            toast.className = 'toast';
            document.body.appendChild(toast);
        }
        
        toast.textContent = message;
        
        // Style depending on type
        if (type === 'success') {
            toast.style.borderLeftColor = 'var(--success)';
        } else if (type === 'error') {
            toast.style.borderLeftColor = 'var(--danger)';
        } else {
            toast.style.borderLeftColor = 'var(--primary)';
        }
        
        toast.classList.add('show');
        
        setTimeout(() => {
            toast.classList.remove('show');
        }, 4000);
    }

    // --- Fetch and Update Plotly Charts ---
    async function updateCharts() {
        // Collect selected countries (from multiselect)
        const selectedCountries = Array.from(countrySelect.selectedOptions).map(option => option.value);
        if (selectedCountries.length === 0) {
            showToast("Please select at least one country.", "warning");
            return;
        }

        const metric = metricSelect.value;
        const startDate = startDateInput.value;
        const endDate = endDateInput.value;

        // Anomaly / sanity check on date ranges
        if (startDate && endDate && startDate > endDate) {
            showToast("Start date cannot be after end date.", "warning");
            return;
        }

        try {
            // Fetch updated timeseries interactive chart
            const params = new URLSearchParams();
            selectedCountries.forEach(c => params.append('countries', c));
            params.append('metric', metric);
            if (startDate) params.append('start_date', startDate);
            if (endDate) params.append('end_date', endDate);

            const url = `/api/charts/cases?${params.toString()}`;
            const response = await fetch(url);
            
            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.error || `HTTP error ${response.status}`);
            }

            const chartData = await response.json();
            
            // Render using global Plotly library (loaded in html)
            Plotly.react('plotly-cases-chart', chartData.data, chartData.layout);

        } catch (error) {
            console.error("Failed to load interactive charts:", error);
            showToast(`Error rendering trends: ${error.message}`, "error");
        }
    }

    // --- ETL Refresh Trigger ---
    if (refreshBtn) {
        refreshBtn.addEventListener('click', async () => {
            // Lock UI
            refreshBtn.disabled = true;
            refreshSpinner.style.display = 'inline-block';
            showToast("Triggering daily data refresh pipeline...", "info");

            try {
                const response = await fetch('/api/refresh', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.error || `Refresh failed with status ${response.status}`);
                }

                showToast(`ETL pipeline completed! Loaded: ${data.countries_inserted_or_updated} countries, ${data.case_records_inserted_or_updated} cases.`, "success");
                
                // Refresh window to reload metric cards, maps, and static images
                setTimeout(() => {
                    window.location.reload();
                }, 2000);

            } catch (error) {
                console.error("ETL pipeline refresh error:", error);
                showToast(`ETL pipeline refresh failed: ${error.message}`, "error");
            } finally {
                // Unlock UI
                refreshBtn.disabled = false;
                refreshSpinner.style.display = 'none';
            }
        });
    }

    // --- Bind Event Listeners ---
    if (countrySelect) countrySelect.addEventListener('change', updateCharts);
    if (metricSelect) metricSelect.addEventListener('change', updateCharts);
    if (startDateInput) startDateInput.addEventListener('change', updateCharts);
    if (endDateInput) endDateInput.addEventListener('change', updateCharts);

    // Initial render trigger
    if (countrySelect && metricSelect) {
        updateCharts();
    }
});
