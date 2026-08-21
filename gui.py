"""
Interface de sélection des filtres AInonymizer (tkinter stdlib).
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk
from pathlib import Path

# (id_catégorie, libellé affiché, activé par défaut)
_CATEGORIES: list[tuple[str, str, bool]] = [
    ("PERSONNE",        "Personnes physiques",        True),
    ("PERSONNE_MORALE", "Personnes morales",          True),
    ("AVOCAT",          "Avocats",                    False),
    ("MAGISTRAT",       "Magistrats",                 False),
    ("JURIDICTION",     "Juridictions",               True),
    ("EMAIL",           "Emails",                     True),
    ("TEL",             "Téléphones",                 True),
    ("ADRESSE",         "Adresses",                   True),
    ("LIEU",            "Lieux",                      True),
    ("NIR",             "NIR (n° sécurité sociale)",  True),
    ("IBAN",            "IBAN",                       True),
    ("SIREN",           "SIREN / SIRET",              True),
    ("PLAQUE",          "Plaques d'immatriculation",  True),
    ("NUM_DOSSIER",     "Numéros de dossier",         True),
    ("DATE",            "Dates procédurales",         True),
    ("DATE_NAISSANCE",  "Dates de naissance / décès", True),
]

_DISABLED_NOTE = "(désactivé par défaut — délibération CNIL 01-057)"


def launch_gui(doc_count: int) -> frozenset[str]:
    """
    Affiche la fenêtre de sélection.
    Retourne l'ensemble des catégories désactivées par l'utilisateur.
    Appelle sys.exit(0) si l'utilisateur ferme ou annule.
    """
    root = tk.Tk()
    root.title("AInonymizer")
    root.resizable(False, False)

    pad = {"padx": 20}

    # ── Titre ────────────────────────────────────────────────────────────
    ttk.Label(root, text="AInonymizer", font=("Segoe UI", 13, "bold")).pack(
        pady=(18, 2), **pad
    )

    doc_text = (
        f"{doc_count} fichier(s) trouvé(s) dans input/"
        if doc_count
        else "Aucun fichier trouvé dans input/"
    )
    ttk.Label(root, text=doc_text, foreground="#666").pack(pady=(0, 10), **pad)
    ttk.Separator(root).pack(fill="x", padx=20)

    # ── En-tête cases à cocher ────────────────────────────────────────────
    ttk.Label(
        root, text="Catégories à anonymiser :", font=("Segoe UI", 9, "bold")
    ).pack(anchor="w", pady=(10, 4), **pad)

    # ── Grille de cases à cocher (2 colonnes) ────────────────────────────
    grid = ttk.Frame(root)
    grid.pack(anchor="w", **pad, pady=(0, 8))

    mid = (len(_CATEGORIES) + 1) // 2
    left_col  = _CATEGORIES[:mid]
    right_col = _CATEGORIES[mid:]

    vars_: dict[str, tk.BooleanVar] = {}

    for col_index, column in enumerate((left_col, right_col)):
        for row_index, (cat_id, label, default) in enumerate(column):
            var = tk.BooleanVar(value=default)
            vars_[cat_id] = var
            display = label
            if not default:
                display += f"  {_DISABLED_NOTE}"
            cb = ttk.Checkbutton(grid, text=display, variable=var)
            cb.grid(row=row_index, column=col_index, sticky="w",
                    padx=(0, 32) if col_index == 0 else 0, pady=1)

    # ── Boutons tout/rien ─────────────────────────────────────────────────
    ttk.Separator(root).pack(fill="x", padx=20, pady=(4, 0))

    def select_all():
        for v in vars_.values():
            v.set(True)

    def deselect_all():
        for v in vars_.values():
            v.set(False)

    quick_frame = ttk.Frame(root)
    quick_frame.pack(pady=(6, 0))
    ttk.Button(quick_frame, text="Tout cocher",   command=select_all).pack(side="left", padx=4)
    ttk.Button(quick_frame, text="Tout décocher", command=deselect_all).pack(side="left", padx=4)

    # ── Boutons Lancer / Annuler ──────────────────────────────────────────
    result: list[frozenset[str]] = []

    def on_launch():
        disabled = frozenset(cat for cat, _, _ in _CATEGORIES if not vars_[cat].get())
        result.append(disabled)
        root.destroy()

    def on_cancel():
        root.destroy()
        sys.exit(0)

    root.protocol("WM_DELETE_WINDOW", on_cancel)

    action_frame = ttk.Frame(root)
    action_frame.pack(pady=(10, 18))

    launch_btn = ttk.Button(action_frame, text="  Lancer  ", command=on_launch)
    launch_btn.pack(side="left", padx=8)
    ttk.Button(action_frame, text="Annuler", command=on_cancel).pack(side="left", padx=8)

    # ── Centrage écran ────────────────────────────────────────────────────
    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    x = (root.winfo_screenwidth()  - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"+{x}+{y}")

    root.mainloop()

    return result[0] if result else frozenset()
