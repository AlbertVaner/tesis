"""Captura reutilizable de ventanas Tkinter en PDF."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_DIR / "results" / "graphs" / "capturas_gui"


def _physical_window_bbox(root: Any) -> tuple[int, int, int, int]:
    """Obtiene el rectángulo físico de Windows, incluyendo escala DPI."""
    try:
        import ctypes
        from ctypes import wintypes

        # Tk puede devolver el HWND del área cliente. GetAncestor(GA_ROOT)
        # obtiene la ventana nativa completa, incluida su barra de título.
        hwnd = root.winfo_id()
        native_root = ctypes.windll.user32.GetAncestor(hwnd, 2) or hwnd
        rectangle = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(native_root, ctypes.byref(rectangle)):
            raise OSError("GetWindowRect falló")
        return rectangle.left, rectangle.top, rectangle.right, rectangle.bottom
    except Exception:
        left = root.winfo_rootx()
        top = root.winfo_rooty()
        return left, top, left + root.winfo_width(), top + root.winfo_height()


def install_gui_pdf_capture(
    root: Any,
    prefix: str,
    *,
    min_width: int = 0,
    min_height: int = 0,
) -> None:
    """Añade botón, Ctrl+P y método ``save_gui_pdf`` a una ventana Tk."""
    safe_prefix = "".join(character if character.isalnum() or character in "-_" else "_" for character in prefix)

    def save_gui_pdf(*, silent: bool = False, once: bool = False) -> Path | None:
        if once and getattr(root, "_gui_pdf_auto_saved", False):
            return None
        try:
            from PIL import ImageGrab

            root.update_idletasks()
            original_geometry = root.geometry()
            original_state = root.state()
            # En Windows, Tk y ImageGrab pueden usar escalas DPI distintas.
            # Maximizar y capturar el monitor completo evita cualquier recorte
            # por coordenadas lógicas/físicas. La ventana se restaura después.
            if original_state != "zoomed":
                root.state("zoomed")
            root.lift()
            root.update()
            try:
                image = ImageGrab.grab(all_screens=False).convert("RGB")
            finally:
                if original_state != "zoomed":
                    root.state("normal")
                    root.geometry(original_geometry)
                    root.update_idletasks()
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            path = OUTPUT_DIR / f"{safe_prefix}_{stamp}.pdf"
            image.save(path, "PDF", resolution=150.0)
            if once:
                root._gui_pdf_auto_saved = True
            if not silent:
                messagebox.showinfo("GUI guardada", f"Captura PDF guardada en:\n{path.resolve()}", parent=root)
            return path
        except Exception as exc:
            if silent:
                print(f"No se pudo guardar automáticamente la GUI en PDF: {exc}")
            else:
                messagebox.showerror("Error guardando PDF", str(exc), parent=root)
            return None

    root.save_gui_pdf = save_gui_pdf
    button = ttk.Button(root, text="GUARDAR GUI PDF", command=save_gui_pdf)
    button.place(relx=1.0, x=-14, y=12, anchor="ne")
    button.lift()
    root.bind_all("<Control-p>", lambda _event: save_gui_pdf())
    root.bind_all("<Control-P>", lambda _event: save_gui_pdf())


def auto_save_gui_pdf(root: Any) -> None:
    save = getattr(root, "save_gui_pdf", None)
    if callable(save):
        save(silent=True, once=True)


def save_cv_frame_pdf(frame: Any, prefix: str) -> Path:
    """Guarda un frame BGR de OpenCV como PDF."""
    from PIL import Image

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    path = OUTPUT_DIR / f"{prefix}_{stamp}.pdf"
    image = Image.fromarray(frame[:, :, ::-1]).convert("RGB")
    image.save(path, "PDF", resolution=150.0)
    return path
