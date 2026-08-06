"""
Bộ tạo menu chuột phải (Right-click Context Menu) và Phím tắt Bàn phím (Keyboard Shortcuts) cho Tkinter
"""

import tkinter as tk
from tkinter import ttk

def select_all_event(event):
    """Xử lý phím tắt Ctrl+A (Select All) chuẩn cho cả Text và Entry trên Linux/Windows"""
    widget = event.widget
    try:
        if isinstance(widget, tk.Text):
            widget.tag_add("sel", "1.0", "end-1c")
            widget.mark_set("insert", "end-1c")
            return "break"
        elif isinstance(widget, (tk.Entry, ttk.Entry, ttk.Spinbox)):
            widget.select_range(0, tk.END)
            widget.icursor(tk.END)
            return "break"
    except Exception:
        pass

def delete_prev_word_event(event):
    """Xử lý phím tắt Ctrl+Backspace (Xóa từ trước con trỏ)"""
    widget = event.widget
    try:
        if isinstance(widget, tk.Text):
            widget.delete("insert -1word", "insert")
            return "break"
        elif isinstance(widget, (tk.Entry, ttk.Entry, ttk.Spinbox)):
            idx = widget.index("insert")
            val = widget.get()
            if idx > 0:
                new_val = val[:idx].rstrip().rsplit(" ", 1)[0]
                widget.delete(0, tk.END)
                widget.insert(0, new_val + val[idx:])
                widget.icursor(len(new_val))
            return "break"
    except Exception:
        pass

def clear_text_event(event):
    """Xử lý phím tắt Ctrl+L (Xóa sạch văn bản trong ô nhập)"""
    widget = event.widget
    try:
        if isinstance(widget, tk.Text):
            widget.delete("1.0", "end")
            return "break"
        elif isinstance(widget, (tk.Entry, ttk.Entry, ttk.Spinbox)):
            widget.delete(0, tk.END)
            return "break"
    except Exception:
        pass

def setup_global_keyboard_shortcuts(root):
    """Đăng ký phím tắt toàn cục cho toàn bộ ứng dụng"""
    root.bind_all("<Control-a>", select_all_event)
    root.bind_all("<Control-A>", select_all_event)
    root.bind_all("<Control-BackSpace>", delete_prev_word_event)
    root.bind_all("<Control-l>", clear_text_event)
    root.bind_all("<Control-L>", clear_text_event)

def bind_right_click_menu(widget):
    """Liên kết menu chuột phải chuẩn (Cắt, Sao chép, Dán, Chọn tất cả, Xóa sạch) cho widget Entry hoặc Text."""
    menu = tk.Menu(widget, tearoff=0, bg="#121b28", fg="#dbe4f0", 
                   activebackground="#4f8cff", activeforeground="#ffffff", bd=1)
    
    def cut():
        try:
            widget.event_generate("<<Cut>>")
        except Exception:
            pass

    def copy():
        try:
            widget.event_generate("<<Copy>>")
        except Exception:
            pass

    def paste():
        try:
            widget.event_generate("<<Paste>>")
        except Exception:
            pass

    def select_all():
        try:
            widget.focus_set()
            if isinstance(widget, tk.Text):
                widget.tag_add("sel", "1.0", "end-1c")
                widget.mark_set("insert", "end-1c")
            else:
                widget.select_range(0, tk.END)
                widget.icursor(tk.END)
        except Exception:
            pass

    def clear_all():
        try:
            widget.focus_set()
            if isinstance(widget, tk.Text):
                widget.delete("1.0", "end")
            else:
                widget.delete(0, tk.END)
        except Exception:
            pass

    menu.add_command(label="✂ Cắt (Cut)", accelerator="Ctrl+X", command=cut)
    menu.add_command(label="📋 Sao chép (Copy)", accelerator="Ctrl+C", command=copy)
    menu.add_command(label="📥 Dán (Paste)", accelerator="Ctrl+V", command=paste)
    menu.add_separator()
    menu.add_command(label="🔍 Chọn tất cả (Select All)", accelerator="Ctrl+A", command=select_all)
    menu.add_command(label="🗑 Xóa sạch văn bản", accelerator="Ctrl+L", command=clear_all)

    # Đăng ký phím tắt Ctrl+A & Ctrl+L trực tiếp cho widget này
    widget.bind("<Control-a>", select_all_event)
    widget.bind("<Control-A>", select_all_event)
    widget.bind("<Control-l>", clear_text_event)
    widget.bind("<Control-L>", clear_text_event)

    def show_menu(event):
        try:
            widget.focus_set()
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    widget.bind("<Button-3>", show_menu)
