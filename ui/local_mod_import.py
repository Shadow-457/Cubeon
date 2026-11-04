"""Review a local mod batch before writing to its captured instance."""
import logging
import threading

import flet as ft

from cubeon import dialogs, local_mods, theme, thread_safe_ui


class LocalModImport:
    def __init__(self, page, review, *, instance_label, finished, closed):
        self.page, self.review = page, review
        self.finished, self.closed = finished, closed
        self.phase = 'review'
        self.choices = []
        rows = []
        for entry in review['entries']:
            usable = entry['status'] in ('ready', 'replace')
            checkbox = ft.Checkbox(value=entry['status'] == 'ready', disabled=not usable,
                                   on_change=self._selection_changed)
            self.choices.append((entry, checkbox))
            detail = ft.Text(entry['detail'], size=12, color=theme.DANGER if entry['status'] == 'blocked' else theme.TEXT_DIM,
                             selectable=True)
            texts = [ft.Text(f"{entry['name']} {entry.get('version', '')}".strip(), size=14,
                             color=theme.TEXT, weight=ft.FontWeight.W_600),
                     ft.Text(entry['filename'], size=11, color=theme.TEXT_DIM, selectable=True), detail]
            warning = ft.Text('\n'.join(entry.get('warnings', [])), size=12, color=theme.DANGER,
                              selectable=True, visible=bool(entry.get('warnings')))
            texts.append(warning)
            entry['_warning_text'] = warning
            rows.append(ft.Container(content=ft.Row([checkbox, ft.Column(texts, spacing=3, expand=True)],
                                                    vertical_alignment=ft.CrossAxisAlignment.START),
                                     bgcolor=theme.SURFACE_HI, padding=10, border_radius=theme.RADIUS))
            entry['_result_text'] = detail
        self.status = ft.Text('Select the mods to import. Replacements keep the previous files disabled.',
                              size=12, color=theme.TEXT_DIM)
        self.progress = ft.ProgressBar(value=0, visible=False, color=theme.ACCENT)
        self.cancel = ft.TextButton('Cancel', on_click=self._close, data='local-import-cancel')
        self.submit = ft.FilledButton('Import', on_click=self._import, data='local-import-submit')
        self.dialog = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE, shape=theme.block(),
            title=ft.Text('Import local mods', size=22, color=theme.TEXT),
            content=ft.Container(width=600, content=ft.Column([
                ft.Text(f"{instance_label} · Minecraft {review['mc_version']} · {review['loader'].title()}",
                        size=13, color=theme.TEXT, selectable=True),
                ft.ListView(controls=rows, spacing=8, height=320), self.status, self.progress,
            ], spacing=12, tight=True)),
            actions=[self.cancel, self.submit], on_dismiss=self._close,
        )
        self._selection_changed()

    def open(self):
        with thread_safe_ui.TREE_LOCK:
            dialogs.open_dialog(self.page, self.dialog)
        return self

    def _selected(self):
        return [entry for entry, control in self.choices
                if control.value and not control.disabled]

    def _selection_changed(self, _event=None):
        with thread_safe_ui.TREE_LOCK:
            selected = self._selected()
            count = len(selected)
            self.submit.content = f'Import {count} mod' + ('' if count == 1 else 's')
            self.submit.disabled = not count
            warnings = local_mods.selection_warnings(self.review, selected)
            for entry, checkbox in self.choices:
                label = entry['_warning_text']
                label.value = '\n'.join(warnings.get(entry['path'], []))
                label.visible = bool(label.value)
                thread_safe_ui.refresh(label)
            thread_safe_ui.refresh(self.submit)

    def _close(self, _event=None):
        with thread_safe_ui.TREE_LOCK:
            if self.phase in ('importing', 'closed'):
                return
            self.phase = 'closed'
            dialogs.close_dialog(self.page, self.dialog)
            self.closed()

    def _progress(self, done, total, name):
        with thread_safe_ui.TREE_LOCK:
            self.progress.value = done / max(total, 1)
            self.status.value = f'Importing {done + 1}/{total}: {name}'
            thread_safe_ui.refresh(self.dialog)

    def _import(self, _event=None):
        with thread_safe_ui.TREE_LOCK:
            if self.phase != 'review':
                return
            selected = self._selected()
            if not selected:
                return
            self.phase = 'importing'
            self.submit.disabled = self.cancel.disabled = True
            for entry, checkbox in self.choices:
                checkbox.disabled = True
            self.progress.visible = True
            thread_safe_ui.refresh(self.dialog)

        def worker():
            try:
                results = local_mods.import_review(self.review, selected, replace=True, progress=self._progress)
                self.finished(results)
            except Exception as error:
                logging.getLogger(__name__).exception('Local mod import failed')
                results = [{'status': 'failed', 'detail': str(error)} for entry in selected]
            with thread_safe_ui.TREE_LOCK:
                for entry, result in zip(selected, results):
                    label = entry['_result_text']
                    label.value = ('Imported' + (f"; kept {len(result.get('replaced', []))} previous build(s) disabled"
                                                if result.get('replaced') else '')
                                   if result['status'] == 'imported' else result.get('detail', 'Skipped'))
                    label.color = theme.DANGER if result['status'] == 'failed' else theme.TEXT_DIM
                self.phase = 'done'
                imported = sum(result['status'] == 'imported' for result in results)
                failed = sum(result['status'] == 'failed' for result in results)
                self.status.value = f'{imported} imported · {len(results) - imported - failed} already installed · {failed} failed'
                self.progress.value = 1
                self.cancel.content, self.cancel.disabled = 'Done', False
                self.submit.visible = False
                thread_safe_ui.refresh(self.dialog)
        try:
            threading.Thread(target=worker, daemon=True, name='cubeon-local-mod-import').start()
        except Exception:
            with thread_safe_ui.TREE_LOCK:
                self.phase = 'review'
                self.cancel.disabled = False
                self.progress.visible = False
                for entry, checkbox in self.choices:
                    checkbox.disabled = entry['status'] not in ('ready', 'replace')
                self.status.value = "Couldn't start importing. Try again."
                self._selection_changed()
                thread_safe_ui.refresh(self.dialog)
