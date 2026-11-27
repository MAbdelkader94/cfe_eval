"""
report.py - where the analysis notebooks put their figures and tables.

Everything a notebook produces goes to

    results/report/<analysis>/<type of analysis>/

for example results/report/02_long_term_series/maps/map_KGE.png. Next to a
figure, <name>_data.csv holds the numbers behind it. figure_list.csv in the
analysis folder lists every figure and table with its caption, in the order of
the notebook, and <analysis>.zip packs the whole folder for download.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from . import config as cfg


class Report:
    def __init__(self, analysis: str, formats=("png",), save: bool = True):
        """analysis: folder name under results/report. formats: figure formats,
        for example ("png", "pdf"). save=False draws everything but writes nothing."""
        self.root = cfg.REPORT / analysis
        self.analysis, self.formats, self.on = analysis, tuple(formats), save
        self.items: list[dict] = []
        if save:
            self.root.mkdir(parents=True, exist_ok=True)

    def folder(self, name: str) -> Path:
        p = self.root / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _add(self, kind, folder, file, caption, data_file=""):
        self.items = [i for i in self.items if not (i["folder"] == folder and i["file"] == file)]
        self.items.append({"kind": kind, "folder": folder, "file": file, "data_file": data_file,
                           "caption": " ".join(caption.split())})
        idx = pd.DataFrame(self.items)
        idx.insert(0, "order", range(1, len(idx) + 1))
        idx.to_csv(self.root / "figure_list.csv", index=False)

    def figure(self, fig, folder: str, name: str, caption: str, data: pd.DataFrame | None = None):
        """Save fig as <folder>/<name>.<format> and the numbers behind it as <name>_data.csv.
        data defaults to the table the plotting function attached to the figure (fig.cfe_data)."""
        if not self.on:
            return fig
        d = self.folder(folder)
        for ext in self.formats:
            fig.savefig(d / f"{name}.{ext}")
        data = data if data is not None else getattr(fig, "cfe_data", None)
        data_file = ""
        if data is not None:
            data_file = f"{name}_data.csv"
            keep_index = not isinstance(data.index, pd.RangeIndex)
            data.to_csv(d / data_file, index=keep_index)
        self._add("figure", folder, f"{name}.{self.formats[0]}", caption, data_file)
        return fig

    def table(self, df: pd.DataFrame, folder: str, name: str, caption: str, index: bool = True):
        """Save df as <folder>/<name>.csv and return it, so it still shows in the notebook."""
        if self.on:
            df.to_csv(self.folder(folder) / f"{name}.csv", index=index)
            self._add("table", folder, f"{name}.csv", caption)
        return df

    def finish(self, make_zip: bool = True):
        """Print what was written, folder by folder, and pack the analysis folder into a zip file."""
        if not self.on:
            print("nothing saved (save=False)")
            return
        idx = pd.DataFrame(self.items)
        print(f"{self.root}")
        for folder, g in idx.groupby("folder", sort=False):
            print(f"  {folder + '/':42s} {int((g['kind'] == 'figure').sum()):3d} figures  "
                  f"{int((g['kind'] == 'table').sum()):3d} tables")
        print(f"  total: {int((idx['kind'] == 'figure').sum())} figures, {int((idx['kind'] == 'table').sum())} tables")
        print("  list with captions: figure_list.csv")
        if make_zip:
            z = shutil.make_archive(str(cfg.REPORT / self.analysis), "zip", root_dir=cfg.REPORT, base_dir=self.analysis)
            print(f"  packed for download: {z}")
