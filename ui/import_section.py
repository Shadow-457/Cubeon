"""Settings → Import: import an installed FastClient instance locally."""
import flet as ft

from ui.instance_import import FastClientImport


def build_import_section(page, cfg, *, section_label, on_instance_imported=None,
                         instance_import_busy=None, **_theme):
    fastclient = FastClientImport(page, finished=on_instance_imported or (lambda _result: None),
                                 busy_reason=instance_import_busy or (lambda: None))
    pane = ft.Column([section_label("Import"), fastclient.view], spacing=8, visible=False,
                     horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    pane.fastclient_import = fastclient
    return pane
