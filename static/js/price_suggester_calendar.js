/**
 * Price Suggester Calendar View
 * Handles calendar initialization and event rendering with FullCalendar
 */

document.addEventListener('DOMContentLoaded', function() {
    console.log('Calendar JS loaded');

    // Check if FullCalendar is available
    if (typeof FullCalendar === 'undefined') {
        console.error('FullCalendar library not loaded!');
        return;
    }
    console.log('FullCalendar library loaded:', FullCalendar);

    const calendarEl = document.getElementById('calendar');
    console.log('Calendar element:', calendarEl);

    if (!calendarEl) {
        console.error('Calendar element not found!');
        return; // Calendar element not present (list view)
    }

    // Get events data from data attribute
    const eventsData = calendarEl.dataset.events;
    console.log('Raw events data:', eventsData);

    let events = [];

    try {
        events = JSON.parse(eventsData);
        console.log('Parsed events:', events);
        console.log('Number of events:', events.length);
    } catch (e) {
        console.error('Failed to parse calendar events:', e);
        return;
    }

    // Initialize FullCalendar
    console.log('Initializing FullCalendar...');
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

    console.log('Calendar object created, now rendering...');
    calendar.render();
    console.log('Calendar render complete!');
});
