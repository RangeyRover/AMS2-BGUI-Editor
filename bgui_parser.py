"""
BGUI Register Parser - Core Logic Module
Separated from GUI for unit testing.

DROP-IN REPLACEMENT
===================
Changes vs your current version:
- Properly supports BOTH container markers: 03 and 04 (container_type is stored per container)
- Fixes the incorrect assumption that BD has a fixed header size:
  - BD is a tagged property (u32 0xBD), not a fixed-length block
  - The length byte position varies (03 vs 04 and even within same marker family)
- Robust BD resource extraction:
  - Finds BD near the body
  - Tries multiple candidate length offsets
  - Validates ASCII and likely suffixes (.dds, .bfont, etc.)
- Improves colour extraction window:
  - Searches further (default 512 bytes) for the *last* 00 00 80 3F marker and takes RGB from the 3 bytes before it
"""

import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple


# ----------------------------
# Data structures
# ----------------------------

@dataclass
class RegisterEntry:
    """Single entry from the Register section."""
    index: int
    container_id: int
    child_count: int
    file_offset: int


@dataclass
class ContainerInfo:
    """Container found by scanning for markers."""
    marker_offset: int      # Offset of container marker (03 or 04)
    name_length: int        # Length of name string
    name: str               # Container name
    container_id: int       # ID from container body (after name + padding)
    body_offset: int        # Offset where ID field begins
    container_type: int = 3 # Marker type: 3 or 4

    # Body properties (relative to body_offset)
    x: float = 0.0          # +04: X position
    y: float = 0.0          # +08: Y position
    size: float = 0.0       # +12: Size/Scale

    color: int = 0          # RGBA packed (A=FF)
    color_offset: int = 0   # Offset where RGB begins (R byte)
    resource: str = ""      # Resource string decoded from BD property
    resource_offset: int = 0  # Offset where resource string begins


@dataclass
class HeaderInfo:
    """Parsed data from the 01-marker header section and Manifest."""
    sprite_path: str = ""
    project_name: str = ""
    manifest_strings: List[Tuple[str, int]] = None  # List of (string, offset_of_length_byte)
    
    def __post_init__(self):
        if self.manifest_strings is None:
            self.manifest_strings = []


class TreeNode:
    """Node in the container hierarchy tree."""
    def __init__(self, entry: Optional[RegisterEntry] = None, name: str = "Root"):
        self.entry = entry
        self.name = name
        self.children: List['TreeNode'] = []

    def add_child(self, child: 'TreeNode'):
        self.children.append(child)

    @property
    def id(self) -> int:
        return self.entry.container_id if self.entry else -1

    @property
    def child_count(self) -> int:
        return self.entry.child_count if self.entry else 0

    def to_text(self, prefix: str = "", is_last: bool = True) -> str:
        """Generate text representation of tree."""
        lines: List[str] = []

        if self.entry:
            connector = "└── " if is_last else "├── "
            # Include name in output
            label = f"{self.name} (ID:{self.entry.container_id})" if self.name else f"ID:{self.entry.container_id}"
            lines.append(f"{prefix}{connector}{label} (children:{self.entry.child_count})")
            child_prefix = prefix + ("    " if is_last else "│   ")
        else:
            lines.append(f"Root (total entries: {len(self.children)})")
            child_prefix = ""

        for i, child in enumerate(self.children):
            is_last_child = (i == len(self.children) - 1)
            lines.append(child.to_text(child_prefix, is_last_child))

        return "\n".join(lines)


# ----------------------------
# Parser
# ----------------------------

