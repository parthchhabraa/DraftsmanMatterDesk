import time
import tkinter as tk

# Palette values copied from CARD_BG_ALT/LINE at the top of matterdesk.py.
# modules/*.py don't import matterdesk.py (it's run as __main__, not as a
# module named "matterdesk" — importing it here would re-execute the whole
# entrypoint file as a second module). Matches how telemetry.py/brain.py
# already hardcode their own color literals instead of cross-importing.
_CARD_BG_ALT = "#171b24"
_LINE = "#242938"


class MotionEngine:
    """
    Presentation-layer motion helpers for MatterDeskCore.

    Pure Tkinter: every animation is a chain of `root.after(ms, ...)` steps
    that interpolate a value with an ease-out curve. Nothing here blocks the
    UI thread (no time.sleep) and nothing here touches engine logic in
    modules/telemetry.py, modules/dpn.py, etc. — this only moves/colors/
    scales widgets that other code already builds and updates.

    Every animation can be given a `key`; starting a new tween under a key
    already in flight cancels the pending one first, so rapid repeated taps
    (toggle spam, fast nav) can't stack up runaway after() chains.
    """

    FRAME_MS = 16  # ~60fps

    def __init__(self, core):
        self.core = core
        self._active = {}  # key -> after() id, for cancelable tweens

    # --- easing ---
    @staticmethod
    def ease_out_cubic(t):
        t = 0.0 if t < 0 else (1.0 if t > 1 else t)
        return 1 - pow(1 - t, 3)

    # --- generic driver ---
    def cancel(self, key):
        job = self._active.pop(key, None)
        if job is not None:
            try:
                self.core.root.after_cancel(job)
            except Exception:
                pass

    def tween(self, duration_ms, on_update, on_complete=None, key=None, ease=None):
        """Drive on_update(eased_t) from t=0..1 over duration_ms via after().
        If key is given, any tween already running under that key is cancelled
        first (last write wins — used to keep taps/toggles/nav responsive)."""
        ease = ease or self.ease_out_cubic
        if key is not None:
            self.cancel(key)
        start = time.monotonic()

        def step():
            elapsed_ms = (time.monotonic() - start) * 1000.0
            t = 1.0 if duration_ms <= 0 else min(1.0, elapsed_ms / duration_ms)
            try:
                on_update(ease(t))
            except tk.TclError:
                # widget got destroyed (screen rebuilt/torn down) mid-tween — bail quietly
                if key is not None:
                    self._active.pop(key, None)
                return
            if t < 1.0:
                job = self.core.root.after(self.FRAME_MS, step)
                if key is not None:
                    self._active[key] = job
            else:
                if key is not None:
                    self._active.pop(key, None)
                if on_complete:
                    on_complete()

        step()

    # --- numeric value tween (telemetry count up/down, positions, etc.) ---
    def animate_number(self, key, from_val, to_val, duration_ms, setter, on_complete=None):
        def on_update(t):
            setter(from_val + (to_val - from_val) * t)
        self.tween(duration_ms, on_update, on_complete=on_complete, key=key)

    # --- color tween (any widget option that takes a Tk color) ---
    def _to_rgb8(self, widget, color):
        r, g, b = widget.winfo_rgb(color)  # Tk resolves names/hex to 16-bit channels
        return (r / 256.0, g / 256.0, b / 256.0)

    @staticmethod
    def _rgb8_to_hex(rgb):
        r, g, b = (max(0, min(255, int(round(v)))) for v in rgb)
        return f"#{r:02x}{g:02x}{b:02x}"

    def animate_widget_color(self, widget, duration_ms=200, key=None, on_complete=None, **target_options):
        """e.g. animate_widget_color(btn, bg=CARD_BG_ALT, fg=ACCENT_CYAN)."""
        try:
            froms = {opt: self._to_rgb8(widget, widget.cget(opt)) for opt in target_options}
            tos = {opt: self._to_rgb8(widget, target_options[opt]) for opt in target_options}
        except tk.TclError:
            return

        def on_update(t):
            kwargs = {}
            for opt, to in tos.items():
                fr = froms[opt]
                kwargs[opt] = self._rgb8_to_hex(tuple(fr[i] + (to[i] - fr[i]) * t for i in range(3)))
            try:
                widget.config(**kwargs)
            except tk.TclError:
                pass

        self.tween(duration_ms, on_update, on_complete=on_complete, key=key or f"color_{id(widget)}")

    # --- touch press feedback for plain tk.Button widgets ---
    def bind_press_feedback(self, button, press_ms=70, release_ms=150):
        """Quick color pulse on touch-down/up — the CarPlay-style tactile
        acknowledgment a touchscreen needs in place of a mouse hover state.
        Uses only colors already on the button/app palette, never a new one."""
        def on_press(_event):
            try:
                base_bg = button.cget("bg")
            except tk.TclError:
                return
            button._motion_base_bg = base_bg
            flash = _LINE if base_bg == _CARD_BG_ALT else _CARD_BG_ALT
            self.animate_widget_color(button, duration_ms=press_ms, key=f"press_{id(button)}", bg=flash)

        def on_release(_event):
            base_bg = getattr(button, "_motion_base_bg", None)
            if base_bg is None:
                return
            self.animate_widget_color(button, duration_ms=release_ms, key=f"press_{id(button)}", bg=base_bg)

        button.bind("<ButtonPress-1>", on_press, add="+")
        button.bind("<ButtonRelease-1>", on_release, add="+")
        # touch can also just leave the widget without a release event on some setups
        button.bind("<Leave>", on_release, add="+")

    # --- scale pulse for canvas-drawn tap targets (e.g. the home-screen app grid) ---
    def pulse_canvas_items(self, canvas, item_ids, cx, cy, peak=1.06, key=None):
        """Punch-in/ease-out scale pulse around (cx, cy) using Canvas.scale(),
        Tkinter's own (relative) scaling primitive — no fake transforms."""
        key = key or f"pulse_{item_ids}"
        state = {"applied": 1.0}

        def scale_to(target_scale):
            rel = target_scale / state["applied"]
            for iid in item_ids:
                try:
                    canvas.scale(iid, cx, cy, rel, rel)
                except tk.TclError:
                    pass
            state["applied"] = target_scale

        def phase_down():
            def on_update(t):
                scale_to(peak - (peak - 1.0) * t)
            self.tween(150, on_update, key=key)

        def phase_up(t):
            scale_to(1.0 + (peak - 1.0) * t)

        self.tween(70, phase_up, on_complete=phase_down, key=key)

    # --- screen/mode transitions: slide, since Tk widgets can't alpha-blend ---
    def slide_transition(self, outgoing, incoming, duration_ms=220, width=800, height=480):
        """Slides `incoming` in from the right while `outgoing` slides out to
        the left. Both frames are reset to their normal relwidth/relheight
        placement on completion so nothing else about frame sizing changes."""
        outgoing.place(x=0, y=0, width=width, height=height)
        incoming.place(x=width, y=0, width=width, height=height)
        incoming.tkraise()

        def on_update(t):
            try:
                incoming.place_configure(x=int(width * (1 - t)))
                outgoing.place_configure(x=int(-width * t))
            except tk.TclError:
                pass

        def on_complete():
            try:
                incoming.place(x=0, y=0, relwidth=1, relheight=1)
                outgoing.place(x=0, y=0, relwidth=1, relheight=1)
            except tk.TclError:
                pass

        self.tween(duration_ms, on_update, on_complete=on_complete, key="screen_nav")
