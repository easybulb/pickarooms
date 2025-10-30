/**
 * Price Suggester Calendar View
 * Handles calendar initialization and event rendering with FullCalendar
 */

document.addEventListener('DOMContentLoaded', function() {
    const calendarEl = document.getElementById('calendar');

    if (!calendarEl) {
        return; // Calendar element not present (list view)
    }

    // Get events data from data attribute
    const eventsData = calendarEl.dataset.events;
    let events = [];

    try {
        events = JSON.parse(eventsData);
    } catch (e) {
        console.error('Failed to parse calendar events:', e);
        return;
    }

    // Initialize FullCalendar
    const calendar = new FullCalendar.Calendar(calendarEl, {
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
            const props = info.event.extendedProps;
            let tooltip = props.venue + '\n' +
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
        windowResize: function(view) {
            if (window.innerWidth < 768) {
                calendar.changeView('listMonth');
            }
        },
        height: 'auto',
        contentHeight: 'auto',
        aspectRatio: 1.5
    });

    calendar.render();
});
