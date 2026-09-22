/* Talks to the Local Agent (local_agent/flasher_agent.py) on
 * http://localhost:8765 — see Administration > Local Agent for setup.
 * Shared by Build detail's "Flash to Device" and Kit Firmware Versions'
 * per-version "Flash" button. */
async function mmoFlashToDevice(opts) {
  const sel = document.getElementById(opts.selectId);
  const status = document.getElementById(opts.statusId);
  const optEl = sel.options[sel.selectedIndex];
  if (!sel.value) {
    status.style.color = '#b3261e';
    status.textContent = 'Pick a firmware version first.';
    return;
  }
  status.style.color = '';
  status.textContent = 'Contacting Local Agent on this PC…';
  try {
    const resp = await fetch('http://localhost:8765/flash', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        build_id: opts.buildId || null,
        firmware_version_id: parseInt(sel.value, 10),
        firmware_url: optEl.dataset.url,
        version_label: optEl.dataset.label,
      }),
    });
    const data = await resp.json();
    if (data.result === 'Success') {
      status.style.color = 'var(--accent)';
      status.textContent = 'Flashed successfully' + (data.device_port ? ' on ' + data.device_port : '') + ' — reloading…';
      setTimeout(() => location.reload(), 1200);
    } else {
      status.style.color = '#b3261e';
      status.textContent = 'Flash failed: ' + (data.error || data.log_output || 'see Local Agent console');
    }
  } catch (err) {
    status.style.color = '#b3261e';
    status.textContent = "Can't reach the Local Agent on this PC (http://localhost:8765) — is it running? See Administration > Local Agent.";
  }
}
