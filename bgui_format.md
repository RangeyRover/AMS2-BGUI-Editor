# BGUI File Format Specification

**Status**: Reverse-Engineered (Refined)  
**Endianness**: Little-Endian (`<`)  
**Alignment**: Appears to be 4-byte aligned for major fields.

## 1. File Structure Overview
The file consists of three main sections:
1.  **Head**: Global header, configurations, sprite/page lists.
2.  **Container Data**: Sequence of UI element definitions.
3.  **Register**: Hierarchy definition at the end.

---

| Offset | Type | Name | Description |
| :--- | :--- | :--- | :--- |
| `+0` | `u32` | **Container ID** | Unique ID linking to Container Data. |
| `+4` | `u32` | **Child Count** | Number of subsections/children for this node. |

---

## 2. Head Section & Markers
The file begins with a header section containing `01` markers and the Manifest (ID:0).

### `01` Markers
- **Sprite Pointer**: The first `01` marker typically marks the sprite path (e.g., `gui\displaysprites6.bspr`).
- **Project Container (ID:1)**: The second `01` marker (name "Container") defines **Container 1**.
    - It acts as the root of the standard container hierarchy.
    - Its physical location is in the header, but its children may be anywhere in the file.

### Container 0 (The Manifest)
- **Marker**: `03 00 00 00`
- **Name**: Empty (Length 0).
- **Structure**:
    - `Offset + 0`: Marker (03)
    - `Offset + 4`: Name Length (00)
    - `Offset + 5`: **String Count** (u32)
    - `Offset + 9`: ... Body / Padding ...
    - `Offset + ~64`: Start of String List (Pascal strings).
- **Purpose**: Defines the Manifest Keys (strings used for lookup/pages).

## 3. Container Data Block
Located between Head End and the Register Signature. contains visual properties.

### 3.1 Block Header
Each container block starts with a marker pattern.

| Offset | Type | Value/Name | Description |
| :--- | :--- | :--- | :--- |
| `0x00` | `u32` | `03` or `04` | **Container Marker** (Standard or Text) |
| `0x04` | `u8` | **Name Len** (N) | Length of cosmetic name. |
| `0x05` | `char` | **Name** | ASCII String (N bytes). |
| `0x05+N`| `u32` | **Hash/Pad** | Unknown value (often large/random looking, possibly a hash of the name). |

### 3.2 Container Body
Immediately follows the `Hash/Pad` field. Offsets below are relative to the **Container ID** (which is at `NameEnd + 4`).

| Rel Off | Type | Name | Description |
| :--- | :--- | :--- | :--- |
| **`+00`** | `u32` | **Container ID** | **Anchor**. Matches Register ID. |
| `+04` | `f32` | **X Position** | Lateral position relative to parent? |
| `+08` | `f32` | **Y Position** | Vertical position. |
| `+12` | `f32` | **Size/Scale** | Element size or scale factor. |
| `+16` | | **Color** | **Not fixed**. Located by searching backwards from container end for `1.0f` marker. |
| `+20` | `byte[44]` | **Reserved** | "Unknown Data" block (44 bytes). Non-zero in some variants. |
| `+64` | `u32` | **Resource Tag** | Tag `BD 00 00 00` (Start of Resource Property). |
| `+68` | | **Resource Data** | See **Section 3.3** for dynamic structure. |

### 3.3 Resource Property (Dynamic)
The Resource Property is identified by the tag `BD 00 00 00`. It is **not** fixed size.

| Rel Off | Type | Name | Description |
| :--- | :--- | :--- | :--- |
| `+0` | `varies` | **Header/Flags** | Variable length header (5-14 bytes). |
| `+5` | `u8` | **Inner String Len** | Actual string length (0 if empty). |
| `+6` | `char[N]` | **Resource String** | Texture (.dds) or Font (.bfont) path. |
| `+6+N` | `byte[]` | **Padding** | Zero-padding to fill block. |

**Example** (from `display_bentley_speed8.bgui`):
```
bd 00 00 00   <- Resource Block Len = 189
00 01 00 00 00   <- Flags (5 bytes)
1e   <- Inner String Len = 30
64 69 73 70 6c 61 79 5f...   <- "display_bentley_speed8_off.dds"
00 00 00...   <- Padding to 189 total
```

> [!IMPORTANT]
> The **BD** tag identifies the property. The parser scans for this tag and then heuristically finds the string length byte.

---

## 4. Head Section
*   **Magic**: `00 00 10 40` at `0x00` (primary format).
*   **Sprite Block**: Optional `01 00 00 00` flag + string + `01 00 00 00 01 00 00 00` marker.
*   **Page List**: Repeating structure following Container String block.

## 5. Magic Header Variants

| Magic Bytes | Hex | Description |
| :--- | :--- | :--- |
| `00 00 10 40` | `0x40100000` | **Standard format** (most files). |
| `7b 14 0e 40` | `0x400E147B` | **Alternate format** (e.g., `display_audi_v8.bgui`). Different structure, not yet supported. |

> [!WARNING]
> Files with non-standard magic headers (`7b 14 0e 40`) use a different internal structure and cannot be parsed with the current implementation.

## 6. Register
*   **Signature**: 14 bytes starting with `0E`. Often `0E 00 ...`.
*   **Structure**: 8-byte entries: `[Container ID (u32)] [Subsection Count (u32)]`.
*   **Head End**: DEFINED by the start of the first Container (no gaps).

## 7. Parsing Strategy (Robustness)
1.  **Validate Magic**: Check for `00 00 10 40`. Reject or warn on other variants.
2.  **Register First**: Scan backwards for register signature.
3.  **Scan Containers**: Find `03` or `04` markers, validate IDs against register.
4.  **Overlap Handling**: If resource block extends past next container, truncate.
5.  **Preserve Unknown Data**: Keep 44-byte reserved block intact.
