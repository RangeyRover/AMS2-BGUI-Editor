
import struct
import io
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict

# Constants
MAGIC = b"\x00\x00\x10\x40"
CONTAINER_MARKER = b"\x03\x00\x00\x00"
REGISTER_SIG = b"\x0E" + (b"\x00" * 13)
SPRITE_MARKER = b"\x01\x00\x00\x00\x01\x00\x00\x00"

def u32_le(b): return struct.unpack("<I", b)[0]
def f32_le(b): return struct.unpack("<f", b)[0]
def p_u32(val): return struct.pack("<I", val)
def p_f32(val): return struct.pack("<f", val)

@dataclass
class BguiHead:
    sprite_present: bool = False
    sprite_path: str = ""
    # "Pages" are complex repeating structures. For now we just capture raw bytes of the 
    # page section to preserve them, as full expansion wasn't key requirement vs containers.
    # However, requirements mention "View/Edit Page Names".
    # Let's try to parse them if possible, or store raw if robust.
    # Based on verification: Separator e0 26... 
    # Let's store the RAW bytes between Sprite/Container String and Head End to be safe.
    raw_page_data: bytes = b""
    
    # We also have the "Container" string block immediately after sprite marker.
    container_str: str = "Container"
    
    # Editor Metadata
    file_offset: int = 0
    byte_len: int = 0

@dataclass
class BguiContainer:
    id: int = 0
    name: str = "NewContainer"
    x: float = 0.0
    y: float = 0.0
    size: float = 1.0
    color: int = 0xFFFFFFFF # u32
    
    # The "Unknown Data" / Reserved block (44 bytes).
    unknown_data: bytes = field(default_factory=lambda: b"\x00"*44)
    
    res_string: str = ""
    
    # Subsection count (Syncs with Register)
    subsection_count: int = 0
    
    # Raw header bytes (everything before the CONTAINER_MARKER).
    # Variable length in practice. Preserved for byte-perfect round-trips.
    raw_header: bytes = field(default_factory=lambda: b"\x00"*8)
    
    # Internal: Hash/Pad after name.
    name_hash_pad: int = 0x00000000
    
    # claimed_res_len: The value read from the file for Resource Length.
    claimed_res_len: int = -1
    
    # Raw bytes of entire container (for byte-perfect round-trips)
    raw_bytes: bytes = b""
    
    # Metadata for Editor (Offsets)
    file_offset: int = -1
    body_offset: int = -1  # Absolute offset of body (ID field)
    byte_len: int = 0




@dataclass
class BguiNode:
    container: BguiContainer
    children: List['BguiNode'] = field(default_factory=list)

