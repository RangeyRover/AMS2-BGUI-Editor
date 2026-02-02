"""
BGUI Register Viewer - GUI Module
Uses bgui_parser for core logic.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import ctypes
from typing import Optional

from bgui_parser import BguiRegisterParser, TreeNode, RegisterEntry, ContainerInfo


# Windows DPI Awareness
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass


class RegisterViewer(tk.Tk):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        
        self.title("BGUI Register Viewer")
        self.geometry("1200x700")
        self.minsize(900, 500)
        
        self.parser: Optional[BguiRegisterParser] = None
        self.tree_nodes: dict = {}  # tree_id -> TreeNode
        
        self._create_menu()
        self._create_ui()
        self._create_statusbar()
    
    def _create_menu(self):
        """Create menu bar."""
        menubar = tk.Menu(self)
        
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open...", command=self._open_file, accelerator="Ctrl+O")
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.quit)
        menubar.add_cascade(label="File", menu=file_menu)
        
        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Copy Tree", command=self._copy_tree_to_clipboard, accelerator="Ctrl+C")
        edit_menu.add_command(label="Copy Raw Entries", command=self._copy_raw_entries)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        
        self.config(menu=menubar)
        self.bind('<Control-o>', lambda e: self._open_file())
        # self.bind('<Control-c>', lambda e: self._copy_tree_to_clipboard())  <-- Moved to Tree widget
    
    def _create_ui(self):
        """Create three-pane layout."""
        self.main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.main_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self._create_tree_pane()
        self._create_properties_pane()
        self._create_hex_pane()
    
    def _create_tree_pane(self):
        """Create tree view pane."""
        tree_frame = ttk.LabelFrame(self.main_pane, text="Container Hierarchy", padding=5)
        self.main_pane.add(tree_frame, weight=1)
        
        tree_scroll = ttk.Scrollbar(tree_frame)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Toolbar
        toolbar = ttk.Frame(tree_frame)
        toolbar.pack(side=tk.TOP, fill=tk.X, pady=(0, 5))
        
        ttk.Button(toolbar, text="Expand All", command=self._expand_all).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Collapse All", command=self._collapse_all).pack(side=tk.LEFT, padx=5)
        
        # Increase row height to prevent clipping
        style = ttk.Style()
        style.configure("Treeview", rowheight=24)
        
        self.tree = ttk.Treeview(tree_frame, yscrollcommand=tree_scroll.set, 
                                  columns=('id', 'children'), displaycolumns=('children',))
        self.tree.pack(fill=tk.BOTH, expand=True)
        tree_scroll.config(command=self.tree.yview)
        
        self.tree.heading('#0', text='Container')
        self.tree.heading('children', text='Children')
        self.tree.column('#0', width=180)
        self.tree.column('children', width=60, anchor='center')
        
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)
        # Bind Copy only to tree widget so it doesn't steal focus from Entry/Text
        self.tree.bind('<Control-c>', lambda e: self._copy_tree_to_clipboard())
    
    def _create_properties_pane(self):
        """Create properties panel with clickable fields."""
        props_frame = ttk.LabelFrame(self.main_pane, text="Properties", padding=10)
        self.main_pane.add(props_frame, weight=1)
        
        # Add scrollable frame for properties
        canvas = tk.Canvas(props_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(props_frame, orient="vertical", command=canvas.yview)
        self.props_inner = ttk.Frame(canvas)
        
        self.props_inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.props_inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Store vars, entries, and offset info for each field
        self.prop_vars = {}        # key -> StringVar (value)
        self.prop_entries = {}     # key -> Entry widget
        self.prop_offsets = {}     # key -> (offset, size) tuple
        self.prop_offset_vars = {} # key -> StringVar (offset text)
        
        fields = [
            ('Container ID', 'id'),
            ('Child Count', 'children'),
            ('Register Index', 'index'),
            ('Register Offset', 'reg_offset'),
            ('---', 'sep1'),
            ('Name Length', 'name_len'),
            ('Name', 'name'),
            ('Marker Offset', 'marker_offset'),
            ('---', 'sep2'),
            ('X', 'x'),
            ('Y', 'y'),
            ('Size', 'size'),
            ('Color', 'color'),
            ('Resource Length', 'res_len'),
            ('Resource', 'resource'),
            ('---', 'sep3'),
            ('Sprite Path', 'sprite_path'),
            ('Manifest Count', 'manifest_count'),
            ('Manifest Keys', 'manifest_keys'),
        ]
        
        # Add Copy Button at the top
        copy_btn = ttk.Button(self.props_inner, text="Copy All Properties", command=self._copy_properties)
        copy_btn.grid(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 10))
        
        # Add Headers
        ttk.Label(self.props_inner, text="Offset (Hex)", font=('Consolas', 9, 'bold')).grid(row=1, column=0, sticky='w', pady=(0,5))
        ttk.Label(self.props_inner, text="Property", font=('Segoe UI', 9, 'bold')).grid(row=1, column=1, sticky='w', pady=(0,5))
        ttk.Label(self.props_inner, text="Value", font=('Segoe UI', 9, 'bold')).grid(row=1, column=2, sticky='w', pady=(0,5))
        
        for i, (label, key) in enumerate(fields):
            row_idx = i + 2  # Shift down by 2 (button + header)
            
            if label == '---':
                ttk.Separator(self.props_inner, orient='horizontal').grid(row=row_idx, column=0, columnspan=3, sticky='ew', pady=5)
                continue
            
            # Column 0: Offset
            off_var = tk.StringVar(value="-")
            self.prop_offset_vars[key] = off_var
            off_lbl = ttk.Label(self.props_inner, textvariable=off_var, font=('Consolas', 9), width=10)
            off_lbl.grid(row=row_idx, column=0, sticky='w', padx=(0, 10))
            
            # Column 1: Label
            ttk.Label(self.props_inner, text=label + ":").grid(row=row_idx, column=1, sticky='w', pady=2)
            
            # Column 2: Value
            var = tk.StringVar(value="-")
            self.prop_vars[key] = var
            width = 50 if key in ('resource', 'name') else 30
            entry = ttk.Entry(self.props_inner, textvariable=var, state='readonly', width=width)
            entry.grid(row=row_idx, column=2, sticky='w', padx=(10, 0), pady=2)
            self.prop_entries[key] = entry
            self.prop_offsets[key] = None
            
            # Bind click to highlight
            entry.bind('<Button-1>', lambda e, k=key: self._on_property_click(k))
        
        self.props_inner.columnconfigure(2, weight=1)
    
    def _on_property_click(self, key: str):
        """Handle click on property field - highlight its bytes in hex."""
        offset_info = self.prop_offsets.get(key)
        if offset_info:
            offset, size = offset_info
            self._highlight_range(offset, offset + size)
    
    def _create_hex_pane(self):
        """Create hex viewer pane."""
        hex_frame = ttk.LabelFrame(self.main_pane, text="Register Hex View", padding=5)
        self.main_pane.add(hex_frame, weight=2)
        
        hex_scroll = ttk.Scrollbar(hex_frame)
        hex_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.hex_text = tk.Text(hex_frame, font=('Consolas', 10), wrap=tk.NONE,
                                 yscrollcommand=hex_scroll.set, state='disabled',
                                 bg='#1e1e1e', fg='#d4d4d4', insertbackground='white')
        self.hex_text.pack(fill=tk.BOTH, expand=True)
        hex_scroll.config(command=self.hex_text.yview)
        
        self.hex_text.tag_configure('highlight', background='#264f78', foreground='white')
        self.hex_text.tag_configure('offset', foreground='#569cd6')
        self.hex_text.tag_configure('ascii', foreground='#6a9955')
    
    def _create_statusbar(self):
        """Create status bar."""
        self.statusbar = ttk.Label(self, text="No file loaded", relief=tk.SUNKEN, anchor='w')
        self.statusbar.pack(side=tk.BOTTOM, fill=tk.X)
    
    def _open_file(self):
        """Open file dialog and load BGUI file."""
        filepath = filedialog.askopenfilename(
            title="Open BGUI File",
            filetypes=[("BGUI Files", "*.bgui"), ("All Files", "*.*")]
        )
        
        if not filepath:
            return
        
        self._load_file(filepath)
    
    def _load_file(self, filepath: str):
        """Load and parse a BGUI file."""
        print(f"UI: load_file called for {filepath}")
        self.parser = BguiRegisterParser.from_file(filepath)
        
        print("UI: Calling parser.load()...")
        if not self.parser.load():
            messagebox.showerror("Error", "Failed to parse file. Could not locate register section.")
            return
        
        if not self.parser.is_standard_magic():
            messagebox.showwarning("Warning", 
                f"Non-standard magic header detected: {self.parser.magic.hex()}\n"
                "File may not parse correctly.")
        
        # Scan for containers is now handled inside load()
        # print("UI: Calling scan_containers()...")
        # self.parser.scan_containers()
        
        print("UI: Calling _populate_tree()...")
        self._populate_tree()
        print("UI: Calling _populate_hex()...")
        self._populate_hex()
        print("UI: Updating status...")
        self._update_status(filepath)
        print("UI: File load complete.")
    
    def _populate_tree(self):
        """Populate tree view with Containers and Register sections."""
        print("UI: _populate_tree started")
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.tree_nodes.clear()
        
        print("UI: building tree...")
        root = self.parser.build_tree()
        
        # === Header Section ===
        header_root = self.tree.insert('', 'end', text="📁 Header / Manifest", values=('', ''), open=True)
        self.tree_nodes[header_root] = ('header', self.parser.header_info)
        
        # Add Manifest Strings as children
        if self.parser.header_info.manifest_strings:
            manifest_root = self.tree.insert(header_root, 'end', text=f"Manifest ({len(self.parser.header_info.manifest_strings)})", values=('', ''))
            self.tree_nodes[manifest_root] = ('manifest_root', None)
            
            for i, (s_val, offset) in enumerate(self.parser.header_info.manifest_strings):
                node_text = f"[{i}] {s_val}"
                child_id = self.tree.insert(manifest_root, 'end', text=node_text, values=('', ''))
                self.tree_nodes[child_id] = ('manifest_entry', (s_val, offset))
        
        # === Containers Section (first in file) ===
        print(f"UI: Adding {len(self.parser.containers)} containers to tree...")
        container_root = self.tree.insert('', 'end', text=f"📁 Containers ({len(self.parser.containers)} found)",
                                           values=('', ''), open=True)
        
        def add_container_node(parent_id: str, node: TreeNode):
            if node.entry:
                container = self.parser.get_container_by_id(node.entry.container_id)
                if container:
                    text = f"{container.name} (ID:{container.container_id})"
                else:
                    text = f"[No Container] (ID:{node.entry.container_id})"
                tree_id = self.tree.insert(parent_id, 'end', text=text,
                                            values=(node.entry.container_id, node.entry.child_count))
                # Store with type marker - include both container and node
                self.tree_nodes[tree_id] = ('container', (container, node))
            else:
                tree_id = parent_id
            
            for child in node.children:
                add_container_node(tree_id, child)
        
        add_container_node(container_root, root)
        
        # Expand first level
        for child in self.tree.get_children(container_root):
            self.tree.item(child, open=True)
        
        # === Register Section (at end of file) ===
        print(f"UI: Adding {len(self.parser.entries)} register entries to tree...")
        register_root = self.tree.insert('', 'end', text=f"📁 Register ({len(self.parser.entries)} entries)",
                                          values=('', ''), open=True)
        
        def add_register_node(parent_id: str, node: TreeNode):
            if node.entry:
                # Look up container for name
                container = self.parser.get_container_by_id(node.entry.container_id)
                if container:
                    text = f"{container.name} (ID:{node.entry.container_id})"
                else:
                    text = f"ID:{node.entry.container_id} (children:{node.entry.child_count})"
                
                # Check if it has children for display?
                if node.entry.child_count > 0:
                     text += f" [{node.entry.child_count}]"

                tree_id = self.tree.insert(parent_id, 'end', text=text,
                                            values=(node.entry.container_id, node.entry.child_count))
                # Store with type marker
                self.tree_nodes[tree_id] = ('register', node)
            else:
                tree_id = parent_id
            
            for child in node.children:
                add_register_node(tree_id, child)
        
        add_register_node(register_root, root)
        
        # Expand first level
        for child in self.tree.get_children(register_root):
            self.tree.item(child, open=True)
        print("UI: Tree population done.")
    
    def _populate_hex(self):
        """Populate hex view with entire file."""
        print("UI: _populate_hex started")
        self.hex_text.config(state='normal')
        self.hex_text.delete('1.0', tk.END)
        
        if not self.parser:
            self.hex_text.config(state='disabled')
            return
        
        file_bytes = self.parser.data
        bytes_per_line = 16
        
        count = 0
        for i in range(0, len(file_bytes), bytes_per_line):
            count += 1
            if count % 200 == 0:
                print(f"UI: Hex view line {count}...")
                self.update() # Prevent UI freeze
                
            line_bytes = file_bytes[i:i + bytes_per_line]
            
            offset_str = f"{i:08X}  "
            self.hex_text.insert(tk.END, offset_str, 'offset')
            
            hex_parts = []
            for j, b in enumerate(line_bytes):
                hex_parts.append(f"{b:02X}")
                if j == 7:
                    hex_parts.append(" ")
            hex_str = " ".join(hex_parts)
            hex_str = hex_str.ljust(49)
            self.hex_text.insert(tk.END, hex_str)
            
            ascii_str = "  "
            for b in line_bytes:
                if 32 <= b < 127:
                    ascii_str += chr(b)
                else:
                    ascii_str += '.'
            self.hex_text.insert(tk.END, ascii_str + '\n', 'ascii')
        
        print("UI: Hex view finished.")
        self.hex_text.config(state='disabled')
    
    def _on_tree_select(self, event):
        """Handle tree selection."""
        selection = self.tree.selection()
        if not selection:
            return
        
        tree_id = selection[0]
        node_data = self.tree_nodes.get(tree_id)
        
        if not node_data:
            # Section header selected
            self._clear_properties()
            return
        
        node_type, data = node_data
        
        if node_type == 'register':
            # Register node - data is TreeNode
            node = data
            entry = node.entry
            
            # Set register properties with offsets
            self._set_register_properties(entry)
            
            # Look up matching container
            container = self.parser.get_container_by_id(entry.container_id)
            self._set_container_properties(container)
            
            # Scroll to register entry in file (8 bytes per entry)
            self._highlight_range(entry.file_offset, entry.file_offset + 8)
            
        elif node_type == 'container':
            # Container node - data is (ContainerInfo, TreeNode) tuple
            container, node = data
            entry = node.entry
            
            # Set register properties with offsets
            self._set_register_properties(entry)
            
            # Container properties
            self._set_container_properties(container)
            
            # Highlight this node and all its descendants
            start_offset, end_offset = self.parser.get_node_byte_range(node)
            self._highlight_range(start_offset, end_offset)
            
        elif node_type == 'header':
            self._clear_properties()
            header = data
            self.prop_vars['sprite_path'].set(header.sprite_path)
            self.prop_vars['name'].set(header.project_name or "Project")
            
            total = len(header.manifest_strings)
            self.prop_vars['manifest_count'].set(str(total))
            
            # Show first few keys
            display_keys = ", ".join([s for s, o in header.manifest_strings[:10]])
            if total > 10:
                display_keys += "..."
            self.prop_vars['manifest_keys'].set(display_keys)
            
        elif node_type == 'manifest_root':
            self._clear_properties()
            
        elif node_type == 'manifest_entry':
            self._clear_properties()
            s_val, offset = data
            
            # Reuse Name/Length fields for this string
            slen = len(s_val)
            self.prop_vars['name'].set(s_val)
            self.prop_vars['name_len'].set(str(slen))
            
            # Linking
            # Offset points to Length Byte. String starts +1
            self.prop_offsets['name_len'] = (offset, 1)
            self.prop_offset_vars['name_len'].set(f"{offset:08X}")
            
            self.prop_offsets['name'] = (offset + 1, slen)
            self.prop_offset_vars['name'].set(f"{offset+1:08X}")
            
            # Highlight total entry (Len + String)
            self._highlight_range(offset, offset + 1 + slen)

    def _set_register_properties(self, entry: RegisterEntry):
        """Set register-related properties with clickable offsets."""
        self.prop_vars['id'].set(str(entry.container_id))
        self.prop_vars['children'].set(str(entry.child_count))
        self.prop_vars['index'].set(str(entry.index))
        self.prop_vars['reg_offset'].set(f"0x{entry.file_offset:X}")
        
        # Store offsets and update offset labels
        self.prop_offsets['id'] = (entry.file_offset, 4)
        self.prop_offset_vars['id'].set(f"{entry.file_offset:08X}")
        
        self.prop_offsets['children'] = (entry.file_offset + 4, 4)
        self.prop_offset_vars['children'].set(f"{entry.file_offset + 4:08X}")
        
        self.prop_offsets['index'] = None
        self.prop_offset_vars['index'].set("-")
        
        self.prop_offsets['reg_offset'] = (entry.file_offset, 8)
        self.prop_offset_vars['reg_offset'].set(f"{entry.file_offset:08X}")
    
    def _set_container_properties(self, container):
        """Set container-related properties with clickable offsets."""
        if container:
            # ID
            self.prop_offsets['id'] = (container.body_offset, 4)
            self.prop_offset_vars['id'].set(f"{container.body_offset:08X}")
            
            # Name Length
            self.prop_vars['name_len'].set(str(container.name_length))
            self.prop_offsets['name_len'] = (container.marker_offset + 4, 1)
            self.prop_offset_vars['name_len'].set(f"{container.marker_offset + 4:08X}")

            # Name
            self.prop_vars['name'].set(container.name)
            name_offset = container.marker_offset + 5
            self.prop_offsets['name'] = (name_offset, container.name_length)
            self.prop_offset_vars['name'].set(f"{name_offset:08X}")
            
            # Marker info
            self.prop_vars['marker_offset'].set(f"0x{container.marker_offset:X}")
            self.prop_offsets['marker_offset'] = (container.marker_offset, 4)
            self.prop_offset_vars['marker_offset'].set(f"{container.marker_offset:08X}")
            
            # Body fields
            body = container.body_offset
            
            self.prop_vars['x'].set(f"{container.x:.2f}")
            self.prop_offsets['x'] = (body + 4, 4)
            self.prop_offset_vars['x'].set(f"{body + 4:08X}")
            
            self.prop_vars['y'].set(f"{container.y:.2f}")
            self.prop_offsets['y'] = (body + 8, 4)
            self.prop_offset_vars['y'].set(f"{body + 8:08X}")
            
            self.prop_vars['size'].set(f"{container.size:.2f}")
            self.prop_offsets['size'] = (body + 12, 4)
            self.prop_offset_vars['size'].set(f"{body + 12:08X}")
            
            self.prop_vars['color'].set(f"#{(container.color & 0xFFFFFF):06X}")
            if container.color_offset > 0:
                self.prop_offsets['color'] = (container.color_offset, 3)
                self.prop_offset_vars['color'].set(f"{container.color_offset:08X}")
            else:
                self.prop_offsets['color'] = None
                self.prop_offset_vars['color'].set("-")
            
            # Resource
            if container.resource:
                res_len = len(container.resource)
                self.prop_vars['res_len'].set(str(res_len))
                self.prop_vars['resource'].set(container.resource)
                
                # Length byte is immediately before the string start
                len_off = container.resource_offset - 1
                self.prop_offsets['res_len'] = (len_off, 1)
                self.prop_offset_vars['res_len'].set(f"{len_off:08X}")
                
                self.prop_offsets['resource'] = (container.resource_offset, res_len)
                self.prop_offset_vars['resource'].set(f"{container.resource_offset:08X}")
            else:
                self.prop_vars['res_len'].set("-")
                self.prop_vars['resource'].set("-")
                self.prop_offsets['res_len'] = None
                self.prop_offsets['resource'] = None
                self.prop_offset_vars['res_len'].set("-")
                self.prop_offset_vars['resource'].set("-")
        else:
            for key in ['name', 'marker_offset', 'x', 'y', 'size', 'color', 'resource']:
                self.prop_vars[key].set("-")
                self.prop_offsets[key] = None
                self.prop_offset_vars[key].set("-")
        
        # Clear header specific
        self.prop_vars['sprite_path'].set("-")
        self.prop_vars['manifest_count'].set("-")
        self.prop_vars['manifest_keys'].set("-")
    
    def _clear_properties(self):
        """Clear all properties."""
        for var in self.prop_vars.values():
            var.set("-")
        for var in self.prop_offset_vars.values():
            var.set("-")
    
    def _highlight_range(self, start_offset: int, end_offset: int):
        """Highlight a byte range in hex view and scroll to it."""
        self.hex_text.tag_remove('highlight', '1.0', tk.END)
        
        if not self.parser or start_offset < 0:
            return
        
        # Clamp offsets
        file_size = len(self.parser.data)
        start_offset = max(0, min(start_offset, file_size - 1))
        end_offset = max(start_offset + 1, min(end_offset, file_size))
        
        # Calculate line ranges
        start_line = start_offset // 16 + 1
        end_line = (end_offset - 1) // 16 + 1
        
        # For each line in the range, highlight the hex portion
        for line_num in range(start_line, end_line + 1):
            line_start_byte = (line_num - 1) * 16
            line_end_byte = line_num * 16
            
            # Determine which bytes on this line to highlight
            highlight_start = max(start_offset, line_start_byte) % 16
            highlight_end = min(end_offset, line_end_byte) - line_start_byte
            if highlight_end <= 0:
                continue
            
            # Calculate character positions (10 chars for offset, 3 chars per byte)
            hex_start_col = 10 + highlight_start * 3
            if highlight_start >= 8:
                hex_start_col += 1
            
            hex_end_col = 10 + highlight_end * 3 - 1
            if highlight_end > 8:
                hex_end_col += 1
            
            start_pos = f"{line_num}.{hex_start_col}"
            end_pos = f"{line_num}.{hex_end_col}"
            
            self.hex_text.tag_add('highlight', start_pos, end_pos)
        
        # Scroll to start
        self.hex_text.see(f"{start_line}.0")
    
    def _update_status(self, filepath: str = ""):
        """Update status bar."""
        if self.parser:
            filename = filepath.split('/')[-1].split('\\')[-1] if filepath else "Unknown"
            entry_count = len(self.parser.entries)
            file_size = len(self.parser.data)
            reg_size = self.parser.register_end - self.parser.register_start
            
            status = (f"{filename} | Register: {entry_count} entries | "
                     f"Register size: {reg_size} bytes | File size: {file_size:,} bytes")
            self.statusbar.config(text=status)
    
    def _copy_properties(self):
        """Copy all current properties to clipboard."""
        lines = []
        # Define field order to match UI
        fields = [
            'Container ID', 'id',
            'Child Count', 'children',
            'Register Index', 'index',
            'Register Offset', 'reg_offset',
            '-----------------', None,
            'Name Length', 'name_len',
            'Name', 'name',
            'Marker Offset', 'marker_offset',
            '-----------------', None,
            'X', 'x',
            'Y', 'y',
            'Size', 'size',
            'Color', 'color',
            'Resource Length', 'res_len',
            'Resource', 'resource',
            '-----------------', None,
            'Sprite Path', 'sprite_path',
            'Manifest Count', 'manifest_count',
            'Manifest Keys', 'manifest_keys'
        ]
        
        for i in range(0, len(fields), 2):
            label = fields[i]
            key = fields[i+1]
            
            if key is None:
                lines.append(label)
                continue
            
            val = self.prop_vars.get(key)
            offset_var = self.prop_offset_vars.get(key)
            
            if val:
                val_str = val.get()
                off_str = "-"
                
                if offset_var:
                    off_val = offset_var.get()
                    if off_val and off_val != "-":
                        off_str = f"0x{off_val}"
                
                # Align nicely: [Offset] Label: Value
                if off_str != "-":
                    lines.append(f"[{off_str:<10}] {label}: {val_str}")
                else:
                    lines.append(f"{' ': <12} {label}: {val_str}")
        
        text = "\n".join(lines)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.statusbar.config(text="Properties (with offsets) copied to clipboard!")

    def _copy_tree_to_clipboard(self):
        """Copy tree structure as text to clipboard."""
        if not self.parser:
            return
        
        root = self.parser.build_tree()
        text = root.to_text()
        
        self.clipboard_clear()
        self.clipboard_append(text)
        self.statusbar.config(text="Tree copied to clipboard!")
    
    def _copy_raw_entries(self):
        """Copy raw register entries list to clipboard."""
        if not self.parser:
            return
        
        text = self.parser.get_entries_table()
        self.clipboard_clear()
        self.clipboard_append(text)
        self.statusbar.config(text="Raw entries copied to clipboard!")

    def _expand_all(self):
        """Expand all nodes in the tree."""
        def expand_recursive(item):
            self.tree.item(item, open=True)
            for child in self.tree.get_children(item):
                expand_recursive(child)
        
        for item in self.tree.get_children():
            expand_recursive(item)

    def _collapse_all(self):
        """Collapse all nodes in the tree."""
        def collapse_recursive(item):
            self.tree.item(item, open=False)
            for child in self.tree.get_children(item):
                collapse_recursive(child)
        
        for item in self.tree.get_children():
            collapse_recursive(item)


def main():
    app = RegisterViewer()
    app.mainloop()


if __name__ == '__main__':
    main()
