"""Shared, high-contrast states for existing Tkinter buttons."""

import tkinter as tk

from config.constants import (
    ACCENT_COLOR,
    BUTTON_DANGER_ACTIVE,
    BUTTON_DANGER_BG,
    BUTTON_DISABLED_BG,
    BUTTON_DISABLED_FG,
    BUTTON_PRIMARY_ACTIVE,
    BUTTON_PRIMARY_BG,
    BUTTON_SECONDARY_ACTIVE,
)


def apply_button_theme(parent):
    for widget in parent.winfo_children():
        if isinstance(widget, tk.Button):
            background = widget.cget("background").lower()
            if background == ACCENT_COLOR.lower():
                normal, active = BUTTON_PRIMARY_BG, BUTTON_PRIMARY_ACTIVE
            elif background in {"#e11d48", "#be123c", "#831843"}:
                normal, active = BUTTON_DANGER_BG, BUTTON_DANGER_ACTIVE
            else:
                normal, active = widget.cget("background"), BUTTON_SECONDARY_ACTIVE

            widget.config(
                bg=normal,
                activebackground=active,
                activeforeground="#FFFFFF",
                disabledforeground=BUTTON_DISABLED_FG,
                highlightcolor="#60A5FA",
            )
            widget._normal_background = normal
        apply_button_theme(widget)


def set_button_busy(button, busy, normal_text, busy_text):
    button.config(
        state="disabled" if busy else "normal",
        text=busy_text if busy else normal_text,
        bg=BUTTON_DISABLED_BG if busy else getattr(button, "_normal_background", BUTTON_PRIMARY_BG),
    )
