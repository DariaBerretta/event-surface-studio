"""Local, zero-upload filesystem chooser for the Streamlit GUI.

A browser file-input cannot expose its absolute path to a web application.  For
large YARP logs and existing MP4s, navigating the local filesystem server-side
is preferable to uploading/copying files through Streamlit.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

SUPPORTED_EXTENSIONS = frozenset({".log", ".mp4"})


def normalize_extension(extension: str) -> str:
    suffix = extension.lower().strip()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {extension}")
    return suffix


def picker_start_directory(preferred: str | Path | None, home: Path | None = None) -> Path:
    """Prefer a selected file's parent or a directory, otherwise the user's home."""
    home = (home or Path.home()).expanduser().resolve()
    if preferred:
        candidate = Path(preferred).expanduser()
        if candidate.is_dir():
            return candidate.resolve()
        if candidate.is_file():
            return candidate.resolve().parent
    return home


def directory_entries(directory: Path, extension: str,
                      filter_text: str = "", show_hidden: bool = False) -> tuple[list[Path], list[Path]]:
    """Browse all directories but show only files matching the chosen extension."""
    suffix = normalize_extension(extension)
    if not directory.is_dir():
        raise NotADirectoryError(str(directory))
    needle = filter_text.strip().casefold()
    directories: list[Path] = []
    files: list[Path] = []
    for entry in directory.iterdir():
        if entry.name.startswith(".") and not show_hidden:
            continue
        if needle and needle not in entry.name.casefold():
            continue
        if entry.is_dir():
            directories.append(entry)
        elif entry.is_file() and entry.suffix.lower() == suffix:
            files.append(entry)
    return (sorted(directories, key=lambda p: p.name.casefold()),
            sorted(files, key=lambda p: p.name.casefold()))


def draw_picker(extension: str, context: str, destination_key: str,
                initial_directory: Path | None = None) -> None:
    """Draw the graphical chooser inside an st.dialog fragment.

    The chosen path is stored in a *pending* session key because the destination
    text_input may already have been instantiated during the current app run.
    """
    import streamlit as st

    suffix = normalize_extension(extension)
    directory_key = f"picker_dir_{context}"
    search_key = f"picker_filter_{context}"
    page_key = f"picker_page_{context}"
    reset_filter_key = f"picker_reset_filter_{context}"
    if st.session_state.pop(reset_filter_key, False):
        # This runs before the filter input is instantiated in this fragment.
        st.session_state[search_key] = ""
    if directory_key not in st.session_state:
        st.session_state[directory_key] = str(initial_directory or Path.home())

    directory = Path(st.session_state[directory_key]).expanduser()
    if not directory.is_dir():
        directory = Path.home()
        st.session_state[directory_key] = str(directory)

    st.caption("Select a file on this computer. Files are opened in place, without uploading or copying them.")

    nav_home, nav_downloads, nav_parent, nav_root = st.columns(4)
    shortcuts = (
        (nav_home, "Home", Path.home()),
        (nav_downloads, "Downloads", Path.home() / "Downloads"),
        (nav_parent, "Up one folder", directory.parent),
        (nav_root, "Filesystem /", Path("/")),
    )
    for col, title, target in shortcuts:
        with col:
            if st.button(title, key=f"{context}_shortcut_{title}",
                         use_container_width=True, disabled=not target.is_dir()):
                st.session_state[directory_key] = str(target.resolve())
                st.session_state[page_key] = 0
                st.session_state[reset_filter_key] = True
                st.rerun(scope="fragment")

    st.code(str(directory), language=None)
    query = st.text_input("Filter names in this folder", key=search_key,
                          placeholder=f"Search folders or {suffix} files...")
    show_hidden = st.checkbox("Show hidden files and folders", value=False,
                              key=f"{context}_show_hidden")
    try:
        folders, files = directory_entries(directory, suffix, query, show_hidden)
    except OSError as error:
        st.error(f"Cannot open this folder: {error}")
        return

    st.caption(f"{len(folders)} folders · {len(files)} {suffix} files")
    if not folders and not files:
        st.info(f"No matching folders or {suffix} files. Try another folder or clear the filter.")
        return

    # Show a manageable number of entries even in very large research datasets.
    entries: list[tuple[Path, bool]] = [(p, True) for p in folders] + [(p, False) for p in files]
    page_size = 40
    pages = (len(entries) + page_size - 1) // page_size
    st.session_state[page_key] = min(st.session_state.get(page_key, 0), pages - 1)
    if pages > 1:
        # Page-widget identity follows the folder/filter so previous-page state
        # cannot point outside the new directory's range.
        page_identity = hashlib.sha256(f"{directory}|{query}".encode()).hexdigest()[:12]
        current = st.selectbox("File browser page", options=range(1, pages + 1),
                               index=st.session_state[page_key],
                               key=f"{context}_page_{page_identity}")
        st.session_state[page_key] = int(current) - 1

    shown = entries[st.session_state[page_key] * page_size:
                    (st.session_state[page_key] + 1) * page_size]
    with st.container(height=410, border=True):
        for index, (path, is_folder) in enumerate(shown):
            icon = "📁" if is_folder else "🎞️" if suffix == ".mp4" else "📄"
            if st.button(f"{icon}  {path.name}{'/' if is_folder else ''}",
                         use_container_width=True, key=f"{context}_entry_{index}_{path}"):
                if is_folder:
                    st.session_state[directory_key] = str(path.resolve())
                    st.session_state[page_key] = 0
                    st.session_state[reset_filter_key] = True
                    st.rerun(scope="fragment")
                else:
                    st.session_state[destination_key] = str(path.resolve())
                    st.rerun()