class BguiRegisterParser:
    """Parser for BGUI file register sections."""

    MAGIC_STANDARD = b'\x00\x00\x10\x40'
    MAGIC_ALTERNATE = b'\x7b\x14\x0e\x40'
    MARKER_03 = b'\x03\x00\x00\x00'
    MARKER_04 = b'\x04\x00\x00\x00'
    BD_MARKER = b'\xBD\x00\x00\x00'
    COLOR_MARKER = b'\x00\x00\x80\x3F'  # float 1.0 (LE)

    def __init__(self, data: bytes = b''):
        self.data: bytes = data
        self.entries: List[RegisterEntry] = []
        self.containers: List[ContainerInfo] = []
        self.header_info: HeaderInfo = HeaderInfo()
        self.register_start: int = 0
        self.register_end: int = 0
        self.magic: bytes = b''
        self.filepath: str = ""

    @classmethod
    def from_file(cls, filepath: str) -> 'BguiRegisterParser':
        """Create parser from file path."""
        with open(filepath, 'rb') as f:
            data = f.read()
        parser = cls(data)
        parser.filepath = filepath
        return parser

    def is_standard_magic(self) -> bool:
        """Check if file has standard magic."""
        if not self.magic and len(self.data) >= 4:
            self.magic = self.data[:4]
        return self.magic == self.MAGIC_STANDARD

    def load(self) -> bool:
        """Parse the file data."""
        try:
            if len(self.data) < 4:
                return False

            self.magic = self.data[0:4]

            if not self.find_register():
                print("Could not find register section")
                return False

            # 1. Scan Standard Containers (03/04)
            self.scan_containers()

            # 2. Parse Header (01 Markers + Manifest)
            # This adds C1 and C0 to the containers list
            try:
                self.parse_header()
            except Exception as e:
                print(f"Header parsing warning: {e}")

            # 3. Parse Register
            if not self.parse_register():
                print("Failed to parse register")
                return False

            return True

        except Exception as e:
            print(f"Error loading file: {e}")
            import traceback
            traceback.print_exc()
            return False

    # ----------------------------
    # Register
    # ----------------------------

    def find_register(self) -> bool:
        """Locate the register section at the end of the file."""
        # Strategy 1: Signature scan near end for: 0E 00 00 00 + 10x00 then candidate is sig+14
        start_search_sig = max(0, len(self.data) - 4096)
        sig_scan = b'\x0E\x00\x00\x00' + (b'\x00' * 10)

        sig_pos = self.data.rfind(sig_scan, start_search_sig)
        if sig_pos != -1:
            candidate = sig_pos + 14
            if candidate + 8 <= len(self.data):
                try:
                    id_val = struct.unpack_from('<I', self.data, candidate)[0]
                    count_val = struct.unpack_from('<I', self.data, candidate + 4)[0]
                    if id_val == 0 and 0 <= count_val < 100000:
                        self.register_start = candidate
                        return True
                except Exception:
                    pass

        # Strategy 2: heuristic scan backwards for Root Node (ID=0, Count valid)
        start_search = (len(self.data) - 8) & ~1
        end_search = max(0, len(self.data) - 8192)

        for offset in range(start_search, end_search, -2):
            if offset + 8 > len(self.data):
                continue

            id_val = struct.unpack_from('<I', self.data, offset)[0]
            if id_val != 0:
                continue

            count_val = struct.unpack_from('<I', self.data, offset + 4)[0]
            remaining_bytes = len(self.data) - (offset + 8)
            needed_bytes = count_val * 8
            if needed_bytes > remaining_bytes:
                continue

            if not (0 <= count_val < 100000):
                continue

            # Strict: Root usually preceded by 00 00 00 00 padding
            if offset >= 4:
                prev = struct.unpack_from('<I', self.data, offset - 4)[0]
                if prev != 0:
                    continue

            self.register_start = offset
            return True

        return False

    def parse_register(self) -> bool:
        """Parse register hierarchy (flat list of [id,count] u32 pairs)."""
        if self.register_start == 0:
            return False

        self.entries.clear()

        curr = self.register_start
        idx = 0
        while curr < len(self.data) - 7:
            id_val, count_val = struct.unpack_from('<II', self.data, curr)
            self.entries.append(RegisterEntry(idx, id_val, count_val, curr))
            curr += 8
            idx += 1

        self.register_end = curr
        return True

    # ----------------------------
    # Header & Manifest
    # ----------------------------

    def parse_header(self):
        """Parse 01 markers and Container 0 (Manifest)."""
        offset = 4  # Skip magic
        
        # 1. Scan for 01 Markers (Sprite / Project)
        # Expecting up to 2 '01 00 00 00' markers before the first '03'
        import re
        
        while offset < len(self.data) - 8:
            val = struct.unpack_from('<I', self.data, offset)[0]
            
            if val == 3:  # Start of Manifest/Container 0
                break
                
            if val == 1: # Header element
                # Check for explicit ID field (Double 01 seen in Container 1)
                has_id = False
                if offset + 8 <= len(self.data):
                    check_id = struct.unpack_from('<I', self.data, offset + 4)[0]
                    if check_id == 1:
                        # Ambiguity check: NameLen at +8?
                        nl_candidate = self.data[offset + 8]
                        # "Container" is len 9. Sprite path is usually longer.
                        if nl_candidate > 1:
                            has_id = True
                
                name_len_offset = offset + 8 if has_id else offset + 4
                name_len = self.data[name_len_offset]
                
                name_start = name_len_offset + 1
                name_end = name_start + name_len
                
                if name_end >= len(self.data):
                    break
                    
                name = self.data[name_start:name_end].decode('ascii', errors='replace')
                
                if ".bspr" in name.lower():
                    self.header_info.sprite_path = name
                    # Do NOT create C1 here. The sprite path is just a header property.
                else:
                    self.header_info.project_name = name
                    # Create ContainerInfo for C1 from this "Container" string
                    c1 = ContainerInfo(
                        container_id=1,
                        name=name,
                        marker_offset=offset,
                        name_length=name_len,
                        body_offset=name_end 
                    )
                    self.containers.append(c1)
                    
                
                offset = name_end
                
                # Scan for next marker
                pat = re.compile(b'(\x01\x00\x00\x00|\x03\x00\x00\x00)')
                m = pat.search(self.data, offset)
                if m:
                    offset = m.start()
                else:
                    break
            else:
                # Unknown data, find next marker
                offset += 4
                pat = re.compile(b'(\x01\x00\x00\x00|\x03\x00\x00\x00)')
                m = pat.search(self.data, offset)
                if m:
                    offset = m.start()
                else:
                    break

        # 2. Parse Manifest (Container 0)
        # Expecting '03 00 00 00' at offset
        if offset + 16 < len(self.data):
            marker = struct.unpack_from('<I', self.data, offset)[0]
            if marker == 3:
                nl = self.data[offset+4]
                if nl == 0:
                    try:
                        # String Count is in the Pad/Hash field (offset+5) for C0
                        string_count = struct.unpack_from('<I', self.data, offset + 5)[0]
                        if 0 < string_count < 10000:
                            # Create ContainerInfo for C0
                            # Manifest doesn't really have a name, but we call it "Manifest"
                            c0 = ContainerInfo(
                                container_id=0,
                                name="Manifest",
                                marker_offset=offset,
                                name_length=0,
                                body_offset=offset+5,
                                resource=f"{string_count} strings"
                            )
                            self.containers.append(c0)

                            # Scan for strings starting after C0 body (approx offset + 64)
                            # Heuristic: Scan for Pascal strings [Len][String]
                            curr_s = offset + 64
                            found = 0
                            while found < string_count and curr_s < len(self.data) - 100: # Limit scan
                                slen = self.data[curr_s]
                                if 1 <= slen <= 100:
                                    # Check if followed by valid ASCII
                                    try:
                                        s_val = self.data[curr_s+1 : curr_s+1+slen].decode('ascii', errors='strict')
                                        # Filter garbage
                                        if any(ord(c) < 32 or ord(c) > 126 for c in s_val):
                                             curr_s += 1
                                             continue
                                             
                                        # Store (string, offset)
                                        self.header_info.manifest_strings.append((s_val, curr_s))
                                        found += 1
                                        curr_s += 1 + slen
                                        continue 
                                    except:
                                        pass
                                curr_s += 1
                                
                    except Exception:
                        pass

    # ----------------------------
    # Containers
    # ----------------------------

    def _is_plausible_marker(self, pos: int) -> bool:
        """Check if a marker at pos looks like a valid container start."""
        if pos + 10 >= len(self.data):
            return False
            
        # Name length (u8)
        name_len = self.data[pos + 4]
        if not (1 <= name_len <= 100):
            return False
            
        # Name should be printable ASCII
        name_bytes = self.data[pos + 5 : pos + 5 + name_len]
        if any(b < 0x20 or b > 0x7E for b in name_bytes):
            return False
            
        # Body start (after name + 4 byte padding/hash)
        body_off = pos + 5 + name_len + 4
        if body_off + 4 > len(self.data):
            return False
            
        # Optional: check if ID is plausible
        try:
            container_id = struct.unpack_from('<I', self.data, body_off)[0]
            if container_id > 50000:
                return False
        except Exception:
            return False
            
        return True

    def scan_containers(self) -> List[ContainerInfo]:
        """Scan file for container markers (03 and 04)."""
        import re

        self.containers = []
        search_end = self.register_start if self.register_start > 0 else len(self.data)

        marker_pattern = re.compile(b'(\x03\x00\x00\x00|\x04\x00\x00\x00)')

        all_matches = list(marker_pattern.finditer(self.data, 0, search_end))
        
        # Filter for PLAUSIBLE markers only to build boundaries
        valid_matches = [m for m in all_matches if self._is_plausible_marker(m.start())]

        for i, match in enumerate(valid_matches):
            pos = match.start()
            
            # Determine end of this container (start of next, or EOF/RegStart)
            if i + 1 < len(valid_matches):
                limit = valid_matches[i+1].start()
            else:
                limit = search_end
            
            try:
                # Pass limit to parser
                container = self._parse_container_at(pos, max_offset=limit)
                if container:
                    self.containers.append(container)
            except Exception:
                continue
    
        return self.containers

    def _parse_container_at(self, marker_offset: int, max_offset: int) -> Optional[ContainerInfo]:
        """Parse a container starting at marker_offset, strictly within max_offset."""
        if marker_offset + 5 >= len(self.data):
            return None

        marker_bytes = self.data[marker_offset:marker_offset + 4]
        if marker_bytes == self.MARKER_03:
            container_type = 3
        elif marker_bytes == self.MARKER_04:
            container_type = 4
        else:
            return None

        # Name length is at marker + 4 (u8)
        name_length = self.data[marker_offset + 4]
        if name_length == 0 or name_length > 100:
            return None

        name_start = marker_offset + 5
        name_end = name_start + name_length
        if name_end >= len(self.data):
            return None

        try:
            name = self.data[name_start:name_end].decode('ascii', errors='replace')
        except Exception:
            return None

        # Body starts after name + 4 bytes pad/hash
        body_offset = name_end + 4
        if body_offset + 16 > len(self.data):
            return None

        container_id = struct.unpack_from('<I', self.data, body_offset)[0]
        if container_id > 10000:
            return None

        x = struct.unpack_from('<f', self.data, body_offset + 4)[0]
        y = struct.unpack_from('<f', self.data, body_offset + 8)[0]
        size = struct.unpack_from('<f', self.data, body_offset + 12)[0]

        # Colour: last RGB immediately before last 00 00 80 3F within the container
        color, color_offset = self._extract_color(body_offset, max_offset=max_offset)

        # Resource: BD-tagged property with variable header
        resource, resource_offset = self._extract_bd_resource(body_offset, container_type, max_offset=max_offset)

        return ContainerInfo(
            marker_offset=marker_offset,
            name_length=name_length,
            name=name,
            container_id=container_id,
            body_offset=body_offset,
            container_type=container_type,
            x=x, y=y, size=size,
            color=color, color_offset=color_offset,
            resource=resource,
            resource_offset=resource_offset
        )

    # ----------------------------
    # Helpers: Colour
    # ----------------------------

    def _extract_color(self, body_offset: int, max_offset: int) -> Tuple[int, int]:
        """
        Find the last 00 00 80 3F before max_offset
        and treat the 3 bytes immediately before it as RGB.
        """
        search_start = body_offset + 20
        # Use rfind from search_start up to max_offset
        marker_pos = self.data.rfind(self.COLOR_MARKER, search_start, max_offset)
        
        # Diagnostic logging for RPMbar1
        # if max_offset - body_offset < 1000 and b'RPMbar1' in self.data[max_offset-200:max_offset]:
        #    print(f"DEBUG: Color scan for container near {body_offset:X}. limit={max_offset:X}, found={marker_pos:X}")

        if marker_pos == -1:
            return 0, 0

        rgb_offset = marker_pos - 3
        if rgb_offset < 0 or rgb_offset + 3 > len(self.data):
            return 0, 0

        r, g, b = self.data[rgb_offset:rgb_offset + 3]
        rgba = (0xFF << 24) | (r << 16) | (g << 8) | b
        return rgba, rgb_offset

    # ----------------------------
    # Helpers: BD Resource
    # ----------------------------

    @staticmethod
    def _is_plausible_resource_string(s: str) -> bool:
        """Heuristic for resource strings seen in BGUI."""
        if not s:
            return False
        if any(ord(ch) < 0x20 or ord(ch) > 0x7E for ch in s):
            return False
        # Common patterns observed
        if '.' not in s:
            return False
        # Often ends with these
        lowered = s.lower()
        if lowered.endswith(('.dds', '.bfont', '.bspr', '.png', '.jpg', '.jpeg', '.bmp')):
            return True
        # Allow unknown extensions but keep it cautious
        return len(s) >= 5 and len(s) <= 200

    def _extract_bd_resource(self, body_offset: int, container_type: int, max_offset: int) -> Tuple[str, int]:
        """
        Find BD 00 00 00 within container bounds and decode its length-prefixed ASCII string.
        """
        # Search for BD within the container body range.
        start = body_offset + 24
        end = max_offset
        
        if start >= end:
            return "", 0
            
        res_pos = self.data.find(self.BD_MARKER, start, end)
        if res_pos == -1:
            return "", 0

        # After BD tag (4 bytes), there is a variable header.
        # Try several plausible locations for the length byte.
        # These cover your observed cases and a few safe extras.
        candidate_len_offsets = [5, 6, 8, 9, 10, 11, 12, 13, 14]  # relative to res_pos
        best = ("", 0)

        for rel in candidate_len_offsets:
            len_offset = res_pos + rel
            if len_offset >= len(self.data):
                continue
            n = self.data[len_offset]
            if not (1 <= n <= 200):
                continue

            str_start = len_offset + 1
            str_end = str_start + n
            if str_end > len(self.data):
                continue

            try:
                s = self.data[str_start:str_end].decode('ascii', errors='strict')
            except Exception:
                continue

            if self._is_plausible_resource_string(s):
                # Prefer the earliest valid candidate (usually the true one)
                best = (s, str_start)
                break

        # If no strict decode worked, do a softer decode as last resort
        if not best[0]:
            for rel in candidate_len_offsets:
                len_offset = res_pos + rel
                if len_offset >= len(self.data):
                    continue
                n = self.data[len_offset]
                if not (1 <= n <= 200):
                    continue
                str_start = len_offset + 1
                str_end = str_start + n
                if str_end > len(self.data):
                    continue
                s = self.data[str_start:str_end].decode('ascii', errors='replace')
                if self._is_plausible_resource_string(s):
                    best = (s, str_start)
                    break

        return best

    # ----------------------------
    # Public helpers
    # ----------------------------

    def get_containers_table(self) -> str:
        if not self.containers:
            self.scan_containers()

        lines = [f"Containers ({len(self.containers)} found):"]
        lines.append("\nID    | Type | Offset     | Name")
        lines.append("-" * 70)
        for c in sorted(self.containers, key=lambda x: x.container_id):
            lines.append(f"{c.container_id:5} | {c.container_type:4} | 0x{c.marker_offset:08X} | {c.name}")
        return "\n".join(lines)

    def get_container_by_id(self, container_id: int) -> Optional[ContainerInfo]:
        if not self.containers:
            self.scan_containers()
        for c in self.containers:
            if c.container_id == container_id:
                return c
        return None

    def build_tree(self) -> TreeNode:
        """Build tree from register entries using Virtual Root."""
        virtual_root = TreeNode(name="Virtual Root")
        if not self.entries:
            return virtual_root
        
        # Ensure containers are scanned for name lookup
        if not self.containers:
            self.scan_containers()

        idx = 0
        total_entries = len(self.entries)

        def build_node_recursive() -> Optional[TreeNode]:
            nonlocal idx
            if idx >= total_entries:
                return None

            entry = self.entries[idx]
            idx += 1
            
            # Lookup name
            c = self.get_container_by_id(entry.container_id)
            node_name = c.name if c else ""
            
            node = TreeNode(entry=entry, name=node_name)

            if entry.child_count > 0:
                for _ in range(entry.child_count):
                    child = build_node_recursive()
                    if child:
                        node.add_child(child)
                    else:
                        break
            return node

        while idx < total_entries:
            root = build_node_recursive()
            if root:
                virtual_root.add_child(root)
            else:
                break

        return virtual_root

    def get_entries_table(self) -> str:
        lines = [f"Register Entries ({len(self.entries)}):"]
        lines.append("\nIdx   | ID    | Children | Offset")
        lines.append("-" * 50)
        for e in self.entries:
            lines.append(f"{e.index:<5} | {e.container_id:<5} | {e.child_count:<8} | 0x{e.file_offset:08X}")
        return "\n".join(lines)

    def get_node_byte_range(self, node: 'TreeNode') -> Tuple[int, int]:
        """
        Determine byte range for a node by:
        - start = its container marker_offset
        - end   = next container marker that is NOT in this node's subtree (or register_start)
        """
        if not node.entry:
            return (0, len(self.data))

        if not self.containers:
            self.scan_containers()

        def collect_ids(n: TreeNode) -> List[int]:
            ids = [n.entry.container_id] if n.entry else []
            for c in n.children:
                ids.extend(collect_ids(c))
            return ids

        # Strategy Update: User wants bounds to cover ALL children.
        # Since file layout is not strictly hierarchical (siblings can be interleaved or distant),
        # we calculate the [Min Start, Max End] of all containers in the subtree.
        
        subtree_ids = set(collect_ids(node))
        if not subtree_ids:
             # Just this node (no container info?)
             return (node.entry.file_offset, node.entry.file_offset + 8)

        min_off = len(self.data)
        max_off = 0
        
        relevant_containers = [c for c in self.containers if c.container_id in subtree_ids]
        
        if not relevant_containers:
             return (node.entry.file_offset, node.entry.file_offset + 8)

        # Calculate bounds based on relevant containers
        # We need their lengths too.
        # "Length" of a container is from its marker to the next container marker.
        # We can reuse the sorted_containers logic to determine individual lengths.
        
        sorted_containers = sorted(self.containers, key=lambda c: c.marker_offset)
        
        for c in relevant_containers:
            # Find its start
            start = c.marker_offset
            if start < min_off:
                min_off = start
                
            # Find its end (next marker in global list)
            # Find index in sorted_containers
            # Optimization: create map or iterate? iterating entire sorted list per node is slow O(N^2)
            # But N is small (~200).
            
            c_end = self.register_start
            for j, sc in enumerate(sorted_containers):
                if sc.marker_offset == start:
                    if j + 1 < len(sorted_containers):
                        c_end = sorted_containers[j+1].marker_offset
                    break
            
            if c_end > max_off:
                max_off = c_end

        return (min_off, max_off)
