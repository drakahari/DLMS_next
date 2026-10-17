"""Bounded caller drives one owned native COM dialog; no backend/browser/input."""
import argparse
import json
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--events', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(mode=0o700, exist_ok=False)
    def stage(value):
        with (args.output / 'stages.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'stage': value, 'monotonic': time.monotonic()})+'\n')
        print(value, flush=True)
    from desktop.windows_processes import own_launcher
    own_launcher()
    from PySide6.QtWidgets import QApplication, QMainWindow
    from desktop.windows_backup_chooser import NativeSaveDialog, choose
    from tests.webview2.gui_backup_followup import cancel_dialog_class
    app = QApplication([])
    owner = QMainWindow(); owner.resize(640, 480); owner.show(); app.processEvents()
    folders = (args.output / 'Synthetic Documents', args.output / 'Synthetic Downloads 日本語')
    for folder in folders: folder.mkdir(mode=0o700)
    observation = {}
    stage('before-choose')
    try:
        if args.events:
            from tests.webview2.native_dialog_events import CancelEvents
            with NativeSaveDialog() as dialog:
                dialog.configure('synthetic backup.zip', folders)
                with CancelEvents(dialog, stage) as sink:
                    stage('native-event-show-enter')
                    result = (dialog.show(int(owner.winId())), '')
                    stage('native-event-show-return')
                    assert sink.fired and not sink.errors
                    observation['native_dialog_event_cancelled'] = True
        else:
            result = choose(owner, 'synthetic backup.zip', folders,
                            factory=cancel_dialog_class(NativeSaveDialog, observation, stage))
        assert result == ('', '')
        stage('choose-cancel-returned')
        with (args.output / 'result.json').open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(observation | {'result': result, 'passed': True}, indent=2)+'\n')
    finally:
        owner.close(); app.processEvents()


if __name__ == '__main__':
    main()
