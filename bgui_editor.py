
#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import os
import binascii
try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(1) # 1 = PROCESS_SYSTEM_DPI_AWARE
except Exception:
    pass

from bgui_core import BguiFile, BguiContainer, BguiHead, BguiNode

class BguiEditorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BGUI Editor v1.2")
        self.geometry("1400x800")
        
        self.bgui_file: BguiFile | None = None
        self.current_filepath: str | None = None
        self.selected_object: object | None = None # Can be BguiContainer, BguiHead, or "Register"
        
        self.original_raw_data: bytes = b""
        self.tree_map = {} # Maps item_id -> object
        
        self.setup_ui()
        
    def setup_ui(self):
        # Configure style for High DPI (increase row height)
        style = ttk.Style()
        style.configure("Treeview", rowheight=30) # Default is 20, 30 handles ~150% scaling nicely

        # Menu
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open...", command=self.on_open)
        file_menu.add_command(label="Save", command=self.on_save)
        file_menu.add_command(label="Save As...", command=self.on_save_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.quit)
        menubar.add_cascade(label="File", menu=file_menu)
        self.config(menu=menubar)
        
        # Panes
        panes = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True)
        
        # Left: File Hierarchy
        left_frame = ttk.Frame(panes, width=300)
        panes.add(left_frame, weight=1)
        
        ttk.Label(left_frame, text="File Hierarchy").pack(anchor="w")
        self.tree = ttk.Treeview(left_frame)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.heading("#0", text="Struct / Name / ID")
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        
        # Center: Property Editor
        center_frame = ttk.Frame(panes, width=400)
        panes.add(center_frame, weight=2)
        
        ttk.Label(center_frame, text="Properties").pack(anchor="w")
        
        self.prop_frame = ttk.LabelFrame(center_frame, text="Details")
        self.prop_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Helper for Dynamic Properties
        self.prop_widgets = {} # key -> widget
        self.prop_vars = {}    # key -> var
        
        btn_frame = ttk.Frame(center_frame)
        btn_frame.pack(fill=tk.X, padx=5)
        self.apply_btn = ttk.Button(btn_frame, text="Apply Changes", command=self.apply_changes)
        self.apply_btn.pack(side=tk.RIGHT)
        
        # Right: Hex View
        right_frame = ttk.Frame(panes, width=400)
        panes.add(right_frame, weight=2)
        
        ttk.Label(right_frame, text="Hex View").pack(anchor="w")
        
        # Hex Edit Controls
        hex_tools = ttk.Frame(right_frame)
        hex_tools.pack(fill=tk.X)
        self.edit_hex_var = tk.BooleanVar(value=False)
        self.edit_chk = ttk.Checkbutton(hex_tools, text="Enable Direct Edit", 
                                        variable=self.edit_hex_var, command=self.on_hex_edit_toggle)
        self.edit_chk.pack(side=tk.LEFT)
        self.commit_hex_btn = ttk.Button(hex_tools, text="Commit Hex Changes", 
                                         state="disabled", command=self.commit_hex_changes)
        self.commit_hex_btn.pack(side=tk.RIGHT)
        
        self.hex_text = tk.Text(right_frame, font=("Courier", 9), state="disabled", wrap="none")
        self.hex_text.pack(fill=tk.BOTH, expand=True)
        self.hex_text.tag_config("highlight", background="yellow", foreground="black")

    def clear_props(self):
        for w in self.prop_frame.winfo_children():
            w.destroy()
        self.prop_widgets = {}
        self.prop_vars = {}
        
    def add_prop_entry(self, label, key, init_val="", readonly=False, field_offset=-1, field_length=0):
        row = len(self.prop_widgets)
        ttk.Label(self.prop_frame, text=label).grid(row=row, column=0, sticky="e", padx=5, pady=2)
        v = tk.StringVar(value=str(init_val))
        self.prop_vars[key] = v
        e = ttk.Entry(self.prop_frame, textvariable=v)
        if readonly: e.config(state="readonly")
        e.grid(row=row, column=1, sticky="ew", padx=5, pady=2)
        self.prop_widgets[key] = e
        
        # Field-level hex highlighting on focus
        if field_offset >= 0 and field_length > 0:
            e.bind("<FocusIn>", lambda ev, off=field_offset, ln=field_length: self.highlight_hex(off, ln))
        
    def add_prop_text(self, label, key, hex_data: bytes, field_offset=-1, field_length=0):
        row = len(self.prop_widgets)
        ttk.Label(self.prop_frame, text=label).grid(row=row, column=0, sticky="ne", padx=5, pady=2)
        t = tk.Text(self.prop_frame, height=4, width=40)
        t.insert("1.0", hex_data.hex(' '))
        t.grid(row=row, column=1, sticky="ew", padx=5, pady=2)
        self.prop_widgets[key] = t
        
        # Field-level hex highlighting on focus
        if field_offset >= 0 and field_length > 0:
            t.bind("<FocusIn>", lambda ev, off=field_offset, ln=field_length: self.highlight_hex(off, ln))

    def on_open(self):
        f = filedialog.askopenfilename(filetypes=[("BGUI Files", "*.bgui")])
        if not f: return
        try:
            with open(f, "rb") as fo:
                data = fo.read()
            self.original_raw_data = data
            self.bgui_file = BguiFile.parse(data)
            self.current_filepath = f
            self.refresh_tree()
            self.refresh_hex_view()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def on_save(self):
        if not self.current_filepath:
            self.on_save_as()
            return
        self._write_file(self.current_filepath)

    def on_save_as(self):
        f = filedialog.asksaveasfilename(defaultextension=".bgui", filetypes=[("BGUI Files", "*.bgui")])
        if not f: return
        self._write_file(f)
        self.current_filepath = f

    def _write_file(self, path):
        try:
            data = self.bgui_file.serialize()
            with open(path, "wb") as f:
                f.write(data)
            self.original_raw_data = data
            self.refresh_hex_view()
        except Exception as e:
            messagebox.showerror("Save Error", str(e))

    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        self.tree_map = {}
        if not self.bgui_file: return
        
        # 1. Header Node
        head_id = self.tree.insert("", "end", text="[HEADER]", open=True)
        self.tree_map[head_id] = self.bgui_file.head
        
        # Add Header Values as child nodes for visibility
        h = self.bgui_file.head
        if h.sprite_present:
            self.tree.insert(head_id, "end", text=f"Sprite: {h.sprite_path}")
        else:
            self.tree.insert(head_id, "end", text="Sprite: (None)")
            
        self.tree.insert(head_id, "end", text=f"String: {h.container_str}")
        self.tree.insert(head_id, "end", text=f"Pages: {len(h.raw_page_data)} bytes")
        
        # 2. Virtual "Containers" Root
        cont_root_id = self.tree.insert("", "end", text="[CONTAINERS]", open=True)
        self.tree_map[cont_root_id] = "CONTAINERS_ROOT"
        
        # Build Container Tree
        roots = self.bgui_file.get_structure_tree()
        def add_node(parent_id, node: BguiNode):
            text = f"{node.container.name} (ID: {node.container.id})"
            item_id = self.tree.insert(parent_id, "end", text=text, open=True)
            self.tree_map[item_id] = node.container
            for child in node.children:
                add_node(item_id, child)
                
        for r in roots:
            add_node(cont_root_id, r)
            
        # 3. Register Node
        reg_id = self.tree.insert("", "end", text="[REGISTER]", open=True)
        self.tree_map[reg_id] = "REGISTER_Type"
        
        # Expand Register Entry nodes (Virtual view of Container data)
        if self.bgui_file:
            # Register starts at reg_offset + 14 (header)
            base_off = self.bgui_file.reg_offset + 14
            for idx, c in enumerate(self.bgui_file.containers):
                # We create a wrapper object or just use a dict to identify it
                # Let's use a tuple ("REG_ENTRY", container, index, offset)
                entry_offset = base_off + (idx * 8)
                entry_obj = ("REG_ENTRY", c, idx, entry_offset)
                
                text = f"Entry {idx}: ID={c.id}, Subs={c.subsection_count}"
                rid = self.tree.insert(reg_id, "end", text=text)
                self.tree_map[rid] = entry_obj

    def refresh_hex_view(self):
        self.hex_text.config(state="normal")
        self.hex_text.delete("1.0", tk.END)
        if not self.original_raw_data:
            self.hex_text.config(state="disabled")
            return
            
        lines = []
        data = self.original_raw_data
        bytes_per_line = 16
        
        for i in range(0, len(data), bytes_per_line):
            chunk = data[i:i+bytes_per_line]
            hex_part = " ".join(f"{b:02X}" for b in chunk)
            ascii_part = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
            hex_part = hex_part.ljust(bytes_per_line*3 - 1)
            lines.append(f"{i:08X} | {hex_part} | {ascii_part}")
            
        self.hex_text.insert("1.0", "\n".join(lines))
        self.hex_text.config(state="disabled")

    def highlight_hex(self, start_offset, length):
        if start_offset < 0 or length <= 0: return
        self.hex_text.tag_remove("highlight", "1.0", tk.END)
        
        bytes_per_line = 16
        
        # We must highlight strictly the bytes involved.
        # This requires iterating through the lines involved.
        
        current_off = start_offset
        remaining = length
        
        # Scroll to start
        start_line = (start_offset // bytes_per_line) + 1
        self.hex_text.see(f"{start_line}.0")
        
        while remaining > 0:
            line_idx = current_off // bytes_per_line
            row = line_idx + 1
            
            byte_in_line = current_off % bytes_per_line
            bytes_on_this_line = min(bytes_per_line - byte_in_line, remaining)
            
            # --- Hex Column Calculation ---
            # Offset (8) + " | " (3) = 11 chars.
            # Each byte is "XX " (3 chars).
            # Last byte in logical set might not have space if we just calculated math, 
            # but my generator uses " ".join(), so "XX XX XX".
            # Start Col = 11 + (byte_in_line * 3)
            # Length = (bytes_on_this_line * 3) - 1 (The last char has no trailing space relevant to highlight? 
            # Actually "XX " is 3 chars. "XX". 
            # Let's highlight the full triplet "XX " except for the very last byte of the LINE?
            # Or just highlight "XX". 
            # "XX XX" -> chars 0-1, 3-4.
            # Simpler to highlight the span.
            
            col_start = 11 + (byte_in_line * 3)
            col_end = col_start + (bytes_on_this_line * 3) - 1
            
            self.hex_text.tag_add("highlight", f"{row}.{col_start}", f"{row}.{col_end}")
            
            # --- ASCII Column Calculation ---
            # Hex part is padded to 47 chars.
            # " | " (3 chars).
            # Start = 11 + 47 + 3 = 61.
            ascii_start = 61 + byte_in_line
            ascii_end = ascii_start + bytes_on_this_line
            
            self.hex_text.tag_add("highlight", f"{row}.{ascii_start}", f"{row}.{ascii_end}")
            
            current_off += bytes_on_this_line
            remaining -= bytes_on_this_line

    def on_hex_edit_toggle(self):
        if self.edit_hex_var.get():
            warn = messagebox.askokcancel("Warning", "Direct Hex Editing is unstructured.\n"
                                          "You can easily corrupt the file structure.\n\n"
                                          "Are you sure you want to proceed?")
            if not warn:
                self.edit_hex_var.set(False)
                return
            
            self.hex_text.config(state="normal")
            self.commit_hex_btn.config(state="normal")
        else:
            # Revert or just lock?
            # Let's just lock. Changes are lost if not committed? No, text stays.
            self.hex_text.config(state="disabled")
            self.commit_hex_btn.config(state="disabled")

    def commit_hex_changes(self):
        # Parse text content back to bytes
        content = self.hex_text.get("1.0", tk.END)
        lines = content.splitlines()
        
        new_data = bytearray()
        try:
            for line in lines:
                if not line.strip(): continue
                # Format: 00000000 | AA BB ... | ....
                parts = line.split("|")
                if len(parts) < 2:
                    # Maybe user messed up format?
                    # Try to parse purely as hex string if no pipes?
                    # But we enforce pipes in display.
                    raise ValueError(f"Invalid line format: {line}")
                
                hex_part = parts[1].strip()
                # Remove spaces
                hex_part = hex_part.replace(" ", "")
                # Parse
                chunk = binascii.unhexlify(hex_part)
                new_data.extend(chunk)
                
            # Update file
            self.original_raw_data = bytes(new_data)
            # Re-parse structure
            self.bgui_file = BguiFile.parse(self.original_raw_data)
            self.refresh_tree()
            self.refresh_hex_view() # Re-format cleanly
            
            self.edit_hex_var.set(False)
            self.commit_hex_btn.config(state="disabled")
            messagebox.showinfo("Success", "Hex changes committed and file re-parsed.")
            
        except Exception as e:
            messagebox.showerror("Hex Parse Error", f"Failed to parse hex content:\n{e}")

    def on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel: return
        item_id = sel[0]
        obj = self.tree_map.get(item_id)
        
        self.selected_object = obj
        self.display_properties(obj)
        
        
        # Hex Zoom
        if isinstance(obj, BguiHead):
            self.highlight_hex(obj.file_offset, obj.byte_len)
        elif isinstance(obj, BguiContainer):
            self.highlight_hex(obj.file_offset, obj.byte_len)
        elif obj == "REGISTER_Type" and self.bgui_file:
            self.highlight_hex(self.bgui_file.reg_offset, self.bgui_file.reg_byte_len)
        elif obj == "CONTAINERS_ROOT" and self.bgui_file:
            # Highlight from end of Header to start of Register
            start = self.bgui_file.head.byte_len
            end = self.bgui_file.reg_offset
            if end == -1: end = len(self.original_raw_data)
            length = end - start
            self.highlight_hex(start, length)
        elif isinstance(obj, tuple) and obj[0] == "REG_ENTRY":
            # ("REG_ENTRY", c, idx, offset)
            self.highlight_hex(obj[3], 8) # 8 bytes: 4 ID, 4 SubCount

    def display_properties(self, obj):
        self.clear_props()
        if obj is None: return
        
        if isinstance(obj, BguiHead):
            self.add_prop_entry("Sprite Present:", "h_sprite", obj.sprite_present)
            self.add_prop_entry("Sprite Path:", "h_path", obj.sprite_path)
            self.add_prop_entry("Container String:", "h_cstr", obj.container_str)
            self.add_prop_entry("Raw Page Data (Hex):", "h_raw", obj.raw_page_data.hex(), readonly=True)
            self.apply_btn.config(state="normal")
            
        elif isinstance(obj, BguiContainer):
            # Use body_offset stored during parsing (not calculated)
            body_off = obj.body_offset
            
            # Field offsets relative to body: ID=+0, X=+4, Y=+8, Size=+12, Color=+16, UnkData=+20, etc.
            self.add_prop_entry("ID:", "id", obj.id, field_offset=body_off, field_length=4)
            
            # Name with length prefix (name_len is 1 byte before body - 4 for hash - len(name))
            name_len_off = body_off - 4 - len(obj.name)
            self.add_prop_entry("Name Length:", "name_len", len(obj.name), readonly=True,
                                field_offset=name_len_off, field_length=1)
            self.add_prop_entry("Name:", "name", obj.name, 
                                field_offset=name_len_off+1, field_length=len(obj.name))
            
            self.add_prop_entry("X Pos:", "x", obj.x, field_offset=body_off+4, field_length=4)
            self.add_prop_entry("Y Pos:", "y", obj.y, field_offset=body_off+8, field_length=4)
            self.add_prop_entry("Size:", "size", obj.size, field_offset=body_off+12, field_length=4)
            self.add_prop_entry("Color (Hex):", "color", f"{obj.color:08X}", 
                                field_offset=body_off+16, field_length=4)
            
            # Resource Block (Nested Structure)
            # Format: [4-byte block len][5-byte flags][1-byte inner len][string][padding]
            res_block_off = body_off + 64
            res_inner_len_off = res_block_off + 4 + 5  # After 4-byte len + 5-byte flags
            res_str_off = res_inner_len_off + 1
            
            self.add_prop_entry("Resource Block Len:", "res_block_len", 189, readonly=True,
                                field_offset=res_block_off, field_length=4)
            self.add_prop_entry("Resource Str Len:", "res_str_len", len(obj.res_string), readonly=True,
                                field_offset=res_inner_len_off, field_length=1)
            self.add_prop_entry("Resource:", "res_str", obj.res_string, 
                                field_offset=res_str_off, field_length=len(obj.res_string))
            
            self.add_prop_text("Unknown Data:", "unk_data", obj.unknown_data,
                               field_offset=body_off+20, field_length=44)
            self.apply_btn.config(state="normal")
            
        elif obj == "REGISTER_Type":
            # Just read-only stats
            count = len(self.bgui_file.containers) if self.bgui_file else 0
            self.add_prop_entry("Total Containers:", "reg_count", count, readonly=True)
            self.add_prop_entry("Offset:", "reg_off", f"{self.bgui_file.reg_offset:X}", readonly=True)
            self.apply_btn.config(state="disabled")
            
        elif obj == "CONTAINERS_ROOT":
            count = len(self.bgui_file.containers) if self.bgui_file else 0
            self.add_prop_entry("Total Containers:", "cont_count", count, readonly=True)
            if self.bgui_file:
                start = self.bgui_file.head.byte_len
                end = self.bgui_file.reg_offset
                if end == -1: end = len(self.original_raw_data)
                self.add_prop_entry("Section Size:", "cont_size", f"{end-start} bytes", readonly=True)
            self.apply_btn.config(state="disabled")

        elif isinstance(obj, tuple) and obj[0] == "REG_ENTRY":
            # ("REG_ENTRY", c, idx, offset)
            c = obj[1]
            self.add_prop_entry("Index:", "idx", obj[2], readonly=True)
            self.add_prop_entry("Container ID:", "reg_id", c.id)
            self.add_prop_entry("Subsections:", "reg_sub", c.subsection_count)
            self.apply_btn.config(state="normal")

    def apply_changes(self):
        obj = self.selected_object
        if not obj or obj == "REGISTER_Type" or obj == "CONTAINERS_ROOT": return
        
        try:
            if isinstance(obj, BguiHead):
                # Update Head
                s_pres = self.prop_vars["h_sprite"].get()
                obj.sprite_present = (s_pres.lower() == "true" or s_pres == "1")
                obj.sprite_path = self.prop_vars["h_path"].get()
                obj.container_str = self.prop_vars["h_cstr"].get()
                # Raw page data edit logic omitted for safety
                
            elif isinstance(obj, BguiContainer):
                # Update Container
                obj.id = int(self.prop_vars["id"].get())
                obj.name = self.prop_vars["name"].get()
                obj.x = float(self.prop_vars["x"].get())
                obj.y = float(self.prop_vars["y"].get())
                obj.size = float(self.prop_vars["size"].get())
                obj.color = int(self.prop_vars["color"].get(), 16)
                obj.res_string = self.prop_vars["res_str"].get()
                
                t_widget = self.prop_widgets["unk_data"]
                hex_data = t_widget.get("1.0", tk.END).strip().replace(" ", "")
                if len(hex_data) > 0:
                    obj.unknown_data = binascii.unhexlify(hex_data)
                    
            elif isinstance(obj, tuple) and obj[0] == "REG_ENTRY":
                # ("REG_ENTRY", c, idx, offset)
                c = obj[1]
                # Editing here updates the container
                new_id = int(self.prop_vars["reg_id"].get())
                new_sub = int(self.prop_vars["reg_sub"].get())
                c.id = new_id
                c.subsection_count = new_sub
            
            # Clear raw blocks to force rebuild on next serialize
            self.bgui_file.raw_container_block = b""
            self.bgui_file.raw_register_block = b""
            
            # Also clear container raw_bytes if we edited a container
            if isinstance(obj, BguiContainer):
                obj.raw_bytes = b""
            elif isinstance(obj, tuple) and obj[0] == "REG_ENTRY":
                obj[1].raw_bytes = b""
            
            # Re-serialize to get updated bytes
            self.original_raw_data = self.bgui_file.serialize()
            
            # Refresh views
            self.refresh_tree()
            self.refresh_hex_view()
            
            # Re-highlight current field if we have one selected
            # (Properties panel will be rebuilt on tree refresh)
            
        except Exception as e:
            messagebox.showerror("Error", f"Invalid data: {e}")

if __name__ == "__main__":
    app = BguiEditorApp()
    app.mainloop()
