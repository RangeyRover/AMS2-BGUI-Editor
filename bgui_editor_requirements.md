# BGUI Editor - System Requirements Specification

## 1. Overview
The goal is to develop a comprehensive BGUI Editor that surpasses the limitations of the existing `bgui-editor25.py` tool. The new editor will provide full support for viewing, editing, and saving BGUI files, including not just the "Head" section but also the Function Containers and Register.

## 2. Functional Requirements

### 2.1 File Operations
*   **Open File**: Load `.bgui` files. Validate signature (`00 00 10 40`). Warn on non-standard magic (e.g., `7b 14 0e 40`) but attempt to parse.
*   **Save File**: Save changes back to disk with correct structure regeneration (Head + Containers + Register).
*   **Save As**: Save copy to new path.
*   **Validation**: Report parsing errors or anomalies upon load (e.g., mismatch between Register and Container count).

### 2.2 Header Management (Head Section)
*   **Boundary Definition**: The Header MUST extend to the start of the first Container. Everything before the first Container is "Header".
*   **View Metadata**: Display file size, header size, and Page count.
*   **Sprite Management**:
    *   Toggle "Sprite Present" flag.
    *   Edit Sprite Path string (automatically handling byte-length prefix).
*   **Page Strings**: View and edit the list of Page Names.
*   **Magic Marker Config**: Maintain the `01...01` marker after the sprite string.

### 2.3 Container Management (The Core Feature)
*   **Hex View Integration**:
    *   Display the raw file content in a hex+ASCII format.
    *   **Direct Editing**: Allow users to edit the hex bytes directly.
    *   **Warning**: Display a warning when editing starts ("Unstructured edit").
    *   **Section Highlighting**: Clicking top-level nodes highlights their full byte range.
    *   **Precise Highlighting**: Highlighting MUST be applied only to the specific hex bytes (and corresponding ASCII) of the selection, avoiding entire row selection that includes offsets/separators.
    *   **Zoom/Highlight**: Sync with tree selection (auto-scroll to container data).
*   **Tree View**: Display the hierarchy defined by the Register (Parent-Child relationships).
*   **File Hierarchy**:
    *   Display high-level sections: **Header**, **Containers** (Tree), **Register**.
    *   **Header Values**: The tree MUST display header contents (Sprite Path, Container Strings, Page Data size) as child nodes.
    *   **Register**: Show all entries in the Register block (ID, Count).
*   **Container List**: Flat list view for quick searching by ID or Name.
*   **Properties Editor**:
    *   **Name**: Edit cosmetic name.
    *   **ID**: View and edit Container ID.
    *   **Geometry**: Edit `X`, `Y`, `Size` (f32).
    *   **Color**: Edit Color (Hex/RGB).
    *   **Resource**: Edit Resource String.
    *   **Unknown Data**: View/Edit the "Unknown Data" block (44 bytes).
*   **Add/Remove**:
    *   Add/Delete containers (Updating Register and Data).

### 2.4 Register Management
*   **Automatic Sync**: The editor automatically rebuilds the Register on save.
*   **Detailed View**: Register entries are viewable as a list in the Tree logic.

### 2.5 Hex/Raw View
*   **Hex Preview**: Integrated hex viewer.
*   **Direct Edit**: "Enable Direct Edit" mode with "Commit" functionality to re-parse the file.
*   **Navigation**: Zoom to offset on selection.
*   **Field-Level Highlighting**: Clicking an editable property field MUST highlight only the specific bytes for that field in the hex view.

### 2.6 Live Property Editing
*   **Hex Sync**: Property edits MUST update the hex view immediately after applying.
*   **Length Auto-Calculation**: For length-prefixed strings (Name, Resource), lengths MUST be automatically calculated and displayed when strings are edited.
*   **Length Display**: Properties panel MUST show current Name Length, Resource Block Length (fixed 189), and Resource String Length (inner) as read-only fields.

## 3. Data Structure Rules (based on `bgui_format.md`)

### 3.1 Container Layout
The editor **MUST** adhere to the validated container structure:
*   **Logical Start**: 8 bytes before Marker.
*   **Offset Tracking**: Capture `File Offset` and `Byte Length`.
*   **Subsection Count**: Start + 3 (Also synced from Register).
*   **Marker**: `03 00 00 00` at Start + 4.
*   **Name Length**: Start + 8.
*   **Name String**: Variable length, no null terminator.
*   **Padding**: 4 bytes after Name.
*   **Anchor ID**: `u32` at `NameEnd + 4`.
*   **Properties**: Fixed offsets from ID (`X`+4, `Y`+8, `Size`+12, `Color`+16).
*   **Unknown Data**: 44 bytes at `ID + 20` must be preserved.
*   **Resource Block**: At `ID + 64`. Fixed 189 bytes. Contains nested structure: `[Flags (5b)][Inner Len (1b)][String][Padding]`.

### 3.2 File Assembly
When saving, the file must be written in this strict order:
1.  **Head**: Magic -> Sprite Block -> Page Strings -> Head End Pad.
2.  **Container Data**: Sequential blocks for all containers.
3.  **Register**: `14-byte Signature` -> Sequence of `[ID, ChildCount]` pairs.

## 4. UI/UX Requirements
*   **Technology**: Modern GUI (e.g., Python `tkinter` with `ttk` or `PyQt`).
*   **Layout**:
    *   **Left Pane**: Tree hierarchy of containers.
    *   **Middle/Right Pane**: Property Inspector for the selected container.
    *   **Bottom Pane**: Status log and validation messages.
*   **Float Precision**: Display float values with high precision (e.g., 4 decimal places) as seen in analysis.
*   **High DPI Support**: The application MUST be Windows DPI-aware to prevent blurry text on high-resolution displays (using `ctypes` / `shcore`).


## 5. Non-Functional Requirements
*   **Robustness**: Must verify "Name Length" bytes to avoid reading garbage.
*   **Compatibility**: Support "Bentley", "Cart", and non-standard magic header variants (with warnings).
*   **Performance**: Handle files with 100+ containers efficiently.


