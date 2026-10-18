"""Run tests/scripts_runner.py on a job, optionally with patches off. usage: run_job.py JOB.json [off|nogc]"""
import os
import runpy
import sys

mode = sys.argv[2] if len(sys.argv) > 2 else "on"
sys.argv = [sys.argv[0], sys.argv[1]]
from obsidian_pdf_exporter.compat import weasyprint_patches as wp
if mode == "nogc":
    wp.PATCHES = tuple(p for p in wp.PATCHES if p.wrap is not wp.pause_garbage_collection)
import obsidian_pdf_exporter.core.exporter as ex
orig = wp.apply_weasyprint_patches
if mode == "off":
    ex.apply_weasyprint_patches = lambda options=None: orig({"weasyprint.patches": "off"})
runpy.run_path(os.environ["RUNNER"], run_name="__main__")
