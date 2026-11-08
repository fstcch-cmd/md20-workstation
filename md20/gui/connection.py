"""D-147 GUI connection stability, free of NiceGUI imports so it can be tested anywhere."""
from __future__ import annotations

# D-147: client side of the connection.  Background tabs on Windows are throttled (timers ~1/min), the laptop sleeps,
# Wi-Fi drops: when the page is visible / online again and the socket is down, reconnect at once instead of waiting
# for the next back-off step.  A reconnect keeps the page (state is server-side and on disk, D-103); NiceGUI itself
# reloads the page when the server no longer knows this client (e.g. after a GUI restart).
CONNECTION_JS = """
<script>
(function () {
  function sock() { return window.socket || (window.nicegui && window.nicegui.socket) || null; }
  function wake() {
    var s = sock();
    if (s && !s.connected && typeof s.connect === "function") { try { s.connect(); } catch (e) {} }
  }
  document.addEventListener("visibilitychange", function () { if (!document.hidden) wake(); });
  window.addEventListener("online", wake);
  window.addEventListener("focus", wake);
})();
</script>
"""


HEARTBEAT = {"ping_interval": 20, "ping_timeout": 90}


def tune_heartbeat(sio=None) -> dict:
    """D-147: engine.io heartbeat.  The default ping timeout (20 s) drops a tab that Windows/Chrome throttles in the
    background or that misses pings while a large OpenMM XML holds the GIL (D-93); 90 s rides through both, and the
    socket still notices a closed browser within a couple of minutes.  Returns what was applied (empty if the
    NiceGUI version does not expose the server)."""
    try:
        if sio is None:
            from nicegui import core
            sio = getattr(core, "sio", None)
        eio = getattr(sio, "eio", None)
        if eio is None:
            return {}
        eio.ping_interval, eio.ping_timeout = HEARTBEAT["ping_interval"], HEARTBEAT["ping_timeout"]
        return dict(HEARTBEAT)
    except Exception:  # noqa: BLE001  (never block the GUI start on a tuning knob)
        return {}
