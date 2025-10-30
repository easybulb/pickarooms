/**
 * Price Suggester Calendar View
 * Handles calendar initialization and event rendering with FullCalendar v5
 * Wrapped in IIFE to avoid conflicts with other scripts
 */

(function() {
    'use strict';

    // Wait for both DOM and FullCalendar to be ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initCalendar);
    } else {
        // DOM is already ready, init immediately
        initCalendar();
    }

    function initCalendar() {
        var calendarEl = document.getElementById('calendar');

        if (!calendarEl) {
            return;
        }

        // Check if FullCalendar is available
        if (typeof FullCalendar === 'undefined') {
            console.error('FullCalendar library not loaded');
            return;
        }

        // Get events data from script tag
        var dataScript = document.getElementById('calendar-events-data');
        if (!dataScript) {
            calendarEl.textContent = 'Error: Events data not found';
            return;
        }

        var eventsData = dataScript.textContent;
        var events = [];

        try {
            events = JSON.parse(eventsData || '[]');
        } catch (e) {
            console.error('Failed to parse calendar events:', e);
            calendarEl.textContent = 'Error loading calendar data';
            return;
        }

        // Initialize FullCalendar v5
        var calendar = new FullCalendar.Calendar(calendarEl, {
            initialView: window.innerWidth < 768 ? 'listMonth' : 'dayGridMonth',
            headerToolbar: {
                left: 'prev,next today',
                center: 'title',
                right: window.innerWidth < 768 ? 'listMonth' : 'dayGridMonth,listMonth'
            },
            events: events,
            eventClick: function(info) {
                // Redirect to event detail page
                window.location.href = '/admin-page/event/' + info.event.id + '/';
            },
            eventDidMount: function(info) {
                // Add tooltip with event details
                var props = info.event.extendedProps;
                var tooltip = props.venue + '\n' +
                             'Popularity: ' + props.popularity + '/100\n' +
                             'Suggested Price: £' + props.suggestedPrice;

                if (props.soldOut) {
                    tooltip += '\n[SOLD OUT]';
                }

                info.el.title = tooltip;

                // Add custom class for sold out events
                if (props.soldOut) {
                    info.el.classList.add('sold-out-event');
                }
            },
            // Responsive behavior
            windowResize: function(arg) {
                if (window.innerWidth < 768) {
                    calendar.changeView('listMonth');
                }
            },
            height: 'auto',
            contentHeight: 'auto',
            aspectRatio: 1.5
        });

        try {
            calendar.render();
        } catch (e) {
            console.error('Error rendering calendar:', e);
            calendarEl.textContent = 'Error rendering calendar';
        }
    }
})();
