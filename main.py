import tkinter as tk
from tkinter import ttk
import ttkbootstrap as tb
from PIL import Image, ImageTk
import camera_module as cam
import theme_module as tm
import json
import os

class MainApp(tb.Window):
    def __init__(self):
        super().__init__(themename="superhero")
        self.title("Check Ref - Tunitech")
        self.geometry("1100x850")
        
        self.running = True
        self.references = self.load_references()
        self.adding_new_ref = False
        self.pending_ref = None

        # Virtual Keyboard State
        self.keyboard_win = None
        self.current_kb_entry = None
        self._closing_keyboard = False

        self.setup_ui()
        
        self.camera = cam.CameraApp()
        self.start_camera()
        self.update_camera()

    def setup_ui(self):
        # ─── Header ───
        self.header = tb.Frame(self, bootstyle="light")
        self.header.pack(side="top", fill="x", padx=10, pady=5)
        
        try:
            logo_img = Image.open("logo.png")
            logo_img = logo_img.resize((150, 50), Image.Resampling.LANCZOS)
            self.logo_tk = ImageTk.PhotoImage(logo_img)
            self.logo_label = tb.Label(self.header, image=self.logo_tk)
            self.logo_label.pack(side="left", padx=10)
        except:
            tb.Label(self.header, text="TUNITECH", font=("Helvetica", 20, "bold")).pack(side="left", padx=10)
        
        self.theme_mb = tb.Menubutton(self.header, text="Themes", bootstyle="primary")
        self.theme_mb.pack(side="right", padx=10)
        self.theme_menu = tb.Menu(self.theme_mb)
        for theme in tm.get_available_themes():
            self.theme_menu.add_command(label=theme, command=lambda t=theme: self.change_theme(t))
        self.theme_mb["menu"] = self.theme_menu

        # DROPDOWN LIST (Auto-updates)
        self.ref_var = tk.StringVar()
        self.ref_combo = tb.Combobox(self.header, textvariable=self.ref_var,
                                     values=[r['name'] for r in self.references],
                                     state="readonly", width=25)
        self.ref_combo.pack(side="right", padx=10)
        self.ref_combo.bind("<<ComboboxSelected>>", self.on_ref_selected)

        # ─── Sidebar ───
        self.sidebar = tb.Frame(self, bootstyle="dark")
        self.sidebar.pack(side="left", fill="y", padx=5, pady=5)
        
        tb.Button(self.sidebar, text="⚙ Add Reference", bootstyle="success", command=self.open_settings).pack(pady=10, padx=10, fill="x")
        tb.Button(self.sidebar, text="📁 Archive", bootstyle="primary", command=self.open_archive).pack(pady=10, padx=10, fill="x")
        tb.Button(self.sidebar, text="Clear Zone", bootstyle="warning", command=self.clear_zone).pack(pady=10, padx=10, fill="x")

        # ─── Main Content ───
        self.main_content = tb.Frame(self)
        self.main_content.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        
        self.result_label = tb.Label(self.main_content, text="Ready", font=("Helvetica", 14), bootstyle="info")
        self.result_label.pack(side="bottom", pady=10)

        self.camera_frame = tb.Labelframe(self.main_content, text="Live Feed")
        self.camera_frame.pack(fill="both", expand=True)
        self.camera_label = tb.Label(self.camera_frame)
        self.camera_label.pack(fill="both", expand=True)
        
        self.camera_label.bind("<Button-1>", self.on_mouse_down)
        self.camera_label.bind("<B1-Motion>", self.on_mouse_drag)
        self.camera_label.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.rect_start = None

    # ─── Virtual Keyboard (Pi Optimized) ───
    def show_virtual_keyboard(self, entry, next_widget=None):
        if self._closing_keyboard: return
        self.current_kb_entry = entry
        
        if not self.keyboard_win or not self.keyboard_win.winfo_exists():
            self.keyboard_win = tb.Toplevel(self)
            self.keyboard_win.title("Keyboard")
            self.keyboard_win.geometry("700x350+200+400")
            self.keyboard_win.attributes("-topmost", True)
            self.keyboard_win.protocol("WM_DELETE_WINDOW", self._close_keyboard)
        
        self._refresh_kb_layout(next_widget)
        self.keyboard_win.deiconify()
        self.keyboard_win.lift()
        self.keyboard_win.focus_force()
        self.keyboard_win.update()

    def _refresh_kb_layout(self, next_widget):
        for w in self.keyboard_win.winfo_children(): w.destroy()
        kb_frame = tb.Frame(self.keyboard_win, padding=10)
        kb_frame.pack(fill="both", expand=True)

        rows = ["1234567890", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"]
        for r_chars in rows:
            row_frame = tb.Frame(kb_frame)
            row_frame.pack(pady=2)
            for char in r_chars:
                btn = tb.Button(row_frame, text=char, width=4, bootstyle="outline",
                               takefocus=False, command=lambda c=char: self._kb_insert_char(c))
                btn.pack(side="left", padx=2, ipady=12)

        ctrl_row = tb.Frame(kb_frame)
        ctrl_row.pack(pady=10, fill="x")

        tb.Button(ctrl_row, text="⌫", width=6, bootstyle="danger", takefocus=False,
                  command=self._kb_backspace).pack(side="left", padx=2)
        
        tb.Button(ctrl_row, text="SPACE", bootstyle="secondary", takefocus=False,
                  command=lambda: self._kb_insert_char(" ")).pack(side="left", expand=True, fill="x", padx=5)
        
        done_text = "NEXT" if next_widget else "DONE"
        done_cmd = (lambda: self._move_to_next(next_widget)) if next_widget else self._close_keyboard
        
        tb.Button(ctrl_row, text=done_text, width=8, bootstyle="success", takefocus=False,
                  command=done_cmd).pack(side="right", padx=2)

    def _kb_insert_char(self, char):
        if self.current_kb_entry:
            self.current_kb_entry.insert(tk.INSERT, char)
            self.current_kb_entry.focus_set()

    def _kb_backspace(self):
        if self.current_kb_entry:
            pos = self.current_kb_entry.index(tk.INSERT)
            if pos > 0: self.current_kb_entry.delete(pos - 1, pos)

    def _move_to_next(self, next_widget):
        next_widget.focus_set()
        self.show_virtual_keyboard(next_widget)

    def _close_keyboard(self):
        self._closing_keyboard = True
        if self.keyboard_win:
            self.keyboard_win.destroy()
            self.keyboard_win = None
        self.after(300, lambda: setattr(self, "_closing_keyboard", False))

    # ─── Logic: Add Reference & Success Message ───
    def open_settings(self):
        win = tb.Toplevel(self)
        win.title("Reference Setup")
        win.geometry("500x380")
        win.attributes("-topmost", True)
        
        container = tb.Frame(win, padding=20)
        container.pack(fill="both", expand=True)

        tb.Label(container, text="Reference Name:").pack(anchor="w")
        e1 = tb.Entry(container)
        e1.pack(fill="x", pady=5)

        tb.Label(container, text="Expected Text:").pack(anchor="w", pady=(10,0))
        e2 = tb.Entry(container)
        e2.pack(fill="x", pady=5)

        # Trigger on both Click (Touch) and Focus
        e1.bind("<Button-1>", lambda e: self.show_virtual_keyboard(e1, e2))
        e1.bind("<FocusIn>", lambda e: self.show_virtual_keyboard(e1, e2))
        e2.bind("<Button-1>", lambda e: self.show_virtual_keyboard(e2, None))
        e2.bind("<FocusIn>", lambda e: self.show_virtual_keyboard(e2, None))

        def confirm():
            if e1.get() and e2.get():
                self.pending_ref = {"name": e1.get(), "expected_text": e2.get(), "roi": None}
                self.adding_new_ref = True
                win.destroy()
                self._close_keyboard()
                self.result_label.configure(text=f"Please draw the ROI for: {e1.get()}", bootstyle="warning")
            else:
                tb.dialogs.Messagebox.show_error("All fields are required!", parent=win)

        tb.Button(container, text="CONTINUE TO ROI", bootstyle="success", command=confirm).pack(pady=20, fill="x")

    def on_mouse_up(self, event):
        if not self.rect_start: return
        x1, y1 = self.rect_start
        scale = 1 / self.camera.display_scale
        rx, ry = int(min(x1, event.x) * scale), int(min(y1, event.y) * scale)
        rw, rh = int(abs(event.x - x1) * scale), int(abs(event.y - y1) * scale)

        if self.adding_new_ref and self.pending_ref:
            self.pending_ref["roi"] = (rx, ry, rw, rh)
            self.references.append(self.pending_ref)
            self.save_references()
            
            # REFRESH DROPDOWN
            self.update_ref_combo()
            
            self.camera.clear_roi()
            # SUCCESS MESSAGE
            tb.dialogs.Messagebox.show_info("Success", f"Reference '{self.pending_ref['name']}' saved!", parent=self)
            self.result_label.configure(text="Reference Saved Successfully", bootstyle="success")
            self.adding_new_ref = False
        else:
            self.camera.set_roi(rx, ry, rw, rh)
        self.rect_start = None

    # ─── Archive: Delete All Functionality ───
    def open_archive(self):
        pwd_win = tb.Toplevel(self)
        pwd_win.title("Security")
        pwd_win.geometry("300x200")
        tb.Label(pwd_win, text="Password:").pack(pady=10)
        p_entry = tb.Entry(pwd_win, show="*")
        p_entry.pack(pady=5, padx=20, fill="x")
        
        p_entry.bind("<Button-1>", lambda e: self.show_virtual_keyboard(p_entry))
        p_entry.bind("<FocusIn>", lambda e: self.show_virtual_keyboard(p_entry))

        def check():
            if p_entry.get() == "TUNITECH":
                pwd_win.destroy()
                self._close_keyboard()
                self.show_archive_manager()
        tb.Button(pwd_win, text="Login", command=check).pack(pady=10)

    def show_archive_manager(self):
        win = tb.Toplevel(self)
        win.title("Archive")
        win.geometry("800x600")
        cols = ("name", "text")
        tree = tb.Treeview(win, columns=cols, show="headings")
        tree.heading("name", text="Name"); tree.heading("text", text="Text")
        tree.pack(fill="both", expand=True, padx=10, pady=10)

        def refresh_tree():
            for i in tree.get_children(): tree.delete(i)
            for r in self.references: tree.insert("", "end", values=(r["name"], r["expected_text"]))
        refresh_tree()

        btn_frame = tb.Frame(win)
        btn_frame.pack(fill="x", pady=10)
        
        def delete_all():
            if tb.dialogs.Messagebox.yesno("Delete all references?", "Confirm", parent=win):
                self.references = []
                self.save_references()
                self.update_ref_combo() # UPDATE DROPDOWN
                refresh_tree()

        def delete_selected():
            sel = tree.selection()
            if not sel: return
            for item in sel:
                name = tree.item(item)["values"][0]
                self.references = [r for r in self.references if r["name"] != name]
            self.save_references()
            self.update_ref_combo() # UPDATE DROPDOWN
            refresh_tree()

        tb.Button(btn_frame, text="🗑 Delete Selected", bootstyle="danger-outline", command=delete_selected).pack(side="left", padx=10, expand=True, fill="x")
        tb.Button(btn_frame, text="🔥 DELETE ALL", bootstyle="danger", command=delete_all).pack(side="left", padx=10, expand=True, fill="x")

    # ─── System / Data Helpers ───
    def load_references(self):
        if os.path.exists("references.json"):
            with open("references.json", "r") as f: return json.load(f)
        return []

    def save_references(self):
        with open("references.json", "w") as f: json.dump(self.references, f, indent=4)

    def update_ref_combo(self):
        self.ref_combo['values'] = [r['name'] for r in self.references]

    def on_ref_selected(self, event):
        for r in self.references:
            if r["name"] == self.ref_var.get():
                self.camera.set_roi(*r["roi"])
                self.camera.expected_text = r["expected_text"]

    def start_camera(self): self.camera.start_camera(0)
    def update_camera(self):
        if self.running and self.camera.is_running:
            img = self.camera.get_frame()
            if img: self.camera_label.configure(image=img); self.camera_label.image = img
        self.after(30, self.update_camera)

    def on_mouse_down(self, event): self.rect_start = (event.x, event.y)
    def on_mouse_drag(self, event):
        if self.rect_start:
            x1, y1 = self.rect_start
            self.camera.set_roi_temp(x1, y1, event.x - x1, event.y - y1)
    
    def change_theme(self, name): tm.set_theme(self, name)
    def clear_zone(self): self.camera.clear_roi()

# ─── THE MAIN FUNCTION ───
if __name__ == "__main__":
    app = MainApp()
    app.mainloop()