class BguiFile:
    def __init__(self):
        self.head = BguiHead()
        self.containers: List[BguiContainer] = []
        self._preserved_register_unknowns = b""
        
        # Raw container block (for byte-perfect round-trips)
        self.raw_container_block: bytes = b""
        
        # Raw register block (for byte-perfect round-trips)
        self.raw_register_block: bytes = b""
        
        # Register Offset Metadata
        self.reg_offset: int = -1
        self.reg_byte_len: int = 0

    def get_structure_tree(self) -> List[BguiNode]:
        """
        Reconstructs the hierarchy based on the container list order 
        and subsection_count (child count).
        Assumes Pre-Order traversal (Standard for this type of structure).
        """
        if not self.containers:
            return []
            
        # We process the linear list.
        # A stack keeps track of: [ (parent_node, remaining_children_to_attach) ]
        # But wait, 'subsection_count' usually means IMMEDIATE children.
        
        # Iterative approach:
        # We have a list of roots.
        # When we encounter a node, we attach it to the current active parent.
        # If the node has children, it becomes the active parent.
        
        # However, we don't know "remaining descendants", only "immediate children".
        # If Child A has 2 children.
        # We attach Child A to Root.
        # Now we expect 2 children for Child A.
        # The next node in list is Child A1. We attach to Child A.
        # If Child A1 has 0 children. We are done with A1.
        # We still expect 1 child for Child A.
        # Next node is Child A2. Attach to Child A.
        # Done with Child A.
        # Return to Root.
        
        roots = []
        stack = [] # List of [node, remaining_children]
        
        iterator = iter(self.containers)
        
        # But wait, there might be multiple top-level roots?
        # A container with NO parent logic?
        # Usually file starts with a Root?
        
        # Let's run through the iterator.
        for c in self.containers:
            node = BguiNode(c)
            
            if not stack:
                roots.append(node)
            else:
                parent, remaining = stack[-1]
                parent.children.append(node)
                stack[-1][1] -= 1
                if stack[-1][1] <= 0:
                    stack.pop()
                    
            if c.subsection_count > 0:
                stack.append([node, c.subsection_count])
                
        return roots

    @staticmethod
    def parse(blob: bytes) -> 'BguiFile':
        bf = BguiFile()
        n = len(blob)
        
        # Scan for Register first to have reg_off available
        reg_map = {} # ID -> SubCount
        reg_off = blob.rfind(REGISTER_SIG)
        if reg_off != -1:
            bf.reg_offset = reg_off
            bf.reg_byte_len = n - reg_off
            # Store raw register block for byte-perfect round-trips
            bf.raw_register_block = blob[reg_off:]
            
            r_curr = reg_off + 14
            while r_curr < n - 7:
                 rid = blob[r_curr]
                 rcnt = blob[r_curr+4]
                 reg_map[rid] = rcnt
                 r_curr += 8

        # --- 1. HEAD PARSE ---
        if blob[0:4] != MAGIC:
            import warnings
            actual_magic = blob[0:4].hex(' ')
            warnings.warn(f"Non-standard magic header detected: {actual_magic}. Expected: 00 00 10 40. Attempting to parse anyway.")
            bf.head.non_standard_magic = True
        else:
            bf.head.non_standard_magic = False
            
        curr = 4
        bf.head.sprite_present = (u32_le(blob[curr:curr+4]) == 1)
        curr += 4
        
        if bf.head.sprite_present:
            s_len = blob[curr]
            curr += 1
            bf.head.sprite_path = blob[curr : curr+s_len].decode("latin1")
            curr += s_len
            
            # Expect Sprite Marker
            if blob[curr:curr+8] == SPRITE_MARKER:
                curr += 8
            else:
                # Warning or loose parsing?
                pass
        
        # Container String Block
        c_len = blob[curr]
        curr += 1
        bf.head.container_str = blob[curr : curr+c_len].decode("latin1")
        curr += c_len
        
        # Scan for First Container Marker to define Head End
        # We must use robust scanning to avoid false positives in Page Data
        scan_h = curr
        head_end = n
        if reg_off != -1: head_end = reg_off
        
        while scan_h < n:
            m_idx = blob.find(CONTAINER_MARKER, scan_h)
            if m_idx == -1:
                break
            
            # Found a marker? Validate it.
            # Start = m_idx - 8
            # ID = m_idx + [Marker(4) + NameLen(1) + Name(N) + Pad(4)] -> Hard to predict NameLen.
            # But we can try to parse it?
            
            # Wait, robust scanning in the main loop calculates 'start_off' then parses.
            # We should do the same here.
            
            p_start = m_idx - 8
            if p_start < scan_h:
                 scan_h = m_idx + 4
                 continue
                 
            # Quick parse attempt
            try:
                # Need at least header bytes
                if p_start + 12 >= n: 
                    scan_h = m_idx + 4
                    continue
                    
                p_name_len = blob[p_start + 12]
                # ID is at Start + 13 + NameLen + 4
                p_id_off = p_start + 13 + p_name_len + 4
                
                if p_id_off + 4 > n:
                    scan_h = m_idx + 4
                    continue
                    
                p_id = u32_le(blob[p_id_off : p_id_off+4])
                
                # Check register if available
                if reg_map and p_id in reg_map:
                    # Valid!
                    head_end = p_start
                    break
                elif not reg_map:
                    # No register? Trust the first marker found?
                    # Or heuristic?
                    head_end = p_start
                    break
                else:
                    # Not in register -> False positive
                    # print(f"DEBUG: False positive marker in Header at {m_idx:X}")
                    scan_h = m_idx + 4
                    continue
                    
            except Exception:
                scan_h = m_idx + 4
                continue
            
        if head_end > curr:
            bf.head.raw_page_data = blob[curr:head_end]
            
        # Capture Head Offset info
        bf.head.file_offset = 0
        bf.head.byte_len = head_end
            
        # --- 3. CONTAINER PARSE ---
        # Scan markers from head_end
        scan_cursor = head_end
        if scan_cursor < 0: scan_cursor = 0 # Safety
        
        # If reg_off is -1, scan to end
        scan_end = reg_off if reg_off != -1 else n
        
        # Store raw container block for byte-perfect round-trips
        bf.raw_container_block = blob[head_end:scan_end]
        
        while scan_cursor < scan_end:
            # We look for valid containers.
            # A container conceptually starts at 'offset'.
            # Marker is at offset + 8.
            # We can search for marker, then backtrack 8 bytes to find start.
            
            m_idx = blob.find(CONTAINER_MARKER, scan_cursor, scan_end)
            if m_idx == -1: 
                # print(f"DEBUG: No marker found from {scan_cursor} to {scan_end}")
                break
            
            start_off = m_idx - 8
            if start_off < scan_cursor: 
                # Should not happen if we advance correctly, but safety:
                # print(f"DEBUG: Backtrack invalid. m_idx={m_idx}, start={start_off}, cursor={scan_cursor}")
                scan_cursor = m_idx + 4
                continue

            # Parse Header
            # +3: SubCount (Original theory) -> UPDATED: +4 (4 bytes)
            # +8: Marker
            try:
                # Capture all bytes before the marker as raw_header
                # start_off is m_idx - 8, so raw_header = blob[start_off : m_idx]
                raw_hdr = blob[start_off : m_idx]
                
                # For containers with variable header sizes, we need to find the actual start
                # by looking backwards from the marker for non-zero patterns
                
                name_len = blob[start_off+12]
                
                # Name
                name_start = start_off + 13
                
                if name_start + name_len > scan_end:
                     # print("DEBUG: Name overflow")
                     scan_cursor = m_idx + 4
                     continue
                     
                name_bytes = blob[name_start : name_start+name_len]
                # Validate ASCII
                try:
                    name_str = name_bytes.decode("ascii") 
                except:
                     # print("DEBUG: Name invalid ascii")
                     scan_cursor = m_idx + 4
                     continue

                # Pad/Hash (4 bytes)
                pad_off = name_start + name_len
                name_hash = u32_le(blob[pad_off:pad_off+4])
                
                # Body Start (ID)
                body_off = pad_off + 4
                cid = u32_le(blob[body_off:body_off+4])
                
                # Validate ID against Register (Robustness against false positive markers)
                if reg_map and cid not in reg_map:
                     # print(f"DEBUG: False Positive Marker at {m_idx:X}. ID {cid} not in Register.")
                     scan_cursor = m_idx + 4
                     continue
                
                # Props
                cx = f32_le(blob[body_off+4 : body_off+8])
                cy = f32_le(blob[body_off+8 : body_off+12])
                csize = f32_le(blob[body_off+12 : body_off+16])
                ccolor = u32_le(blob[body_off+16 : body_off+20])
                
                # Unknown Data (44 bytes)
                unk_start = body_off + 20
                unk_data = blob[unk_start : unk_start+44]
                
                # Resource Block (Nested Structure)
                # Format: [4-byte outer len][5-byte flags][1-byte inner len][string][padding]
                res_block_off = body_off + 64
                res_block_len = u32_le(blob[res_block_off : res_block_off+4])
                
                res_str = ""
                inner_str_len = 0
                if res_block_len > 0:
                    # Resource block starts at body+68
                    res_block_start = res_block_off + 4
                    if res_block_start + res_block_len > scan_end:
                         scan_cursor = m_idx + 4
                         continue
                    
                    # Parse nested structure: [5-byte flags][1-byte inner len][string]
                    if res_block_len >= 6:
                        inner_str_len = blob[res_block_start + 5]  # 1-byte inner string length
                        inner_str_off = res_block_start + 6
                        if inner_str_len > 0 and inner_str_off + inner_str_len <= res_block_start + res_block_len:
                            res_str = blob[inner_str_off : inner_str_off + inner_str_len].decode("latin1")
                
                # Store both outer block length and actual string
                res_len = res_block_len  # Keep for backward compatibility
                end_of_cont = res_block_off + 4 + res_block_len
                
                # --- ROBUST SCANNING ---
                # Issue: Some files have ResLen or garbage that claims to extend 
                # BEYOND the start of the next container.
                # We must prioritize finding the NEXT valid marker.
                # Min size of a container is 68 bytes from body (ignoring name).
                
                search_start = body_off + 68 
                search_limit = min(scan_end, end_of_cont + 2048) # Limit lookahead to avoid stalling
                
                # Scan for marker in the 'potential' overlap zone until expected end + slop
                # Or actually, we should just scan until we find one?
                # Let's scan from search_start up to scan_end (global limit).
                
                next_marker = blob.find(CONTAINER_MARKER, search_start, scan_end)
                
                if next_marker != -1:
                    # found a marker. Is it valid?
                    # Check padding before it?
                    # Marker is at +8. Start at -8.
                    next_start = next_marker - 8
                    
                    if next_start < end_of_cont:
                         # OVERLAP DETECTED!
                         # Verify it's a real container?
                         # Check header bounds?
                         if next_start + 12 < scan_end:
                             # Assume valid for now to salvage structure
                             # print(f"DEBUG: Overlap detected. Truncating cont {cid} from {end_of_cont:X} to {next_start:X}")
                             
                             # Truncate container end, but keep the correctly parsed res_str
                             # (The res_str was already parsed from the inner string length,
                             # so we don't want to overwrite it with raw bytes)
                             end_of_cont = next_start
                             # print(f"DEBUG: Overlap fixed. Next scan starts at {end_of_cont:X}")
                             
                # Create Container
                cont = BguiContainer(
                    id=cid,
                    name=name_str,
                    x=cx,
                    y=cy,
                    size=csize,
                    color=ccolor,
                    unknown_data=unk_data,
                    res_string=res_str,
                    subsection_count=0, # Will be set by Register
                    raw_header=raw_hdr,
                    name_hash_pad=name_hash,
                    claimed_res_len=res_len,
                    raw_bytes=blob[start_off:end_of_cont],
                    file_offset=start_off,
                    body_offset=body_off,
                    byte_len=end_of_cont - start_off
                )

                
                # Sync subcount from Register if available (Register is truth?)
                # Actually, core file has it in two places. Let's trust Register if available, else Header.
                if cid in reg_map:
                    cont.subsection_count = reg_map[cid]
                    
                bf.containers.append(cont)
                
                # Advance cursor to the end of this container (truncated or original)
                scan_cursor = end_of_cont

                
                # Safety check to prevent infinite loop if we didn't advance
                if scan_cursor <= start_off:
                    scan_cursor = start_off + 1
                
            except Exception as e:
                # Parsing failed, maybe false positive marker?
                # Just skip this marker
                # print(f"DEBUG: Parse exc {e}")
                scan_cursor = m_idx + 4
                
        return bf

    def serialize(self) -> bytes:
        out = bytearray()
        
        # 1. HEAD
        out.extend(MAGIC)
        out.extend(p_u32(1 if self.head.sprite_present else 0))
        
        if self.head.sprite_present:
            s_bytes = self.head.sprite_path.encode("latin1")
            out.append(len(s_bytes))
            out.extend(s_bytes)
            out.extend(SPRITE_MARKER)
            
        c_bytes = self.head.container_str.encode("latin1")
        out.append(len(c_bytes))
        out.extend(c_bytes)
        
        out.extend(self.head.raw_page_data)
        
        # 2. CONTAINERS
        if self.raw_container_block:
            # Byte-perfect round-trip: use stored raw block
            out.extend(self.raw_container_block)
        else:
            # Fallback: reconstruct containers (for new files)
            for c in self.containers:
                if c.raw_bytes:
                    out.extend(c.raw_bytes)
                else:
                    out.extend(c.raw_header)
                    out.extend(CONTAINER_MARKER)
                    n_bytes = c.name.encode("latin1")
                    out.append(len(n_bytes))
                    out.extend(n_bytes)
                    out.extend(p_u32(c.name_hash_pad))
                    out.extend(p_u32(c.id))
                    out.extend(p_f32(c.x))
                    out.extend(p_f32(c.y))
                    out.extend(p_f32(c.size))
                    out.extend(p_u32(c.color))
                    out.extend(c.unknown_data[:44].ljust(44, b"\x00"))
                    
                    # Resource Block (Nested Structure)
                    # Format: [4-byte outer len=189][5-byte flags][1-byte inner len][string][padding]
                    RESOURCE_BLOCK_SIZE = 189
                    res_bytes = c.res_string.encode("latin1")
                    inner_len = min(len(res_bytes), RESOURCE_BLOCK_SIZE - 6)  # Cap at max
                    
                    out.extend(p_u32(RESOURCE_BLOCK_SIZE))  # Outer block length
                    out.extend(b"\x00\x01\x00\x00\x00")     # 5-byte flags
                    out.append(inner_len)                   # 1-byte inner string length
                    out.extend(res_bytes[:inner_len])       # Resource string (capped)
                    
                    # Padding to fill 189-byte block (189 - 6 - inner_len)
                    padding_len = RESOURCE_BLOCK_SIZE - 6 - inner_len
                    out.extend(b"\x00" * padding_len)
            
        # 3. REGISTER
        if self.raw_register_block:
            # Byte-perfect round-trip: use stored raw register
            out.extend(self.raw_register_block)
        else:
            # Fallback: reconstruct register
            out.extend(REGISTER_SIG)
            for c in self.containers:
                out.append(c.id & 0xFF)
                out.extend(b"\x00\x00\x00")
                out.append(c.subsection_count & 0xFF)
                out.extend(b"\x00\x00\x00")
            
        return bytes(out)
