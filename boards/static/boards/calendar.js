const CalendarState = {
  enabled: false,
  mode: 'month', // month | week
  field: 'due',  // due | start | warn
  start: null,
};

function toggleCalendarMode() {
  CalendarState.enabled = !CalendarState.enabled;

  if (CalendarState.enabled) {
    renderCalendar();
  } else {
    window.location.reload(); // volta pro modo normal
  }
}

document.getElementById('cm-toggle-calendar')
  ?.addEventListener('click', toggleCalendarMode);
