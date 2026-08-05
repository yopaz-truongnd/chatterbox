"""
Bộ tạo menu chuột phải (Right-click Context Menu) cho các Widget Text và Entry trong Tkinter
"""

import tkinter as tk

def bind_right_click_menu(widget):
    """Liên kết menu chuột phải chuẩn (Cắt, Sao chép, Dán, Chọn tất cả) cho widget Entry hoặc Text."""
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
            else:
                widget.select_range(0, tk.END)
                widget.icursor(tk.END)
        except Exception:
            pass

    menu.add_command(label="✂ Cắt (Cut)", command=cut)
    menu.add_command(label="📋 Sao chép (Copy)", command=copy)
    menu.add_command(label="📥 Dán (Paste)", command=paste)
    menu.add_separator()
    menu.add_command(label="🔍 Chọn tất cả (Select All)", command=select_all)

    def show_menu(event):
        try:
            widget.focus_set()
            # Hiển thị menu tại vị trí con trỏ chuột
            menu.post(event.x_root, event.y_root)
        except Exception:
            pass

    # Button-3 là chuột phải trên Windows/Linux
    widget.bind("<Button-3>", show_menu)
