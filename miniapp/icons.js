const icons={
  grid:'<rect x="3" y="3" width="7" height="7" rx="1.6"/><rect x="14" y="3" width="7" height="7" rx="1.6"/><rect x="3" y="14" width="7" height="7" rx="1.6"/><rect x="14" y="14" width="7" height="7" rx="1.6"/>',
  bag:'<path d="M6 7h12l1 13H5L6 7Z"/><path d="M9 7V5a3 3 0 0 1 6 0v2"/>',
  box:'<path d="m12 3 8.5 4.8-8.5 4.8-8.5-4.8L12 3Zm-8.5 4.8v8.4L12 21l8.5-4.8V7.8M12 12.6V21"/>',
  chart:'<path d="M4 19.5h16M7 16v-5M12 16V6M17 16v-8"/>',
  store:'<path d="M4 9.5h16l-1.6-5.5H5.6L4 9.5Zm1 0V19.5h14V9.5M9.5 19.5v-6h5v6"/>',
  shield:'<path d="m12 3 7 3v5.5c0 4.6-7 8.5-7 8.5s-7-3.9-7-8.5V6l7-3Z"/><path d="m8.8 12 2.2 2.2 4.4-4.6"/>',
  bell:'<path d="M6 16.5h12l-1.6-2.5V9.5a4.4 4.4 0 0 0-8.8 0V14L6 16.5ZM10.3 19.5h3.4"/>',
  refresh:'<path d="M20 11a8 8 0 0 0-14.3-4.8L4 8m0-4.5V8h4.5M4 13a8 8 0 0 0 14.3 4.8L20 16m0 4.5V16h-4.5"/>',
  search:'<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.2 4.2"/>',
  line:'<path d="m3.5 16.5 5-5 4 3 8-8.5"/>',
  bars:'<rect x="4" y="11" width="3.5" height="8" rx="1"/><rect x="10.25" y="6" width="3.5" height="13" rx="1"/><rect x="16.5" y="9" width="3.5" height="10" rx="1"/>',
  wallet:'<rect x="3.5" y="5.5" width="17" height="13" rx="2.2"/><path d="M15.5 12h5M16.5 12h.01"/>',
  layers:'<path d="m12 4 8.5 4.5L12 13 3.5 8.5 12 4Zm-8.5 8L12 16.5 20.5 12m-17 4L12 20.5 20.5 16"/>',
  calendar:'<rect x="3.5" y="5" width="17" height="15.5" rx="2.2"/><path d="M8 3.5v3M16 3.5v3M3.5 9.5h17"/>',
  star:'<path d="m12 3.8 2.4 4.9 5.4.8-3.9 3.8.9 5.4-4.8-2.5-4.8 2.5.9-5.4-3.9-3.8 5.4-.8L12 3.8Z"/>',
  alert:'<path d="M12 8.5v4.5M12 16.2h.01"/><path d="M10.3 4.3 2.9 17.2a2 2 0 0 0 1.7 3h14.8a2 2 0 0 0 1.7-3L13.7 4.3a2 2 0 0 0-3.4 0Z"/>',
  check:'<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  'arrow-up-right':'<path d="M7 17 17 7M8 7h9v9"/>',
  'arrow-down-right':'<path d="m7 7 10 10M8 17h9V8"/>'
};
const icon=(name)=>`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name]||icons.box}</svg>`;
function hydrateIcons(root=document){root.querySelectorAll('[data-icon]').forEach(el=>{el.innerHTML=icon(el.dataset.icon)})}
hydrateIcons();
